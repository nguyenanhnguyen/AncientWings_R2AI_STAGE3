# Sửa F4 — Ngữ cảnh câu hỏi 120ask — 23/10/2026

**F4 đã sửa và đạt kiểm chứng trong phạm vi các ca đã xác nhận.** Câu chỉ hỏi cách chữa, thời gian/tuổi hoặc tham chiếu bệnh lý/thuốc chưa rõ được giữ nguyên nguồn và chuyển REVIEW. Câu ngắn có chủ đề rõ tiếp tục qua các gate khác. Candidate giảm **657 → 644 document**; **14 thread INCLUDE → REVIEW**.

Run: `runs/ask120_f4_20261023T142240359846Z`, bắt đầu **21:22:40 ngày 23/10/2026, giờ Việt Nam**. So sánh trực tiếp với run sau F5 `ask120_f5_20261023T134656601041Z`. Đây là replay **cùng 1.000 HTML gốc**, chặn Requests, **0 request mạng**; không phải kiểm chứng live trên một mẫu URL mới.

## Thay đổi

- Parser **v4.2**, gate/admission **v3.3**, ruleset `120ask-question-context-v1`. Extractor giữ `120ask_qa_dom_v4`.
- Kiểm title và body sau chuẩn hóa F5. DOM hợp lệ và ngữ cảnh là hai kiểm tra riêng. Không suy vấn đề từ answer, không thay body bằng title và không đặt ngưỡng độ dài.
- Mask giới hạn các mẫu hỏi chung, thời gian/tuổi/giới, nhãn trường, lời chào/cảm ơn để phân tích; title/body không bị chỉnh sửa. Ghi span/hash/DOM locator cho từng trường, phần generic và phần còn lại trong `question_context`.
- Body có nội dung ngoài các mẫu chung: `context_present`, nguồn `body` hoặc `both`. Chỉ title có nội dung: `title_only`/`title`, REVIEW. Cả hai không có vấn đề cụ thể: `insufficient`; tham chiếu chưa rõ: `unresolved`, đều REVIEW.
- Yêu cầu xem “bệnh lý của chú tôi”, “thuốc như vậy” thiếu báo cáo/tên bệnh/tên thuốc được REVIEW. Câu hỏi định nghĩa hoặc báo cáo có kết quả cụ thể có đối chứng bảo toàn.
- Mọi thread đủ điều kiện chữ của trang cùng chịu kiểm tra F4. Hard blocker/audio-only/DOM thiếu vẫn EXCLUDE. Manual INCLUDE không vượt blocker F4; invariant cuối tính lại context để phát hiện checkpoint bị thay đổi.
- Candidate JSONL thêm context/status/source; cột Parquet production giữ nguyên. Snapshot hai notebook crawl/domain và notebook check đã đồng bộ. Hash mới yêu cầu run mới, không tự chuyển nhãn cũ.

`context_present` chỉ ghi nhận bộ rule tìm được phần nội dung ngoài mẫu chung, **không xác nhận đủ bệnh sử hoặc tính đúng y khoa**. Bộ kiểm giới hạn này chưa đánh giá mọi kiểu tham chiếu, văn bản vô nghĩa hoặc ngữ cảnh bị thiếu trên toàn domain.

## Tác động trên 1.000 trang

| Chỉ tiêu | Trước F4 | Sau F4 |
|---|---:|---:|
| Candidate document | 657 | **644** |
| Thread INCLUDE | 936 | **922** |
| Thread REVIEW | 541 | **555** |
| Thread EXCLUDE | 81 | **81** |
| Vi phạm candidate invariant | 0 | **0** |
| Mục review bắt buộc / nhãn người thật | 526 / 0 | **528 / 0** |

Có **31 trang được ghi cờ context**: **27 title-only, 3 insufficient, 1 unresolved**. Trong đó 13 trang trước đây có candidate, 1 trang đã REVIEW và 17 trang đã EXCLUDE; 16 trang trong nhóm EXCLUDE thiếu question DOM hợp lệ. Vì vậy không được hiểu là cả 31 trang vừa chuyển từ INCLUDE sang REVIEW.

Có 21 thread đổi tập lý do, gồm **14 đổi quyết định** và 7 vốn đã REVIEW chỉ bổ sung lý do F4. Không có ID mới thêm vào candidate. Cả 1.000 title/body/provenance/QC sau F5 và parsed reply giữ nguyên; text của 644 candidate còn lại khớp baseline từng document.

| Ca kiểm tra | Quan sát sau fix |
|---|---|
| `1205311`: “怎么治疗啊!” | Thiếu vấn đề, REVIEW |
| `1183810`: “9年 / 没治过 / 能治好吗” | Chỉ thời gian và hỏi khả năng chữa, REVIEW |
| `2905493`: title “25”, body “患者性别:25” | Chỉ số/nhãn nhân khẩu, REVIEW |
| `2686938`: title nói tăng lipid, body “谢谢” | `title_only`, REVIEW; không chép title vào body |
| `1040547`: body “时间了.” | Giữ nguyên mảnh câu nguồn, `title_only`, REVIEW |
| `2612463`: body dẫn “我说的这些” | Body chưa nêu rõ đối tượng, chỉ title có bệnh cụ thể; REVIEW |
| `2876901`: bệnh lý/thuốc của người thân không nêu cụ thể | `unresolved`, REVIEW |
| `933967`: “什么是血性恶露” | Ngữ cảnh hợp lệ, vẫn INCLUDE |
| `990877`: “精神分裂能治愈吗” | Ngữ cảnh hợp lệ; vẫn REVIEW vì lý do tác giả F2 có trước |

## Kiểm chứng và review

| Kiểm tra | Kết quả |
|---|---:|
| Toàn bộ test 120ask | **106/106 pass** |
| Test method mới F4 trong bộ trên | **12** |
| HTML fixture thực F4 | **52/52 đạt** |
| Câu ngắn trong baseline gốc | **16/16 đối chiếu** |
| Raw hash/parse | **1.000/1.000 đạt** |
| Title/body context/hash/DOM | **1.000 trang, 2.000 trường** |
| Span context đối chiếu offset/text | **47.467** |
| Question normalization action / span F5 | **2.076 / 2.519**, không đổi |
| Turn DOM locator / candidate source span | **1.829 / 1.114** |
| F3 flag / evidence span | **39 / 62**, khớp nguồn |
| Fixture F1 / F3 / F5 replay | **9 / 20 / 51**, đạt |
| Kiểm author F2 trong INCLUDE | **0 vi phạm** |
| Regression cố định cũ | **9/9 đạt** |
| JSONL ↔ Parquet production | Khớp từng record |
| Notebook check trong kernel sạch | **17/17 cell**, 0 lỗi, 0 request |
| Test unified notebook sau chạy có outputs | **7/7 pass** |
| A/B manual / resume / media | **1/1 + 7/7 + 6/6 pass** |
| A/B impact | **1.000 trang, pass**, 0 request |

Fixture gồm toàn bộ 31 trang có cờ context và 21 ca đối chứng; bao phủ đủ 16 câu ngắn của baseline ban đầu. Có thêm ca tổng hợp cho chủ đề ngắn, văn bản generic dài, định nghĩa/báo cáo, answer không được bổ sung ngữ cảnh, manual override/checkpoint và hard blocker. F5 làm một ca khác ngắn hơn sau khi bỏ BR>; nhóm 16 được định danh theo baseline gốc, không theo số ký tự sau F5.

Review 50 câu hỏi candidate với seed `2026102304`, tránh các packet review cũ, tìm thấy thêm `2876901`. Đã bổ sung rule giới hạn và fixture cho ca này, chạy lại test/replay. Mẫu cuối gồm 49 câu còn được giữ và 1 câu thay thế `1340093` từ seed `2026102305`; câu thay thế nêu giãn tĩnh mạch, sưng chân và huyết khối trong body, có vấn đề rõ. Không quan sát thêm lỗi F4 trong 50 câu cuối. Đã đọc packet 31 trang có cờ và ghi riêng nhận xét AI. Đây là kiểm tra chẩn đoán phục vụ sửa lỗi; không phải tập đánh giá độc lập hoặc ước lượng precision/recall toàn domain.

**Bộ notebook rộng đạt 198/200; 2 lỗi setup có trước là `NameError: CNKANG_TRANSPORT`.** Hai test thuộc PubMed và VOV. Đã thay snapshot bằng parser trước F4 trong bộ notebook hiện tại và tái hiện đúng hai lỗi; chúng không thực thi URL 120ask. Log và bằng chứng tái hiện được đóng gói. Bộ 120ask và notebook check thực tế đều đạt.

Run notebook: `runs/ask120_gate_20261023T142348106729Z`. Reparsed pages, toàn bộ thread, candidate JSONL/Parquet và phiếu review khớp byte với run audit; summary khớp giá trị JSON. A/B dùng baseline V3 đóng băng nên so sánh **775 → 644**; tác động riêng F4 là **657 → 644**.

Các lỗi F1–F5 đã xác nhận đạt hồi quy trong phạm vi này. Gate tự động là `READY_FOR_FILTERED_PILOT`; **528 mục review bắt buộc chưa có nhãn người thật**. Bước tiếp theo là kiểm chứng mẫu mới và review nội dung theo policy; không coi corpus đã được duyệt chỉ vì test đạt.

## Artifact

- [Tóm tắt F4](../../runs/ask120_f4_20261023T142240359846Z/f4_review_summary.json).
- [31 câu hỏi có cờ, kèm URL và trước/sau](../../runs/ask120_f4_20261023T142240359846Z/f4_context_review_packet.md).
- [Delta thread](../../runs/ask120_f4_20261023T142240359846Z/thread_decision_delta.jsonl).
- [Review AI câu hỏi](../../runs/ask120_f4_20261023T142240359846Z/f4_ai_question_review.jsonl).
- [Notebook check đã chạy](../../notebooks/check_120ask_50.ipynb).
- [ZIP kèm source, fixtures, test log, notebook và A/B](../../runs/ask120_f4_20261023T142240359846Z.zip).

Source chính: `scripts/ask120.py`, `scripts/ask120_gate.py`, `scripts/ask120_holdout_audit.py`. Test mới: `tests/test_ask120_question_context.py`, `tests/fixtures/120ask_f4/`. Parser SHA-256: `3bad0c32a95a10cc834afdeb37db8e5f90e64ee5f6e358a8a8e812b01aa7aa1e`; gate: `14cf8c29a88cdff81d55cb13abac6d16d1413da0f9c0dfef15ed8c9f4ff13c98`; policy: `1cdce0126e3e03d1220c3bf96602f22f033369b7af455dd8244bc9488f299326`.
