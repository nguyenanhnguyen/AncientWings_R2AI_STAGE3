# Pipeline crawl corpus ViBioMIR cho R2AI2026

Ngày đối chiếu: **03/10/2026, giờ Việt Nam**. Phạm vi: lấy danh sách URL, tải nội dung, trích xuất văn bản, kiểm tra chất lượng và xuất corpus tài liệu. Theo yêu cầu mới nhất, mẫu hiện hành là **1.000 ID từ 583 đến 1582**, tương ứng khoảng **[583, 1583)**. Lấy cả hai đầu 583 và 1583 sẽ thành 1.001 ID.

**Bắt đầu ở [`CRAWL_1000_IDS.md`](CRAWL_1000_IDS.md)** để chạy/resume đúng dải ID. Run tải: `runs/ids_583_1582`; corpus hiện hành: `runs/ids_583_1582_clean`. Các phần về mẫu cân bằng hostname trong tài liệu này là thiết kế mở rộng và lịch sử pilot trước khi người dùng chốt dải ID; không mô tả mẫu ID hiện hành.

**Kết quả thực tế:** [`CRAWL_RESULT_1000.md`](CRAWL_RESULT_1000.md), gồm 976 tài liệu vượt kiểm tra tự động, 13 cần xem lại và 11 rejected; corpus đã xuất JSONL/Parquet.

Logic crawl nằm tại [`src/vibiomir/crawl/crawler.py`](../../src/vibiomir/crawl/crawler.py); điểm chạy giữ tại [`scripts/crawl_corpus.py`](../../scripts/crawl_corpus.py). Kết quả chạy lưu riêng trong `runs/`; các mục về browser, OCR, parser đặc thù và hệ thống crawl quy mô lớn là hướng mở rộng, được ghi rõ bên dưới.

## 1. Kết luận từ các tài liệu đã đọc

| Nguồn | Yêu cầu liên quan trực tiếp đến crawl | Quyết định cho pipeline |
| --- | --- | --- |
| [`overview.pdf`](../references/overview.pdf), trang 1–2 | Bài toán truy hồi y sinh đa ngôn ngữ; đội thi chủ động thu thập nguồn | Giữ nguyên ngôn ngữ gốc, không dịch hoặc viết lại tài liệu |
| [`data.pdf`](../references/data.pdf), trang 1–2 | URL và ID trong `links_corpus.parquet`; tài liệu ngoài danh sách không được tính là nhãn dương trong bản đánh giá này | Danh sách Parquet là nguồn công việc; giữ nguyên ID số nguyên và URL gốc |
| [`evaluation.pdf`](../references/evaluation.pdf), trang 1–2 | Chấm theo tài liệu và đoạn; đối chiếu đoạn trong cùng `doc_id`; LCS token sau chuẩn hóa, ngưỡng overlap 40%; Precision/Recall/F2 macro | Ưu tiên giữ đầy đủ nội dung thật và thứ tự đoạn; chất lượng crawl là phép đo riêng, không gọi tỷ lệ HTTP 200 là điểm contest |
| [`submission.pdf`](../references/submission.pdf), trang 2–3 | `doc_id` là ID gốc; `chunk_text` phải trích từ nguồn, không sinh lại; nộp đủ 1.200 truy vấn | Corpus phải truy vết được đến ID/URL/raw; không lấy query làm tài liệu; chưa tạo submission trong giai đoạn crawl |
| [`LEGALQA_CORPUS_MEMORY.md`](../references/LEGALQA_CORPUS_MEMORY.md), mục 4, 10–11 | Tách raw, tài liệu sạch, artifact; chuẩn hóa nhẹ, provenance, kiểm tra lỗi | Kế thừa tổ chức dữ liệu; không áp dụng schema pháp luật, regex Điều, thông số chunk hay xóa ID trùng text của LegalQA |
| [ViBioMIR dataset card](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/blob/0148f6f80ffafed5c005af6d506ccfd9d3fb47a7/README.md) | Hai config `corpus` và `query`; file nguồn là Parquet | Đọc file trực tiếp, không scrape bảng HTML của Dataset Viewer |

Quy định chuẩn hóa của evaluator gồm NFKC, giải mã HTML entity, chữ thường và gộp khoảng trắng. Đây là phép biến đổi **khi so khớp**, không phải lý do phá hủy bản văn gốc trong corpus. Bản clean ở đây dùng NFC, giữ hoa/thường, dấu tiếng Việt, số, đơn vị, công thức và đoạn văn. Raw luôn được giữ để trích lại.

Các PDF là bản chụp trang contest ngày 02/10/2026 do người dùng cung cấp, đã đọc đủ 11 trang bằng ảnh vì PDF không có text layer. Tài liệu này không khẳng định các trang contest trực tuyến sẽ không thay đổi sau ngày đối chiếu.

## 2. Đầu vào đã kiểm tra thực tế

| Thuộc tính | Giá trị |
| --- | --- |
| Dataset | `AIGuruTinix/ViBioMIR` |
| Revision Hugging Face đã đối chiếu | `0148f6f80ffafed5c005af6d506ccfd9d3fb47a7` |
| File local | `data/links_corpus.parquet` |
| Dung lượng | 35.111.121 byte |
| Số bản ghi thực tế | **4.394.718** |
| Schema | `id: int64`, `url: string` |
| ID nhỏ nhất / lớn nhất | **583 / 4.420.561** |
| ID trùng | **0** |
| Số hostname | **97** |
| Query local | `data/query.parquet`, 1.200 hàng; schema `id`, `query` |

SHA-256 file corpus local khớp `X-Linked-ETag` của file tại revision trên:

```text
dee1153f5b9d9010dea18e1b7724b4915ff847b711d036bec8b933486802a971
```

Dataset card ghi 4.420.561 liên kết và ID 1–4.420.561; file thực tế có số hàng thấp hơn. **Không tạo thêm các ID còn thiếu, không gán lại ID liên tiếp, không dùng số hàng làm doc_id.** Manifest lấy số hàng và hash thực tế làm căn cứ.

Một số hostname lớn: `www.cnkang.com` 963.438 URL, `www.120ask.com` 918.479, `www.familydoctor.com.cn` 447.453, `ask.39.net` 337.375. Đây là thống kê URL, không phải nhãn ngôn ngữ hoặc số tài liệu crawl thành công. Dataset được giới thiệu là Việt–Anh–Trung, nhưng chưa được phép suy ra số tài liệu tiếng Anh chỉ từ mô tả đó.

## 3. Luồng xử lý

```text
links_corpus.parquet + hash nguồn
    -> kiểm tra schema / ID / URL / phân bố hostname
    -> sample.jsonl cố định, đúng ID 583 <= id < 1583
    -> kiểm tra robots + tải HTTP có giới hạn + log redirect/retry
    -> raw/<sha256>.gz và records/<id>.json
    -> trích nội dung chính HTML hoặc PDF có text
    -> chuẩn hóa nhẹ + đánh cờ chất lượng + nhóm trùng text
    -> documents.jsonl / corpus.accepted.jsonl / quarantine.jsonl
    -> báo cáo toàn mẫu, từng hostname, kiểm tra thủ công
    -> sửa parser hoặc phương thức tải theo lỗi quan sát được
```

Đầu ra dừng ở **document đầy đủ**. Chia chunk, embedding, index, retrieval, reranking và train nằm ở công việc sau.

## 4. Thiết kế pilot 1.000 URL

### 4.1. Mẫu ID đã chốt và giới hạn đại diện

Run hiện hành lọc trên cột `id` bằng `583 <= id < 1583`, xác nhận có đúng 1.000 hàng và không thiếu ID nào. Mẫu gồm 999 URL Bạch Mai và 1 URL VietnamPlus. Đây là phép thử tập trung theo yêu cầu người dùng; tỷ lệ thành công của nó không đại diện cho tiếng Anh/Trung hoặc toàn bộ 97 hostname. `weighted_accepted_rate` sẽ để null cho mẫu này.

### 4.2. Thiết kế cân bằng hostname để dùng sau

Thứ tự file gom URL theo nguồn. Trong 1.000 dòng đầu có 1 URL `special.vietnamplus.vn` và 999 URL `bachmai.gov.vn`. Mẫu đó hữu ích để viết parser Bạch Mai nhưng không đại diện cho các loại trang trong corpus.

Pilot cũ `runs/pilot1000_v2` đã dùng **reservoir sampling trong từng hostname**:

1. Đếm số URL mỗi hostname trên toàn bộ Parquet.
2. Phân bổ quota lần lượt, gần bằng nhau, tổng đúng 1.000.
3. Hostname ít URL được lấy hết; phần dư phân bổ cho các hostname khác.
4. Dùng seed 42 chọn ngẫu nhiên trong từng nhóm; lưu lại danh sách ID/URL và hash mẫu trước khi crawl.
5. Lịch crawl xáo trộn để tránh dồn toàn bộ request vào cùng website.

Đây là mẫu để **phát hiện lỗi parser và khả năng truy cập trên nhiều nguồn**. Tỷ lệ thành công không trọng số của mẫu này không phải ước lượng trực tiếp tỷ lệ toàn bộ 4,39 triệu URL. Báo cáo bổ sung ước lượng trọng số theo số URL mỗi hostname khi toàn bộ mẫu đã hoàn tất:

```text
weighted_acceptance = Σ_h (N_h / N_total) × (accepted_h / sampled_h)
```

Mẫu mỗi hostname nhỏ, và các subdomain cùng website có thể tương quan. Chỉ xem đây là ước lượng sơ bộ; chưa có khoảng tin cậy hoặc cam kết hiệu suất full crawl. Lần kiểm tra tiếp theo nên có một mẫu ngẫu nhiên đều theo URL độc lập để đo độ bao phủ toàn corpus.

### 4.3. Giới hạn của “1.000”

- 1.000 là **số URL đầu vào**, không phải cam kết 1.000 tài liệu sạch.
- Không thay URL lỗi bằng URL khác để làm đẹp tỷ lệ; giữ nguyên mẫu số và lý do thất bại.
- Nếu cần đủ 1.000 tài liệu sạch, thực hiện lượt lấy mẫu bổ sung riêng và báo cáo cả hai lượt.
- `query.parquet` chỉ được kiểm tra schema/số hàng; không dùng câu hỏi để chọn trang, viết lại nội dung hoặc suy ra gold relevance.

## 5. Tải nội dung và lưu bằng chứng

### 5.1. Cấu hình pilot đã triển khai

| Cấu hình | Mặc định |
| --- | --- |
| Tổng worker | 12 |
| Request đồng thời cùng registered domain | 1, kể cả các subdomain |
| Khoảng nghỉ | Ít nhất 1 giây sau mỗi request; tôn trọng crawl-delay/request-rate lớn hơn |
| User-Agent | `ViBioMIRResearchCrawler/0.1` |
| Timeout connect/read | 8 / 20 giây |
| Ngân sách một response | Khoảng 45 giây, kiểm tra khi nhận chunk; read timeout vẫn có thể kéo dài thêm |
| Số lần thử tải trang | Tối đa 3 |
| Retry | Network error, HTTP 408/429/500/502/503/504; backoff; tôn trọng Retry-After |
| Redirect | Tối đa 8 bước; kiểm tra URL/robots ở đích mới |
| Giới hạn response | 10 MiB sau giải nén HTTP |
| robots.txt | Cache trong tiến trình, lưu bằng chứng xuống file; tải lại khi khởi động lượt crawl |
| Checkpoint | Một JSON ghi atomic cho mỗi ID hoàn tất |

Robots 404/410 được hiểu là không có file quy tắc; 401/403 được ghi `robots_denied`; lỗi mạng hoặc response không rõ được ghi `robots_unknown`, không tự xem là cho phép. URL bị disallow có trạng thái riêng. Đây là lựa chọn vận hành thận trọng của pilot, không phải một yêu cầu riêng đã thấy trong PDF contest.

Không thử vượt CAPTCHA, dùng proxy xoay vòng hoặc đăng nhập tự động. TLS được kiểm tra bình thường. Chỉ nhận HTTP(S), chặn đích private/loopback và cổng bất thường, kể cả khi redirect.

Raw lưu **response body sau HTTP content decoding**, nén gzip để tiết kiệm đĩa; không phải ảnh chụp toàn bộ gói tin mạng. Lưu hash trước gzip, URL gốc/cuối, redirect chain, status, thời gian, Content-Type/ETag/Last-Modified nếu có. Các response lỗi HTTP vẫn được giữ raw nếu tải hoàn tất. Các body vượt giới hạn/deadline không được dùng như văn bản đầy đủ.

### 5.2. Resume và phục hồi

- Chạy lại cùng lệnh sẽ bỏ qua ID đã có checkpoint, bao gồm cả ID thất bại. Vì thế resume không tạo retry vô hạn.
- Script hash, phiên bản package, delay, attempts và User-Agent phải khớp cấu hình lượt chạy; mẫu phải khớp SHA-256.
- Thay parser/cấu hình cần **run mới**, không sửa hash trong manifest để ép resume.
- Lượt phục hồi lỗi phải có manifest riêng gồm các ID lỗi đã chọn, `parent_run` và lý do retry; chưa có CLI tự động tạo recovery run trong bản pilot này.
- Không đánh đồng `robots_unknown`, HTTP 403, timeout, trang cần JS và lỗi extraction. Mỗi nhóm cần hướng xử lý khác nhau.
- Trường hợp Retry-After dài được ghi deferred khi phát hiện trong vòng retry; trước full crawl cần bổ sung scheduler lưu `next_retry_at` bền vững để worker không phải chờ lâu.

## 6. Trích xuất và chuẩn hóa

### 6.1. Đã triển khai

**HTML:** Đọc charset từ Content-Type hoặc khai báo HTML trước; ánh xạ GB2312/GBK sang bộ giải mã GB18030. Nếu không có khai báo thì chuyển bytes cho extractor tự nhận diện; nếu decode strict thất bại thì gắn cờ review. Trafilatura lấy title, nội dung chính, bảng và metadata sẵn có. Tắt comments, không bật deduplicate nội bộ để tránh làm mất các đoạn lặp nhưng có ý nghĩa. Giữ raw để kiểm tra lại khi main-content extractor lấy thiếu.

**Riêng Bạch Mai, bản v3:** lấy trực tiếp `div.content-excerpt` và `div.content-editor-post` sau khi kiểm tra DOM thực tế. Cách này giữ phần mở đầu mà extractor chung đã bỏ sót ở ID 1015, 1122 và 1247. Giữ văn bản các heading/paragraph/list/table trong vùng bài, không lấy khối tin liên quan/menu/footer. Nếu không tìm đúng một container thân bài thì dùng fallback và gắn cờ review. Parser không tự loại văn bản vì thiếu đoạn mở đầu; nhiều bài gốc không có excerpt.

**PDF có text:** PyMuPDF lấy text theo trang, giữ thứ tự trang và metadata title nếu có. Trang ít text được gắn cờ để xem lại. Không chạy OCR trong pilot.

**Chuẩn hóa:** Unicode NFC; CRLF về LF; gộp space/tab dư; giảm dòng trắng dư. Không lower-case toàn văn, xóa dấu, stemming, dịch, tóm tắt hoặc viết lại bằng LLM. Không loại toàn bộ các đoạn có từ “thuốc”, “liều” hay tên bệnh bằng một bộ lọc từ khóa.

Ví dụ phải giữ nguyên về mặt nội dung: `0,5 mg/kg`, `Na⁺ ≥ 135 mmol/L`, câu phủ định, chống chỉ định, độ tuổi, thời gian điều trị. “Tài liệu sạch” ở đây có nghĩa là trích xuất tốt, **không phải xác nhận tính đúng đắn về y khoa của tác giả**.

### 6.2. Cần làm theo kết quả pilot, chưa triển khai

| Tình huống | Hướng xử lý tiếp theo | Điều kiện nghiệm thu |
| --- | --- | --- |
| HTTP 200 nhưng chỉ có JavaScript shell | Render có giới hạn bằng browser cho các trang công khai và được phép truy cập | Main content thật xuất hiện, còn giữ URL/ID gốc và raw rendered |
| Website hỏi–đáp | Parser theo DOM của câu hỏi + câu trả lời chuyên môn; tách quảng cáo/bình luận | Không mất nội dung câu trả lời vì bị xem nhầm là comments |
| Trang bài dài nhiều phần | Xác minh pagination thuộc cùng bài; lưu từng phần và quan hệ | Không ghép bài liên quan thành một document |
| HTML chỉ có player/video | Ghi thiếu text; dùng transcript chính thức nếu nguồn có và truy vết được | Không tự sinh transcript hoặc nội dung y khoa |
| PDF scan/bảng phức tạp | OCR hoặc parser bảng, lưu engine/version và điểm tin cậy | Rà số, dấu thập phân, đơn vị, quan hệ hàng–cột |
| Trang lỗi mềm HTTP 200 / chuyển về homepage | Heuristic + kiểm tra title/URL/DOM theo nguồn | Không cho trang chủ/anti-bot vào accepted |
| Redirect đổi domain | Kiểm tra thủ công quan hệ nội dung | Giữ ID nguồn; không tự gán nội dung website khác là bài gốc |
| Nội dung trùng template trên nhiều ID | Phân tích nhóm hash trùng và near-duplicate | Phân biệt bản đăng lại thật với cùng một trang lỗi |

Chưa có near-dedup, model nhận diện ngôn ngữ, parser riêng 97 website, trình render JS, OCR, hoặc phát hiện đầy đủ mọi paywall/challenge. Không mô tả các phần này là đã chạy.

## 7. Schema và artifact

Giữ một bản ghi cho **mỗi ID gốc**. Khóa chính là `id` integer. Một URL hoặc text có thể gắn với nhiều ID; nhóm trùng chỉ bổ sung metadata, không xóa các ID còn lại.

| Artifact trong `runs/pilot1000/` | Nội dung |
| --- | --- |
| `manifest.json` | Hash nguồn, phương pháp chọn mẫu, seed, số URL, hash mẫu |
| `source_profile.json` | Phân bố toàn nguồn, quota từng hostname, thống kê 1.000 dòng đầu |
| `sample.jsonl` | Chính xác 1.000 dòng `id`, `url`, `domain` |
| `crawl_config.json` | Script hash, package versions, thông số request |
| `robots/*.json` | Response/rule/error khi kiểm tra robots |
| `raw/<prefix>/<sha256>.gz` | Body nguồn theo content hash |
| `records/<id>.json` | Checkpoint: trạng thái, lỗi, request trace, metadata, text và QC nếu có |
| `documents.jsonl` | Tất cả bản ghi đã đi qua extractor, kể cả review/rejected |
| `corpus.accepted.jsonl` | Bản ghi vượt bộ kiểm tra tự động; chất lượng còn cần audit |
| `quarantine.jsonl` | Bản ghi chưa accepted, gồm lỗi truy cập và nội dung đáng ngờ |
| `duplicates.jsonl` | Nhóm SHA-256 text và mọi ID thuộc nhóm |
| `quality_report.json` | Các phép đếm, tỷ lệ, độ dài và bảng theo hostname |
| `QUALITY_REPORT.md` | Báo cáo đọc nhanh |
| `manual_review.jsonl` | Phiếu audit mẫu; không tự ghi đè nhãn người đánh giá |
| `artifact_manifest.json` | Hash các file đầu ra chính |

Các trường quan trọng của document: `id`, `url`, `domain`, `final_url`, `title`, `text`, `published_at`, `author`, `extractor`, `raw_path`, `raw_sha256`, `text_sha256`, `started_at`, `finished_at`, `http_status`, `quality_status`, `quality_flags`, `char_count`, `language_hint`, `duplicate_doc_ids`.

Metadata không có thì để null/rỗng; không suy ra ngày xuất bản từ ngày crawl. `language_hint` là dấu hiệu chữ viết, không phải nhãn ngôn ngữ có xác suất được hiệu chuẩn. `latin_or_unknown` không được gọi là tiếng Anh.

## 8. Đánh giá chất lượng crawl

### 8.1. Độ bao phủ và trạng thái kỹ thuật

Với `N_selected = 1000`, báo cáo tối thiểu:

```text
completion_rate = N_checkpoint / N_selected
http_success_rate = N_HTTP_2xx / N_selected
extraction_rate = N_extracted / N_selected
usable_rate_auto = N_accepted / N_selected
extraction_given_http = N_extracted / N_HTTP_2xx
```

Mẫu số bằng 0 thì ghi không xác định, không báo 100%. Chưa hoàn tất phải báo `pending`; không gom pending vào HTTP failure. Chia theo hostname, nhóm lỗi, Content-Type và dấu hiệu ngôn ngữ. Khi cần ngôn ngữ chuẩn, bổ sung detector có đánh giá riêng; không dùng hostname làm nhãn chắc chắn.

`extracted` nghĩa là đã chạy extractor, có thể trả text rỗng; chỉ số đó phải đọc cùng `accepted/review/rejected`. HTTP 200 không chứng minh có bài viết. Lỗi robots tính vào độ bao phủ cuối cùng nhưng không gọi là lỗi parser.

### 8.2. Kiểm tra tự động trong pilot

| Kiểm tra | Hành động |
| --- | --- |
| ID trùng/missing hoặc mẫu thay đổi | Dừng thay vì tự sửa |
| Raw/text hash không khớp lúc export | Dừng, không xuất artifact giả hợp lệ |
| Text rỗng hoặc dấu hiệu error/challenge | Rejected |
| Text ngắn hơn 300 ký tự; với CJK-dominant ngắn hơn 120 | Review, không loại vĩnh viễn |
| Thiếu title | Review |
| Ký tự thay thế `�` trên 0,1%; charset khai báo decode thất bại; tỷ lệ Cyrillic bất thường trên 10% | Review decode/script, không tự coi là nội dung hợp lệ |
| Có ít nhất 3 marker template/quảng cáo đã thấy trong smoke test | Review boilerplate; vẫn giữ text để sửa parser |
| Tỷ lệ chữ dưới 45% | Review; có thể là bảng hợp lệ |
| Tỷ lệ dòng lặp trên 20% ở các dòng dài từ 20 ký tự | Review template/boilerplate |
| PDF có trang dưới 30 ký tự | Review OCR |
| Redirect đổi hostname hoặc về trang chủ | Review quan hệ với URL gốc |
| Exact text duplicate | Ghi nhóm và giữ tất cả ID |

Đây là **ngưỡng khởi đầu do dự án chọn**, không phải ngưỡng contest. Không áp dụng ngưỡng số từ dựa trên dấu cách của tiếng Việt/Anh cho tiếng Trung. Không tăng tỷ lệ accepted bằng cách nới ngưỡng trước khi xem raw.

### 8.3. Audit thủ công bắt buộc trước khi gọi corpus “đạt”

Pilot tạo phiếu lấy ví dụ theo hostname. Mở **raw và text cạnh nhau**, ưu tiên đủ các loại trang và đủ vi/zh/en thực sự hiện diện. Lấy thêm mẫu ở nhóm accepted, short, redirect, decode và duplicate; ghi rõ nhóm lấy mẫu để không suy diễn tỷ lệ sai.

Chấm từng tài liệu:

1. **Đúng trang:** nội dung đúng bài tương ứng ID/URL; không phải trang chủ, login hoặc challenge.
2. **Đầy đủ (0–2):** 0 sai/thiếu phần lớn; 1 thiếu phần quan trọng; 2 giữ được thân bài chính.
3. **Sạch (0–2):** 0 chủ yếu menu/ads; 1 còn nhiễu đáng kể; 2 ít nhiễu, đọc độc lập được.
4. **Trung thực với nguồn:** liều lượng, số, đơn vị, phủ định và thứ tự nội dung còn đúng; bảng không bị ghép nhầm quan hệ.
5. **Truy vết:** tìm được raw, hash, thời gian tải và ID nguồn.

Không có gold passages trong đầu vào local để đo recall nội dung chuẩn của contest. Nếu muốn đo extraction precision/recall, người kiểm tra phải đánh dấu các block nội dung chính trên raw cho một tập audit rồi so với output; không tự tạo “gold” bằng output của chính extractor.

Ngưỡng đề xuất để chuyển từ pilot sang batch 10.000: mapping/hash hợp lệ 100%; không còn lỗi sai ID; trong tối thiểu 100 tài liệu accepted được audit, ít nhất 95% đúng trang và ít nhất 90% đạt đầy đủ=2/sạch=2; không có lỗi số/đơn vị nghiêm trọng chưa xử lý. Các tỷ lệ này là gate nội bộ cần kiểm tra trên mẫu audit, **chưa phải kết quả đã đạt**. Với miền thất bại nhiều, viết kế hoạch khắc phục riêng trước khi mở rộng.

## 9. Lệnh chạy trên PowerShell

**Run đúng yêu cầu ID hiện hành:** dùng các lệnh ở [`CRAWL_1000_IDS.md`](CRAWL_1000_IDS.md). Đoạn dưới minh họa chế độ cân bằng hostname cũ; không dùng lại tên `pilot_balanced_example` nếu thư mục đã tồn tại.

Chạy từ thư mục gốc dự án; không cần GPU hoặc tải model.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/crawl.lock.txt

.\.venv\Scripts\python.exe -m unittest discover -s tests -v

.\.venv\Scripts\python.exe scripts/crawl_corpus.py prepare --source data/links_corpus.parquet --out runs/pilot_balanced_example --size 1000 --seed 42

# Thử 30 URL trong đúng mẫu đã chọn trước khi chạy phần còn lại.
.\.venv\Scripts\python.exe -u scripts/crawl_corpus.py crawl --out runs/pilot_balanced_example --workers 12 --delay 1 --attempts 3 --max-new 30

# Hoàn tất các URL chưa có checkpoint; dùng cùng cấu hình và mã nguồn.
.\.venv\Scripts\python.exe -u scripts/crawl_corpus.py crawl --out runs/pilot_balanced_example --workers 12 --delay 1 --attempts 3

# Tính lại báo cáo và kiểm tra hash mà không truy cập mạng.
.\.venv\Scripts\python.exe scripts/crawl_corpus.py report --out runs/pilot_balanced_example
```

`prepare` không ghi đè run đã tồn tại. Nếu đã có `runs/pilot_balanced_example/manifest.json`, dùng thẳng `crawl`/`report`; muốn chọn mẫu mới, đổi `--out`. Trong môi trường hạn chế network, lệnh crawl cần được phép kết nối đến các URL công khai; chạy báo cáo không cần network.

`requirements/crawl.txt` liệt kê thư viện trực tiếp; `requirements/crawl.lock.txt` khóa cả dependency đã cài trong lần triển khai. Môi trường đã kiểm tra: Windows, Python 3.14. Không cam kết dependency lock này dùng nguyên vẹn trên mọi phiên bản Python.

### Đọc nhanh kết quả

```powershell
Get-Content -Encoding UTF8 runs/pilot_balanced_example/QUALITY_REPORT.md
Get-Content -Encoding UTF8 runs/pilot_balanced_example/quality_report.json
```

Từ bản v2, phiếu `manual_review.jsonl` chỉ sinh khi đủ checkpoint cho toàn mẫu. Script không ghi đè phiếu để giữ nhãn thủ công. Báo cáo tự động được tính lại từ toàn bộ checkpoint hiện có.

### Các run cũ giữ làm bằng chứng

Các lệnh dưới mô tả quy trình lịch sử. Khi resume run cũ, dùng snapshot khớp hash trong `crawl_config.json`; code hiện hành sẽ từ chối cấu hình khác. Output reprocess phải là thư mục mới.

`runs/pilot1000` là smoke run v1 gồm 30 URL. Sau khi phát hiện lỗi charset và nhiễu template, đã tạo **`runs/pilot1000_v2`** bằng raw đã lưu, rồi crawl tiếp các URL chưa có checkpoint. Không trộn phiên bản parser trong run cũ và không tải lại 30 trang chỉ để sửa extraction.

```powershell
# Tạo phiên bản mới từ raw; --out phải chưa tồn tại.
.\.venv\Scripts\python.exe scripts/crawl_corpus.py reprocess --source-run runs/pilot1000 --out runs/pilot1000_v2

# Xem run cân bằng website cũ; không phải dải ID hiện hành:
.\.venv\Scripts\python.exe -u scripts/crawl_corpus.py crawl --out runs/pilot1000_v2 --workers 12 --delay 1 --attempts 3
.\.venv\Scripts\python.exe scripts/crawl_corpus.py report --out runs/pilot1000_v2
Get-Content -Encoding UTF8 runs/pilot1000_v2/QUALITY_REPORT.md
```

`reprocess` đọc lại raw và tạo bộ document/report mới; không chạy mạng, không thử lại các URL trước đó bị chặn hoặc lỗi tải. Phiên bản source run được giữ nguyên.

## 10. Mở rộng sau pilot

Không dùng script pilot nạp hàng triệu future và hàng triệu record vào RAM để chạy full corpus. Bản hiện tại phù hợp cho 1.000 URL, có thể tăng batch có kiểm soát sau khi đo RAM/đĩa/thời gian.

Lộ trình crawl:

1. Sửa các lỗi có bằng chứng từ mẫu; re-extract từ raw khi chỉ đổi parser để giảm tải website.
2. Chạy batch 10.000, gồm mẫu theo tỷ trọng URL và các case khó; giữ báo cáo riêng, không nhập nhằng với pilot cân bằng hostname.
3. Thay danh sách future bằng hàng đợi giới hạn; trạng thái dùng SQLite/PostgreSQL, mỗi lần commit một batch, có lease/checkpoint bền vững.
4. Lập lịch theo registered domain với rate limit/cooldown lưu qua restart; cơ chế thử lại lỗi tạm thời và dừng domain lỗi diện rộng.
5. Raw lưu content-addressed thành shard/object storage; document xuất JSONL/Parquet theo shard, không tạo hàng triệu file lẻ khi không cần.
6. Ước lượng dung lượng bằng **số byte raw gzip và text thực đo theo hostname**, nhân số URL tương ứng; có khoảng dự phòng. Không hứa thời gian full crawl chỉ từ băng thông đường truyền.
7. Đóng băng corpus version cùng manifest, số ID thành công/thất bại và hồ sơ audit trước khi chuyển sang chunk/index/train.

Việc nguồn ngoài được phép sử dụng có điều kiện theo `overview.pdf` không làm mọi URL ngoài manifest trở thành tài liệu có nhãn dương. Trong giai đoạn này chỉ dùng URL BTC cung cấp và các redirect được lưu vết, không tự mở rộng frontier bằng sitemap hoặc link trong bài.

## 11. Nguồn kỹ thuật và giới hạn kết quả

- [Danh sách corpus trên Hugging Face](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/viewer/corpus/train): điểm vào người dùng cung cấp.
- [Dataset card tại revision đã đối chiếu](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/blob/0148f6f80ffafed5c005af6d506ccfd9d3fb47a7/README.md): schema và bối cảnh dataset; thống kê số hàng được kiểm tra lại bằng file.
- [API rows của Hugging Face](https://huggingface.co/docs/dataset-viewer/rows): nếu không có file local, có thể lấy lát dữ liệu qua API; không cần điều khiển UI. Chạy hiện tại không phụ thuộc API này.
- [Trafilatura API](https://trafilatura.readthedocs.io/en/latest/corefunctions.html): tùy chọn extraction, metadata, tables, comments; pipeline không đặt bộ lọc chỉ nhận một ngôn ngữ.

Báo cáo thực nghiệm hiện hành nằm ở [`runs/ids_583_1582_clean/QUALITY_REPORT.md`](../../runs/ids_583_1582_clean/QUALITY_REPORT.md), còn chi tiết máy đọc ở `quality_report.json` cùng thư mục. Corpus accepted vẫn là **bản ứng viên đã qua heuristic**, cần audit trước khi tuyên bố đạt độ đầy đủ và độ sạch mục tiêu.
