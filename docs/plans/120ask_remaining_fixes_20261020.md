# Kế hoạch sửa các lỗi 120ask còn lại — 20/10/2026

Trạng thái: kế hoạch triển khai; tài liệu này không thay đổi parser, policy hoặc candidate.

Cập nhật cùng ngày: **F1 đã triển khai và kiểm chứng đạt**; xem [báo cáo F1](../reports/120ask_f1_fix_review_20261020.md).
Replay thực tế còn 772 candidate, gồm tác động chuyển câu trả lời quá ngắn sau lời chúc sang REVIEW. F2–F5 còn mở; các phần dưới giữ nội dung kế hoạch ban đầu để đối chiếu.

Cập nhật tiếp: **F2 đã triển khai V4 và kiểm chứng đạt**, 325 thread chuyển REVIEW, candidate 772 → 651;
xem [báo cáo F2](../reports/120ask_f2_fix_review_20261020.md). F3–F5 còn mở. Các mốc F1/F2 phía trên ghi theo từng lần triển khai; nội dung kế hoạch dưới đây được giữ để đối chiếu.

Cập nhật tiếp: **F3 đã sửa và kiểm chứng đạt**, gate v3.1, 20/20 ca HTML thực; candidate 651 → 657 sau khi chặn thêm 10 thread và gỡ hold 18 thread.
Xem [báo cáo F3](../reports/120ask_f3_fix_review_20261020.md). Còn F5 → F4 theo thứ tự phụ thuộc trong plan.

Cập nhật 23/10/2026: **F5 đã sửa và kiểm chứng trên 1.000 raw cũ**: đủ 31 trang BR>
trong baseline ban đầu, toàn bộ 50 question có BR> và footer 1404664 được chuẩn hóa
có raw/actions/QC; candidate giữ 657. Xem [báo cáo F5](../reports/120ask_f5_fix_review_20261023.md).
**F4 còn mở**. Các mốc lịch sử và tiêu chí bên dưới giữ lại để đối chiếu.

Cập nhật tiếp 23/10/2026: **F4 đã sửa và kiểm chứng trong phạm vi 1.000 raw cũ**,
parser v4.2/gate v3.3. Kiểm title/body sau F5, giữ nguyên nguồn và câu ngắn có chủ đề;
title-only, thiếu vấn đề hoặc tham chiếu chưa rõ chuyển REVIEW. 52/52 fixture thực,
đủ 16 câu ngắn baseline và 106/106 test 120ask đạt. 14 thread INCLUDE → REVIEW,
candidate 657 → 644. Xem [báo cáo F4](../reports/120ask_f4_fix_review_20261023.md).
Các ca F1–F5 đã xác nhận đạt kiểm tra hồi quy trên tập raw này. Kiểm chứng domain
trên mẫu mới và các mục review con người vẫn là công việc riêng; chưa có nhãn người thật.

Rà bổ sung cuối ngày 23/10/2026: **vẫn cần sửa parser/gate**. Audit lại 1.000 raw và
đọc thêm 50 trang đầy đủ hỏi–đáp xác nhận 15 thread ở 15 trang INCLUDE còn vấn đề:
F3 có 7 biến thể quảng bá/CTA/claim chưa bị giữ, F1 có 6 boilerplate (một ca làm
nội dung 15 ký tự vượt ngưỡng), F4 có 1 yêu cầu đọc báo cáo thiếu dữ liệu, và F6 mới
có 1 answer lệch chủ đề. Thêm 2 trang lặp nội dung nguồn. Xem
[báo cáo rà sau F4](../reports/120ask_postfix_recheck_20261023.md).
Các mốc “đạt” trước đó chỉ áp dụng tập ca đã kiểm, không đóng lỗi trên toàn domain.

## Cơ sở và mục tiêu

Baseline là run `ask120_review_20261020T013753043042Z`: replay 1.000 HTML, 775 candidate document, 1.260 thread INCLUDE, 223 REVIEW, 75 EXCLUDE. Audit artifact không có lỗi nhưng AI review kết luận **NEEDS_PARSER_FIX**. Chi tiết bằng chứng tại [báo cáo run mới](../reports/120ask_new_run_review_20261020.md).

Mục tiêu vòng sửa: xử lý F1–F5 bằng rule có bằng chứng, giữ provenance, và giải thích được mọi thay đổi quyết định ở cấp thread. Số candidate giữ lại không phải chỉ tiêu tối ưu; không ép kết quả quay về 775 document.

Hai blocker P1 là F1 và F2. Thứ tự triển khai đề xuất: **F1 → F2 → F3 → F5 → F4 → kiểm chứng tích hợp**. F5 đứng trước F4 để bộ kiểm ngữ cảnh nhận câu hỏi đã chuẩn hóa.

## 0. Đóng băng bằng chứng và kỳ vọng trước khi sửa

- Giữ nguyên run baseline và baseline V3 đóng băng trong thí nghiệm hiện có. So sánh vòng sửa này trực tiếp với kết quả V3.1; không thay baseline V3 bằng source mới.
- Bổ sung fixture HTML thực từ raw đã kiểm SHA-256: toàn bộ 9 mixed reply, các header nghề nghiệp, 9 tín hiệu quảng bá/liên hệ, hai câu hỏi thiếu ngữ cảnh, các câu hỏi ngắn hợp lệ và mẫu nhiễu câu hỏi.
- Mỗi kỳ vọng ghi source ID, thread/reply ID, DOM locator và bằng chứng nguồn. Phân biệt assertion trích xuất với ghi chú AI; không tạo nhãn thẩm định y khoa hoặc điền nhãn con người.
- Fixture phải kiểm quyết định, phần text giữ/bỏ và provenance; không chỉ kiểm tên hàm hay output snapshot.

## 1. F1 / P1 — Loại lời nhắc thao tác khỏi text câu trả lời

**Điểm sửa:** `scripts/ask120.py` — chuẩn hóa reply và `classify_reply_media()`; `scripts/ask120_gate.py` — kiểm main answer/độ dài.

**Cách sửa:**

1. Nhận diện các đoạn template đã xác nhận: yêu cầu bấm chấp nhận câu trả lời, lời nhắc hỗ trợ người trả lời, dẫn sang tư vấn trực tuyến. Dùng chữ ký/ranh giới đoạn cụ thể, không xóa mọi câu có từ “咨询” hoặc “采纳”.
2. Bỏ đúng đoạn boilerplate; lưu text gốc, đoạn bị bỏ, rule ID và normalization actions. Giữ nội dung thực nếu nằm cùng reply.
3. Tính text có nội dung sau khi bỏ nhãn, lời chúc và boilerplate có bằng chứng. Phân loại media từ text cuối cùng, kể cả sau bước bỏ tail.
4. Rỗng + có audio → audio-only, EXCLUDE khỏi corpus chữ; rỗng không audio → NO_TEXT_MAIN_ANSWER; còn text dưới ngưỡng → REVIEW. Áp quyết định từng thread, giữ thread tốt cùng trang.

**Nghiệm thu:**

- Sáu reply lỗi tại `1025409`, `1029798`, `1031179`, `1053679`, `1087866`, `1404664` không còn INCLUDE như text answer.
- Mixed thật `1159296` giữ phần trả lời đầy đủ; `1173870` chuyển REVIEW nếu chỉ còn nội dung rất ngắn; `1199818` tiếp tục được chặn vì quá ngắn.
- Có ca text thật + lời nhắc, text-only + lời nhắc, audio-only và chữ “audio” trong nội dung nhưng không có media.
- Khi chỉ áp riêng F1, tác động kỳ vọng của sáu thread đã xác nhận là 775 → 773 document. Đây là mốc kiểm chẩn đoán, không phải số đích của toàn vòng sửa.

## 2. F2 / P1 — Tách vai hội thoại khỏi nghề nghiệp tác giả

**Điểm sửa:** `scripts/ask120.py` — `_role()`, metadata tác giả, turn/thread và render text; `scripts/ask120_gate.py` — admission, candidate builder, thống kê và regression; builders, audit/thí nghiệm và test liên quan.

**Hợp đồng đề xuất:**

| Trường | Ý nghĩa |
|---|---|
| `turn_kind` | `answer` hoặc `followup`, theo vị trí DOM |
| `speaker_role` | `responder`, `patient` hoặc `unknown`, theo bằng chứng sở hữu |
| `author_name`, `author_profile_url` | Chỉ lấy giá trị quan sát được |
| `qualification_raw`, `source_role` | Chức danh nguyên văn và vai nghề nghiệp chuẩn hóa từ header |
| `author_evidence` | DOM locator, phạm vi card/reply và trạng thái attribution |

Không dùng tên `doctor_answer` làm bằng chứng người trả lời là bác sĩ. Nhãn mặc định là “người trả lời”; chỉ hiển thị chức danh khi header nguồn hỗ trợ. Chức danh nguồn vẫn là thông tin do website công bố, không được ghi như đã xác minh giấy phép.

**Policy mặc định đề xuất:**

- Header có bằng chứng bác sĩ/y sĩ, dược sĩ hoặc điều dưỡng: gán đúng vai, tiếp tục các kiểm tra nội dung khác; không mặc định INCLUDE chỉ vì có chức danh.
- `其他`, thiếu chức danh, không ánh xạ được hoặc attribution chưa rõ: REVIEW. Nghề khác ngoài allowlist ban đầu cũng REVIEW, giữ đầy đủ thông tin nguồn để mở rộng policy sau.
- Không suy nghề từ nickname có chữ “医生”, tên dạng IP hoặc chỉ vì có tên tác giả. Không truyền tác giả card sang mọi reply khi nguồn không chứng minh quan hệ.
- Ca chia sẻ cá nhân `1351960 / card1:reply2180544` phải rời INCLUDE và không còn hiển thị thành câu trả lời bác sĩ.

**Nghiệm thu:**

- Không còn nhãn bác sĩ thiếu bằng chứng từ qualification header, kể cả trong formatted text và candidate JSONL.
- Toàn bộ 307 INCLUDE có header `其他` trong baseline được đối chiếu và chuyển quyết định theo policy; không kết luận họ đều không phải bác sĩ. Nhóm 111 vai khác/chưa rõ được tách đúng, không loại đồng loạt.
- Test phủ bác sĩ, y sĩ, dược sĩ, điều dưỡng, nghề ngoài allowlist, `其他`, header thiếu, nickname gây nhầm và card nhiều reply; giữ đúng thứ tự/ownership follow-up.
- Cập nhật mọi consumer đang lọc `doctor_answer`, nhãn, counter và source span; không chỉ sửa chữ hiển thị.

**Version và tương thích:** đề xuất parser/extractor V4 vì hợp đồng turn/author thay đổi, gate/admission v3. Giữ nguyên các cột Parquet production; metadata mới nằm trong record/JSONL. Adapter đọc baseline V3 phục vụ so sánh, không coi `doctor_answer` cũ là bằng chứng nghề nghiệp. Đồng bộ version/hash trong notebook; không resume checkpoint hoặc chuyển nhãn review từ policy cũ một cách tự động.

## 3. F3 / P2 — Bắt quảng bá theo ngữ cảnh, giảm cờ sai

**Điểm sửa:** `scripts/ask120_gate.py` — `source_flags()`, policy và summary; fixture nguồn tương ứng.

**Cách sửa:**

- Tách các tín hiệu: tự giới thiệu cơ sở/phương pháp, CTA bấm tên/ảnh để liên hệ, cam kết kết quả và lời hứa chữa khỏi. Lưu rule ID, turn/DOM locator và đoạn trích bằng chứng; một thread có thể có nhiều cờ.
- Dùng ngữ cảnh câu/đoạn và vai người nói. Không gán quảng cáo cho người trả lời chỉ vì bệnh nhân nhắc thuốc hoặc trích một claim trong câu hỏi.
- Các tín hiệu quảng bá rõ hoặc dẫn liên hệ như những ca đã xác nhận chuyển REVIEW; giữ nguyên lời nguồn để review. Không đổi thành kết luận “sai y khoa”.
- Thay regex bắt mọi “根治” bằng rule có ngữ cảnh. “未彻底根治” trong diễn tiến bệnh không tự động là quảng bá; một phủ định ở câu khác cũng không được vô hiệu hóa lời hứa điều trị rõ ràng.
- Báo lặp câu trả lời xuyên trang để hỗ trợ review, không tự dedup mọi câu trả lời giống nhau.

**Nghiệm thu:** toàn bộ 9 thread trong `unflagged_promotion_and_contact_signals.json` có kỳ vọng được đối chiếu; ca rõ như `1168492`, `2770682`, `2899724` bị hold. Bổ sung negative fixture, gồm `1164309 / card5:reply522282`, để chứng minh giảm false positive. Báo kết quả trên tập fixture đã gán kỳ vọng, không gọi đó là precision/recall toàn domain.

## 4. F5 / P2 — Chuẩn hóa câu hỏi và mở rộng QC

**Điểm sửa:** `scripts/ask120.py` — trích xuất/normalize question; `scripts/ask120_gate.py` — kiểm question-level và audit.

**Cách sửa:**

- Dùng bước chuẩn hóa có giới hạn cho question: markup định dạng đã biết, mảnh `BR>` có bằng chứng từ raw và footer khi có cấu trúc template xác định.
- Giữ raw question, hash raw/clean, DOM locator, các đoạn bị bỏ và normalization actions. Tách rõ text nguồn với text chuẩn hóa; giữ paragraph break.
- Không xóa mọi chuỗi có `<`/`>` hoặc mọi lần xuất hiện từ “投诉”. Bảo toàn gene, bất đẳng thức và lời kể thực.
- Kiểm UI/markup còn dư trên question cùng với turn text. Lỗi câu hỏi chung làm hold mọi thread liên quan; không chỉ ghi cờ parser rồi để gate bỏ qua.

**Nghiệm thu:** đối chiếu đủ 31 trang candidate có mảnh `BR>` trong baseline; mảnh đã xác nhận được loại hoặc chặn nếu chưa xử lý chắc chắn. Footer ở `1404664` không còn lọt vào câu hỏi sạch. Có negative fixture cho `BRCA1`, chuỗi gene, dấu `<`, `>` và bệnh nhân dùng từ “投诉” trong nội dung thật.

## 5. F4 / P2 — Tách tính hợp lệ DOM khỏi đủ ngữ cảnh câu hỏi

**Điểm sửa:** `scripts/ask120.py` — metadata question; admission policy và candidate builder trong `scripts/ask120_gate.py`.

**Cách sửa:**

- Giữ kiểm tra có đúng question node và không rỗng; bổ sung `question_context_status`, `question_context_source` (`body`, `title`, `both`, `unresolved`) và reason/evidence độc lập.
- Kiểm title và body sau F5. Cả hai chỉ chứa thời gian, lời cảm ơn hoặc câu hỏi chung “chữa thế nào/có khỏi không” mà không nêu vấn đề → REVIEW vì thiếu ngữ cảnh, không đoán bệnh từ answer.
- Không dùng số ký tự làm tiêu chí thiếu ngữ cảnh. Dùng rule giới hạn cho mẫu đã biết; ca không chắc chắn đưa REVIEW.
- Nếu chỉ title có ngữ cảnh, giữ nguyên body và lưu rõ `title_only`; policy vòng đầu đưa REVIEW để kiểm riêng. Không âm thầm thay body bằng title hoặc answer. Sau khi review nhóm này có thể nới bằng một thay đổi policy riêng.

**Nghiệm thu:** `1205311`, `1183810` rời INCLUDE; các câu hỏi ngắn rõ chủ đề như “什么是血性恶露” và “精神分裂能治愈吗” không bị đánh thiếu ngữ cảnh chỉ vì ngắn. `2686938` được ghi nhận title-only và REVIEW; `1040547` giữ bằng chứng body nguồn bị cụt. Đối chiếu toàn bộ 16 câu hỏi ngắn của baseline, phân biệt quyết định do ngữ cảnh với các lý do hold khác.

## 6. Kiểm chứng tích hợp và notebook check

**Đồng bộ source:** cập nhật hai notebook crawl/domain bằng builder hiện có và tái tạo `notebooks/check_120ask_50.ipynb`. Giữ tên legacy và LIMIT=1.000. Thêm thí nghiệm/delta theo F1–F5, tận dụng helper thay vì nhân bản logic parser trong cell. Baseline V3 cũ vẫn được giữ; kết quả V3.1 là mốc so vòng sửa mới.

**Kiểm tra bắt buộc:**

1. Chạy các unittest 120ask, test notebook liên quan và fixture mới. Giữ regression các lỗi từng sửa: sticky manual review, resume/hash/raw recovery và question media.
2. Replay offline cùng 1.000 HTML vào thư mục timestamp mới, mock network để phát hiện request ngoài ý muốn. Không ghi đè baseline hoặc resume bằng hash cũ.
3. Xuất delta cấp thread: quyết định cũ/mới, reasons, role/header, text hash, phần text thêm/bỏ; tổng hợp thêm/bớt document. Các thay đổi do nhiều rule cùng tác động phải có đủ reasons, không ép quy về một finding.
4. Audit lại raw/hash, ID, schema, DOM locator, source span và JSONL/Parquet. Kiểm invariants mới: không INCLUDE UI-only, không nhãn bác sĩ thiếu bằng chứng, không câu hỏi còn footer/markup đã biết hoặc thiếu ngữ cảnh theo rule mới.
5. Đối chiếu lại các ca F1–F5 và packet 82 thread cũ. Lấy thêm tối thiểu 50 INCLUDE phân tầng với seed mới; ưu tiên phần chưa có trong packet cũ và ghi rõ mức trùng nếu không đủ. Đây vẫn là cùng tập raw 1.000 URL, không phải mẫu domain độc lập.
6. Chạy toàn bộ cell của notebook check trong kernel sạch; kiểm hash snapshot/parser/policy và xuất ZIP kèm audit, delta, report, phiếu review.

Lệnh nền cho bước xác minh:

    .venv\Scripts\python.exe -X utf8 scripts/build_120ask_notebooks.py
    .venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p '*120*.py' -q
    .venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_notebook_*.py' -q

**Tiêu chí kết thúc vòng sửa:**

- Mọi fixture xác nhận lỗi đạt kỳ vọng, các ca đối chứng không bị xóa nội dung thực; regression và artifact audit đạt.
- Mọi chênh lệch candidate được giải thích; không còn hai blocker P1 trong phần INCLUDE được kiểm.
- Gate kiểm được các invariant mới; khi invariant thất bại phải trả `NEEDS_PARSER_FIX`. Readiness tự động và kết luận review nội dung được trình bày riêng, tránh việc chỉ dựa artifact audit để tuyên bố corpus đã duyệt.
- Nhãn AI vẫn tách khỏi nhãn con người. `READY_FOR_FILTERED_PILOT` chỉ áp dụng kiểm tra tự động; `READY_FOR_FILTERED_CORPUS` vẫn cần review theo policy. Các mục REVIEW chưa xử lý tiếp tục ở ngoài candidate.

## Gói bàn giao khi triển khai

- Source, fixtures/tests và notebook được build cùng version; tài liệu hợp đồng role/policy cập nhật.
- Run replay mới và ZIP có provenance; bảng delta so V3.1 và báo cáo tác động từng finding.
- Danh sách phần còn cần review người thật; không coi việc pass test hoặc giữ ít candidate hơn là xác nhận đúng y khoa.
- Dữ liệu ngày hỏi trước 2020, độ đúng y khoa và chất lượng retrieval/RAG là các hướng đánh giá riêng sau vòng sửa trích xuất này; không gộp vào tiêu chí pass F1–F5.
