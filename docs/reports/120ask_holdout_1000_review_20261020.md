# Thử 1.000 URL 120ask khác và kiểm tra lại F1/F2/F3 — 20/10/2026

**Kết luận: chưa đánh giá được F1/F2/F3 trên mẫu mới vì lỗi truy cập.** Đã chọn đủ 1.000 câu hỏi độc lập với lịch sử mẫu có sẵn. Cả 5 URL đầu tiên được thử crawl đều trả **HTTP 521, response body rỗng**. Circuit breaker dừng; 995 URL còn lại chưa gửi request. Không có HTML/câu trả lời mới để xác nhận còn hay hết lỗi.

Run: `runs/ask120_holdout_20261020T050502017470Z`. Mẫu tạo lúc 12:05 ngày 20/10/2026, crawl thực hiện khoảng 12:44–12:45 giờ Việt Nam. Đây là lần thử crawl live trên mẫu khác, không replay bộ 1.000 HTML cũ. Chưa hoàn tất crawl 1.000 URL.

## Mẫu độc lập và phiên bản

- Nguồn: `data/links_corpus_vi_en_zh.parquet`, 1.220.598 dòng. Giữ ID nguyên bản; gom HTTP/HTTPS theo canonical question, reservoir sampling với seed **2026102003**.
- Đối chiếu **269 file lịch sử**, gồm `sample.jsonl` trong các run local và hai ZIP check 120ask trong Downloads. Các bản replay trùng nhau được tính một lần theo câu hỏi: **1.086 câu hỏi lịch sử duy nhất**.
- **1.000 câu hỏi mới, 1.000 canonical URL duy nhất, trùng lịch sử = 0**. Không cam kết với lịch sử không có trên máy.
- Parser `120ask-parser-v4`; gate/admission `v3.1`; ruleset `120ask-source-signals-v1`. Source parser/gate/policy giữ nguyên bản sau F3.
- SHA-256 source Parquet: `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`.
- SHA-256 sample JSONL: `b7007a60a2b9406831892a28232303e695f6224b3f974b624e7bb25442bb3474`.

## Kết quả truy cập

| Chỉ số | Kết quả |
|---|---:|
| URL được chọn | 1.000 |
| URL thực sự đã gửi request | 5 |
| HTTP 521 | 5/5 |
| HTML sử dụng được | 0 |
| URL chưa thử | 995 |
| Thread mới được parse | 0 |
| Candidate mới | 0 |

| Source ID | URL | HTTP | Body |
|---|---|---:|---:|
| 1266388 | http://www.120ask.com/question/4191214.htm | 521 | 0 byte |
| 1353680 | http://www.120ask.com/question/71771441.htm | 521 | 0 byte |
| 1073444 | http://www.120ask.com/question/14739224.htm | 521 | 0 byte |
| 2908421 | https://www.120ask.com/question/608054.htm | 521 | 0 byte |
| 2873663 | https://www.120ask.com/question/46620.htm | 521 | 0 byte |

Crawl dùng một worker, delay 2 giây, một attempt/URL; không browser, không đổi proxy/IP hoặc tự retry hàng loạt. Đã chạy ngoài sandbox sau khi sandbox ban đầu chặn socket. Vì vậy HTTP 521 trên đây là kết quả request ngoài sandbox. Từ response hiện có chưa xác định được nguyên nhân ở origin, mạng hay chính sách truy cập của site.

Năm checkpoint EXCLUDE có lý do `FETCH_OR_RAW_EVIDENCE_ERROR`, không phải năm lỗi nội dung hay năm câu trả lời bị loại sau review. `summary.json` dùng nhãn tổng quát `NEEDS_PARSER_FIX` khi thiếu dữ liệu/raw; chín regression cố định thuộc bộ cũ cũng vắng mặt theo thiết kế holdout. Những trường này không chứng minh parser mới hỏng. Kết luận riêng của lượt này là **`NOT_ASSESSED_ACCESS_BLOCKED`**.

## Review F1/F2/F3

| Finding | Trạng thái trên mẫu mới | Lý do |
|---|---|---|
| F1: audio chỉ có lời nhắc vẫn INCLUDE | **Chưa đánh giá được** | Chưa có reply/audio mới |
| F2: nghề nghiệp thiếu bằng chứng | **Chưa đánh giá được** | Chưa có header/qualification mới |
| F3: quảng bá bỏ sót / bắt nhầm lâm sàng | **Chưa đánh giá được** | Chưa có nội dung mới để đọc ngữ cảnh |

**76/76 test regression 120ask pass** trong lượt này. Kết quả đó xác nhận các ca đã biết vẫn đạt; không thay thế kiểm chứng trên 1.000 URL mới. Không đưa nhãn AI vào phiếu review con người, không suy tỷ lệ lỗi từ 0 thread và không thay đổi các rule F1/F2/F3 khi chưa có bằng chứng mới.

## Đã chuẩn bị để hoàn tất thử nghiệm

[Notebook check chung](../../notebooks/check_120ask_50.ipynb), chế độ MODE='holdout_1000', đóng gói đúng tập URL đã chọn, lịch sử loại trùng và source hiện tại. Không cần đưa Parquet gốc lên Kaggle. Bật Internet và chạy **Run All** trên Kaggle có khả năng truy cập site; notebook tự tạo source Parquet cho mẫu cố định, dừng khi gặp challenge/429 hoặc năm lỗi truy cập liên tiếp, xuất ZIP. Khả năng truy cập từ Kaggle chưa được kiểm chứng ở lượt này.

Notebook tạo `holdout_quality_audit.json` và `holdout_review_packet.jsonl`, gồm toàn bộ cờ F3, reply có audio/boilerplate, tác giả cần review, tìm kiếm ngữ cảnh rộng và 50 thread INCLUDE ngẫu nhiên nếu đủ. Quét rộng chỉ chọn mục cần đọc, không tự kết luận quảng bá. Audit kiểm raw hash, DOM locator, admission tác giả và offset/evidence từng cờ; review ngữ nghĩa vẫn cần đọc dữ liệu thật.

Đã compile **16 cell code** và chạy smoke test offline phần giải nén source, dựng Parquet/lịch sử, chọn lại mẫu: khớp đủ **1.000 ID/URL**, đủ **1.086 câu hỏi lịch sử**, không gửi request thật. Không chạy toàn notebook trong kernel hoặc chạy Kaggle ở lượt này.

Sau khi có HTML mới, ưu tiên đọc toàn bộ mixed/audio để tìm biến thể boilerplate F1; đối chiếu qualification và ownership F2; đọc cả thread có cờ và thread không có cờ nhưng khớp tìm kiếm rộng để tìm false positive/false negative F3. Chỉ đề xuất thêm fix khi có raw/DOM/turn cụ thể.

- [Trạng thái và kết luận riêng](../../runs/ask120_holdout_20261020T050502017470Z/holdout_review_summary.json).
- [Audit độc lập của mẫu](../../runs/ask120_holdout_20261020T050502017470Z/sample_independence_audit.json).
- [Mẫu 1.000 URL](../../runs/ask120_holdout_20261020T050502017470Z/sample.jsonl).
- [ZIP bằng chứng và notebook](../../runs/ask120_holdout_20261020T050502017470Z.zip).
