from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import polars as pl

from common import read_shard, utf8_console
from export_json import export


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(
        description="Quick trial: crawl a small sample of ids and write a report you can open in Excel. "
                    "Any other flag (e.g. --interval 2) is passed on to crawl.py.")
    ap.add_argument("--corpus", default="data/links_corpus.parquet")
    ap.add_argument("--n", type=int, default=100, help="how many ids to try")
    ap.add_argument("--pick", choices=["random", "first"], default="random",
                    help="random ids across the corpus (default) or the first ids in id order")
    ap.add_argument("--seed", type=int, default=42, help="same seed gives the same random sample")
    ap.add_argument("--worker", default="")
    ap.add_argument("--json-dir", default="json_out", help="folder for the JSON file with the full content")
    args, extra = ap.parse_known_args()

    corpus = Path(args.corpus)
    if not corpus.exists():
        sys.exit(f"not found: {corpus} (put links_corpus.parquet in data/ or pass --corpus)")
    df = pl.read_parquet(corpus, columns=["id", "url"]).filter(pl.col("url").is_not_null())
    n = min(args.n, df.height)
    if args.pick == "first":
        sample = df.sort("id").head(n)
    else:
        sample = df.sample(n=n, seed=args.seed).sort("id")

    name = f"try_{args.pick}_{n}"
    inp = Path("data") / f"{name}.parquet"
    out = Path("crawl_out") / name
    inp.parent.mkdir(parents=True, exist_ok=True)
    sample.write_parquet(inp)
    print(f"trying {n} ids ({args.pick}, id {sample['id'].min()} to {sample['id'].max()}) -> {out}\n")

    cmd = [sys.executable, str(Path(__file__).with_name("crawl.py")), "--input", str(inp), "--out", str(out),
           "--report-every", "10", "--no-json", *extra]
    if args.worker:
        cmd += ["--worker", args.worker]
    t0 = time.time()
    try:
        subprocess.run(cmd, check=False)
    except KeyboardInterrupt:
        print("\nstopped, writing the report for what was crawled")
    elapsed = time.time() - t0

    files = sorted(out.glob("*.parquet"))
    if not files:
        sys.exit("no results yet")
    cols = ["id", "url", "status", "http_status", "lang", "n_chars", "title", "text", "final_url", "domain",
            "error", "extractor", "published_at", "fetched_at"]
    rows = (
        pl.concat([read_shard(str(f), cols) for f in files])
        .sort("fetched_at")
        .unique("id", keep="last")
        .sort("id")
    )
    report = rows.select(
        "id", "url", "status", "http_status", "lang", "n_chars", "title",
        pl.col("text").str.slice(0, 300).str.replace_all(r"\s+", " ").alias("text_preview"),
        "final_url", "domain", "extractor", "published_at", "error",
    )
    csv_path = Path(f"{name}_report.csv")
    report.write_csv(csv_path, include_bom=True)

    done = rows.height
    print(f"\n===== trial result: {done}/{n} ids in {elapsed:.0f}s =====")
    for s, c in rows.group_by("status").len().sort("len", descending=True).iter_rows():
        print(f"  {s:<20} {c:>4}  {100 * c / done:5.1f}%")
    ok = rows.filter(pl.col("status") == "ok")
    if ok.height:
        langs = ", ".join(f"{l or '?'} {c}" for l, c in ok.group_by("lang").len().sort("len", descending=True).iter_rows())
        how = ", ".join(f"{e or 'not recorded'} {c}" for e, c in
                        ok.group_by("extractor").len().sort("len", descending=True).iter_rows())
        print(f"\n  ok pages by language: {langs}")
        print(f"  text extracted by: {how}")
        print(f"  text length of ok pages: median {int(ok['n_chars'].median()):,} chars, "
              f"min {ok['n_chars'].min():,}, max {ok['n_chars'].max():,}")
    print(f"  distinct domains in the sample: {rows['domain'].n_unique()}\n")
    export([str(out)], Path(args.json_dir), name)
    print(f"report: {csv_path} (opens in Excel) | raw files: {out}")
    print("run the same command again to continue an unfinished trial; delete the folder above to start over")


if __name__ == "__main__":
    main()
