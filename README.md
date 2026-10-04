# R2AI2026 Stage 3 — ViBioMIR

Repo phục vụ pipeline RAG của dự án ViBioMIR, chia theo các block trong [docs/note/pipeline.txt](docs/note/pipeline.txt). Block A (crawl, trích xuất, QC, export) được đóng gói trong hai notebook độc lập. Block A4 đến E (chunking, index, retrieval, bài nộp, đánh giá) đã có code chạy được đầu–cuối, nhưng chưa chạy với model thật trên corpus lớn. Chưa có fine-tune.

## Bố cục

```text
src/vibiomir/common/      Schema, chuẩn hóa văn bản, đọc/ghi và hash
src/vibiomir/corpus/      Block A4: chunk.py chia corpus thành các đoạn có vị trí nguồn
src/vibiomir/index/       Block B: bm25.py, embedding.py; CLI ở build.py
src/vibiomir/retrieval/   Block C: query.py, hybrid.py, rerank.py; CLI ở run.py
src/vibiomir/submission/  Block D: choose.py, validate.py, export.py; CLI ở build.py
src/vibiomir/evaluation/  Block E: labels.py, metrics.py, errors.py; CLI ở run.py
scripts/                  Lệnh chạy pipeline A4–E, gọi code trong src/
notebooks/                Hai notebook crawl độc lập, chứa code và dependencies
crawler_minh/             Bộ crawler riêng của Minh
tests/                    Kiểm tra pipeline A4–E offline
requirements/             rag.txt cho pipeline A4–E
docs/                     Ghi chú pipeline, tài liệu tham khảo và thiết kế giải pháp
data/                     Parquet nguồn và metadata nguồn
runs/                     Raw, checkpoint, corpus do Block A sinh ra (ngoài Git)
notebooks/runs/           Output khi chạy notebook local (ngoài Git)
work/                     Chunk, index, ứng viên, bài nộp, báo cáo (ngoài Git)
```

Các script A4–E đọc tham số rồi gọi hàm trong `src/`. Script tự thêm `src/` vào đường dẫn import nên chưa cần cài package hoặc đặt `PYTHONPATH`. Hai notebook crawl tự chứa snapshot Python; các file code được giải nén vào thư mục run khi chạy.

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

Đặt `MAX_NEW = 10` để thử trước, rồi đổi thành `None` và chạy lại ô crawl. Khi đổi session, giữ output và thêm run đã giải nén vào Kaggle Input để dùng `RESUME_RUN_PATH`.

Notebook corpus dùng chung engine với `crawl_domain_samples`: User-Agent trình duyệt, timeout 20/45 giây, ngân sách 180 giây/URL và Selenium cho URL Requests lỗi, trang JS hoặc text rỗng/QC lỗi. `RESPECT_ROBOTS` chỉnh ở ô cấu hình. Để nâng cấp run cũ hoặc thử lại lỗi, dùng `RECOVERY_RUN_PATH` và `RUN_TAG` mới. Kết quả cuối chọn engine có QC tốt hơn, giữ Requests khi tương đương; nội dung Selenium qua QC được xuất vào corpus, lỗi Requests vẫn được giữ riêng.

Khi bật Selenium, notebook kiểm tra Chrome trước lượt Requests. Trên Kaggle/Linux dùng apt, notebook tự cài thư viện Chrome còn thiếu (gồm ATK); nếu Chrome không khởi động được thì dừng sớm và lưu lỗi/log. Parser riêng của 120ask lấy câu hỏi/câu trả lời; cnkang lấy thân bài và bỏ menu/bài liên quan.

Phần chẩn đoán nằm ngay trong notebook, tại mục **8. ZIP chẩn đoán**; không cần file hay ô Python rời. Output tự có `<run>_diagnostics.zip`, cập nhật sau mỗi log tiến độ và khi bước xử lý kết thúc. Có thể chạy lại mục 8 để tạo ZIP từ checkpoint hiện tại mà không tải lại URL.

Giải nén ZIP, mở `overview.html` để xem tiến độ, tốc độ/ETA, lỗi và QC. Gói gồm CSV từng ID/request/redirect/pending, log pip/crawl và traceback notebook, manifest/cấu hình, phiên bản môi trường, snapshot code và bằng chứng robots. Có tối đa 10 mẫu record/raw để debug parser; tổng raw mẫu tối đa 10 MiB, mỗi JSON mẫu tối đa 1 MiB. `sample_manifest.json` ghi mẫu được lấy hoặc bỏ qua. Bản đầy đủ `<run>.zip` tại mục 9 vẫn giữ toàn bộ raw/checkpoint để resume.

## Notebook kiểm tra domain

[crawl_domain_samples.ipynb](notebooks/crawl_domain_samples.ipynb) chứa sẵn 97 URL mẫu của 97 hostname, snapshot crawler và code probe. Chạy các ô từ trên xuống trên Kaggle, Colab hoặc Jupyter có Internet. Notebook tự cài dependencies và lưu phiên bản cùng output.

Đặt `MAX_NEW = 10` để chạy thử; dùng `RESUME_RUN_DIR` để tiếp tục output cùng phiên bản code. Dùng `RECOVERY_RUN_DIR` với một run mới để thử lại nhóm lỗi và tái sử dụng raw hợp lệ bằng parser mới. `BROWSER_TEST_MODE` điều khiển bước đối chiếu Selenium cho URL Requests lỗi hoặc trích xuất lỗi/rỗng. Sau khi đổi snapshot, giữ `RESUME_RUN_DIR = None` và tạo run mới.

Output gồm bảng `ket_qua.csv/html`, kết quả Requests/Selenium, lỗi theo loại, raw, ảnh chụp và snapshot code. `browser_runtime.json` / `browser_preflight.json` cùng log Chrome ghi tình trạng môi trường; `summary.json` tách số URL phục hồi truy cập và cải thiện nội dung nhờ Selenium. Tải ZIP trong Output của Kaggle hoặc qua các liên kết notebook hiển thị.

## Môi trường RAG

Chạy từ thư mục gốc repo bằng PowerShell. Chỉ tạo môi trường khi chưa có `.venv`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/rag.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`requirements/rag.txt` phục vụ phần A4–E; `torch` nên cài theo bản CUDA của máy từ trang pytorch.org thay vì wheel mặc định. Hai notebook crawl cài dependencies trong chính notebook; môi trường của `crawler_minh` được mô tả trong README riêng của bộ crawler đó.

Toàn bộ test chạy offline. `tests/test_pipeline.py` chạy A4 → E trên corpus mẫu bằng `--encoder hash` nên không cần GPU hay tải model; nó kiểm tra đường ống, không kiểm tra chất lượng truy hồi.

## Dữ liệu và resume

Giữ nguyên Parquet nguồn trong `data/` và các thư mục run để bảo toàn ID, hash và đường dẫn trong manifest. Pipeline RAG nhận `corpus.parquet` do notebook xuất; raw/checkpoint và corpus đã chạy tiếp tục nằm trong `runs/` hoặc `notebooks/runs/` ở máy local.

Resume dùng cấu hình và snapshot của cùng run. Recovery tạo run mới để thử lại lỗi hoặc đổi code/cấu hình. Corpus accepted là kết quả QC tự động, vẫn cần rà nội dung.

Git lưu hai notebook crawl, bộ `crawler_minh`, pipeline RAG, dữ liệu nguồn và tài liệu dự án. Output, cache và file tạm local được ignore theo `.gitignore`.
