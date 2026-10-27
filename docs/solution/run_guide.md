> C?p nh?t encoder local: Qwen3 Embedding 0.6B, FP16 tr?n GPU, v?n chia theo
> token th?t v? ranh gi?i c?u. Notebook Kaggle gi? 8B. C?c v? d? 4B b?n d??i l?
> c?u h?nh tr??c; mu?n ch?y 4B ph?i ch? ??nh `--encoders qwen3-embedding-4b`.
>
> Ch?y embedding local ID 0?50000:
>
> ```powershell
> .\env\Scripts\python.exe scripts/vibiomir.py pipeline --source hf --id-range 0:50000 --language all --limit 0 --encoders qwen3-embedding-0.6b --chunk-tokenizer Qwen/Qwen3-Embedding-0.6B --chunk-target 320 --chunk-overlap 80 --model-max-length 768 --quantize none --cpu-offload --embedding-on-gpu --stop-after dense --out nguyen/pipeline_runs/ids_0_50000_qwen06b
> ```
>
> B? `--stop-after dense` ?? ti?p t?c ??n submission v?i c?ng output. Reranker
> v?n l? 4B CPU offload. Kh?ng tr?n vector 0.6B (1024 chi?u) v?i 4B (2560 chi?u).
> Ch?a c? ph?p ?o ??m b?o 0.6B gi? nguy?n ?i?m; c?n Codabench tr?n c?ng corpus.

# Pipeline truy xuất chính

## Thử nghiệm embedding có ngữ cảnh — 26/10/2026

### Lượt đa ngôn ngữ mới

**Cấu hình đã thống nhất: 20.000 mẫu mỗi ngôn ngữ, không phải hai khoảng đầu.**
Lệnh mới bên dưới thay ví dụ `mixed20k_each` ở dưới. `--balanced20k` tìm mẫu
trong Việt 0–766443, Trung 766444–4392214, Anh 4421055–7466161, lọc đúng
ngôn ngữ và ID/URL chính thức, lấy đủ 20.000 mẫu hợp lệ/ngôn ngữ. Nếu thiếu
thì dừng, không tự giảm số lượng. Ranh giới ID là phạm vi tìm kiếm; tập thử
thực tế được chốt bằng `dataset/selected_ids.json`, không phải toàn phạm vi.

```powershell
.\env\Scripts\python.exe scripts/compare_embeddings.py --balanced20k --arms contextual --out nguyen/pipeline_runs/balanced_60k
```

Lần đầu ghi revision HF, corpus đầu vào 60.000 mẫu và checksum; các lần sau
dùng lại đúng dữ liệu này. Từng phương pháp chuẩn hóa/chia chunk/index riêng.
Bộ lọc trùng nội dung/template ở prepare vẫn được áp dụng; số còn lại theo
ngôn ngữ được ghi trong `comparison.json` và phải cùng corpus hash giữa các bản.
Không gọi tập sau prepare là đúng 60.000 nếu bộ lọc đã loại mẫu.

Sau khi contextual hoàn tất và đã xem kết quả, chạy:

```powershell
.\env\Scripts\python.exe scripts/compare_embeddings.py --balanced20k --arms adjacent --require-contextual --out nguyen/pipeline_runs/balanced_60k
```

Không xóa `balanced_60k/dataset` giữa các lượt. Phương pháp thứ hai không tự
chọn lại mẫu hoặc lấy revision HF mới. Cả hai dùng model 0.6B, rerank 50/keep 25.

`compare_embeddings.py` nhận nhiều `--id-range START:END`. Cấu hình thử nhỏ:
Việt `0:20000`; Anh `4421055:5174242`, `5174255:5276329`; Trung
`766444:902757`, `902759:1006674`. Bảng URL chính thức local có 19.418 ID trong
khoảng Việt và 10.000 ID trong mỗi khoảng Anh/Trung trên; số đã crawl hợp lệ
trên HF có thể ít hơn. Không coi mỗi khoảng số nguyên là đủ 10.000 tài liệu.

Chạy `--arms contextual` trước và chỉ chạy `--arms adjacent --require-contextual`
sau khi có ZIP/report của contextual. Giữ cùng các khoảng và `--out` để chốt
cùng snapshot. Hai model vẫn là Qwen3 0.6B, truy vấn Việt dùng dense đa ngôn ngữ,
không thêm model dịch trong phép đối chứng này. Hai bài có thể cùng thiếu recall
xuyên ngôn ngữ; đó là giới hạn cần ghi nhận khi xem điểm.

```powershell
.\env\Scripts\python.exe scripts/compare_embeddings.py --arms contextual `
  --id-range 0:20000 `
  --id-range 4421055:5174242 --id-range 5174255:5276329 `
  --id-range 766444:902757 --id-range 902759:1006674 `
  --out nguyen/pipeline_runs/mixed20k_each
```

ZIP ở `<out>/contextual/submission/submission.zip`, log ở `<out>/contextual/logs`.
`--require-contextual` chỉ xác nhận đã xuất bài thành công, không xác nhận bài
đã được chấm trên Codabench. Người chạy quyết định thời điểm chạy lượt thứ hai.

Lượt tiếp theo `adjacent`: bỏ 48 token mở đầu bài, chỉ thêm tối đa 48 token
ngay trước chunk (loại overlap). Giữ corpus, chunk 320/80, embedding/reranker
0.6B, top 50/keep 25 và profile submission như `contextual`. Đây là phép đo
tác động của phần mở đầu bài, chưa có bằng chứng sẽ tăng điểm.

```powershell
.\env\Scripts\python.exe scripts/compare_embeddings.py --arms adjacent
```

ZIP: `nguyen/pipeline_runs/embedding_comparison_0_50000/adjacent/submission/submission.zip`.
Kết quả `contextual` đã được người dùng báo: FINAL_SCORE 0.0093, DOCS_F2MACRO
0.0138, CHUNKS_F2MACRO 0.0049, DOCS_PRECISION 0.0721, DOCS_RECALL 0.0119,
CHUNKS_PRECISION 0.0231, CHUNKS_RECALL 0.0043. Đây là điểm do người dùng cung cấp,
chưa đối chiếu ID submission trên Codabench. Giữ ZIP/log cũ để so sánh.

Chỉ giữ hai phương pháp trong luồng thử nghiệm: `baseline` gần nhất (tiêu đề +
chunk 320/80 theo tokenizer) và `contextual` mới. Bộ thử ba cỡ chunk đã được
thay bằng `scripts/compare_embeddings.py`; không tạo thêm bản pipeline riêng.

Phương pháp mới đưa tối đa 48 token đầu bài và 48 token ngay trước chunk vào
đầu vào dense encoder. Chỉ trích từ cùng tài liệu, bỏ phần overlap/trùng, giảm
ngữ cảnh nếu vượt 768 token; không cắt thân chunk để nhường chỗ cho ngữ cảnh.
Chunk gốc, offsets, BM25, reranker và đoạn nộp bài giữ nguyên. Không gọi LLM,
không sinh câu hỏi giả, không fine-tune. Giả thuyết: thông tin đầu bài và câu
trước giúp giải nghĩa những đoạn mất chủ ngữ/ngữ cảnh khi đứng riêng.
Rủi ro: mở đầu bài có thể chứa nội dung chung hoặc chủ đề khác, làm vector kém
tập trung. Chưa có bằng chứng điểm cuộc thi tăng.

Nghiên cứu tham khảo:
- [Contextual Retrieval của Anthropic](https://www.anthropic.com/research/contextual-retrieval)
  bổ sung ngữ cảnh do LLM sinh trước khi lập chỉ mục. Code này là biến thể
  **trích xuất nhẹ**, chỉ thử dense; không áp dụng con số cải thiện của nghiên cứu
  cho biến thể này.
- [Qwen3 Embedding](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B): last-token
  pooling, chuẩn hóa L2, instruction cho query. Không đổi pooling sang mean để
  ghép late chunking khi chưa có phép đo phù hợp.

Local chạy embedding **0.6B** và reranker **0.6B FP16**, không CPU offload;
top-k 300, fuse-k 600, rerank 50, keep 25. Notebook giữ model 8B và dùng chung
hàm ngữ cảnh; trường `EMBEDDING_TEXT` quyết định baseline/contextual.

Chạy phương pháp mới trên HF ID 0–50000 đến ZIP:

```powershell
.\env\Scripts\python.exe scripts/compare_embeddings.py --arms contextual
```

Chạy bản đối chứng gần nhất cùng cấu hình nếu cần đo lại:

```powershell
.\env\Scripts\python.exe scripts/compare_embeddings.py --arms baseline
```

Kết quả: `nguyen/pipeline_runs/embedding_comparison_0_50000/<arm>/submission/submission.zip`.
Gửi cùng profile `submission` lên cùng phase Codabench. `comparison.json` ghi
hash corpus/chunks/query, revision model, thời gian stage, số chunk và byte vector.
Nhập 7 metric vào `codabench_scores.csv`. Giữ code và cấu hình cố định khi resume.
Snapshot HF được dùng chung; script phát hiện khác biệt corpus/chunks/query/model
giữa hai bản đã hoàn tất. Lịch sử local đã bị xóa khi dọn ổ đĩa: không coi đây là
phục hồi log cũ. Nếu chỉ có điểm leaderboard cũ mà không có snapshot/config,
đối chiếu lịch sử chỉ mang tính tham khảo.


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


## Th? nghi?m chunk theo tokenizer (2026-10-25)

Local v? `notebooks/embedding_kaggle_hf.ipynb` d?ng chung `chunk_document`:
320 token m?c ti?u, overlap 80; ?u ti?n cu?i c?u/xu?ng d?ng, ki?m tra ng?n s?ch
encoder bao g?m ti?u ??, gi? ch?nh x?c char_start/char_end. Notebook gi? Qwen3
Embedding 8B, local gi? 4B. C?u h?nh notebook version=2 t?o namespace HF m?i:
kh?ng d?ng l?i vector c? c?ch chunk c?. Kh?ng s?a v?n b?n b?ng LLM.

??y l? gi? thuy?t c?i thi?n retrieval, ch?a c? ?i?m Codabench x?c nh?n. So s?nh
tr?n c?ng t?p ID v? c?ng query; gi? nguy?n reranker/selection. Corpus b? gi?i
h?n c? th? kh?ng ch?a t?i li?u ??p ?n n?n ?i?m th?p kh?ng t? ch?ng minh model k?m.
Token tokenizer v? token c?a h? th?ng ch?m kh?ng nh?t thi?t gi?ng nhau.

Ngu?n: https://huggingface.co/Qwen/Qwen3-Embedding-8B (last-token pooling,
normalize, instruction cho query); https://arxiv.org/abs/2409.04701 (late
chunking d?ng mean pooling, ch?a ?p d?ng tr?c ti?p cho Qwen3).
LegalQA tham kh?o c?u tr?c v? gi? ng? c?nh, kh?ng chuy?n regex ?i?u/Kho?n sang y khoa.

12.800 c?a archive c? l? s? vector, kh?ng ph?i ID. Ph?i x?c ??nh ID cu?i t?
h?ng 12.799 trong chunks.parquet c?a archive tr??c khi ch?n kho?ng k? ti?p.
N?u thay chunk/model th? c?n encode l?i to?n b? t?p th? nghi?m v?o output m?i.
