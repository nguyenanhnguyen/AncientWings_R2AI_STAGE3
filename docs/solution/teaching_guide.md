# Block T — teacher 32B dạy student 4B / 8B / 14B

Teacher `Qwen3-32B-AWQ` tự viết dữ liệu huấn luyện từ corpus, rồi các student ≤15B học lại ba vai trò đang dùng model trong pipeline: **reranker**, **embedding** và **dịch query**. BTC đã xác nhận được dùng teacher lớn hơn 15B nếu nó chỉ chạy lúc huấn luyện (`docs/note/Q&A, tools.txt`, câu 3). Teacher không bao giờ nhìn thấy 1.200 query test.

Code nằm trong [src/vibiomir/teach/](../../src/vibiomir/teach), gọi qua `scripts/vibiomir.py teach`. Notebook Kaggle: [teach_kaggle.ipynb](teach_kaggle.ipynb).

## Luồng

```text
chunks.parquet ─T1 sample─▶ seeds.jsonl ─T2 generate (Kaggle)─▶ generated/  (query vi + en/zh + evidence)
                                                                  │
                     index Block B ──T3 mine (laptop)─────────────▶ groups.jsonl  (1 positive + 11 negative)
                                                                  │
                                         T4 judge (Kaggle) ───────▶ judged/  (P(yes) của teacher cho từng cặp)
                                                                  │
                                         T5 train (Kaggle) ───────▶ students/<task>-<size>/  (LoRA adapter)
```

| Bước | Lệnh | Máy | Kiểm soát chất lượng |
| --- | --- | --- | --- |
| T1 | `vibiomir.py teach sample` | laptop | Mỗi tài liệu tối đa 1 chunk; domain giới hạn theo căn bậc hai kích thước; 5% làm dev. |
| T2 | `vibiomir.py teach generate` | Kaggle, chia shard | Query phải là tiếng Việt, không chép nguyên từ passage; `evidence` phải có thật trong passage; teacher được trả lời `usable: false` cho trang không có nội dung y tế. |
| T3 | `vibiomir.py teach mine` | laptop (bge-m3 vừa 4 GB) | Bỏ toàn bộ chunk cùng tài liệu với positive. Ghi recall@k của retriever hiện tại trên query tổng hợp vào `groups_manifest.json`. |
| T4 | `vibiomir.py teach judge` | Kaggle, chia shard | Nhóm có positive bị teacher chấm dưới 0,5 sẽ bị bỏ. Negative được chấm từ 0,8 trở lên được coi là positive phụ, không bị đẩy xa. |
| T5 | `vibiomir.py teach train` | Kaggle, mỗi T4 một student | Có MRR/top-1 trên tập dev trước và sau khi train, lưu trong `vibiomir_student.json`. |

## Student

| Vai trò | 4B | 8B | 14B | Thay cho |
| --- | --- | --- | --- | --- |
| reranker | Qwen3-Reranker-4B (fp16) | Qwen3-Reranker-8B (4-bit) | Qwen3-14B (4-bit) | `bge-reranker-v2-m3`, `qwen3-reranker-0.6b` |
| embedding | Qwen3-Embedding-4B (fp16) | Qwen3-Embedding-8B (4-bit) | Qwen3-14B (4-bit) | `bge-m3`, `qwen3-embedding-0.6b` |
| translator | Qwen3-4B | Qwen3-8B | Qwen3-14B | `qwen3-4b` trong bước dịch |

Student 14B cho reranker và embedding khởi đầu từ model chat, không phải model retrieval, nên chỉ đáng thử khi đã có nhiều dữ liệu. Loss dùng:
- **Reranker:** softmax của teacher trên cả nhóm (listwise) cộng BCE theo từng cặp.
- **Embedding:** InfoNCE, có che các positive phụ, cộng chưng cất phân phối của teacher.
- **Translator:** SFT, chỉ tính loss trên phần bản dịch.

## Chạy

### 0. Chuẩn bị (laptop, một lần)

```powershell
$env:HF_TOKEN = '<token có quyền ghi>'
.\env\Scripts\python.exe scripts\vibiomir.py teach sample --chunks work\rtx2050_60k\chunks\chunks.parquet --out work\teach --target 30000 --shards 4
.\env\Scripts\python.exe scripts\vibiomir.py teach push --hub-repo AncientWings/AncientWings_R2AI_STAGE3_ds work\teach\seeds.jsonl work\rtx2050_60k\chunks\chunks.parquet
```

`--shards` bằng số tài khoản Kaggle chạy song song. `push` đẩy `src/`, `scripts/` và các file input lên dataset `AncientWings_R2AI_STAGE3_ds` đã dùng cho crawl, dưới các đường dẫn `code/`, `inputs/`, `teach/` để không đụng dữ liệu crawl cũ; notebook Kaggle tải về từ đó. Gói HF free là đủ.

### 1. T2 trên Kaggle

Mở `teach_kaggle.ipynb` trên từng tài khoản và đặt `STAGE='generate'`. Mỗi tài khoản dùng một `SHARD` riêng (0, 1, 2, 3), còn `SHARDS=4`. Sau đó Run All.

Kết quả được đẩy lên `teach/generated/shard_XX_of_04.jsonl` khoảng 10 phút một lần. Hết 11 giờ, notebook tự dừng sạch; Run All lại là chạy tiếp từ chỗ dừng.

**Nếu vLLM không khởi động được trên T4:** đặt `TEACHER='qwen3-32b'` và `BACKEND='hf'`. Cách này dùng bitsandbytes 4-bit, chậm hơn nhiều nhưng không phụ thuộc vLLM. Tôi chưa chạy thử vLLM trên T4 lần nào, nên cần kiểm tra ô đầu tiên trước khi để chạy dài.

### 2. T3 trên laptop

```powershell
.\env\Scripts\python.exe -c "from huggingface_hub import snapshot_download as d; d('AncientWings/AncientWings_R2AI_STAGE3_ds', repo_type='dataset', local_dir='work/teach_hub', allow_patterns=['teach/generated/*'])"
Copy-Item -Recurse -Force work\teach_hub\teach\generated work\teach\
.\env\Scripts\python.exe scripts\vibiomir.py teach mine --teach work\teach --chunks work\rtx2050_60k\chunks\chunks.parquet --index work\rtx2050_60k\index\bge-m3 --extra-index work\rtx2050_60k\index\qwen3-embedding-0.6b --shards 4
.\env\Scripts\python.exe scripts\vibiomir.py teach push --hub-repo AncientWings/AncientWings_R2AI_STAGE3_ds work\teach\groups.jsonl
```

Xem `work\teach\groups_manifest.json` → `retriever_on_synthetic_queries`. Đây là recall của retriever hiện tại trên các câu hỏi đã biết chunk đáp án: một thước đo offline không tốn lượt nộp, và cũng là mốc để so sánh student embedding.

### 3. T4 trên Kaggle

Dùng notebook như ở bước 1 nhưng đặt `STAGE='judge'`.

### 4. T5 trên Kaggle

Đặt `STAGE='train'`, `TRAIN_JOBS=[('reranker','4b'), ('embedding','4b')]`; hai student chạy song song, mỗi T4 một student. Adapter và checkpoint được đẩy lên `HUB_MODEL_REPO`. Session tiếp theo để `RESUME=True` là chạy tiếp được.

Chạy thử trước với `TRAIN_LIMIT=500` để xem tốc độ `update/phút` trong log rồi mới chạy thật.

### 5. Dùng student trong pipeline

Tải `students/<task>-<size>/` về một thư mục rồi đặt `VIBIOMIR_STUDENTS` trỏ tới đó. Student sẽ xuất hiện với tên `student:<thư mục>`:

```powershell
$env:VIBIOMIR_STUDENTS = 'work\students'
.\env\Scripts\python.exe scripts\vibiomir.py pipeline --source ... --encoders student:embedding-4b --rerankers student:reranker-4b --translation-model student:translator-4b
```

Laptop 4 GB không chạy được student 4B trở lên, nên bước index và retrieve có student cũng phải chạy trên Kaggle.

## Ngân sách GPU (ước tính, chưa đo)

Có 3–5 tài khoản × 30 giờ GPU/tuần. Các con số dưới đây là ước lượng từ thông lượng điển hình của T4, **chưa chạy thật lần nào**. Nên đo trên lần chạy đầu (log in tốc độ `/s` và `update/phút`) rồi chỉnh `--target`, `--limit` theo đó.

| Việc | Khối lượng (30.000 seed, 4 shard) | Ước tính |
| --- | --- | --- |
| T2 generate | ~7.500 seed/shard | 2–5 giờ mỗi shard |
| T4 judge | ~22.000 nhóm × 12 cặp | 4–10 giờ mỗi shard |
| T5 reranker 4B | 1 epoch | 10–20 giờ |
| T5 embedding 4B | 1 epoch | 6–12 giờ |
| T5 8B / 14B | | gấp khoảng 2× / 3,5× bản 4B |
| Index 225k chunk bằng embedding 4B | | 2–3 giờ |

Thứ tự nên làm:
1. Teacher (T2, T4) cho cả 30.000 seed.
2. Embedding 4B và reranker 4B. Recall đang là điểm yếu nhất, nên embedding được ưu tiên.
3. Chỉ lên 8B/14B nếu bản 4B cải thiện `dev_mrr` và điểm leaderboard, và còn giờ GPU.

Translator chỉ có ích khi corpus có tài liệu zh/en; corpus hiện tại toàn tiếng Việt.

## Giới hạn đã biết

- Query tổng hợp chỉ là xấp xỉ query thật. `dev_mrr` đo khả năng phân biệt bên trong nhóm, không thay được leaderboard.
- Negative chỉ được lấy trong corpus đã crawl. Tài liệu chưa crawl thì không student nào tìm được: khâu crawl vẫn là giới hạn trên của recall.
- vLLM trên T4 (Turing) và bộ thông số batch/độ dài mặc định chưa được chạy thử. Test trong repo chỉ kiểm phần dữ liệu, parse, log chạy tiếp và loss trên CPU.
