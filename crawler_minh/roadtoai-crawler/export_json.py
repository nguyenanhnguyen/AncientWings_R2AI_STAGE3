from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
from pathlib import Path

import polars as pl

from common import find_files, pick_winners, read_shard, scan_light, utf8_console

FIELDS = ["id", "url", "status", "lang", "n_chars", "title", "text", "final_url", "domain", "http_status",
          "content_type", "error", "extractor", "published_at", "text_sha256", "canonical_id", "dup_count",
          "fetched_at", "worker", "batch"]
DEFAULT_ROWS = 10_000
_PART = re.compile(r"-\d{4}\.json(\.tmp)?")


def existing_outputs(out_dir: Path, name: str) -> list[Path]:
    found = []
    if not out_dir.is_dir():
        return found
    for p in sorted(out_dir.glob(glob.escape(name) + "*")):
        rest = p.name[len(name):]
        if rest in (".json", ".jsonl") or _PART.fullmatch(rest):
            found.append(p)
    return [p for p in found if not p.name.endswith(".tmp")]


def clear_old(out_dir: Path, name: str) -> None:
    for p in out_dir.glob(glob.escape(name) + "*"):
        rest = p.name[len(name):]
        if rest in (".json", ".jsonl", ".json.tmp", ".jsonl.tmp") or _PART.fullmatch(rest):
            p.unlink()


def to_records(df: pl.DataFrame, with_html: bool) -> list[dict]:
    rows = df.to_dicts()
    if with_html:
        for r in rows:
            h = r.get("html")
            r["html"] = h.decode("utf-8", errors="replace") if h else ""
    return rows


def write_json(path: Path, rows: list[dict], compact: bool) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        if compact:
            json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def export(inputs: list[str], out_dir: Path, name: str, rows_per_file: int = DEFAULT_ROWS, only_ok: bool = False,
           with_html: bool = False, jsonl: bool = False, compact: bool = False) -> list[Path]:
    files = find_files(inputs)
    if not files:
        print("JSON: no crawl results to export yet")
        return []
    present: set[str] = set()
    for f in files:
        present |= set(pl.read_parquet_schema(f))
    if "status" in present:
        winners = pick_winners(scan_light(files, ["id", "status", "fetched_at"]))
        if only_ok:
            winners = winners.filter(pl.col("status") == "ok")
    else:
        winners = scan_light(files, ["id"]).unique("id", keep="last", maintain_order=True)
    total = winners.height
    cols = [c for c in FIELDS if c in present]
    use_html = with_html and "html" in present
    if use_html:
        cols.append("html")

    out_dir.mkdir(parents=True, exist_ok=True)
    clear_old(out_dir, name)
    by_file = winners.group_by("file").agg("id").sort("file")
    paths: list[Path] = []

    def load(file: str, ids: list[int]) -> list[dict]:
        part = read_shard(file, cols).filter(pl.col("id").is_in(ids)).unique("id", keep="last").sort("id")
        return to_records(part, use_html)

    if jsonl:
        path = out_dir / f"{name}.jsonl"
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for file, ids in by_file.iter_rows():
                for r in load(file, ids):
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        paths.append(path)
    else:
        rows_per_file = max(1, rows_per_file)
        n_parts = max(1, math.ceil(total / rows_per_file))

        def flush(chunk: list[dict]) -> None:
            chunk.sort(key=lambda r: r["id"])
            suffix = ".json" if n_parts == 1 else f"-{len(paths) + 1:04d}.json"
            path = out_dir / f"{name}{suffix}"
            write_json(path, chunk, compact)
            paths.append(path)

        buffer: list[dict] = []
        for file, ids in by_file.iter_rows():
            buffer.extend(load(file, ids))
            while len(buffer) >= rows_per_file:
                chunk, buffer = buffer[:rows_per_file], buffer[rows_per_file:]
                flush(chunk)
        if buffer or not paths:
            flush(buffer)

    size = sum(p.stat().st_size for p in paths) / 1e6
    if len(paths) == 1:
        print(f"JSON: {total:,} rows -> {paths[0]} ({size:.1f} MB)")
    else:
        print(f"JSON: {total:,} rows -> {len(paths)} files, {paths[0]} ... {paths[-1].name} ({size:.1f} MB)")
    return paths


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(description="Export crawl results (parquet) to readable JSON, one record per id.")
    ap.add_argument("--input", nargs="+", default=["crawl_out"],
                    help="crawl output folders or parquet files, e.g. crawl_out/batch_00 or merged/docs.parquet")
    ap.add_argument("--out-dir", default="json_out")
    ap.add_argument("--name", default="", help="output file name without extension (default: name of the input)")
    ap.add_argument("--rows-per-file", type=int, default=DEFAULT_ROWS,
                    help="split the output into files of this many records")
    ap.add_argument("--only-ok", action="store_true", help="only pages whose text was extracted")
    ap.add_argument("--with-html", action="store_true", help="also include the stored HTML (much larger files)")
    ap.add_argument("--jsonl", action="store_true", help="one JSON object per line in a single .jsonl file")
    ap.add_argument("--compact", action="store_true", help="no indentation (smaller files)")
    args = ap.parse_args()

    name = args.name
    if not name:
        first = Path(args.input[0])
        name = (first.stem if first.is_file() else first.name) if len(args.input) == 1 else "crawl"
    export(args.input, Path(args.out_dir), name, args.rows_per_file, args.only_ok, args.with_html, args.jsonl,
           args.compact)


if __name__ == "__main__":
    main()
