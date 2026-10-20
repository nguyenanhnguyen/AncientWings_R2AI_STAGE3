# Kiểm lại toàn bộ hạng mục cnkang — 21/10/2026

**Chưa fix hết: R1, R2, F2/F3, Q1, Q2 và hồi quy F1 đạt bộ test hiện có;
Q3 mới có kế hoạch, chưa triển khai và chưa đủ điều kiện nghiệm thu.**
Các cờ còn lại không được mặc định là lỗi parser hoặc tự gỡ để tăng accepted.
Lượt này chỉ kiểm thử, tái trích/audit từ raw và ghi báo cáo; không sửa production.

## Kết quả chạy mới

- **155/155 test đạt**, 0 failure, 0 error, 0 skip, 91,196 giây trên Windows.
  Có chạy test khóa file bằng Windows kernel, process exit, DNS/read treo và
  kiểm worker không còn chạy/không trả kết quả muộn sau deadline.
- **611/611 record Q2 đạt audit bằng code production hiện tại**: kiểm raw hash,
  text hash và tái trích nội dung/provenance. Kết quả parser vẫn 531 accepted,
  80 review; 606 complete và 5 incomplete.
- **9/9 chuỗi, 26 trang đạt audit**, giữ 9.723 ký tự compact. Test phân trang
  cũng chạy mới việc ghép từ 26 raw fixture, kiểm từng merged hash và 5 pager.
  Đây là tập fixture riêng, không cộng thành số URL mới đã crawl.
- **122/122 ca F1 khớp oracle JavaScript** đã ghim SHA-256, đối chiếu HTML
  tích lũy và việc ẩn các block gốc; không tải hoặc chạy JavaScript từ mạng.
- **21/21 phép so snapshot khớp production** cho main/domain/check và
  runner/auditor liên quan. Bốn phần tích hợp cnkang trong core main/domain
  khớp AST: loader, extract, quality và nhánh audit trong report.

Không gọi mạng website, không chạy lại mẫu live 50 URL, không tiếp tục 385 URL
pending. Kiểm raw mới có chặn worker/Requests gửi mạng và ghi nhận 0 lời gọi.
Hash code và các file tổng kết baseline không đổi trong quá trình audit.

## Đánh giá theo hạng mục

| Hạng mục | Bằng chứng kiểm mới | Kết luận và giới hạn |
|---|---|---|
| R1 — deadline | 10 test trong module deadline, gồm snapshot; DNS/header/body treo, reset, cause gốc, clock jump, redirect/budget, worker lỗi | Đạt trên Windows. Không suy ra DNS ngoài môi trường đã hết lỗi; deadline cần OS lập lịch supervisor. Kaggle/Linux chưa được chạy trực tiếp trong lượt này. |
| R2 — checkpoint Windows | 19 test: replace tạm thời/vĩnh viễn, khóa Windows thật, crash, recovery/ZIP, một writer, giữ cooldown, không GET lại do lỗi ghi | Đạt bộ nghiệm thu hiện có. |
| F2 + F3 — phân trang/audit | 21 test chuyên mục, cộng tích hợp notebook/domain và audit raw; thiếu/sửa phần, nhảy bài, vòng lặp, giới hạn trang/thời gian, resume | Cơ chế đạt fixture/audit. 5 bài thực tế vẫn incomplete; chưa thể gọi toàn bộ dữ liệu là đã đủ toàn văn. |
| Q1 — cấu trúc | 13 test scope DOM, danh sách lồng/lượt đáp/bảng, lặp cùng hoặc khác scope, ca âm và tampering | Rule có bằng chứng đạt; còn 15 cờ đánh số và 2 cờ lặp trên baseline Q2, giữ review. Chưa có tập nhãn độc lập để kết luận mọi cờ còn lại là đúng/sai. |
| Q2 — glyph/encoding/layout | 14 test với 9 raw fixture, bảo vệ ký hiệu/số/bảng, decoder, layout anchor và audit; replay 611 record | Unknown layout 0; còn 3 record PUA, trong đó 1 encoding uncertain. Đạt các sửa đổi đã có bằng chứng, chưa giải quyết hết glyph chưa rõ. |
| Q3 — gate nguồn | Kiểm code, inventory 57 short text, ví dụ thật và 3 probe ngữ cảnh tổng hợp | Chưa triển khai: chưa có policy module, fixture Q3, source_decision hoặc policy version. Không có test Q3 để kết luận đạt. |
| F1 — hồi quy | 11 test chuyên mục, 122 oracle JS và audit 611 raw | Đạt; giữ thứ tự formattext và quy tắc loại pager có bằng chứng. |

Các số test chuyên mục không phải toàn bộ 155: còn test parser/check/notebook
và 40 test tích hợp dùng chung. Danh sách module/count có trong artifact.

Core main/domain không giống toàn bộ byte vì còn khác UA/TRUST_ENV, PubMed và
cách cache kiểm hash raw ngoài phạm vi cnkang. Phép so toàn core không được
dùng để tuyên bố chúng đồng nhất; module production cnkang và bốn nhánh tích
hợp nêu trên đã được kiểm riêng. Không sửa khác biệt ngoài phạm vi trong lượt này.

## Những phần còn giữ review

**5 bài incomplete:** 1690503, 1851609, 3529935, 3530118 thiếu raw trang tiếp;
1405611 có previous-page mismatch. Cả 5 đều review, không được accepted như
bài toàn văn. Test offline xác nhận cách xử lý phần thiếu; chưa tải các phần đó.

**Q1:** cờ đánh số 47 ban đầu còn 15 sau Q1+Q2; cờ lặp 7 còn 2. Tại riêng
bước Q1 là 16 cờ đánh số; Q2 xác minh body 1690503 nên giảm thêm 1. Đây là các
tín hiệu còn phải đọc, không phải 17 lỗi chắc chắn cần xóa.

**Q2:** 1772904 giữ cặp U+E5E4…U+E5E5 cùng encoding uncertain; 1850128 giữ
hai U+E004, 1906646 giữ một U+E008. Tổng 5 glyph chưa rõ được bảo toàn.
1690503 đã xác minh layout nhưng vẫn thiếu trang tiếp.

## Q3 còn thiếu cụ thể

1. **Short text:** vẫn đủ 57 cờ, phân bố compact 19 dưới 50, 7 từ 50–99,
   31 từ 100–199. Hai bài 1405611/3530118 incomplete. Đã xuất inventory theo ID,
   hash và completeness; chưa gán nhãn độc lập hoặc đánh giá đủ 57 bài theo
   policy nguồn. Không coi inventory là nghiệm thu chất lượng short text.
2. **Metadata:** extract vẫn chỉ lấy author từ meta. 1544618 có người trả lời
   trong body nhưng chưa có attributions phân vai trò. AUTHOR_UNAVAILABLE_REVIEW
   vẫn xuất hiện ở 611/611 record; không thể suy ra cả 611 bài không có tác giả.
3. **Title–body:** còn khớp nguyên cụm tiếng Trung, tạo 368 cờ. 1782034 vẫn bị
   cờ dù có nội dung cùng chủ đề; chưa có đánh giá coverage/ngram trên tập nhãn
   đóng băng. Ca này là ứng viên fixture, không phải nhãn gold độc lập.
4. **Claim:** vẫn regex từ khóa. Ba probe tổng hợp — phủ định, trích rồi bác bỏ,
   khẳng định kèm lời mời mua — đều nhận cùng PROMOTIONAL_CLAIM_REVIEW, chưa có
   phân loại chủ thể/stance/ngữ cảnh. Đây không phải bằng chứng parser tự loại
   nhầm bài: hiện chúng chỉ tạo cờ review, chưa có source gate để KEEP/EXCLUDE.
5. **Quyết định corpus:** 0/611 record có source_decision hoặc policy version;
   chưa có scripts/cnkang_source_gate.py, fixture manifest hoặc test Q3 dự kiến.
   Có 17 claim flag, 4 experience flag; hợp nhóm parser accepted có một trong
   hai loại là 16 bài. Các số này là tín hiệu, chưa phải nhãn nguồn xấu.

Bộ 155 test đều đạt vì kiểm những phần đã triển khai; nó không chứng minh các
yêu cầu Q3 chưa có code đã được đáp ứng. Bước còn lại theo
[kế hoạch Q3](../plans/cnkang_q3_source_gate_20261021.md): nhãn/fixture → metadata
→ title–body → claim theo ngữ cảnh → policy báo cáo → kiểm độc lập trước enforce.

## Artifact

Output mới tại runs/cnkang_full_verification_20261021/, đã gitignore:

- [Test summary](../../runs/cnkang_full_verification_20261021/test_summary.json),
  [log](../../runs/cnkang_full_verification_20261021/test_results.txt) và
  [count theo module](../../runs/cnkang_full_verification_20261021/test_module_counts.json).
- [Audit summary](../../runs/cnkang_full_verification_20261021/saved_raw_audit.json)
  và [kết quả theo ID](../../runs/cnkang_full_verification_20261021/saved_raw_audit_cases.jsonl).
- [Oracle F1](../../runs/cnkang_full_verification_20261021/f1_js_oracle.json) và
  [snapshot checks](../../runs/cnkang_full_verification_20261021/snapshot_verification.json).
- [Q3 gaps/probes](../../runs/cnkang_full_verification_20261021/q3_gap_review.json)
  và [inventory 57 short text](../../runs/cnkang_full_verification_20261021/short_text_inventory.json).

Không thêm file thí nghiệm rời hoặc đổi notebook check; một file check ignored
hiện có tiếp tục là nơi thí nghiệm khi triển khai Q3. Báo cáo này là tài liệu
kiểm chứng, không đánh dấu Q3 done và không thay kết quả lịch sử.
