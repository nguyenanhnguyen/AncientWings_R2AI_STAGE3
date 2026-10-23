# ask.39.net — review fix B: claim theo ngữ cảnh và người nói

Ngày: 22/10/2026. Phạm vi: gate candidate local, replay 250 HTML cũ; không crawl holdout mới.

## Kết quả

**Fix B đạt trên regression hiện có.** Hai candidate **2229930** và **2252991** chuyển từ accepted sang REVIEW với cờ `source_treatment_claim_review`. Chỉ cờ này có nghĩa cần review claim nguồn, không phải kết luận đúng/sai y khoa.

| Chỉ số | Baseline A | Sau B |
| --- | ---: | ---: |
| Trang replay | 250 | 250 |
| Extraction accepted | 250 | 250 |
| Answer / follow-up | 343 / 22 | 343 / 22 |
| Text hash giữ nguyên so với fixture | 250 | 250 |
| Candidate local | 244 | 242 |
| REVIEW | 6 | 8 |

Hai cờ promotion cũ và bốn ca chức danh chưa nhận diện giữ nguyên. Ca định danh 2401990 tiếp tục có hai answer riêng và đủ điều kiện candidate. Không sửa parser, text nguồn, parent follow-up hoặc allowlist chức danh trong bước B.

## Quy tắc và bằng chứng

Gate: `ask39-gate-v2-claims`; rule: `ask39-treatment-claim-v1`.

- Ghép chữ ký phương pháp đã quan sát (`靶位定向体液疗法`, `靶位定向给药`, `定点\s*祛炎`) với claim hiệu quả mạnh trong cùng câu, hoặc câu kế tiếp có tham chiếu rõ như `该方法`. Không ghép qua newline hoặc sang message khác.
- Chỉ xét answer chính và follow-up vai `responder`. Câu hỏi và follow-up bệnh nhân không được gán thành claim của người trả lời. Contact/promotion cũng chỉ xét lời responder.
- Ghi nhận các trường hợp bị triệt tiêu do phủ định, nghi vấn, lời thuật lại, trích dẫn hoặc bác bỏ. Dấu ngoặc kép bọc toàn answer vốn có trong nguồn không làm mất claim khẳng định.
- Mỗi bằng chứng có rule version, answer ID nguồn đã xác minh, message ID (answer chính dùng answer ID), vai, DOM locator, câu nguồn, method/claim và offset chính xác. Danh sách `claim_assessments` giữ cả quyết định review và lý do suppression.

| ID corpus | Answer ID xác minh | Tổ hợp ghi nhận |
| --- | --- | --- |
| 2229930 | `ask39:30435163:answer:71027728` | `靶位定向给药` + `从根本上治愈` |
| 2252991 | `ask39:40831155:answer:128775128` | `定点 祛炎` + `实现阻断病情发展` / `病情不易反复复发` |

Export đọc lại raw và chạy lại gate, kể cả record mang trạng thái accepted cache. Parquet đọc lại có 242 ID đủ điều kiện, không chứa hai ID đích hoặc bất kỳ quyết định REVIEW nào. `corpus_eligible=False`; production export bằng 0.

## Kiểm chứng

Test mới nằm trực tiếp trong các cell tag `ask39-fix-b` của [notebook check](../../notebooks/check_ask.39.net.ipynb), được gitignore theo yêu cầu trước đó. Các phần F1–F5 và A chạy snapshot riêng đã đóng băng, không thay kỳ vọng lịch sử để khớp rule mới.

**82 test notebook pass** (50 F1–F5 + 13 A + 19 B), cùng 3 test helper có sẵn. Toàn bộ code cell đã chạy thành công. Artifact: `runs/ask39_claim_b_replay250_20261022T024601355130Z`, gồm raw, records, candidate Parquet, decisions, decision diff, target evidence, summary và manifest/hash code. Hash parser/gate/audit đã đối chiếu với source hiện tại và payload notebook.

Các ca kiểm tra gồm: hai HTML thật, đối chiếu đủ 250 quyết định, biến thể khoảng trắng, phương pháp/claim độc lập, phủ định claim/phương pháp, nghi vấn, câu thuật lại và trích dẫn, bác bỏ, phủ định không liên quan, tham chiếu câu kế tiếp, ranh giới paragraph/message, vai bệnh nhân/không rõ, follow-up đi qua parser → gate với đúng parent, offset bằng chứng và tái kiểm tra export.

## Giới hạn và bước tiếp

Đây là rule có phạm vi chữ ký cụ thể đã quan sát, không phải bộ phân loại mọi phương pháp hoặc mọi cách diễn đạt claim. Các ca âm được kiểm chứng bằng regression, không suy ra đảm bảo không có false positive trên toàn domain.

Replay C trên 250 HTML hiện có đạt trong bước này. Sau khi đóng băng A–B, còn bước D: 200 URL xác nhận mới, loại toàn bộ 250 ID/URL đã dùng và review theo kế hoạch. Readiness hiện tại: **`FIX_B_PASSED_FRESH_HOLDOUT_PENDING`**, chưa đủ điều kiện F6/production.
