# Sửa F3 và kiểm chứng trên 1.000 HTML — 20/10/2026

**Kết luận: F3 đạt các ca đối chứng và audit của run cuối.** Cả 9 thread bỏ sót đã review trước đây được gắn cờ nguồn. Hai ca lâm sàng bắt nhầm được gỡ cờ; các ca phần trăm chẩn đoán, mức chắc chắn và câu an toàn có điều kiện phát hiện thêm trong audit cũng đã có test và được sửa.

Run chốt: `ask120_f3_20261020T044558800281Z`, tạo lúc **11:45:58 ngày 20/10/2026, giờ Việt Nam**. Offline replay cùng 1.000 HTML, **0 request mạng**. Baseline chính là run sau F2 `ask120_f2_20261020T041719385491Z`; không phải mẫu URL mới.

## Thay đổi

- Parser V4 không đổi. Gate/admission nâng v3.1, ruleset `120ask-source-signals-v1`; notebook check đã build từ source mới. Cần run mới do gate/policy hash đổi.
- Chỉ phân tích turn của người trả lời; không ghép lời bệnh nhân hoặc câu hỏi vào phần lời nguồn cần gắn cờ. Follow-up người trả lời có bằng chứng riêng theo turn.
- Kết hợp tín hiệu tự giới thiệu cơ sở + offer/phương pháp, cơ sở + công thức đặc biệt, profile click + liên hệ, lời mời hỗ trợ cá nhân, cam kết thời gian/kết quả/an toàn và quảng bá sản phẩm/phương pháp có claim mạnh. Khoảng cách và ngữ cảnh câu bị giới hạn.
- Không dùng riêng “根治/彻底治愈” làm bằng chứng quảng bá. Phủ định, cảnh báo, câu hỏi và qualifier liên quan được xét tại mệnh đề chứa tín hiệu; phủ định ở câu/mệnh đề khác không che lời hứa điều trị thực.
- Giữ nguyên text nguồn. Mỗi cờ có category, rule/version, raw hash/path, source/thread/turn/reply ID, DOM locator, text hash, excerpt và các span chính xác trên clean text của turn.
- Cờ đưa thread REVIEW theo policy. Candidate JSONL có `source_claim_flags` để giữ evidence nếu được nhập bằng policy/nhãn hợp lệ; cột Parquet không đổi. Invariant cuối chặn claim chưa duyệt kể cả khi quyết định checkpoint bị đổi thành INCLUDE.

## Kiểm chứng và các ca biên

| Kiểm tra | Kết quả |
|---|---:|
| Unittest `*120*.py` trên source chốt | **76/76 đạt** |
| Unittest notebook cho parser/crawl | **198/198 đạt** |
| Test độc lập, bỏ 12 test trùng | **262 đạt** |
| Test method riêng F3 trong các nhóm trên | 11 |
| Ca HTML thực trong test và replay | **20/20 đạt** |
| A/B candidate: manual review / resume / media | **1/1 + 7/7 + 6/6** |
| A/B impact replay | **1.000/1.000, đạt** |
| Gate regression cũ | **9/9 đạt** |
| Ca F1 trong replay | **9/9 đạt** |
| Tác giả không đạt admission F2 lọt INCLUDE | **0** |
| Raw kiểm hash / parse | **1.000/1.000** |
| Raw/parse error | **0** |
| DOM turn locator / candidate source span | **1.829 / 1.135** |
| Cờ / evidence span đã đối chiếu offset/hash/DOM | **39 / 62** |
| Lỗi artifact/invariant | **0** |
| Parquet và JSONL theo cột production | Khớp từng record |

20 ca gồm 13 positive và 7 negative, lấy từ 19 raw HTML. Đây là tập đối chứng được chọn để chẩn đoán, không phải phép đo precision/recall toàn domain. Bộ test còn phủ ngữ cảnh tổng hợp, provenance, phân biệt người nói, nhãn thủ công/policy và invariant cuối. Chạy các hàm A/B được notebook gọi cùng pipeline replay thực tế; không chạy lại toàn notebook trong kernel ở lượt này.

Các ca chính:

- 9 false negative ban đầu: `1375991` (hai thread), `1351960`, `1168492`, `2899724`, `2770682`, `1329046`, `1326948`, `1240571` đều có evidence và REVIEW. Một số đã REVIEW do F2; F3 bổ sung đúng lý do nguồn, không chỉ dựa vào chặn nghề nghiệp.
- `1164309 / card5:reply522282`: “未彻底根治” không còn bị coi là quảng bá. Thread vẫn REVIEW vì bằng chứng nghề nghiệp, không được tự bỏ blocker khác.
- `1152799 / card1:reply627666`: mô tả “部分病人可获根治” được gỡ cờ và trở lại INCLUDE khi không có blocker khác.
- Giữ review các đoạn quảng bá claim mạnh tại `1115074`, `1281002`, `1332675`, thay vì làm chúng lọt khi bỏ regex “根治”.
- Không gắn cờ chỉ vì hẹn liên hệ lại thông thường (`1396404`) hoặc yêu cầu gửi bệnh án (`1354101`) khi thiếu tín hiệu quảng bá theo rules này.
- `1002892`, `1089606`, `1307527`: không coi phần trăm trong sự không chắc chắn/độ đặc hiệu chẩn đoán hoặc “一般无痛苦、无副作用” là cam kết điều trị tuyệt đối. Ba ca này được phát hiện ở run thử, thêm vào fixture rồi replay lại. Run thử `ask120_f3_20261020T044215264095Z` được giữ với kết luận `NEEDS_RULE_REFINEMENT`, không dùng làm run chốt.

## Tác động so với F2

| Chỉ số | Sau F2 | Sau F3 |
|---|---:|---:|
| Candidate document | 651 | **657** |
| Thread INCLUDE | 928 | **936** |
| Thread REVIEW | 549 | **541** |
| Thread EXCLUDE | 81 | **81** |
| Thread có cờ nguồn | 48 | **30** |

Có **10 INCLUDE → REVIEW**, **18 REVIEW → INCLUDE**. Tám document được thêm lại và hai document rời candidate; không tối ưu theo số lượng document giữ lại. Chênh lệch tăng 6 document đến từ việc vừa chặn tín hiệu mới vừa gỡ các hold không còn đủ căn cứ theo rules đã sửa.

Trong toàn bộ thread, **16 thread mới có cờ**, **34 thread được gỡ cờ cũ**, 14 còn cờ với evidence mới. Các con số này gồm cả thread đã REVIEW/EXCLUDE vì lý do khác. 39 cờ trên 30 thread gồm 20 cờ claim, 8 cờ tự quảng bá và 11 cờ CTA; một thread có thể có nhiều cờ, không đồng nghĩa 39 câu trả lời hay 39 quảng cáo đã xác minh.

Đã đối chiếu packet bằng chứng của **64 thread** thuộc hợp của nhóm có cờ trước/sau, bao gồm các ca mất cờ nhưng vẫn cần giữ review theo tín hiệu khác. Việc review tập trung vào đoạn chữ, người nói, rule và quyết định; không thẩm định đúng/sai y khoa của toàn bộ lời nguồn.

Có một nhóm câu trả lời có cờ lặp xuyên trang (`1168492`, `2770682`). Cả hai giữ mapping nguồn và REVIEW; chỉ báo nhóm lặp, không tự dedup mọi câu trả lời giống nhau.

**Toàn bộ parsed thread của 1.000 trang giữ nguyên so với F2**: nội dung/normalization từng turn, raw text/hash, media, role, tác giả và DOM evidence không đổi. Chỉ gate, cờ nguồn và tập thread xuất candidate thay đổi.

Thí nghiệm A/B vẫn dùng baseline V3 đóng băng trước các fix cũ, nên mốc của A/B là 775 → 657. So sánh chính của vòng F3 là **651 → 657**.

## Trạng thái và artifact

**F1–F3: đã xử lý trong phạm vi đã kiểm. F4/F5: còn mở.** Gate tự động trả `READY_FOR_FILTERED_PILOT`; đánh giá tổng thể tiếp tục `NEEDS_PARSER_FIX` do những finding còn lại. Có **526 mục review, 0 nhãn con người**; ghi chú AI và nhãn tổng hợp của thí nghiệm không được điền vào phiếu review thật.

Rules hiện bao phủ các dạng đã định nghĩa và ca đối chứng. Không kết luận mọi tự quảng bá/claim ngoài mẫu đều được phát hiện; đây là tín hiệu đưa review, không phải kết luận gian dối hoặc sai y khoa.

- [Tóm tắt F3](../../runs/ask120_f3_20261020T044558800281Z/f3_review_summary.json).
- [Packet bằng chứng](../../runs/ask120_f3_20261020T044558800281Z/f3_signal_review_packet.md).
- [Thay đổi quyết định thread](../../runs/ask120_f3_20261020T044558800281Z/f3_thread_decision_delta.jsonl).
- [Nhóm lời đáp có cờ lặp xuyên trang](../../runs/ask120_f3_20261020T044558800281Z/f3_repeated_flagged_answers.json).
- [Audit artifact](../../runs/ask120_f3_20261020T044558800281Z/artifact_audit.json).
- [ZIP run chốt](../../runs/ask120_f3_20261020T044558800281Z.zip).

Source fix: `scripts/ask120_gate.py`; test: `tests/test_ask120_source_signals.py`, fixture `tests/fixtures/120ask_f3/`. Log test, source/runner, manifest fixture và kết quả A/B được lưu trong run để truy nguyên.
