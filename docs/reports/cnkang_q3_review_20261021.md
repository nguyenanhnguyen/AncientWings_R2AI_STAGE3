# Cnkang Q3 — metadata và gate nguồn, 21/10/2026

Đã triển khai parser cnkang-v6-spec-7, helper cnkang-article-4 và policy
cnkang-source-1 vào main, domain samples và file check. **Mặc định report_only**:
có quyết định nguồn/corpus và bằng chứng, giữ hành vi export parser hiện tại.
Chưa bật lọc cứng mặc định vì chưa có tập nhãn độc lập 80/40 theo kế hoạch.

**179/179 test đạt**, 0 failure/error/skip, 139,226 giây trên Windows. Có 23 test
Q3 mới và thêm một test tích hợp main/domain so với bộ 155 trước đó. 21 raw
fixture có SHA-256, ca tổng hợp dương/âm và inventory nhận xét đủ 57 short text.
Nhãn đọc nguồn do agent đề xuất, không phải gold y khoa hoặc đánh giá độc lập.

## Phần đã sửa và cách nghiệm thu

| Phần | Thay đổi production và fixture | Kết quả kiểm |
|---|---|---|
| Short text | Đo sau ghép; tách incomplete, câu hỏi thiếu đáp, rất ngắn cần ngữ cảnh và nguồn ngắn cần đọc. Giữ ngưỡng 200 và text gốc. Fixture 1716739/1792421/1889767, 1606857, 1622860, ca ghép và thiếu trang. | 57/57 có text/hash/selector, phân loại, nhận xét đọc nguồn và lý do. Không gỡ SHORT_TEXT_REVIEW. |
| Metadata | Meta/byline trong vùng bài, attributions có role/path/quote/institution/title. Phân biệt author/reviewer/respondent/quoted_person; trang sau không ghi đè tác giả trang đầu. | 6 test metadata; 1544618 nhận 陈勇 là respondent, 1827470 nhận 胡孟彩. Sidebar, lời trích và heading không thành tác giả; sửa tên/vai trò/path bị audit chặn. |
| Title–body | Bigram/coverage tiếng Trung và tín hiệu intent; thiếu heading, thiếu từ khóa, chỉ trùng chủ đề và mismatch có trạng thái riêng. Tính lại trên toàn bài. | 1782034 không cần lặp nguyên title. Tráo body, cùng chủ đề nhưng sai câu hỏi, title chung chung và đoạn liên quan ở trang 2 có ca âm/dương. Ngưỡng 0,5 mới kiểm fixture, chưa hiệu chuẩn độc lập. |
| Claim/trải nghiệm | Span trên text nguyên vẹn, page/paragraph/path/speaker, phân biệt phủ định, trích dẫn bác bỏ/tán thành/chưa rõ, câu hỏi, mô tả có điều kiện, khẳng định và CTA. | Giữ review ca 1740065; 1516530 có mô tả điều kiện. 1441624/1524726/1836347/1946477 có phủ định; 1759215 là biên từ 葛根, 1998448 là thuật ngữ phẫu thuật. Lời nhắc đừng mua và người được trích không tạo EXCLUDE nhầm. |
| Gate/audit/resume | Module source riêng; source_decision và corpus_decision không thay quality_status. Snapshot/hash policy, chế độ bền vững, audit tái lập từ mọi raw trước export. | Main/domain/check và POSTPROCESS_ONLY dùng cùng policy. Enforce bị chặn khi đổi mode trên cache cũ; fixture source EXCLUDE không vào corpus.accepted nhưng vẫn giữ raw/record. |

EXCLUDE tự động chỉ áp dụng khi có claim tuyệt đối được khẳng định và CTA rõ
trong cùng đoạn. Chưa rõ thì REVIEW. Thiếu meta author riêng lẻ là thông tin
chưa xác minh, không tự loại toàn domain. KEEP là ứng viên theo policy, không
xác nhận tính đúng chuyên môn.

## Replay và hồi quy

Baseline là runs/cnkang_q2_20261020_pass2. Lượt cuối dùng raw/checkpoint đã dựng
ở lượt staging, tái trích/audit bằng snapshot cuối, không gửi request. 606 bài
một trang giữ raw/text đã lưu, chỉ tính lại record; 5 chuỗi incomplete và 9 chuỗi
fixture được phục hồi bằng transport offline. Không tiếp tục 385 URL pending.

| Kiểm | Kết quả |
|---|---:|
| Raw hash/text hash và audit 611 record | 611/611 khớp baseline |
| Formatter/pager F1, encoding/candidates, parser flags/quality | 611/611 giữ nguyên |
| Title/date/source cũ, text_before/source DOM/bảng, Q1/Q2 evidence | 611/611 giữ nguyên |
| Oracle JavaScript F1, bảo toàn byte JS đã ghim | 122/122 |
| Chuỗi phân trang và audit | 9/9 bài, 26 trang, 9.723 ký tự compact |
| Snapshot production trong ba notebook, runner/auditor | 24/24 khớp |
| Bài complete / incomplete | 606 / 5, giữ nguyên |
| Parser accepted / review | 531 / 80, giữ nguyên |

5 incomplete vẫn là 1405611, 1690503, 1851609, 3529935 và 3530118; không bài
nào thành corpus KEEP. Cờ Q1 còn 15 đánh số/2 lặp, Q2 còn 3 PUA/1 encoding
uncertain; Q3 không che hoặc gỡ các cờ này.

## Kết quả nguồn trên 611 record

| Lớp quyết định | KEEP | REVIEW | EXCLUDE |
|---|---:|---:|---:|
| source_decision | 399 | 212 | 0 |
| corpus_decision, kết hợp parser/completeness | 384 | 227 | 0 |

Đây là các quyết định đề xuất trong report_only. Export mặc định vẫn theo
parser; không trình bày 384 ứng viên là corpus đã được kiểm nhãn độc lập.
9 chuỗi fixture riêng có 4 source/corpus KEEP và 5 REVIEW, không cộng vào số
URL mới đã crawl. Không bắt buộc có EXCLUDE trong mẫu để chứng minh gate hoạt động.

| Tín hiệu nguồn | Q2 | Q3 |
|---|---:|---:|
| AUTHOR_UNAVAILABLE_REVIEW | 611 | 611 |
| TITLE_BODY_ALIGNMENT_REVIEW | 368 | 185 |
| PROMOTIONAL_CLAIM_REVIEW | 17 | 9 |
| PERSONAL_EXPERIENCE_REVIEW | 4 | 13 |
| CONTEXTUAL_REPETITION_REVIEW | 2 | 2 |
| SOURCE_UI_CONTAMINATION_REVIEW | 0 | 1 |

301 record đổi tập source flag; từng ID có diff. Các tổng trên là số tín hiệu,
không phải precision/recall hoặc số lỗi đã chữa. PERSONAL tăng vì nhận diện
trải nghiệm từ văn bản; từ gọi “网友/楼主” không còn tự đồng nghĩa trải nghiệm.
Thêm 5 attribution respondent ở 4 record, không tự gán chúng làm article_author.

## Đánh giá 57 short text

| Nhóm | Số bài | Cách xử lý |
|---|---:|---|
| Bài chưa đủ trang | 2 | 1405611/3530118: incomplete; chưa kết luận nguồn ngắn thật |
| Câu hỏi không có đáp được xác minh | 1 | 1606857: giữ review; không lấy title/bài khác để bù |
| Rất ngắn, cần thêm ngữ cảnh | 19 | Giữ text và review; gồm câu trả lời 5/6/7 ký tự |
| Nguồn ngắn cần kiểm nguồn/ngữ cảnh | 35 | Phân biệt mô tả, Q&A, checklist, kinh nghiệm, lời giới thiệu và UI trong nhận xét theo ID |

1833833 chứa navigation/search UI: thêm SOURCE_UI_CONTAMINATION_REVIEW, giữ text
để mở việc xử lý extraction riêng có bằng chứng. Các ca như 1783463 kết bằng
heading chưa triển khai, 1898628 là lời kể kèm sản phẩm, 1889863 dẫn tới trung tâm
tư vấn được ghi nhận riêng. Không coi mọi short text là lỗi crawler, không tự
loại tất cả và không tuyên bố nội dung y khoa đúng/sai từ heuristic.

## Giới hạn và artifact

Chưa có nhãn độc lập 80 dev/40 test; chưa báo confusion matrix chất lượng nguồn
trên holdout hoặc hiệu chuẩn ngưỡng. Fixture hiện là dev/regression đã biết,
phân biệt real/synthetic và nguồn nhãn. Enforce có code và test đường lọc, nhưng
mặc định tiếp tục report_only cho đến khi nghiệm thu phần nhãn trong
[kế hoạch Q3](../plans/cnkang_q3_source_gate_20261021.md).

Thí nghiệm/code/output chỉ ở notebooks/check_cnkang.com.ipynb, đã gitignore.
Hai lượt đầu ô check dừng do record_dir và cách đọc newline của JS ghim; giữ
artifact cũ, dùng pass3 làm kết quả cuối. Đây là lỗi ô thí nghiệm; raw/baseline
không đổi. Fixture/test/code production và tài liệu được track.

Run cuối: runs/cnkang_q3_20261021_pass3/.

- [final_verification.json](../../runs/cnkang_q3_20261021_pass3/final_verification.json),
  [test_summary.json](../../runs/cnkang_q3_20261021_pass3/test_summary.json) và
  [test_results.txt](../../runs/cnkang_q3_20261021_pass3/test_results.txt).
- [review_summary.json](../../runs/cnkang_q3_20261021_pass3/review_summary.json),
  [baseline_review.json](../../runs/cnkang_q3_20261021_pass3/baseline_review.json) và
  [source_flag_changes.json](../../runs/cnkang_q3_20261021_pass3/source_flag_changes.json).
- [short_text_review.json](../../runs/cnkang_q3_20261021_pass3/short_text_review.json):
  đủ 57 ID, text, hash, selector, trạng thái, nhận xét và lý do.
- [Fixture Q3](../../tests/fixtures/cnkang_q3/manifest.json) và
  [nhận xét 57 nguồn ngắn](../../tests/fixtures/cnkang_q3/short_text_reading.json).
