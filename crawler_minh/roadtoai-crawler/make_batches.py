from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import polars as pl

from common import _HOST_RE, domain_of_host, utf8_console


def load_corpus(path: Path) -> pl.DataFrame:
    df = pl.read_parquet(path, columns=["id", "url"])
    n = df.height
    null_ids = df["id"].null_count()
    null_urls = df["url"].null_count()
    dup_ids = n - df["id"].n_unique()
    dup_urls = n - df["url"].n_unique()
    print(f"corpus: {n:,} rows | null id: {null_ids} | null url: {null_urls} | duplicate id: {dup_ids} | duplicate url: {dup_urls}")
    if null_ids or dup_ids:
        sys.exit("id column has nulls or duplicates; fix the corpus file before splitting")
    return df.filter(pl.col("url").is_not_null()).sort("id")


def add_domains(df: pl.DataFrame) -> pl.DataFrame:
    url = pl.col("url").str.strip_chars()
    df = df.with_columns(
        url.str.extract(_HOST_RE, 1).str.to_lowercase().str.replace(r"^www\.", "").alias("_h"),
        url.str.extract(_HOST_RE, 2).alias("_p"),
    ).with_columns(
        pl.when(pl.col("_p").is_not_null() & ~pl.col("_p").is_in(["80", "443"]))
        .then(pl.concat_str([pl.col("_h"), pl.lit(":"), pl.col("_p")]))
        .otherwise(pl.col("_h"))
        .fill_null("")
        .alias("host")
    ).drop("_h", "_p")
    hosts = df.select("host").unique()
    mapping = hosts.with_columns(
        pl.col("host").map_elements(domain_of_host, return_dtype=pl.String).alias("domain")
    )
    return df.join(mapping, on="host", how="left")


def boundaries(domains: np.ndarray, size: int, window: int) -> list[int]:
    n = len(domains)
    nominal = list(range(size, n, size))
    if window <= 0 or not nominal:
        return [0] + nominal + [n]
    change = np.flatnonzero(domains[1:] != domains[:-1]) + 1
    result = [0]
    for b in nominal:
        pos = np.searchsorted(change, b)
        best = b
        cands = [change[i] for i in (pos - 1, pos) if 0 <= i < len(change)]
        cands = [c for c in cands if abs(c - b) <= window and c > result[-1]]
        if cands:
            best = int(min(cands, key=lambda c: abs(c - b)))
        if best > result[-1]:
            result.append(best)
    result.append(n)
    return result


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(description="Split links_corpus.parquet into non-overlapping batches of ids.")
    ap.add_argument("--corpus", default="data/links_corpus.parquet")
    ap.add_argument("--out", default="batches")
    ap.add_argument("--batch-size", type=int, default=500_000)
    ap.add_argument("--people", default="", help="comma separated names; batches are assigned round-robin")
    ap.add_argument("--align-domains", type=int, default=0,
                    help="move each cut to the nearest change of domain within this many rows (0 keeps exact sizes)")
    ap.add_argument("--max-batches", type=int, default=0,
                    help="only write the first N batches, e.g. 3 = the first 1.5M ids (0 = all)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    df = add_domains(load_corpus(Path(args.corpus)))
    cuts = boundaries(df["domain"].to_numpy(), args.batch_size, args.align_domains)
    batch_ids = np.zeros(df.height, dtype=np.int32)
    for k in range(len(cuts) - 1):
        batch_ids[cuts[k]:cuts[k + 1]] = k
    df = df.with_columns(pl.Series("batch", batch_ids))
    total_batches = len(cuts) - 1
    n_batches = total_batches if args.max_batches <= 0 else min(args.max_batches, total_batches)
    if n_batches < total_batches:
        df = df.filter(pl.col("batch") < n_batches)
        print(f"keeping the first {n_batches} of {total_batches} batches: {df.height:,} ids "
              f"(id {df['id'].min()} to {df['id'].max()})")
    for stale in out.glob("batch_*.parquet"):
        if int(stale.stem.split("_")[1]) >= n_batches:
            stale.unlink()
            print(f"removed old {stale.name}")

    people = [p.strip() for p in args.people.split(",") if p.strip()]

    manifest_rows = []
    for k in range(n_batches):
        part = df.filter(pl.col("batch") == k)
        part.select("id", "url", "host", "domain").write_parquet(out / f"batch_{k:02d}.parquet", compression="zstd")
        top = part.group_by("domain").len().sort("len", descending=True).head(5)
        manifest_rows.append({
            "batch": k,
            "person": people[k % len(people)] if people else "",
            "rows": part.height,
            "id_min": int(part["id"].min()),
            "id_max": int(part["id"].max()),
            "domains": part["domain"].n_unique(),
            "top_domains": "; ".join(f"{d}:{c}" for d, c in top.iter_rows()),
        })

    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)

    dom = (
        df.group_by("domain")
        .agg(pl.len().alias("urls"), pl.col("batch").unique().sort().alias("batches"))
        .with_columns(
            (pl.col("urls") / df.height * 100).round(3).alias("share_pct"),
            (pl.col("urls") / 86_400).round(2).alias("days_at_1_req_per_s"),
            pl.col("batches").list.len().alias("n_batches"),
            pl.col("batches").cast(pl.List(pl.String)).list.join(" ").alias("batches"),
        )
        .sort("urls", descending=True)
    )
    dom.write_csv(out / "domains.csv")

    print(f"\n{n_batches} batches written to {out}/")
    print(f"{'batch':>5} {'person':>10} {'rows':>9} {'id_min':>10} {'id_max':>10} {'domains':>8}  top domains")
    for r in manifest_rows:
        print(f"{r['batch']:>5} {r['person']:>10} {r['rows']:>9,} {r['id_min']:>10} {r['id_max']:>10} {r['domains']:>8}  {r['top_domains'][:70]}")

    print(f"\n{dom.height:,} domains. Top 15 by URL count (days = time to crawl at 1 request/second):")
    for d, urls, share, days, nb in dom.select("domain", "urls", "share_pct", "days_at_1_req_per_s", "n_batches").head(15).iter_rows():
        print(f"  {d[:40]:<40} {urls:>9,}  {share:>6.2f}%  {days:>6.1f} days  in {nb} batch(es)")

    spanning = dom.filter(pl.col("n_batches") > 1)
    print(f"\n{spanning.height:,} domains appear in more than one batch "
          f"({spanning['urls'].sum() if spanning.height else 0:,} URLs). "
          "If two people crawl batches sharing a domain at the same time, that site gets requests from both.")
    for d, urls, b in spanning.select("domain", "urls", "batches").head(10).iter_rows():
        print(f"  {d[:40]:<40} {urls:>9,}  batches {b}")


if __name__ == "__main__":
    main()
