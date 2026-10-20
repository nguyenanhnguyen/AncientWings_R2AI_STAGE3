# Review chất lượng 120ask — 20/10/2026

Đây là kết quả review trước sửa. Ba lỗi bên dưới đã được xử lý trong
[bản V3.1](120ask_fixes_20261020.md); số liệu ở báo cáo này giữ nguyên để đối chiếu.

Kết luận: parser V3 tái tạo ổn định kết quả trên mẫu 1.000 HTML đã lưu, phù hợp chạy pilot có lọc. Chưa đủ điều kiện gọi corpus đã duyệt: 144 mục review bắt buộc chưa có nhãn, và có ba lỗi được tái hiện ngoài coverage hiện tại. Đây là đánh giá chất lượng trích xuất và cổng xét nhập, không phải thẩm định y khoa hoặc xác nhận khả năng truy cập live hiện tại.

## Phát hiện theo mức ưu tiên

### 1. [P1] Nhãn lỗi parser đã được người review xác nhận có thể bị bỏ khỏi readiness

Vị trí: `scripts/ask120_gate.py:552`, `scripts/ask120_gate.py:590`.

`build_outputs()` áp dụng nhãn thủ công trước, rồi lấy lại mẫu INCLUDE để dựng `required`. Một thread INCLUDE thông thường được reviewer chuyển EXCLUDE sẽ rời mẫu. Nếu thread đó không thuộc regression, không có source/parser flag và không đại diện reason, nó bị bỏ khỏi `review_rows`. `critical_manual` chỉ đọc `review_rows`, nên bỏ sót ghi chú PARSER_ERROR đã hợp lệ về provenance.

Tái hiện trên run thật: source ID `2926587`, thread `card2:reply3487075`, thêm nhãn EXCLUDE với notes `PARSER_ERROR: source content omitted.` và thời gian review. Sau tổng hợp, dòng có nhãn biến mất khỏi phiếu và readiness vẫn là `READY_FOR_FILTERED_PILOT`, thay vì `NEEDS_PARSER_FIX`. Điều này cũng có thể làm mất blocker khi tiến tới xét duyệt corpus.

Đề xuất: giữ tất cả nhãn đã được xác thực trong audit và kiểm tra lỗi nghiêm trọng trên toàn bộ nhãn hợp lệ; cố định mẫu review ban đầu, thêm mẫu thay thế khi cần thay vì xóa lịch sử review.

### 2. [P2] Resume từ thư mục đầu vào giữ checkpoint cũ khi raw và hash nguồn cùng thay đổi

Vị trí: `scripts/ask120_gate.py:258`.

Khi checkpoint có cùng parser/policy, nhánh resume gọi `safe_raw(reader, old)` rồi `continue`. Nó chỉ chứng minh raw hiện tại khớp record nguồn hiện tại, không so raw hash đó với checkpoint đã parse. Identity của input dạng thư mục chỉ ràng buộc manifest và sample, không bao gồm nội dung từng record/raw.

Tái hiện: replay thư mục có một trang; sửa câu trả lời trong raw và cập nhật `raw_sha256` trong record nguồn, giữ nguyên manifest/sample; replay cùng output. Input mới được chấp nhận nhưng checkpoint vẫn giữ hash và text cũ. Baseline cập nhật trong khi reparsed output vẫn cũ, khiến so sánh trước/sau không còn cùng đầu vào.

Đề xuất: so raw hash, source mapping và metadata ảnh hưởng parsing với checkpoint trước khi skip; nếu thay đổi thì từ chối resume hoặc parse lại theo hợp đồng rõ ràng. ZIP đầu vào được hash toàn archive nên không có cùng đường tái hiện này.

### 3. [P2] Ảnh câu hỏi không được lưu bằng chứng và không tự tạo reason review

Vị trí: `scripts/ask120.py:263`, `scripts/ask120_gate.py:285`; nhánh crawl tương tự ở dòng 408.

Parser chỉ lấy text của question node. Attachment URLs chỉ được lấy cho turn trả lời. `essential_media_missing` của câu hỏi chỉ dựa vào chuỗi `图片涉及用户隐私`, nên `<img src="/lab.jpg">` không kèm chuỗi đó bị bỏ mất mà không có cờ.

Fixture bổ sung có câu hỏi `Please interpret the attached medical image: <img src="/lab.jpg">` và câu trả lời đủ dài được quyết định INCLUDE, reasons rỗng, `essential_media_missing=false`. Corpus text không còn ảnh/bằng chứng liên quan nên có thể thiếu ngữ cảnh quyết định của câu hỏi.

Giới hạn tác động đã đo: cả 18 trang có `#d_msCon img[src]` trong mẫu 1.000 đều là ảnh placeholder riêng tư và đã được flag; 17 trang REVIEW, 1 EXCLUDE. Chưa thấy case ảnh bị lọt trong mẫu này.

Đề xuất: lưu attachment/media provenance của câu hỏi từ DOM, đánh dấu review khi ngữ cảnh có thể phụ thuộc ảnh; thêm coverage cho ảnh thật, placeholder và ảnh trang trí.

## Test và replay

- `.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p '*120*.py' -v`: 28/28 đạt, 13,692 giây. Bao gồm parser, gate, raw integrity, ownership, snapshot, schema, routing và resume hiện có.
- `.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_notebook_*.py' -q`: 198/198 đạt, 159,494 giây; kiểm tra thêm tích hợp notebook và các domain dùng chung pipeline. Hai lượt trùng 12 test parser 120ask, tương ứng 214 test duy nhất.
- Replay mới bằng parser/policy hiện tại trên ZIP gốc 1.000 URL, mock `requests.Session.request` để fail nếu có request ngoài ý muốn. Không crawl live, không upload. Output cũ được giữ nguyên.
- Ba probe bổ sung đều tái hiện được lỗi mô tả trên. Đây là probe review, chưa thêm thành regression test vào bộ test của repo.
- Môi trường không cài pytest; dùng unittest theo README, không thay dependency.

| Chỉ số replay mới | Kết quả |
|---|---:|
| Raw được kiểm hash / parse | 1.000 / 1.000 |
| Raw hoặc parse error | 0 |
| Regression chuẩn | 9 / 9 đạt |
| Trang INCLUDE / INCLUDE_PARTIAL | 680 / 95 |
| Trang REVIEW / EXCLUDE | 94 / 131 |
| Candidate document, ID duy nhất | 775 (77,5% mẫu) |
| Thread INCLUDE / REVIEW / EXCLUDE | 1.260 / 223 / 75 |
| Audio fallback trong candidate | 0 |
| Legacy markup trong candidate | 0 |
| Vi phạm invariant candidate hiện có | 0 |
| Review bắt buộc / đã có nhãn | 144 / 0 |

Kết quả khớp báo cáo replay 18/10/2026. Parser SHA-256: `d46d93e9435bf6e058f1eb80003beefe415368fd2ee1c3dfc996e4a0493bd7c2`. Policy SHA-256: `b1a5b7ddbcac05c0ba8344a01da9dbd54a1fe6066259db76bd632226ae2119bb`.

Điểm tốt: tách vai và lượt hội thoại; giữ provenance/raw hash; lọc cấp thread để giữ partial; không coi audio fallback là câu trả lời; bảo toàn source ID và schema; snapshot notebook khớp source.

Giới hạn chất lượng: 518/1.000 câu hỏi thuộc thập niên 2000, 362 thuộc thập niên 2010, 120 thuộc thập niên 2020. Đây là phân bố của mẫu, chưa chứng minh đại diện toàn domain. Có 99 trang không có answer trong HTML đã tải; các trang này không được bổ sung bằng nội dung suy đoán. Các cờ quảng bá, câu ngắn và metadata là tín hiệu review, không xác nhận đúng/sai y khoa.

## Artifact và cách tái hiện

- Runner/probe: `tmp/review_120ask_20261020.py`.
- Log: `tmp/review_120ask_20261020.log`.
- Run mới: `runs/ask120_review_20261020/` gồm summary, report, candidate JSONL/Parquet, raw, records, regression CSV và phiếu review.
- Audit ảnh câu hỏi: `runs/ask120_review_20261020/question_image_audit.json`.

Runner có dùng thư mục cố định cho probe resume. Khi chạy lại probe từ đầu, dùng thư mục output/probe mới để tránh checkpoint từ lần trước. Nhãn PARSER_ERROR trong probe là dữ liệu thử được tạo để kiểm tra luồng xử lý, không phải kết luận review thủ công về thread thật. Runner đã tổng hợp lại output cuối không dùng nhãn thử; summary cuối giữ `manual_reviewed=0`.

Chỉ thêm báo cáo này; chưa sửa parser/gate hoặc thay snapshot notebook.
