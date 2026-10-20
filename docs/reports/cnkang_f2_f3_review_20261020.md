# Cnkang F2 + F3 — phân trang, checkpoint và audit toàn bài

Đã triển khai vào production: parser cnkang-v6-spec-4 và cnkang-article-1.
Crawler chính, domain samples và check dùng chung transport/helper. F1 tiếp tục
khôi phục formattext và loại pager có bằng chứng trước khi ghép từng phần.

Kết quả: **9/9 bài, 26/26 trang ghép và audit đúng**, hash text khớp toàn bộ
thí nghiệm cũ; replay **611/611 raw F1 giữ nguyên text/hash và qua audit**.
Đây là kiểm tra offline trên dữ liệu đã biết, không phải holdout mới hoặc live.

## Thay đổi

- Chỉ đi theo next trong pager đã xác minh thuộc bài: cùng host/path gốc, số
  trang liên tiếp; kiểm redirect, heading, template, ngày khi có và body trùng.
  Link ngoài phạm vi, query lạ, nhảy số/vòng lặp và pager mâu thuẫn giữ review.
- Mỗi trang có raw gzip/HTML, SHA-256 và checkpoint riêng. Manifest cuối cùng
  cùng bản chụp checkpoint dùng tên theo hash; progress có thể cập nhật mà không
  làm hỏng bằng chứng của record đã commit trước đó.
- Trang phụ không sinh ID corpus, không làm tăng MAX_NEW. URL nguồn bắt đầu
  ở trang 2 trở đi không được gọi là toàn bài.
- Ghép theo thứ tự; chỉ bỏ đoạn biên khớp nguyên văn, dài ít nhất 20 ký tự.
  Lưu phần bỏ và số đoạn, không xóa đoạn giống nhau ở vị trí tùy ý.
  QC được tính lại trên toàn bài; các cờ cấu trúc còn lại vẫn được giữ.
- Audit đọc lại mọi raw và checkpoint, tự suy ra chuỗi từ pager trong HTML,
  tái dựng text/overlap/QC. Thiếu phần, thay hash/thứ tự, sửa text hoặc đánh
  complete sai đều chặn publication/export. Bỏ manifest cũng không vượt gate.
- Resume reuse trang đã commit và response chưa commit theo cơ chế R2; recovery
  sang run mới tái trích mọi raw hiện có. Thiếu raw trang tiếp chỉ giữ review,
  không gọi mạng trong postprocess/recovery.

Mặc định tối đa 6 trang/bài; deadline mạng toàn chuỗi 360 giây, tiếp tục chịu
45 giây/request và 120 giây/URL. Hết giới hạn, lỗi giữa chuỗi, 403/429 hoặc
challenge đều giữ bằng chứng từng phần, lý do dừng và state/cooldown.
Không chuyển sang Selenium để vượt chặn.

## Replay 9 chuỗi thật

Fixture: tests/fixtures/cnkang_pagination/manifest.json, 26 HTML gốc có hash.
So sánh với hash merged text đã đóng băng từ thí nghiệm pagination trước khi
triển khai production; audit production là kiểm tái lập, không phải nhãn gold.

| ID | Trang | Ký tự compact | Kết quả parser |
|---|---:|---:|---|
| 1816933 | 2 | 2.016 | accepted |
| 1994369 | 3 | 807 | accepted |
| 1993675 | 3 | 1.135 | accepted |
| 1993984 | 2 | 536 | accepted |
| 1993608 | 4 | 1.185 | accepted |
| 1993904 | 4 | 1.511 | accepted |
| 1993625 | 2 | 749 | accepted |
| 1684761 | 3 | 1.211 | review: DESCENDING_NUMBERING_REVIEW |
| 1993751 | 3 | 573 | accepted |
| **Tổng** | **26** | **9.723** | **8 accepted, 1 review** |

17 trang phụ được ghép; 5 pager có bằng chứng bị loại đúng như F1.
9/9 bài recovery sang thư mục riêng vẫn đủ phần, hash giống nhau và tự audit
được mà không phụ thuộc đường dẫn tuyệt đối của run nguồn.

## Hồi quy 611 raw F1

Run cũ runs/cnkang_f1_1000_20261020 được giữ nguyên. Tái trích vào
runs/cnkang_f2_f3_20261020/f1_replay: 611/611 raw hash, text hash và audit khớp.
Quyết định parser giữ nguyên **492 accepted / 119 review**, không có record đổi
quality_status. 606 record được xác định là bài một trang; 5 record chưa đủ
bằng chứng toàn bài:

| ID | Lý do còn incomplete |
|---|---|
| 1851609, 3529935, 3530118 | offline_missing_page: chỉ có raw đầu, chưa tải trang tiếp |
| 1690503 | unknown_layout: chưa xác minh biên bài, chờ Q2 |
| 1405611 | previous_page_mismatch: URL gốc nhưng raw có “上一页” trỏ tới _6.html và pager 3–6 |

1405611 trước đây chỉ mang SHORT_TEXT_REVIEW. F2 phát hiện thêm pager mâu thuẫn,
giữ nguyên text và thêm ARTICLE_INCOMPLETE_REVIEW/PAGINATION_REVIEW; không đoán
rằng URL gốc là trang đầu đầy đủ. Cả 5 vẫn review và qua audit ở trạng thái
chưa hoàn chỉnh. Qua audit không đồng nghĩa được công bố là bài đầy đủ.

## Kiểm chứng và bằng chứng

21 test phân trang/audit kiểm raw thật, overlap, title/date/template/body sai,
scope/redirect/host/query sai, vòng lặp/nhảy số, trang nguồn không phải trang 1,
cap/deadline, crash sau commit trang 2, resume không GET lại trang đã lưu,
403/429, raw/checkpoint/hash bị sửa, bỏ manifest và export.

**128/128 test đạt, 0 lỗi, 0 skip, 84,461 giây** trên Windows. Bao gồm 88 test
cnkang và 40 test tích hợp/hồi quy liên quan. Test tích hợp thực sự đi qua runner → accepted corpus → auditor và route
domain samples. Mất raw trang 2 làm audit/export dừng. Bộ kiểm F1/R1/R2 vẫn
được chạy cùng với kiểm report/postprocess/resume và snapshot dùng chung.
Chi tiết từng test nằm trong final_verification.json và test_results.txt của run
dưới đây. Hash snapshot của cả ba notebook khớp production; các module nhúng
không thuộc cnkang/core report/runner/auditor giữ nguyên so với HEAD.

Toàn bộ config/code nhúng/output thí nghiệm nằm trong một file ignored:
notebooks/check_cnkang.com.ipynb, phần F2 + F3. Artifact đầy đủ:

- runs/cnkang_f2_f3_20261020/run_config.json: hash code, fixture và manifest F1.
- runs/cnkang_f2_f3_20261020/review_summary.json: tổng hợp và 5 case incomplete.
- runs/cnkang_f2_f3_20261020/chains_review.json, baseline_review.json: đối chiếu từng ID.
- runs/cnkang_f2_f3_20261020/chains, recovered_chains, f1_replay: raw/checkpoint/manifest tự đủ bằng chứng.
- runs/cnkang_f2_f3_20261020/final_verification.json: test và hash snapshot production.

Lượt replay mất 175,996 giây, **0 request mạng bên ngoài**.
Các notebook kiểm code/hash trước resume; code đổi phải dùng run mới + recovery.

## Giới hạn và phần còn lại

Chưa live ba chuỗi mới chỉ có raw đầu; chưa thực hiện Q1–Q3 hoặc xác nhận chất
lượng y khoa/nguồn. Next link phải có bằng chứng trong phạm vi template đã biết;
cấu trúc lạ giữ review. 385 URL pending của manifest F1 không được chạy thêm.
Không dùng kết quả này để tuyên bố đã kiểm đủ 1.000 URL.
