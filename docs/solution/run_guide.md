# Chạy pipeline thác đến `submission.zip`: laptop và Kaggle, cùng dữ liệu từ Hugging Face

Chạy PowerShell từ thư mục gốc dự án. Một lệnh điều phối (`scripts/pipeline.py`) chạy mọi khâu, mỗi khâu một tiến trình riêng, lưu log và dùng lại khâu đã xong khi chạy lại. Pipeline đọc một **snapshot** dữ liệu crawl rồi đóng băng; crawl vẫn chạy song song không ảnh hưởng run hiện tại. Lý do thiết kế: [research.md](research.md).

**Trạng thái xác minh (10/10/2026):** toàn bộ luồng mới đã chạy đầu–cuối trên CPU với encoder `hash` và reranker `identity`, trên 3.000 tài liệu thật của corpus HF và 1.200 truy vấn thật; 129 test offline đạt. **Chưa chạy với model thật trên GPU nào, chưa có điểm leaderboard cho thiết kế mới.** Các con số mặc định (số tài liệu ứng viên, `rerank-k`, cửa sổ 768 token) là điểm xuất phát để đo, chưa phải giá trị tối ưu.

## 1. Thiết kế đang chạy

| Khâu | Cách chạy | Ghi chú |
|---|---|---|
| fetch | Tải `corpus/*.parquet` của dataset nhóm và `query`/`links_corpus` của BTC từ HF; **ghim commit** của corpus cho thư mục run | Mặc định `--source hf`; chạy lại cùng `--out` dùng đúng commit đã ghim |
| prepare | Đọc corpus HF vừa tải (hoặc run crawl local nếu `--source nguyen`); lọc lỗi tải/trang chủ/template; giữ `review` | `--source` còn nhận thư mục cha, run hoặc file |
| chunk | Chunk đích 320 token, overlap 80, trần 768; giữ offset nguồn | Chạy cho toàn corpus, chỉ CPU |
| cards | Một **thẻ** mỗi tài liệu: tiêu đề + đoạn mở đầu ≤160 token | Trang hỏi–đáp: thẻ chứa câu hỏi của bệnh nhân |
| translate | **Một LLM** (Qwen3-4B) sinh theo batch: bản dịch tiếng Trung (+Anh nếu corpus có ≥1% tài liệu Anh) và đoạn trả lời giả HyDE tiếng Trung/Việt | Chỉ để tìm; `chunk_text` luôn lấy từ corpus |
| cards_bm25, cards_dense | BM25 + BGE-M3 trên thẻ của toàn corpus | Rẻ hơn nhiều so với encode mọi chunk |
| doc_search | Tìm trên thẻ, giữ `--docs-per-query` tài liệu mỗi truy vấn | Không rerank ở tầng này |
| subset | Giữ chunk của các tài liệu ứng viên (hợp của mọi truy vấn) | Chunk id/offset giữ nguyên |
| subset_bm25, subset_dense | Chỉ mục đoạn trên tập con | |
| retrieve | BM25 + dense + **kênh card** (thứ hạng tài liệu từ tầng thẻ) → RRF → **một reranker**, chấm đoạn tiếng Trung bằng bản dịch tiếng Trung của câu hỏi | Với nhiều GPU, chia truy vấn mỗi card một phần |
| submit | Profile **`f2`**: giữ một mục khi xác suất > F2 kỳ vọng / 5; **mở rộng đoạn nộp** thành cửa sổ ≤768 token (vẫn là đoạn trích nguyên văn); bỏ đoạn đã nằm trong cửa sổ khác | Xuất thêm bản `submission_nowindow` để so sánh A/B |

Hồ sơ `--profile local` (mặc định): 1 GPU 4 GB, BGE-M3, **bge-reranker-v2-m3**, Qwen3-4B 4-bit, 150 tài liệu/truy vấn, rerank 60 đoạn. Hồ sơ `kaggle`: T4×2, BGE-M3, **Qwen3-Reranker-4B**, Qwen3-4B fp16, 250 tài liệu/truy vấn, rerank 80 đoạn. Mọi giá trị đều ghi đè được bằng tham số.

Điểm reranker chưa được hiệu chỉnh thành xác suất. Khi có nhãn dev do người gán, chạy `scripts/evaluate.py calibrate` để sinh `calibration.json` rồi truyền `--calibration` cho pipeline (mục 6).

## 2. Chuẩn bị môi trường CUDA (chạy một lần)

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
& $py scripts/benchmark.py --check-only --quantized
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra CUDA/NF4 chưa đạt; xem lỗi phía trên.' }
```

Kết quả cuối phải có `gpu` là RTX 2050, `cuda` khác `null` và `nf4_gpu_test: ok`. Wheel PyTorch khoảng 2,9 GB được lưu tại `work\wheels`; nếu mạng ngắt, chạy lại khối lệnh để tiếp tục tải. Nếu pip báo wheel hỏng, xóa **riêng file wheel đó** rồi chạy lại. Không cần cài CUDA Toolkit riêng. [Wheel PyTorch CUDA 12.8](https://download.pytorch.org/whl/cu128/torch/) · [bitsandbytes trên Windows](https://huggingface.co/docs/bitsandbytes/en/installation)

## 3. Chạy từ đầu đến bài nộp

### Trên laptop

Dữ liệu lấy từ Hugging Face giống hệt Kaggle: corpus nhóm `AncientWings/AncientWings_R2AI_STAGE3_ds` (`corpus/*.parquet`) và `query.parquet`, `links_corpus.parquet` của BTC. Dataset nhóm là **private**, nên đăng nhập một lần bằng token có quyền đọc:

```powershell
.\env\Scripts\hf.exe auth login
```

(Kiểm tra ngày 10/10: token đang lưu trên máy bị HF trả 401, cần đăng nhập lại.)

Xem kế hoạch các khâu, chưa tải gì:

```powershell
.\env\Scripts\python.exe scripts/pipeline.py --out work/run_hf --dry-run
```

Chạy thật (mặc định `--source hf --profile local`):

```powershell
.\env\Scripts\python.exe scripts/pipeline.py --out work/run_hf
```

**Chạy tiếp khi bị ngắt:** gõ lại đúng lệnh. Khâu `fetch` tiếp tục tải phần còn thiếu; commit corpus đã ghim trong `work/run_hf/hf/pinned.json` nên dữ liệu không đổi dù nhóm vừa đẩy thêm lên HF; khâu đã xong được dùng lại. Muốn dùng dữ liệu mới nhất trên HF: chạy với `--out` mới. Muốn chạy lại đúng một snapshot cũ: `--hf-revision <commit>`.

Chạy thử nhỏ trước: thêm `--limit 20000` (20.000 dòng đầu vào theo ID tăng dần) và dùng `--out` riêng. Vẫn chạy được trên crawl local mà không cần HF: `--source nguyen` (khi đó `query`/`links` lấy từ `data\`).

Trên GPU 4 GB, LLM dịch và encoder không cùng nằm trên card, nên các khâu GPU chạy lần lượt. Pilot đo batch cho đúng một encoder và một reranker trước khi chạy dài. Snapshot hiện tại gồm cả trang tiếng Trung của các shard, nên khâu dịch sẽ chạy; tắt bằng `--skip-translation`, tắt HyDE bằng `--hyde` không kèm giá trị.

```text
work/run_hf/
  hf/                pinned.json (commit đã ghim), fetch_manifest.json, corpus_<commit>/corpus/*.parquet, source/ (query, links)
  corpus/            snapshot, dropped.jsonl, prepare_manifest.json
  chunks/            chunk của toàn corpus
  cards/             thẻ tài liệu
  pilot.json         batch đã chọn, VRAM (chỉ profile local)
  translations/      bản dịch + HyDE, bản bị loại, SQLite cache
  index/cards/       BM25 + embedding của thẻ
  doc_search/        tài liệu ứng viên mỗi truy vấn
  subset/            chunk của tài liệu ứng viên, doc_candidates.jsonl
  index/subset/      BM25 + embedding của tập con
  retrieval/         candidates.jsonl (một thư mục part<i> mỗi GPU khi có nhiều GPU), cache điểm
  submission/        BÀI NỘP CHÍNH: f2 + cửa sổ 768 token
  submission_nowindow/  cùng lựa chọn, không mở rộng cửa sổ — để A/B
  stages/, logs/     khóa và SHA-256 từng khâu; log nối tiếp
```

**File nộp:** `work/run_hf/submission/submission.zip`. Bản `submission_nowindow` chỉ dùng để đo riêng tác động của việc mở rộng cửa sổ trên leaderboard.

### Trên Kaggle, dữ liệu lấy từ Hugging Face

Dùng [notebooks/for_kaggle.ipynb](../../notebooks/for_kaggle.ipynb). Notebook chạy **cùng lệnh** `pipeline.py --source hf` với `--profile kaggle`: khâu `fetch` tải và ghim dữ liệu HF, rồi hai T4 chạy song song hai nửa embedding và hai nửa truy vấn rerank. Cần Secret `HF_TOKEN` vì dataset nhóm private. Chạy lại ô pipeline trong cùng phiên thì các khâu đã xong được dùng lại. Kết quả: `/kaggle/working/submission.zip`.

Code của repo được nhúng sẵn trong notebook. Sau khi sửa code trên laptop:

```powershell
.\env\Scripts\python.exe scripts/build_kaggle_notebook.py
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

Trong `pilot.json`: xem tốc độ, VRAM và mẫu vượt `max_length`. Bộ đếm chunk repo khác tokenizer model và tokenizer BTC. Model cắt ở 1024 token gồm cả tiêu đề/prompt/query, nên có thể bỏ đuôi đoạn dài. Nếu bị cắt nhiều, giảm chunk size hoặc tăng max_length sau khi đo lại VRAM; đổi chunk cần index mới.

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
$R = 'work/run_hf'
.\env\Scripts\python.exe scripts/evaluate.py sheet --candidates $R/retrieval/candidates.jsonl --chunks $R/subset/chunks.parquet --out $R/eval --limit 60 --per-query 20
# Đọc label_sheet.html, điền relevant trong label_sheet.jsonl.
.\env\Scripts\python.exe scripts/evaluate.py collect --sheet $R/eval/label_sheet.jsonl --out $R/eval
.\env\Scripts\python.exe scripts/evaluate.py score --labels $R/eval/labels.jsonl --submission $R/submission/submission.json --candidates $R/retrieval/candidates.jsonl --corpus $R/corpus/corpus.parquet --out $R/eval/main
```

Hiệu chỉnh điểm reranker thành xác suất (Platt, tách theo ngôn ngữ tài liệu), rồi dựng lại bài nộp mà không chạy lại GPU:

```powershell
.\env\Scripts\python.exe scripts/evaluate.py calibrate --labels $R/eval/labels.jsonl --candidates $R/retrieval/candidates.jsonl --out $R/eval
.\env\Scripts\python.exe scripts/submit.py --candidates $R/retrieval/candidates.jsonl --chunks $R/subset/chunks.parquet --corpus $R/corpus/corpus.parquet --queries data/query.parquet --links data/links_corpus.parquet --require-complete --profile f2 --calibration $R/eval/calibration.json --window-tokens 768 --out $R/submission_calibrated
```

`calibrate` từ chối nhãn `pseudo`. Nhãn dev gộp từ chính ứng viên của hệ thống nên đánh giá thấp lỗi `not_retrieved`; Recall/F2 local chỉ phản ánh nhãn đã có. Tokenizer LCS local là giả định ghi trong `schema.py`, điểm chunk có thể khác BTC.

Các tham số chỉnh nhanh của `submit.py`: `--window-tokens` (0–1024), `--missing` (khối lượng tài liệu đúng ước lượng là đã bỏ sót mỗi truy vấn; tăng thì danh sách dài hơn), `--chunk-max`, `--doc-max`. Profile cũ `recall`/`balanced`/`precision` vẫn dùng được để so sánh.

## 7. Lệnh riêng và sự cố

`--dry-run` in lệnh của từng khâu. Trên Windows ưu tiên lệnh điều phối: nó truyền JSON trọng số bằng danh sách đối số, tránh lỗi quote PowerShell. CLI cũ vẫn dùng được, xem `scripts/index.py --help`, `scripts/retrieve.py --help`, `scripts/translate.py --help`.

| Tình huống | Xử lý |
|---|---|
| CUDA unavailable / CPU-only torch | Làm mục 2 và chạy preflight; không tự chuyển toàn lượt sang CPU |
| OOM khi dịch | Batch tự giảm một nửa khi hết VRAM. Nếu batch 1 vẫn lỗi: `--translation-model qwen3-1.7b` (vẫn NF4), hoặc `--translation-model qwen3-0.6b --translation-quantize none`, rồi kiểm tra chất lượng bản dịch |
| OOM encode/rerank batch >1 | Code tự giảm batch. Nếu batch 1 vẫn lỗi, giải phóng VRAM; giảm max_length/chunk size và đo lại |
| Đã đo pilot, muốn bỏ qua | `--skip-pilot` (hoặc `--encoder-batch`, `--rerank-batch`); dự phòng 16 encoder, 4 reranker, không phải batch đã benchmark |
| Rerank quá lâu | Giảm `--rerank-k` (số cặp = 1.200 × rerank-k) hoặc đổi sang reranker nhỏ hơn; có thể giảm Recall |
| Đổi model | Output mới, `--encoder qwen3-embedding-0.6b` hoặc `--reranker qwen3-reranker-0.6b`; luôn chỉ một reranker |
| Dịch có `rejected` | Xem `translations/rejected.jsonl`; pipeline dùng phần hợp lệ và giữ query gốc |
| Embedding checkpoint differs | Dùng index/output mới; không ghép model hoặc chunk khác vào checkpoint |
| Frozen corpus/config changed | Dùng `--out` mới để snapshot mới, giữ run cũ |
| Hash mismatch | Dùng artifact cùng run hoặc chạy lại từ khâu đã thay đổi |
| Mạng ngắt tải model | Chạy lại lệnh; cache Hugging Face và cache pipeline độc lập |

Kiểm thử offline, không tải model:

```powershell
.\env\Scripts\python.exe -m unittest discover -s tests -v
.\env\Scripts\python.exe -m unittest discover -s scripts -p "test_*.py"
```

Bộ bổ sung kiểm tra resume embedding, tìm vector theo block, suffix Qwen, bản dịch cũ/đổi chữ số, ID ngoài corpus, ngưỡng sau giới hạn chunk/document, CLI đến ZIP và cache/snapshot. `tests/test_cascade.py` kiểm tra phần thác: tìm nguồn trong `nguyen\`, thẻ và tập con giữ nguyên chunk, kênh card, chia truy vấn theo shard, ghép embedding nhiều phần, ngưỡng F2 (so với vét cạn), hiệu chỉnh Platt và cửa sổ nộp. Các test này không chứng minh chất lượng model hay thông lượng RTX 2050; pilot và lượt nộp thật cung cấp số đo đó.
