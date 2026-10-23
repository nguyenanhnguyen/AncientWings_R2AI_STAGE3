# ask.39.net — bước 2: tách đánh giá bệnh nhân khỏi answer (23/10/2026)

**Đã sửa 2205416, 2207135, 2207389.** `span.pingjia` không còn trong text bác sĩ hoặc rendered text dùng cho candidate. Đánh giá vẫn được lưu riêng trong `answers[].patient_evaluations`, có owner và provenance đối chiếu được raw. **Readiness tổng thể: NEEDS_FIX** vì còn 3 claim sản phẩm/thiết bị và 3 ca policy/chuyên môn pending; chưa F6, production = 0.

## Thay đổi và ranh giới

Parser nhận đúng **tag span + class token pingjia trong body của answer đã map**, gồm paragraph được khôi phục hợp lệ. Không xóa theo chuỗi “提问者对于答案的评价” hoặc “谢谢”. Node có class gần giống, tag khác hoặc nằm trong follow-up/question không bị áp dụng cleanup này. Khi bỏ subtree khỏi clinical text, giữ tail sau span và đủ text bác sĩ trước/sau node. Đánh giá không trở thành answer/follow-up mới.

Mỗi answer có `patient_evaluations` dạng list (rỗng nếu không có). Mỗi đánh giá có:

- `evaluation_id`: ID suy ra từ source answer ID và thứ tự đánh giá trong body, không giả định đây là ID do website cấp.
- `parent_answer_id`, `order`, `speaker_role='patient'`: vai trò đánh giá từ DOM nguồn, không xác minh danh tính thật của tài khoản.
- `text`, `source_text`, `text_sha256`: giữ toàn bộ nội dung node, gồm nhãn đánh giá và tên tài khoản hiển thị nếu có; không tự suy diễn người viết.
- `locator`, `provenance`: rule `patient_evaluation_dom`, raw SHA-256, owner/body locator và SHA-256 HTML node (không gồm tail).

`answer.source_text` vẫn giữ text raw trước làm sạch để truy vết. Clinical `answer.text`, rendered `record.text` và hash tương ứng đã loại đúng đánh giá. `dom_exclusions` ghi lý do `patient_evaluation_metadata` cùng bằng chứng node; “exclusion” ở đây chỉ khỏi clinical text, metadata vẫn được giữ.

Audit độc lập xác định các node đánh giá từ body/sibling raw, không tin riêng `body_locators` hoặc metadata của record và không gọi parser. Thiếu metadata, sai ID/parent/role/order/locator/text/hash hoặc provenance đều tạo `patient_evaluation_metadata_mismatch`, gate chuyển REVIEW. Record cũ còn gộp đánh giá trong text bác sĩ cũng bị `answer_message_text_mismatch`.

Parser version `ask39-parser-v2-patient-evaluations`; gate version `ask39-gate-v5-patient-evaluations` yêu cầu parser mới. Rule claim, chức danh và điều kiện nhận nguồn giữ nguyên; nội dung trong metadata bệnh nhân không bị đánh giá như lời bác sĩ. Claim thật trong text bác sĩ vẫn được QC bình thường.

## Kết quả ba ca thật

| ID | Parent answer | Lời bác sĩ giữ nguyên | Đánh giá chuyển metadata |
| --- | --- | --- | --- |
| 2207135 | `ask39:17730621:answer:45226279` | 要完全治愈这种病，唯一的办法只能靠中医中草药治疗。西医无法根治。 | 提问者对于答案的评价： / askR5S9J：谢谢 |
| 2207389 | `ask39:17962702:answer:45734781` | 你好你的检查结果来看，考虑雌激素偏低，可以服用补佳乐调理的 | 提问者对于答案的评价： / askH1IUJ：谢谢医生！ |
| 2205416 | `ask39:15782940:answer:40888286` | 你好，按照正常剂量服用就可以了，任何药物都有一定的副作用遵医嘱用药不用担心 | 提问者对于答案的评价： / askB67PB：谢谢你 |

Source question, source answer ID, header tác giả, answer order và mọi follow-up/parent/thread order giữ nguyên. Ca 2207135 vẫn REVIEW vì thiếu chức danh ở answer khác; không thay đổi source policy để làm accepted.

## Kiểm thử và replay

**16 test notebook mới pass** (12 tập trung + 4 replay); chạy lại **14 test bước sửa UI** với snapshot baseline và **3 helper test hiện có**, đều pass. Test mới nằm trong cell tag `ask39-fix-patient-evaluations` của [notebook check](../../notebooks/check_ask.39.net.ipynb), vẫn gitignore; không tạo file unit test Python mới. Builder giữ snapshot bước UI và section mới. Lượt này không chạy lại toàn bộ các section lịch sử của notebook.

Bao phủ: exact text ba ca thật; metadata/raw-node hash; mất/sửa metadata; text tail; class token; negative cho keyword, class gần giống, tag khác và follow-up; hai đánh giá/answer; paragraph khôi phục; answer chỉ có đánh giá vẫn empty/REVIEW; source claim trong metadata không gắn sang bác sĩ; claim thật của bác sĩ vẫn bị QC; candidate export chỉ chứa clinical text sạch và record JSON round-trip giữ đủ metadata.

Replay **200 raw của holdout gần nhất**, so với bản sửa UI bước 1: chỉ **2205416, 2207135, 2207389** đổi clinical text/hash, đúng phần đánh giá được chuyển metadata. Thêm field metadata vào schema của 269 answer (266 list rỗng); giữ **269 answer + 21 follow-up + 3 đánh giá metadata**. Các trường khác của answer và tất cả question/follow-up/ID/parent/thứ tự giữ nguyên. Ca 2211175 vẫn không lẫn nút “回复”.

QC, source flags và claim evidence của 200 record không đổi: **194 candidate-eligible, 6 REVIEW**. Replay này lưu record và sidecar metadata, không tạo candidate parquet toàn batch mới. Test export trên một ca thật xác nhận text candidate sạch; metadata được lưu trong record JSON và `patient_evaluations.jsonl`, không nhét trở lại cột clinical text của parquet.

Không có request mới; mẫu và artifact holdout cũ giữ nguyên hash. Đây là kiểm hồi quy 200 raw đã có, chưa phải replay 850 raw hoặc holdout mới xác nhận bản sửa.

## Artifact và việc còn lại

Run: `runs/ask39_patient_evaluation_fix_20261022T201454294500Z`.

- `patient_evaluations.jsonl`: đủ 3 đánh giá, mỗi dòng có corpus ID/URL, parent, locator và provenance.
- `replay200.json`: đủ record và gate decision mới; metadata nằm trong answer tương ứng.
- `text_diff.json`, `summary.json`: giải thích toàn bộ ba thay đổi text và thống kê.
- `*.before.json`, `raw/`: bằng chứng trước sửa của ba ca thật.
- `code/`, `manifest.json`, `verification.json`: code/hash và kiểm chứng.

Tiếp theo là bước 3: đưa **2249721, 2252713, 2381257** sang REVIEW theo sản phẩm/thiết bị + claim ở đúng ngữ cảnh/người nói; có ca âm tính cho phủ định, trích dẫn, bệnh nhân và liệt kê thuốc. Ba ca policy/chuyên môn 2203052/2407658/2459843 vẫn pending. Sau các fix cần replay 850 raw, rồi holdout mới loại đủ 850 URL trước F6.
