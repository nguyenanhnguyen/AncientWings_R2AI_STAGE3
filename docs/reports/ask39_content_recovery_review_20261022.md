# ask.39.net — khôi phục answer sau sele_txt rỗng

**Bước 1 đã sửa và replay đạt. Readiness tổng thể: NEEDS_FIX**, vì bước 2 về claim nguồn 2214666 và URL lỗi mạng 2458259 còn mở. Không tích hợp F6 hoặc xuất production trong bước này.

## Nguyên nhân và phạm vi sửa

Ca corpus **2203985**, URL `https://ask.39.net/question/14579504.html`, có answer nguồn `ask39:14579504:answer:392262374`. HTML lồng paragraph bị lxml sửa thành `p.sele_txt` rỗng rồi `p#content2831302` ngang hàng. Recovery cũ dừng ở mọi thẻ có ID, nên bỏ mất text của answer thứ ba; QC và audit đã chặn REVIEW.

Nhánh mới chỉ nhận **một paragraph `id=content` theo sau bằng số nguyên dương**, không có class, ngay sau `sele_txt` rỗng. Cả hai phải là con trực tiếp của đúng container `sele_all`. Không dò vượt qua thẻ UI hay ranh giới cấu trúc, không lấy content ID tùy ý, không ghép paragraph này vào answer đã có text, và dừng ngay sau paragraph được nhận. Các subtree UI bên trong vẫn được bộ lọc DOM loại bỏ.

Answer khôi phục:

> 猪胰就是猪的胰腺，您的血糖那么高 最好还是正规治疗 以免耽误病情

Khoảng trắng được chuẩn hóa theo parser hiện có. Hai answer trước, ID/tác giả của cả ba answer và nội dung hỏi giữ nguyên. `body_locators` bổ sung đúng paragraph nguồn; action `recover_empty_answer_content_paragraph` ghi locator block rỗng, locator được khôi phục và container answer.

Audit tự kiểm DOM bằng quy tắc riêng, không gọi parser. Bản record cũ vẫn bị phát hiện `main_answer_text_missing`; bản mới đạt audit. Parser version `ask39-parser-v2-content-recovery` và gate version `ask39-gate-v3-content-recovery` giúp gate từ chối record parser cũ; các rule source/claim và allowlist chức danh giữ nguyên.

## Replay offline

| Chỉ số | Kết quả |
| --- | ---: |
| Raw đã đối chiếu hash | 649 |
| Answer / follow-up | 833 / 50 |
| Text không đổi | 648 |
| Trang đổi text | 2203985 |
| Candidate trước → sau | 624 → 625 |
| REVIEW trước → sau | 25 → 24 |
| Lỗi audit độc lập sau sửa | 0 |
| Request mới / production export | 0 / 0 |

833 answer đều có text; 50 follow-up giữ nguyên thứ tự, vai và parent. Toàn bộ ID nguồn và raw hash giữ nguyên. Ngoài version parser, 648 trang giữ nguyên toàn bộ trường parser. Ở 2203985 chỉ answer thứ ba đổi text/source_text/text hash/body locators; render, char count, normalization và các flag thiếu nội dung thay đổi theo đó. Các field parser đổi ở trang này: `answers, text, char_count, text_sha256, normalization_actions, parser_status, parser_flags, quality_flags`.

Đúng một quyết định quality đổi: **2203985 REVIEW → accepted**. Không có source flag nào thay đổi. Claim mới 2214666 vẫn là candidate theo gate hiện tại; đây là việc của bước 2, nên toàn bộ artifact vẫn chưa được dùng cho release. URL 2458259 không có raw hợp lệ nên không nằm trong 649 raw; không thay URL để đủ mẫu.

## Test và bằng chứng

16 test mới nằm trực tiếp ở cell tag `ask39-fix-content` trong [notebook check](../../notebooks/check_ask.39.net.ipynb), gồm 12 ca recovery/gate/audit và 4 kiểm tra replay. Không tạo file test Python mới. Payload E và holdout cũ được đóng băng riêng để tiếp tục tái hiện lỗi trước sửa.

Run All offline hoàn tất: **155 test notebook pass**, toàn bộ 39 code cell thực thi thành công; **3 test helper pass**. Notebook vẫn được gitignore. `verification.json` lưu hash notebook/source và kết quả kiểm lại 649 raw; `code/` giữ snapshot mã của bản sửa.

Test kiểm ca raw thật, source ID/locator, ID không hợp lệ, thẻ không phải paragraph, class UI, answer không rỗng, boundary xen giữa, sibling answer, wrapper/outside container, subtree UI, paragraph phía sau, follow-up ownership, audit độc lập và gate từ chối record cũ/record sửa thiếu text. Export đọc lại Parquet và đối chiếu đúng tập candidate cùng text đã khôi phục.

Artifact: `runs/ask39_content_recovery649_20261022T104141135821Z`. Các file chính: `summary.json`, `manifest.json`, `parser_gate_diff.json`, `audits.json`, `raw/`, `records/`, `candidate.parquet`, `candidate.decisions.jsonl`.
