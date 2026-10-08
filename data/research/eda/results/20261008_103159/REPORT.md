# Crawl data EDA

Generated UTC: 2026-10-08T03:32:42.045789+00:00

- Scan mode: **evenly_spaced_sample**; available record files: **271,616**
- Record files parsed: **9,000** (0 invalid JSON)
- Runs: **3**; strata sampled: **23**
- Text length chars: median 925.0, p95 5983.5, max 36894
- Exact text duplicate excess records: **157**

## Records per run

| Run | Available files | Analyzed files | Unique sampled IDs |
|---|---:|---:|---:|
| `nguyen\output\runs\batch01_nguyen` | 119,794 | 3,000 | 3,000 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | 65,001 | 3,000 | 3,000 |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | 86,821 | 3,000 | 3,000 |

## Top domains

See `domain_counts.csv` for full per-run distribution.

### `nguyen\output\runs\batch01_nguyen`

| Domain | Records |
|---|---:|
| `thanhnien.vn` | 771 |
| `suckhoedoisong.vn` | 725 |
| `tiemchunglongchau.com.vn` | 332 |
| `vietnamnet.vn` | 293 |
| `vov.vn` | 245 |
| `suckhoeviet.org.vn` | 141 |
| `tamanhhospital.vn` | 107 |
| `tuoitre.vn` | 97 |
| `vov2.vov.vn` | 87 |
| `tienphong.vn` | 76 |
| `thaythuocvietnam.vn` | 74 |
| `vnexpress.net` | 51 |
| `www.120ask.com` | 1 |

### `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843`

| Domain | Records |
|---|---:|
| `www.cnkang.com` | 3,000 |

### `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843`

| Domain | Records |
|---|---:|
| `www.cnkang.com` | 2,074 |
| `www.wujue.com` | 926 |

## Text length by run

| Run | Text records | Median chars | P95 chars | Max chars |
|---|---:|---:|---:|---:|
| `nguyen\output\runs\batch01_nguyen` | 2,752 | 3260.5 | 7371.499999999998 | 36894 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | 3,000 | 685.5 | 1975.0499999999997 | 14553 |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | 2,999 | 678.0 | 2238.1 | 21126 |

## Crawl status and QC by sampled run

| Run | Status counts | QC flags |
|---|---|---|
| `nguyen\output\runs\batch01_nguyen` | extracted: 2752, http_error: 1, unsupported_content_type: 2, robots_denied: 245 | decode_warning: 0, mojibake_suspect: 0, html_residue_suspect: 0, cjk_dominant_text: 1 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | extracted: 3000 | decode_warning: 0, mojibake_suspect: 0, html_residue_suspect: 0, cjk_dominant_text: 3000 |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | extracted: 2999, http_error: 1 | decode_warning: 0, mojibake_suspect: 0, html_residue_suspect: 1, cjk_dominant_text: 2999 |

Quality flags in sample: `{"domain_parser_fallback": 3000, "short_text": 151, "redirect_review": 59, "repeated_lines": 13, "low_letter_ratio": 1}`.

## Quality and text integrity signals

Counts are heuristic indicators requiring inspection; a mojibake marker can occur legitimately.

`question_mark_lines`, `records_with_question_mark_line`, and `records_with_qa_role_marker` are weak FAQ/Q&A structure signals, not proof that a clean question–answer pair was found.

See `summary.json`, `suspect_mojibake_samples.json`, `suspect_html_samples.json`, and `stratified_samples.jsonl`.

## Sampling method

Reservoir sampling with fixed seed 20261008; capped at 30 per run × domain × status × quality-status. Samples retain at most 5,000 text characters each.

## Caveats

- Default scan selects evenly spaced IDs per run; distributions describe this sample, not exact full-run totals. Use `--full-scan` for exact record-level totals; it can take a long time.
- Crawl runs may still be updating; rerun after crawl completion for a stable snapshot.
- This script reads record JSON only; it does not decompress or copy raw response bodies.
- Word counts are rough Unicode regex counts, not model-token counts.
- Structural, language, and mojibake flags are screening signals, not automatic rejection labels.
