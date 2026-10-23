# ask.39.net — bước 1: loại UI khỏi follow-up theo DOM (23/10/2026)

**Đã sửa ca 2211175. Readiness tổng thể vẫn NEEDS_FIX** vì còn 6 finding đã xác minh và 3 ca policy/chuyên môn pending của holdout trước. Chưa tích hợp F6 hoặc xuất production.

## Thay đổi

`scripts/ask39.py` loại subtree có **tag `i`, class token `hfu`, nằm trong trường `zw2`**. Đây là nút trả lời của trang, kể cả khi CSS đổi trạng thái hiển thị. Không xóa chuỗi “回复”, không loại mọi node ẩn, không áp dụng class `hfu` trên toàn trang. `drop_tree()` giữ tail sau nút. Parser lưu locator và hash node bị loại trong `dom_exclusions`, lý do `followup_reply_control`.

`source_text` vẫn giữ nội dung nguồn gồm nút UI để truy vết; `text` và hash của message chỉ chứa hội thoại thật. ID nguồn, role, locator, parent, thứ tự và answer không đổi.

`scripts/ask39_audit.py` tự kiểm ranh giới node từ raw, không gọi parser. Audit mới phát hiện `followup_message_text_mismatch` khi kiểm record cũ còn nút UI; record đã sửa không có flag này. Không dùng danh sách từ “回复” để bắt contamination, vì từ đó có thể là nội dung thật.

Parser version: `ask39-parser-v2-followup-ui`. Gate version: `ask39-gate-v4-followup-ui`, yêu cầu đúng parser mới; không thay rule claim, chức danh hoặc eligibility. Record parser cũ cần replay, không tự nhận tương thích với ranh giới text mới.

Builder notebook giữ cell snapshot lịch sử riêng cho các section cũ. Section bản sửa khôi phục payload hiện tại; kết quả holdout cũ vẫn tái hiện đúng, không thay expected để che lỗi. Notebook vẫn gitignore.

## Kết quả ca thật

URL: `https://ask.39.net/question/20576256.html`.

| Trường | Kết quả |
| --- | --- |
| Corpus ID | 2211175 |
| Answer parent | `ask39:20576256:answer:51343768` |
| Message | `followup-454900` |
| Speaker / order / thread_order | patient / 1 / 1 |
| Text mới | 那请问这两样病毒在唇彩中能存活吗？如果是有血液的话 |
| Text bỏ đi | Chỉ hậu tố xuống dòng + nút 回复 |
| Source text, question, answer | Giữ nguyên |
| QC sau replay | accepted; không có parser/audit flag |
| Raw SHA-256 | `f8eb1fe6bd4cfa655d43370b8b5d78e70dfe1e3becb259b84a57bb98322cebbb` |

## Kiểm thử và hồi quy

**Toàn bộ notebook offline: 220 test pass**, gồm **14 test mới** (10 tập trung + 4 replay), cùng **3 helper test hiện có pass**. Test mới nằm trực tiếp trong cell tag `ask39-fix-followup-ui` của [notebook check](../../notebooks/check_ask.39.net.ipynb); không tạo file unit test Python mới.

Test bao phủ ca raw thật, exact text, source evidence và node hash; từ “回复” trong câu thật; tail sau control; class nhiều token; control lồng/hiển thị; class gần giống, tag khác và node ngoài follow-up; 6 message patient/responder xen kẽ với ID/parent/thứ tự; audit từ chối record nhiễm UI; gate từ chối parser cũ.

Replay **200 raw của holdout gần nhất**, không gửi request mới: chỉ **2211175** đổi rendered text/hash do bỏ UI. Giữ đủ **269 answer + 21 follow-up**; mọi question, answer ID, message ID, parent, role, thứ tự và nội dung answer giữ nguyên. QC/claim evidence/source flags giữ nguyên: **194 candidate-eligible, 6 REVIEW**. Đây là số eligibility khi replay; không tạo candidate parquet mới trong bước sửa này. Các finding sản phẩm/thiết bị và `span.pingjia` vẫn mở.

Chưa gọi đây là replay toàn bộ 850 raw hoặc holdout xác nhận bản mới. Hai bước đó vẫn nằm sau các fix tiếp theo trong plan. Hash các artifact lịch sử được theo dõi vẫn giữ nguyên.

## Artifact và bước kế tiếp

Run: `runs/ask39_followup_ui_fix_20261022T195626348656Z`.

- `case2211175.json`, `2211175.before.json`, `2211175.original.html.gz`: trước/sau và raw gốc.
- `text_diff.json`, `replay200.json`, `summary.json`: mọi thay đổi text và quyết định replay.
- `manifest.json`, `code/`, `verification.json`: code/hash, không network và kết quả test.

Tiếp theo: **tách `span.pingjia` khỏi lời responder** ở 2205416/2207135/2207389, giữ metadata đánh giá và provenance; sau đó xử lý 3 claim lọt gate. Không coi việc sửa UI này là hoàn thành các finding khác.
