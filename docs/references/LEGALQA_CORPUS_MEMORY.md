# Bộ nhớ dự án: cách xây dựng corpus LegalQA

> Mục đích: giúp Codex hiểu corpus của UIT DSC 2026 Task 2 LegalQA, tìm đúng code và tái sử dụng cách tổ chức dữ liệu khi xây dựng một corpus RAG khác.
>
> Vị trí đề xuất trong GitHub: `docs/LEGALQA_CORPUS_MEMORY.md`.
> Ngày đối chiếu: 03/10/2026.
> Repo tham chiếu: https://github.com/lighth-gh/uit-dsc-2026-task2-legalqa
> Commit đã đọc: `05806a7dd613bf5a2e96e413ddd0e8e7411b5d49`.
>
> Các mục 1–10 mô tả dữ liệu và implementation đã đối chiếu. Mục 11 là cách vận dụng, không phải khẳng định pipeline mới đã được triển khai.

## 1. Kết luận cần nhớ trước tiên

Corpus retrieval của LegalQA bắt đầu từ **văn bản nguồn do BTC cung cấp trong `selected-contexts.zip`**. Dự án đọc, chuẩn hóa, loại rỗng/trùng, chia parent–child và lập chỉ mục; không lấy đáp án trong `train.json` làm văn bản pháp luật nguồn.

Luồng xây dựng:

```text
selected-contexts.zip
→ đọc các context JSON
→ chuẩn hóa passage
→ kiểm tra ID, bỏ passage rỗng và passage trùng hoàn toàn
→ tách parent theo Điều
→ chia child theo tokenizer embedding
→ lưu parent/child vào SQLite + FTS5
→ encode child bằng E5
→ tạo dense.faiss và manifest
```

Luồng sử dụng: câu hỏi → tìm child bằng lexical/dense retrieval → hợp nhất và rerank → lấy lại parent tương ứng → đóng context cho generator.

**Đơn vị tìm kiếm là child; đơn vị cung cấp bằng chứng thường là parent hoặc cửa sổ nguyên văn trong parent.** Tài liệu nguồn, parent, child, index và context đưa vào prompt là các lớp khác nhau.

## 2. Phân biệt các loại dữ liệu

| Thành phần | Vai trò | Ghi nhớ |
| --- | --- | --- |
| `selected-contexts.zip` | Corpus tài liệu nguồn để retrieval | Là đầu vào của `build-index` |
| `train.json` | Cặp câu hỏi–đáp án có nhãn | Dùng chia train/dev/holdout, SFT và đánh giá nội bộ |
| `public-official.json` | Câu hỏi public test | Không có reference để tự tính METEOR |
| `private-official.json` | Câu hỏi private test | Đổi tập câu hỏi không tự làm thay đổi corpus |
| `corpus.sqlite` | Parent, child và chỉ mục lexical | Là artifact sinh từ corpus, không phải dữ liệu raw |
| `dense.faiss` | Vector index của các child | Phải khớp SQLite và model embedding |
| `*.retrieval.json` | Kết quả retrieval theo từng câu hỏi | Là cache của một lần chạy, không phải corpus gốc |
| `submission.json` | Đáp án dự đoán | Không nhập ngược vào corpus hoặc làm nhãn chuẩn |

Không dùng reference của dev/holdout/public/private để chọn context cho chính câu hỏi đang đánh giá. Retriever nhận câu hỏi; đáp án chuẩn phục vụ huấn luyện hoặc đo chất lượng theo split thích hợp.

## 3. Corpus gốc có hình thức gì?

### 3.1. Cách đóng gói

Trong ZIP có các file dạng `selected-contexts/context_<id>.json`. Loader đọc trực tiếp ZIP, không bắt buộc giải nén. Nếu đầu vào là thư mục, loader tìm đệ quy `context_*.json`, nên dùng được với thư mục lồng như `selected-contexts/selected-contexts`.

Khác biệt implementation cần biết:

- Nhánh ZIP đọc các entry `.json`, bỏ entry bắt đầu bằng `__MACOSX/`.
- Nhánh thư mục chỉ tìm `context_*.json`.
- Mỗi file được hiểu là **một document JSON object**, không phải JSONL hoặc danh sách document.

### 3.2. Schema nguồn

Ví dụ minh họa cấu trúc; các giá trị trong dấu `<...>` là placeholder:

```json
{
  "id": 123456,
  "name": "<tên văn bản nếu nguồn có cung cấp>",
  "link": "<URL nguồn>",
  "passage": "<toàn bộ nội dung văn bản đã trích xuất>"
}
```

| Field | Yêu cầu của parser | Xử lý |
| --- | --- | --- |
| `id` | Bắt buộc tồn tại | Chuyển thành chuỗi `doc_id` |
| `passage` | Bắt buộc; chuỗi hoặc `null` | Chuẩn hóa thành `text`; `null` thành chuỗi rỗng |
| `name` | Có thể thiếu hoặc rỗng | Mặc định `""`; không tự suy diễn tên |
| `link` | Có thể thiếu hoặc rỗng | Mặc định `""`; giữ URL nếu có |
| `source_file` | Loader bổ sung | Lưu đường dẫn entry ZIP hoặc đường dẫn tương đối trong thư mục |

Schema không hợp lệ phải báo lỗi. Không tự đoán schema khác và bỏ qua lỗi âm thầm.

Một file thực tế đã kiểm tra là `selected-contexts/context_100050.json`: có `link`, `passage`, `id`, không có `name`; URL nguồn thuộc `thuvienphapluat.vn` và trỏ tới một tiêu chuẩn bảo vệ thực vật. Vì vậy, **không giả định mọi document đều có tên hoặc đều là luật có cấu trúc Điều**.

### 3.3. Giới hạn thông tin về nguồn hình thành

Repo cho biết đầu vào là corpus BTC và giữ URL nguồn của từng document. Repo này không đủ bằng chứng để mô tả crawler gốc của BTC, lịch crawl, selector HTML, cách OCR hoặc quy trình biên tập trước khi phát hành ZIP.

Không ghi rằng nhóm đã tự crawl corpus LegalQA hoặc BTC dùng Selenium nếu chưa có tài liệu xác nhận. Phần có thể tái lập từ repo là **xử lý sau khi nhận corpus**.

## 4. Chuẩn hóa và kiểm tra document

Code chính: `legalqa/data.py::_parse_document`, `legalqa/retrieval.py::build_index`.

Thứ tự xử lý hiện tại:

1. Đọc JSON UTF-8, chấp nhận BOM qua `utf-8-sig`.
2. Chuẩn hóa Unicode về NFC.
3. Thay ký tự `\r` bằng `\n`.
4. Gộp chuỗi dấu cách/tab thành một dấu cách.
5. Thu gọn chuỗi nhiều dòng trống và `strip()` hai đầu.
6. Kiểm tra trùng `doc_id`: nếu gặp lại ID thì dừng với lỗi, kể cả nội dung khác.
7. Bỏ document có `text` rỗng, tăng `empty_documents`.
8. Tính hash của `text` đã chuẩn hóa; bỏ passage trùng hoàn toàn, tăng `duplicate_passages`.
9. Giữ bản passage đầu tiên trong thứ tự duyệt nguồn đã sắp xếp.

Lưu ý về khử trùng:

- Đây là **exact dedup sau chuẩn hóa**, không phải phát hiện mọi cặp gần trùng.
- Khi hai ID khác nhau có passage giống hệt, chỉ bản đầu được đưa vào index. SQLite hiện tại không lưu danh sách tất cả URL của các bản trùng.
- Không xóa dấu tiếng Việt, không viết lại điều kiện pháp lý, không tóm tắt bằng LLM trong bước này.
- Không áp dụng stemming hay word segmentation tiếng Việt cho passage ở loader.

Số hiệu văn bản được tìm từ dòng `Số: ...` trong 6.000 ký tự đầu, bằng regex của `document_number()`. Không có kết quả thì để rỗng. **ID trang web và đuôi URL không phải số hiệu luật/nghị định/quyết định.**

## 5. Chia parent–child đúng theo implementation

### 5.1. Parent

Code: `legalqa/data.py::legal_parents`.

- Tìm dòng bắt đầu bằng `Điều <số>...` theo regex `ARTICLE`.
- Các vị trí bắt đầu parent gồm đầu văn bản, đầu mỗi Điều và cuối văn bản.
- Một Điều kéo dài đến trước Điều tiếp theo.
- Phần mở đầu trước Điều đầu tiên cũng có thể thành một parent.
- Văn bản không khớp regex Điều được giữ thành một parent toàn văn, rồi vẫn chia child.
- Bỏ segment rỗng; không bỏ tài liệu chỉ vì không có Điều.
- `parent_id` có dạng `<doc_id>:<ordinal>`; ordinal là vị trí segment, **không phải số Điều**.

Parent lưu: `parent_id`, `doc_id`, `heading`, `number`, `text`, `source_file`, `link`.

Implementation hiện tại không có parser riêng cho Chương, khoản, điểm, bảng hoặc Phụ lục. Không mô tả nó như một bộ phân tích đầy đủ cấu trúc pháp luật. Ranh giới khoản/điểm chưa được dùng để chia child.

### 5.2. Child

Code: `legalqa/data.py::token_children`; cấu hình trong `config.json`.

| Tham số | Giá trị ở commit tham chiếu | Ý nghĩa |
| --- | --- | --- |
| `child_tokens` | 320 | Số token tối đa của thân child |
| `overlap_tokens` | 64 | Số token chồng lấn giữa hai child liền nhau |
| Bước cửa sổ | 256 | `320 - 64` |
| `header_tokens` | 48 | Giới hạn header số hiệu + heading |
| Tokenizer | `intfloat/multilingual-e5-small` | Token được đếm bằng tokenizer embedding, không phải số từ |

Tokenizer trả `offset_mapping` để cắt lại **chuỗi nguyên văn** trong parent. Child lưu `parent_id`, `start`, `end`, `header`, `text`.

- `start`/`end` là offset ký tự trong `parent.text`, không phải offset byte hoặc số token.
- Mỗi child nằm trong một parent; không nối cuối Điều này với đầu Điều khác.
- Overlap giúp nội dung ở mép cửa sổ có cơ hội xuất hiện đầy đủ trong cửa sổ bên cạnh.
- Child cuối ngắn hơn 320 token là bình thường.
- Header gồm số hiệu và heading nếu có, được token hóa rồi cắt tối đa 48 token; không tự thêm metadata chưa được xác thực.

Header và body có thể cùng chứa dòng tiêu đề Điều; đây là cách code hiện tại tạo input. Không nhầm `320 + 48` với số token cuối cùng của input encoder: còn có prefix, newline và special tokens.

## 6. Lập chỉ mục lexical và dense

Code: `legalqa/retrieval.py::build_index`, `legalqa/models.py::Encoder`.

### 6.1. SQLite/FTS5

| Bảng | Dữ liệu |
| --- | --- |
| `parents` | Metadata và text của parent |
| `chunks` | `chunk_id`, `parent_id`, offset, header, text của child |
| `search` | FTS5 trên hai cột `header`, `text` |

FTS5 dùng `unicode61 remove_diacritics 0`. `search.rowid` khớp `chunks.chunk_id`. Child ID là số nguyên tăng từ 0 trong quá trình build; thay nguồn/thứ tự/chunking có thể làm mapping ID thay đổi.

BM25 ưu tiên header với trọng số cột `2.5` và body `1.0`. Corpus không cần được viết lại thành danh sách câu hỏi để BM25 hoạt động.

### 6.2. Dense

- Model hiện tại: `intfloat/multilingual-e5-small`.
- Encode tài liệu bằng chuỗi `passage: <header>\n<text>`.
- Encode câu hỏi bằng prefix `query:`.
- Mean pooling theo attention mask, chuẩn hóa L2, lưu float32.
- Vector có 384 chiều; từ chối vector chứa NaN/Inf.
- Passage sau prefix và special tokens phải không quá 512 token; code kiểm tra và báo lỗi thay vì cắt lén.
- Tạo FAISS `IndexFlatIP(384)`; với vector chuẩn hóa L2, inner product tương ứng cosine similarity.
- Thứ tự vector được thêm vào FAISS trùng thứ tự `chunk_id` trong SQLite.

Không ghép `dense.faiss` của một corpus/chunking/tokenizer khác với `corpus.sqlite` hiện tại. Cùng số lượng vector chưa đủ chứng minh hai artifact khớp nhau.

### 6.3. Artifact và checkpoint

| File trong thư mục index | Vai trò |
| --- | --- |
| `corpus.sqlite` | Cơ sở dữ liệu parent/child/FTS5 |
| `corpus_manifest.json` | Thống kê corpus và identity sau khi xây SQLite |
| `vectors.npy` | Vector memmap, hỗ trợ build tiết kiệm RAM và resume |
| `embedding_progress.json` | Số vector đã lưu và hash manifest tương ứng |
| `dense.faiss` | Dense index hoàn chỉnh |
| `index_manifest.json` | Manifest hoàn tất, gồm hash SQLite/FAISS |

Identity lúc build gồm cấu hình chunking, khóa model embedding và `source_hash()` của các file Python trong `legalqa/`. Resume build phải khớp identity và corpus; index đã hoàn tất phải được reuse hoặc build vào thư mục mới.

`corpus_sha256` trong manifest là hash của danh sách document đã parse kèm đường dẫn nguồn. Nó **không phải** SHA-256 trực tiếp của file ZIP. Không so hai loại hash này với nhau.

Checkpoint embedding được flush và ghi tiến độ sau mỗi 20 batch, hoặc khi hoàn tất. Với `embedding_batch=32`, thông thường là mỗi 640 child. Không khẳng định bước parse/SQLite cũng resume từng document: nếu SQLite đang build chưa hoàn tất, code có thể xây lại phần đó.

## 7. Số liệu đã đối chiếu và cách hiểu các phiên bản

Các số dưới đây được tính trực tiếp từ ZIP và các file QA trong commit tham chiếu, dùng loader và quy tắc lọc của repo; riêng số child là số full index được README ghi nhận.

| Chỉ số | Giá trị | Nguồn |
| --- | --- | --- |
| Document đọc từ corpus | 8.532 | Đếm trực tiếp |
| Document rỗng | 20 | Đếm sau chuẩn hóa |
| Passage trùng bị loại | 5 | Exact hash sau chuẩn hóa |
| Document được giữ | 8.507 | Đếm trực tiếp |
| Parent sau chia Điều | 158.395 | Chạy `legal_parents` trên document được giữ |
| Child của full index Version 3 | 407.107 | README; chưa encode/build lại trong lần lập tài liệu này |
| Cặp QA trong `train.json` | 7.000 | Đếm trực tiếp |
| Câu hỏi public | 1.000 | Đếm trực tiếp |
| Câu hỏi private | 1.918 | Đếm trực tiếp |

SHA-256 file `selected-contexts.zip` đã đối chiếu:

```text
ebcfc896df06087e7da532b4653f32adfaba2200c8ed92a0069e46dbfa126a97
```

Log cũ của dự án từng ghi 240.911 chunks và model `AITeamVN/Vietnamese_Embedding_v2`. Đó là một phiên bản xử lý/index trước đây. Không dùng số chunk hoặc model cũ để mô tả index Version 3 ở đây; khi chạy thật, **manifest artifact được sử dụng là nguồn xác nhận chính**.

Không suy ra số văn bản raw từ số parent hoặc số child. Một document có thể tạo nhiều parent và mỗi parent có thể tạo nhiều child.

## 8. Corpus được sử dụng trong retrieval như thế nào?

Full retrieval tại cấu hình tham chiếu:

1. BM25 thường và dense lấy tối đa 100 child mỗi nhánh; các nhánh lexical chính xác/cụm từ dùng giới hạn cấu hình tương ứng, mặc định `precise_bm25_k=40`.
2. RRF hợp nhất thứ hạng với hằng số 60.
3. Pool mặc định 32 child; giới hạn tối đa 2 child mỗi parent để giảm các cửa sổ chồng lấn chiếm hết pool.
4. Reranker chấm cặp câu hỏi–child; mặc định batch 8 và tối đa 768 token.
5. Sau rerank/điều chỉnh điểm, lấy tối đa 4 parent khác nhau.
6. Parent quá lớn được materialize thành cửa sổ nguyên văn tối đa 24.000 ký tự quanh seed child; lưu offset cửa sổ và seed để truy vết.
7. Prompt packing tiếp tục áp dụng ngân sách token của generator; không phải tất cả parent raw được đưa nguyên vẹn vào prompt.

Các nhánh retrieval ablation hoặc recipe cụ thể có thể ghi đè cấu hình. Phải đọc config/manifest của lần chạy; không mặc định mọi Main 04 đều dùng các giá trị trên.

Lexical mode dùng cho cache SFT không chạy dense/reranker; vẫn tra cùng corpus. Cache retrieval không thay thế corpus và không chứng minh rằng câu trả lời được sinh ra đã đúng.

## 9. Cách build hoặc reuse trong repo

### 9.1. Build mới khi cần

Chạy từ thư mục gốc repo; các lệnh dưới dùng đường dẫn tương đối minh họa, cần sửa theo input thực tế.

```bash
python -m pip install -r requirements.txt
python -m legalqa fetch-models
python -m legalqa audit-models
python -m legalqa --models models --device cuda:0 build-index --corpus selected-contexts.zip --output runs/index
```

Đây là lệnh của CLI hiện tại, không phải script crawl. Cần model weights và tài nguyên phù hợp; `fetch-models` cần truy cập nguồn model. `build-index` qua CLI còn chạy kiểm định model trước khi build.

### 9.2. Ưu tiên reuse full index trên Kaggle

Dự án hiện dùng index/model build sẵn từ Dataset `lighth/ver3-smoke-output`. Đọc input ở `/kaggle/input/...`, ghi output mới ở `/kaggle/working/...`.

- Đổi public sang private, đổi model generator/adapter hoặc điều chỉnh decoding không tự yêu cầu encode lại corpus.
- Đổi corpus, tokenizer/model embedding hoặc cấu hình chunking yêu cầu index tương ứng mới.
- Đổi top-k/rerank/prompt có thể cần chạy lại cache retrieval/generation thích hợp, không tự động phải build corpus mới.
- Code identity có thể khiến cache/checkpoint cũ bị từ chối dù corpus chưa đổi. Khi đó kiểm tra quy trình reuse/migration của repo; không xóa guard hoặc sửa hash để ép artifact cũ được chấp nhận.
- Không ghi đè index hoàn tất hoặc trộn artifact giữa hai thư mục index.

### 9.3. Kiểm tra sau build hoặc trước reuse

- Manifest khai báo đúng corpus, chunking, model embedding và thống kê document/child.
- Hash SQLite và FAISS khớp manifest.
- Số vector FAISS khớp số child; vector index thứ `i` ánh xạ đúng `chunk_id=i`.
- Parent không rỗng; child không vượt ranh giới parent; offset trỏ đúng đoạn text.
- Số passage bị loại được ghi nhận, không mất tài liệu âm thầm.
- Smoke retrieval trả context có `doc_id`, `parent_id`, nguồn và nội dung liên quan.

Các kiểm tra này xác nhận pipeline dữ liệu; không đủ để tuyên bố chất lượng retrieval. Nếu có gold evidence, đo Recall@k/MRR; nếu chỉ có đáp án, dùng chẩn đoán liên quan và đánh giá end-to-end với giới hạn của nó.

## 10. Chỉ dẫn dành cho Codex

### 10.1. Đọc đúng file

| Nhu cầu | Nơi đọc trước |
| --- | --- |
| Schema, Unicode, đọc ZIP/thư mục | `legalqa/data.py`: `iter_documents`, `_parse_document` |
| Số hiệu văn bản và chia parent | `legalqa/data.py`: `document_number`, `legal_parents` |
| Chia child và offset | `legalqa/data.py`: `token_children` |
| Dedup, SQLite/FTS5, vector, manifest, resume | `legalqa/retrieval.py`: `build_index` |
| E5 prefix, pooling, giới hạn 512 token | `legalqa/models.py`: `Encoder` |
| Fusion, rerank, materialize parent | `legalqa/retrieval.py`: `Retriever` |
| Prompt và cắt cửa sổ context | `legalqa/prompts.py` |
| Giá trị cấu hình mặc định | `config.json` |
| Hash, khóa JSON, ghi file | `legalqa/io.py` |
| Test dữ liệu/chunking đang có | `tests/test_core.py` |
| Tổng quan vận hành và reuse | `README.md`, `PIPELINE.md`, `docs/retrieval_reuse.md` |

### 10.2. Quy tắc khi sửa

1. Đọc `AGENTS.md` và tài liệu này trước khi thay loader/chunking/index.
2. Đối chiếu code và manifest hiện tại; commit mới có thể khác bản mô tả này.
3. Giữ nguồn nguyên văn, tiếng Việt có dấu, metadata và khả năng truy vết.
4. Không biến ID website thành số hiệu văn bản.
5. Không đưa answer/reference vào truy vấn retrieval đang đánh giá.
6. Không tự đổi schema, child ID mapping hoặc embedding prefix.
7. Thay chunking/embedding phải dùng index tương ứng mới và mô tả ảnh hưởng tới cache cũ.
8. Sửa generation phải giữ ranh giới module, không kéo theo thay corpus nếu nhiệm vụ không cần.
9. Không tự crawl nguồn ngoài, tạo QA synthetic hoặc tăng cường dữ liệu cho LegalQA. Pipeline đã ghi nhận chỉ dùng QA/corpus Task 2; thay phạm vi dữ liệu phải đối chiếu thể lệ và yêu cầu người dùng.
10. Nếu nhiệm vụ chỉ là sửa tài liệu, không tải weights, build full index hoặc train để kiểm chứng một mô tả đã đối chiếu được từ code.

Để Codex dễ tìm tài liệu khi mở repo, có thể bổ sung dòng này vào **file `AGENTS.md` hiện có**, không ghi đè toàn bộ file:

```markdown
Before working on corpus loading, normalization, chunking or indexing, read `docs/LEGALQA_CORPUS_MEMORY.md` and verify the active artifact manifest.
```

## 11. Vận dụng cách tổ chức này cho một corpus RAG mới

Đây là hướng dẫn vận dụng, không phải schema bắt buộc của cuộc thi khác.

Giữ ba lớp tách biệt:

| Lớp | Nội dung | Lý do |
| --- | --- | --- |
| Raw | Bản tải gốc, URL, thời điểm tải, trạng thái tải | Có thể trích xuất lại khi parser thay đổi |
| Document sạch | ID ổn định, title, text, URL, loại nội dung, metadata nguồn | Corpus đọc được độc lập với model |
| Artifact retrieval | Parent/child, tokenizer config, SQLite/FAISS, manifest | Có thể thử model/chunking mới mà không crawl lại |

Quy trình tương ứng:

1. Đối chiếu yêu cầu corpus/schema/nộp bài của cuộc thi mới.
2. Thu thập nguồn được phép và lưu raw có khả năng resume.
3. Trích nội dung chính, giữ tiêu đề, đoạn, danh sách, bảng và provenance.
4. Chuẩn hóa nhẹ; kiểm tra rỗng, lỗi decode, trang lỗi, trùng ID và trùng nội dung.
5. Lưu document sạch **trước khi** chia chunk hoặc encode.
6. Chọn parent theo cấu trúc nguồn: Điều đối với văn bản luật; section/heading đối với bài viết; đơn vị riêng cho bảng hoặc hỏi–đáp nếu nguồn có.
7. Tạo child với offset và metadata kế thừa; chọn kích thước theo tokenizer/model thực tế.
8. Build index cùng manifest; smoke retrieval rồi mới chạy toàn bộ.

Có thể kế thừa ý tưởng parent–child, provenance, exact dedup và artifact identity. Không sao chép máy móc regex Điều, bộ 320/64/48 token hoặc schema LegalQA sang corpus y sinh/báo chí. Với văn bản không có cấu trúc Điều, việc tạo section parent có ý nghĩa cần parser mới; loader LegalQA hiện tại chưa làm việc đó.

**Corpus là tập bằng chứng nguồn có thể tra cứu và truy vết. Retrieval cache là kết quả tìm kiếm trên corpus. QA training là tập nhãn. Ba thành phần cần được lưu và quản lý riêng.**

## 12. Nguồn đối chiếu và giới hạn xác minh

Nguồn chính là checkout repo tại commit đã ghi ở đầu tài liệu, gồm corpus ZIP thực tế, ba file QA, và code/tài liệu được liệt kê ở mục 10.

- [Source tree của commit đã đọc](https://github.com/lighth-gh/uit-dsc-2026-task2-legalqa/tree/05806a7dd613bf5a2e96e413ddd0e8e7411b5d49).
- [Loader và chunking](https://github.com/lighth-gh/uit-dsc-2026-task2-legalqa/blob/05806a7dd613bf5a2e96e413ddd0e8e7411b5d49/legalqa/data.py).
- [Index và retrieval](https://github.com/lighth-gh/uit-dsc-2026-task2-legalqa/blob/05806a7dd613bf5a2e96e413ddd0e8e7411b5d49/legalqa/retrieval.py).
- [Encoder/model contract](https://github.com/lighth-gh/uit-dsc-2026-task2-legalqa/blob/05806a7dd613bf5a2e96e413ddd0e8e7411b5d49/legalqa/models.py).
- [Cấu hình](https://github.com/lighth-gh/uit-dsc-2026-task2-legalqa/blob/05806a7dd613bf5a2e96e413ddd0e8e7411b5d49/config.json).

Lần lập tài liệu này đã đọc toàn bộ document để kiểm tra thống kê lọc và parent, nhưng không tải model, tạo lại child bằng tokenizer E5 hoặc rebuild dense index. Vì vậy số 407.107 child được dẫn theo README của bản repo, không phải kết quả rebuild mới. Quy trình thu thập gốc của BTC chưa được xác minh từ repo này.
