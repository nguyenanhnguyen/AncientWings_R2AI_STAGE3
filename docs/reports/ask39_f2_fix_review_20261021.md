# ask.39.net — kết quả sửa F2 ngày 21/10/2026

Đã bổ sung follow-up theo từng answer trong `scripts/ask39.py`, version `ask39-parser-v1-f2`. Replay 50 HTML baseline giữ đủ **6/6 message**, đúng text, người nói theo nhãn nguồn, parent answer và thứ tự. Regression F1 tiếp tục giữ đủ **72/72 answer**.

## Cách sửa

- Trích `doc_zw .zw2` làm nội dung message; không lấy textarea, nút gửi hoặc `hfu_box` vào text.
- Gắn message vào container `sele_all` gần nhất chỉ khi container đó đã được nhận diện thành answer. Không gắn orphan sang answer trước đó.
- Nhãn nguồn `追问` → `patient`, `回复` → `responder`; thiếu/nhãn khác hoặc nhiều nhãn giữ `unknown` và có cờ review. Không suy vai từ vị trí chẵn/lẻ hoặc nội dung.
- Giữ message ở cả `answers[].followups[]` và danh sách `followups[]` cấp trang; lưu ID nguồn, locator, parent answer, thứ tự toàn trang/trong answer, text/hash và bằng chứng nhãn/ownership.
- ID message quan sát từ tham số tĩnh của `editInquire` được lưu riêng; không chạy JavaScript nguồn. Thiếu ID dùng locator hash; text trùng không bị gộp, ID nguồn trùng được đánh cờ.
- Render answer chính rồi đến các message thuộc answer đó với nhãn `患者追问`/`回答者补充回答`. Không tự điền tên tác giả hoặc thời gian riêng của message khi nguồn không cung cấp.
- Message rỗng, body không nhận diện, container lồng nhau, parent không rõ hoặc vai không rõ giữ bằng chứng và cờ review.

## Đối chiếu sáu message thực

| Source ID | Parent answer | Message hỏi tiếp | Message trả lời tiếp |
| --- | --- | --- | --- |
| 2216701 | reply_12533991 | 1090569 — patient | 1090757 — responder |
| 2263361 | reply_2029082 | 6744306 — patient | 6744331 — responder |
| 2262579 | reply_2006569 | 6414482 — patient | 6414592 — responder |

Sáu kỳ vọng text/ID/nhãn/parent/thứ tự/locator được đóng băng từ raw trong cell notebook, độc lập với output candidate. Tất cả đều khớp; không có orphan hoặc vai unknown trong 50 trang baseline. Người nói được xác định theo cấu trúc/nhãn website, không phải xác minh danh tính hay chuyên môn người viết.

Audit đã được mở rộng: đọc lại raw và đối chiếu text từng message, parent, vai, thứ tự/coverage và danh sách message nằm trong answer. Các test cố ý sửa sai parent/vai/body/thứ tự hoặc làm mất message trong nested thread đều bị audit phát hiện, kể cả khi text phẳng của trang vẫn còn đủ nội dung.

## Kết quả kiểm thử

| Chỉ số replay 50 trang | Kết quả |
| --- | ---: |
| Answer chính giữ đủ text | 72/72 |
| Follow-up giữ đủ text | 6/6 |
| Vai patient / responder | 3 / 3 |
| Orphan / vai unknown | 0 / 0 |
| Answer chính hoặc follow-up bị thiếu | 0 |
| Cờ audit trong mẫu | 0 |
| Test trong notebook | 19/19 pass |

**Chín test F2 mới nằm trực tiếp trong cell của `notebooks/check_ask.39.net.ipynb`**, không tạo file test Python mới:

1. Sáu message nguồn: text, role, parent, ID, thứ tự và ownership evidence.
2. Nhiều answer và các vai lặp liên tiếp; render đúng ranh giới hội thoại.
3. Nhãn thiếu/không rõ/nhiều nhãn giữ unknown.
4. Orphan không bị gắn sang answer gần trước đó.
5. Message rỗng hoặc thiếu body không bị lấy UI thay thế.
6. Container lồng nhau không sao chép body con sang cha.
7. Text trùng vẫn giữ riêng; source ID trùng được báo lỗi.
8. Answer container không nhận diện không được dùng làm parent giả.
9. Audit bắt sai parent, vai, body, thứ tự và danh sách message trong answer.

Mười test F1 được giữ và cập nhật kỳ vọng follow-up từ pending sang đã trích. Đã thực thi tuần tự các code cell bằng IPython local với mode `replay_f2`, lưu output ngay trong notebook; không gọi lại website. Ba test check/audit có từ trước cũng pass.

## Bằng chứng và phạm vi còn lại

- Replay cuối: `runs/ask39_f2_replay_20261021T165854598329Z`.
- `summary.json`: 50 trang, 72 answer, 6 follow-up và 19 test pass.
- `followup_review.md`: text đầy đủ của sáu message cùng parent và người nói; cũng hiển thị trong output notebook.
- `records/`, `raw/`, `dom_audit.jsonl`, parser/audit snapshots, `followup_expectations.json` và manifest/hash phục vụ đối chiếu.
- Parser SHA-256: `66259b86a5d8de93ad606679c6cf4baf5aa535a65942fa9d570cdeca0f28b048`.
- Follow-up expectations SHA-256: `edfe1f8c9cdd6e6bf9c42940ee6466905f42d4779bce5ef51eeec2895650aac3`.

Đạt tiêu chí F2 trên baseline và các ca biên đã test. Candidate vẫn luôn REVIEW, chưa cho phép xuất corpus; F3–F6, holdout mới và tích hợp production còn mở. Notebook check vẫn nằm trong `.gitignore`.
