# Cnkang Q2 — glyph, encoding và bố cục legacy

Đã triển khai parser cnkang-v6-spec-6, rule cnkang-glyph-1 và helper
cnkang-article-3. Chỉ chuẩn hóa PUA có bằng chứng ngữ cảnh; giữ ký tự chưa xác
minh và raw/text_before để đối chiếu. Không sửa nội dung hoặc số liệu y khoa.

## Các ca mục tiêu

9 record: 8 có PUA, trong đó 2 có encoding uncertain, và 1 unknown layout.
Baseline là run Q1 đã đóng băng; các nhóm không phải 11 record độc lập.

| ID | Xử lý | Còn review Q2 |
|---|---|---|
| 1708607 | 6 U+E5E5 ở vị trí thụt đầu đoạn → khoảng trắng; giải thích được PUA ratio làm cờ encoding | Không |
| 1722395 | 1 U+E5E5 ở đầu đoạn có khoảng đệm → khoảng trắng | Không |
| 1723595 | 2 U+E5E5 sau br, giữa khoảng đệm đầu dòng → khoảng trắng | Không |
| 1728042 | 2 U+E5E5 sau hai nhãn một chữ “流”/“留”, có anchor trong tiêu đề → dấu cách phân nhãn | Không |
| 1772904 | 10 U+E5E5 đầu đoạn được chuẩn hóa; cặp U+E5E4…U+E5E5 giữa câu chưa rõ nghĩa được giữ | PUA + encoding uncertain |
| 1844705 | 3 U+F06C ở đầu ba mục p cùng cấp → bullet • | Không |
| 1850128 | 2 U+E004 ở cuối dòng/heading, chưa có bằng chứng font/glyph đủ chắc chắn | PUA |
| 1906646 | 1 U+E008 ở cuối đoạn, chưa có bằng chứng đủ để đổi thành ngắt dòng hoặc footnote | PUA |
| 1690503 | Xác minh ô thân bài legacy_table, heading/ngày và pager cùng bài | Thiếu trang tiếp; vẫn incomplete |

Kết quả mục tiêu: **PUA 8→3, encoding uncertain 2→1, unknown layout 1→0**.
24 glyph có bằng chứng được chuẩn hóa; 5 glyph còn lại giữ nguyên.
Không thay toàn bộ U+E5E5: trong 1772904, nó còn xuất hiện trong cặp ký tự
giữa câu, khác với vị trí thụt đầu đoạn. Không đoán cặp này là dấu ngoặc.

## Nguyên tắc triển khai

- Thụt đầu dòng chỉ áp dụng trong template đã biết, charset legacy GB và vị trí
  đệm có cấu trúc; không đổi PUA inline, UTF-8, glyph lạ hoặc PUA trong ô bảng.
  Dấu phân nhãn cần nhiều nhãn đầu đoạn khớp các chữ được trích trong title.
- Bullet được suy ra từ các mục CJK cùng cấp có cùng glyph đầu dòng; đây là
  bằng chứng cấu trúc của nguồn, không phải khẳng định mọi U+F06C là bullet.
  Glyph đơn lẻ, đứng giữa câu hoặc trước số/gene không được thay.
- glyph_normalization lưu rule, codepoint/ký tự gốc, thay thế, path tương đối
  trong body, field/offset, context/font style nếu có, hash trước/sau và glyph
  chưa giải thích. cleaning_actions chứa từng thay đổi. Audit tái lập tất cả.
- selected_encoding, declared_encoding và encoding_candidates gốc được giữ.
  encoding_uncertain_before_q2 cùng encoding_resolution giải thích quyết định.
  Chỉ gỡ uncertain khi nguyên nhân duy nhất là PUA ratio, strict decode phù hợp
  charset khai báo và toàn bộ glyph trong body đã được giải thích.
- Không cho PUA penalty âm thầm đổi bản decode theo charset khai báo thành
  CJK khác. Ca âm GB18030 có U+E111 từng bị Big5 thắng điểm nhưng mất ký tự
  gốc: nay giữ bản decode khai báo, lưu xung đột và giữ review.

## Bố cục 1690503

Raw có body tại td.style3 với class ID bài 107572, thuộc bảng nội dung thứ hai
trong cùng cột với bảng header thứ nhất. Header có span.style8 duy nhất, khớp
phần đầu HTML title; metadata cùng header có ngày và anchor về cnkang.
Không dùng style3 hoặc số class một mình để chọn body.

Heading: “去痘印的十三个不外传绝招”; ngày: 2008-4-26 10:36:43.
Selector và các path/ID anchor được lưu trong layout_evidence. Menu, tìm kiếm,
sidebar, bài liên quan và quảng cáo không thuộc ô body. Q1 không coi TD wrapper
này là bảng số liệu y khoa; list 3→2 trong body mới vẫn bị phát hiện.

Pager [1]/[2]/[3]/下一页 có liên kết 107572_2.html và 107572_3.html cùng bài;
F1 loại đúng khối pager. Văn bản compact còn lại khớp baseline sau trừ 12 ký
tự pager; chỉ có khác biệt ranh giới dòng từ DOM. F2 nhận next trang 2 nhưng
recovery offline không tải phần thiếu: article_complete=False,
article_reason=offline_missing_page. Không gọi bài này là toàn văn đã đạt.

## Kiểm chứng và hồi quy

**155/155 test đạt, 0 lỗi, 0 skip, 86,39 giây** trên Windows: 115 test cnkang
và 40 test tích hợp/hồi quy liên quan. Snapshot của main, domain samples và check
khớp production; các module nhúng ngoài phạm vi cnkang/core report/runner/auditor
giữ nguyên so với HEAD. File check tiếp tục được gitignore.

14 test Q2 với 9 raw fixture có SHA, kỳ vọng text/metadata cụ thể và ca âm:
glyph chưa biết, glyph trong gene/đơn vị/ô bảng, UTF-8, bullet đơn lẻ,
declared charset sai, chọn nhầm Big5, heading/ID/meta sai hoặc body trùng,
giữ review khi recovery thiếu trang, bằng chứng bị sửa và proof mọi trang
khi ghép toàn bài.

Replay offline 611 raw Q1 và 9 chuỗi/26 trang giữ nguyên các run nguồn.
Các thay đổi text chỉ được phép ở 7 ID đã chỉ rõ: 1690503, 1708607, 1722395,
1723595, 1728042, 1772904, 1844705. Oracle text độc lập với normalizer kiểm thứ
tự ký tự sau đúng các thay thế cho phép; không chỉ so số lượng ký tự.
Ngày/title, text_before, bảng và source DOM của các trang ngoài bố cục mới
được đối chiếu riêng. Formatter F1 giữ nguyên cho toàn bộ mẫu.

Kết quả test, audit, delta từng ID và hash snapshot cuối nằm trong artifact
nghiệm thu dưới đây. Đây là hồi quy đã biết, không phải gold/holdout độc lập,
không xác nhận nội dung nguồn đúng chuyên môn.

| Kiểm chứng | Kết quả |
|---|---:|
| Raw hash và audit mới | 611/611 |
| Encoding/declared charset/candidates giữ nguyên | 611/611 |
| Formatter F1 giữ nguyên | 611/611 |
| Text không đổi | 604/611 |
| Text đổi đúng oracle/whitelist | 7/611 |
| Metadata/text_before/bảng/source DOM giữ nguyên ngoài layout mới | 610/611 |
| Chuỗi phân trang ghép/audit/recovery đúng | 9/9 bài, 26 trang, 9.723 ký tự |
| Sạch parser / review parser | 531 / 80 |
| Clean → review | 0 |

5 record incomplete vẫn giữ review. 1690503 chuyển lý do unknown_layout sang
offline_missing_page; không đánh complete khi chưa có trang 2/3.
Cờ đánh số còn 15 thay vì 16 ở Q1 vì body 1690503 nay có phạm vi xác minh;
cờ lặp vẫn là 2. Source_flags chỉ đổi ở 1690503 do lấy lại heading và áp dụng
heuristic title/body đang có; Q2 không hiệu chỉnh heuristic nguồn của Q3.

## Artifact và phần còn lại

Thí nghiệm/code nhúng/output chỉ nằm trong file ignored
notebooks/check_cnkang.com.ipynb, phần Q2. Run nghiệm thu:
runs/cnkang_q2_20261020_pass2/; pass đầu được giữ riêng để bảo toàn bằng chứng.

- run_config.json: hash code, fixture, manifest F1 và baseline Q1.
- target_review.json: 9 record, action/glyph chưa rõ, charset/layout trước/sau.
- baseline_review.json, review_summary.json: đối chiếu đủ 611 record.
- f1_replay/, chains/, recovered_chains/: raw, checkpoint và manifest toàn bài.
- final_verification.json, test_results.txt: kết quả kiểm thử và hash 3 notebook.

Không gọi mạng bên ngoài, không tiếp tục 385 URL pending hoặc tải các trang
phân trang còn thiếu. Ba record PUA còn lại cần bằng chứng glyph/font bổ sung;
1772904 tiếp tục giữ encoding uncertain. Q3 chưa triển khai.
Đổi code cần run mới + recovery, không ép record/manifest cũ qua audit mới.
