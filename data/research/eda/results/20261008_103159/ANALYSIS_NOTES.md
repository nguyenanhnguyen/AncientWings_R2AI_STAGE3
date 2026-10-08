# Interpretation notes for the 2026-10-08 sample

This is an interpretation of the 9,000 records selected by `analyze_crawl.py`, not a census of all 271,616 record files. Sampling takes 3,000 evenly spaced IDs per run; counters below describe the selected sample.

## What is in the crawled material

- The Vietnamese batch sample contains multiple Vietnamese news/health domains. Its largest sampled domains are `thanhnien.vn` (771), `suckhoedoisong.vn` (725), and `tiemchunglongchau.com.vn` (332).
- The two later shards are a different population: shard 01 is `www.cnkang.com`; shard 02 is `www.cnkang.com` (2,074) and `www.wujue.com` (926). All 3,000 sampled shard 01 texts and 2,999/3,000 shard 02 texts are Chinese-dominant by a simple character heuristic and carry `zh_hint`.
- This means the shards should be analyzed as a separate language/source cohort before they are merged into a retrieval corpus. The Vietnamese batch and Chinese shards differ materially in source domains, language, and document length.

## Text length and structure

| Crawl run | Text samples | Median chars | P95 chars | Max chars |
|---|---:|---:|---:|---:|
| `batch01_nguyen` | 2,752 | 3,260.5 | 7,371.5 | 36,894 |
| `shard_01` | 3,000 | 685.5 | 1,975.1 | 14,553 |
| `shard_02` | 2,999 | 678.0 | 2,238.1 | 21,126 |

The shard text is much shorter by character count, with a long tail. A single fixed chunk size will therefore produce different chunks-per-document distributions by language and source. Measure chunk counts and evidence coverage separately for Vietnamese and Chinese; do not interpret character counts as model-token counts.

## FAQ/Q&A evidence in the source

The screening found question-mark lines in 872 Vietnamese-batch records, 928 shard 01 records, and 590 shard 02 records. Weak role markers such as Vietnamese `Hỏi/Đáp/Trả lời` and Chinese `患者/医生/问答` appeared in 63, 110, and 104 records respectively. These are search signals only: a question mark can be rhetorical, and role labels do not guarantee a clean QA pair.

This supports testing an auxiliary extractor that marks Q/A-like spans and their character offsets. Keep the original document intact; use extracted pairs only as retrieval metadata/query views, and submit validated contiguous source spans. First inspect examples by domain and language and quantify parser precision manually.

## Crawl quality signal requiring review

Every sampled shard 01 record has `quality_status=review` and `domain_parser_fallback`. The flag means the site-specific parser path fell back to the general extractor; it does not by itself mean the text is unusable. Sampled examples include relevant article bodies, but at least one also includes a suspicious inserted sentence (`感冒除了服药，还有更重要凑数的文字`) among otherwise relevant text. Audit a larger stratified sample from this shard before admitting it to the canonical corpus; inspect boilerplate, injected/template text, titles, and answer boundaries.

Shard 02 has 2,867 accepted, 132 review, and one failed record in the 3,000-record sample. The Vietnamese sample has 2,667 accepted, 85 review, and 248 missing/unavailable/blocked records. These proportions are sample observations and can shift by ID interval.

## Duplication and encoding

There are 157 excess exact text duplicates among the selected 9,000 records (70 duplicate groups). Check duplicates by source/domain and retain original IDs; repeated content across IDs may still matter if labels reference a specific ID.

The stricter mojibake screen found no suspicious marker in this sample and no replacement characters or decoder warnings. This is not a full proof of correct language encoding; preserve a manual spot-check, especially around crawler/parser changes.

## Recommended follow-up analyses

1. Audit at least 100 examples per shard/domain, stratified across `accepted`, `review`, and failure/recovery status. Include full text and raw-response references only in a controlled local audit.
2. For each domain, quantify title/body quality, boilerplate overlap, short-text rate, duplicated template lines, section/heading retention, FAQ/Q&A marker precision, and extractor source.
3. Build language-specific corpus snapshots and compare chunk sizes/paragraph boundaries separately. Add a cross-lingual retrieval test set before assuming Chinese pages help Vietnamese queries.
4. Create optional sidecar fields for `language`, `section_path`, `topic_facets[]`, `qa_pair_spans[]`, and extraction confidence. Keep source `text`, IDs, and offsets immutable.
5. Evaluate document Recall@K and official chunk overlap/F2 before reranking. Compare global retrieval with soft facet/Q&A channels; never hard-filter candidates only by predicted topic.

See `REPORT.md`, `summary.json`, `domain_counts.csv`, and `stratified_samples.jsonl` for the supporting sample and counts.
