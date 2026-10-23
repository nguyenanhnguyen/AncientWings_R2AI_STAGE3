# Sửa F5 — BR> và footer câu hỏi 120ask — 23/10/2026

**Kết luận: F5 đạt trong phạm vi kiểm chứng.** Toàn bộ 50 câu hỏi có mảnh `BR>` trong 1.000 raw đã lưu được làm sạch, gồm đủ **31 trang candidate trong baseline ban đầu**. Footer `| 投诉 | 评价(0` ở source ID `1404664` được bỏ đúng đoạn template. Gene, bất đẳng thức và lời bệnh nhân có từ “投诉” được giữ trong các ca đối chứng.

Run chốt: `runs/ask120_f5_20261023T134656601041Z`, tạo lúc **20:46:56 ngày 23/10/2026, giờ Việt Nam**. Offline replay cùng bộ 1.000 HTML gốc, **0 request mạng**. Baseline so sánh chính là run sau F3 `ask120_f3_20261020T044558800281Z`. Đây không phải kiểm chứng live trên 1.000 URL khác.

## Những gì đã sửa

- Chuẩn hóa question riêng, giữ paragraph break và chỉ thay token formatting trong allowlist với tối đa hai lớp entity; không giải mã toàn bộ nội dung vì gặp một tag.
- Chỉ bỏ `BR>` ở đầu câu hỏi khi có bằng chứng DOM của đoạn đầu `p.crazy_new` và span “健康咨询描述：”. Không lấy header ở một đoạn sau làm bằng chứng xóa prefix của đoạn trước. Fragment chưa đủ bằng chứng được giữ và chuyển REVIEW.
- Chỉ bỏ footer complaint/evaluation ở cuối khi đúng template hai `br` liên tiếp. Lời kể/chuỗi trích dẫn có từ 投诉 hoặc 评价 được giữ.
- `question_provenance` lưu raw paragraph text, serialized source DOM, locator, raw/DOM/clean hash và từng action/span/replacement/hash trước-sau. `ask120_question_raw` legacy giữ nguyên trên cả 1.000 trang; byte raw response vẫn có hash/path độc lập.
- `question_qc` kiểm markup/UI còn dư. Question có vấn đề chuyển mọi thread đủ điều kiện chữ của trang REVIEW; audio/hard blocker tiếp tục EXCLUDE. Manual INCLUDE không vượt blocker này, invariant cuối tính lại QC để chặn quyết định checkpoint bị đổi.
- Candidate JSONL có evidence question và `question_source_span`; cột Parquet production không đổi. Parser audit và audit holdout kiểm thêm trace question.

Parser nâng **v4.1**, gate/admission **v3.2**, question ruleset **`120ask-question-normalization-v1`**. Extractor vẫn `120ask_qa_dom_v4`, hợp đồng turn không đổi. Cần run mới vì hash/parser/policy thay đổi; không tự chuyển nhãn review từ run cũ.

## Kết quả kiểm chứng

| Kiểm tra | Kết quả |
|---|---:|
| Test 120ask trên source chốt | **94/94 pass** |
| Test method mới cho F5 trong nhóm trên | **11** |
| HTML fixture F5 thật | **51/51 đạt** |
| BR> trong toàn bộ clean question | **50 → 0** |
| Trang BR> trong candidate baseline ban đầu / sau F3 | **31 / 27**, đều sạch sau fix |
| Footer 1404664 | Sạch; vẫn EXCLUDE do audio-only |
| Raw kiểm hash và parse | **1.000/1.000** |
| Question DOM/raw/action chain đã đối chiếu | **1.000** |
| Action / span question đã replay kiểm hash | **2.076 / 2.519** |
| DOM locator turn / source span candidate | **1.829 / 1.135** |
| Cờ F3 / evidence span đối chiếu lại | **39 / 62** |
| Regression cố định cũ | **9/9 đạt** |
| Fixture F1 / F3 trong replay | **9/9 / 20/20 đạt** |
| Author blocker F2 lọt INCLUDE | **0** |
| Parquet và JSONL theo cột production | Khớp từng record |
| Candidate invariant violation | **0** |
| Notebook check: toàn bộ cell code | **17/17 chạy xong**, kernel sạch, 0 lỗi, 0 request |
| A/B candidate manual / resume / media | **1/1 + 7/7 + 6/6** |
| A/B impact replay | **1.000 trang, đạt** |
| Unified notebook sau khi đã chạy có outputs | **7/7 test pass**, nằm trong bộ 94 test |

Fixture lấy từ raw đã kiểm hash, gồm 50 BR> và một footer, không phải 51 ví dụ tổng hợp. Mỗi ca giữ toàn bộ ký tự nội dung như baseline sau khi bỏ qua whitespace, chỉ trừ artifact đã xác nhận; test kiểm thêm đúng rule, DOM evidence, raw/clean hash và replay từng action. Ca tổng hợp phủ escaped tag, gene/`<`/`>`, lời kể có 投诉, fragment chưa rõ, footer thiếu template, chặn ở mọi thread, manual override và checkpoint bị đổi.

**Bộ notebook rộng: 198/200 test đạt, 2 test lỗi setup `NameError: CNKANG_TRANSPORT`.** Hai ca là `test_domain_notebook_executes_same_primary_route` (PubMed) và `test_domain_cell_uses_curl_and_never_browser_even_mode_all` (VOV). Đã dựng lại snapshot parser trước F5 trong bộ notebook hiện tại và tái hiện đúng hai lỗi; namespace mock thiếu cấu hình cnkang, cả hai không chạy URL 120ask. Không sửa hay bỏ qua các test này để báo xanh toàn bộ. Log và bản tái hiện được đóng gói. Các test 120ask và notebook check 120ask thực tế đều đạt.

Việc chạy notebook còn phát hiện composition làm mất execution metadata của cell holdout được tái tạo. Builder đã giữ output/count khi source cell không đổi; test idempotence trên notebook đã chạy đạt. Chỉ sửa cơ chế build của notebook check chung.

## Tác động và review nội dung

Candidate giữ **657 document**, thread **936 INCLUDE / 541 REVIEW / 81 EXCLUDE**, **0 thay đổi quyết định thread**, không thêm/bớt ID. Cả 1.000 trang giữ nguyên parsed reply, nội dung/role/tác giả/media/ownership/follow-up; F5 chỉ thay phần question và metadata/QC liên quan.

Có **589 question đổi text**, gồm **538 trang chỉ đổi whitespace/xuống dòng** và **51 trang bỏ artifact đã xác nhận**. Những document chứa question đổi có text hash mới và source span được tính lại; không suy việc text hash đổi thành thêm/bớt câu trả lời. Phần BR>/footer vẫn tồn tại trong raw/evidence để truy nguyên, không phải trong clean question/corpus text.

Đã đối chiếu packet 51 ca với source/expectation và đọc **50 question của candidate chọn ngẫu nhiên**, seed `2026102305`. Không thấy thêm lỗi F5 trong packet này. Review tập trung vào giữ nội dung và ranh giới đoạn, không đánh giá đúng/sai y khoa của lời nguồn hoặc đọc thủ công toàn bộ 1.000 trang.

Một số câu hỏi vốn cụt/thiếu ngữ cảnh vẫn được giữ nguyên; ví dụ source bắt đầu bằng mảnh câu hoặc hỏi chung mà không nêu đủ chủ đề. Đó là **F4 còn mở**, không tự đoán hoặc khôi phục thông tin từ lời trả lời trong lượt F5. “Không còn BR>” không có nghĩa mọi question đã đủ ngữ cảnh.

AI review ghi riêng, không điền phiếu con người. Có **526 mục review bắt buộc, 0 nhãn con người**. Gate tự động vẫn `READY_FOR_FILTERED_PILOT`; đánh giá tổng thể tiếp tục **`NEEDS_PARSER_FIX` vì F4**. Không coi candidate là corpus đã duyệt.

Notebook đã chạy: `runs/ask120_gate_20261023T134658759864Z`; đầu ra candidate/reparsed được đối chiếu với run audit F5. A/B dùng baseline V3 đóng băng trước các fix trước đây, nên so sánh của A/B là 775 → 657; so sánh chính riêng F5 là **657 → 657**.

## Artifact

- [Tóm tắt F5](../../runs/ask120_f5_20261023T134656601041Z/f5_review_summary.json).
- [Packet 51 ca trước/sau](../../runs/ask120_f5_20261023T134656601041Z/f5_question_review_packet.md).
- [Delta text question](../../runs/ask120_f5_20261023T134656601041Z/question_text_delta.jsonl).
- [Ghi chú AI review 50 câu hỏi](../../runs/ask120_f5_20261023T134656601041Z/f5_ai_question_review.jsonl).
- [Notebook check chung đã chạy](../../notebooks/check_120ask_50.ipynb).
- [ZIP run F5](../../runs/ask120_f5_20261023T134656601041Z.zip).

Source: `scripts/ask120.py`, `scripts/ask120_gate.py`, `scripts/ask120_holdout_audit.py`; test: `tests/test_ask120_question_normalization.py`, fixture: `tests/fixtures/120ask_f5/`. Builders đồng bộ snapshot production/domain và check; log test, nguồn chốt, notebook đã chạy và kết quả A/B nằm trong ZIP.
