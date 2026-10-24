# ask.39.net — fix E: 5 phát hiện sau holdout D

Ngày 22/10/2026. Gate mới: `ask39-gate-v3-source-context`; parser/audit giữ nguyên. Đã sửa và replay 450 raw; lượt xác nhận 200 URL mới đang được kiểm riêng trước khi kết luận readiness.

## Thay đổi

| ID corpus | Rule mới | Bằng chứng |
| --- | --- | --- |
| 2138096 | `source_absolute_safety_claim_review` | Laser không tổn thương mô lành xung quanh |
| 2173132 | `source_absolute_safety_claim_review` | Thuốc cụ thể phối hợp chống đông không tăng rủi ro chảy máu |
| 2213438 | `source_absolute_safety_claim_review` | Phẫu thuật không ảnh hưởng sinh hoạt tình dục |
| 2223535 | `source_consultation_cta_review` | Mời click tư vấn trực tuyến trong answer quảng bá điều trị |
| 2402453 | `source_absolute_safety_claim_review` | Xạ trị không tổn thương mô lành xung quanh |

Cả 5 trang chuyển từ accepted sang **REVIEW**, trong khi extraction vẫn accepted. Rule không chứa ID trang hoặc tên tác giả. Không xóa câu nguồn để làm answer pass QC.

Rule an toàn chỉ ghép phương pháp/thuốc và lời khẳng định không gây hại/không tăng rủi ro trong cùng câu hoặc câu liền kề có tham chiếu rõ. `不/不会` nằm trong claim không gây hại được hiểu là lời bảo đảm an toàn, khác với phủ định một claim hiệu quả. Phủ định lồng như “không thể bảo đảm không có rủi ro”, mô tả giảm rủi ro/hiệu quả có điều kiện, câu hỏi, lời thuật lại, trích dẫn và bác bỏ được kiểm riêng. Phủ định không liên quan không tự hủy claim khẳng định.

Rule CTA bắt lời mời click/mở tư vấn trực tuyến trong lời responder. Lời bệnh nhân và mô tả giáo dục một-một, gồm ca âm 2444995, không bị gán thành lời mời tư vấn quảng bá.

Mỗi assessment giữ rule/version, answer ID nguồn, message ID, vai, DOM locator, câu nguồn, method/claim và offset; trường hợp bị triệt tiêu cũng giữ lý do trong `source_context_assessments`. Chỉ assessment quyết định review mới thêm source flag và chặn export. Các rule hiệu quả, contact/promotion cũ và allowlist chức danh giữ nguyên.

## Replay và test

| Chỉ số | Trước E | Sau E |
| --- | ---: | ---: |
| Raw | 450 | 450 |
| Answer / follow-up | 595 / 38 | 595 / 38 |
| Extraction accepted | 450 | 450 |
| Text hash không đổi | — | 450 |
| Candidate local | 436 | 431 |
| REVIEW | 14 | 19 |

Đúng 5 quyết định quality thay đổi; mọi source flag cũ giữ nguyên. Câu hỏi, text, định danh nguồn, tác giả, thứ tự, vai/parent, normalization và DOM exclusions đối chiếu bằng object/hash không thay đổi. Ca 2401990 tiếp tục có hai answer riêng. Không có thay đổi quyết định cấu trúc hoặc access.

**22 test E mới pass**, cùng 3 test helper có sẵn. Test mới nằm trực tiếp trong cell tag `ask39-fix-e` của [notebook check](../../notebooks/check_ask.39.net.ipynb), không tạo file test Python mới. F1–D giữ payload riêng, gồm gate D cũ, để tái hiện lịch sử và 5 ca bị bỏ sót trước E.

Sau khi bổ sung kiểm tra DNS và bằng chứng holdout xác nhận: Run All offline **139 test notebook + 3 helper pass**, toàn bộ 36 code cell thực thi thành công.

Các test bao phủ 5 raw thật, đủ 450 quyết định, phủ định lồng, điều kiện và ranh giới câu/đoạn/message, lời bệnh nhân/không rõ vai, trích dẫn/bác bỏ, CTA âm, follow-up đi qua parser → gate và đúng parent, span bằng chứng và rule không phụ thuộc ID trang. Export đọc lại raw và kiểm lại gate dù record mang trạng thái accepted cache; Parquet đọc lại có đúng 431 ID đủ điều kiện và không chứa cả 5 trang đích. Mọi record vẫn `corpus_eligible=False`; production export bằng 0.

Artifact: `runs/ask39_e_replay450_20261022T041615818553Z`, gồm raw, records, candidate/decisions, `decision_diff.json`, `target_evidence.json`, summary và manifest/hash code.

## Xác nhận sau sửa

Sau replay đạt, đã chọn và thử đủ 200 URL mới, seed `20261024`, phân bổ 100 numeric + 100 underscore; loại toàn bộ 450 ID và URL trước đó. Thu được 199 raw; một URL lỗi TLS sau request và browser fallback. Parser/gate/audit giữ nguyên hash, thay đổi timeout DNS ở transport được ghi riêng trong manifest.

Readiness tổng thể vẫn **`NEEDS_FIX`**: lượt xác nhận mới phát hiện một answer bị bỏ sót sau `sele_txt` rỗng (QC đã chặn REVIEW) và một claim phương pháp đặc thù “tốt nhất” chưa được gate triage. Năm ca D đã sửa vẫn đạt replay; các phát hiện mới không sửa ngược vào kết quả holdout. Xem [báo cáo xác nhận](ask39_e_confirmation_review_20261022.md). Chưa tích hợp F6.
