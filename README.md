# R2AI2026 Stage 3 — ViBioMIR

Repo phục vụ pipeline RAG của dự án ViBioMIR. Phần đã triển khai hiện tại là crawl, trích xuất, kiểm tra chất lượng và xuất corpus. Chưa có code chunking, indexing, retrieval hoặc training.

## Bố cục hiện tại

```text
src/vibiomir/crawl/   Logic crawl, extraction, audit và export
scripts/             Lệnh chạy, gọi code trong src/
notebooks/           Notebook crawl độc lập trên Kaggle
tests/               Kiểm tra phần crawl đã triển khai
requirements/        Dependencies crawl và bản khóa phiên bản
docs/crawl/          Thiết kế, hướng dẫn chạy và kết quả crawl
docs/references/     PDF và tài liệu tham khảo local
data/                Parquet nguồn và metadata nguồn
runs/                Raw, checkpoint, corpus và báo cáo sinh ra (ngoài Git)
tmp/                 File tạm local (ngoài Git)
```

Các thư mục dành cho RAG/train sẽ được bổ sung khi có implementation. Logic hiện có được chuyển nguyên nội dung vào `src/vibiomir/crawl/`; các script chỉ là điểm chạy. Script tự thêm `src/` vào đường dẫn import nên chưa cần cài package hoặc đặt `PYTHONPATH`.

## Notebook Kaggle

Upload [crawl_corpus_kaggle.ipynb](notebooks/crawl_corpus_kaggle.ipynb) lên Kaggle, bật Internet và chỉnh `ID_FROM` / `ID_TO` trong ô cấu hình. Cả hai đầu đều được tính vào khoảng chọn. Notebook tự chứa code, tải Parquet nguồn, crawl/resume và xuất corpus JSONL/Parquet cùng ZIP chứa raw/checkpoint. Không cần clone repo hoặc GPU.

Đặt `MAX_NEW = 10` để thử trước, rồi đổi thành `None` và chạy lại ô crawl. Khi đổi session, giữ output và thêm run đã giải nén vào Kaggle Input để dùng `RESUME_RUN_PATH`. Notebook có các snapshot code độc lập; sau khi sửa code crawl trong repo, chạy `python scripts/build_kaggle_notebook.py` để cập nhật notebook.

## Môi trường

Chạy từ thư mục gốc repo bằng PowerShell. Chỉ tạo môi trường khi chưa có `.venv`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/crawl.lock.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`requirements/crawl.txt` liệt kê dependencies trực tiếp; `requirements/crawl.lock.txt` khóa môi trường đã dùng. Môi trường đã kiểm tra là Windows với Python 3.14; không cam kết lock dùng nguyên vẹn trên mọi phiên bản Python.

## Chạy một lượt mới

Ví dụ chọn 1.000 ID từ 583 đến 1582. Dùng tên output chưa có manifest; `--id-stop` là cận trên không bao gồm:

```powershell
.\.venv\Scripts\python.exe scripts/crawl_corpus.py prepare --source data/links_corpus.parquet --out runs/crawl_example --size 1000 --id-start 583 --id-stop 1583
.\.venv\Scripts\python.exe -u scripts/crawl_corpus.py crawl --out runs/crawl_example --workers 4 --delay 1 --attempts 3 --max-new 10
.\.venv\Scripts\python.exe -u scripts/crawl_corpus.py crawl --out runs/crawl_example --workers 4 --delay 1 --attempts 3
.\.venv\Scripts\python.exe scripts/audit_corpus.py --out runs/crawl_example
.\.venv\Scripts\python.exe scripts/export_corpus.py --out runs/crawl_example
```

Chạy lại lệnh `crawl` để xử lý ID chưa có checkpoint; ID đã có checkpoint, kể cả lỗi, sẽ được bỏ qua. Giữ nguyên mã nguồn, dependencies, delay và attempts để resume cùng run. `crawl` tự sinh báo cáo; có thể chạy `report --out <run>` để tính lại báo cáo offline. `audit_corpus.py` yêu cầu run đã xử lý đủ ID.

Đầu ra chính: `corpus.parquet`, `corpus.jsonl`, `quality_report.json` và `quarantine.jsonl` trong output đã chọn. Accepted là kết quả kiểm tra tự động, vẫn cần rà nội dung.

## Kết quả đã có và resume run cũ

Run `runs/ids_583_1582_clean` đã có corpus 976 tài liệu accepted; 13 tài liệu cần xem lại và 11 rejected. Xem [kết quả](docs/crawl/CRAWL_RESULT_1000.md).

Giữ nguyên `data/` và `runs/` khi sắp xếp repo để bảo toàn đường dẫn trong manifest. Nội dung ba module được giữ nguyên byte khi chuyển từ `scripts/` sang `src/`; hash crawler vẫn được tính từ module thực thi, không phải wrapper. Các snapshot cũ vẫn nằm trong run gốc.

Run `runs/ids_583_1582` dùng crawler v3, vì vậy resume bằng `runs/ids_583_1582/crawler_snapshot.py` theo [hướng dẫn](docs/crawl/CRAWL_1000_IDS.md). Không sửa manifest để ép dùng phiên bản code khác.

- [Hướng dẫn mẫu 1.000 ID](docs/crawl/CRAWL_1000_IDS.md)
- [Thiết kế pipeline crawl](docs/crawl/CRAWL_PIPELINE.md)
- [Kết quả và các ID cần xử lý tiếp](docs/crawl/CRAWL_RESULT_1000.md)

Git lưu code, tests, tài liệu crawl, dependencies và các Parquet nguồn đang được track. Raw/checkpoint và corpus sinh ra nằm trong `runs/`, được ignore; PDF và file memory tham khảo local vẫn theo quy tắc ignore hiện có.
