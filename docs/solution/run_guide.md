# Pipeline thống nhất: local và Kaggle (11/10/2026)

Chạy từ thư mục gốc dự án. Mặc định mới **tìm chunk trên toàn corpus đã chọn**, một encoder và một reranker. Không khối T, huấn luyện, LLM viết lại/dịch truy vấn, vòng feedback hay ensemble. Thiết kế gốc: [pipeline.txt](pipeline.txt). Cấu hình dưới đây để đo, chưa được chứng minh tối ưu trên leaderboard.

## 1. Thiết kế đang chạy

| Khâu | Cách chạy |
|---|---|
| fetch (nguồn HF) | Ghim commit; chỉ tải shard giao khoảng ID theo tên `ids_<đầu>_<cuối>_synced.parquet`; shard tên cũ chưa biết khoảng vẫn được đọc |
| prepare | Lọc `id_start <= id <= id_end`, rồi áp dụng trần số dòng, làm sạch, giữ ID nguồn và snapshot |
| chunk | Toàn corpus đã chọn: theo đoạn/câu, mục tiêu 384 token, overlap 64, trần 768 theo bộ đếm repo; giữ offset |
| bm25 + dense | BM25 Latin/CJK + **BGE-M3 (local)** hoặc **Qwen3-Embedding-4B (Kaggle)**; embedding chia GPU/shard, có checkpoint |
| retrieve | Query gốc + từ khóa bằng quy tắc → lexical/dense → RRF → tối đa 3 chunk/doc trong tập rerank |
| rerank | **BGE-reranker-v2-m3 (local)** hoặc **Qwen3-Reranker-4B (Kaggle)**, một model, một lượt; cache theo cặp; hai GPU chia truy vấn không trùng |
| submit | Heuristic F2, giữ chunk đã chấm (`window_tokens=0`), trích lại từ offset, kiểm tra đủ truy vấn và ID BTC, đóng ZIP |

Bỏ tầng lọc tiêu đề/mở đầu giúp bằng chứng ở cuối bài có cơ hội được truy hồi. Đổi lại, phải encode mọi chunk trong corpus đã chọn. Encoder đảm nhiệm truy xuất xuyên ngôn ngữ; BM25 query Việt không tự khớp thuật ngữ Trung. Căn cứ nâng riêng model Kaggle: [kaggle_models.md](kaggle_models.md).

| Cấu hình | Local RTX 2050 | Kaggle |
|---|---:|---:|
| GPU | 1 | tối đa 2 |
| Model embedding / rerank | BGE ~0,6B / BGE ~0,6B | Qwen3 4B / Qwen3 4B |
| Trần dòng đầu vào | 100.000 | 100.000, chỉnh đầu notebook |
| Rerank chunk/query | 120 | 60 |
| Tối đa cặp mới với 1.200 query | 144.000 | 72.000 |
| Batch encode / rerank | 8 / 2 | 16 / 8 |
| Deadline | không giới hạn mặc định | notebook 8 giờ thực từ ô cấu hình; CLI profile 9 giờ |

Batch tự giảm khi CUDA OOM. Encoder và reranker được nạp lần lượt. Dense mặc định tìm chính xác theo block; `--ann --nprobe 64` dùng FAISS IVF xấp xỉ, giảm chi phí search nhưng **không giảm chi phí encode**. Cần `requirements/search.txt` nếu bật ANN. Retrieval manifest ghi overlap với exact trên 5 query variants mỗi GPU; đây không phải Recall nhãn đúng.

Chưa đo GPU/leaderboard cho cấu hình mới này. Ngưỡng F2 dùng điểm chưa hiệu chỉnh nên là heuristic; có nhãn dev độc lập thì thêm `--calibration`. Corpus hẹp vẫn giới hạn recall. Với hàng triệu tài liệu, cần đo RAM/ổ đĩa và chia phạm vi: prepare, chunk, BM25 vẫn có bước giữ dữ liệu trong RAM; `--disk-text` chỉ giảm RAM ở retrieval.

## 1b. Cấu trúc code

| Đường dẫn | Vai trò |
|---|---|
| `scripts/vibiomir.py` | **Cửa vào duy nhất** cho mọi khâu: `pipeline`, `fetch`, `prepare`, `cards`, `chunk`, `index`, `translate`, `retrieve`, `submit`, `evaluate`, `benchmark`, `teach`. Ví dụ `scripts/vibiomir.py submit --help` |
| `scripts/build_notebooks.py` | Nhúng code repo vào `notebooks/pipeline_for_kaggle.ipynb` và `notebooks/teach_kaggle.ipynb` |
| `scripts/notebook_postprocess.py` | Công cụ của notebook crawl (đóng gói/kiểm tra khi upload HF), không thuộc pipeline truy xuất |
| `src/vibiomir/corpus/` | `prepare`, `cards` (thẻ + tập con), `chunk` (cắt đoạn, cửa sổ nộp), `fetch` (HF) |
| `src/vibiomir/index/` | BM25, embedding (bge-m3) |
| `src/vibiomir/retrieval/` | truy vấn, dịch, RRF, reranker, CLI truy xuất |
| `src/vibiomir/submission/` | chọn theo F2, hiệu chỉnh, kiểm tra, đóng ZIP |
| `src/vibiomir/evaluation/` | gán nhãn dev, chấm điểm, quy lỗi |
| `src/vibiomir/teach/` | Khối T (teacher → student), **tạm dừng**; giữ lại vì `rerank`/`embedding` dùng chung hàm nạp model và có thể bật lại |
| `tests/` | Toàn bộ test offline: `.\env\Scripts\python.exe -m unittest discover -s tests` |

Đã gom ngày 10/10: 12 file wrapper một dòng (`scripts/prepare.py`, `index.py`, `retrieve.py`...) thành `scripts/vibiomir.py`; hai script build notebook thành `scripts/build_notebooks.py`; `scripts/test_local_pipeline.py` chuyển về `tests/`; bỏ hai hàm không còn ai gọi.

## 1c. Lịch sử thiết kế và cách quay lại

Bảng dưới ghi lịch sử trước bản thống nhất 11/10 ở mục 1. Luồng cascade cũ còn qua `--architecture cascade`.

| Đời | Commit | Thiết kế | Khâu |
|---|---|---|---|
| 1 | `e65e41d`, `cd7aeaa` | Pipeline phẳng: chunk toàn corpus, **2 encoder + 2 reranker** chạy nối tiếp rồi lấy trung bình điểm, xuất 2 bài nộp `recall` + `balanced` | prepare, chunk, pilot, translate, dense ×2, retrieve, submit ×2 |
| 2 | `d5c87bb` | **Thác, chưa tối ưu thời gian**: thêm thẻ tài liệu và tập con, nhưng vẫn chunk toàn corpus, vẫn có `pilot` đo batch, Kaggle dùng **Qwen3-Reranker-4B**, HyDE bật mặc định (`zh`,`vi`), 150/250 tài liệu mỗi truy vấn, rerank 60/80 đoạn, xuất thêm `submission_nowindow` | fetch, prepare, chunk, cards, pilot, translate, cards_bm25, cards_dense, doc_search, subset, retrieve, submit ×2 |
| 3 | `c516963` (cascade cũ) | Tối giản: một model mỗi vai trò, bỏ pilot, chỉ chunk tài liệu ứng viên, HyDE tắt, 100/200 tài liệu, rerank 50/60, một bài nộp | mục 1 |

Xem hoặc lấy lại một bản cũ (không làm mất bản hiện tại):

```powershell
# Đọc thử
git show d5c87bb:src/vibiomir/pipeline.py | more

# Lấy riêng pipeline của đời 2 ra file khác để so sánh
git show d5c87bb:src/vibiomir/pipeline.py > work/pipeline_gen2.py

# Quay lại hẳn đời 2 (chỉ các file của pipeline; nên làm trên nhánh riêng)
git switch -c gen2_restore
git checkout d5c87bb -- src/vibiomir scripts
```

Đời 2 cần các model đã gỡ khỏi registry (Qwen3-Reranker-4B, Qwen3-Embedding-0.6B...), nên `git checkout d5c87bb -- src/vibiomir` lấy lại luôn cả registry cũ. Đừng trộn một nửa: `pipeline.py` của đời 2 gọi `benchmark.py`/`chunk` theo tên khâu cũ và tham số `--encoders`/`--rerankers` dạng số nhiều.

Không cần quay lại cả đời để nới một tham số: đời 3 vẫn nhận `--docs-per-query`, `--rerank-k`, `--hyde zh vi`, `--window-tokens`, `--encoder-batch`, `--rerank-batch`. Ví dụ chạy gần giống đời 2 về độ phủ:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --architecture cascade --enable-translation --docs-per-query 250 --rerank-k 80 --hyde zh vi --out work/run_wide
```

## 2. Chuẩn bị môi trường CUDA (chạy một lần)

Máy đã chạy BGE với CUDA thì **không cài lại torch**. Kiểm tra:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py benchmark --check-only
```

Luồng mới không cần bitsandbytes/NF4 vì không nạp LLM 4-bit. Chỉ bật ANN mới cần:

```powershell
.\env\Scripts\python.exe -m pip install -r requirements/search.txt
```

### Chỉ dùng phần dưới khi cần cài mới/sửa torch CUDA

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
& $py -m pip install --index-url https://pypi.org/simple -r requirements/rag.txt
if ($LASTEXITCODE -ne 0) { throw 'Cài thư viện pipeline thất bại.' }
& $py -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Các thư viện đang xung đột.' }
& $py scripts/vibiomir.py benchmark --check-only
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra CUDA chưa đạt; xem lỗi phía trên.' }
```

Kết quả cuối phải có `gpu` là RTX 2050, `cuda` khác `null` và kiểm tra thoát thành công. Wheel PyTorch khoảng 2,9 GB được lưu tại `work\wheels`; nếu mạng ngắt, chạy lại khối lệnh để tiếp tục tải. Nếu pip báo wheel hỏng, xóa **riêng file wheel đó** rồi chạy lại. Không cần cài CUDA Toolkit riêng. [Wheel PyTorch CUDA 12.8](https://download.pytorch.org/whl/cu128/torch/)

## 3. Chạy thật đến bài nộp

### Local: nguồn `nguyen/all.parquet`

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source nguyen/all.parquet --limit 0 --out work/run_quality_all
```

Đây là BGE-M3 + BGE reranker thật. File nộp: `work/run_quality_all/submission/submission.zip`.
`--limit 0` lấy hết file. Dùng thư mục mới để so với pipeline cũ.

Chọn khoảng ID từ các nhánh crawl:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source nguyen --id-start 504799 --id-end 568887 --limit 0 --out work/run_quality_ids_504799_568887
```

ID là mã tài liệu, không phải vị trí dòng; bao gồm hai đầu và có thể có khoảng trống. Khi có `--limit`, chia trần theo kích thước nguồn **sau lọc ID**, lấy ID nhỏ trước trong mỗi nguồn. `prepare_manifest.json` ghi khoảng yêu cầu, ID min/max thực, nguồn và số giữ lại. Trần lớn hơn số hiện có vẫn chạy với số hiện có.

Local lấy HF (đăng nhập `hf auth login` trước):

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source hf --id-start 504799 --id-end 568887 --limit 0 --out work/run_quality_hf_ids
```

Tùy chọn: `--max-hours 12` dừng theo giờ thực; `--rerank-k 160` chấm nhiều hơn, chi phí tăng và điểm không chắc tăng. `--dry-run` chỉ xem kế hoạch. `--architecture cascade` dùng tầng thẻ cũ; muốn bật dịch ở luồng cũ phải thêm `--enable-translation`.

```text
work/run_quality_all/
  corpus/            snapshot, dropped.jsonl, prepare_manifest.json
  chunks/            mọi chunk trong corpus đã chọn, offset và manifest
  index/full/        BM25, embeddings, passages.sqlite; FAISS nếu bật
  retrieval/         candidates, candidate_trace, cache điểm, manifest
  submission/        submission.json, submission.zip, manifest kiểm tra
  stages/, logs/     trạng thái và log từng bước
  pipeline_status.json  running / complete / budget_exhausted / failed
  pipeline_config.json  cấu hình lần gọi gần nhất
```

### Kaggle: dữ liệu HF

1. Upload [pipeline_for_kaggle.ipynb](../../notebooks/pipeline_for_kaggle.ipynb), bật Internet, chọn T4 x2, thêm Secret `HF_TOKEN` có quyền đọc.
2. Ô đầu: đổi **`ID_START`, `ID_END`**. Mặc định `504799–568887` là ví dụ từ lần chạy local trước. Chỉnh `LIMIT_ROWS`, `MAX_WALL_HOURS` theo tài nguyên thật còn lại. Hai đầu `None` = không giới hạn khoảng; trần dòng `0` = lấy hết khoảng.
3. Run All. Hai GPU chia phần không trùng, chỉ một model rerank.
4. Chỉ lấy `/kaggle/working/submission.zip` khi báo hoàn tất. Mã 124 = hết thời gian đã đặt, chưa có bài nộp mới; Save Version giữ Output.
5. Phiên mới gắn Output cũ vào Input, đặt `RESTORE_RUN` tới thư mục run cũ, giữ nguyên `RUN_NAME`, ID, commit, số GPU, code và cấu hình. Không tự đồng bộ checkpoint lên HF. Đổi dữ liệu: tên run mới, không restore run cũ.

Kaggle mặc định mới có `ENCODER='qwen3-embedding-4b'`, `RERANKER='qwen3-reranker-4b'`, thư mục `run_qwen4b_...`. Không restore run BGE cũ vì phải dựng lại embedding bằng model mới. Chỉ local vẫn dùng BGE.

Hai model tải lần đầu khoảng 16 GB; cache trọng số tại `/kaggle/temp/vibiomir_hf_cache`, không lưu vào Output. Qua phiên mới có thể cần tải lại trọng số, còn checkpoint tính toán lấy từ Output cũ. Kaggle cài thêm `accelerate`, giữ torch CUDA có sẵn, không cần bitsandbytes/FlashAttention 2. Mỗi model chạy FP16, được ghim revision; xem model và số tham số thực trong `dense_manifest.json` và `retrieval_manifest.json`.

Ngân sách là **giờ thực**, không phải quota GPU còn lại của tài khoản. Đối chiếu Settings và chừa thời gian lưu Output. Không đảm bảo chạy xong trong giới hạn: deadline dừng subprocess, giữ phần xong để chạy tiếp. Copy/khôi phục Output và setup cũng tốn thời gian.

Sau khi sửa source:

```powershell
.\env\Scripts\python.exe scripts/build_notebooks.py kaggle
```

Lệnh này chỉ cập nhật notebook pipeline, không sửa notebook teacher.

## 4. Resume và giữ artifact

Chạy lại **đúng lệnh mục 3** khi bị ngắt. Bước hoàn thành chỉ được dùng lại khi khóa/checksum khớp. Corpus không tự cập nhật theo crawl; muốn đưa dữ liệu crawl mới vào thì chạy với `--out` mới. Code khóa thư mục run để tránh hai tiến trình cùng ghi.

- Embedding ghi `embeddings.partial.npy`, flush và checkpoint sau mỗi 2.048 chunk trong lệnh pipeline; chỉ khi đủ mới công bố `embeddings.npy`. Lượt ngắt thường chỉ tính lại shard đang dở. Giữ cả partial và checkpoint.
- Điểm rerank cache theo revision/config model, prompt, query và passage; commit sau mỗi query. Đổi ngưỡng bài không phải chấm lại, đổi text/model không dùng nhầm điểm cũ.
- Luồng mặc định không tạo bản dịch. Bản dịch có sẵn vẫn dùng được qua `--translations` nếu muốn so sánh.
- Nếu thay nguồn/config/code làm snapshot cũ không còn tương ứng, dùng `--out` mới. Không xóa corpus để ép run cũ đọc lại crawl đang tăng.

Giữ corpus, chunks, index/checkpoint, cache và manifest cùng nhau. Mỗi ma trận embedding khoảng `số_dòng × 1024 × 2 byte`; mặc định có một ma trận chunk; hai GPU còn giữ các file part và file ghép, cộng BM25, corpus, cache model và file tạm. Cache Hugging Face mặc định nằm ngoài `work/`; có thể đặt `$env:HF_HOME` sang ổ đủ chỗ trước lần tải đầu tiên. Lần đầu tải nhiều model cần dung lượng và thời gian mạng đáng kể.

## 5. Kiểm tra trước khi nộp

Trong `corpus/prepare_manifest.json`: xem `sources` (đúng các run mong muốn), số giữ lại, lý do loại, domain/ngôn ngữ. Corpus chỉ phủ phần nguồn BTC đã crawl; tài liệu đúng chưa crawl sẽ không thể được retrieve. Trong `chunks/chunk_manifest.json`: số tài liệu và số chunk toàn corpus đã chọn.

Trong `logs/`: xem tốc độ encode/rerank và các lần tự giảm batch. Bộ đếm chunk repo khác tokenizer model và tokenizer BTC. Model cắt ở 1024 token gồm cả tiêu đề/prompt/query, nên có thể bỏ đuôi đoạn dài. Nếu bị cắt nhiều, giảm chunk size hoặc tăng max_length sau khi đo lại VRAM; đổi chunk cần index mới.

Trong `submission/submission_manifest.json`:

- Số query bằng số hàng `data/query.parquet` (bộ hiện tại: 1.200).
- `queries_without_candidates = 0` nghĩa là không thiếu bản ghi query, không bảo đảm mọi query có tài liệu đúng.
- Kỳ vọng `dropped_docs = 0`, `dropped_chunks = 0` với corpus chính thức.
- `resliced_from_offsets` bằng số chunk đã kiểm tra; mọi nội dung khớp lát cắt nguồn.
- Nếu `window_tokens > 0`, kiểm tra `chunk_tokens_max` ≤ `window_tokens`; mặc định 0 giữ chunk gốc; `chunks_inside_window` là số đoạn bị bỏ vì đã nằm trong cửa sổ khác cùng tài liệu.
- Kích thước `submission.json`: mặc định tối đa 15 cửa sổ/truy vấn; nếu file quá lớn, giảm `--chunk-max` hoặc `--window-tokens` ở `submit.py`.

Code chặn candidates lệch hash chunk/query, thiếu query khi `--require-complete`, trùng query ID và chunk gắn sai tài liệu. Docs và chunks ngoài danh sách ID chính thức đều bị lọc.

## 6. Đánh giá, hiệu chỉnh và chỉnh ngưỡng không chạy lại GPU

Với một GPU, ứng viên nằm ở `retrieval/candidates.jsonl`; với nhiều GPU là các file `retrieval/part*/candidates.jsonl` (truyền tất cả cho `--candidates`). Chunk của bài nộp lấy từ `chunks/chunks.parquet`.

```powershell
$R = 'work/run_quality_all'
.\env\Scripts\python.exe scripts/vibiomir.py evaluate sheet --candidates $R/retrieval/candidates.jsonl --chunks $R/chunks/chunks.parquet --out $R/eval --limit 60 --per-query 20
# Đọc label_sheet.html, điền relevant trong label_sheet.jsonl.
.\env\Scripts\python.exe scripts/vibiomir.py evaluate collect --sheet $R/eval/label_sheet.jsonl --out $R/eval
.\env\Scripts\python.exe scripts/vibiomir.py evaluate score --labels $R/eval/labels.jsonl --submission $R/submission/submission.json --candidates $R/retrieval/candidates.jsonl --corpus $R/corpus/corpus.parquet --out $R/eval/main
```

Hiệu chỉnh điểm reranker thành xác suất (Platt, tách theo ngôn ngữ tài liệu), rồi dựng lại bài nộp mà không chạy lại GPU:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py evaluate calibrate --labels $R/eval/labels.jsonl --candidates $R/retrieval/candidates.jsonl --out $R/eval
.\env\Scripts\python.exe scripts/vibiomir.py submit --candidates $R/retrieval/candidates.jsonl --chunks $R/chunks/chunks.parquet --corpus $R/corpus/corpus.parquet --queries data/query.parquet --links data/links_corpus.parquet --require-complete --profile f2 --calibration $R/eval/calibration.json --window-tokens 0 --out $R/submission_calibrated
```

`calibrate` từ chối nhãn `pseudo`. Nhãn dev gộp từ chính ứng viên của hệ thống nên đánh giá thấp lỗi `not_retrieved`; Recall/F2 local chỉ phản ánh nhãn đã có. Tokenizer LCS local là giả định ghi trong `schema.py`, điểm chunk có thể khác BTC.

Các tham số chỉnh nhanh của `submit.py`: `--window-tokens` (0–1024), `--missing` (khối lượng tài liệu đúng ước lượng là đã bỏ sót mỗi truy vấn; tăng thì danh sách dài hơn), `--chunk-max`, `--doc-max`. Profile cũ `recall`/`balanced`/`precision` vẫn dùng được để so sánh.

## 7. Lệnh riêng và sự cố

Các dòng về `translate` chỉ áp dụng khi chủ động bật cascade cũ; mặc định mới không chạy khâu này.

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

## Rebuild 100k (10/10/2026)

Full-corpus chunk/index rebuild and progressive model experiments, without LLM query rewriting: [rebuild_100k.md](rebuild_100k.md).

`powershell
.\env\Scripts\python.exe scripts/vibiomir.py rebuild
`
