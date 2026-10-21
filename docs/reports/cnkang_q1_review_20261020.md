# Cnkang Q1 — QC theo phạm vi cấu trúc

Đã triển khai cnkang-v6-spec-5, rule cnkang-structure-1 và helper toàn bài
cnkang-article-2. Q1 chỉ thay QC/provenance: **không đảo đoạn, xóa câu lặp hoặc
thay số, liều lượng, bảng hay nội dung nguồn**.

## Kết quả đối chiếu

Replay offline cùng 611 raw của F1, so với bản F2/F3 đã đóng băng. Đây là tập
hồi quy đã biết; chưa phải gold hoặc holdout độc lập do người đánh giá xác nhận.
47 cờ đánh số và 7 cờ lặp thuộc 53 record vì một record có cả hai.

| Chỉ số | Trước Q1 | Sau Q1 |
|---|---:|---:|
| DESCENDING_NUMBERING_REVIEW | 47 | 16 |
| REPEATED_PARAGRAPH_REVIEW | 7 | 2 |
| Record sạch parser | 492 | 526 |
| Record còn review parser | 119 | 85 |
| Clean → review | — | 0 |
| Review → clean | — | 34 |

31/47 cờ đánh số được gỡ theo phạm vi/kiểu số; 5/7 cờ lặp được phân loại lại.
Không có cờ mục tiêu mới. Những cờ giữ lại là ca cần review, chưa khẳng định
đều là lỗi thứ tự hoặc duplication thật.

611/611 raw hash, text/hash, text_before, encoding, title/date, bảng,
cleaning_actions và provenance F1 giữ nguyên; audit 611/611 khớp.
5 bài incomplete của F2/F3 vẫn chưa đủ toàn văn, không chuyển thành accepted.

## Rule và bằng chứng

- Ánh xạ từng dòng render về DOM, lưu path, heading/emphasis, list/depth,
  ô bảng và label lượt trả lời. Chỉ dùng scope khi toàn bộ dòng khớp chính xác;
  không đoán bằng matching một đoạn sau khi synopsis bị cắt. Unknown/không khớp
  tiếp tục dùng QC bảo thủ.
- Giữ các frame danh sách cha/con theo kiểu marker. Trở lại marker cha không
  so số với phần tử cuối của danh sách con. Dấu chấm/fullwidth và “、” của cùng
  cấp Arabic được so trong cùng chuỗi, tránh gỡ nhầm khi chỉ đổi dấu.
- Xét outline 6.2.4 → (1)/(2) → 6.3 và list DOM riêng. Heading, đoạn in đậm
  nguyên dòng, nhãn người trả lời có anchor hoặc nhãn nhóm rõ ràng mới tạo
  scope. Dòng ngắn thông thường hay một từ in đậm giữa câu không đủ.
- Không coi số đo thập phân, liều lượng hoặc giá trị trong ô bảng là thứ tự
  danh sách. Width normalization chỉ phục vụ nhận diện marker, không sửa text.
- Dòng phân cách chỉ có dấu câu không phải đoạn văn lặp; giữ nguyên trong text.
  Một đoạn lặp dưới các heading khác nhau chuyển sang tín hiệu nguồn
  CONTEXTUAL_REPETITION_REVIEW. Lặp cùng scope/không rõ scope hoặc lặp cả khối
  liên tiếp vẫn có REPEATED_PARAGRAPH_REVIEW.
- Sau ghép phân trang, QC chạy lại trên cấu trúc toàn bài, bỏ đúng context của
  overlap đã xác minh. Không tự tạo scope mới chỉ vì sang trang. Audit tái dựng
  và so cả qc_structure, cờ và quyết định từ raw.

Heading dạng đoạn in đậm có giới hạn 80 ký tự, heading mục đánh số 60 ký tự;
đây là heuristic bảo thủ, chưa hiệu chuẩn trên tập nhãn độc lập 80/40 trong
plan. Các trường hợp mơ hồ vẫn cần người đọc nguồn; không diễn giải số sạch
parser thành chất lượng y khoa hoặc nguồn đạt chuẩn.

## Những ca đã kiểm

| ID | Quyết định và bằng chứng |
|---|---|
| 1782034 | Gỡ cờ đánh số: các mục 1)/2)/3)/4) có danh sách con dùng 1./2.; không đổi trình tự DOM. |
| 1544618 | Gỡ cờ đánh số: nhãn strong của bệnh nhân và người trả lời từ bệnh viện xác định lượt mới. |
| 1461617 | Gỡ cờ: “一、非手术治疗” và “二、手术治疗” chứa các danh sách con riêng. |
| 1512877 | Gỡ cờ: outline có cấp 6.2.4, nhóm (1)/(2), rồi trở lại 6.3. |
| 1541173 | Gỡ cờ: các số thập phân trong bảng đo lường bị QC cũ hiểu nhầm thành item list. |
| 1759215 | Giữ đủ 4 lần đoạn xét nghiệm dưới 4 nhóm; bỏ cờ parser, thêm CONTEXTUAL_REPETITION_REVIEW. |
| 1669081 | Đoạn hướng dẫn được lặp dưới các loại chấn thương khác nhau; giữ nguyên và thêm tín hiệu nguồn để đọc lại. |
| 1468122, 1871903 | Gỡ cờ lặp đối với dòng dấu chấm phân cách. Không chứng nhận nội dung các trang này là nguồn tốt. |
| 1840464 | Giữ các dòng gạch trống của bài tập; không coi chúng là paragraph duplication. |
| 1902464 | Giữ cờ lặp: 6 đoạn xuất hiện nguyên khối hai lần trong raw; không tự dedup. |
| 1769931 | Giữ cờ lặp: scope của lần xuất hiện đầu chưa đủ anchor để kết luận lặp theo nhóm. |
| 1874785, 1739129, 1503459 | Giữ cờ đánh số: chuyển 6/3/5 → 1/2 chưa có scope đủ chắc chắn hoặc item 1 dính trong đoạn. |
| 1690503 | Unknown layout: giữ QC bảo thủ và incomplete, chờ Q2 xác minh thân bài. |

Các ID còn cờ đánh số: **1503459, 1612259, 1690503, 1739129, 1744453,
1786685, 1791587, 1798181, 1801031, 1814866, 1874785, 1910550, 1913516,
1957760, 3374458, 3520043**. Không gỡ toàn bộ vì nhiều nhãn nhóm vẫn trộn trong
câu, thiếu markup hoặc chưa rõ quan hệ danh sách. Chúng vẫn được xuất ở review.

## Kiểm chứng

13 test Q1, dùng 16 fixture HTML thật có SHA và kỳ vọng được ghi rõ, cùng ca âm:
3→2→1 trong cùng nhóm, đổi dấu/fullwidth, số cha giảm sau danh sách con, bold
không được che lỗi, scope chưa xác minh, khối lặp có heading, sửa bằng chứng,
synopsis bị cắt và lỗi thứ tự đi qua biên trang. Fixture không được tạo từ text
đã sửa; không dùng nhãn do rule vừa chạy sinh ra làm kỳ vọng test.

**141/141 test đạt, 0 lỗi, 0 skip, 89,774 giây** trên Windows: 101 test cnkang
và 40 test tích hợp/hồi quy liên quan. Bộ kiểm cuối gồm toàn bộ F1/R1/R2/F2/F3/Q1 và các kiểm tích hợp report, export,
audit, postprocess, resume, domain route và snapshot. Kết quả cụ thể ở
final_verification.json/test_results.txt trong run nghiệm thu. Hash snapshot của
cả ba notebook khớp production, các module nhúng ngoài phạm vi cnkang/core
report/runner/auditor giữ nguyên so với HEAD.

Replay 9 chuỗi/26 trang vẫn khớp **9.723 ký tự**, audit/recovery 9/9.
1684761 gỡ cờ đánh số sau khi xác minh heading mới “牛奶+蔬果断食” trước list
bắt đầu lại ở 1; 9/9 bài nay sạch parser. Đây là thay đổi QC có bằng chứng,
không phải xác nhận các claim dinh dưỡng/giảm cân trong bài.

## Artifact và giới hạn

Thí nghiệm/code nhúng/output chỉ nằm trong notebooks/check_cnkang.com.ipynb,
gitignored, phần Q1. Giữ cả pass đầu và pass cuối với điều kiện ánh xạ DOM chặt
hơn. Run nghiệm thu: **runs/cnkang_q1_20261020_pass2/**:

- run_config.json: hash parser/helper, fixture, manifest F1 và summary F2/F3.
- review_summary.json: thống kê và ID cờ giữ/gỡ/thêm.
- target_review.json: 53 record mục tiêu, quyết định/evidence từng ID.
- baseline_review.json: đối chiếu đủ 611 record.
- f1_replay/, chains/, recovered_chains/: raw/checkpoint/manifest tự đủ bằng chứng.
- final_verification.json, test_results.txt: kiểm thử và hash snapshot của 3 notebook.

Không gọi mạng bên ngoài, không tiếp tục 385 URL pending hoặc tải trang thiếu.
Các run F1/F2/F3/R1/R2 vẫn được giữ nguyên. Khi dùng code mới, tạo run mới +
RECOVERY_RUN_PATH; record/manifest phiên bản cũ không được ép qua audit mới.
Q2 và Q3 chưa triển khai. Source flags giữ riêng; parser accepted vẫn chỉ là
ứng viên cho bước review/gate nguồn tiếp theo.
