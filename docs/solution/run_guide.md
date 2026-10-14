# Chạy pipeline local Qwen3-4B NF4 trên RTX 2050 4 GB

Chạy PowerShell từ thư mục gốc dự án. Cấu hình này dùng **model thật**, dành cho một GPU RTX 2050 4GB. Lệnh điều phối đọc snapshot chốt từ HF, lưu log và tiếp tục được khi bị ngắt.

**Trạng thái xác minh:** CLI và kiểm tra tĩnh đã chạy; chưa đo trực tiếp Qwen3-Embedding-4B/Reranker-4B NF4 trên RTX 2050 4 GB. Pilot của run mới tải model và đo bộ nhớ trước khi xây index dài. Nếu batch 1 vẫn OOM thì profile này không vừa GPU; xem lựa chọn nhẹ hơn bên dưới. Không dùng lại `--out` của run cũ vì snapshot và khóa code đã đổi.

## 1. Cấu hình local

| Khâu | Cách chạy |
|---|---|
| A2–A3 | Đọc 60.000 bản ghi theo ID, lọc lỗi tải/trang chủ/template, giữ bài `review`, bảo toàn ID và nguồn |
| A4 | Chunk đích 320 token, overlap 80, trần 768 theo bộ đếm repo; giữ offset nguồn |
| B0 | Pilot 8 đoạn phân tầng theo độ dài, đo batch 1/2 và VRAM cho từng model 4B NF4 |
| B1 | BM25 với token Việt/Anh và unigram + bigram CJK |
| B2 | **Qwen3-Embedding-4B NF4**, một index; encode theo shard, có checkpoint/resume |
| C1 | Query gốc, biến thể bỏ lời xã giao cho BM25; **Qwen3-4B NF4** dịch Anh/Trung khi corpus có ngôn ngữ đó |
| C2 | Top 300/kênh, weighted RRF, giữ tối đa 600 rồi chọn tối đa 200 để rerank, tối đa 4 chunk/document |
| C3 | **Qwen3-Reranker-4B NF4**, chấm một lượt; điểm lưu trong SQLite theo model, query và chunk |
| D | Giữ 100 ứng viên/query; xuất `recall` và `balanced`, kiểm tra đủ query, ID chính thức, cắt lại chunk từ nguồn |
| E | Công cụ gán nhãn người và đánh giá; chỉ tính F2 khi có nhãn phù hợp |

Hai model 4B chạy **lần lượt**, lượng tử NF4; không chạy đồng thời. NF4 giảm bộ nhớ trọng số nhưng GPU vẫn cần bộ nhớ cho activation và prompt. Độ chính xác sau lượng tử và điểm thi chưa được đo. Điểm yes/no chưa được hiệu chỉnh thành xác suất liên quan. `--weights` cho phép thử trọng số RRF trên tập dev gán nhãn; `--adaptive-submit` bật chọn bằng chứng theo điểm, chỉ dùng sau khi so sánh F2 trên dev.

Lựa chọn model dựa trên [Qwen3-Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B), [Qwen3-Reranker-4B](https://huggingface.co/Qwen/Qwen3-Reranker-4B) và [hướng dẫn lượng tử bitsandbytes](https://huggingface.co/docs/transformers/quantization/bitsandbytes). Model 4B lớn hơn không tự bảo đảm điểm cao hơn trên tập thi; nếu cần so công bằng, giữ cùng snapshot và tạo `--out` mới cho từng cấu hình.

Qwen3-4B NF4 cần thử trên máy vì activation/KV cache còn dùng VRAM ngoài trọng số. Nếu không vừa, dùng lựa chọn nhỏ hơn ở mục 7. Dịch chỉ thêm kênh tìm kiếm; `chunk_text` luôn lấy từ corpus. Bản dịch đổi chữ số, rỗng, thiếu dấu hiệu ngôn ngữ đích hoặc hết ngân sách sinh bị loại và ghi `rejected.jsonl`. Kiểm tra này không bảo đảm đúng ngữ nghĩa, cần xem một số mẫu.

Theo `pipeline.txt`, nhánh teacher 32B → student cần Kaggle T4×2 và dev do người gán nhãn. Lượt local này chạy zero-shot. Chưa tự huấn luyện bằng 1.200 truy vấn thi, chưa có student được chứng minh tốt hơn. GraphRAG trong tài liệu tham khảo cũng chưa có triển khai/đo kiểm để đưa vào bài nộp này.

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
& $py scripts/vibiomir.py benchmark --check-only --quantized
if ($LASTEXITCODE -ne 0) { throw 'Kiểm tra CUDA/NF4 chưa đạt; xem lỗi phía trên.' }
```

Kết quả cuối phải có `gpu` là RTX 2050, `cuda` khác `null` và `nf4_gpu_test: ok`. Wheel PyTorch khoảng 2,9 GB được lưu tại `work\wheels`; nếu mạng ngắt, chạy lại khối lệnh để tiếp tục tải. Nếu pip báo wheel hỏng, xóa **riêng file wheel đó** rồi chạy lại. Không cần cài CUDA Toolkit riêng. [Wheel PyTorch CUDA 12.8](https://download.pytorch.org/whl/cu128/torch/) · [bitsandbytes trên Windows](https://huggingface.co/docs/bitsandbytes/en/installation)

## 3. Chạy từ đầu đến bài nộp

Mặc định đọc dataset riêng của nhóm trên HF, chọn 60.000 tài liệu tiếng Việt có đúng ID/URL BTC. Đăng nhập một lần bằng `hf auth login` hoặc đặt `HF_TOKEN` có quyền đọc repo. Pipeline chốt commit HF, duyệt tối đa 48 shard theo thứ tự phân tán cố định và **dừng khi đủ 60.000 mẫu**; Parquet được đọc theo range từ xa, không tải nguyên bộ shard xuống đĩa. Nếu chưa đủ mẫu trong 48 shard, tăng `--hf-max-shards` hoặc giảm `--limit` và dùng output mới. Lượt thử này là mẫu có kiểm soát, không phải mẫu ngẫu nhiên đều trên toàn corpus.

Xem kế hoạch, chưa tải model hoặc dữ liệu:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source hf --limit 60000 --dry-run
```

Chạy thật:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source hf --limit 60000
```

Nếu cần mẫu hash trải đều hơn trên **mọi** shard, thêm `--hf-sample-mode hash` và `--out` mới. Chế độ này đọc mọi shard từ xa hai lượt nên tốn mạng và thời gian hơn, nhưng vẫn không lưu bản sao tất cả shard trên đĩa.

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source hf --limit 60000 --hf-sample-mode hash --out nguyen/pipeline_runs/rtx2050_4b_hash_60k
```

`--limit 60000` trong nguồn HF là **60.000 bản ghi hợp lệ**, sau bước đối chiếu ID/URL và ngôn ngữ. `prepare` có thể loại thêm template trùng lặp. Đây không phải khoảng ID `1..60000`. Nếu HF chưa có đủ mẫu hợp lệ, snapshot báo số thực tế rồi dừng. Vẫn có thể dùng file local bằng `--source <run hoặc parquet>`; nguồn trước thắng khi trùng ID.

Nếu snapshot chỉ có tiếng Việt, pipeline bỏ dịch Anh/Trung vì chưa có tài liệu đích để tìm. Khi crawl mở rộng sang ngôn ngữ khác, tạo run mới.

### Corpus tiếng Trung

Khi snapshot chủ yếu là tài liệu tiếng Trung, ba tham số sau thay đổi cách truy xuất:

| Tham số | Tác dụng |
| --- | --- |
| `--zh-corpus` | Chỉ dịch sang tiếng Trung (bỏ tiếng Anh), đặt trọng số BM25 của câu hỏi tiếng Việt về 0 và dồn sang kênh tiếng Trung. Từ tiếng Việt không xuất hiện trong văn bản tiếng Trung, nên BM25 tiếng Việt chỉ khớp chữ Latin và chữ số rời rạc, chiếm chỗ của ứng viên thật. |
| `--rerank-query translated_zh` | Đưa câu hỏi đã dịch sang tiếng Trung vào reranker thay vì câu gốc tiếng Việt. |
| `--translations <file>` | Dùng lại `translations.jsonl` đã có, bỏ hẳn bước dịch nên không tải model dịch 4B. |

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --source <run> --out work/zh_run --zh-corpus --rerank-query translated_zh --translations work/run_cu/translations/translations.jsonl
```

`--zh-corpus` và `--rerank-query translated_zh` đều cần câu hỏi đã dịch: hoặc để pipeline tự dịch, hoặc truyền `--translations`. Dùng cùng `--skip-translation` mà không có `--translations` sẽ bị từ chối ngay.

Pilot chọn batch có thông lượng cao nhất trong những batch đã thử trên mẫu; lô dài hơn gây OOM thì encoder/reranker giảm batch và nhớ mức đó. Mỗi lúc chỉ có một model trên GPU. Query encoder được giải phóng trước khi tìm vector trên GPU và nạp reranker. Qwen reranker giữ suffix sau khi cắt input và chỉ tính logits vị trí cuối để giảm bộ nhớ.

```text
nguyen/pipeline_runs/rtx2050_4b_60k/
  corpus/                 snapshot, dropped.jsonl, prepare_manifest.json
  chunks/                 chunks.parquet, chunk_manifest.json
  pilot.json              throughput, batch chọn, peak VRAM, mẫu có nguy cơ bị cắt
  translations/           bản dịch, bản bị loại, SQLite cache, manifest (nếu có)
  index/qwen3-embedding-4b/ BM25, embedding, checkpoint, manifest
  retrieval/              candidates.jsonl, điểm từng model, SQLite cache
  submission/             submission.json, submission.zip, manifest — recall
  submission_balanced/    cùng định dạng — balanced
  stages/                 khóa input/code/tham số và SHA-256 output từng bước
  logs/                   log từng bước, ghi nối tiếp khi chạy lại
```

**File đem đánh giá lần đầu:** `nguyen/pipeline_runs/rtx2050_4b_60k/submission/submission.zip`. Bản `submission_balanced/submission.zip` dùng để so sánh; không tự động nộp cả hai. ZIP chứa đúng một JSON ở gốc. Khi dùng HF, pipeline lấy đúng `query.parquet` và `links_corpus_vi_en_zh.parquet` đã chốt cùng snapshot.

## 4. Resume và giữ artifact

Chạy lại **đúng lệnh mục 3** khi bị ngắt. Bước hoàn thành chỉ được dùng lại khi khóa/checksum khớp. Corpus không tự cập nhật theo crawl; 60k và 100k là hai run riêng. Code khóa thư mục run để tránh hai tiến trình cùng ghi.

- Embedding ghi `embeddings.partial.npy`, flush và checkpoint sau mỗi 512 chunk; chỉ khi đủ mới công bố `embeddings.npy`. Lượt ngắt thường chỉ tính lại shard đang dở. Giữ cả partial và checkpoint.
- Điểm rerank cache theo revision/config model, prompt, query và passage; commit sau mỗi query. Đổi ngưỡng bài không phải chấm lại, đổi text/model không dùng nhầm điểm cũ.
- Dịch cache từng query/ngôn ngữ với model revision và prompt; bản không qua kiểm tra cũng được lưu để xem lại.
- Nếu thay nguồn/config/code làm snapshot cũ không còn tương ứng, dùng `--out` mới. Không xóa corpus để ép run cũ đọc lại crawl đang tăng.

Giữ corpus, chunks, index/checkpoint, cache và manifest cùng nhau. Ma trận embedding 4B có chiều 2560: khoảng `số_chunk × 2560 × 2 byte`, cộng BM25, corpus và file tạm. Với `--source hf`, snapshot và các file BTC nằm trong `nguyen/hf_pipeline/snapshots/`, cache model trong `nguyen/hf_pipeline/hf_home/hub/`, còn các artifact chạy trong `nguyen/pipeline_runs/`. Toàn bộ `nguyen/` đã được `.gitignore` bỏ qua. Lần đầu tải model 4B vẫn cần nhiều GB; đọc Parquet theo range chỉ giảm bản sao dữ liệu corpus.

## 5. Kiểm tra trước khi nộp

Trong `prepare_manifest.json`: `rows_read = 60000`; xem số giữ lại, lý do loại, domain/ngôn ngữ. Corpus 60k chỉ phủ một phần nguồn BTC; tài liệu đúng chưa crawl sẽ không thể được retrieve.

Trong `pilot.json`: xem tốc độ, VRAM và mẫu vượt `max_length`. Bộ đếm chunk repo khác tokenizer model và tokenizer BTC. Profile 4B mặc định cắt ở 512 token gồm cả tiêu đề/prompt/query, nên có thể bỏ đuôi đoạn dài. Nếu bị cắt nhiều, giảm chunk size hoặc tăng `--model-max-length` sau khi đo lại VRAM; đổi chunk cần index mới.

Trong `submission/submission_manifest.json`:

- Số query bằng số hàng `data/query.parquet` (bộ hiện tại: 1.200).
- `queries_without_candidates = 0` nghĩa là không thiếu bản ghi query, không bảo đảm mọi query có tài liệu đúng.
- Kỳ vọng `dropped_docs = 0`, `dropped_chunks = 0` với corpus chính thức.
- `resliced_from_offsets` bằng số chunk đã kiểm tra; mọi nội dung khớp lát cắt nguồn.

Code chặn candidates lệch hash chunk/query, thiếu query khi `--require-complete`, trùng query ID và chunk gắn sai tài liệu. Docs và chunks ngoài danh sách ID chính thức đều bị lọc.

## 6. Đánh giá và chỉnh ngưỡng không chạy lại GPU

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py evaluate sheet --candidates nguyen/pipeline_runs/rtx2050_4b_60k/retrieval/candidates.jsonl --chunks nguyen/pipeline_runs/rtx2050_4b_60k/chunks/chunks.parquet --out nguyen/pipeline_runs/rtx2050_4b_60k/eval --limit 50 --per-query 30
# Đọc label_sheet.html, điền relevant trong label_sheet.jsonl.
.\env\Scripts\python.exe scripts/vibiomir.py evaluate collect --sheet nguyen/pipeline_runs/rtx2050_4b_60k/eval/label_sheet.jsonl --out nguyen/pipeline_runs/rtx2050_4b_60k/eval
.\env\Scripts\python.exe scripts/vibiomir.py evaluate score --labels nguyen/pipeline_runs/rtx2050_4b_60k/eval/labels.jsonl --submission nguyen/pipeline_runs/rtx2050_4b_60k/submission/submission.json --candidates nguyen/pipeline_runs/rtx2050_4b_60k/retrieval/candidates.jsonl --corpus nguyen/pipeline_runs/rtx2050_4b_60k/corpus/corpus.parquet --out nguyen/pipeline_runs/rtx2050_4b_60k/eval/recall
```

So sánh bằng cách chạy `score` với `submission_balanced/submission.json` và `--out .../eval/balanced`. Nhãn trong tập ứng viên có thể thiếu tài liệu đúng chưa tìm ra, nên Recall/F2 local chỉ phản ánh nhãn đã có. Không dùng `pseudo` làm bằng chứng chất lượng. Tokenizer LCS local là giả định được ghi trong `schema.py`, điểm chunk có thể khác BTC.

Ví dụ tạo bài adaptive từ cùng ứng viên:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py submit --candidates nguyen/pipeline_runs/rtx2050_4b_60k/retrieval/candidates.jsonl --chunks nguyen/pipeline_runs/rtx2050_4b_60k/chunks/chunks.parquet --corpus nguyen/pipeline_runs/rtx2050_4b_60k/corpus/corpus.parquet --queries data/query.parquet --links data/links_corpus_vi_en_zh.parquet --require-complete --profile recall --adaptive --out nguyen/pipeline_runs/rtx2050_4b_60k/submission_adaptive
```

Adaptive có thể cắt mất bằng chứng nên chưa bật mặc định. `model_scores` lưu điểm riêng để phân tích. Muốn so một reranker, chạy `scripts/vibiomir.py retrieve` vào output riêng và chọn model đó; điểm đã chấm lấy từ SQLite nếu khóa model/query/chunk khớp.

## 7. Lệnh riêng và sự cố

`--dry-run` in lệnh của từng khâu. Trên Windows ưu tiên lệnh điều phối: nó truyền JSON trọng số bằng danh sách đối số, tránh lỗi quote PowerShell. CLI cũ vẫn dùng được, xem `scripts/vibiomir.py index --help`, `scripts/vibiomir.py retrieve --help`, `scripts/vibiomir.py translate --help`.

| Tình huống | Xử lý |
|---|---|
| CUDA unavailable / CPU-only torch | Làm mục 2 và chạy preflight; không tự chuyển toàn lượt sang CPU |
| OOM dịch Qwen3-4B batch 1 | Chạy lại pipeline thêm `--translation-model qwen3-1.7b`, vẫn NF4. Nếu lỗi thư viện, sửa bitsandbytes hoặc thử `--translation-model qwen3-0.6b --translation-quantize none`, rồi kiểm tra chất lượng bản dịch |
| OOM encode/rerank batch >1 | Code tự giảm batch. Nếu batch 1 vẫn lỗi, profile 4B không vừa GPU hiện tại; dùng output mới với `--encoders bge-m3 --rerankers bge-reranker-v2-m3 --quantize none` |
| Đã đo pilot, muốn bỏ qua | `--skip-pilot` dùng batch dự phòng 1 cho model NF4; không có số đo thông lượng/VRAM |
| Rerank quá lâu | `--rerank-k 100 --keep 100` giảm tối đa 240.000 xuống 120.000 cặp với một reranker/1.200 query, có thể giảm Recall |
| Baseline model nhỏ | Output mới, thêm `--encoders bge-m3 --rerankers bge-reranker-v2-m3 --quantize none`, có thể thêm `--skip-translation` |
| Dịch có `rejected` | Xem `translations/rejected.jsonl`; pipeline dùng phần hợp lệ và giữ query gốc |
| Embedding checkpoint differs | Dùng index/output mới; không ghép model hoặc chunk khác vào checkpoint |
| Frozen corpus/config changed | Dùng `--out` mới để snapshot mới, giữ run cũ |
| Hash mismatch | Dùng artifact cùng run hoặc chạy lại từ khâu đã thay đổi |
| Mạng ngắt tải model | Chạy lại lệnh; cache Hugging Face và cache pipeline độc lập |

Kiểm thử offline, không tải model:

```powershell
.\env\Scripts\python.exe -m unittest discover -s tests -v
```

Bộ bổ sung kiểm tra resume embedding, tìm vector theo block, suffix Qwen, bản dịch cũ/đổi chữ số, ID ngoài corpus, ngưỡng sau giới hạn chunk/document, CLI đến ZIP và cache/snapshot. Các test này không chứng minh chất lượng model hay thông lượng RTX 2050; pilot và lượt nộp thật cung cấp số đo đó.
