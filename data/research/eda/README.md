# Crawl EDA

`analyze_crawl.py` performs a read-only, streaming audit over record JSON found below the supplied input roots.

Run from repository root:

```powershell
.\env\Scripts\python.exe data\research\eda\analyze_crawl.py
```

It scans `nguyen/output` and `nguyen/shards`, including extracted shard run folders. Results go to a fresh timestamped folder in `data/research/eda/results/`.

Options:

- `--sample-per-stratum 30`: maximum sample per run × domain × crawl status × quality status.
- `--seed 20261008`: stable reservoir sample.
- `--input <root> [<root> ...]`: alternative read-only roots.
- `--out <directory>`: explicit output folder; use a new path for each run.

No source files are modified. Raw `.gz` files are not opened. See `data/research/README.md` for output descriptions and data handling rules.
