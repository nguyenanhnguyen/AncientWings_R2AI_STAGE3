# Kế hoạch áp dụng kết quả cnkang vào crawler chính — 20/10/2026

Trạng thái: **F1, R1, R2, F2/F3, Q1, Q2 và Q3 report_only đã triển khai**,
parser cnkang-v6-spec-7, helper cnkang-article-4, policy cnkang-source-1.
F2/F3 replay 9/9 chuỗi, 26 raw, 9.723 ký tự khớp; 611/611 raw F1 giữ nguyên
text/hash và audit. Xem [review F2/F3](../reports/cnkang_f2_f3_review_20261020.md).
Lượt live F1 trước đó dừng ở 615/1.000 URL, có 611 raw và oracle JS 122/122 khớp;
Q1 QC theo cấu trúc: 47→16 cờ đánh số, 7→2 cờ lặp; 611 text/hash giữ nguyên,
141/141 test đạt. Xem [review Q1](../reports/cnkang_q1_review_20261020.md).
Q2: chuẩn hóa có bằng chứng 24 glyph, giữ 3 record PUA/1 encoding uncertain;
template legacy 1690503 đã có anchor, vẫn incomplete khi thiếu raw tiếp.
Xem [review Q2](../reports/cnkang_q2_review_20261020.md).
385 URL chưa chạy. Không tiếp tục run cũ. Q3: 179/179 test đạt, đủ 57 short text
có nhận xét, body 611/611 giữ nguyên. Còn nhãn độc lập trước enforce mặc định;
các chuỗi chưa đủ raw tiếp giữ incomplete/review. Xem [review Q3](../reports/cnkang_q3_review_20261021.md).

**Kế hoạch còn lại sau review 611 trang:** [cnkang_remaining_fixes_20261020.md](cnkang_remaining_fixes_20261020.md).
Đây là thứ tự ưu tiên hiện tại: R1 deadline mạng → R2 checkpoint → F2 kèm F3 →
Q1 cấu trúc danh sách/lặp đoạn → Q2 PUA/bố cục → Q3 metadata và gate nguồn.
Các phần F2–F4 bên dưới giữ mô tả kiến trúc; trạng thái nghiệm thu xem plan cập nhật và review.

Hướng đã chọn: **Requests tuần tự → parser DOM riêng → khôi phục `formattext` có bằng chứng → ghép trang có xác minh → audit toàn bài → gate nguồn riêng**.

Cơ sở: [review thí nghiệm](../reports/cnkang_experiments_review_20261020.md). Replay 521 trang, 85/85 ca khớp hàm JS gốc, 79 trang đổi thứ tự mà không mất ký tự; 9/9 chuỗi phân trang ghép được 17 trang mới. Những số này là mốc đối chiếu, không phải chỉ tiêu ép kết quả hoặc chứng nhận độ đúng y khoa.

## Phần áp dụng và phần giữ nguyên

| Phần | Quyết định | Ưu tiên |
|---|---|---|
| Requests, một worker, gap >= 1,5 giây, robots, retry/cooldown | Giữ; mọi trang tiếp đi qua cùng transport | Nền tảng |
| Quy tắc `formattext`/`jbk` đã xác minh | Đưa vào parser riêng, có provenance và trạng thái review khi cấu trúc lạ | F1 / P1 |
| Xóa pager đã xác minh | Đưa vào parser; tách phát hiện liên kết khỏi xóa text giao diện | F1 / P1 |
| Ghép trang theo cùng bài | Đưa vào transport/runner với checkpoint từng trang và trạng thái toàn bài | F2 / P1 |
| Audit lại từ raw của từng trang, recovery và snapshot | Bắt buộc đi cùng F1/F2 trước khi export | F3 / P1 |
| Tác giả từ byline, title/body, loại nguồn và claim quảng bá | Cải thiện có tập nhãn; gate riêng khỏi parser sạch | F4 / P2 |
| Selenium toàn domain, Node/JS runtime cho mỗi URL | Chưa đưa vào route mặc định; thí nghiệm không chứng minh cần thiết | Không áp dụng |
| Trích xuất trafilatura với cấu hình đã thử | Không thay parser riêng bằng cấu hình này; đã thấy menu lẫn vào text | Không áp dụng |
| Đảo đoạn theo số thứ tự, bỏ mọi cờ nguồn hoặc số bị reset | Không áp dụng; không có bằng chứng đủ để sửa tổng quát | Không áp dụng |

Sau F1, ưu tiên R1/R2 vận hành như plan cập nhật trước khi mở rộng crawl. F3 phải được thiết kế và nghiệm thu cùng F2, không chờ tới cuối mới thêm audit. F4 được cụ thể hóa thành Q1–Q3 và hiệu chuẩn trước khi bật gate nguồn.

## F1 — Khôi phục thứ tự và loại pager trong parser

**Điểm sửa:** `scripts/cnkang.py`; test production trong `tests/test_cnkang_v6_check.py` và/hoặc file test production riêng cho rule mới.

1. Parse lời gọi `formattext(count)`, script nguồn đã biết, vùng `jkpl` và tập khối `jbk`. Chỉ khôi phục khi đúng cấu trúc; ID trùng, khối lồng không rõ nghĩa, nhiều lời gọi hoặc script không khớp chuyển review, không âm thầm trả `accepted` từ DOM tĩnh.
2. Tái tạo đúng kết quả ghép `innerHTML` theo ID tăng dần. Chỉ xử lý các khối mà hàm website thực sự đọc; không sắp xếp lại mọi đoạn có số hoặc đảo cả bài.
3. Decode raw **một lần**, biến đổi cây DOM trong bộ nhớ, giữ encoding/declared charset/encoding evidence của nguồn. Không mang cách serialize UTF-8 ở thí nghiệm vào record production rồi làm mất thông tin GB2312/GB18030 gốc.
4. Lưu rule/version, hash bằng chứng JS, ID/thứ tự trước và sau, text/hash trước bước sửa trong sidecar. Giữ raw bất biến. Quy tắc production được port xác định; không tải JS hoặc chạy Node cho từng bài. Nếu gặp dạng lời gọi/source mới chưa xác minh thì review.
5. Phát hiện và lưu `pagination_candidates` trước khi loại pager. Chỉ xóa khối giao diện có mẫu đã xác minh và mọi link đúng cùng bài; không xóa toàn bộ câu có số hoặc anchor.
6. Tăng parser version, giữ hợp đồng cột corpus. Làm rõ `text_before`: nội dung sau khôi phục thứ tự, trước các bước làm sạch nội dung; DOM tĩnh cũ lưu riêng để đối chiếu.

**Nghiệm thu:**

- 85 ca có `formattext` vẫn khớp đầu ra hàm JS đã lưu; kiểm tra nội dung và thứ tự, không chỉ so số lượng ký tự.
- ID 1869305 đi ①→⑤; ID 1733228 bắt đầu bằng phần giới thiệu; ID 1780432 giữ đúng các nhóm nội dung.
- Không mất bảng/inline text hoặc phát sinh lỗi charset; trang không dùng cơ chế này không đổi text ngoài các pager có bằng chứng.
- Có fixture dương/âm cho nhiều lời gọi, script lạ, khối trùng/lồng, thiếu ID, pager giả và câu thật có số.

## F2 — Ghép toàn bài, checkpoint từng trang

**Điểm sửa chính:** `scripts/cnkang_transport.py` (`Transport.fetch`, `crawl`); chỗ gọi/đếm tiến độ trong `scripts/corpus_runner.py`; báo cáo trong `scripts/cnkang_check.py`.

1. Tách kết quả tải/parse **một trang** khỏi kết quả **toàn bài** để không lẫn `extracted` của trang đầu với bài hoàn chỉnh.
2. Xác minh next link: host thuộc cnkang cho phép, cùng path gốc/ID, đúng chỉ số kế tiếp, không query lạ, không loop. Xác minh lại sau redirect và sau parse: tiêu đề chuẩn hóa, template, ngày khi có ở cả hai trang, body không rỗng/không lặp. Khác biệt chưa được xác minh phải review.
3. Mọi request tiếp dùng cùng robots, session, một worker, gap, timeout, giới hạn dung lượng và cooldown. Bắt đầu với `max_pages=6` như thí nghiệm, thêm budget toàn bài; chạm giới hạn khi còn next link là trạng thái chưa hoàn tất.
4. Lưu raw/checksum/URL cuối/metadata/status từng trang trước khi tiếp tục; manifest chỉ rõ thứ tự, hành động loại pager và phần overlap đã bỏ. Cache mỗi trang theo danh tính URL và checksum, không chỉ theo ID corpus.
5. Một record nguồn vẫn giữ **ID và URL corpus gốc**. Trang tiếp là thành phần của bài, không tự sinh ID corpus. Nếu corpus có riêng URL `_2.html`, không âm thầm coi chuỗi từ trang 2 là toàn văn: đánh dấu cần xác minh trang gốc, giữ ánh xạ ID/URL và xử lý trùng bài ở gate tương ứng.
6. Ghép theo thứ tự đã xác minh; chỉ bỏ overlap đuôi/đầu đoạn khớp chính xác. Kiểm QC lại toàn bài, giữ cờ lỗi thực của các trang thành phần. Không để `SHORT_TEXT` của một trang ngắn tự động loại bài đầy đủ đã ghép.
7. Lỗi giữa chuỗi giữ đủ phần đã tải và checkpoint để resume; `article_complete=False`, không export như bài hoàn chỉnh. 429 phải dừng/lưu cooldown; resume không tải lại trang đã có raw hợp lệ.
8. `MAX_NEW` và tiến độ chính đếm record nguồn mới, không đếm trang phụ như ID corpus mới. Bổ sung riêng số request, trang thành phần, bài hoàn chỉnh/chưa hoàn chỉnh/review.

**Nghiệm thu:**

- 9 bài đã biết tái dựng đúng 26 trang, bỏ 5 pager đã xác minh; giải thích mọi khác biệt với mốc 9.723 ký tự.
- Không ghép bài khác/nhảy trang/vòng lặp/redirect sai hoặc body trùng; không accepted khi chuỗi bị cắt do lỗi/budget.
- Test ngắt sau mỗi bước ghi raw/manifest/record và resume xác nhận không GET lại phần hợp lệ, không mất hoặc lặp text, giữ cooldown.
- ID/URL/cột corpus không đổi; tải trang phụ không làm tăng nhầm `MAX_NEW`.

## F3 — Audit, recovery và đồng bộ notebook chính

**Điểm sửa:** `scripts/cnkang.py:audit`, `scripts/corpus_audit.py`, `scripts/cnkang_transport.py`, `scripts/corpus_runner.py`, `scripts/cnkang_check.py`, `scripts/build_cnkang_notebooks.py`.

1. Audit nhận manifest/raw **tất cả trang**; kiểm checksum và quan hệ trang, tái trích từng phần, áp quy tắc thứ tự/loại pager/overlap rồi ghép. Không audit bài ghép chỉ bằng raw trang đầu hoặc dùng text record làm nguồn chứng minh.
2. Thiếu raw, đổi thứ tự/hash/identity hoặc ghép khác text phải fail audit; không được export `accepted`. Case âm phải bao gồm sửa text một trang thành phần, thiếu trang và đánh dấu complete sai.
3. Run cũ dùng `RUN_TAG` mới và `RECOVERY_RUN_PATH`. Reuse raw hợp lệ và tái trích bằng phiên bản mới, không sửa record/code của run đã lưu. Copy cooldown; các trang tiếp chưa có mới được tải trong chế độ crawl.
4. `POSTPROCESS_ONLY` không gửi request. Thiếu trang tiếp thì ghi chưa hoàn chỉnh/review; không báo complete để vượt gate.
5. Sau khi parser/transport/audit đạt test, build lại snapshot vào `crawl_corpus_kaggle_hf_upload.ipynb` và `crawl_domain_samples.ipynb`. Kiểm hash, version và diff để tránh ghi đè những thay đổi domain khác đang có trong workspace.
6. Hai notebook chính dùng cùng parser/rule và cùng contract manifest; không tạo một parser khác chỉ chạy tốt trong notebook check.

**Nghiệm thu:** audit từ raw khớp toàn bộ record mới, mọi test tampering bị chặn; recovery không crawl lại phần đã lưu; hash snapshot khớp code; các domain khác không thay hành vi.

## F4 — Metadata và gate nguồn

Q3 được cụ thể hóa trong [kế hoạch gate nguồn ngày 21/10/2026](cnkang_q3_source_gate_20261021.md),
gồm short text, vai trò metadata, title–body, claim theo ngữ cảnh và các đường
export/audit/resume. Đã triển khai report_only và kiểm các đường enforce bằng
fixture; còn đánh giá nhãn độc lập trước khi bật enforce mặc định.

**Điểm sửa dự kiến:** metadata/QC trong `scripts/cnkang.py`; record/summary và policy export ở tầng runner/audit hiện có. Có thể tách policy module khi cần; không trộn logic thí nghiệm vào runtime production.

- Lấy tác giả từ byline/DOM có bằng chứng, giữ tên, chức danh, cơ sở, vị trí DOM và mức xác minh. Thiếu meta author không đồng nghĩa không có tác giả.
- Thay heuristic khớp nguyên câu chữ Hán bằng tín hiệu phù hợp tiếng Trung; chọn ngưỡng trên tập gán nhãn thủ công, không chọn theo tỷ lệ accepted tăng.
- Giữ riêng trạng thái fetch, độ đúng trích xuất và mức phù hợp nguồn. Thiếu ngày/tác giả là tín hiệu chưa xác minh theo policy đã chốt; không tự chặn 100% domain dựa vào cờ meta author hiện tại.
- Claim quảng bá/trải nghiệm cá nhân/bài tin tức được giữ bằng chứng và phân loại riêng. Không tự loại mọi bài `/xinwen/` hoặc `/dzjk/` chỉ từ path; cũng không đưa vào train chỉ vì parser sạch.
- Cờ đánh số giảm do bắt đầu danh sách mới vẫn review cho đến khi có quy tắc cấu trúc và test chứng minh; không xóa cờ toàn cục.

**Nghiệm thu:** có tập nhãn và bảng lỗi trước/sau cho tác giả/title-body/loại nguồn; mọi quyết định giữ/review/loại có lý do và bằng chứng; không tuyên bố xác minh y khoa bằng heuristic.

## Kiểm chứng trước khi mở rộng crawl

1. Unit/integration test production cho F1–F3, gồm cả crash/resume, kiểm `MAX_NEW`, thiếu phần, robots và 429.
2. Replay cùng 521 raw để lập diff theo ID; ưu tiên đọc mọi thay đổi ngoài nhóm rule dự kiến, không chỉ báo tổng số accepted.
3. Replay 9 chuỗi đã có đủ 26 raw, audit toàn bài; đọc mẫu đầu/cuối/biên trang, bảng, encoding và provenance.
4. Chạy holdout mới khoảng 100 URL phân tầng theo các nhánh/template và nhóm rủi ro, loại mọi manifest lịch sử đã biết. Nhánh không đủ URL mới phải ghi số thiếu; lịch sử chưa đủ vẫn không được gọi là holdout hoàn toàn chưa từng test.
5. Chỉ mở rộng sau khi không còn mismatch nội dung/audit hoặc bài ghép sai chưa giải thích. Báo riêng độ phủ lấy mẫu, fetch, parse, complete, parser review và source review. Không đặt số accepted tối thiểu làm điều kiện đạt.

## Tổ chức phần thí nghiệm theo yêu cầu hiện tại

- Chỉ một file làm việc: **`notebooks/check_cnkang.com.ipynb`**, đã có rule `.gitignore`.
- Code/helper, output A/B/C và 10 test thí nghiệm nhúng trong phần cuối notebook; có thể chạy phần này độc lập trên raw đã lưu.
- Không giữ notebook thí nghiệm/đã chạy hay script runner/helper rời trong `notebooks/`, `scripts/`, `tests/`. Bản cũ chuyển vào `runs/cnkang_experiments_20261020/consolidation_backup/`, thuộc vùng output đã ignore, để giữ bằng chứng.
- Builder chỉ tạo một check và bảo toàn các cell local có tag `cnkang-local-experiments`; không nhúng code thí nghiệm vào repo hoặc tái sinh file check thứ hai. Trên checkout mới không có file local này, builder vẫn tạo check baseline; kế hoạch và báo cáo giữ trong Git.
- Khi triển khai F1–F4, code/rule/test **production** mới đi vào Git như bình thường; yêu cầu ignore chỉ áp dụng khu vực thí nghiệm local và output.
