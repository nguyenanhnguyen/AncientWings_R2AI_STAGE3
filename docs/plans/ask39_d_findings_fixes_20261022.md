# ask.39.net — xử lý các phát hiện sau holdout D

Trạng thái mới nhất: **NEEDS_FIX** sau holdout200 mới loại850: 200 raw hợp lệ, 261 answer + 10 follow-up; frozen candidate 195, REVIEW 5. Review đủ 80 trang, 17 nhóm cấu trúc, mọi lỗi/REVIEW và 20 accepted ngẫu nhiên. Phát hiện 5 lỗi/thiếu coverage, 8 trang pending chính sách/chuyên môn; 13 test mới notebook + 3 helper pass. Code đóng băng giữ nguyên; chưa F6. Xem [review holdout850](../reports/ask39_holdout850_review_20261023.md). Lượt chọn sau phải loại toàn bộ 1.050 ID/URL. Các phần dưới giữ lịch sử.

| Nhóm | ID cần chuyển REVIEW | Bằng chứng ngắn |
| --- | --- | --- |
| An toàn tuyệt đối | 2138096 | Laser không tổn thương mô lành xung quanh |
| An toàn tuyệt đối | 2173132 | Thuốc cụ thể phối hợp chống đông không tăng rủi ro chảy máu |
| An toàn/hiệu quả chắc chắn | 2213438 | Phẫu thuật: hiệu quả chắc chắn, không ảnh hưởng sinh hoạt tình dục |
| Contact/promotion | 2223535 | Quảng bá điều trị, claim phục hồi gene/tế bào và mời click tư vấn trực tuyến |
| An toàn tuyệt đối | 2402453 | Xạ trị không tổn thương mô lành xung quanh |

Các ID trên là ID corpus; answer ID nguồn, locator, raw hash, quote và offset nằm trong `d_assistant_review.json` của artifact D. Giữ candidate/decisions D nguyên trạng làm bằng chứng lỗi; không sửa kết quả holdout thành accepted/review sau fix.

1. **Thêm rule claim an toàn theo ngữ cảnh/người nói.** Xét trong từng answer hoặc follow-up responder, gắn phương pháp/thuốc với khẳng định không gây hại hoặc không tăng rủi ro. `不/不会` trong lời bảo đảm không gây hại không được hiểu đơn giản là phủ định claim. Lưu rule version, câu nguồn, method/claim span, answer/message ID và locator.
2. **Phân biệt các ca âm.** Không bắt câu hỏi/lời bệnh nhân, lời thuật lại hoặc bác bỏ như “không thể bảo đảm không có tác dụng phụ”; không bắt câu mô tả giảm rủi ro có điều kiện hoặc nhắc tên phương pháp đơn thuần. Kiểm ranh giới câu, đoạn và message; không để một phủ định không liên quan hủy claim thật.
3. **Mở rộng CTA/contact trong lời responder.** Bắt lời mời click tư vấn trực tuyến gắn với quảng bá/điều trị như ca 2223535, không chỉ click tên/avatar. Giữ text thật để REVIEW; không xóa CTA trong answer nhằm làm gate pass. Ca 2444995 về giáo dục một-một là ca âm, không phải lời mời tư vấn.
4. **Test và replay 450 HTML.** Test mới tiếp tục ở cell của `notebooks/check_ask.39.net.ipynb`, không tạo file test Python mới. Tách payload D đóng băng khỏi candidate mới để giữ kiểm tra tái hiện lỗi cũ. Đối chiếu toàn bộ text, định danh, vai/parent và quyết định với baseline đóng băng; tham chiếu raw hiện có là **595 answer + 38 follow-up**. Cả 5 trang phải REVIEW sau sửa; giải thích mọi thay đổi khác, không mở allowlist chức danh trong cùng bước này.
5. **Xác nhận lại bằng holdout mới.** Sau sửa và replay đạt, đóng băng code rồi chọn 200 URL khác, loại toàn bộ **450 ID và URL** đã dùng. Review toàn bộ REVIEW/error, đại diện template và ít nhất 20 accepted ngẫu nhiên. Chỉ cân nhắc F6 khi không còn phát hiện chưa xử lý ở lượt xác nhận mới.

Review ở đây đánh giá tính toàn vẹn trích xuất và tín hiệu nguồn cần review; không gắn nhãn xác thực lâm sàng cho mọi tư vấn y khoa của website.

## Cập nhật sau thực hiện E

Đã hoàn thành sửa năm ca và replay 450 raw: giữ nguyên 595 answer + 38 follow-up, đúng năm trang chuyển REVIEW, candidate 436 → 431. Xem [review fix E](../reports/ask39_e_five_findings_fix_review_20261022.md).

Đã thử đủ 200 URL mới, loại 450 URL cũ, thu 199 raw; đọc đủ 73 trang bắt buộc và tổng cộng 79 trang. Sửa lỗi DNS treo 42 phút bằng giới hạn chờ riêng 5 giây; test mới vẫn ở notebook. Readiness **NEEDS_FIX** vì còn hai phát hiện mới và một URL chưa nhận được raw. Chi tiết và hướng sửa tiếp ở [review xác nhận](../reports/ask39_e_confirmation_review_20261022.md). Giữ nguyên dữ liệu holdout và chưa tích hợp F6.

**Bước recovery đã hoàn thành:** ca 2203985 lấy đủ answer thứ ba từ `p#content…` ngay sau `sele_txt` rỗng, trong đúng container. Replay 649 raw có đủ 833 answer + 50 follow-up; chỉ trang này đổi text và REVIEW → accepted. 16 test mới nằm trong notebook. Xem [review recovery](../reports/ask39_content_recovery_review_20261022.md). Còn bước 2 về claim 2214666 và URL lỗi mạng 2458259; readiness tổng thể vẫn NEEDS_FIX.

**Bước 2 đã hoàn thành:** ca 2214666 chuyển REVIEW theo tổ hợp phương pháp đặc thù + claim tốt nhất trong lời responder. 21 test mới ở notebook và replay 649 raw đạt: giữ nguyên toàn bộ record trích xuất, chỉ ca này đổi quality; candidate 625 → 624. Parser/audit và các source flag cũ giữ nguyên. Xem [review bước 2](../reports/ask39_superlative_review_20261022.md). Tiếp theo thử lại riêng URL lỗi transport và kiểm 200 URL mới, loại toàn bộ 650 ID/URL đã chọn; chưa tích hợp F6.

**Bước 3 đã hoàn thành:** fresh reparse 649 raw, map đầy đủ 833 answer + 50 follow-up. So trước hai fix: chỉ 2203985 đổi text, không đổi ID/parent; QC đổi đúng 2203985 REVIEW → accepted và 2214666 accepted → REVIEW. So sau bước 2: không có drift ở gate fresh replay. Mọi metadata audit echo/version được giữ và giải thích riêng; không còn diff chưa giải thích. 10 test replay mới + 3 helper pass; [báo cáo bước 3](../reports/ask39_replay649_review_20261022.md).

**Bước 4 đã hoàn thành:** retry đúng 2458259 bằng Requests một lần, HTTP 200 trong 1,045 giây; không cần browser. Thu thêm 1 answer, 0 follow-up, hash/ID/DOM audit/gate đạt, một candidate supplement local. Mẫu 200 URL, 450 URL loại trừ và artifact lịch sử giữ nguyên hash; inventory có đủ 650 raw cho 650 URL đã chọn. 8 test notebook mới + 3 helper pass; [báo cáo bước 4](../reports/ask39_transport2458259_review_20261022.md). Chưa ghép lại thành replay 650 mới; bước tiếp là holdout 200 URL khác, loại toàn bộ 650 ID/URL cũ.
