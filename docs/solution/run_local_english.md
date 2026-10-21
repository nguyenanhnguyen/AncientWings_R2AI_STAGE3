# Local English corpus run from team HF

Run from the repository root in PowerShell. This reads corpus text from
`AncientWings/AncientWings_R2AI_STAGE3_ds`, validates ID/URL pairs against the
pinned official mapping, and keeps English records in the eight intervals below.
These are official corpus IDs, not PubMed PMIDs. Both endpoints are inclusive.

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline `
  --source hf `
  --hf-repo AncientWings/AncientWings_R2AI_STAGE3_ds `
  --language en `
  --id-range 4421055:5174242 `
  --id-range 5174255:5276329 `
  --id-range 5276332:5379235 `
  --id-range 5379237:5481792 `
  --id-range 5481811:5582417 `
  --id-range 5582429:5681209 `
  --id-range 5681216:5782500 `
  --id-range 5782505:5880573 `
  --limit 0 `
  --hf-sample-mode bounded `
  --hf-max-shards 0 `
  --out nguyen/pipeline_runs/en_batches_01_08
```

`--limit 0` selects all available valid records, rather than demanding exactly
80,000. Metadata checked on 2026-10-16 at HF revision
`0a5b56eaf1158fd1ad4c9095aa8a1e586f88669b` showed 79,982 stored rows in the eight
named shards (10000, 9999, 10000, 10000, 10000, 9998, 9989, 9996).
Filtering and deduplication can reduce the final count. The manifest records
selected counts per interval and actual min/max IDs.

The run pins the first HF revision it reads. Parquet row-group statistics skip
groups outside the intervals; row-level official ID/URL validation still applies.
The reader inspects all corpus shard metadata to avoid silently missing records.

The pipeline runs HF snapshot, prepare, chunk, GPU pilot, Vietnamese-to-English
query translation, BM25, Qwen3-Embedding-4B NF4, hybrid retrieval,
Qwen3-Reranker-4B NF4, and two submission profiles. It does not fine-tune models.
It uses the existing local defaults, including reranking up to 200 candidates per
query; this can take substantial time on an RTX 2050.

Outputs:

- `nguyen/pipeline_runs/en_batches_01_08/submission/submission.zip`
- `nguyen/pipeline_runs/en_batches_01_08/submission_balanced/submission.zip`
- Stage logs: `nguyen/pipeline_runs/en_batches_01_08/logs/`
- Snapshot and model cache: `nguyen/hf_pipeline/`

If authentication fails, run `.\env\Scripts\hf.exe auth login` and use a token
with read access to the team dataset. Do not paste tokens into command arguments.
Rerun the same command to resume with unchanged configuration. For one interval,
keep only that `--id-range` and choose a new `--out`; do not run the eight separate
jobs unless you intentionally want eight separate submission experiments.
