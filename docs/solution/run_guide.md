# Chạy pipeline thác đến `submission.zip`: laptop (dữ liệu local) và Kaggle (dữ liệu HF)

Chạy PowerShell từ thư mục gốc dự án. Một lệnh điều phối (`scripts/vibiomir.py pipeline`) chạy mọi khâu, mỗi khâu một tiến trình riêng, lưu log và dùng lại khâu đã xong khi chạy lại. Pipeline đọc một **snapshot** dữ liệu crawl rồi đóng băng; crawl vẫn chạy song song không ảnh hưởng run hiện tại. Lý do thiết kế: [research.md](research.md).

**Trạng thái xác minh (10/10/2026):** toàn bộ luồng mới đã chạy đầu–cuối trên CPU với encoder `hash` và reranker `identity`, trên 3.000 tài liệu thật của corpus HF và 1.200 truy vấn thật; 133 test offline đạt (126 trong `tests/`, 7 trong `scripts/`). Môi trường `env` có `torch 2.10.0+cu128`, CUDA khả dụng. **Chưa chạy với model thật trên GPU nào, chưa có điểm leaderboard cho thiết kế mới.** Các con số mặc định (số tài liệu ứng viên, `rerank-k`, cửa sổ 768 token) là điểm xuất phát để đo, chưa phải giá trị tối ưu.

## 1. Thiết kế đang chạy

| Khâu | Cách chạy | Ghi chú |
|---|---|---|
| fetch | **Chỉ Kaggle** (`--source hf`): tải `corpus/*.parquet` của dataset nhóm và `query`/`links_corpus` của BTC; ghim commit corpus cho thư mục run | Laptop bỏ qua khâu này |
| prepare | Laptop: đọc các run crawl trong `nguyen\` (batch01 + 2 shard), **100.000 bản ghi chia theo tỷ lệ số bản ghi của từng run**, ID nhỏ trước trong mỗi run. Kaggle: corpus HF vừa tải. Lọc lỗi tải/trang chủ/template; giữ `review` | `--limit 0` đọc hết; `--split sequential` lấy từ run đầu trước |
| cards | Một **thẻ** mỗi tài liệu: tiêu đề + đoạn mở đầu ≤160 token | Trang hỏi–đáp: thẻ chứa câu hỏi của bệnh nhân |
| translate | **Một LLM** (Qwen3-4B) dịch theo batch 1.200 truy vấn sang tiếng Trung (+Anh nếu corpus có ≥1% tài liệu Anh) | Chỉ để tìm; `chunk_text` luôn lấy từ corpus. HyDE tắt mặc định (`--hyde zh vi` để bật) |
| cards_bm25, cards_dense | BM25 + BGE-M3 trên thẻ của toàn corpus | Rẻ hơn nhiều so với encode mọi chunk |
| doc_search | Tìm trên thẻ, giữ `--docs-per-query` tài liệu mỗi truy vấn | Không rerank ở tầng này |
| subset | **Chỉ chunk các tài liệu ứng viên** (hợp của mọi truy vấn): đích 384 token, overlap 32, trần 768; giữ offset nguồn | Không chunk toàn corpus: phần lớn tài liệu không truy vấn nào chạm tới |
| subset_bm25, subset_dense | Chỉ mục đoạn trên tập con | |
| retrieve | BM25 + dense + **kênh card** (thứ hạng tài liệu từ tầng thẻ) → RRF → **một reranker**, chấm đoạn tiếng Trung bằng bản dịch tiếng Trung của câu hỏi | Với nhiều GPU, chia truy vấn mỗi card một phần |
| submit | Profile **`f2`**: giữ một mục khi xác suất > F2 kỳ vọng / 5; **mở rộng đoạn nộp** thành cửa sổ ≤768 token (vẫn là đoạn trích nguyên văn); bỏ đoạn đã nằm trong cửa sổ khác | Một bài nộp duy nhất |

**Pipeline tối giản, ưu tiên xử lý nhiều dữ liệu:** đúng một model mỗi vai trò, dùng chung cho laptop và Kaggle:

| Vai trò | Model | Ghi chú |
|---|---|---|
| Encoder | BAAI/bge-m3 (568M) | Đã có trong cache máy |
| Reranker (duy nhất) | BAAI/bge-reranker-v2-m3 (568M) | Đã có trong cache máy; vừa GPU 4 GB và T4 |
| LLM dịch truy vấn | Qwen/Qwen3-4B | 4-bit trên laptop, fp16 trên Kaggle; lần đầu tải ~8 GB |

Không còn bước pilot đo batch: batch cố định (laptop 16 encoder / 8 reranker; Kaggle 128 / 32), tự giảm một nửa khi hết VRAM. Các model khác (Qwen3-Embedding, Qwen3-Reranker, e5, gte) đã gỡ khỏi code và cache.

Hồ sơ `--profile local` (mặc định): dữ liệu `nguyen\`, 100.000 bản ghi, `query`/`links` từ `data\`, 1 GPU 4 GB, 100 tài liệu ứng viên/truy vấn, rerank 50 đoạn/truy vấn. Hồ sơ `kaggle`: dữ liệu HF, toàn bộ corpus, T4×2, 200 tài liệu/truy vấn, rerank 60 đoạn. Mọi giá trị đều ghi đè được bằng tham số.

Điểm reranker chưa được hiệu chỉnh thành xác suất. Khi có nhãn dev do người gán, chạy `scripts/vibiomir.py evaluate calibrate` để sinh `calibration.json` rồi truyền `--calibration` cho pipeline (mục 6).

## 1b. Cấu trúc code

| Đường dẫn | Vai trò |
|---|---|
| `scripts/vibiomir.py` | **Cửa vào duy nhất** cho mọi khâu: `pipeline`, `fetch`, `prepare`, `cards`, `chunk`, `index`, `translate`, `retrieve`, `submit`, `evaluate`, `benchmark`, `teach`. Ví dụ `scripts/vibiomir.py submit --help` |
| `scripts/build_notebooks.py` | Nhúng code repo vào `notebooks/for_kaggle.ipynb` và `notebooks/teach_kaggle.ipynb` |
| `scripts/notebook_postprocess.py` | Công cụ của notebook crawl (đóng gói/kiểm tra khi upload HF), không thuộc pipeline truy xuất |
| `src/vibiomir/corpus/` | `prepare`, `cards` (thẻ + tập con), `chunk` (cắt đoạn, cửa sổ nộp), `fetch` (HF) |
| `src/vibiomir/index/` | BM25, embedding (bge-m3) |
| `src/vibiomir/retrieval/` | truy vấn, dịch, RRF, reranker, CLI truy xuất |
| `src/vibiomir/submission/` | chọn theo F2, hiệu chỉnh, kiểm tra, đóng ZIP |
| `src/vibiomir/evaluation/` | gán nhãn dev, chấm điểm, quy lỗi |
| `src/vibiomir/teach/` | Khối T (teacher → student), **tạm dừng**; giữ lại vì `rerank`/`embedding` dùng chung hàm nạp model và có thể bật lại |
| `tests/` | Toàn bộ test offline: `.\env\Scripts\python.exe -m unittest discover -s tests` |

Đã gom ngày 10/10: 12 file wrapper một dòng (`scripts/prepare.py`, `index.py`, `retrieve.py`...) thành `scripts/vibiomir.py`; hai script build notebook thành `scripts/build_notebooks.py`; `scripts/test_local_pipeline.py` chuyển về `tests/`; bỏ hai hàm không còn ai gọi.

## 2. Chuẩn bị môi trường CUDA (chạy một lần)

> **Đã cài xong trên máy này** (10/10: `torch 2.10.0+cu128`, CUDA khả dụng). File wheel trong `work\wheels` đã được xóa để giải phóng 2,7 GB; chỉ chạy lại khối lệnh dưới khi phải cài lại `env`, lúc đó wheel được tải lại.

Dùng PowerShell ở thư mục gốc dự án với `env` Python 3.13 x64. Đóng kernel đang dùng `torch` trong `env` và không chạy hai lệnh pip cùng lúc; crawler không dùng `torch` vẫn có thể tiếp tục. **Chạy toàn bộ khối lệnh dưới đây trong cùng một cửa sổ PowerShell:**

```powershell
$py = '.\env\Scripts\python.exe'
$env:PIP_NO_INDEX = '0'
$env:TEMP = Join-Path (Get-Location) 'work\pip_tmp'
$env:TMP = $env:TEMP
$wheelDir = Join-Path (Get-Location) 'work\wheels'
New-Item -ItemType Directory -Force -Path $env:TEMP, $wheelDir | Out-Null
$wheel = Join-Path $wheelDir 'torch-2.10.0+cu128-cp313-cp313-win_amd64.whl'
if (!(Test-Path $wheel) -or (Get-Item $wheel).Length -ne 2867408009) {
    curl.exe -fL -C - --retry 8 --retry-all-errors --retry-delay 10 -o $wheel 'https://download-r2.pytorch.org/whl/cu128/torch-2.10.0%2Bcu128-cp313-cp313-win_amd64.whl'
    if ($LASTEXITCODE -ne 0 -or (Get-Item $wheel).Length -ne 2867408009) { throw 'Wheel tải chưa đủ; chạy lại khối lệnh để tiếp tục.' }
}
& $py -m pip install --no-index --no-deps --no-cache-dir $wheel
if ($LASTEXITCODE -ne 0) { throw 'Cài torch CUDA thất bại.' }
& $py -m pip install --index-url https://pypi.org/simple -r requirements/rag.txt 'accelerate>=1.6' 'bitsandbytes==0.50.2'
if ($LASTEXITCODE -ne 0) { throw 'Cài thư viện pipeline thất bại.' }
& $py -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Các thư viện đang xung đột.' }
& $py scripts/vibiomir.py benchmark --check-only --quantized
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra CUDA/NF4 chưa đạt; xem lỗi phía trên.' }
```

Kết quả cuối phải có `gpu` là RTX 2050, `cuda` khác `null` và `nf4_gpu_test: ok`. Wheel PyTorch khoảng 2,9 GB được lưu tại `work\wheels`; nếu mạng ngắt, chạy lại khối lệnh để tiếp tục tải. Nếu pip báo wheel hỏng, xóa **riêng file wheel đó** rồi chạy lại. Không cần cài CUDA Toolkit riêng. [Wheel PyTorch CUDA 12.8](https://download.pytorch.org/whl/cu128/torch/) · [bitsandbytes trên Windows](https://huggingface.co/docs/bitsandbytes/en/installation)

## 3. Chạy từ đầu đến bài nộp

### Trên laptop: dữ liệu local trong `nguyen\`, không dùng HF

Dữ liệu đầu vào là các run crawl trên máy: `nguyen\output\runs\batch01_nguyen`, `nguyen\shards\shard_01\runs\...` và `nguyen\shards\shard_02\runs\...` (pipeline tự tìm). `query.parquet` và `links_corpus.parquet` lấy từ `data\`. Không cần đăng nhập HF.

Mặc định lấy **tổng 100.000 bản ghi**, chia theo tỷ lệ số bản ghi hiện có của từng run; trong mỗi run lấy ID nhỏ trước. Với số bản ghi ngày 10/10:

| Run | Bản ghi hiện có | Lấy |
|---|---:|---:|
| batch01_nguyen | 139.160 | 40.043 |
| shard_01 | 94.764 | 27.268 |
| shard_02 | 113.602 | 32.689 |

Con số thực tế được tính lại lúc chạy và ghi ở `corpus/prepare_manifest.json` (`rows_read_per_source`). Đây là **bản ghi đầu vào**, gồm cả bản ghi tải lỗi hay bị robots chặn; số tài liệu dùng được thấp hơn sau lọc (xem `documents_kept`, `drop_reasons`).

Xem kế hoạch các khâu, chưa chạy gì:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --dry-run
```

Chạy thật (mặc định `--profile local --source nguyen --limit 100000 --out work/run_local_100k`):

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline
```

Nếu run cũ đã xong `prepare` nhưng dừng vì thiếu `scripts/cards.py` sau khi gom các wrapper, tiếp tục bằng:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --reuse-corpus
```

Snapshot đã chuẩn bị được **tự động dùng lại**, kể cả khi đổi wrapper CLI, code hoặc môi trường, chỉ khi tham số nguồn/giới hạn và SHA-256 của corpus cùng manifest khớp checkpoint. `--reuse-corpus` được giữ để tương thích lệnh cũ, không còn bắt buộc. Các bước sau được kiểm tra/chạy lại theo code hiện tại. Muốn áp dụng code chuẩn bị mới hoặc lấy dữ liệu crawl mới, chọn `--out` mới. Không xóa `stages/prepare.json` để ép đọc lại nguồn đang crawl.

**Chạy tiếp khi bị ngắt (kể cả Ctrl+C):** gõ lại đúng lệnh; khâu đã xong (khớp SHA-256) được dùng lại — kể cả khâu xong trước khi bạn ngắt, và model tải dở được tải tiếp, embedding tiếp tục từ shard đang dở. Snapshot 100k đã đóng băng ở lần chạy đầu: crawl có thêm dữ liệu cũng không làm đổi run này. Muốn snapshot mới (crawl đã nhiều hơn, hoặc số lượng khác): dùng `--out` mới, ví dụ `--limit 200000 --out work/run_local_200k`, hoặc `--limit 0` để lấy hết.

Trên GPU 4 GB, LLM dịch và encoder không cùng nằm trên card, nên các khâu GPU chạy lần lượt. Hai shard là trang tiếng Trung (cnkang, wujue), nên khâu dịch sẽ chạy; tắt bằng `--skip-translation`. Lần đầu sẽ tải Qwen3-4B (khoảng 8 GB) vào cache HF; bge-m3 và bge-reranker-v2-m3 đã có sẵn.

Chạy thử 3.000 bản ghi (10/10, CPU, encoder `hash`, không dịch) đi hết các khâu trong 83 giây: 1.199 tài liệu Việt + 1.801 Trung, tập con 2.273 tài liệu → 5.591 chunk (2,46 chunk/tài liệu). Thời gian với model thật trên GPU chưa đo.

```text
work/run_local_100k/
  corpus/            snapshot, dropped.jsonl, prepare_manifest.json
  cards/             thẻ tài liệu
  translations/      bản dịch, bản bị loại, SQLite cache
  index/cards/       BM25 + embedding của thẻ
  doc_search/        tài liệu ứng viên mỗi truy vấn
  subset/            chunk chỉ của tài liệu ứng viên, doc_candidates.jsonl
  index/subset/      BM25 + embedding của tập con
  retrieval/         candidates.jsonl (một thư mục part<i> mỗi GPU khi có nhiều GPU), cache điểm
  submission/        BÀI NỘP CHÍNH: f2 + cửa sổ 768 token
  stages/, logs/     khóa và SHA-256 từng khâu; log nối tiếp
```

**File nộp:** `work/run_local_100k/submission/submission.zip`. Muốn so A/B việc mở rộng cửa sổ: chạy riêng `submit.py ... --window-tokens 0` (mục 6), không cần chạy lại GPU.

### Trên Kaggle, dữ liệu lấy từ Hugging Face

Dùng [notebooks/for_kaggle.ipynb](../../notebooks/for_kaggle.ipynb). Notebook chạy cùng `pipeline.py` với `--profile kaggle --source hf`: khâu `fetch` tải `corpus/*.parquet` của dataset nhóm và `query`/`links` của BTC, **ghim commit** corpus cho run (chạy lại trong cùng phiên dùng đúng commit đó, khâu đã xong được dùng lại), rồi hai T4 chạy song song hai nửa embedding và hai nửa truy vấn rerank. Dataset nhóm là private: cần Secret `HF_TOKEN` (token Read). Kết quả: `/kaggle/working/submission.zip`, kèm thư mục `run/hf/` chứa commit đã ghim.

Code của repo được nhúng sẵn trong notebook. Sau khi sửa code trên laptop:

```powershell
.\env\Scripts\python.exe scripts/build_notebooks.py kaggle
```

rồi upload lại notebook. Không sửa tay ô code nhúng.

## 4. Resume và giữ artifact

Chạy lại **đúng lệnh mục 3** khi bị ngắt. Bước hoàn thành chỉ được dùng lại khi khóa/checksum khớp. Corpus không tự cập nhật theo crawl; muốn đưa dữ liệu crawl mới vào thì chạy với `--out` mới. Code khóa thư mục run để tránh hai tiến trình cùng ghi.

- Embedding ghi `embeddings.partial.npy`, flush và checkpoint sau mỗi 512 chunk; chỉ khi đủ mới công bố `embeddings.npy`. Lượt ngắt thường chỉ tính lại shard đang dở. Giữ cả partial và checkpoint.
- Điểm rerank cache theo revision/config model, prompt, query và passage; commit sau mỗi query. Đổi ngưỡng bài không phải chấm lại, đổi text/model không dùng nhầm điểm cũ.
- Dịch cache từng query/ngôn ngữ với model revision và prompt; bản không qua kiểm tra cũng được lưu để xem lại.
- Nếu thay nguồn/config/code làm snapshot cũ không còn tương ứng, dùng `--out` mới. Không xóa corpus để ép run cũ đọc lại crawl đang tăng.

Giữ corpus, chunks, index/checkpoint, cache và manifest cùng nhau. Mỗi ma trận embedding khoảng `số_dòng × 1024 × 2 byte`; có hai ma trận (thẻ của toàn corpus và chunk của tập con), cộng BM25, corpus, cache model và file tạm. Cache Hugging Face mặc định nằm ngoài `work/`; có thể đặt `$env:HF_HOME` sang ổ đủ chỗ trước lần tải đầu tiên. Lần đầu tải nhiều model cần dung lượng và thời gian mạng đáng kể.

## 5. Kiểm tra trước khi nộp

Trong `corpus/prepare_manifest.json`: xem `sources` (đúng các run mong muốn), số giữ lại, lý do loại, domain/ngôn ngữ. Corpus chỉ phủ phần nguồn BTC đã crawl; tài liệu đúng chưa crawl sẽ không thể được retrieve. Trong `subset/chunk_manifest.json`: số tài liệu ứng viên và số chunk của tập con.

Trong `logs/`: xem tốc độ encode/rerank và các lần tự giảm batch. Bộ đếm chunk repo khác tokenizer model và tokenizer BTC. Model cắt ở 1024 token gồm cả tiêu đề/prompt/query, nên có thể bỏ đuôi đoạn dài. Nếu bị cắt nhiều, giảm chunk size hoặc tăng max_length sau khi đo lại VRAM; đổi chunk cần index mới.

Trong `submission/submission_manifest.json`:

- Số query bằng số hàng `data/query.parquet` (bộ hiện tại: 1.200).
- `queries_without_candidates = 0` nghĩa là không thiếu bản ghi query, không bảo đảm mọi query có tài liệu đúng.
- Kỳ vọng `dropped_docs = 0`, `dropped_chunks = 0` với corpus chính thức.
- `resliced_from_offsets` bằng số chunk đã kiểm tra; mọi nội dung khớp lát cắt nguồn.
- `chunk_tokens_max` ≤ `window_tokens`; `chunks_inside_window` là số đoạn bị bỏ vì đã nằm trong cửa sổ khác cùng tài liệu.
- Kích thước `submission.json`: mặc định tối đa 15 cửa sổ/truy vấn; nếu file quá lớn, giảm `--chunk-max` hoặc `--window-tokens` ở `submit.py`.

Code chặn candidates lệch hash chunk/query, thiếu query khi `--require-complete`, trùng query ID và chunk gắn sai tài liệu. Docs và chunks ngoài danh sách ID chính thức đều bị lọc.

## 6. Đánh giá, hiệu chỉnh và chỉnh ngưỡng không chạy lại GPU

Với một GPU, ứng viên nằm ở `retrieval/candidates.jsonl`; với nhiều GPU là các file `retrieval/part*/candidates.jsonl` (truyền tất cả cho `--candidates`). Chunk của bài nộp lấy từ `subset/chunks.parquet`.

```powershell
$R = 'work/run_local_100k'
.\env\Scripts\python.exe scripts/vibiomir.py evaluate sheet --candidates $R/retrieval/candidates.jsonl --chunks $R/subset/chunks.parquet --out $R/eval --limit 60 --per-query 20
# Đọc label_sheet.html, điền relevant trong label_sheet.jsonl.
.\env\Scripts\python.exe scripts/vibiomir.py evaluate collect --sheet $R/eval/label_sheet.jsonl --out $R/eval
.\env\Scripts\python.exe scripts/vibiomir.py evaluate score --labels $R/eval/labels.jsonl --submission $R/submission/submission.json --candidates $R/retrieval/candidates.jsonl --corpus $R/corpus/corpus.parquet --out $R/eval/main
```

Hiệu chỉnh điểm reranker thành xác suất (Platt, tách theo ngôn ngữ tài liệu), rồi dựng lại bài nộp mà không chạy lại GPU:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py evaluate calibrate --labels $R/eval/labels.jsonl --candidates $R/retrieval/candidates.jsonl --out $R/eval
.\env\Scripts\python.exe scripts/vibiomir.py submit --candidates $R/retrieval/candidates.jsonl --chunks $R/subset/chunks.parquet --corpus $R/corpus/corpus.parquet --queries data/query.parquet --links data/links_corpus.parquet --require-complete --profile f2 --calibration $R/eval/calibration.json --window-tokens 768 --out $R/submission_calibrated
```

`calibrate` từ chối nhãn `pseudo`. Nhãn dev gộp từ chính ứng viên của hệ thống nên đánh giá thấp lỗi `not_retrieved`; Recall/F2 local chỉ phản ánh nhãn đã có. Tokenizer LCS local là giả định ghi trong `schema.py`, điểm chunk có thể khác BTC.

Các tham số chỉnh nhanh của `submit.py`: `--window-tokens` (0–1024), `--missing` (khối lượng tài liệu đúng ước lượng là đã bỏ sót mỗi truy vấn; tăng thì danh sách dài hơn), `--chunk-max`, `--doc-max`. Profile cũ `recall`/`balanced`/`precision` vẫn dùng được để so sánh.

## 7. Lệnh riêng và sự cố

`--dry-run` in lệnh của từng khâu. Trên Windows ưu tiên lệnh điều phối: nó truyền JSON trọng số bằng danh sách đối số, tránh lỗi quote PowerShell. CLI cũ vẫn dùng được, xem `scripts/vibiomir.py index --help`, `scripts/vibiomir.py retrieve --help`, `scripts/vibiomir.py translate --help`.

| Tình huống | Xử lý |
|---|---|
| CUDA unavailable / CPU-only torch | Làm mục 2 và chạy preflight; không tự chuyển toàn lượt sang CPU |
| Khâu `translate` đứng rất lâu ở `Fetching 3 files` | Đang **tải Qwen3-4B (7,49 GiB)** lần đầu, không phải treo. Mạng ~1 MB/s thì mất khoảng 2 giờ. Nhấn Ctrl+C rồi chạy lại **tải tiếp** từ chỗ dở (file `.incomplete` trong cache HF). Tải nhanh hơn: `pip install hf_transfer` rồi đặt `$env:HF_HUB_ENABLE_HF_TRANSFER=1`. Không muốn tải: dùng `--translations <file>` (bản dịch tạo sẵn ở Kaggle) hoặc `--skip-translation` (mất kênh tiếng Trung) |
| Đã có bản dịch từ nơi khác | `--translations <đường dẫn translations.jsonl>`: pipeline bỏ qua khâu translate, không nạp model dịch nào |
| OOM khi dịch | Batch tự giảm một nửa khi hết VRAM. Nếu batch 1 vẫn lỗi, đóng chương trình khác đang dùng GPU; hoặc chạy `--skip-translation` (mất kênh tiếng Trung, Recall với tài liệu Trung giảm) |
| OOM encode/rerank batch >1 | Code tự giảm batch. Nếu batch 1 vẫn lỗi, giải phóng VRAM; giảm max_length/chunk size và đo lại |
| Muốn đổi batch | `--encoder-batch`, `--rerank-batch`, `--translate-batch` |
| Rerank quá lâu | Giảm `--rerank-k` (số cặp = 1.200 × rerank-k); có thể giảm Recall |
| Dịch có `rejected` | Xem `translations/rejected.jsonl`; pipeline dùng phần hợp lệ và giữ query gốc |
| Embedding checkpoint differs | Dùng index/output mới; không ghép model hoặc chunk khác vào checkpoint |
| Frozen corpus verification failed | Tham số prepare đổi, checkpoint không tương thích hoặc output thiếu/sai hash. Giữ run cũ; dùng `--out` mới để lấy snapshot mới |
| Hash mismatch | Dùng artifact cùng run hoặc chạy lại từ khâu đã thay đổi |
| Mạng ngắt tải model | Chạy lại lệnh; cache Hugging Face và cache pipeline độc lập |

Kiểm thử offline, không tải model:

```powershell
.\env\Scripts\python.exe -m unittest discover -s tests -v
```

Bộ bổ sung kiểm tra resume embedding, tìm vector theo block, suffix Qwen, bản dịch cũ/đổi chữ số, ID ngoài corpus, ngưỡng sau giới hạn chunk/document, CLI đến ZIP và cache/snapshot. `tests/test_cascade.py` kiểm tra phần thác: tìm nguồn trong `nguyen\`, thẻ và tập con giữ nguyên chunk, kênh card, chia truy vấn theo shard, ghép embedding nhiều phần, ngưỡng F2 (so với vét cạn), hiệu chỉnh Platt và cửa sổ nộp. Các test này không chứng minh chất lượng model hay thông lượng RTX 2050; pilot và lượt nộp thật cung cấp số đo đó.
