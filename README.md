# R2AI2026 Stage 3 — ViBioMIR

Repo phục vụ pipeline RAG của dự án ViBioMIR, chia theo các block trong [docs/note/pipeline.txt](docs/note/pipeline.txt). Block A (crawl, trích xuất, QC, export) được đóng gói trong notebook crawl corpus tự upload Hugging Face. Block A4 đến E (chunking, index, retrieval, bài nộp, đánh giá) đã có code chạy được đầu–cuối, nhưng chưa chạy với model thật trên corpus lớn. Chưa có fine-tune.

## Bố cục

```text
src/vibiomir/common/      Schema, chuẩn hóa văn bản, đọc/ghi và hash
src/vibiomir/corpus/      Block A4: chunk.py chia corpus thành các đoạn có vị trí nguồn
src/vibiomir/index/       Block B: bm25.py, embedding.py; CLI ở build.py
src/vibiomir/retrieval/   Block C: query.py, hybrid.py, rerank.py; CLI ở run.py
src/vibiomir/submission/  Block D: choose.py, validate.py, export.py; CLI ở build.py
src/vibiomir/evaluation/  Block E: labels.py, metrics.py, errors.py; CLI ở run.py
scripts/                  Lệnh chạy pipeline A4–E, gọi code trong src/
notebooks/                Notebook crawl corpus và kiểm tra domain, chứa code và dependencies
crawler_minh/             Bộ crawler riêng của Minh
tests/                    Kiểm tra pipeline A4–E offline
requirements/             rag.txt cho pipeline A4–E
docs/                     Ghi chú pipeline, tài liệu tham khảo và thiết kế giải pháp
data/                     Parquet nguồn và metadata nguồn
runs/                     Raw, checkpoint, corpus do Block A sinh ra (ngoài Git)
notebooks/runs/           Output khi chạy notebook local (ngoài Git)
work/                     Chunk, index, ứng viên, bài nộp, báo cáo (ngoài Git)
```

Các script A4–E đọc tham số rồi gọi hàm trong `src/`. Script tự thêm `src/` vào đường dẫn import nên chưa cần cài package hoặc đặt `PYTHONPATH`. Các notebook crawl tự chứa snapshot Python; các file code được giải nén vào thư mục run khi chạy.

## Chạy pipeline từ dữ liệu crawl đến bài nộp

Hướng dẫn đầy đủ từng bước, thời gian đo được và cách xử lý sự cố: [docs/solution/run_guide.md](docs/solution/run_guide.md).

```powershell
.\env\Scripts\python.exe -m pip install -r requirements/rag.txt

.\env\Scripts\python.exe scripts/vibiomir.py prepare --source nguyen/output/runs/batch01_nguyen --limit 30000
.\env\Scripts\python.exe scripts/vibiomir.py chunk
.\env\Scripts\python.exe scripts/vibiomir.py index all --encoder bge-m3
.\env\Scripts\python.exe scripts/vibiomir.py retrieve --keyword-variant
.\env\Scripts\python.exe scripts/vibiomir.py submit --links data/links_corpus.parquet --profile recall
```

Mọi đường dẫn mặc định đều trỏ vào `work/`. `prepare.py` đọc thư mục run có `records/` hoặc file `.parquet`/`.json`/`.jsonl` xuất từ crawler; nhiều nguồn thì truyền nhiều đường dẫn vào `--source`. Kết quả nộp là `work/submission/submission.zip`.

Muốn chạy thử toàn bộ flow mà không tải model, dùng `--encoder hash` và `--reranker identity`. Hai tùy chọn này chỉ kiểm tra đường ống, không phản ánh chất lượng truy hồi.

`scripts/vibiomir.py evaluate` lo phần đánh giá: `sheet` xuất phiếu để người gán nhãn, `collect` biến phiếu đã điền thành `labels.jsonl`, `score` tính Precision/Recall/F2 hai cấp và quy từng tài liệu bị mất về block gây ra. BTC không phát hành nhãn, nên `pseudo` chỉ dùng cho smoke test và báo cáo sẽ ghi rõ điểm đó là vòng tròn.

Model mặc định: `bge-m3` (568M) cho embedding và `bge-reranker-v2-m3` (568M) cho reranking. Các lựa chọn khác liệt kê trong docstring của [embedding.py](src/vibiomir/index/embedding.py) và [rerank.py](src/vibiomir/retrieval/rerank.py), gồm `qwen3-embedding-4b` và `qwen3-reranker-4b`. Mọi model trong hai danh sách đều là model mở, phát hành trước 01/08/2026 và không quá 15B tham số, theo quy định cuộc thi; trước khi nộp vẫn cần tự đối chiếu lại ngày phát hành và số tham số thực tế.

## Notebook Kaggle

Upload [crawl_corpus_kaggle_hf_upload.ipynb](notebooks/crawl_corpus_kaggle_hf_upload.ipynb) lên Kaggle, bật Internet và chỉnh `ID_FROM` / `ID_TO` trong ô cấu hình. Cả hai đầu đều được tính vào khoảng chọn. Notebook tự chứa code, tải Parquet nguồn, crawl/resume và xuất corpus JSONL/Parquet cùng ZIP chứa raw/checkpoint. Không cần clone repo hoặc GPU.

Mục 10 tự upload output đã hoàn tất vào `AncientWings/AncientWings_R2AI_STAGE3_ds`. Trước Run All, tạo và bật Kaggle Secret `HF_TOKEN` có quyền ghi vào dataset. Đặt `HF_UPLOAD_ENABLED = False` nếu chỉ muốn lưu output trên Kaggle. Mặc định upload corpus, diagnostics và manifest; `HF_UPLOAD_ARCHIVE = False` giữ ZIP raw/checkpoint trong Kaggle Output, không đưa lên HF. Các artifact được phân biệt theo tên run; manifest ghi khoảng ID, số bản ghi và SHA-256. Run còn pending chưa upload; lỗi mạng có thể chạy lại riêng mục 10. Nếu crawl lại cùng khoảng ID với cấu hình khác, dùng `RUN_TAG` mới.

[delete_hf_archives.ipynb](notebooks/delete_hf_archives.ipynb) có một cell dọn `archives/` trên dataset HF, gồm các blob LFS của archive trong lịch sử để thu hồi dung lượng. Cell dùng Kaggle Secret `HF_TOKEN` hoặc token local, không chạy cùng uploader. Xoá blob archive là vĩnh viễn; giữ bản ZIP raw/checkpoint ở Kaggle hoặc local nếu còn cần resume. Cell không super-squash toàn bộ lịch sử repo.

Đặt `MAX_NEW = 10` để thử trước, rồi đổi thành `None` và chạy lại ô crawl. Khi đổi session, giữ output và thêm run đã giải nén vào Kaggle Input để dùng `RESUME_RUN_PATH`.

Để cứu run đã crawl xong nhưng audit/export thất bại, dùng notebook mới và đặt `POSTPROCESS_ONLY = True`, đúng `ID_FROM` / `ID_TO`, cùng `RESUME_RUN_PATH` tới **thư mục run đầy đủ** trong Kaggle Input. Giữ `RESUME_RUN_PATH = None` nếu output vẫn ở session hiện tại. Có thể đặt `SOURCE_PARQUET` tới file nguồn trong Input; nguồn vẫn phải đúng hash đã chốt. Chạy các ô từ trên xuống: mục 6 bỏ qua Requests/Selenium, mục 7 chạy report/audit/export trên checkpoint cũ. Auditor/exporter được cập nhật; snapshot crawler/runner/probe, cấu hình crawl, manifest nguồn, raw và records được giữ nguyên. ZIP diagnostics chỉ chứa một số mẫu, không đủ để phục hồi toàn run.

Raw rỗng hoặc HTML không parse được được ghi cờ chẩn đoán; sai hash, sai ID/URL hoặc thiếu raw của bản ghi extracted vẫn chặn xuất corpus. Khi một bước xử lý lỗi, notebook tạo ZIP checkpoint đầy đủ và diagnostics trước khi báo lại lỗi gốc. `postprocess_status.json` ghi kết quả audit/export; `notebook_manifest.json` chỉ ghi `complete = True` sau khi đủ checkpoint và các kiểm tra bắt buộc đạt. Upload kiểm tra lại bằng chứng audit/export và hash corpus trước khi đọc secret; manifest cũ chỉ ghi hết pending chưa đủ điều kiện upload. Nếu chính việc tạo ZIP gặp lỗi I/O, lỗi đó được báo riêng và checkpoint gốc vẫn được giữ lại.

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

`requirements/rag.txt` phục vụ phần A4–E; `torch` nên cài theo bản CUDA của máy từ trang pytorch.org thay vì wheel mặc định. Các notebook crawl cài dependencies trong chính notebook; môi trường của `crawler_minh` được mô tả trong README riêng của bộ crawler đó.

Toàn bộ test chạy offline. `tests/test_pipeline.py` chạy A4 → E trên corpus mẫu bằng `--encoder hash` nên không cần GPU hay tải model; nó kiểm tra đường ống, không kiểm tra chất lượng truy hồi.

## Dữ liệu và resume

Giữ nguyên Parquet nguồn trong `data/` và các thư mục run để bảo toàn ID, hash và đường dẫn trong manifest. Pipeline RAG nhận `corpus.parquet` do notebook xuất; raw/checkpoint và corpus đã chạy tiếp tục nằm trong `runs/` hoặc `notebooks/runs/` ở máy local.

Resume dùng cấu hình và snapshot của cùng run. Recovery tạo run mới để thử lại lỗi hoặc đổi code/cấu hình. Corpus accepted là kết quả QC tự động, vẫn cần rà nội dung.

Git lưu các notebook, bộ `crawler_minh`, pipeline RAG, dữ liệu nguồn và tài liệu dự án. Output, cache và file tạm local được ignore theo `.gitignore`.
