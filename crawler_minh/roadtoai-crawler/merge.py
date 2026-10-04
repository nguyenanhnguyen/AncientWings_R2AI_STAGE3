from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

from common import RETRYABLE, find_files, pick_winners, read_shard, scan_light, sha256_text, utf8_console
from quality import domain_quality, quality_lines

DOC_COLS = ["id", "url", "final_url", "domain", "title", "text", "lang", "n_chars", "extractor", "published_at",
            "text_sha256", "canonical_id", "dup_count", "batch", "worker", "fetched_at"]
STATUS_COLS = ["id", "url", "final_url", "domain", "status", "http_status", "content_type", "error",
               "n_chars", "lang", "extractor", "batch", "worker", "fetched_at"]
SHARD_COLS = ["id", "url", "final_url", "domain", "status", "http_status", "content_type", "title", "text", "lang",
              "n_chars", "error", "fetched_at", "worker", "batch", "extractor", "published_at", "text_sha256"]


class BufferedWriter:
    def __init__(self, path: Path, rows_per_group: int = 50_000):
        self.path = path
        self.rows_per_group = rows_per_group
        self.frames: list[pl.DataFrame] = []
        self.n = 0
        self.total = 0
        self.writer: pq.ParquetWriter | None = None

    def add(self, df: pl.DataFrame) -> None:
        if df.height == 0:
            return
        self.frames.append(df)
        self.n += df.height
        if self.n >= self.rows_per_group:
            self.flush()

    def flush(self) -> None:
        if not self.frames:
            return
        table = pl.concat(self.frames, how="vertical_relaxed").to_arrow()
        if self.writer is None:
            self.writer = pq.ParquetWriter(self.path, table.schema, compression="zstd")
        else:
            table = table.cast(self.writer.schema)
        self.writer.write_table(table)
        self.total += table.num_rows
        self.frames, self.n = [], 0

    def close(self) -> None:
        self.flush()
        if self.writer is not None:
            self.writer.close()


def content_keys() -> tuple:
    text = pl.col("text")
    try:
        text = text.str.normalize("NFKC")
    except AttributeError:
        pass
    norm = text.str.to_lowercase().str.replace_all(r"\s+", " ").str.strip_chars()
    return norm.hash(seed=11).alias("k1"), norm.hash(seed=47).alias("k2")


def find_duplicates(winners: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    ok = winners.filter(pl.col("status") == "ok").select("id", "domain", "k1", "k2")
    groups = (
        ok.group_by("k1", "k2")
        .agg(pl.col("id").min().alias("canonical_id"), pl.len().cast(pl.Int32).alias("dup_count"),
             pl.col("id").sort().alias("doc_ids"), pl.col("domain").unique().sort().alias("domains"))
    )
    per_id = ok.join(groups.select("k1", "k2", "canonical_id", "dup_count"), on=["k1", "k2"], how="left").select(
        "id", pl.col("canonical_id").fill_null(pl.col("id")), pl.col("dup_count").fill_null(1))
    multi = groups.filter(pl.col("dup_count") > 1).select("canonical_id", pl.col("dup_count").alias("size"),
                                                           "doc_ids", "domains")
    return per_id, multi


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(description="Merge crawl shards from all machines, keep the best result per id.")
    ap.add_argument("--inputs", nargs="+", default=["crawl_out"], help="folders or parquet files from every person")
    ap.add_argument("--out", default="merged")
    ap.add_argument("--batches-dir", default="batches", help="to report ids never attempted (skipped if missing)")
    ap.add_argument("--with-html", action="store_true", help="also copy the html column into docs.parquet")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("retry_ids_b*.txt")) + list(out.glob("missing_ids_b*.txt")):
        old.unlink()
    files = find_files(args.inputs)
    if not files:
        raise SystemExit("no parquet files found")
    print(f"{len(files):,} shard files")

    light = scan_light(files, ["id", "status", "fetched_at", "batch", "domain"], content_keys())
    winners = pick_winners(light)
    print(f"{light.height:,} rows -> {winners.height:,} unique ids")
    dup_per_id, dup_groups = find_duplicates(winners)

    docs = BufferedWriter(out / "docs.parquet")
    status = BufferedWriter(out / "status.parquet")
    doc_cols = DOC_COLS + (["html"] if args.with_html else [])
    shard_cols = SHARD_COLS + (["html"] if args.with_html else [])
    previews: dict[int, tuple] = {}
    for file, ids in winners.group_by("file").agg("id").iter_rows():
        part = read_shard(file, shard_cols).filter(pl.col("id").is_in(ids)).unique("id", keep="last")
        part = part.with_columns(pl.col("extractor").fill_null(""), pl.col("published_at").fill_null(""))
        ok = part.filter(pl.col("status") == "ok").join(dup_per_id, on="id", how="left")
        if ok.height:
            need_hash = ok["text_sha256"].is_null() | (ok["text_sha256"] == "")
            if need_hash.any():
                hashes = [sha256_text(t) if miss else h
                          for t, h, miss in zip(ok["text"].to_list(), ok["text_sha256"].to_list(), need_hash.to_list())]
                ok = ok.with_columns(pl.Series("text_sha256", hashes, dtype=pl.String))
            heads = ok.filter((pl.col("id") == pl.col("canonical_id")) & (pl.col("dup_count") > 1))
            for cid, url, n_chars, text in heads.select("id", "final_url", "n_chars",
                                                        pl.col("text").str.slice(0, 120)).iter_rows():
                previews[cid] = (url, n_chars, " ".join(text.split()))
            docs.add(ok.select(doc_cols))
        status.add(part.select(STATUS_COLS))
    docs.close()
    status.close()

    dup_path = out / "duplicates.parquet"
    if dup_groups.height:
        meta = pl.DataFrame(
            [(cid, *previews.get(cid, ("", 0, ""))) for cid in dup_groups["canonical_id"].to_list()],
            schema={"canonical_id": pl.Int64, "final_url": pl.String, "n_chars": pl.Int64, "preview": pl.String},
            orient="row",
        )
        dup_groups = dup_groups.join(meta, on="canonical_id", how="left").sort(["size", "canonical_id"],
                                                                              descending=[True, False])
        dup_groups.write_parquet(dup_path, compression="zstd")
    elif dup_path.exists():
        dup_path.unlink()

    lines: list[str] = []
    say = lines.append
    n = winners.height
    say(f"unique ids attempted: {n:,} | docs with text (status ok): {docs.total:,} ({100 * docs.total / max(1, n):.1f}%)")
    say("\nstatus breakdown:")
    for s, c in winners.group_by("status").len().sort("len", descending=True).iter_rows():
        flag = "  (retryable)" if s in RETRYABLE else ""
        say(f"  {s:<20} {c:>10,}  {100 * c / n:5.1f}%{flag}")

    expected: dict[int, pl.Series] = {}
    bdir = Path(args.batches_dir)
    if bdir.is_dir():
        for f in sorted(bdir.glob("batch_*.parquet")):
            expected[int(f.stem.split("_")[1])] = pl.read_parquet(f, columns=["id"])["id"]

    say("\nper batch:")
    say(f"  {'batch':>5} {'expected':>9} {'attempted':>9} {'ok':>9} {'ok%':>6} {'retry':>8} {'missing':>8}")
    batches = sorted(set(winners["batch"].unique().to_list()) | set(expected))
    for b in batches:
        wb = winners.filter(pl.col("batch") == b)
        ok_n = wb.filter(pl.col("status") == "ok").height
        retry_ids = wb.filter(pl.col("status").is_in(sorted(RETRYABLE)))["id"]
        if retry_ids.len():
            (out / f"retry_ids_b{b:02d}.txt").write_text("\n".join(map(str, retry_ids.to_list())) + "\n", encoding="utf-8")
        missing = 0
        if b in expected:
            miss = pl.DataFrame({"id": expected[b]}).join(winners.select("id"), on="id", how="anti")["id"]
            missing = miss.len()
            if missing:
                (out / f"missing_ids_b{b:02d}.txt").write_text("\n".join(map(str, miss.to_list())) + "\n", encoding="utf-8")
        exp = expected[b].len() if b in expected else 0
        say(f"  {b:>5} {exp:>9,} {wb.height:>9,} {ok_n:>9,} {100 * ok_n / max(1, wb.height):5.1f}% "
            f"{retry_ids.len():>8,} {missing:>8,}")

    if docs.total:
        summary = pl.scan_parquet(out / "docs.parquet").select("lang", "extractor").collect()
        say("\nlanguage of docs (rough guess from text):")
        for lang, c in summary.group_by("lang").len().sort("len", descending=True).iter_rows():
            say(f"  {lang or '?':<12} {c:>10,}  {100 * c / docs.total:5.1f}%")
        say("\ntext extracted by:")
        for ex, c in summary.group_by("extractor").len().sort("len", descending=True).iter_rows():
            say(f"  {ex or '(not recorded)':<16} {c:>10,}  {100 * c / docs.total:5.1f}%")

        copies = int(dup_groups["size"].sum()) - dup_groups.height if dup_groups.height else 0
        say("\nduplicate content (same text after ignoring case and spacing):")
        say(f"  {docs.total:,} docs -> {docs.total - copies:,} distinct texts | {dup_groups.height:,} groups, "
            f"{copies:,} docs are copies of another doc")
        if dup_groups.height:
            say("  largest groups (many identical pages on one site are usually error or placeholder pages):")
            for cid, size, _ids, domains, url, n_chars, preview in dup_groups.head(10).iter_rows():
                say(f"    {size:>7,} docs  {', '.join(domains)[:40]:<40}  {n_chars or 0:>6,} chars  id {cid}  \"{(preview or '')[:60]}\"")

        flagged = quality_lines(domain_quality(out / "docs.parquet"), min_share=0.2)
        if flagged:
            say("\nsites where much of the text repeats across pages (menus, dialogs, link lists), from up to 300 pages each:")
            lines.extend(flagged)
            say("  these sites may need a site rule in extract.py; send a few of their pages for review")

    bad = winners.filter(pl.col("status") != "ok")
    if bad.height:
        say("\ndomains with most failures:")
        top = (
            bad.group_by("domain")
            .agg(pl.len().alias("n"), pl.col("status").mode().first().alias("main_status"))
            .sort("n", descending=True)
            .head(15)
        )
        for d, c, s in top.iter_rows():
            say(f"  {str(d)[:45]:<45} {c:>9,}  mostly {s}")

    say(f"\nwritten: {out / 'docs.parquet'}, {out / 'status.parquet'}, {out / 'duplicates.parquet'} (if any), "
        f"retry_ids_bXX.txt, missing_ids_bXX.txt")
    report = "\n".join(lines)
    print(report)
    (out / "report.txt").write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
