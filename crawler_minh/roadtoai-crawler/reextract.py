from __future__ import annotations

import argparse
import os
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from common import (MAX_TEXT_CHARS, SHARD_SCHEMA, find_files, guess_lang, read_shard, sha256_text, text_status,
                    utf8_console, write_shard)
from extract import extract_html

COLUMNS = [f.name for f in SHARD_SCHEMA]
WITH_TEXT = {"ok", "empty_text", "extract_error"}
_XML_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")


def process_file(task: tuple[str, int]) -> Counter:
    file, min_chars = task
    stats: Counter = Counter()
    rows = read_shard(file, COLUMNS).to_dicts()
    for r in rows:
        stats["rows"] += 1
        old_text, old_status = r.get("text") or "", r["status"]
        r["extractor"] = r.get("extractor") or ""
        r["published_at"] = r.get("published_at") or ""
        r["text_sha256"] = r.get("text_sha256") or sha256_text(old_text)
        html = r.get("html")
        if not html or old_status not in WITH_TEXT:
            continue
        try:
            decoded = _XML_DECL.sub("", html.decode("utf-8", errors="replace"))
            title, text, date, extractor = extract_html(decoded, r.get("final_url") or r["url"])
        except Exception:
            stats["failed"] += 1
            continue
        stats["pages"] += 1
        if not text and old_text and not extractor.startswith("site:"):
            stats["kept_old_text"] += 1
            continue
        text = text[:MAX_TEXT_CHARS]
        r.update(
            title=(title or r.get("title") or "")[:1000],
            text=text,
            n_chars=len(text),
            lang=guess_lang(text),
            extractor=extractor,
            published_at=date or r["published_at"],
            text_sha256=sha256_text(text),
            status=text_status(text, extractor, min_chars),
        )
        if old_status == "extract_error":
            r["error"] = ""
        if text != old_text:
            stats["text_changed"] += 1
        if r["status"] != old_status:
            stats[f"{old_status} -> {r['status']}"] += 1
        stats["chars_before"] += len(old_text)
        stats["chars_after"] += len(text)
    write_shard(rows, Path(file))
    return stats


def main() -> None:
    utf8_console()
    ap = argparse.ArgumentParser(
        description="Extract the text again from the HTML stored in crawl files, without downloading anything. "
                    "Run it after updating extract.py so pages crawled earlier get the improved text.")
    ap.add_argument("--input", nargs="+", default=["crawl_out"], help="crawl output folders or shard files")
    ap.add_argument("--min-chars", type=int, default=100, help="same meaning as in crawl.py")
    ap.add_argument("--workers", type=int, default=0, help="processes (default: CPUs - 1)")
    args = ap.parse_args()

    files = find_files(args.input)
    if not files:
        raise SystemExit("no parquet files found")
    workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
    print(f"{len(files):,} shard files, {workers} processes; files are rewritten in place")
    total: Counter = Counter()
    t0 = time.time()
    tasks = [(f, args.min_chars) for f in files]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, stats in enumerate(pool.map(process_file, tasks), start=1):
            total.update(stats)
            if i % 20 == 0 or i == len(files):
                rate = total["pages"] / max(1e-6, time.time() - t0)
                print(f"  {i:,}/{len(files):,} files | {total['pages']:,} pages extracted again | {rate:.0f} pages/s")

    print(f"\nrows: {total['rows']:,} | pages with stored HTML extracted again: {total['pages']:,} | "
          f"text changed: {total['text_changed']:,}")
    if total["pages"]:
        print(f"characters of text: {total['chars_before']:,} -> {total['chars_after']:,}")
    for key in sorted(k for k in total if " -> " in k):
        print(f"  status {key}: {total[key]:,}")
    if total["kept_old_text"]:
        print(f"  kept the earlier text for {total['kept_old_text']:,} pages where the new extraction found nothing")
    if total["failed"]:
        print(f"  {total['failed']:,} pages could not be processed and were left unchanged")
    print("next: run export_json.py and merge.py again so their outputs use the new text")


if __name__ == "__main__":
    main()
