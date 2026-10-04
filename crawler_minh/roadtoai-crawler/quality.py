from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from common import utf8_console


def domain_quality(docs_path: str | Path, top: int = 40, sample: int = 300, min_docs: int = 10) -> pl.DataFrame:
    lf = pl.scan_parquet(str(docs_path))
    counts = (
        lf.group_by("domain")
        .agg(pl.len().alias("docs"), pl.col("n_chars").median().alias("median_chars"),
             (pl.col("n_chars") < 200).mean().alias("short_share"))
        .filter(pl.col("docs") >= min_docs)
        .sort("docs", descending=True)
        .head(top)
        .collect()
    )
    if counts.height == 0:
        return counts.with_columns(pl.lit(None, dtype=pl.Float64).alias("repeated_share"),
                                   pl.lit(None, dtype=pl.List(pl.String)).alias("examples"),
                                   pl.lit(None, dtype=pl.UInt32).alias("sampled"))
    picked = (
        lf.filter(pl.col("domain").is_in(counts["domain"].to_list()))
        .select("id", "domain", "text")
        .filter(pl.int_range(pl.len()).over("domain") < sample)
        .collect()
    )
    doms, ids, texts = [], [], []
    for doc_id, domain, text in picked.iter_rows():
        for line in (text or "").split("\n"):
            if line:
                doms.append(domain)
                ids.append(doc_id)
                texts.append(line)
    lines = pl.DataFrame({"domain": doms, "id": ids, "line": texts},
                         schema={"domain": pl.String, "id": pl.Int64, "line": pl.String})
    lines = lines.with_columns(pl.col("line").str.len_chars().alias("chars"))
    sizes = picked.group_by("domain").agg(pl.len().alias("sampled"))
    per_line = lines.group_by("domain", "line").agg(pl.col("id").n_unique().alias("pages"), pl.col("chars").first())
    per_line = per_line.join(sizes, on="domain").with_columns(
        (pl.col("pages") >= pl.max_horizontal(pl.lit(5), (pl.col("sampled") * 0.2).ceil())).alias("repeated"))
    flagged = lines.join(per_line.select("domain", "line", "repeated", "pages"), on=["domain", "line"])
    share = flagged.group_by("domain").agg(
        (pl.col("chars").filter(pl.col("repeated")).sum() / pl.col("chars").sum()).alias("repeated_share"))
    examples = (
        per_line.filter(pl.col("repeated"))
        .with_columns((pl.col("pages") * pl.col("chars")).alias("weight"))
        .sort("weight", descending=True)
        .group_by("domain", maintain_order=True)
        .agg(pl.col("line").str.slice(0, 40).head(3).alias("examples"))
    )
    return (
        counts.join(sizes, on="domain", how="left").join(share, on="domain", how="left")
        .join(examples, on="domain", how="left")
        .with_columns(pl.col("repeated_share").fill_null(0.0))
        .sort("docs", descending=True)
    )


def quality_lines(table: pl.DataFrame, min_share: float = 0.0) -> list[str]:
    out = []
    for r in table.filter(pl.col("repeated_share") >= min_share).iter_rows(named=True):
        ex = "; ".join(f'"{e}"' for e in (r["examples"] or []))
        out.append(f"  {r['domain'][:32]:<32} {r['docs']:>9,} docs  median {int(r['median_chars'] or 0):>6,} chars  "
                   f"short {100 * (r['short_share'] or 0):>3.0f}%  repeated {100 * r['repeated_share']:>3.0f}%  {ex}")
    return out


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(
        description="Per-site text quality: how much of the extracted text is made of lines repeated across pages "
                    "(menus, dialogs, link lists). Sites with a high share probably need a site rule in extract.py.")
    ap.add_argument("--docs", default="merged/docs.parquet")
    ap.add_argument("--top", type=int, default=40, help="number of largest sites to check")
    ap.add_argument("--sample", type=int, default=300, help="pages sampled per site")
    args = ap.parse_args()
    table = domain_quality(args.docs, args.top, args.sample)
    print("site, docs, median length, share of pages under 200 chars, share of text repeated across pages, examples")
    print("\n".join(quality_lines(table)) or "  no site has enough pages yet")


if __name__ == "__main__":
    main()
