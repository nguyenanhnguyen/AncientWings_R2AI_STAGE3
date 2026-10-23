# Review check ask.39.net — 21/10/2026

Đã tạo `notebooks/check_ask.39.net.ipynb`, notebook độc lập cho Kaggle/Jupyter, và chạy thử cùng helper/snapshot trên máy local. **Truy cập tốt trong lượt thử này, nhưng trích xuất hiện tại chưa đạt để nhập corpus tự động.**

## Phạm vi và cách chạy

- Nguồn: `data/links_corpus_vi_en_zh.parquet`, 1.220.598 dòng; 32.772 URL duy nhất đúng hostname `ask.39.net`.
- Chọn 50 URL, seed `20261021`, giữ ID/URL gốc. Toàn bộ nguồn domain thuộc tầng `https:question`; do đó lượt này tương đương lấy mẫu ngẫu nhiên cố định trong tầng đó.
- Dùng snapshot fetcher, parser và QC từ notebook corpus chính, kiểm SHA-256 trước khi nạp. Không thay đổi parser/cấu hình production, không upload HF.
- Lượt có mạng: 23:30:00–23:33:30 ngày 21/10/2026, giờ Việt Nam; khoảng 210 giây. Một worker, delay 2 giây, một attempt/URL; browser fallback tối đa 3 URL nhưng không cần dùng. Notebook mặc định hai attempts.
- Lượt sandbox trước đó ở `runs/check_ask39_20261021_50` lỗi socket `WinError 10013`, chưa nhận HTTP; không dùng lượt này để kết luận website chặn IP.
- Lượt đánh giá chính: `runs/check_ask39_20261021_live50`.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/build_ask39_notebook.py
.\.venv\Scripts\python.exe -X utf8 scripts/check_ask39.py --limit 50 --attempts 1 --browser-limit 3 --out runs/check_ask39_new
.\.venv\Scripts\python.exe -X utf8 scripts/ask39_audit.py runs/check_ask39_new
```

Trong notebook, bật Internet rồi Run All. Đặt `SOURCE_PARQUET` nếu dùng nguồn local; nếu để trống, notebook tải nguồn HF ghim revision/hash. Mỗi lượt có thư mục mới, không resume. Có raw HTML nén, records, manifest, hash snapshot, kết quả theo URL, báo cáo, DOM audit và ZIP; không tải lại URL khi chạy riêng audit offline.

## Kết quả truy cập và QC chung

| Chỉ số | Kết quả |
| --- | ---: |
| URL đã thử / còn pending | 50 / 0 |
| HTTP 200 / truy cập được | 50 / 50 |
| Requests / Selenium | 50 / 0 |
| Extractor | trafilatura: 50 |
| QC chung accepted / review / rejected | 50 / 0 / 0 |
| Độ dài text: nhỏ nhất / trung vị / lớn nhất | 276 / 707 / 1.926 ký tự |
| Text trùng hoàn toàn trong mẫu | 0 |

Các số này phản ánh khả năng lấy trang và bộ QC chung, chưa chứng minh đủ và sạch nội dung hỏi–đáp.

## Review nội dung đối chiếu HTML gốc

Audit offline kiểm hash raw, so sánh text sau khi bỏ khoảng trắng với các khối DOM `txt_ms`/`txt_bc`, `sele_txt`, `doc_zw .zw2`, `jbk_txt`. Đây là kiểm tra tự động theo cấu trúc của mẫu; các ví dụ bên dưới đã được đọc lại. Không phải 50 nhãn chất lượng thủ công hay thẩm định nội dung y khoa.

| Phát hiện | Số lượng |
| --- | ---: |
| Trang có marker giao diện trong text | 50/50 |
| Trang lẫn nguyên đoạn bách khoa bệnh `jbk_txt` dài ít nhất 30 ký tự | 39/50 |
| Trang thiếu ít nhất một khối trả lời chính | 3/50 |
| Khối trả lời chính đối chiếu được / thiếu | 72 / 3 |
| Trang có trao đổi tiếp / bị thiếu trao đổi tiếp | 3 / 3 |
| Khối trao đổi tiếp tìm thấy / thiếu | 6 / 6 |
| Khối câu hỏi đã nhận diện bị thiếu | 0 |

Các nhóm lỗi có thể chồng lấp. Cả 50 trang đều có ít nhất một vấn đề và được audit gắn `REVIEW`, dù QC chung gắn `accepted`.

### 1. Mất câu trả lời chính

- **ID 2201880**, `https://ask.39.net/question/13268877.html`: HTML có trả lời “没有必要，医用的维生素E足以…” nhưng text chỉ còn câu hỏi và thông tin bệnh/điều trị ở phần phụ.
- **ID 2246297**, `https://ask.39.net/question/37568748.html`: câu trả lời bắt đầu “你好，你最近的情况我已经了解…” không có trong text; phần bách khoa lại được giữ.
- **ID 2212484**, `https://ask.39.net/question/21308126.html`: thiếu một câu trả lời trong hai khối nguồn, vẫn giữ câu trả lời khác và đoạn bách khoa.

Đây là lỗi đáng ưu tiên: text đủ dài và có từ y khoa nên QC chung vẫn chấp nhận, kể cả khi nội dung trả lời cần thiết bị mất.

### 2. Mất toàn bộ trao đổi tiếp trong ba trang có follow-up

- ID **2216701** — `https://ask.39.net/question/24228245.html`.
- ID **2263361** — `https://ask.39.net/question/48803909.html`.
- ID **2262579** — `https://ask.39.net/question/48101733.html`.

Mỗi trang có hai message trong `doc_zw .zw2` ở HTML đã tải, gồm hỏi tiếp và trả lời tiếp. Cả sáu message không có trong text. Ví dụ 2216701 còn câu trả lời đầu nhưng mất nội dung trao đổi về việc xác định chẩn đoán qua bệnh lý; text vẫn giữ các nút `回复追问：`, `取消 提交`. Không cần request mới để thấy các message này.

### 3. Lẫn nội dung phụ và mất cấu trúc

39 trang chứa nguyên đoạn bách khoa từ `jbk_txt`; đây là mức đếm bảo thủ, chưa bao quát mọi phần phụ. Ví dụ ID 2216701 có text 1.926 ký tự nhưng phần lớn là bách khoa về phù. Toàn bộ 50 trang còn marker như `我要咨询`, `举报`, `向医生提问`. Text phẳng chưa thể hiện ổn định bác sĩ nào trả lời và message nào thuộc câu hỏi hay trao đổi tiếp; cần parser cấu trúc nếu muốn dùng như QA.

Audit cũng xử lý sáu khối trả lời có HTML lồng `<p>` không hợp lệ khiến lxml đẩy nội dung sang các paragraph anh em. Đây là sửa cách audit đọc nguồn, không phải sửa parser production hoặc bằng chứng mất sáu câu trả lời.

## Kết luận và hướng tiếp theo

Có thể lấy trang trên mạng/IP local đã thử. **Chưa nên crawl toàn bộ rồi nhập trực tiếp text trafilatura vào corpus.** Cần parser riêng cho ask.39.net giữ câu hỏi, câu trả lời theo từng bác sĩ và các message follow-up; bỏ UI/bách khoa/bài liên quan. QC cần đối chiếu số khối nguồn và nội dung đã giữ, để thiếu câu trả lời/follow-up không được `accepted` chỉ vì text đủ dài.

Sau khi sửa parser, dùng raw đã lưu để replay 50 URL và kiểm lại các ID lỗi; sau đó thử một mẫu holdout mới. Lượt này không xác định quota/tốc độ crawl an toàn cho cả 32.772 URL hoặc độ đúng y khoa của câu trả lời.

## Kiểm tra và bằng chứng

- Ba test đã pass: chọn mẫu đúng hostname/giữ ID/tái lập; notebook đúng cú pháp và payload/hash; audit phát hiện mất follow-up, bách khoa/UI và xử lý HTML paragraph lồng sai.
- Lệnh: `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p test_ask39_check.py -v`.
- Đã thực thi helper crawl 50 URL và audit offline; notebook đã được validate/compile, chưa Run All trong kernel Kaggle.
- `runs/check_ask39_20261021_live50/summary.json`: kết quả truy cập/QC chung.
- `runs/check_ask39_20261021_live50/dom_audit_summary.json` và `dom_audit.jsonl`: thống kê và bằng chứng từng ID.
- `runs/check_ask39_20261021_live50/report.md`: text trích xuất đủ 50 URL.
- `runs/check_ask39_20261021_live50.zip`: raw, records, snapshot, source sample, báo cáo và code check/audit dùng cho lượt này.
