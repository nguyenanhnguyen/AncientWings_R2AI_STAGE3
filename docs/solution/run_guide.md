# Pipeline truy xuất chính

Entry point duy nhất cho lượt chạy mới là `scripts/vibiomir.py pipeline`. Mặc định:
đọc toàn bộ dữ liệu hợp lệ từ dataset HF của nhóm, chuẩn hóa và chia chunk, dựng
BM25, tạo embedding bằng **Qwen3 Embedding 4B FP16**, mã hóa câu hỏi bằng đúng model
đó, tìm kiếm dense + BM25, chấm lại bằng **Qwen3 Reranker 4B FP16**, rồi tạo hai file
ZIP `submission` và `submission_balanced`. Mỗi model chạy trong subprocess riêng;
corpus và index được lưu với manifest/checksum để tiếp tục sau khi ngắt.
Reranker mặc định chấm tối đa 100 ứng viên mỗi câu hỏi, giữ tối đa 50 ứng viên
cho bước chọn bằng chứng; đổi bằng `--rerank-k` và `--keep` khi có phép đo.

Đây là cấu hình mạnh về model, **chưa được chứng minh cho điểm cao**. Lượt chỉ dùng
79.721 tài liệu PubMed tiếng Anh đã cho điểm public bằng 0; xem
`audit_zero_score_english.md`. Trước một lượt GPU dài, cần kiểm tra độ phủ corpus
và đánh giá trên tập có nhãn độc lập. `pipeline.txt` mô tả cả kiến trúc thiết kế,
bao gồm teacher/student và khâu đánh giá; teacher không nằm trong lệnh này.

## Chạy mới từ dataset HF

Yêu cầu môi trường đã có `torch` CUDA, `transformers`, `accelerate`, `pyarrow`,
`huggingface_hub` và các gói trong `requirements/rag.txt`. Đăng nhập HF bằng token
có quyền đọc repo private của nhóm (`hf auth login` hoặc `HF_TOKEN`). Dùng GPU có
đủ VRAM cho từng model 4B FP16 và batch nhỏ; trên RTX 2050 4 GB phải thêm
`--cpu-offload`, sẽ chậm đáng kể. Cache HF nằm trong `nguyen/hf_pipeline/hf_home`.

Kiểm tra các bước sẽ chạy, không tải corpus hay model:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --out nguyen/pipeline_runs/full_4b --dry-run
```

Chạy toàn bộ nguồn hiện có trên HF:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline --out nguyen/pipeline_runs/full_4b
```

Mặc định `--language all --limit 0 --hf-max-shards 0` để quét hết shard phù hợp.
Để làm thí nghiệm nhỏ, dùng `--language vi --limit 60000 --hf-max-shards 48`
và **thư mục `--out` riêng**. Để giới hạn theo ID, truyền nhiều lần
`--id-range START:END`. Mọi nguồn/ID/URL/query được chốt theo cùng snapshot HF.

Nếu cần giảm bộ nhớ, `--quantize 4bit` áp dụng NF4 cho embedding và reranker;
đây là cấu hình khác, cần `--out` riêng. `--cpu-offload` dùng FP16 với một phần
trọng số nằm trong RAM; yêu cầu `--quantize none`. Bước dịch câu hỏi chỉ chạy khi
corpus có tiếng Anh/Trung; có thể dùng `--translations <translations.jsonl>` đã
kiểm tra hoặc `--skip-translation`. Mặc định dịch bằng Qwen3 4B FP16.

## Chỉ tạo embedding cho toàn bộ HF (RTX 2050 4 GB)

Lệnh này đọc toàn bộ corpus hợp lệ ở snapshot HF, chuẩn hóa, chia chunk theo
đoạn/câu (320 token mục tiêu, 80 token overlap), rồi mã hóa bằng Qwen3
Embedding 4B FP16 với CPU offload. Nó dừng sau dense index; chưa dịch truy vấn,
dựng BM25, rerank hoặc tạo bài nộp. Chạy lại **cùng lệnh** để tiếp tục checkpoint.
Giữ `--out`, cỡ chunk và model cố định trong suốt lượt chạy.

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline `
  --source hf --language all --limit 0 --hf-max-shards 0 `
  --chunk-target 320 --chunk-overlap 80 --model-max-length 768 `
  --encoders qwen3-embedding-4b --quantize none --cpu-offload `
  --stop-after dense --out nguyen/pipeline_runs/hf_all_qwen4b_v1
```

Vector ở `nguyen/pipeline_runs/hf_all_qwen4b_v1/index/qwen3-embedding-4b/embeddings.npy`;
`dense_manifest.json` xác nhận hoàn tất và ghi hash của chunk. Bản HF đầu vào
được chốt ở `nguyen/hf_pipeline/snapshots/`, không tải toàn bộ repo thành các
file shard. Snapshot vẫn chiếm dung lượng vì cần để tái lập nguồn; corpus và
chunks là các artifact riêng. Mã hóa toàn bộ trên RTX 2050 với CPU offload có
thể kéo dài nhiều ngày. 4B là cấu hình model mạnh đã thử chạy, không bảo đảm
điểm cao nếu tài liệu đúng không nằm trong corpus.

Khi muốn chạy phần còn lại, bỏ `--stop-after dense` và giữ nguyên mọi tham số
còn lại, đặc biệt `--out`. Pipeline kiểm tra checksum trước khi dùng lại vector.

## Dùng lại embedding corpus đã hoàn tất


Không tính lại vector khi đã có `embeddings.npy` và `checkpoint.json` khớp với
`chunks.parquet` đã chốt. Lệnh dưới đây dùng lại 85.841 vector của lượt English
trước, nhưng **chỉ để minh họa cách resume**: corpus English này đã đạt 0 điểm
public, nên không nên coi kết quả mới là cải thiện đã xác nhận.

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline `
  --reuse-run nguyen/pipeline_runs/en_batches_01_08 `
  --precomputed-embeddings nguyen/pipeline_runs/en_batches_01_08/qwen4b_cpu_offload `
  --skip-translation `
  --out nguyen/pipeline_runs/en_4b_reuse_new
```

`--reuse-run` dùng corpus, chunk, query và bảng URL của snapshot cũ, nên phải
chỉ định thư mục `--out` mới. Code kiểm checkpoint, model, số hàng, đường dẫn
chunk, SHA của chunk, shape và chuẩn của vector trước khi dùng lại. Encoder câu
hỏi lấy revision và cấu hình từ manifest của embedding corpus. BM25, truy xuất,
rerank và bài nộp chạy trong thư mục mới; BM25 không ghi vào thư mục vector cũ.
Lượt mới chỉ dùng lại embedding khi
truyền **cả hai** cờ nêu trên.

## Đầu ra và tiếp tục

```text
<out>/corpus/corpus.parquet
<out>/chunks/chunks.parquet
<out>/index/bm25/bm25.npz
<out>/index/qwen3-embedding-4b/embeddings.npy
<out>/retrieval/candidates.jsonl
<out>/submission/submission.zip
<out>/submission_balanced/submission.zip
<out>/logs/ và <out>/stages/
```

Với `--reuse-run`, `corpus`, `chunks` và `embeddings.npy` tiếp tục nằm trong
thư mục run gốc; chỉ BM25, retrieval, submission và log nằm trong `--out` mới.

Chạy lại **cùng lệnh** để dùng lại stage hoàn tất có checksum đúng. Embedding
ghi checkpoint theo shard; rerank lưu điểm theo từng câu hỏi trong SQLite.
Không chạy hai tiến trình cùng ghi một thư mục output. Nếu đổi corpus, chunk
hoặc model embedding, dùng output mới và tạo lại vector tương ứng. File ZIP
chỉ được coi là hợp lệ về cấu trúc sau khi validation; điểm phải đo bằng nhãn
độc lập hoặc leaderboard.

Các lệnh `scripts/vibiomir.py` ở mức `prepare`, `chunk`, `index`, `retrieve`,
`submit`, `evaluate` vẫn là công cụ cho từng khâu và phân tích lỗi; pipeline
chính điều phối chúng. `benchmark` là công cụ đo thủ công, không nằm trong luồng
chạy mặc định. Các script crawler, notebook builder và `teach` phục vụ quy trình
khác, không phải code thừa của pipeline truy xuất.
