# Chạy 60.000 bản ghi crawl trên RTX 2050 4GB đến `submission.zip`

Chạy PowerShell từ thư mục gốc dự án. Cấu hình này dùng **model thật**, dành cho một GPU RTX 2050 4GB. Lệnh điều phối chạy các khâu, lưu log và tiếp tục được khi bị ngắt. Crawl tiếp tục ghi dữ liệu vào run hiện tại; pipeline đọc một snapshot rồi chỉ dùng corpus đã đóng băng.

**Trạng thái xác minh:** máy nhận RTX 2050 4096 MiB qua `nvidia-smi`, nhưng môi trường `env` được kiểm tra đang có `torch 2.14.1+cpu`, `torch.cuda.is_available() == False`. Chưa chạy encode/rerank model thật trên GPU và chưa có điểm thi cho cấu hình mới. Tốc độ của lượt `hash`/`identity` 30k cũ không dùng để dự báo lượt này. Pilot đo tốc độ và VRAM tại máy trước khi chạy dài.

## 1. Cấu hình local

| Khâu | Cách chạy |
|---|---|
| A2–A3 | Đọc 60.000 bản ghi theo ID, lọc lỗi tải/trang chủ/template, giữ bài `review`, bảo toàn ID và nguồn |
| A4 | Chunk đích 320 token, overlap 80, trần 768 theo bộ đếm repo; giữ offset nguồn |
| B0 | Pilot mẫu phân tầng theo độ dài, gồm đoạn dài nhất; đo batch 2/4/8/16 cho từng model |
| B1 | BM25 với token Việt/Anh và unigram + bigram CJK |
| B2 | **BGE-M3 + Qwen3-Embedding-0.6B**, fp16, SDPA, hai index riêng, chạy lần lượt |
| C1 | Query gốc, biến thể bỏ lời xã giao cho BM25; **Qwen3-4B NF4** dịch Anh/Trung khi corpus có ngôn ngữ đó |
| C2 | Top 300/kênh, weighted RRF, giữ tối đa 600 rồi chọn tối đa 200 để rerank, tối đa 4 chunk/document |
| C3 | **BGE-reranker-v2-m3 + Qwen3-Reranker-0.6B**, chạy lần lượt, trung bình hai điểm; lưu điểm riêng |
| D | Giữ 100 ứng viên/query; xuất `recall` và `balanced`, kiểm tra đủ query, ID chính thức, cắt lại chunk từ nguồn |
| E | Công cụ gán nhãn người và đánh giá; chỉ tính F2 khi có nhãn phù hợp |

Model embedding/reranker 4B fp16 cần riêng khoảng 8GB trọng số nên không thuộc profile 4GB. Hai model nhỏ chạy nối tiếp cung cấp các kênh bổ sung; **chưa có bằng chứng đây là tổ hợp đạt điểm cao nhất**. Điểm sigmoid/yes-no và trung bình ensemble chưa được hiệu chỉnh thành xác suất liên quan. Ngưỡng bài nộp, trọng số dịch 0,5 và giới hạn ứng viên là điểm xuất phát để đo.

Qwen3-4B NF4 cần thử trên máy vì activation/KV cache còn dùng VRAM ngoài trọng số. Nếu không vừa, dùng lựa chọn nhỏ hơn ở mục 7. Dịch chỉ thêm kênh tìm kiếm; `chunk_text` luôn lấy từ corpus. Bản dịch đổi chữ số, rỗng, thiếu dấu hiệu ngôn ngữ đích hoặc hết ngân sách sinh bị loại và ghi `rejected.jsonl`. Kiểm tra này không bảo đảm đúng ngữ nghĩa, cần xem một số mẫu.

Theo `pipeline.txt`, nhánh teacher 32B → student cần Kaggle T4×2 và dev do người gán nhãn. Lượt local này chạy zero-shot. Chưa tự huấn luyện bằng 1.200 truy vấn thi, chưa có student được chứng minh tốt hơn. GraphRAG trong tài liệu tham khảo cũng chưa có triển khai/đo kiểm để đưa vào bài nộp này.

## 2. Cài môi trường CUDA

Máy đang dùng Python 3.13 x64, driver NVIDIA nhận RTX 2050; `env` hiện có `torch 2.14.1+cpu`, nên chưa thể chạy CUDA. Lỗi `WinError 32` ở `pip-unpack-...torch...whl` là file tạm bị tiến trình khác giữ trong lúc pip tải/cài; riêng thông báo đó không chứng minh wheel sai. Hướng dẫn cũ cài `torch` CPU qua `requirements/rag.txt` rồi dùng `--force-reinstall` để tải lại wheel CUDA 2,9 GB: thứ tự này sai cho môi trường hiện tại và tốn thêm một lượt cài. Dùng file wheel cố định trên ổ D để có thể tiếp tục tải nếu mạng ngắt và tránh đường dẫn `pip-unpack` trong `%TEMP%`.

Đóng các kernel đang import `torch` từ **chính `env` này** và bảo đảm không có lệnh pip thứ hai đang cài cùng môi trường. Không dừng crawler đang chạy nếu nó không dùng `torch`. Chạy PowerShell từ gốc dự án:

```powershell
$env:PIP_NO_INDEX = "0"
$env:TEMP = Join-Path (Get-Location) 'work\pip_tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
$wheelDir = Join-Path (Get-Location) 'work\wheels'
New-Item -ItemType Directory -Force -Path $wheelDir | Out-Null
$wheel = Join-Path $wheelDir 'torch-2.10.0+cu128-cp313-cp313-win_amd64.whl'
$url = 'https://download-r2.pytorch.org/whl/cu128/torch-2.10.0%2Bcu128-cp313-cp313-win_amd64.whl'
curl.exe --location --fail --retry 8 --retry-all-errors --retry-delay 10 --continue-at - --output $wheel $url
if ($LASTEXITCODE -ne 0) { throw 'Tải torch chưa xong; chạy lại lệnh curl để tiếp tục.' }
.\env\Scripts\python.exe -m pip install --no-index --no-deps --no-cache-dir $wheel
if ($LASTEXITCODE -ne 0) { throw 'Cài wheel CUDA thất bại; không chạy tiếp pipeline.' }
.\env\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -r requirements/rag.txt
if ($LASTEXITCODE -ne 0) { throw 'Cài requirements/rag.txt thất bại.' }
.\env\Scripts\python.exe -m pip install --index-url https://pypi.org/simple "accelerate>=1.6" "bitsandbytes==0.50.2"
if ($LASTEXITCODE -ne 0) { throw 'Cài accelerate/bitsandbytes thất bại.' }
.\env\Scripts\python.exe -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Môi trường có dependency xung đột.' }
.\env\Scripts\python.exe scripts/benchmark.py --check-only --quantized
```

`curl --continue-at -` dùng lại file tải dở. Nếu wheel đã tải đủ nhưng pip báo file hỏng, xóa riêng file `work\wheels\torch-2.10.0+cu128-cp313-cp313-win_amd64.whl` rồi tải lại. Giữ file wheel này đến khi preflight thành công. `TEMP`/`TMP` của riêng phiên PowerShell được chuyển sang `work\pip_tmp` trên ổ D, tránh thư mục `pip-unpack` cũ ở ổ C. Không dùng `--force-reinstall`, không cài `requirements/rag.txt` trước wheel CUDA và không trỏ pip vào kho `cu128` cho toàn bộ phụ thuộc. `$env:PIP_NO_INDEX = "0"` mở lại truy vấn package trong phiên PowerShell vì máy hiện đặt `PIP_NO_INDEX=1`. Các lệnh đều dùng đúng `env\Scripts\python.exe`.

Đã xác minh có wheel `torch 2.10.0+cu128` cho CPython 3.13/Windows x64 trên [chỉ mục PyTorch](https://download.pytorch.org/whl/cu128/torch/). Phiên bản `bitsandbytes 0.50.2` đã có trong `env` nhưng phải chạy phép tính NF4 thật trên GPU ở preflight; chỉ tìm hoặc import wheel chưa đủ chứng minh dùng được.

Nếu gặp `No matching distribution found for bitsandbytes`, chạy lại lệnh có `--index-url https://pypi.org/simple` bên trên; không cần đổi Python hay hạ model chỉ vì thông báo này. Nếu vẫn lỗi, kiểm tra `python.exe -m pip index versions bitsandbytes --index-url https://pypi.org/simple` và log `-v` để phân biệt nguồn package, mạng và wheel không tương thích.

CUDA wheel mang theo runtime; không cần cài riêng CUDA Toolkit để chạy. Cần NVIDIA driver tương thích. Nếu Python không có wheel tương ứng, dùng bộ chọn Windows/Pip/CUDA trên [trang PyTorch](https://docs.pytorch.org/get-started/locally/) và [danh sách wheel CUDA 12.8](https://download.pytorch.org/whl/cu128/torch/). Bản CPU cần được thay, không chỉ thêm `--device cuda`.

Qwen3 cần Transformers ≥4.51 theo [model card reranker](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B). Profile dùng fp16/SDPA, không yêu cầu FlashAttention 2, vLLM hoặc FAISS. NF4 dùng [bitsandbytes cho Windows/NVIDIA](https://huggingface.co/docs/bitsandbytes/en/installation). Tài liệu model: [BGE-M3](https://huggingface.co/BAAI/bge-m3), [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B), [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B). Các họ model này ra đời trước mốc 01/08/2026; manifest lưu revision thực tế để đối chiếu và viết working notes.

Preflight phải hiện RTX 2050, khoảng 4 GiB VRAM, CUDA khác `null` và `nf4_gpu_test: ok`. Không dùng được CUDA/NF4 thì pipeline dừng trước khi xử lý corpus. Cắm nguồn, dùng chế độ hiệu năng cao, đóng ứng dụng chiếm VRAM; theo dõi bằng `nvidia-smi -l 2`. Tokenizer, đọc đĩa, BM25 và xuất JSON chạy CPU nên GPU không cần luôn đầy.

## 3. Chạy từ đầu đến bài nộp

Xem kế hoạch, chưa tải model/chạy pipeline:

```powershell
.\env\Scripts\python.exe scripts/pipeline.py --source nguyen/output/runs/batch01_nguyen --limit 60000 --out work/rtx2050_60k --dry-run
```

Chạy thật:

```powershell
.\env\Scripts\python.exe scripts/pipeline.py --source nguyen/output/runs/batch01_nguyen --limit 60000 --out work/rtx2050_60k
```

`--limit 60000` là **60.000 bản ghi đầu vào**, gồm cả bản ghi lỗi; số tài liệu dùng được thường thấp hơn sau lọc. Đây không phải khoảng ID `1..60000`, vì ID có thể khuyết. Chưa đủ 60k thì pipeline báo số thực tế và dừng; dùng output mới với số lượng thực tế hoặc chờ crawl đủ. Nhiều nguồn: `--source <run1> <run2>`; nguồn trước thắng khi trùng ID.

Nếu snapshot chỉ có tiếng Việt, pipeline bỏ dịch Anh/Trung vì chưa có tài liệu đích để tìm. Khi crawl mở rộng sang ngôn ngữ khác, tạo run mới.

Pilot chọn batch có thông lượng cao nhất trong những batch đã thử trên mẫu; lô dài hơn gây OOM thì encoder/reranker giảm batch và nhớ mức đó. Mỗi lúc chỉ có một model trên GPU. Query encoder được giải phóng trước khi tìm vector trên GPU và nạp reranker. Qwen reranker giữ suffix sau khi cắt input và chỉ tính logits vị trí cuối để giảm bộ nhớ.

```text
work/rtx2050_60k/
  corpus/                 snapshot, dropped.jsonl, prepare_manifest.json
  chunks/                 chunks.parquet, chunk_manifest.json
  pilot.json              throughput, batch chọn, peak VRAM, mẫu có nguy cơ bị cắt
  translations/           bản dịch, bản bị loại, SQLite cache, manifest (nếu có)
  index/bge-m3/           BM25, embedding, checkpoint, manifest
  index/qwen3-embedding-0.6b/  embedding, checkpoint, manifest
  retrieval/              candidates.jsonl, điểm từng model, SQLite cache
  submission/             submission.json, submission.zip, manifest — recall
  submission_balanced/    cùng định dạng — balanced
  stages/                 khóa input/code/tham số và SHA-256 output từng bước
  logs/                   log từng bước, ghi nối tiếp khi chạy lại
```

**File đem đánh giá lần đầu:** `work/rtx2050_60k/submission/submission.zip`. Bản `submission_balanced/submission.zip` dùng để so sánh; không tự động nộp cả hai. ZIP chứa đúng một JSON ở gốc.

## 4. Resume và giữ artifact

Chạy lại **đúng lệnh mục 3** khi bị ngắt. Bước hoàn thành chỉ được dùng lại khi khóa/checksum khớp. Corpus không tự cập nhật theo crawl; 60k và 100k là hai run riêng. Code khóa thư mục run để tránh hai tiến trình cùng ghi.

- Embedding ghi `embeddings.partial.npy`, flush và checkpoint sau mỗi 512 chunk; chỉ khi đủ mới công bố `embeddings.npy`. Lượt ngắt thường chỉ tính lại shard đang dở. Giữ cả partial và checkpoint.
- Điểm rerank cache theo revision/config model, prompt, query và passage; commit sau mỗi query. Đổi ngưỡng bài không phải chấm lại, đổi text/model không dùng nhầm điểm cũ.
- Dịch cache từng query/ngôn ngữ với model revision và prompt; bản không qua kiểm tra cũng được lưu để xem lại.
- Nếu thay nguồn/config/code làm snapshot cũ không còn tương ứng, dùng `--out` mới. Không xóa corpus để ép run cũ đọc lại crawl đang tăng.

Giữ corpus, chunks, index/checkpoint, cache và manifest cùng nhau. Mỗi ma trận embedding khoảng `số_chunk × 1024 × 2 byte`; có hai ma trận, cộng BM25, corpus, cache model và file tạm. Cache Hugging Face mặc định nằm ngoài `work/`; có thể đặt `$env:HF_HOME` sang ổ đủ chỗ trước lần tải đầu tiên. Lần đầu tải nhiều model cần dung lượng và thời gian mạng đáng kể.

## 5. Kiểm tra trước khi nộp

Trong `prepare_manifest.json`: `rows_read = 60000`; xem số giữ lại, lý do loại, domain/ngôn ngữ. Corpus 60k chỉ phủ một phần nguồn BTC; tài liệu đúng chưa crawl sẽ không thể được retrieve.

Trong `pilot.json`: xem tốc độ, VRAM và mẫu vượt `max_length`. Bộ đếm chunk repo khác tokenizer model và tokenizer BTC. Model cắt ở 1024 token gồm cả tiêu đề/prompt/query, nên có thể bỏ đuôi đoạn dài. Nếu bị cắt nhiều, giảm chunk size hoặc tăng max_length sau khi đo lại VRAM; đổi chunk cần index mới.

Trong `submission/submission_manifest.json`:

- Số query bằng số hàng `data/query.parquet` (bộ hiện tại: 1.200).
- `queries_without_candidates = 0` nghĩa là không thiếu bản ghi query, không bảo đảm mọi query có tài liệu đúng.
- Kỳ vọng `dropped_docs = 0`, `dropped_chunks = 0` với corpus chính thức.
- `resliced_from_offsets` bằng số chunk đã kiểm tra; mọi nội dung khớp lát cắt nguồn.

Code chặn candidates lệch hash chunk/query, thiếu query khi `--require-complete`, trùng query ID và chunk gắn sai tài liệu. Docs và chunks ngoài danh sách ID chính thức đều bị lọc.

## 6. Đánh giá và chỉnh ngưỡng không chạy lại GPU

```powershell
.\env\Scripts\python.exe scripts/evaluate.py sheet --candidates work/rtx2050_60k/retrieval/candidates.jsonl --chunks work/rtx2050_60k/chunks/chunks.parquet --out work/rtx2050_60k/eval --limit 50 --per-query 30
# Đọc label_sheet.html, điền relevant trong label_sheet.jsonl.
.\env\Scripts\python.exe scripts/evaluate.py collect --sheet work/rtx2050_60k/eval/label_sheet.jsonl --out work/rtx2050_60k/eval
.\env\Scripts\python.exe scripts/evaluate.py score --labels work/rtx2050_60k/eval/labels.jsonl --submission work/rtx2050_60k/submission/submission.json --candidates work/rtx2050_60k/retrieval/candidates.jsonl --corpus work/rtx2050_60k/corpus/corpus.parquet --out work/rtx2050_60k/eval/recall
```

So sánh bằng cách chạy `score` với `submission_balanced/submission.json` và `--out .../eval/balanced`. Nhãn trong tập ứng viên có thể thiếu tài liệu đúng chưa tìm ra, nên Recall/F2 local chỉ phản ánh nhãn đã có. Không dùng `pseudo` làm bằng chứng chất lượng. Tokenizer LCS local là giả định được ghi trong `schema.py`, điểm chunk có thể khác BTC.

Ví dụ tạo bài adaptive từ cùng ứng viên:

```powershell
.\env\Scripts\python.exe scripts/submit.py --candidates work/rtx2050_60k/retrieval/candidates.jsonl --chunks work/rtx2050_60k/chunks/chunks.parquet --corpus work/rtx2050_60k/corpus/corpus.parquet --queries data/query.parquet --links data/links_corpus.parquet --require-complete --profile recall --adaptive --out work/rtx2050_60k/submission_adaptive
```

Adaptive có thể cắt mất bằng chứng nên chưa bật mặc định. `model_scores` lưu điểm riêng để phân tích. Muốn so một reranker, chạy `retrieve.py` cùng output và chọn riêng model đó; điểm đã chấm lấy từ SQLite. Sao lưu candidates/manifest trước nếu muốn giữ cả hai cấu hình.

## 7. Lệnh riêng và sự cố

`--dry-run` in lệnh của từng khâu. Trên Windows ưu tiên lệnh điều phối: nó truyền JSON trọng số bằng danh sách đối số, tránh lỗi quote PowerShell. CLI cũ vẫn dùng được, xem `scripts/index.py --help`, `scripts/retrieve.py --help`, `scripts/translate.py --help`.

| Tình huống | Xử lý |
|---|---|
| CUDA unavailable / CPU-only torch | Làm mục 2 và chạy preflight; không tự chuyển toàn lượt sang CPU |
| OOM dịch Qwen3-4B batch 1 | Chạy lại pipeline thêm `--translation-model qwen3-1.7b`, vẫn NF4. Nếu lỗi thư viện, sửa bitsandbytes hoặc thử `--translation-model qwen3-0.6b --translation-quantize none`, rồi kiểm tra chất lượng bản dịch |
| OOM encode/rerank batch >1 | Code tự giảm batch. Nếu batch 1 vẫn lỗi, giải phóng VRAM; giảm max_length/chunk size và đo lại |
| Đã đo pilot, muốn bỏ qua | `--skip-pilot` dùng batch dự phòng 8 encoder, 4 reranker; không phải batch đã benchmark |
| Rerank quá lâu | `--rerank-k 100 --keep 100` giảm tối đa 480.000 xuống 240.000 cặp với hai reranker/1.200 query, có thể giảm Recall |
| Baseline một model | Output mới, thêm `--encoders bge-m3 --rerankers bge-reranker-v2-m3`, có thể thêm `--skip-translation` |
| Dịch có `rejected` | Xem `translations/rejected.jsonl`; pipeline dùng phần hợp lệ và giữ query gốc |
| Embedding checkpoint differs | Dùng index/output mới; không ghép model hoặc chunk khác vào checkpoint |
| Frozen corpus/config changed | Dùng `--out` mới để snapshot mới, giữ run cũ |
| Hash mismatch | Dùng artifact cùng run hoặc chạy lại từ khâu đã thay đổi |
| Mạng ngắt tải model | Chạy lại lệnh; cache Hugging Face và cache pipeline độc lập |

Kiểm thử offline, không tải model:

```powershell
.\env\Scripts\python.exe -m unittest discover -s tests -v
.\env\Scripts\python.exe scripts/test_local_pipeline.py
```

Bộ bổ sung kiểm tra resume embedding, tìm vector theo block, suffix Qwen, bản dịch cũ/đổi chữ số, ID ngoài corpus, ngưỡng sau giới hạn chunk/document, CLI đến ZIP và cache/snapshot. Các test này không chứng minh chất lượng model hay thông lượng RTX 2050; pilot và lượt nộp thật cung cấp số đo đó.
