# Review kết quả ids_2583_12583

Đối chiếu commit `8280add29aca4c710db55c09fd3279e39b3ff920`, ZIP diagnostics và log Kaggle do người dùng cung cấp. Review ngày 04/10/2026. Không sửa crawler hoặc notebook, không truy cập lại URL nguồn.

## Kết luận

Pipeline hoàn tất, có checkpoint và xuất corpus thành công. Tuy nhiên, 91,71% là tỷ lệ **tự động chấp nhận**, không phải tỷ lệ trích xuất đúng. Có bằng chứng trực tiếp về metadata ngày đăng sai và nội dung liên quan lẫn trong tài liệu accepted. Nên giữ output làm baseline, sửa parser và phục hồi nhóm lỗi trước khi chạy diện rộng.

## Kết quả đã đối chiếu

| Chỉ số | Kết quả |
| --- | ---: |
| ID chọn, bao gồm cả hai đầu | 2583–12583 |
| ID duy nhất / hoàn tất | 10.001 / 10.001 |
| Pending | 0 |
| HTTP 200 / extracted | 9.196 (91,95%) |
| Accepted | 9.172 (91,71% số URL chọn) |
| Review / rejected | 21 / 3 |
| HTTP 500 cuối cùng | 805 (8,05%) |
| Thời gian crawl | 20.977,799 giây, khoảng 5 giờ 49 phút 38 giây |
| Tốc độ | 28,605 URL/phút |

`complete=true` có nghĩa mọi ID đã có checkpoint, bao gồm checkpoint lỗi. Log ghi export 9.172 dòng, giữ ID int64, kiểm tra round trip Parquet/JSONL thành công. Metadata audit ghi mapping ID/URL và hash đã qua kiểm tra. Tôi xác minh độc lập hash raw và text của cả 10 mẫu trong ZIP; không có full corpus/raw để kiểm chứng lại toàn bộ kết luận audit/export.

| Domain | Chọn | HTTP 200 | Accepted | Review | Rejected | HTTP 500 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bachmai.gov.vn | 784 | 784 | 764 | 17 | 3 | 0 |
| baoangiang.com.vn | 9.217 | 8.412 | 8.408 | 4 | 0 | 805 |

Crawler, auditor và exporter trong ZIP giống source tại commit sau khi chuẩn hóa xuống dòng CRLF/LF. ZIP còn có diagnostics và logging bổ sung; commit này chưa chứa module diagnostics. Vì vậy có thể đối chiếu logic crawl với commit, nhưng không nên khẳng định notebook thực thi giống nguyên bản commit từng byte. Workspace hiện có các thay đổi chưa commit; review dùng snapshot và source của commit, không dựa vào các thay đổi đó.

## Phát hiện ưu tiên

### 1. Ngày đăng sai trong cả 9 mẫu có metadata ngày

Tất cả 9 mẫu có `published_at` đều nhận `2026-10-02`, trong khi `publishDate` của chính bài viết trong HTML khác ngày đó. Ví dụ:

| ID | Nhãn | published_at xuất ra | publishDate trong HTML |
| --- | --- | --- | --- |
| 2583 | accepted | 2026-10-02 | 2018-11-22 |
| 2584 | accepted | 2026-10-02 | 2017-09-01 |
| 2587 | accepted | 2026-10-02 | 2009-03-19 |
| 2608 | review | 2026-10-02 | 2023-07-15 |
| 2819 | review | 2026-10-02 | 2025-01-27 |

HTML của ID 2587 có ngày 02/10/2026 trong khu vực bài cùng chuyên mục. Hàm `extract()` lấy `published_at` từ metadata trafilatura (dòng 386–390), sau đó thay body bằng DOM riêng cho Bạch Mai (395–404) nhưng giữ metadata ngày cũ. Bằng chứng phù hợp với việc bộ trích metadata lấy nhầm ngày từ bài liên quan. Chưa đo được phạm vi toàn bộ 784 bài vì ZIP chỉ có 10 mẫu.

Khuyến nghị: lấy ngày từ dữ liệu bài hiện tại hoặc phần DOM dành riêng cho bài, kiểm tra identity bài trước khi dùng `publishDate`; nếu không xác định được thì để null. Dùng raw cũ để reprocess, không cần tải lại các bài HTTP 200 chỉ để sửa parser.

### 2. Accepted vẫn chứa nội dung bài liên quan

ID 2583 được accepted, không có quality_flags, nhưng text chứa hai mục `TIN LIÊN QUAN` và các tiêu đề “Ngăn ngừa ung thư từ phòng ngủ”, “Năm 2018 Việt Nam có hơn 164.000 người mắc ung thư”. Đây là bằng chứng trực tiếp rằng chọn toàn bộ `div.content-editor-post` chưa đủ để làm sạch article body.

`dom_text()` loại script/style/iframe và một số tag, nhưng chưa nhận diện widget liên quan. Quality gate chủ yếu dựa độ dài, tỷ lệ ký tự, dòng lặp và vài marker; nó không kiểm tra đúng ngày hay độ sạch của widget này. Giữ captions cần thiết, bỏ widget theo cấu trúc DOM đã xác minh; không xóa tùy tiện mọi hyperlink hoặc mọi câu có từ khóa. Chưa thể suy ra tỷ lệ ô nhiễm trên 9.172 tài liệu từ 5 mẫu accepted cùng một domain.

### 3. 805 lỗi HTTP 500 có dấu hiệu sự cố truy cập theo thời gian

Toàn bộ 805 lỗi cuối cùng thuộc Báo An Giang, mỗi ID được thử 3 lần; tổng cộng riêng nhóm này là 2.415 request. Cả 805 raw có cùng SHA-256 `4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865`.

Các checkpoint lỗi bắt đầu/kết thúc trong 01:04:58–02:01:12 ngày 04/10/2026, giờ Việt Nam. Request HTTP 200 đầu tiên của Báo An Giang được ghi từ 02:01:12 cùng ngày. Một số ID như 7198 và 10140 đổi từ 500 sang 200 ngay khi retry; sau đó còn một lỗi 500 tạm thời ở ID 11094 nhưng retry thành công.

Dấu hiệu nghiêng về một trang lỗi chung trong một đợt sự cố truy cập, thay vì 805 bài hỏng riêng lẻ. ZIP không chứa raw mẫu HTTP 500 nên chưa thể phân biệt backend/CDN/proxy hoặc chặn crawler. Không có bằng chứng để kết luận chắc chắn IP Kaggle bị block.

Resume hiện tại bỏ qua mọi checkpoint đã có (`crawl()`, dòng 509–520), nên chạy lại cell crawl sẽ không cứu 805 ID này. Nên tạo recovery run riêng; cơ chế `prepare --reuse-run` ở source commit cho phép reuse/reprocess raw HTTP 2xx và để các ID lỗi được crawl lại. Notebook tại commit chưa nối tùy chọn này vào luồng cấu hình. Giữ nguyên run gốc, không xóa hàng loạt checkpoint. Bổ sung cooldown theo domain khi 5xx tăng liên tục để tránh tiêu hết retry trong cùng đợt lỗi; tăng số attempts đơn thuần chưa giải quyết vấn đề.

## Các điểm còn lại

- 24 tài liệu review/rejected nằm trong `review_rejected.csv`. Bạch Mai có các bài chỉ chứa ảnh/tệp hoặc phần giới thiệu. ID 2607/2608 chỉ xuất được tiêu đề; ID 2681 rỗng và bị rejected. Các cờ này đang ngăn một số nội dung thiếu lọt vào corpus.
- `low_letter_ratio` ở các bản tin H1N1 chứa nhiều số liệu có thể là cảnh báo nhầm; cần xem bảng gốc thay vì tự động loại nội dung số. Audit ghi 115 bài có bảng nguồn, chưa chứng minh bảng đã được giữ đầy đủ.
- Audit ghi 2/377 bài không giữ đủ intro. ZIP thiếu `audit_cases.jsonl`, nên chưa xác định được ID của hai trường hợp này. `flagged.csv` dựa flags của records và không bảo đảm chứa flags mới từ audit.
- 21 nhóm text trùng trong accepted gồm 44 ID, tương ứng 23 bản vượt quá một bản mỗi nhóm; có 9.149 text hash duy nhất. Giữ mapping ID gốc là hợp lý; cân nhắc gom nhóm khi indexing hoặc chia train/eval để tránh tăng trọng số nội dung trùng.
- Chỉ 2 hostname được crawl; 97 hosts trong log prepare là số hostname của nguồn đầy đủ. Báo An Giang chiếm 92,16% URL chọn. Đây là một khoảng ID, không đại diện cho toàn corpus 4.394.718 URL, các domain tiếng Trung hay các parser khác.
- `human_review_completed=0`. Gói diagnostics lấy 5 flagged đầu và 5 bản ghi còn lại đầu; cả 10 đều là Bạch Mai, không có mẫu Báo An Giang hoặc raw HTTP 500. Cần mẫu phân tầng theo domain/trạng thái/độ dài, và kèm audit_cases trong diagnostics để review được tốt hơn.
- Pip báo xung đột với các package có sẵn; log không cho thấy chúng làm pipeline thất bại. Debugger và nbconvert SyntaxWarning cũng không phải nguyên nhân 805 lỗi HTTP 500. Có thể pin môi trường tương thích cho lần chạy sau để cải thiện khả năng tái lập.

## Thứ tự đề xuất

1. Sửa metadata ngày và loại widget liên quan; reprocess raw HTTP 200 vào run mới.
2. Chạy recovery cho 805 ID lỗi, giữ provenance và checkpoint của run gốc.
3. Đọc thủ công mẫu accepted phân tầng trên cả hai domain; xử lý 24 review/rejected và 2 intro audit cases trước khi chốt corpus.
4. Thử mẫu đa domain trước khi chạy diện rộng. Không lấy 91,71% làm ước lượng tỷ lệ thành công toàn corpus.

## Bằng chứng kèm theo

- `retry_http_500.csv`: đủ 805 ID/URL và metadata lỗi, trích nguyên từ records.csv.
- `review_rejected.csv`: đủ 24 bản ghi cần kiểm tra nội dung.
- `sample_evidence.json`: ngày từ metadata/HTML và kết quả hash của 10 mẫu.
- Nguồn gốc: `summary.json`, `records.csv`, `requests.csv`, `samples/records/*`, `samples/raw/*`, `code/*`, `metadata/*`, `logs/invocations.jsonl` trong ZIP và log Kaggle đính kèm.
