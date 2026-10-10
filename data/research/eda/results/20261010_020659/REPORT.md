# Crawl data EDA

Generated UTC: 2026-10-09T19:10:29.220834+00:00

- Scan mode: **evenly_spaced_sample**; available record files: **331,618**
- Record files parsed: **9,000** (0 invalid JSON)
- Runs: **3**; strata sampled: **27**
- Text length chars: median 931.0, p95 5769.549999999992, max 30652
- Exact text duplicate excess records: **128**

## Records per run

| Run | Available files | Analyzed files | Unique sampled IDs |
|---|---:|---:|---:|
| `nguyen\output\runs\batch01_nguyen` | 136,926 | 3,000 | 3,000 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | 87,463 | 3,000 | 3,000 |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | 107,229 | 3,000 | 3,000 |

## Top domains

See `domain_counts.csv` for full per-run distribution.

### `nguyen\output\runs\batch01_nguyen`

| Domain | Records |
|---|---:|
| `thanhnien.vn` | 778 |
| `suckhoedoisong.vn` | 738 |
| `vietnamnet.vn` | 340 |
| `tiemchunglongchau.com.vn` | 290 |
| `vov.vn` | 215 |
| `vov2.vov.vn` | 151 |
| `suckhoeviet.org.vn` | 123 |
| `tamanhhospital.vn` | 93 |
| `tuoitre.vn` | 85 |
| `tienphong.vn` | 67 |
| `thaythuocvietnam.vn` | 65 |
| `vnexpress.net` | 45 |
| `www.qdnd.vn` | 4 |
| `www.sggp.org.vn` | 4 |
| `www.pharmacity.vn` | 1 |

### `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843`

| Domain | Records |
|---|---:|
| `www.cnkang.com` | 3,000 |

### `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843`

| Domain | Records |
|---|---:|
| `www.cnkang.com` | 2,250 |
| `www.wujue.com` | 750 |

## Text length by run

| Run | Text records | Median chars | P95 chars | Max chars |
|---|---:|---:|---:|---:|
| `nguyen\output\runs\batch01_nguyen` | 2,780 | 3165.5 | 7290.9999999999945 | 30652 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | 3,000 | 682.0 | 1967.349999999998 | 12847 |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | 3,000 | 708.5 | 2269.5999999999967 | 28132 |

## Crawl status and QC by sampled run

| Run | Status counts | QC flags |
|---|---|---|
| `nguyen\output\runs\batch01_nguyen` | extracted: 2780, unsupported_content_type: 5, robots_denied: 215 | decode_warning: 0, mojibake_suspect: 0, html_residue_suspect: 0, cjk_dominant_text: 1 |
| `nguyen\shards\shard_01\runs\shard_01_ids_1525844_1775843` | extracted: 3000 | decode_warning: 0, mojibake_suspect: 0, html_residue_suspect: 0, cjk_dominant_text: 2999 |
| `nguyen\shards\shard_02\runs\shard_02_ids_1775844_2025843` | extracted: 3000 | decode_warning: 0, mojibake_suspect: 0, html_residue_suspect: 0, cjk_dominant_text: 2996 |

Quality flags in sample: `{"domain_parser_fallback": 3001, "short_text": 148, "redirect_review": 45, "repeated_lines": 24, "low_letter_ratio": 4}`.

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
