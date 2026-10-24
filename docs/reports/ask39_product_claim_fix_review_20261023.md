# ask.39.net — bước 3: phương pháp/sản phẩm cụ thể + claim (23/10/2026)

**Đã sửa 2249721, 2252713, 2381257: cả ba chuyển accepted → REVIEW.** Replay 200 raw: candidate **194 → 191**, REVIEW **6 → 9**. Text, ID, parent, 269 answer, 21 follow-up và 3 metadata đánh giá giữ nguyên hoàn toàn. Chưa F6 hoặc production.

## Thay đổi

Chỉ `scripts/ask39_gate.py` thay đổi trong logic xử lý. Parser, audit, helper crawl, DNS và transport pack giữ nguyên hash so với bước 2. Gate mới `ask39-gate-v6-named-product-claims`; rule `ask39-named-product-claims-v1`. Không nới eligibility hoặc sửa dữ liệu nguồn. Builder chỉ thêm cơ chế giữ snapshot gate bước 2 cho các test lịch sử và giữ cell mới.

Rule nhận diện có chủ đích các họ tên đã quan sát: **人参皂苷Rh2 / G35 / 护命素** và **韩氏疼痛治疗仪 / 韩氏治疗仪**. Sản phẩm phải đi cùng claim chống khối u/ung thư, đảo ngược kháng thuốc hoặc ngăn tái phát/di căn. Thiết bị phải đi cùng claim an toàn tuyệt đối như “没有任何毒副作用”, “无副作用”, “零风险”. Chỉ liệt kê tên, nói về thuốc chung hoặc một thiết bị không nằm trong coverage này không tự phát sinh rule mới; đây chưa phải bộ thẩm định tất cả sản phẩm y tế.

Hai source flag mới: `source_named_product_efficacy_review` và `source_named_device_safety_review`. Flag chỉ tạo từ lời **responder**, không từ câu hỏi, follow-up bệnh nhân hoặc metadata đánh giá. Tách rule mới giúp replay kiểm rõ mọi source flag/evidence cũ giữ nguyên.

Ghép phương pháp và claim trong cùng câu, với khoảng cách giới hạn; claim đứng trước method phải có liên kết rõ như “的是/的药物是…”. Cụm chỉ năng lực bệnh nhân như “抗癌能力减退” không được coi là claim hiệu quả sản phẩm. Chỉ kế thừa một câu trước khi có tham chiếu rõ “该产品/该设备…”, không vượt newline hoặc dấu chấm phẩy, không kế thừa danh sách nhiều phương pháp mơ hồ. Có kiểm đổi chủ thể sang phương pháp khác. Phủ định, câu hỏi, lời người khác được thuật lại, trích dẫn, claim chưa được chứng minh/đang nghiên cứu hoặc lời phản bác sẽ được lưu assessment `suppressed` cùng lý do, không tạo flag REVIEW mới. Claim an toàn có qualifier “通常/一般…” không được coi là tuyệt đối.

Attribution của lời thuật lại được kiểm trên phạm vi câu, kể cả đoạn dài trước tên sản phẩm; polarity dùng cửa sổ cục bộ để không lấy phủ định của điều trị khác ở xa làm phủ định claim mới. Dấu chuyển ý rõ như “但我认为…” có thể mở khẳng định mới của responder. Rule này phân loại nguồn cần review, không phán quyết đúng/sai lâm sàng.

## Bằng chứng ba ca thật

| ID | Answer ID | Sản phẩm/thiết bị | Claim | Method span / claim span |
| --- | --- | --- | --- | --- |
| 2249721 | `ask39:39195186:answer:90902012` | 人参皂苷Rh2(护命素) | 抗肿瘤 | `[277, 289]` / `[299, 302]` |
| 2249721 | `ask39:39195186:answer:90902012` | 人参皂苷Rh2(护命素) | 逆转肿瘤细胞耐药性 | `[277, 289]` / `[308, 317]` |
| 2252713 | `ask39:40729058:answer:95412806` | 韩氏疼痛治疗仪 | 没有任何毒副作用 | `[174, 181]` / `[204, 212]` |
| 2381257 | `ask39:94816498:answer:254304019` | 人参皂苷G35 | 防止术后肿瘤的复发和转移 | `[102, 109]` / `[150, 162]` |

Span là offset ký tự trong `answer.text`, kiểm slice chính xác và đối chiếu raw tại body locator. Evidence có `answer_id`, `message_id`, role, locator, method/claim/quote và span tương ứng; ledger `resolved_findings_evidence.json` bổ sung corpus ID, URL và raw SHA-256. Ca Rh2 có thể có nhiều evidence vì cùng narrative chứa hai claim khác nhau; không tính thành nhiều trang.

Ba ca vẫn **extraction accepted**, không có parser/audit flag; chỉ source QC chuyển REVIEW. Sáu REVIEW cũ giữ nguyên. Các candidate có thông tin chức danh/policy pending không tự được giải quyết bởi rule sản phẩm này.

## Test và replay

**26 test notebook mới pass**: 22 test tập trung và 4 test replay/export, cùng **3 helper test hiện có pass**. Test mới nằm trong cell tag `ask39-fix-product-claims` ở [notebook check](../../notebooks/check_ask.39.net.ipynb), vẫn gitignore. Không tạo file unit test Python mới. Lượt này không chạy lại toàn bộ các section lịch sử; mỗi section cũ giữ code snapshot riêng và builder kiểm syntax/hash.

Test bao phủ raw thật và source IDs/spans; biến thể tên sản phẩm/claim; an toàn tuyệt đối; phủ định trước phương pháp/trước claim/sau claim; trích dẫn nhiều kiểu; thuật lại lời bệnh nhân/nhà quảng cáo/bác sĩ khác/tài liệu; câu thuật lại dài; patient/unknown role; câu hỏi; chuyển chủ thể; giới hạn câu/paragraph; tham chiếu rõ câu trước; qualifier/chưa có bằng chứng; phản bác; tên gần giống; liệt kê thuốc; thứ tự claim trước method; khẳng định mới sau chuyển ý. Test tích hợp raw bảo đảm claim nằm trong follow-up bệnh nhân hoặc metadata đánh giá không bị gắn thành lời bác sĩ. Các rule safety/CTA/superlative cũ được kiểm lại độc lập trên các ca đại diện.

Replay đủ **200 raw của holdout gần nhất** với bản sửa UI và metadata bước 1–2. Chỉ ba quyết định QC nêu trên thay đổi. Toàn bộ 200 record nguồn giữ nguyên mọi field dữ liệu; parser replay khớp mọi field. Không đổi text, source text, metadata, answer/message ID, parent hoặc thứ tự.

Export candidate mới đọc lại raw và tính gate lại: đúng **191 ID**, loại cả ba ca khỏi parquet, 6 REVIEW cũ cũng không được export. Mọi text/hash trong candidate khớp record. 200 quyết định export khớp hoàn toàn replay, gồm source evidence và audit. Mọi record vẫn `corpus_eligible=False`; production export = 0.

Không gửi request mới, không thay mẫu hoặc ghi đè artifact trước đó. Đây chưa phải replay toàn bộ 850 raw hoặc holdout xác nhận bản mới.

## Artifact và trạng thái kế tiếp

Run: `runs/ask39_product_claim_fix_20261022T203942735710Z`.

- `results.jsonl`, `raw/`: đủ 200 record/raw giữ nguyên, gồm metadata đánh giá đã tách.
- `gate_decisions.json`, `decision_diff.json`: mọi quyết định và đúng ba thay đổi QC.
- `resolved_findings_evidence.json`: bằng chứng method/claim và raw hash cho ba ca.
- `candidate.parquet`, `candidate.decisions.jsonl`: 191 candidate local và quyết định export kiểm lại raw.
- `code/`, `manifest.json`, `summary.json`, `verification.json`: code/hash, thống kê và kiểm chứng.

**Readiness: `FIX_3_PASSED_POLICY_REVIEW_AND_REPLAY850_PENDING`.** Bước 3 đã đạt tiêu chí; F6 vẫn chờ xử lý policy/chuyên môn cho **2203052, 2407658, 2459843**, replay toàn bộ **850 raw**, rồi đóng băng và kiểm holdout **200 URL mới loại đủ 850 URL cũ**, review mọi lỗi/REVIEW, template và 20 accepted ngẫu nhiên. Các pending source chưa có phê duyệt con người; không coi 191 candidate là tập đã được release.
