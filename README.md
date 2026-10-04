# R2AI2026 Stage 3 — ViBioMIR

Repo phục vụ pipeline RAG của dự án ViBioMIR, chia theo các block trong [nguyen/pipeline.txt](nguyen/pipeline.txt). Block A (crawl, trích xuất, QC, export) đã chạy thật trên dữ liệu cuộc thi. Block A4 đến E (chunking, index, retrieval, bài nộp, đánh giá) đã có code chạy được đầu–cuối, nhưng chưa chạy với model thật trên corpus lớn. Chưa có fine-tune.

## Bố cục

```text
src/vibiomir/common/      Schema, chuẩn hóa văn bản, đọc/ghi và hash
src/vibiomir/corpus/      Block A: crawler.py, finalize.py, priority_probe.py, chunk.py (A4)
src/vibiomir/index/       Block B: bm25.py, embedding.py; CLI ở build.py
src/vibiomir/retrieval/   Block C: query.py, hybrid.py, rerank.py; CLI ở run.py
src/vibiomir/submission/  Block D: choose.py, validate.py, export.py; CLI ở build.py
src/vibiomir/evaluation/  Block E: labels.py, metrics.py, errors.py; CLI ở run.py
scripts/                  Một lệnh cho mỗi block, chỉ gọi code trong src/
notebooks/                Notebook crawl độc lập trên Kaggle
tests/                    Kiểm tra từng block, không cần mạng hay GPU
requirements/             crawl.txt cho Block A, rag.txt cho A4–E
docs/crawl/               Thiết kế, hướng dẫn chạy và kết quả crawl
data/                     Parquet nguồn và metadata nguồn
runs/                     Raw, checkpoint, corpus do Block A sinh ra (ngoài Git)
work/                     Chunk, index, ứng viên, bài nộp, báo cáo (ngoài Git)
```

Mỗi block là một thư mục trong `src/`, kèm đúng một script trong `scripts/`. Script chỉ đọc tham số rồi gọi hàm trong `src/`, không chứa thuật toán, nên cùng một logic dùng được từ script, notebook và test. Script tự thêm `src/` vào đường dẫn import nên chưa cần cài package hoặc đặt `PYTHONPATH`.

## Chạy pipeline A4 → E

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements/rag.txt

.\.venv\Scripts\python.exe scripts/chunk.py --corpus runs/<run>/corpus.parquet --out work/chunks
.\.venv\Scripts\python.exe scripts/index.py all --chunks work/chunks/chunks.parquet --out work/index --encoder bge-m3
.\.venv\Scripts\python.exe scripts/retrieve.py --chunks work/chunks/chunks.parquet --index work/index --queries data/query.parquet --out work/retrieval
.\.venv\Scripts\python.exe scripts/submit.py --candidates work/retrieval/candidates.jsonl --chunks work/chunks/chunks.parquet --corpus runs/<run>/corpus.parquet --links data/links_corpus.parquet --out work/submission --profile recall
```

Nhiều shard crawl thì truyền nhiều file vào `--corpus`. Kết quả nộp là `work/submission/submission.zip`.

Muốn chạy thử toàn bộ flow mà không tải model, dùng `--encoder hash` và `--reranker identity`. Hai tùy chọn này chỉ kiểm tra đường ống, không phản ánh chất lượng truy hồi.

`scripts/evaluate.py` lo phần đánh giá: `sheet` xuất phiếu để người gán nhãn, `collect` biến phiếu đã điền thành `labels.jsonl`, `score` tính Precision/Recall/F2 hai cấp và quy từng tài liệu bị mất về block gây ra. BTC không phát hành nhãn, nên `pseudo` chỉ dùng cho smoke test và báo cáo sẽ ghi rõ điểm đó là vòng tròn.

Model mặc định: `bge-m3` (568M) cho embedding và `bge-reranker-v2-m3` (568M) cho reranking. Các lựa chọn khác liệt kê trong docstring của [embedding.py](src/vibiomir/index/embedding.py) và [rerank.py](src/vibiomir/retrieval/rerank.py), gồm `qwen3-embedding-4b` và `qwen3-reranker-4b`. Mọi model trong hai danh sách đều là model mở, phát hành trước 01/08/2026 và không quá 15B tham số, theo quy định cuộc thi; trước khi nộp vẫn cần tự đối chiếu lại ngày phát hành và số tham số thực tế.

## Notebook Kaggle

Upload [crawl_corpus_kaggle.ipynb](notebooks/crawl_corpus_kaggle.ipynb) lên Kaggle, bật Internet và chỉnh `ID_FROM` / `ID_TO` trong ô cấu hình. Cả hai đầu đều được tính vào khoảng chọn. Notebook tự chứa code, tải Parquet nguồn, crawl/resume và xuất corpus JSONL/Parquet cùng ZIP chứa raw/checkpoint. Không cần clone repo hoặc GPU.

Đặt `MAX_NEW = 10` để thử trước, rồi đổi thành `None` và chạy lại ô crawl. Khi đổi session, giữ output và thêm run đã giải nén vào Kaggle Input để dùng `RESUME_RUN_PATH`. Notebook có các snapshot code độc lập; sau khi sửa code crawl trong repo, chạy `python scripts/build_kaggle_notebook.py` để cập nhật notebook.

Phần chẩn đoán nằm ngay trong notebook, tại mục **8. ZIP chẩn đoán**; không cần file hay ô Python rời. Output tự có `<run>_diagnostics.zip`, cập nhật sau mỗi log tiến độ và khi bước xử lý kết thúc. Có thể chạy lại mục 8 để tạo ZIP từ checkpoint hiện tại mà không tải lại URL.

Giải nén ZIP, mở `overview.html` để xem tiến độ, tốc độ/ETA, lỗi và QC. Gói gồm CSV từng ID/request/redirect/pending, log pip/crawl và traceback notebook, manifest/cấu hình, phiên bản môi trường, snapshot code và bằng chứng robots. Có tối đa 10 mẫu record/raw để debug parser; tổng raw mẫu tối đa 10 MiB, mỗi JSON mẫu tối đa 1 MiB. `sample_manifest.json` ghi mẫu được lấy hoặc bỏ qua. Bản đầy đủ `<run>.zip` tại mục 9 vẫn giữ toàn bộ raw/checkpoint để resume.

## Môi trường

Chạy từ thư mục gốc repo bằng PowerShell. Chỉ tạo môi trường khi chưa có `.venv`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/crawl.lock.txt
.\.venv\Scripts\python.exe -m pip install -r requirements/rag.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`requirements/crawl.txt` liệt kê dependencies trực tiếp của Block A; `requirements/crawl.lock.txt` khóa môi trường đã dùng. `requirements/rag.txt` là phần A4–E; `torch` nên cài theo bản CUDA của máy từ trang pytorch.org thay vì wheel mặc định. Môi trường đã kiểm tra là Windows với Python 3.13/3.14; không cam kết lock dùng nguyên vẹn trên mọi phiên bản Python.

Toàn bộ test chạy offline. `tests/test_pipeline.py` chạy A4 → E trên corpus mẫu bằng `--encoder hash` nên không cần GPU hay tải model; nó kiểm tra đường ống, không kiểm tra chất lượng truy hồi.

## Chạy một lượt mới

Ví dụ chọn 1.000 ID từ 583 đến 1582. Dùng tên output chưa có manifest; `--id-stop` là cận trên không bao gồm:

```powershell
.\.venv\Scripts\python.exe scripts/crawl.py prepare --source data/links_corpus.parquet --out runs/crawl_example --size 1000 --id-start 583 --id-stop 1583
.\.venv\Scripts\python.exe -u scripts/crawl.py crawl --out runs/crawl_example --workers 4 --delay 1 --attempts 3 --max-new 10
.\.venv\Scripts\python.exe -u scripts/crawl.py crawl --out runs/crawl_example --workers 4 --delay 1 --attempts 3
.\.venv\Scripts\python.exe scripts/finalize.py audit --out runs/crawl_example
.\.venv\Scripts\python.exe scripts/finalize.py export --out runs/crawl_example
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
