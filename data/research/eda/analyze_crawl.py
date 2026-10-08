"""Streaming EDA for crawl records; reads nguyen outputs and writes only under data/research/eda."""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import random
import re
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUTS = [ROOT / "nguyen" / "output", ROOT / "nguyen" / "shards"]
DEFAULT_OUT = Path(__file__).resolve().parent / "results"
MOJIBAKE = ("Ã ", "Ã¡", "Ã¢", "Ã£", "Ã¨", "Ã©", "Ã¬", "Ã­", "Ã²", "Ã³",
            "Ã´", "Ãµ", "Ã¹", "Ãº", "Ã½", "Ä‘", "Æ°", "á»", "áº", "â€“", "â€™", "ï¿½", "�")
HTML_RE = re.compile(r"</?(?:div|p|span|br|a|script|style|table|li|h[1-6])\b", re.I)
WORD_RE = re.compile(r"[\wÀ-ỹ]+", re.UNICODE)
QA_MARKER_RE = re.compile(r"(?:hỏi\s*đáp|hỏi\s*[:：]|đáp\s*[:：]|trả lời\s*[:：]|患者\s*[:：]|医生\s*[:：]|问\s*[:：]|答\s*[:：]|问答)", re.I)


def quantile(values: list[int], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return float(ordered[lo])
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def record_files(inputs: list[Path]):
    seen = set()
    groups = defaultdict(list)
    for root in inputs:
        if not root.exists():
            print(f"WARN missing input: {root}", file=sys.stderr)
            continue
        for current, dirs, files in os.walk(root):
            # Raw response trees can contain hundreds of thousands of nested files; EDA needs
            # records only, so prune them before traversal.
            dirs[:] = [name for name in dirs if name not in {
                "raw", "robots", "requests_records", "browser_records", ".selenium_cache",
                "__pycache__", ".git"}]
            current_path = Path(current)
            if current_path.name != "records":
                continue
            dirs[:] = []
            for name in files:
                if not name.endswith(".json"):
                    continue
                path = current_path / name
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    groups[current_path.parent].append(path)
    return groups


def load_record(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"_eda_parse_error": type(exc).__name__}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="*", type=Path, default=DEFAULT_INPUTS,
                        help="Roots to scan (defaults: nguyen/output and nguyen/shards).")
    parser.add_argument("--out", type=Path, default=None,
                        help="Output directory; default is a timestamped folder under data/research/eda/results.")
    parser.add_argument("--sample-per-stratum", type=int, default=30,
                        help="Maximum examples for each run × domain × status × quality-status group.")
    parser.add_argument("--files-per-run", type=int, default=3000,
                        help="Read evenly spaced records per run (default 3000); --full-scan reads all records.")
    parser.add_argument("--full-scan", action="store_true",
                        help="Parse every record JSON. This can take a long time for hundreds of thousands of small files.")
    parser.add_argument("--seed", type=int, default=20261008)
    args = parser.parse_args()
    if args.sample_per_stratum < 1 or args.files_per_run < 1:
        parser.error("sample limits must be positive")

    out = args.out or DEFAULT_OUT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    files_seen = parsed = errors = 0
    records_per_run = Counter()
    counters = defaultdict(Counter)
    domains_by_run = defaultdict(Counter)
    chars_by_run = defaultdict(list)
    title_chars_by_run = defaultdict(list)
    chars, title_chars, word_counts = [], [], []
    body_hashes = Counter()
    duplicate_ids = Counter()
    run_ids = defaultdict(set)
    mojibake_samples, html_samples = [], []
    sample_reservoirs = defaultdict(list)
    sample_seen = Counter()
    year_counts = Counter()
    heading_counts = Counter()
    qline_counts = Counter()
    raw_ref = Counter()
    raw_exists_sample = Counter()
    quality_flags = Counter()
    max_examples = 12

    run_files = record_files(args.input)
    available_per_run = {}
    selected_files = []
    for run_dir, paths in sorted(run_files.items(), key=lambda pair: str(pair[0])):
        run = str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir)
        paths.sort(key=lambda p: (int(p.stem) if p.stem.isdigit() else 2**63, p.name))
        available_per_run[run] = len(paths)
        take = len(paths) if args.full_scan else min(len(paths), args.files_per_run)
        if take == len(paths):
            chosen = paths
        elif take == 1:
            chosen = [paths[len(paths) // 2]]
        else:
            chosen = [paths[round(i * (len(paths) - 1) / (take - 1))] for i in range(take)]
        selected_files.extend((run_dir, path) for path in chosen)

    for run_dir, path in selected_files:
        files_seen += 1
        run = str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir)
        row = load_record(path)
        if "_eda_parse_error" in row:
            errors += 1
            counters["global"]["json_parse_errors"] += 1
            continue
        parsed += 1
        records_per_run[run] += 1
        rid = row.get("id")
        if rid is not None:
            if rid in run_ids[run]:
                duplicate_ids[run] += 1
            run_ids[run].add(rid)
        status = str(row.get("status") or row.get("requests_status") or "missing")
        quality = str(row.get("quality_status") or "missing")
        extractor = str(row.get("extractor") or "missing")
        access = str(row.get("access_status") or "missing")
        url = str(row.get("final_url") or row.get("url") or "")
        domain = (urlsplit(url).hostname or row.get("domain") or "unknown").lower()
        text = str(row.get("text") or "")
        title = str(row.get("title") or "")
        group = (run, domain, status, quality)
        for key, value in (("status", status), ("quality_status", quality),
                           ("extractor", extractor), ("access_status", access),
                           ("domain", domain)):
            counters["global"][key + ":" + value] += 1
        domains_by_run[run][domain] += 1
        counters[run]["status:" + status] += 1
        counters[run]["quality:" + quality] += 1
        counters[run]["extractor:" + extractor] += 1
        counters[run]["access:" + access] += 1
        counters[run]["with_text"] += bool(text.strip())
        counters[run]["with_title"] += bool(title.strip())
        counters[run]["decode_warning"] += bool(row.get("decode_warning"))
        counters[run]["replacement_char"] += "�" in text
        counters[run]["mojibake_suspect"] += any(mark in text or mark in title for mark in MOJIBAKE)
        counters[run]["html_residue_suspect"] += bool(HTML_RE.search(text))
        cjk_chars = sum("\u4e00" <= ch <= "\u9fff" for ch in text)
        latin_chars = sum(ch.isalpha() and not ("\u4e00" <= ch <= "\u9fff") for ch in text)
        counters[run]["cjk_dominant_text"] += bool(text) and cjk_chars > latin_chars
        counters[run]["language_hint:" + str(row.get("language_hint") or "missing")] += 1
        question_lines = sum(1 for line in text.splitlines() if line.strip().endswith(("?", "？")))
        counters[run]["question_mark_lines"] += question_lines
        counters[run]["records_with_question_mark_line"] += question_lines > 0
        counters[run]["records_with_qa_role_marker"] += bool(QA_MARKER_RE.search(text))
        counters[run]["heading_like_lines"] += sum(1 for line in text.splitlines()
            if line.strip() and (line.strip().startswith(("#", "##", "###")) or
            (len(line.strip()) < 100 and line.strip().endswith((":", "：")))))
        if text:
            chars.append(len(text))
            chars_by_run[run].append(len(text))
            word_counts.append(len(WORD_RE.findall(text)))
            digest = row.get("text_sha256") or hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
            body_hashes[digest] += 1
        if title:
            title_chars.append(len(title))
            title_chars_by_run[run].append(len(title))
        pub = str(row.get("published_at") or "")[:4]
        if pub.isdigit():
            year_counts[pub] += 1
        for flag in row.get("quality_flags") or []:
            quality_flags[str(flag)] += 1
        raw_path = row.get("raw_path")
        raw_ref[run] += bool(raw_path)

        # Keep bounded, reproducible, stratified examples; never copy raw bodies wholesale.
        sample_seen[group] += 1
        bucket = sample_reservoirs[group]
        item = {
            "run": run, "id": rid, "url": row.get("url"), "final_url": row.get("final_url"),
            "domain": domain, "status": status, "quality_status": quality,
            "quality_flags": row.get("quality_flags") or [], "extractor": extractor,
            "title": title, "text": text[:5000], "text_chars": len(text),
            "text_sha256": row.get("text_sha256"), "published_at": row.get("published_at"),
            "decode_warning": row.get("decode_warning"), "language_hint": row.get("language_hint"),
            "raw_path": raw_path,
        }
        if len(bucket) < args.sample_per_stratum:
            bucket.append(item)
        else:
            j = rng.randrange(sample_seen[group])
            if j < args.sample_per_stratum:
                bucket[j] = item
        if len(mojibake_samples) < max_examples and any(mark in text or mark in title for mark in MOJIBAKE):
            mojibake_samples.append({"run": run, "id": rid, "title": title[:200], "text": text[:500]})
        if len(html_samples) < max_examples and HTML_RE.search(text):
            html_samples.append({"run": run, "id": rid, "title": title[:200], "text": text[:500]})

    duplicates = sum(n - 1 for n in body_hashes.values() if n > 1)
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": [str(p.resolve()) for p in args.input], "records_files_available": available_per_run,
        "records_selected_for_analysis": len(selected_files), "records_parsed": parsed,
        "json_parse_errors": errors, "scan_mode": "full" if args.full_scan else "evenly_spaced_sample",
        "files_per_run_target": None if args.full_scan else args.files_per_run,
        "records_per_run": dict(records_per_run),
        "unique_ids_per_run": {run: len(ids) for run, ids in run_ids.items()},
        "duplicate_ids_per_run": dict(duplicate_ids),
        "text_chars": {"n": len(chars), "median": quantile(chars, .5), "p90": quantile(chars, .9),
                       "p95": quantile(chars, .95), "max": max(chars) if chars else None},
        "text_chars_by_run": {run: {"n": len(values), "median": quantile(values, .5),
                                    "p95": quantile(values, .95), "max": max(values) if values else None}
                              for run, values in chars_by_run.items()},
        "title_chars": {"n": len(title_chars), "median": quantile(title_chars, .5),
                        "p95": quantile(title_chars, .95), "max": max(title_chars) if title_chars else None},
        "title_chars_by_run": {run: {"n": len(values), "median": quantile(values, .5),
                                     "p95": quantile(values, .95), "max": max(values) if values else None}
                               for run, values in title_chars_by_run.items()},
        "approx_word_count": {"median": quantile(word_counts, .5), "p95": quantile(word_counts, .95),
                              "max": max(word_counts) if word_counts else None},
        "exact_text_duplicate_groups": sum(1 for n in body_hashes.values() if n > 1),
        "exact_text_duplicate_excess_records": duplicates,
        "published_year_counts": dict(sorted(year_counts.items())),
        "quality_flags": dict(quality_flags.most_common()),
        "global_counts": dict(counters["global"]),
        "runs": {run: dict(counts) for run, counts in counters.items() if run != "global"},
        "top_domains_by_run": {run: dict(domains.most_common(100)) for run, domains in domains_by_run.items()},
        "potential_issue_counts": {run: {k: v for k, v in counts.items() if k in {
            "decode_warning", "replacement_char", "mojibake_suspect", "html_residue_suspect",
            "question_mark_lines", "records_with_question_mark_line", "records_with_qa_role_marker",
            "heading_like_lines", "with_text", "with_title", "cjk_dominant_text"}}
            for run, counts in counters.items() if run != "global"},
        "raw_path_record_counts": dict(raw_ref), "strata_count": len(sample_reservoirs),
        "sample_per_stratum_cap": args.sample_per_stratum,
    }
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (out / "domain_counts.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["run", "domain", "records"])
        for run, domains in sorted(domains_by_run.items()):
            writer.writerows([run, domain, count] for domain, count in domains.most_common())
    with (out / "stratified_samples.jsonl").open("w", encoding="utf-8") as stream:
        for key in sorted(sample_reservoirs):
            run, domain, status, quality = key
            for item in sample_reservoirs[key]:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")
    (out / "suspect_mojibake_samples.json").write_text(
        json.dumps(mojibake_samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "suspect_html_samples.json").write_text(
        json.dumps(html_samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = ["# Crawl data EDA", "", f"Generated UTC: {report['generated_at_utc']}", "",
             f"- Scan mode: **{report['scan_mode']}**; available record files: **{sum(available_per_run.values()):,}**",
             f"- Record files parsed: **{parsed:,}** ({errors:,} invalid JSON)",
             f"- Runs: **{len(records_per_run)}**; strata sampled: **{len(sample_reservoirs)}**",
             f"- Text length chars: median {report['text_chars']['median']}, p95 {report['text_chars']['p95']}, max {report['text_chars']['max']}",
             f"- Exact text duplicate excess records: **{duplicates:,}**", "", "## Records per run", "",
             "| Run | Available files | Analyzed files | Unique sampled IDs |", "|---|---:|---:|---:|"]
    for run, n in records_per_run.most_common():
        lines.append(f"| `{run}` | {available_per_run.get(run, 0):,} | {n:,} | {len(run_ids[run]):,} |")
    lines += ["", "## Top domains", "", "See `domain_counts.csv` for full per-run distribution.", ""]
    for run, domains in sorted(domains_by_run.items()):
        lines += [f"### `{run}`", "", "| Domain | Records |", "|---|---:|"]
        lines += [f"| `{domain}` | {n:,} |" for domain, n in domains.most_common(15)]
        lines.append("")
    lines += ["## Text length by run", "", "| Run | Text records | Median chars | P95 chars | Max chars |", "|---|---:|---:|---:|---:|"]
    for run, stats in sorted(report["text_chars_by_run"].items()):
        lines.append(f"| `{run}` | {stats['n']:,} | {stats['median']} | {stats['p95']} | {stats['max']} |")
    lines.append("")
    lines += ["## Crawl status and QC by sampled run", "", "| Run | Status counts | QC flags |", "|---|---|---|"]
    for run, counts in sorted(counters.items()):
        if run == "global":
            continue
        statuses = ", ".join(f"{k[7:]}: {v}" for k, v in counts.items() if k.startswith("status:"))
        flags = ", ".join(f"{k}: {v}" for k, v in counts.items() if k in {
            "decode_warning", "mojibake_suspect", "html_residue_suspect", "cjk_dominant_text"})
        lines.append(f"| `{run}` | {statuses} | {flags} |")
    lines += ["", f"Quality flags in sample: `{json.dumps(dict(quality_flags.most_common()), ensure_ascii=False)}`.",
              "", "## Quality and text integrity signals", "",
              "Counts are heuristic indicators requiring inspection; a mojibake marker can occur legitimately.", "",
              "`question_mark_lines`, `records_with_question_mark_line`, and `records_with_qa_role_marker` are weak FAQ/Q&A structure signals, not proof that a clean question–answer pair was found.", "",
              "See `summary.json`, `suspect_mojibake_samples.json`, `suspect_html_samples.json`, and `stratified_samples.jsonl`.", "",
              "## Sampling method", "",
              f"Reservoir sampling with fixed seed {args.seed}; capped at {args.sample_per_stratum} per run × domain × status × quality-status. Samples retain at most 5,000 text characters each.", "",
              "## Caveats", "",
              "- Default scan selects evenly spaced IDs per run; distributions describe this sample, not exact full-run totals. Use `--full-scan` for exact record-level totals; it can take a long time.",
              "- Crawl runs may still be updating; rerun after crawl completion for a stable snapshot.",
              "- This script reads record JSON only; it does not decompress or copy raw response bodies.",
              "- Word counts are rough Unicode regex counts, not model-token counts.",
              "- Structural, language, and mojibake flags are screening signals, not automatic rejection labels.", ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Read {parsed:,} records ({errors:,} JSON errors) from {len(records_per_run)} runs; "
          f"available record files: {sum(available_per_run.values()):,}.")
    print(f"Wrote EDA outputs to: {out}")


if __name__ == "__main__":
    main()
