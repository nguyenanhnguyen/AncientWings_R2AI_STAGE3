# ask.39.net — replay toàn bộ 850 raw và audit độc lập (23/10/2026)

**REPLAY850_PASSED_FRESH_HOLDOUT_PENDING.** Replay đủ **850 raw**, giữ **1.103 answer + 71 follow-up**, tách đủ **4 đánh giá bệnh nhân** thành metadata. Không đổi answer/message ID, parent, role hoặc thứ tự thật. Không có audit flag hoặc thay đổi chưa giải thích được. Candidate local **811**, REVIEW **39**; chưa F6/production.

## Inventory và code đóng băng

850 raw = replay độc lập 649 trang cũ + supplement đúng slot 2458259 + 200 raw holdout mới. Có 850 corpus ID và 850 URL duy nhất, không thay URL khi lỗi và không gửi request mới. Hash raw đã kiểm đủ trước parser, audit, gate và đối chiếu lại export. Inventory giữ record và quyết định nguồn theo từng cohort, original root/raw path và raw SHA-256; manifest pin năm file xử lý và hash các artifact nguồn trước/sau.

Parser giữ `ask39-parser-v2-patient-evaluations`; helper crawl và DNS không đổi. Source policy giữ nguyên bước 4. Gate chỉ tăng version thành `ask39-gate-v8-independent-audit-integrity` để ghi nhận audit mới; đã so source gate với bản bước 4, chỉ khác version string. Audit mới `ask39-independent-audit-v3-render-roles`.

## Audit độc lập được tăng cường

Audit tự đọc raw DOM, không gọi parser:

- Answer phải có role responder; đổi sang patient để né QC bị `answer_speaker_role_mismatch`.
- Follow-up phẳng đối chiếu role từ nhãn zw1 và parent từ container raw; đổi cả bản phẳng lẫn bản lồng vẫn bị phát hiện.
- Bản `answer.followups` phải khớp toàn bộ message phẳng đã kiểm DOM, không chỉ khớp locator. Sai role/text/parent trong riêng bản lồng bị `followup_nested_message_mismatch`.
- Dựng lại clinical rendering từ raw question/answer/follow-up, sau khi loại đúng node UI/metadata. Chèn UI hoặc đổi nhãn người nói chỉ trong record.text bị `raw_rendered_text_mismatch`.
- Các kiểm node i.hfu, metadata span.pingjia, source identity và missing text trước đó vẫn giữ. Từ “回复” trong nội dung thật không bị coi là UI chỉ vì trùng chữ.

Đây là sửa điểm mù của kiểm độc lập; trên 850 record được parser hiện tại tạo lại, audit không phát hiện mismatch. Test đối kháng xác minh audit thực sự từ chối các bản record đã cố tình làm sai, không dùng “audit pass” trên dữ liệu sạch làm bằng chứng duy nhất.

## Mọi thay đổi text và cấu trúc

| ID | Thay đổi clinical text | Giữ lại |
| --- | --- | --- |
| 2205416 | Tách span.pingjia | Lời bác sĩ đầy đủ; đánh giá `askB67PB：谢谢你` trong metadata |
| 2207135 | Tách span.pingjia | Lời bác sĩ đầy đủ; đánh giá `askR5S9J：谢谢` trong metadata |
| 2207389 | Tách span.pingjia | Lời bác sĩ đầy đủ; đánh giá `askH1IUJ：谢谢医生！` trong metadata |
| 2207574 | Cùng dạng span.pingjia, phát hiện trong 649 raw cũ | Lời bác sĩ `您好，老年人因为血管弹性变低，所以压差增大很正常`; đánh giá `askSIMT7：哦 谢谢了 赵医生` trong metadata |
| 2211175 | Bỏ nút i.hfu ẩn khỏi follow-up | Câu bệnh nhân, source_text, parent và thứ tự giữ nguyên |

Chỉ **5 trang đổi rendered text/hash**; 845 trang còn lại giữ nguyên text. Có đúng **4 answer** đổi clinical text do chuyển đánh giá metadata; **1 follow-up** đổi text do loại nút UI. Không mất câu hỏi, answer hay message thật. Source text vẫn giữ nguyên để truy vết.

1.103 answer đều có field `patient_evaluations`: 4 list có nội dung, 1.099 list rỗng. Đây là thêm schema, không phải thêm answer. So sánh theo source answer ID và source message ID xác nhận **0 thay đổi ID/parent/role/order**. Body locator, header tác giả, qualification và identity evidence giữ nguyên.

`dom_exclusions` có đúng 5 node mới: 4 `patient_evaluation_metadata` và 1 `followup_reply_control`; không xóa hoặc sửa exclusion cũ. Nhiều leaf diff của array chỉ do thêm phần tử làm dịch index; đã đối chiếu lại theo locator để không hiểu nhầm thành hàng trăm thay đổi nội dung.

Các thay đổi root còn lại đều đã gắn explanation: parser version của 850 record; trạng thái/flags parse candidate-only (818 status và 849 flag list khác snapshot nguồn), không phải quyết định gate; 201 raw_path được đặt lại trong run mới nhưng raw bytes/hash không đổi; char_count/text_sha256 đi theo đúng 5 thay đổi text. Ledger lưu mọi leaf path trước/sau, không bỏ qua diff ID/parent.

## Mọi thay đổi QC

Có hai mốc so sánh để không gộp lịch sử với thay đổi mới:

| Mốc | Candidate trước → sau | REVIEW trước → sau | Số trang đổi quyết định |
| --- | --- | --- | --- |
| Các snapshot nguồn gốc (649 + supplement + holdout200 ban đầu) | 819 → 811 | 31 → 39 | 8 |
| Kết quả mới nhất đã biết (200 trang đã có fix bước 4) | 813 → 811 | 37 → 39 | 2 |

| ID | Chuyển từ snapshot gốc | Lý do |
| --- | --- | --- |
| 2203052 | accepted → REVIEW | Account 汉森制药 dù nhãn 医师; đã xử lý bước 4 |
| 2223058 | accepted → REVIEW | Account 汉森制药, nhãn 医师, affiliation công ty dược; body giới thiệu 四磨汤口服液. Phát hiện khi replay 649 raw cũ |
| 2249721 | accepted → REVIEW | Rh2/护命素 + claim chống khối u/đảo ngược kháng thuốc; đã xử lý bước 3 |
| 2252713 | accepted → REVIEW | 韩氏疼痛治疗仪 + claim không có độc/tác dụng phụ; đã xử lý bước 3 |
| 2364781 | accepted → REVIEW | Account 汉森制药 dù body không cần nêu sản phẩm; policy danh tính tổ chức không phụ thuộc có quảng bá. Phát hiện khi replay 649 raw cũ |
| 2381257 | accepted → REVIEW | G35 + claim ngăn tái phát/di căn; đã xử lý bước 3 |
| 2407658 | accepted → REVIEW | Hold thẩm định chuyên môn; đã xử lý bước 4, chưa được giải phóng |
| 2459843 | accepted → REVIEW | Hold thẩm định chuyên môn; đã xử lý bước 4, chưa được giải phóng |

Đã đối chiếu raw/answer/header và evidence của cả 8 thay đổi, gồm 2 ca tổ chức mới. Không có REVIEW → accepted hoặc mất source flag cũ. Hai account 2203214/2264689 vốn đã REVIEW vì chức danh thiếu có thêm evidence tổ chức so với snapshot ban đầu; đây không phải đổi quyết định.

39 trang REVIEW là source QC; không có trang bị REVIEW do thiếu answer/follow-up hoặc audit thất bại. Phân bố flag có giao nhau: `{"source_absolute_safety_claim_review": 4, "source_qualification_unrecognized": 21, "source_organization_author_review": 5, "source_promotion_signal": 2, "source_specific_method_superlative_review": 1, "source_consultation_cta_review": 1, "source_treatment_claim_review": 2, "source_named_product_efficacy_review": 2, "source_named_device_safety_review": 1, "source_specialist_review_pending": 2}`. Hai hold chuyên môn tiếp tục REVIEW; replay không thay thế thẩm định y khoa hoặc phê duyệt con người.

## Test và export

**20 test mới trong notebook + 3 helper hiện có pass.** Test mới ở cell tag `ask39-replay850` của [notebook check](../../notebooks/check_ask.39.net.ipynb), vẫn gitignore. Fixture nhúng đủ 850 raw để replay offline; không tạo file unit test Python mới. Các section cũ giữ snapshot riêng. Lượt này chạy lại audit và gate cho đủ 850 raw trong test, không chạy lại toàn bộ section lịch sử của notebook.

Test kiểm inventory/hash, mọi source ID/parent, ledger text/QC, metadata, audit 850 raw, gate 850 quyết định, 811 candidate, hold chuyên môn; cộng các mutation sai role answer, role phẳng+lồng, chỉ bản lồng, sai parent, thêm UI cả hai message copy, UI/nhãn sai chỉ trong rendering, đánh giá bị gắn sang responder và ca âm tính giữ từ 回复. Kiểm độc lập không gọi parser.

Export đọc lại raw và tính gate lại: đúng **811 candidate local**, không có 39 REVIEW. Mọi text/hash khớp record và tất cả quyết định export khớp fresh replay đầy đủ. `audit_version` là metadata mới; `audit.baseline_qc` vẫn phản ánh input parse review, không dùng làm QC quyết định. Toàn bộ record `corpus_eligible=False`, production = 0.

## Artifact và bước kế tiếp

Run: `runs/ask39_replay850_20261023T064737462472Z`.

- `inventory.json`, `manifest.json`, `raw/`, `records/`, `results.jsonl`: provenance và dữ liệu replay.
- `page_diff.json`, `field_explanations.json`, `unexplained.json`: mọi leaf diff, explanation và danh sách chưa giải thích (rỗng).
- `answer_mapping.jsonl` (1.103 dòng), `followup_mapping.jsonl` (71 dòng): source identity/parent và text trước/sau.
- `dom_exclusion_changes.json`, `qc_change_explanations.json`: 5 node cleanup và toàn bộ thay đổi QC/evidence.
- `audits.json`, `gate_decisions.json`, `candidate.parquet`, `candidate.decisions.jsonl`: audit/gate/export.
- `code/`, `summary.json`, `verification.json`: code pin hash, kết quả máy và sign-off review. Summary fixture giữ trạng thái trước sign-off; verification ghi trạng thái cuối `REPLAY850_PASSED_FRESH_HOLDOUT_PENDING`.

Tiếp theo: đóng băng bản hiện tại, chọn **200 URL mới loại toàn bộ 850 ID/URL cũ**, review mọi lỗi/REVIEW, template và 20 accepted ngẫu nhiên trước khi xét F6. Không dùng lại 850 raw này làm holdout độc lập của chính bản sửa.
