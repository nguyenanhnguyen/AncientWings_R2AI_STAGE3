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

Notebook corpus dùng **EFetch GET cho PubMed**, **curl_cffi/Chrome cho Long Châu**; các website còn lại dùng engine Requests/Selenium cùng với `crawl_domain_samples`: User-Agent trình duyệt, timeout 20/45 giây, ngân sách 180 giây/URL và Selenium cho URL Requests lỗi, trang JS hoặc text rỗng/QC lỗi. `RESPECT_ROBOTS` chỉnh lượt crawl website ở ô cấu hình. Để nâng cấp run cũ hoặc thử lại lỗi, dùng `RECOVERY_RUN_PATH` và `RUN_TAG` mới. Kết quả Requests/Selenium chọn engine có QC tốt hơn, giữ Requests khi tương đương.

Nguồn crawl mới là `links_corpus_vi_en_zh.parquet` gồm **1.220.598 URL**, ghim revision `71be0e1239a19dfd7a717e2bc13e3bec21bd0334` và cùng SHA-256 với notebook domain samples. ID gốc không liên tục, từ 583 đến 7.466.161; chọn batch bằng `ID_FROM` / `ID_TO`. Run mới mặc định có hậu tố `_synced_vi_en_zh_efetch_longchau`. Resume chỉ nhận cùng nguồn/code/cấu hình; dùng recovery để nâng cấp run cũ. `POSTPROCESS_ONLY` vẫn dùng snapshot gốc khi manifest của run mang hash nguồn cũ.

Run chỉ có PubMed hoặc Long Châu không khởi động Chrome. Khi crawl các website khác bằng Selenium, notebook kiểm tra Chrome trước lượt Requests. Trên Kaggle/Linux dùng apt, notebook tự cài thư viện Chrome còn thiếu (gồm ATK); nếu Chrome không khởi động được thì dừng sớm và lưu lỗi/log. Parser riêng của 120ask lấy câu hỏi/câu trả lời; cnkang lấy thân bài và bỏ menu/bài liên quan.

`PUBMED_USE_EFETCH = True` mặc định trong **notebook corpus chính**: lấy PMID từ URL gốc, EFetch GET tối đa **100 PMID/batch**, **1 worker**, nghỉ ít nhất **0,5 giây** sau request trước. Ghép XML theo PMID, giữ nguyên corpus `id`/`url`; `text` gồm title và toàn bộ đoạn abstract, nhãn `Label`/`NlmCategory` và `OtherAbstract` nếu có. API không cung cấp toàn văn bài báo. `NCBI_EMAIL`/`NCBI_API_KEY` có thể điền ở ô cấu hình hoặc qua biến môi trường; credential không đi vào settings/log. Abstract ngắn vẫn qua QC; bản ghi thiếu PMID hoặc không có abstract được giữ ở checkpoint/review, không xuất vào corpus accepted.

EFetch hoạt động cả khi `BROWSER_TEST_MODE = 'off'`; không gọi trang PubMed hoặc Selenium cho batch API lỗi. `pubmed_batches/` và XML gốc được lưu trước các record ID, nên resume phục hồi phần ghi dở mà không GET lại batch đã lưu. HTTP 400 có Timeout/Empty Response được retry theo body; batch lỗi giữ pending, tự chia nhỏ và tiếp tục batch khác, cuối lượt thử pending thêm một vòng. Cooldown dài hoặc nhiều batch liên tiếp không lấy được bản ghi thì hoãn để resume; không báo complete khi còn pending. Default 5 attempts, read timeout 90 giây, budget 300 giây; `Retry-After` được giữ cả qua resume. `MAX_NEW` tính URL corpus mới đã lên lịch, kể cả khi nhiều ID dùng cùng một PMID; retry không tính hai lần. Xem `pubmed_results.csv`, `pubmed_pending.csv`, `pubmed_missing_pmids.csv`, `pubmed_no_abstract.csv`, `pubmed_review.csv`, `pubmed_requests.jsonl` và `pubmed_efetch_summary.json` trong ZIP đầy đủ. Audit đối chiếu title/từng đoạn abstract/nhãn với XML độc lập trước khi export.

Resume EFetch cũ tự nâng cấp riêng transport sau kiểm tra hash/parser/schema, giữ core/runner và toàn bộ XML/record/manifest nguồn. Checkpoint full ZIP được tạo định kỳ; có HF_TOKEN quyền ghi thì backup ZIP/checksum trong một commit ở `checkpoints/<run>/`, tách khỏi upload corpus hoàn tất. [Hướng dẫn phục hồi 6.000/110.000 URL và checkpoint Kaggle](docs/pubmed_efetch_resume.md).

Nâng cấp run Selenium cũ bằng `RUN_TAG` mới và `RECOVERY_RUN_PATH`: reuse raw hợp lệ của các website khác; PubMed HTML cũ được lấy mới qua EFetch. `POSTPROCESS_ONLY` vẫn xử lý run cũ mà không crawl; Long Châu legacy chưa tái trích cần recovery trước export. Notebook **domain samples** dùng Selenium trực tiếp cho PubMed để kiểm tra truy cập website/IP; ở notebook corpus, chỉ khi đặt `PUBMED_USE_EFETCH = False` mới dùng lựa chọn legacy `PUBMED_SELENIUM_FIRST`. Sửa code [pubmed_efetch.py](scripts/pubmed_efetch.py), [corpus_runner.py](scripts/corpus_runner.py) hoặc [corpus_audit.py](scripts/corpus_audit.py), rồi chạy `python scripts/build_longchau_notebooks.py` để nhúng lại cả PubMed và Long Châu.

Long Châu dùng `LONGCHAU_USE_CURL = True`, 1 worker, delay mặc định 5 giây, giữ TLS/session/cookie, retry hữu hạn và cooldown qua resume/recovery. Parser v2 [longchau.py](scripts/longchau.py) giữ sapo, thân bài DOM và đủ các phần y khoa/FAQ của `/benh/` từ JSON đã xác minh đúng bài; tách author/reviewer/ngày và nhóm liên kết “Xem thêm” khỏi text. Không fallback trafilatura/Selenium trong route mặc định. Runner chung lưu checkpoint cho mọi engine và khi dừng/ngắt; diagnostics dùng tiến độ chung theo source ID. Run parser cũ dùng recovery từ ZIP đầy đủ. [Hướng dẫn phục hồi run 204274–205274](docs/longchau_resume_v2.md). `check_longchau_50.ipynb` là file local ngoài Git, tạo bằng `python scripts/build_longchau_smoke_notebook.py` ([builder](scripts/build_longchau_smoke_notebook.py)); chạy độc lập trên Kaggle, chọn 50 URL nguồn phân tầng, không upload HF. [Kết quả local trước v2 và nguồn](docs/longchau_crawl.md).

Khi ngắt lượt Requests chạy trực tiếp trong notebook domain, crawler dừng lấy URL mới và chờ request đang chạy ghi checkpoint trong giới hạn thời gian đã cấu hình. Chạy lại ô crawl với cùng thư mục run để tiếp tục các URL còn thiếu. Ngắt giữa lúc ghi checkpoint và cập nhật kết quả cuối được sửa khi resume; Selenium chỉ thử tiếp URL chưa có checkpoint browser. Run còn gián đoạn cần resume mục crawl trước khi audit/export/upload.

Phần chẩn đoán nằm ngay trong notebook, tại mục **8. ZIP chẩn đoán**; không cần file hay ô Python rời. Output tự có `<run>_diagnostics.zip`, cập nhật sau mỗi log tiến độ và khi bước xử lý kết thúc. Có thể chạy lại mục 8 để tạo ZIP từ checkpoint hiện tại mà không tải lại URL.

Giải nén ZIP, mở `overview.html` để xem tiến độ, tốc độ/ETA, lỗi và QC. Gói gồm CSV từng ID/request/redirect/pending, log pip/crawl và traceback notebook, manifest/cấu hình, phiên bản môi trường, snapshot code và bằng chứng robots. Có tối đa 10 mẫu record/raw để debug parser; tổng raw mẫu tối đa 10 MiB, mỗi JSON mẫu tối đa 1 MiB. `sample_manifest.json` ghi mẫu được lấy hoặc bỏ qua. Bản đầy đủ `<run>.zip` tại mục 9 vẫn giữ toàn bộ raw/checkpoint để resume.

## Notebook review chất lượng dữ liệu HF

[review_hf_data_quality.ipynb](notebooks/review_hf_data_quality.ipynb) kiểm tra corpus `AncientWings/AncientWings_R2AI_STAGE3_ds`, chạy độc lập trên Kaggle/Colab/Jupyter và không cần GPU. Trên Kaggle bật Internet, thêm Secret `HF_TOKEN` có quyền đọc dataset rồi Run All. Đặt `HF_REVISION` theo commit của run train cần review; mặc định notebook ghim commit mới nhất. Dùng `LOCAL_CORPUS_DIR` và `LOCAL_SOURCE_DIR` nếu đã tải dữ liệu local.

Notebook quét Parquet theo batch vào SQLite, kiểm tra lỗi text/hash/status, duplicate và ID xung đột xuyên shard, đối chiếu ID/URL với ViBioMIR gốc, phân bố nguồn/ngôn ngữ và độ phủ link. Output gồm biểu đồ, `REPORT.md`, `summary.json`, phiếu `manual_review.csv`, lexical query probe và ZIP báo cáo. Bật `RUN_TOKENIZER` để đo nguy cơ truncation theo tokenizer/max_length đang train. Các kiểm tra trên mẫu và heuristic được ghi rõ; corpus không có relevance labels nên notebook không tính recall/F2 hay tự kết luận nguyên nhân train kém.

Code helper được nhúng sẵn, không cần clone repo khi chạy notebook. Sau khi sửa [scripts/hf_data_quality.py](scripts/hf_data_quality.py) hoặc nội dung notebook trong builder, chạy `python scripts/build_data_quality_notebook.py` để tạo lại notebook.

Nếu snapshot ViBioMIR gốc trên HF bị gỡ, notebook vẫn xuất review corpus và ghi rõ đối chiếu nguồn chưa đo. Dùng `LOCAL_SOURCE_DIR` trỏ tới hai file gốc `data/links_corpus.parquet` và `data/query.parquet` (đúng SHA-256) để đo đầy đủ; file `links_corpus_vi_en_zh.parquet` hiện tại có số link/hash khác nên không thay thế ngầm. Khi run cũ đã quét xong nhưng lỗi ở bước sau, đặt `RESUME_REVIEW_DIR` tới thư mục output có `config.json` và `features.sqlite`, giữ nguyên cấu hình quét để tiếp tục từ SQLite mà không đọc lại text toàn corpus. Các CSV corpus được lưu ngay sau từng bước phân tích.

## Notebook kiểm tra domain

[crawl_domain_samples.ipynb](notebooks/crawl_domain_samples.ipynb) thử **94 hostname của corpus mới**, tối đa 20 URL mới không trùng nhau/hostname, tổng **1.764 URL**. 87 hostname đủ 20 mẫu; 7 hostname chỉ có 1–11 URL nguồn nên lấy toàn bộ và ghi số thiếu. Mẫu seed 20261014 loại các mẫu VOV/Long Châu và URL PubMed đã kiểm tra, giữ ID/URL gốc cùng revision/hash của `links_corpus_vi_en_zh.parquet`. `TARGET_DOMAINS = None` chọn tất cả; có thể đặt tuple hostname để thử một phần. Không cần tải Parquet hoặc clone repo trên Kaggle.

Mặc định `MAX_NEW = None`, `WORKERS = 2`, `LOG_EVERY = 5` để thử toàn bộ mẫu. Bật Internet rồi Run All, không cần GPU; toàn bộ lượt thử có thể mất nhiều giờ. PubMed mặc định đi Selenium trực tiếp; Long Châu dùng curl_cffi/1 worker/parser chung với corpus chính; domain còn lại dùng Requests rồi Selenium khi HTTP/mạng/trích xuất/QC lỗi. Dùng `RESUME_RUN_DIR` để tiếp tục cùng mẫu/code; lỗi Long Châu mặc định được thử lại riêng, success hợp lệ giữ nguyên. Nâng cấp notebook cũ hoặc thử lại lỗi domain khác cần run mới; `RECOVERY_RUN_DIR` tái sử dụng raw hợp lệ cho ID/URL trùng mẫu.

`IP_CHECK_ENABLED = True` đo IP đầu ra của Requests và Chrome qua [ipify](https://www.ipify.org/), ghi DNS và một lượt homepage đối chứng/hostname với timeout/ngân sách hữu hạn. `IP_RECHECK_ON_RESUME = True` đo lại khi resume, giữ lịch sử trong `network_history/`. Có thể tắt riêng homepage hoặc phép đo IP Chrome. Lỗi dịch vụ đo IP được ghi lại và không ngăn crawl trang mẫu; chỉ ghi sự có mặt của biến proxy, không ghi giá trị proxy.

Mở `ip_block_report.html` hoặc CSV để xem kết luận theo hostname, IP từng engine, số 403/429 và homepage đối chứng. `ip_url_evidence.csv` giữ đoạn thông báo và đường dẫn raw/screenshot của từng ID/engine. `IP_BLOCK_MESSAGE` là trang thông báo rõ chặn IP; `ACCESS_BLOCK_SUSPECTED` chỉ nghi ngờ chặn truy cập/anti-bot, **403 không tự chứng minh chặn IP**. Chạy cùng notebook ở Kaggle/local để đối chiếu môi trường; IP đo qua dịch vụ bên ngoài có thể khác theo proxy hoặc đích truy cập.

Output gồm bảng kết quả, báo cáo IP, `network_check.json`, `network_controls/`, raw, ảnh chụp và snapshot code. Báo cáo/ZIP được tạo trước khi crawl và cập nhật cả khi ngắt cell; ô cuối có thể tạo lại từ checkpoint mà không gọi mạng. Tải ZIP trong Output của Kaggle hoặc qua các liên kết notebook. Sửa helper rồi chạy `python scripts/build_domain_samples_notebook.py` để nhúng lại code và mẫu từ Parquet local đúng hash; builder giữ danh sách loại trừ và chọn mẫu có thể tái lập.

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
