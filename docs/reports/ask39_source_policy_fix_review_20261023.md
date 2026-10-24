# ask.39.net — bước 4: nguồn tổ chức và ca pending (23/10/2026)

**Đã áp dụng QC theo yêu cầu:** 2203052 không còn accepted dựa vào nhãn `医师`; 2407658 và 2459843 chuyển REVIEW, giữ hold chờ thẩm định chuyên môn. Replay 200 raw: candidate **191 → 188**, REVIEW **9 → 12**. Không thay text, ID, parent hoặc metadata. Chưa F6 và chưa hoàn tất thẩm định y khoa hai ca pending.

## Policy nguồn tổ chức

Gate mới `ask39-gate-v7-organization-specialist-holds`, policy `ask39-organization-specialist-holds-v1`. Tên tài khoản thể hiện rõ tổ chức (制药/药业/药厂, công ty/tập đoàn, bệnh viện/cơ sở y tế, hiệp hội/quỹ) tạo `source_organization_author_review`, dù nhãn chức danh nằm trong allowlist. Đây là yêu cầu review danh tính nguồn, không phải kết luận tác giả giả mạo hoặc sản phẩm có hại.

Chỉ xét **author_name**, không gắn cờ chỉ vì bác sĩ cá nhân có affiliation công ty dược/bệnh viện hoặc nhắc tên công ty trong nội dung. Policy không cần chờ xuất hiện một tên sản phẩm đã biết mới nhận diện account tổ chức. Những account tổ chức này cần review riêng, không được xác minh thành bác sĩ cá nhân chỉ bằng text nhãn `医师`.

Ca **2203052**, answer `ask39:13841623:answer:409078532`: tác giả **汉森制药**, nhãn `医师`, affiliation `湖南汉森制药股份有限公司`, body giới thiệu `四磨汤口服液`. Rule mới đọc dấu hiệu `制药` trong tên tài khoản, lưu quote/span trên field author_name, qualification nguồn, answer ID và locator. Không xóa hoặc chỉnh nội dung nguồn.

Hai ca **2203214 — 玉林制药** và **2264689 — 强身药业** vốn đã REVIEW do chức danh thiếu; giờ có thêm evidence tổ chức. Không tính đây là hai thay đổi quyết định QC mới. Trên mẫu 200 này có đúng ba account mang dấu hiệu tổ chức ở author_name.

## Hold chuyên môn

| Corpus ID | URL nguồn | Source answer | Trạng thái |
| --- | --- | --- | --- |
| 2407658 | `https://ask.39.net/question/_4n3605.html` | `ask39:_4n3605:answer:170477078` | REVIEW — pending_specialist_review |
| 2459843 | `https://ask.39.net/question/_u5h605.html` | `ask39:_u5h605:answer:170473746` | REVIEW — pending_specialist_review |

`source_specialist_review_pending` đến từ registry rõ ràng `PENDING_SPECIALIST_REVIEWS` trong code đóng băng. Đây là hai ca đã được xác định cần thẩm định, không phải regex kết luận mọi nội dung về vaccine/kháng thể/HBsAg là sai hoặc phải REVIEW.

Hold gắn với canonical URL path trên ask.39.net, không phụ thuộc corpus ID, scheme HTTP/HTTPS hay query. Registry ghi source answer ID, raw hash và quote tham chiếu từ mẫu đã review. Evidence ghi quote/span hiện quan sát được, raw hash hiện tại, raw hash tham chiếu và `source_unchanged`.

Nếu raw/body hoặc answer ID thay đổi, hold vẫn giữ để review lại; không giả vờ quote cũ còn nằm trong nội dung mới. Khi không tìm thấy quote hoặc answer cũ, quote/span/locator quan sát được để null phù hợp, reference cũ vẫn lưu riêng. Các field untrusted như `quality_status=accepted`, `candidate_eligible=True`, `review_resolved=True` hoặc `specialist_review_status=approved` không gỡ hold.

Chưa có kết luận chuyên môn và chưa có giải phóng hai hold. Việc giải phóng sau này cần cập nhật policy có phiên bản, kèm bằng chứng thẩm định và test; không tự thực hiện trong bước này. Cả hai ca vẫn được trích xuất nguyên văn để reviewer kiểm tra.

## Kiểm thử và replay

**16 test mới trong notebook pass** (12 tập trung + 4 replay/export), cùng **3 helper test hiện có pass**. Test nằm trong cell tag `ask39-fix-source-policy` của [notebook check](../../notebooks/check_ask.39.net.ipynb), vẫn gitignore; không tạo unit test Python mới. Snapshot gate bước 3 được giữ riêng cho section cũ. Không chạy lại toàn bộ section lịch sử trong lượt này.

Test bao phủ ba raw thật; organization name/title/evidence; tên bác sĩ cá nhân có affiliation công ty; account tổ chức không còn nêu sản phẩm; hold với source mới hoặc answer mới; URL/ID scoping; không dùng từ khóa vaccine để block chung; cached acceptance/untrusted approval không vượt gate; export với ba target gắn sẵn accepted vẫn xuất **0 candidate**; các rule chức danh và sản phẩm trước đó vẫn giữ hiệu lực.

Replay 200 raw của holdout gần nhất giữ nguyên toàn bộ field của record và tái lập parser chính xác: **269 answer + 21 follow-up + 3 metadata đánh giá**. Chỉ QC của **2203052, 2407658, 2459843** đổi accepted → REVIEW. Tổng 5 trang có evidence mới: ba trang này và hai account tổ chức vốn đã REVIEW (2203214/2264689). **195 quyết định còn lại khớp hoàn toàn bản trước**, ngoại trừ gate version. Evidence và flag cũ của cả 200 trang được giữ nguyên.

Export đọc lại raw, tính gate lại và xuất đúng **188 ID** local; ba target bị loại, 9 REVIEW cũ vẫn bị loại. Mọi text/hash trong parquet khớp nguồn; 200 quyết định export khớp replay đầy đủ. Mọi record vẫn `corpus_eligible=False`, production export = 0. Không gửi request mới; raw và artifact cũ giữ nguyên hash.

## Artifact và bước kế tiếp

Run: `runs/ask39_source_policy_fix_20261023T063211825074Z`.

- `results.jsonl`, `raw/`: đủ 200 record/raw giữ nguyên.
- `gate_decisions.json`, `decision_diff.json`: ba QC thay đổi và hai evidence bổ sung trên REVIEW cũ.
- `source_review_queue.json`: quote/locator/hash và trạng thái của 5 source cần review theo policy mới.
- `candidate.parquet`, `candidate.decisions.jsonl`: 188 candidate local và quyết định export.
- `code/`, `manifest.json`, `summary.json`, `verification.json`: code/hash và kiểm chứng. Chỉ gate thay đổi trong năm file xử lý chính; parser/audit/helper/DNS giữ nguyên.

**Readiness: `SOURCE_POLICY_APPLIED_REPLAY850_PENDING`.** Bước 4 đạt yêu cầu giữ REVIEW; chưa phải chuyên môn đã duyệt. Tiếp theo replay toàn bộ **850 raw**, giải thích mọi thay đổi text/ID/parent/QC, rồi đóng băng và kiểm **200 URL mới loại đủ 850 URL cũ** trước khi xét F6. Hai hold chuyên môn tiếp tục tồn tại qua replay/export trong thời gian chờ thẩm định.
