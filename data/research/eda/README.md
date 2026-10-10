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

## Link lỗi / link chết

Danh sách mọi link không cho ra bài dùng được, quét **đủ** mọi bản ghi của mọi run (chỉ đọc vài trường nhẹ, bỏ phần thống kê văn bản):

```powershell
.\env\Scripts\python.exe data\research\eda\analyze_crawl.py --failed-only
```

Kết quả trong thư mục kết quả mới:

- `FAILED_LINKS.md`: tổng hợp theo nguyên nhân, theo run, 30 domain lỗi nhiều nhất.
- `failed_links.csv`: mỗi link một dòng (`run`, `id`, `category`, `reason`, `domain`, `url`, `status`, `http_status`, `error`...), mở bằng Excel.
- `failed_summary.json`: cùng số liệu dạng máy đọc.

Nhóm nguyên nhân (`category`): `robots_4xx` (robots.txt trả 4xx, crawler coi như cấm), `robots_disallow`, `robots_unreachable`, `dead` (404/410, DNS), `blocked` (401/403/429, challenge), `temporary` (timeout, 5xx), `not_article` (ảnh, trang chủ, rỗng), `quality_rejected`, `other`.

Chế độ thường (không có `--failed-only`) cũng ghi ba file này nhưng chỉ cho các bản ghi trong mẫu, và thêm mục "Failed / dead links" vào `REPORT.md`.

Báo cáo lỗi theo **từng run** mà crawler tự ghi (không gộp các run) nằm sẵn trong thư mục run: `WEB_ERRORS.md`, `khong_vao_duoc.csv`, `access_summary.json`, `quarantine.jsonl` (ví dụ `nguyen\shards\shard_01\runs\<run>\`). Run `batch01_nguyen` chỉ có `quarantine.jsonl` ở thư mục run; bản đầy đủ nằm trong `nguyen\output\batch01_nguyen_diagnostics.zip`.

No source files are modified. Raw `.gz` files are not opened. See `data/research/README.md` for output descriptions and data handling rules.
