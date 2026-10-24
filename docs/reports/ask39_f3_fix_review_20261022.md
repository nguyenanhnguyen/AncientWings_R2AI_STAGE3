# ask.39.net — kết quả sửa F3 ngày 22/10/2026

Đã bổ sung làm sạch theo biên DOM trong `scripts/ask39.py`, version `ask39-parser-v1-f3`. Replay 50 HTML giữ nguyên toàn bộ text F2, đủ **72 answer + 6 follow-up**; không còn bách khoa/UI trong text candidate. **28/28 test trong notebook pass**, gồm chín test F3 mới.

## Thay đổi

- Chỉ nhận câu hỏi, answer và message nằm ngoài các container phụ đã nhận diện; không lấy các khối có class giống nội dung hội thoại nhưng nằm trong sidebar/bài liên quan.
- Khi đọc title, câu hỏi, answer và follow-up, loại các subtree bách khoa, thuốc/bài gợi ý, quảng cáo, form và nút UI theo tag/class token. Xử lý cả trường hợp block phụ nằm lẫn trong vùng nội dung.
- Loại metadata tác giả/thời gian bị lồng vào body khỏi text body; metadata nguồn vẫn nằm trong trường riêng. Giữ phần text sau subtree bị loại, inline link, line break và nội dung thật đang ẩn bởi CSS.
- Không xóa theo các từ như “咨询”, “举报”, tên thuốc hoặc tên bệnh. Class chưa biết hoặc tên class chỉ chứa chuỗi tương tự không bị loại theo phép tìm chuỗi con.
- Mỗi loại trừ có `dom_exclusions`: locator, lý do/tag/class, preview text và SHA-256 của text/HTML nguồn. Cây nguồn và locator không bị sửa; có thể truy lại bằng raw đã kiểm hash.

Audit đọc nguồn độc lập với parser: thêm kiểm phần gợi ý/thuốc/sidebar; không kết luận sao chép UI chỉ vì từ đó xuất hiện trong lời hỏi–đáp thật. Audit cũng giải mã charset trước khi so nội dung tiếng Trung, tránh gắn sai vai hoặc báo mất text ở HTML UTF-8 không có meta charset.

## Kết quả

| Chỉ số trên 50 HTML | Baseline trafilatura | Candidate F3 |
| --- | ---: | ---: |
| Trang lẫn đoạn bách khoa đã xác nhận | 39 | 0 |
| Trang lẫn marker UI đã xác nhận | 50 | 0 |
| Answer chính giữ đủ text | 69/72 | 72/72 |
| Follow-up giữ đủ text | 0/6 | 6/6 |

- Text hash **50/50 trang khớp F2**: baseline F1/F2 đã sạch trên các HTML này; F3 củng cố biên DOM và ca lẫn block phụ, không cắt thêm nội dung đã khôi phục.
- Có **2.396 subtree ngoài nội dung** được ghi bằng chứng loại trừ; số này gồm script/header/form/ads/UI/sidebar, không phải 2.396 lỗi mới trong text F2.
- Audit candidate không có cờ trên mẫu. Vai follow-up vẫn 3 patient / 3 responder, không có orphan/unknown.

## Test mới nằm trong notebook

Chín test F3 được viết trực tiếp trong phần **“F3 — làm sạch theo biên DOM, giữ lời hỏi–đáp thật”** của `notebooks/check_ask.39.net.ipynb`:

1. Hash text 50 trang khớp F2; mọi locator và HTML hash loại trừ khớp nguồn.
2. Đối chiếu 39 ca bách khoa và 50 ca UI của baseline với candidate.
3. Block phụ lồng vào title, câu hỏi, answer và follow-up được bỏ đúng phần.
4. Câu hỏi/answer/follow-up giả trong sidebar không được nhận thành hội thoại thật.
5. Lời thật chứa chữ giống UI, tên bệnh/thuốc hoặc trùng đoạn bách khoa vẫn được giữ, không bị audit gắn cờ nhầm.
6. Class chưa biết, inline link và message thật ẩn bằng CSS không bị xóa.
7. Form/script/metadata được bỏ và text ngay sau chúng vẫn giữ; header tác giả không mất.
8. Khôi phục paragraph lồng sai dừng trước block gợi ý, không lấy tiếp paragraph phía sau.
9. Audit bắt được việc cố ý chèn lại sidebar, thuốc gợi ý hoặc UI vào output.

Đã thực thi tuần tự code cell bằng IPython local, mode `replay_f3`, lưu output ngay trong notebook. Toàn bộ **10 test F1 + 9 test F2 + 9 test F3 đều pass**; ba test check/audit có sẵn cũng pass. Không tạo file test Python mới cho F3, không gọi lại website. Notebook vẫn được Git bỏ qua.

## Bằng chứng và giới hạn

- Replay cuối: `runs/ask39_f3_replay_20261022T003702786856Z`.
- `summary.json`: kết quả test, số answer/message, thống kê trước/sau.
- `records/`: nội dung có cấu trúc và `dom_exclusions` từng trang.
- `dom_exclusion_summary.json`, `dom_audit.jsonl`, `f2_text_hashes.json`, raw, parser/audit snapshot và manifest/hash phục vụ đối chiếu.
- Parser SHA-256: `afc3532d29ce5ea5ec50afcf1dcaf835e5f24afe2d71edd3609e654299c36e2f`.

Đạt F3 trong phạm vi baseline và các ca biên đã kiểm. Class/template chưa biết chưa được chứng minh sạch; F4 QC/admission, F5 holdout và F6 tích hợp production còn mở. Candidate tiếp tục REVIEW, chưa xuất corpus.
