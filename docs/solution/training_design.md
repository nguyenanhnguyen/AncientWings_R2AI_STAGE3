# Thiết kế pipeline A2 → E (tiền xử lý, chunk, index, retrieval, bài nộp, đánh giá)

Tài liệu mô tả phần pipeline đã soạn sau khi corpus được crawl xong: mỗi khâu nhận gì, trả gì, có những tham số nào, dùng kỹ thuật gì và đóng vai trò gì với cả hệ thống. Khung block lấy từ [nguyen/pipeline.txt](../../nguyen/pipeline.txt). Block A1 (crawl) nằm ở crawler của nhóm, ngoài phạm vi tài liệu này; pipeline bắt đầu từ đầu ra của crawler. Lệnh chạy từng bước: [run_guide.md](run_guide.md).

Mọi con số dưới đây là giá trị mặc định trong code tại thời điểm viết, không phải kết quả đã tối ưu.

## 0. Hiện trạng

| Hạng mục | Tình trạng |
| --- | --- |
| Code A2 → E | Có, chạy được đầu–cuối qua 6 lệnh trong `scripts/` |
| Kiểm thử | 38 test (`tests/test_pipeline.py`), chạy offline, không cần GPU hay tải model |
| Đã chạy với model thật (bge-m3, bge-reranker) | **Chưa.** Mọi lượt chạy đều dùng `--encoder hash` và `--reranker identity` |
| Đã chạy trên corpus thật | **Có**, 30.000 bản ghi đầu của `nguyen/output/runs/batch01_nguyen` với 1.200 truy vấn thật, khoảng 4,8 phút đầu–cuối, nhưng chỉ với `hash`/`identity` |
| Nhãn dev | **Chưa có.** BTC không phát hành gold; `pseudo` chỉ là vòng tròn |
| Fine-tune | Block T (teacher Qwen3-32B → student 4B/8B/14B cho reranker, embedding, dịch): code và test có, vòng train đã chạy thử bằng bản 0.6B trên laptop; teacher trên Kaggle chưa chạy. Xem [teaching_guide.md](teaching_guide.md) |

`hash` và `identity` chỉ kiểm tra đường ống (offset, ghép index với chunk, hình dạng bài nộp, phép tính metric). Chúng không nói gì về chất lượng truy hồi.

## 1. Dòng dữ liệu

```text
dữ liệu crawl (thư mục run hoặc parquet/json/jsonl)
   │  scripts/prepare.py
   ▼
work/corpus/corpus.parquet
   │  scripts/chunk.py
   ▼
chunks.parquet ──────────────┬─────────────────────────┐
   │ scripts/index.py        │                         │
   ▼                         │                         │
bm25.npz + embeddings.npy    │                         │
   │ scripts/retrieve.py  ◄──┘ (query.parquet)         │
   ▼                                                   │
candidates.jsonl                                       │
   │ scripts/submit.py  ◄──────────────────────────────┘ (re-slice từ corpus)
   ▼
submission.zip ──► scripts/evaluate.py (cần labels.jsonl) ──► EVAL_REPORT.md
```

Hai ràng buộc xuyên suốt:

1. **`doc_id` là số nguyên `id` trong `links_corpus.parquet`, không bao giờ đổi.** Luật chỉ tính tài liệu nằm trong danh sách đó là nhãn dương.
2. **`chunk_text` phải là đoạn trích nguyên văn từ tài liệu.** Vì vậy chunk chỉ lưu vị trí `char_start`/`char_end`, và Block D cắt lại từ corpus rồi so sánh với bản đã đánh chỉ mục.

## 2. Mức linh hoạt khi cấu trúc dữ liệu thay đổi

Đã kiểm thử bằng cách đưa vào `chunk.py` các biến thể đầu vào:

| Biến thể đầu vào | Kết quả |
| --- | --- |
| Thiếu `title`, `domain`; thừa cột lạ; `title`/`text` là `null` | Chạy được, tài liệu không có chữ bị bỏ và được báo trong manifest |
| `id` dạng chuỗi `"12"` | Chạy được, quy về số nguyên và loại trùng với `12` |
| Thân bài nằm ở cột `content` hoặc `body` | Chạy được tự động |
| Thân bài ở cột tên khác | Chạy được với `--text-field <tên cột>`, không sửa code |
| Trang hỏi–đáp (`question` + `answers`) | Chạy được; ghép câu hỏi và câu trả lời bằng dòng trống, **không thêm nhãn** như "Câu hỏi:" |
| JSON mảng, JSONL, Parquet | Cả ba đều đọc được |
| Crawler xuất cả hàng lỗi (`status` khác `ok`) | Mặc định chỉ giữ `status == ok`; `--status ''` tắt bộ lọc |
| Cấu trúc hoàn toàn khác (không có cột nào ở trên) | Dừng với thông báo nêu rõ cột văn bản, không chạy sai âm thầm |

Nguyên tắc để dễ bảo trì: **chỉ một hàm đọc bên trong một dòng corpus**, là `document_text()` trong [schema.py](../../src/vibiomir/common/schema.py). `chunk.py` và `validate.py` đều gọi hàm này, nên chúng luôn dẫn ra cùng một văn bản. Nếu có kiểu dòng mới, chỉ sửa hàm đó (và `document_columns()` đi kèm). Bước re-slice ở Block D cũng sẽ bắt ngay nếu hai bên lệch nhau.

`chunk_manifest.json` ghi lại `text_field`; `submit.py` đọc lại giá trị đó nên không cần nhắc hai lần.

### Các điểm đổi nhanh

| Muốn đổi | Sửa ở đâu | Chạy lại từ |
| --- | --- | --- |
| Cách đọc một dòng corpus mới | `schema.document_text` | chunk |
| Kích thước và overlap chunk | cờ của `chunk.py` | chunk → index → retrieve → submit |
| Model embedding | cờ `--encoder`; thêm model vào `ENCODERS` trong `embedding.py` | index dense → retrieve → submit |
| Model reranker | cờ `--reranker`; thêm vào `RERANKERS` trong `rerank.py` | retrieve → submit |
| Trọng số kênh RRF | cờ `--weights` | retrieve → submit |
| Số tài liệu/đoạn trả về | cờ `--profile` hoặc `--chunk-*`, `--doc-*` | submit (không cần retrieve lại) |
| Định dạng bài nộp | `schema.submission_row`, `export.py` | submit |

Bảng này khớp với bảng "đổi gì thì chạy lại gì" của pipeline.txt. `retrieve.py` ghi sẵn điểm của 50 ứng viên mỗi truy vấn, nên chỉnh ngưỡng ở Block D chỉ cần chạy lại `submit.py`.

### Cơ chế chống lệch giữa các khâu

- `bm25_manifest.json` và `dense_manifest.json` ghi SHA-256 của `chunks.parquet`. `retrieve.py` từ chối chạy nếu chunk đã đổi sau khi lập chỉ mục, vì dòng thứ i sẽ trỏ sai chunk.
- Mọi file ghi ra đều qua `atomic_write_bytes` (ghi file tạm rồi đổi tên), nên chạy đứt giữa chừng không để lại file dở.
- Mỗi khâu ghi một `*_manifest.json` gồm tham số đã dùng, số lượng và hash file đầu ra.

## 2a. Block A2→A3 — tiền xử lý dữ liệu crawl

**Lệnh:** `scripts/prepare.py` → [corpus/prepare.py](../../src/vibiomir/corpus/prepare.py)

| | |
| --- | --- |
| Nhận | Một hoặc nhiều nguồn (`--source`): thư mục run có `records/<id>.json`, hoặc file `.parquet` / `.json` / `.jsonl` xuất từ crawler. Nguồn đứng trước thắng khi trùng `id` |
| Trả | `work/corpus/corpus.parquet` với schema cố định (`id`, `url`, `final_url`, `domain`, `title`, `text`, `lang`, `status`, `quality_status`, `quality_flags`, `published_at`, `extractor`, `char_count`, `text_sha256`, `raw_path`, `raw_sha256`, `duplicate_doc_ids`, `source`), `dropped.jsonl`, `prepare_manifest.json` |

| Tham số | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--limit` | không | Đọc tối đa N hàng nguồn, ID nhỏ trước |
| `--max-duplicates` | 20 | Nhiều ID hơn mức này cùng một văn bản thì coi là trang mẫu và loại |
| `--min-chars` | 0 | Loại tài liệu ngắn hơn; mặc định giữ mọi tài liệu có chữ |
| `--drop-review` | tắt | Loại cả bài crawler đánh dấu `review` |
| `--text-field` | tự nhận | Cột chứa thân bài |

Lý do loại: `fetch_failed`, `empty_text`, `homepage_redirect` (URL bị chuyển về trang chủ nên văn bản là trang chủ chứ không phải bài), `template_text`, `quality_rejected`. Trong batch crawl đầu có 2.236 bản ghi chuyển về trang chủ, 2.230 cái chung văn bản "Trang chủ"; nếu để lại chúng sẽ khớp nhiều truy vấn và chiếm chỗ bài thật. Văn bản trùng ở nhóm nhỏ được giữ đủ mọi ID và ghi vào `duplicate_doc_ids`, vì ID nào cũng có thể là nhãn.

**Ý nghĩa với hệ thống.** Đây là chỗ duy nhất hiểu các định dạng crawler khác nhau. Mọi khâu sau chỉ đọc `corpus.parquet`, nên đổi crawler chỉ cần sửa một module.

## 3. Block A4 — chunking

**Lệnh:** `scripts/chunk.py` → [corpus/chunk.py](../../src/vibiomir/corpus/chunk.py)

| | |
| --- | --- |
| Nhận | Một hoặc nhiều file corpus (`--corpus`, `.parquet` / `.json` / `.jsonl`); cần ít nhất cột `id` và một cột văn bản |
| Trả | `chunks.parquet` (cột `chunk_id`, `doc_id`, `chunk_order`, `char_start`, `char_end`, `text`, `title`, `lang`, `n_tokens`, `domain`) và `chunk_manifest.json` |

| Tham số | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--target-tokens` | 320 | Cỡ cửa sổ mong muốn |
| `--overlap-tokens` | 64 | Phần gối giữa hai cửa sổ liền nhau (phải nhỏ hơn target) |
| `--max-tokens` | 1024 | Trần cứng, theo khuyến nghị của BTC |
| `--min-tokens` | 24 | Cửa sổ cuối nhỏ hơn mức này được nối vào cửa sổ trước |
| `--text-field` | tự nhận | Cột chứa thân bài |
| `--status` | `ok` | Chỉ giữ hàng có `status` bằng giá trị này (khi cột tồn tại) |

**Kỹ thuật**
- Tách theo ranh giới đoạn (dòng trống), gộp các đoạn thành cửa sổ có overlap. Đoạn dài hơn trần được tách tiếp theo câu (dấu `. ! ? …` và dấu câu CJK `。！？；`); nếu vẫn dài thì cắt theo số ký tự, không bỏ nội dung.
- Token hóa theo cách dùng chung của hệ thống (xem mục 8): từ Latin/số là một token, mỗi ký tự CJK là một token.
- Tiêu đề **không** được ghép vào `text`, chỉ lưu riêng và dùng khi lập chỉ mục (`retrieval_text`). Nếu ghép, chunk không còn là đoạn trích nguyên văn.
- Nhiều shard crawl có thể trùng `id`; giữ bản đầu tiên.

**Ý nghĩa với hệ thống.** Một chunk của đội nộp đúng khi LCS-token với một đoạn tham chiếu đạt 40% độ dài đoạn tham chiếu. Chunk quá nhỏ không phủ nổi 40%; chunk quá lớn kéo Precision xuống. Kích thước thật của đoạn tham chiếu **không được biết**, nên các tham số này cần tinh chỉnh khi có tín hiệu đánh giá.

## 4. Block B — lập chỉ mục

**Lệnh:** `scripts/index.py {bm25|dense|all}` → [index/build.py](../../src/vibiomir/index/build.py)

| | |
| --- | --- |
| Nhận | `chunks.parquet` |
| Trả | `bm25.npz`; `embeddings.npy` (float16, memmap), `doc_ids.npy`, `chunk_ids.jsonl`, tùy chọn `faiss.index`; các manifest |

### B2 — BM25 ([bm25.py](../../src/vibiomir/index/bm25.py))

| Tham số | Mặc định |
| --- | --- |
| `--k1` | 1.5 |
| `--b` | 0.75 |

- Danh sách đảo lưu trong mảng numpy phẳng; chấm điểm chỉ chạm vào danh sách của các từ trong truy vấn.
- Idf âm hoặc bằng 0 được thay bằng 0,25 lần idf trung bình, theo cách làm của notebook tham khảo.
- Token hóa: chuẩn hóa theo dạng so khớp của evaluator (NFKC, giải mã HTML entity, chữ thường), từ Latin/số tách theo từ, **chữ CJK tách thành unigram cộng bigram** (không cần bộ tách từ). Nếu tách theo khoảng trắng, cả câu tiếng Trung sẽ thành một từ và chỉ mục vô dụng.
- Truy vấn tiếng Việt không với tới tài liệu Trung qua BM25. Việc đó thuộc về kênh dense hoặc truy vấn đã dịch.

### B3 — embedding ([embedding.py](../../src/vibiomir/index/embedding.py))

| Tham số | Mặc định |
| --- | --- |
| `--encoder` | `bge-m3` |
| `--batch-size` | 16 |
| `--shard` | 20000 |
| `--device` | cuda nếu có |
| `--fp32` | tắt (mặc định fp16 trên GPU) |
| `--faiss`, `--faiss-lists` | tắt, 4096 |

Các encoder đã đăng ký (đều là model mở; mốc phát hành và số tham số cần tự đối chiếu lại trước khi nộp):

| Tên | Model | Tham số | Pooling | Ghi chú |
| --- | --- | --- | --- | --- |
| `bge-m3` (mặc định) | BAAI/bge-m3 | 568M | CLS | Đa ngôn ngữ, vừa GPU 4GB |
| `multilingual-e5-large` | intfloat/multilingual-e5-large | 560M | mean | Cần tiền tố `query: ` / `passage: ` |
| `gte-multilingual-base` | Alibaba-NLP/gte-multilingual-base | 305M | CLS | Rẻ nhất |
| `qwen3-embedding-0.6b` | Qwen/Qwen3-Embedding-0.6B | 0.6B | token cuối | Phát hành 06/2025, có chỉ dẫn cho truy vấn |
| `qwen3-embedding-4b` | Qwen/Qwen3-Embedding-4B | 4B | token cuối | Cần GPU 16GB |
| `hash` | không phải model | — | — | Chỉ để chạy thử offline |

**Kỹ thuật:** mã hóa theo shard thẳng vào một file `.npy` float16, nên RAM chỉ giữ một shard. Tự giảm một nửa batch khi hết bộ nhớ GPU. Véc-tơ chuẩn hóa L2 nên tích vô hướng là cosine. Tìm kiếm đọc ma trận theo khối và giữ top-k chạy, nên corpus lớn hơn RAM vẫn tìm được; `faiss` chỉ là bộ tăng tốc tùy chọn.

**Ý nghĩa với hệ thống.** Bài toán là truy hồi xuyên ngôn ngữ (truy vấn Việt, tài liệu Việt/Trung/Anh). BM25 chỉ bắt được trùng từ, nên kênh dense mang phần lớn khả năng khớp xuyên ngôn ngữ.

## 5. Block C — truy xuất

**Lệnh:** `scripts/retrieve.py` → [retrieval/run.py](../../src/vibiomir/retrieval/run.py)

| | |
| --- | --- |
| Nhận | `chunks.parquet`, thư mục index, `query.parquet` (`id`, `query`) |
| Trả | `candidates.jsonl`: mỗi truy vấn có `candidates` (chunk, `rrf_score`, `ce_score`, các kênh đã tìm ra nó) và `documents` đã xếp hạng; `retrieval_manifest.json` |

| Tham số | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--top-k` | 200 | Mỗi kênh lấy bao nhiêu trước khi trộn |
| `--fuse-k` | 200 | Giữ lại sau RRF |
| `--rerank-k` | 100 | Số ứng viên đưa vào cross-encoder |
| `--keep` | 50 | Số ứng viên ghi ra mỗi truy vấn |
| `--doc-chunks` | 3 | Số chunk tốt nhất cộng vào điểm của một tài liệu |
| `--encoder` | theo index | Phải là encoder đã dùng khi lập chỉ mục |
| `--reranker` | `bge-reranker-v2-m3` | |
| `--weights` | rỗng | JSON trọng số RRF theo kênh hoặc họ, ví dụ `{"bm25":0.7}` |
| `--keyword-variant` | tắt | Thêm biến thể truy vấn đã bỏ lời chào/xã giao cho BM25 |
| `--translations` | không | File JSONL bản dịch truy vấn chuẩn bị sẵn |
| `--no-bm25`, `--no-dense` | tắt | Tắt từng kênh (không được tắt cả hai) |
| `--batch-size`, `--rerank-batch` | 16, 16 | |

### C1 — chuẩn bị truy vấn ([query.py](../../src/vibiomir/retrieval/query.py))
- Luôn giữ truy vấn gốc làm biến thể đầu tiên; mã hóa dense hoạt động tốt nhất trên câu nguyên văn.
- Biến thể `keyword` chỉ bỏ cụm xã giao ("cho em hỏi", "xin cảm ơn"...), dành cho BM25.
- Dịch truy vấn sang Trung/Anh là hook đọc từ file chuẩn bị sẵn, **không tự sinh**, vì cần một model dịch hợp lệ theo luật.
- Kiểm tra: không có truy vấn rỗng, không trùng `id`.

### C2 — truy xuất lai và RRF ([hybrid.py](../../src/vibiomir/retrieval/hybrid.py))
- Mỗi cặp (biến thể truy vấn, chỉ mục) là một kênh: `bm25:original`, `dense:original`, ...
- Trộn bằng **Reciprocal Rank Fusion** với hằng số 60: điểm = Σ trọng số / (60 + hạng + 1). Trộn theo hạng nên không phải đưa điểm BM25 và cosine về cùng thang.
- Điểm tài liệu = tổng điểm của vài chunk tốt nhất của nó, thay vì lấy chunk cao nhất, vì nhiều chunk cùng xếp cao đáng tin hơn một chunk may mắn. Điểm của chunk là **xác suất của reranker** khi reranker đã chạy, chỉ lùi về điểm RRF khi không có.
- Mã hóa mọi biến thể của mọi truy vấn trong một lượt và tìm một lần, tránh đọc lại ma trận 1.200 lần.

### C3 — rerank ([rerank.py](../../src/vibiomir/retrieval/rerank.py))

| Tên | Model | Tham số | Cách chấm |
| --- | --- | --- | --- |
| `bge-reranker-v2-m3` (mặc định) | BAAI/bge-reranker-v2-m3 | 568M | Đầu phân loại trên cặp (truy vấn, đoạn) |
| `bge-reranker-base` | BAAI/bge-reranker-base | 278M | Như trên, yếu hơn với tiếng Trung |
| `qwen3-reranker-0.6b` / `-4b` | Qwen/Qwen3-Reranker | 0.6B / 4B | Xác suất của token `yes` so với `no` trong prompt riêng |
| `identity` | không phải model | — | Giữ nguyên thứ tự trộn |

Mọi reranker trả **xác suất trong [0, 1]** (sigmoid của logit, hoặc softmax yes/no), nên điểm mang cùng nghĩa giữa các model và ngưỡng tỷ lệ ở Block D có ý nghĩa. Tự giảm batch khi hết bộ nhớ. Hàm `adaptive_cutoff` tìm chỗ điểm rerank tụt mạnh nhất để cắt danh sách, theo ý tưởng adaptive-k của Taguchi và cộng sự (2025).

**Ý nghĩa với hệ thống.** Trộn quyết định vài trăm ứng viên nào đáng xem; cross-encoder đọc cả truy vấn lẫn đoạn nên phán đoán mức liên quan tốt hơn từng kênh riêng lẻ.

## 6. Block D — bài nộp

**Lệnh:** `scripts/submit.py` → [submission/build.py](../../src/vibiomir/submission/build.py)

| | |
| --- | --- |
| Nhận | `candidates.jsonl`, `chunks.parquet`, **chính các file corpus đã dùng khi chunk** (`--corpus`), `query.parquet`, tùy chọn `links_corpus.parquet` |
| Trả | `submission.json`, `submission.zip` (một file ở gốc, không có thư mục con), `submission_manifest.json` |

### D1 — chọn tài liệu và đoạn ([choose.py](../../src/vibiomir/submission/choose.py))

Với g tài liệu đúng, N tài liệu trả về, k trong đó đúng: `F2 = 5k / (4g + N)`. Thêm một tài liệu chỉ có lợi khi xác suất nó đúng lớn hơn `k / (4g + N)`, tức cỡ 0,1 đến 0,2 ở quy mô thực tế. Vì vậy mặc định trả khá rộng.

| Profile | Tài liệu (min–max, ngưỡng tỷ lệ) | Đoạn (min–max, ngưỡng tỷ lệ) | Đoạn tối đa mỗi tài liệu |
| --- | --- | --- | --- |
| `recall` | 5–25, 0,25 | 5–30, 0,25 | 2 |
| `balanced` (mặc định) | 3–15, 0,45 | 3–15, 0,45 | 2 |
| `precision` | 1–7, 0,65 | 1–7, 0,65 | 1 |

Ngưỡng tỷ lệ: giữ ứng viên có điểm ít nhất bằng tỷ lệ đó so với điểm cao nhất của truy vấn, nhưng luôn giữ đủ mức tối thiểu. Các cờ khác: `--adaptive` (cắt đoạn tại chỗ tụt điểm lớn nhất), `--no-sync-docs` (không tự thêm tài liệu của đoạn đã chọn vào `relevant_docs`), `--doc-id-as-string`, và các cờ ghi đè `--doc-min`, `--doc-max`, `--doc-ratio`, `--chunk-min`, `--chunk-max`, `--chunk-ratio`, `--chunk-per-doc`.

Giới hạn số đoạn mỗi tài liệu vì các cửa sổ chồng nhau của cùng một tài liệu thường khớp cùng một đoạn tham chiếu: chúng không thêm Recall nhưng mỗi cái đều tốn Precision.

### D2 — kiểm chứng ([validate.py](../../src/vibiomir/submission/validate.py))
- Cắt lại từng chunk từ corpus bằng `char_start`/`char_end` và so với bản đã lập chỉ mục. **Lệch là lỗi cứng, dừng chạy**, vì nghĩa là corpus hoặc chunk đã đổi sau khi lập chỉ mục.
- Kiểm tra chunk thuộc đúng tài liệu, tài liệu có trong corpus và (nếu truyền `--links`) có trong `links_corpus.parquet`, mọi truy vấn đều có dòng (danh sách rỗng khi không có kết quả), không có truy vấn lạ hay trùng.
- Cảnh báo chunk vượt 1024 token.

### D3 — xuất ([export.py](../../src/vibiomir/submission/export.py))
Ghi JSON, nén ZIP với mốc thời gian cố định (cùng kết quả cho cùng byte), rồi mở lại để kiểm tra đúng một file ở gốc và nội dung khớp.

## 7. Block E — đánh giá

**Lệnh:** `scripts/evaluate.py {sheet|collect|pseudo|score}` → [evaluation/run.py](../../src/vibiomir/evaluation/run.py)

| Lệnh con | Nhận | Trả |
| --- | --- | --- |
| `sheet` | `candidates.jsonl`, `chunks.parquet` | `label_sheet.jsonl` và `label_sheet.html` để người gán nhãn (không ghi đè phiếu đã có) |
| `collect` | phiếu đã điền | `labels.jsonl` (`source: human`); truy vấn chưa đánh dấu bị bỏ, không đoán |
| `pseudo` | `candidates.jsonl`, `chunks.parquet` | `labels.jsonl` (`source: pseudo`), **vòng tròn**, báo cáo tự in cảnh báo |
| `score` | `submission.json`, `labels.jsonl`, `candidates.jsonl`, corpus | `metrics.json`, `per_query.jsonl`, `loss_cases.jsonl`, `EVAL_REPORT.md` |

### Metric ([metrics.py](../../src/vibiomir/evaluation/metrics.py))
Cài đặt đúng công thức đã công bố: Precision, Recall, F2 hai cấp (tài liệu, đoạn), trung bình theo truy vấn. Chunk đúng khi `LCS_token(c, g) / |g| ≥ 0,40` với một đoạn tham chiếu cùng truy vấn và cùng `doc_id`.

LCS dùng thuật toán bit-parallel (Crochemore và cộng sự, 2001), một từ máy cho mỗi 64 token. Đã kiểm khớp quy hoạch động thường trên nhiều ca ngẫu nhiên, và test giữ lại phép so sánh đó. Có bước loại sớm: nếu các token chung không thể đạt ngưỡng thì bỏ qua LCS.

Hai điểm luật không nói rõ, đã chọn và ghi trong code:
1. Cách tách token để tính LCS không được công bố. Giả định: từ Latin/số là một token, mỗi ký tự CJK là một token.
2. Truy vấn không có tham chiếu nào bị loại khỏi trung bình và đếm riêng.

### Quy lỗi về block ([errors.py](../../src/vibiomir/evaluation/errors.py))
Mỗi tài liệu tham chiếu bị mất được xếp vào đúng một nguyên nhân:

| Nguyên nhân | Block chịu trách nhiệm | Hướng xử lý |
| --- | --- | --- |
| `not_crawled` | A | Mở rộng độ phủ crawl; đổi retrieval không lấy lại được |
| `not_retrieved` | B/C | Encoder, số kênh, `top_k` |
| `not_selected` | D1 | Nới ngưỡng chọn, thay đổi rẻ nhất |
| `chunk_too_narrow` | A4 | Kích thước hoặc overlap của chunk |

Báo cáo đếm thêm số tài liệu nộp sai, vì F2 vẫn phải trả giá cho Precision.

## 8. Dùng chung ([common/](../../src/vibiomir/common))

| File | Vai trò |
| --- | --- |
| `schema.py` | Định dạng bản ghi giữa các khâu; `document_text` (đọc một dòng corpus); `normalise_source` (NFC, giữ hoa/thường, dấu, số, xuống dòng) và `normalise_for_match` (NFKC, giải mã entity, chữ thường, gộp khoảng trắng, đúng bước chuẩn hóa của evaluator); `tokenize_for_match`; `detect_language`; `submission_row` và `validate_submission_shape` |
| `storage.py` | Đọc/ghi JSON, JSONL, Parquet (kiểm tra đọc lại khớp), `read_rows` (parquet, json hoặc jsonl), ghi nguyên tử, SHA-256, `write_manifest` |
| `console.py` | `emit()`: in không chết khi console không mã hóa được tiếng Việt (console Windows mặc định cp1252) |

Phân biệt hai dạng chuẩn hóa: dạng lưu giữ nguyên văn bản gần nguồn (vì chunk phải là đoạn trích), còn dạng so khớp chỉ dùng khi so sánh và không bao giờ được ghi vào corpus. `detect_language` chỉ dựa trên chữ viết, không phải bộ phân loại ngôn ngữ đã hiệu chuẩn; nhãn `en` thực chất là "Latin, không phải tiếng Việt".

## 9. Môi trường

`requirements/rag.txt`: `numpy`, `pyarrow`, `torch`, `transformers`, `tokenizers`, `safetensors`, `sentencepiece`, `protobuf`; `faiss-cpu` là tùy chọn. Chunking, BM25 và dựng bài nộp chạy không cần torch. Cài `torch` theo bản CUDA của máy từ trang pytorch.org. Máy dev hiện có RTX 2050 4GB, đủ cho `bge-m3` và `bge-reranker-v2-m3` ở fp16 nhưng không đủ cho các bản 4B.

## 10. Chưa kiểm chứng và giới hạn đã biết

- **Chưa chạy model thật.** Pooling, `max_length`, tiền tố và VRAM của bge-m3 chưa được thử. Có thể lộ lỗi ở lần chạy thật đầu tiên.
- **Quy mô.** `retrieve.py` nạp cả bảng chunk vào RAM (ước chừng 1KB mỗi chunk). Vài triệu chunk sẽ không vừa máy 16GB; cần chia shard corpus rồi gộp file ứng viên, hoặc đọc theo cột.
- **Không có nhãn.** Mọi tham số mặc định (cỡ chunk, trọng số RRF, profile) chưa được tối ưu trên dữ liệu thật. Leaderboard là tín hiệu thật duy nhất nhưng bị giới hạn lượt nộp.
- **Xuyên ngôn ngữ chỉ dựa vào dense.** Chưa có dịch truy vấn; hook đã có nhưng cần model dịch hợp lệ.
- **Token của LCS là giả định** (mục 7). Nếu BTC dùng cách khác, ngưỡng 40% có thể lệch, nhất là với tiếng Trung.
- **Luật model.** Danh sách model là gợi ý đã soạn từ kiến thức sẵn có và tìm kiếm; ngày phát hành và số tham số cần tự đối chiếu lại trước khi nộp, vì đây là điều BTC sẽ kiểm.
- **Giả định về `status`.** Bộ lọc `--status ok` ở `chunk.py` dựa trên định dạng mà `prepare.py` ghi ra; dữ liệu đi qua `prepare.py` luôn có `status = ok`.
- **Corpus mẫu chỉ có tiếng Việt.** 30.000 bản ghi đã chạy đều tiếng Việt từ 4 domain, nên phần xuyên ngôn ngữ chưa được thử trên dữ liệu thật.

### Lỗi đã tìm và sửa khi chạy trên dữ liệu thật (05/10/2026)

| Lỗi | Hậu quả | Sửa |
| --- | --- | --- |
| Encoder `hash` dùng `hash()` của Python, đổi theo từng tiến trình | Index và truy vấn mã hóa ở hai lệnh khác nhau ra véc-tơ không khớp; kênh dense vô nghĩa khi chạy qua CLI | Dùng `crc32`; có test chạy ba tiến trình |
| Điểm reranker là logit thô, có thể âm | Ngưỡng tỷ lệ ở Block D vô nghĩa với reranker thật | Đổi thành xác suất 0–1 |
| Xếp hạng tài liệu chỉ theo RRF | Bỏ qua reranker ở cấp tài liệu | Dùng xác suất reranker khi có |
| faiss trả `-1` khi thiếu kết quả | Dùng `-1` làm chỉ số, lấy nhầm chunk cuối | Lọc bỏ |
| `--encoder` ở bước truy xuất khác bước lập chỉ mục không bị chặn | Truy vấn và tài liệu ở hai không gian véc-tơ | Báo lỗi |
| Pooling token cuối với padding bên trái lấy theo `mask.sum - 1` | Lấy nhầm vị trí padding với `qwen3-embedding-*` | Lấy vị trí cuối |
| Tham số `dtype=` không có ở bản `transformers` cũ | Lặng lẽ nạp fp32, gấp đôi VRAM | Dùng `torch_dtype=` |
| `--keep` lớn hơn `--rerank-k` | Trộn điểm xác suất với điểm RRF khi chọn | Chặn ở CLI |

## 11. Lệnh chạy

```powershell
python -m pip install -r requirements/rag.txt

python scripts/prepare.py --source nguyen/output/runs/batch01_nguyen --limit 30000
python scripts/chunk.py
python scripts/index.py all --encoder bge-m3
python scripts/retrieve.py --keyword-variant
python scripts/submit.py --links data/links_corpus.parquet --profile recall

python scripts/evaluate.py sheet   # xuất phiếu gán nhãn
python scripts/evaluate.py collect # phiếu đã điền -> labels.jsonl
python scripts/evaluate.py score
```

Mọi đường dẫn mặc định đều trỏ vào `work/`. Chạy thử không cần model: thêm `--encoder hash` cho `index.py` và `--reranker identity` cho `retrieve.py`. Chi tiết từng bước, thời gian đo được và cách xử lý sự cố: [run_guide.md](run_guide.md).

### C4 — term và độ liên quan: lý thuyết đã dùng, phần còn thiếu

- **Đã dùng:** BM25 ước lượng khớp term bằng tần suất term (TF), độ hiếm trong corpus (IDF) và chuẩn hóa độ dài; embedding dùng cosine cho khớp ngữ nghĩa; RRF hợp nhất thứ hạng; cross-encoder chấm trực tiếp cặp truy vấn--đoạn. Đây là tín hiệu xếp hạng, không phải xác nhận đoạn đúng.
- **Chưa dùng:** chưa có bước chọn term phản hồi dựa trên nhãn liên quan. Biến thể keyword hiện chỉ bỏ lời xã giao; vòng feedback chưa triển khai. Không nên mặc định mọi term từ top-k đều hữu ích.
- **Khi thử feedback:** giữ truy vấn gốc; chỉ bổ sung term/facet được nhiều ứng viên độc lập hỗ trợ, ưu tiên term đặc trưng hơn term phổ biến; hợp nhất danh sách rồi rerank một lần. Ghi term được thêm cùng nguồn ứng viên để truy vết.
- **Đánh giá:** xác định liên quan bằng nhãn tài liệu/?oạn trên dev và Recall@K, MRR/nDCG cùng metric F2 chính thức. Điểm BM25, cosine, RRF hay reranker dùng để xếp hạng, không thay nhãn đúng/sai.
