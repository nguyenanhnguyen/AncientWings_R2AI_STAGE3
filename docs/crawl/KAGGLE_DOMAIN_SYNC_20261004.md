# Đồng bộ crawl corpus Kaggle với domain_samples — 04/10/2026

`notebooks/crawl_corpus_kaggle.ipynb` đã dùng chung `priority_probe.py` với notebook 97 hostname.
Notebook corpus nhúng 6 snapshot: crawler, priority_probe, corpus_runner, audit, export, diagnostics.
`corpus_runner.py` điều phối hai engine và tạo checkpoint cuối để report/audit/export đọc được.
`scripts/crawl_corpus.py` vẫn là điểm chạy CLI core trước đây; các cấu hình bên dưới áp dụng cho notebook Kaggle.

## Cấu hình đã đồng bộ

| Phần | Cấu hình mặc định |
| --- | --- |
| Requests | User-Agent Mozilla/Chrome và cùng bộ header với domain_samples |
| Retry trang | 3 lần; connect/read timeout 20/45 giây; ngân sách 180 giây mỗi URL |
| Lỗi mạng | Phân loại timeout/DNS/SSL/reset; làm mới session khi retry, giữ cookies và TLS verification |
| Lỗi HTTP | Retry 408, 429 và 5xx trong ngân sách; lưu raw từng lần, giữ Retry-After |
| Robots | `RESPECT_ROBOTS = False` tải trực tiếp giống domain_samples; `True` kiểm tra trước request và redirect |
| Retry/cache robots khi bật | 3 lần, timeout 15/30 giây, ngân sách 90 giây, TTL lỗi tạm thời 30 giây |
| Selenium | `BROWSER_TEST_MODE = 'failed_only'`, 2 lần, page load 45 giây, render wait 15 giây |
| User-Agent Selenium | Dùng User-Agent thực của Chrome khi `BROWSER_USER_AGENT = None` |
| Parser/QC | Cùng core hiện tại, gồm Bach Mai v2; vẫn kiểm tra redirect và challenge |

Selenium Manager tìm hoặc tải Chrome/driver. Nếu khởi động thất bại, `browser_setup_error.json`
ghi lý do và Requests vẫn có báo cáo. Có thể chạy lại ô crawl để thử khởi động browser lần nữa.
Khi bật robots, các URL có trạng thái `robots_*` không được chuyển sang Selenium.
Kết quả truy cập được không đồng nghĩa nội dung accepted: review/rejected ở lại quarantine.

## Chạy trên Kaggle

1. Upload notebook mới, bật Internet, chỉnh `ID_FROM`, `ID_TO` và `SOURCE_PARQUET` nếu dùng Kaggle Input.
2. Có thể đặt `MAX_NEW = 10` để thử trước; sau đó `None` để tiếp tục.
3. Mặc định run mới có tên `ids_<ID_FROM>_<ID_TO>_synced`, tách khỏi run dùng engine cũ.
4. Chạy tuần tự các ô. Ô báo cáo hiện cả QC và tổng số URL được Requests/Selenium tải thành công.

`MAX_NEW` giới hạn số URL Requests mới. Selenium xử lý các URL Requests lỗi đã có checkpoint
và chưa có checkpoint browser, kể cả URL của lượt trước trong cùng run.
Giữ nguyên code, dependencies và cấu hình tải trang/browser khi resume cùng run.

## Resume và recovery

Tiếp tục một run đã dùng notebook mới:

```python
RESUME_RUN_PATH = '/kaggle/input/my-output/ids_583_1582_synced'
RECOVERY_RUN_PATH = None
```

Nâng cấp run cũ hoặc thử lại URL lỗi bằng code/cấu hình mới:

```python
RESUME_RUN_PATH = None
RECOVERY_RUN_PATH = '/kaggle/input/my-output/old-run'
RUN_TAG = 'ids_583_1582_recovery_v1'
```

Giữ khoảng ID muốn crawl. Recovery đối chiếu ID/URL của từng record với mẫu mới,
kiểm tra hash raw 2xx, chạy lại extractor/QC và chỉ gửi request cho URL còn thiếu/lỗi.
Raw thành công từ Selenium trong run corpus mới cũng được tái sử dụng.
Raw từng lần thử của record được reuse cũng được giữ; run nguồn không bị sửa.
`recovery_manifest.json` liệt kê `reused_ids` và `retry_ids`.
Run cũ dùng `crawl_config.json` cần recovery sang run mới để tránh trộn checkpoint của hai engine.

## Đầu ra

| File/thư mục | Nội dung |
| --- | --- |
| `requests_records/` | Checkpoint Requests, kể cả lỗi trước khi Selenium phục hồi |
| `browser_records/`, `browser_screenshots/` | Kết quả và ảnh của Selenium |
| `records/` | Kết quả cuối: Requests thành công, hoặc Selenium phục hồi; giữ liên kết đến bằng chứng gốc |
| `raw/` | Raw và hash của các engine/lần thử |
| `corpus.parquet`, `corpus.jsonl` | Chỉ tài liệu qua QC accepted, giữ ID/URL nguồn |
| `access_summary.json` | Tổng số vào được, còn lỗi, Selenium phục hồi và chưa chạy |
| `requests_vs_selenium.csv` | Đối chiếu từng URL, giữ riêng HTTP/lỗi Requests và Selenium |
| `khong_vao_duoc.csv` | URL còn lỗi, sắp theo tổng URL hostname trong dataset giảm dần |
| `uu_tien_fix_domain.json`, `WEB_ERRORS.md` | Domain còn lỗi và thứ tự ưu tiên theo quy mô dataset |
| `<run>_diagnostics.zip` | Báo cáo, cấu hình và một số record/raw để debug, gồm bằng chứng từng engine |

## Kiểm chứng local

Lượt thử bằng các snapshot giải nén từ notebook mới: 8 URL thật, gồm 5 domain ưu tiên
và `vov.vn`, `suckhoeviet.org.vn`, `special.vietnamplus.vn`.

| Kết quả | Số URL |
| --- | ---: |
| Requests tải thành công | 5 |
| Selenium phục hồi thêm | 2 |
| Tổng truy cập được | 7/8 |
| Còn lỗi | 1 — zysjonline.com, HTTP 403/challenge |
| QC accepted và đã xuất corpus | 6 |
| QC review | 1 — www.120ask.com, boilerplate_suspect |

Selenium phục hồi `vov.vn` từ Requests 403 và `special.vietnamplus.vn` từ Requests 429.
Audit xác nhận ID/URL khớp Parquet, raw/text đúng hash; export Parquet/JSONL qua round-trip.
63 tests đã qua. Đã đối chiếu cả 6 snapshot với mã nguồn hiện tại và snapshot thực chạy;
kiểm tra hash 13 raw artifact, text, ID/URL của 6 bản xuất và tính toàn vẹn ZIP.
Đây là kiểm chứng local, chưa phải một lượt chạy trực tiếp trên mạng Kaggle.

Artifact local (ngoài Git):

- `runs/kaggle_sync_20261004/smoke_network/`
- `runs/kaggle_sync_20261004/smoke_network.log`
- `runs/kaggle_sync_20261004/smoke_network_diagnostics.zip`
- `runs/kaggle_sync_20261004/tests.log`

Lượt `smoke/` đầu tiên bị sandbox chặn socket bằng WinError 10013; không dùng lượt đó để kết luận website lỗi.
Hai notebook trước khi rebuild được giữ trong `runs/kaggle_sync_20261004/*.before.ipynb`.

Sau khi chỉnh engine chung, rebuild cả hai notebook:

```powershell
.\.venv\Scripts\python.exe scripts/build_kaggle_notebook.py
.\.venv\Scripts\python.exe scripts/build_domain_probe_notebook.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Bài test đối chiếu snapshot giữa hai notebook sẽ báo lỗi nếu quên rebuild một bên.
