# Plan sửa các phát hiện sau holdout ask.39.net — 22/10/2026

Trạng thái mới nhất: **NEEDS_FIX** sau holdout200 mới loại850: 200 raw hợp lệ, 261 answer + 10 follow-up; frozen candidate 195, REVIEW 5. Review đủ 80 trang, 17 nhóm cấu trúc, mọi lỗi/REVIEW và 20 accepted ngẫu nhiên. Phát hiện 5 lỗi/thiếu coverage, 8 trang pending chính sách/chuyên môn; 13 test mới notebook + 3 helper pass. Code đóng băng giữ nguyên; chưa F6. Xem [review holdout850](../reports/ask39_holdout850_review_20261023.md). Lượt chọn sau phải loại toàn bộ 1.050 ID/URL. Các phần dưới giữ lịch sử.

Cập nhật 22/10/2026: **A đã triển khai V2 và kiểm chứng đạt** — 343 answer có ID nguồn xác minh, 22 follow-up đúng parent, 250/250 text hash không đổi; 63 test notebook pass. Ca 2401990 có hai answer riêng. Xem [báo cáo fix A](../reports/ask39_identity_a_fix_review_20261022.md).

**B đã sửa và replay C đạt:** hai trang 2229930/2252991 chuyển REVIEW theo tổ hợp phương pháp + claim trong lời responder; candidate 244 → 242, REVIEW 6 → 8. Text, định danh và các source flags cũ giữ nguyên. Test mới nằm trong cell notebook, baseline F1–F5/A đóng băng riêng. Xem [báo cáo fix B](../reports/ask39_claim_b_fix_review_20261022.md). Readiness: `FIX_B_PASSED_FRESH_HOLDOUT_PENDING`; D còn mở, chưa đạt F6. Các phần dưới giữ kế hoạch để đối chiếu.

**C đã replay riêng và đối chiếu đầy đủ với F5:** 250 raw kiểm hash, 343 answer + 22 follow-up, 250 text hash không đổi, audit không lỗi. Đúng 3 quyết định đổi: 2401990 REVIEW → accepted; 2229930/2252991 accepted → REVIEW. Đã lưu diff toàn bộ trường parser/gate, mapping 343 answer và 22 parent; không còn thay đổi chưa giải thích. 90 test notebook + 3 helper pass. Xem [báo cáo replay C](../reports/ask39_replay_c_review_20261022.md). Readiness hiện tại: `REPLAY_C_PASSED_FRESH_HOLDOUT_PENDING`; tiếp theo là D.

**D đã hoàn tất:** seed 20261023, 200 URL không overlap với 250 ID/URL cũ; đủ 200 raw kiểm hash, 252 answer + 16 follow-up, không lỗi parser/audit. Gate đóng băng: 194 candidate / 6 REVIEW chức danh. Assistant review phát hiện **5 candidate** cần REVIEW thêm: 4 claim không gây hại/không tăng rủi ro và 1 CTA tư vấn trong answer quảng bá. 100 test notebook + 3 helper pass. Không sửa rule giữa lượt holdout, không tích hợp F6. Xem [báo cáo D](../reports/ask39_holdout_d_review_20261022.md) và [plan xử lý phát hiện mới](ask39_d_findings_fixes_20261022.md). Kết luận mới nhất: **NEEDS_FIX**; các trạng thái pending ở các cập nhật trước là lịch sử.

Ưu tiên: **A — định danh answer → B — claim cần review → C — replay 250 HTML → D — holdout xác nhận mới**. Chưa làm F6 trước khi các kiểm tra này đạt.

## 0. Giữ nguyên bằng chứng F5

- Đóng băng parser/gate/audit F4, 195 candidate, 5 quyết định REVIEW, hai ghi chú review của assistant và toàn bộ raw/hash. Không thay kết quả cũ thành kết quả sau fix.
- Lập fixture cho ca định danh, hai claim và các ca âm trước khi sửa. Mỗi kỳ vọng có ID nguồn, answer/container locator, raw hash, đoạn nguồn và lý do giữ/bỏ khỏi candidate.
- Test mới tiếp tục viết trực tiếp trong cell của `notebooks/check_ask.39.net.ipynb`, không tạo file test Python mới.
- Tách namespace/payload baseline đóng băng và candidate mới trong notebook. Giữ kiểm tra tái hiện F5 cũ bằng module cũ; không để test cũ về `reply_...` hoặc fingerprint vô tình chạy với parser mới rồi đổi kỳ vọng cho pass.

## A / P1 — Tách định danh answer khỏi header người trả lời

**Lỗi gốc:** tại ID **2401990**, hai answer cùng header `reply_41561620` nhưng ID answer nguồn khác nhau: **168259322**, **163288714**. Header này không đủ làm khóa thread.

**Điểm sửa:** `scripts/ask39.py`, `scripts/ask39_audit.py`, `scripts/ask39_gate.py`, `scripts/check_ask39.py`, builder và cell test/report liên quan.

### Hợp đồng định danh mới

| Trường | Cách dùng |
| --- | --- |
| `source_question_id` | Lấy từ URL câu hỏi; đối chiếu ID câu hỏi trong bằng chứng nguồn |
| `source_answer_id` | ID answer từ tham số tĩnh của `showReportModal`, trong đúng container answer |
| `answer_id` | Khóa thread có phạm vi câu hỏi, ví dụ `ask39:_27vnb5:answer:168259322` |
| `reply_dom_id` | Giữ `reply_41561620` như metadata DOM; không dùng làm khóa answer |
| `identity_evidence` | Locator link nguồn/container, ID câu hỏi/answer quan sát được và trạng thái xác minh |
| `parent_answer_id` | Khóa answer mới, nhất quán ở mọi follow-up và danh sách thread |

### Cách triển khai

1. Đọc các link `showReportModal` trong đúng container `sele_all`; chỉ phân tích chuỗi tham số có cấu trúc đã xác nhận, không thực thi JavaScript/eval.
2. Kiểm ID câu hỏi khớp URL và link thuộc đúng answer. Nhiều link cùng xác nhận một ID có thể dùng; nhiều ID khác nhau trong cùng container phải REVIEW.
3. Nếu hai container có cùng ID answer nguồn hoặc ID câu hỏi không khớp, giữ cờ lỗi. Không nối thêm số thứ tự để che xung đột.
4. Thiếu ID nguồn: tạo khóa tạm có phạm vi câu hỏi/raw snapshot/locator để lưu bằng chứng và tránh va chạm; ghi `identity_status=provisional`, tiếp tục REVIEW. Không coi locator là ID ổn định xuyên các lần tải.
5. Gắn follow-up vào object/container trước, rồi dùng khóa answer mới; giữ ID message và thứ tự. Không suy parent từ tên hoặc header người trả lời.
6. Audit tự đọc ID answer nguồn, kiểm khóa mới, uniqueness và parent; bỏ giả định cũ rằng `answer_id` phải bằng `doctor_all/@id`. Không gọi lại hàm định danh của parser làm phép kiểm duy nhất.
7. Version hợp đồng mới: đề xuất parser/extractor V2 và gate V2. Cập nhật mọi chỗ hard-code extractor/version, summary, export và snapshot/hash; không sửa notebook production trong vòng này.

### Nghiệm thu

- Ca **2401990** có hai khóa answer khác nhau, lần lượt gắn với **168259322** và **163288714**; giữ nguyên hai text và hai thời điểm nguồn.
- Không còn `duplicate_answer_id` do dùng chung header ở ca này. Việc xuất vẫn phụ thuộc các QC/source flags khác.
- Có test: cùng tác giả nhiều answer; cùng text nhiều answer; link nằm nhầm container; ID câu hỏi sai; ID answer trùng thật; thiếu/nhiều ID mâu thuẫn; hai answer cùng tác giả đều có follow-up.
- Không trộn thread hoặc đổi vai/thứ tự các message; toàn bộ parent phải trỏ tới đúng answer mới.
- Không mất text: tổng tham chiếu của 250 HTML hiện có là **343 answer + 22 follow-up**. Trường hợp nguồn không xác định được vẫn REVIEW, không ép đạt bằng cách đổi count.

## B / P1 — Bắt claim theo ngữ cảnh, tách khỏi tư vấn thông thường

**Hai ca đích:**

- **2229930 / header cũ `reply_21717536`**: tên phương pháp `靶位定向体液疗法` đi kèm khẳng định chữa từ gốc.
- **2252991 / header cũ `reply_33885607`**: mô tả `定点祛炎` đi kèm khẳng định chặn tiến triển/ít tái phát.

Các header cũ chỉ dùng tra bằng chứng; sau A, fixture cần gắn với ID answer nguồn đã xác minh. Không viết rule theo ID trang hoặc nickname.

**Điểm sửa:** `scripts/ask39_gate.py`, evidence/report và cell test. Giữ nguyên lời nguồn; không xóa câu để biến answer thành accepted.

### Cách triển khai

1. Tạo cờ riêng, chẳng hạn `source_treatment_claim_review`. Chỉ có nghĩa “cần review claim”, không ghi kết luận sai y khoa.
2. Bắt tổ hợp **phương pháp cụ thể + lời khẳng định hiệu quả mạnh** trong cùng câu/đoạn hoặc đoạn liền kề có liên hệ rõ. Khởi đầu bằng các chữ ký phương pháp đã quan sát và nhóm claim có bằng chứng; không mở regex cho mọi “疗法”/“根治”.
3. Chạy rule trên answer chính và follow-up vai `responder`. Câu hỏi hoặc follow-up vai `patient` nhắc/trích claim không tự gán quảng bá cho người trả lời; vai unknown đã bị QC cấu trúc giữ REVIEW.
4. Xử lý phủ định/trích dẫn trong phạm vi câu/cụm liên quan: “không thể chữa khỏi”, khuyến cáo không tin quảng cáo hoặc câu kể lại lời bệnh nhân không tương đương người trả lời đang hứa hiệu quả. Một phủ định ở câu khác cũng không được vô hiệu hóa claim thật.
5. Mỗi cờ lưu rule/version, answer/message ID mới, vai người nói, locator, câu trích và vị trí ký tự, cue phương pháp/claim và ngữ cảnh liên quan. Không chỉ lưu đoạn cắt tùy ý quanh từ khóa.
6. Tiếp tục tách `extraction_status=accepted` khỏi `quality_status=review` do nguồn. Theo policy hiện tại, một answer cần review vẫn giữ cả trang ngoài candidate; chưa mở thêm cơ chế xuất một phần thread trong vòng fix này.

### Nghiệm thu

- Hai trang đích chuyển từ accepted sang REVIEW với evidence đúng answer; không mất hoặc sửa text. Không còn trong candidate Parquet xuất lại.
- Các ca quảng bá/liên hệ đã bắt ở baseline vẫn được giữ cờ phù hợp.
- Negative fixture: liệt kê liệu pháp thông thường; khuyến cáo điều trị có điều kiện; câu phủ định claim; bệnh nhân trích quảng cáo; responder bác bỏ quảng cáo; từ khóa chỉ nằm trong sidebar; vai unknown; tên phương pháp nằm ở câu khác không có claim liên quan.
- Test thực ở đường export: dù record còn nhãn accepted cũ, gate V2 đọc raw và chặn đúng hai trang sau khi đánh giá lại.
- Không dùng tỷ lệ accepted làm mục tiêu, không gọi bộ fixture nhỏ là precision/recall toàn domain.

## C — Replay 250 HTML và giải thích mọi thay đổi

1. Reparse 50 baseline + 200 holdout cũ từ raw đã kiểm hash, tạo run mới. Sau khi dùng để sửa, 200 URL cũ là regression, không còn là holdout độc lập.
2. Xuất bảng ánh xạ `old reply_dom_id → new source_answer_id/answer_id`, theo container. Quan hệ có thể một-nhiều; không ép thành dictionary một-một.
3. Diff text/hash, số khối, metadata, parent follow-up và quyết định gate. Chỉ đổi định danh không được làm text hội thoại thay đổi.
4. Rà riêng ID **2401990**, hai trang claim, toàn bộ ca missing/ambiguous ID, các ca có follow-up và các quyết định khác baseline.
5. Đọc lại candidate Parquet: không có trang REVIEW, không có ID nguồn trùng, đủ provenance; test accepted cũ không vượt được gate mới.
6. Sinh report readiness từ lỗi còn tồn tại, không từ việc tất cả test đều xanh.

**Kỳ vọng định hướng, không phải quota:** ca trùng header có thể rời REVIEW nếu xác minh đủ ID; hai ca claim phải vào REVIEW. Các trang thiếu/chưa nhận diện chức danh vẫn giữ quyết định thận trọng hiện tại.

## D — Holdout xác nhận mới trước F6

- Sau khi A–C đạt, đóng băng parser/gate/audit V2 rồi chọn **200 URL mới**, loại cả ID và URL của toàn bộ **250 URL đã dùng**.
- Seed mới được ghi trong manifest, tiếp tục phân tầng numeric/underscore; lưu số dân số/mẫu mỗi tầng và không suy tỷ lệ toàn domain từ mẫu phân bổ đều.
- Audit toàn bộ; review tất cả lỗi/REVIEW, đại diện template mới và ít nhất 20 accepted ngẫu nhiên. Giữ raw, hash, code fingerprint và evidence quyết định.
- Chỉ báo `READY_FOR_LIMITED_CRAWL` khi không còn lỗi định danh/ownership/mất nội dung đã biết và không còn phát hiện source claim chưa được xử lý trong mẫu review. Các trang unknown được chặn đúng policy có thể tiếp tục REVIEW; không yêu cầu 100% accepted.
- Nếu tìm lỗi mới: giữ nguyên kết quả lượt xác nhận, đưa ca vào regression và xác nhận lại bằng mẫu mới sau khi sửa. Không đổi rule ngay trong một lượt holdout đang chạy.

## Ngoài phạm vi bắt buộc của đợt này

Ba ca `助理医师` và một trang header trống từ F5 tiếp tục REVIEW. Có thể chuẩn hóa biến thể chức danh thành một thay đổi policy riêng với bằng chứng/test; không tự mở allowlist để tăng số candidate trong đợt sửa định danh và claim.

**Đầu ra cần có:** parser/gate/audit V2, cell test mới và output trong notebook check, báo cáo replay 250 HTML, candidate/decisions mới, sau đó báo cáo holdout xác nhận mới. Chưa thực hiện các bước này trong lượt lập plan.
## Cập nhật sau fix E và xác nhận mới

Năm ca holdout D đã được xử lý và replay 450 raw đạt (595 answer + 38 follow-up không đổi). Lượt xác nhận tiếp theo đã thử 200 URL mới, nhận 199 raw, còn hai phát hiện mới cần sửa/triage nên readiness vẫn **NEEDS_FIX**. Lỗi DNS treo đã có timeout và test trong notebook. Xem [báo cáo xác nhận E](../reports/ask39_e_confirmation_review_20261022.md); chưa tích hợp F6.

Đã sửa tiếp bước 1: khôi phục answer 2203985 từ `p#content…` trong đúng container. Replay 649 raw giữ đủ 833 answer + 50 follow-up, chỉ trang này đổi text và quyết định QC. Xem [review recovery](../reports/ask39_content_recovery_review_20261022.md). Bước 2 về claim 2214666 còn mở; không thay đổi kết quả holdout đóng băng.

Đã hoàn thành bước 2: 2214666 chuyển REVIEW, không đổi text/ID/thread của 649 record; 21 test mới ở notebook pass. Candidate 625 → 624, chỉ một quyết định quality thay đổi; xem [review claim tốt nhất](../reports/ask39_superlative_review_20261022.md). Không sửa ngược kết quả holdout cũ và chưa tích hợp F6.

Đã hoàn thành bước 3: trích xuất lại từ 649 raw và đối chiếu từng field qua ba mốc. So trước hai fix có một trang đổi text (2203985), hai quyết định QC đổi ngược chiều (2203985 và 2214666), không đổi ID/parent. So bước 2 không có drift policy hay trích xuất. Mapping và toàn bộ leaf diff/meta được lưu; 10 test mới ở notebook + 3 helper pass. Xem [review replay649](../reports/ask39_replay649_review_20261022.md).

Đã hoàn thành bước 4: 2458259 trả HTTP 200 bằng Requests trong 1,045 giây, thu 1 answer có ID nguồn verified và 0 follow-up; gate/audit accepted. Lưu supplement riêng, không đổi mẫu hay sửa ngược holdout; số URL đã chọn vẫn 650, số raw hợp lệ tăng 649 → 650. 8 test mới ở notebook + 3 helper pass; [review retry2458259](../reports/ask39_transport2458259_review_20261022.md). Tiếp theo kiểm 200 URL mới, loại đủ 650 URL/ID cũ trước F6.

