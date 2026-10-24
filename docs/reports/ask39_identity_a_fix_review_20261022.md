# ask.39.net — kết quả fix A: định danh answer, 22/10/2026

**Đã sửa và kiểm chứng fix A.** Parser `ask39-parser-v2-identity` / extractor `ask39_qa_dom_v2` dùng ID answer nguồn trong đúng container, giữ `reply_...` làm metadata riêng. Gate/audit V2 kiểm lại định danh và parent follow-up từ raw.

## Ca 2401990 đã sửa

Hai answer ở `https://ask.39.net/question/_27vnb5.html` có cùng `reply_dom_id=reply_41561620` nhưng được giữ riêng:

| ID answer nguồn | Khóa thread mới | Thời điểm nguồn |
| --- | --- | --- |
| 168259322 | `ask39:_27vnb5:answer:168259322` | 2024-08-19 11:20 |
| 163288714 | `ask39:_27vnb5:answer:163288714` | 2024-05-27 15:54 |

Text giống nhau vẫn giữ thành hai answer, không dedup theo text hoặc tác giả. Ca này không còn `duplicate_answer_id` và đã đạt điều kiện candidate theo gate hiện tại.

## Cách sửa

- Chỉ đọc tham số tĩnh trong link `reportBtn` gọi `showReportModal` với endpoint feedback đã xác nhận, trong đúng `sele_all`. Không thực thi JavaScript; không lấy ID từ answer khác, sidebar hoặc message con.
- Đối chiếu ID câu hỏi với URL. Nhiều link cùng xác nhận một ID được chấp nhận; thiếu ID, nhiều ID mâu thuẫn, ID câu hỏi sai hoặc handler không nhận diện được đều giữ trạng thái provisional và REVIEW.
- Khóa provisional có phạm vi câu hỏi/raw snapshot/locator; không coi đây là định danh ổn định xuyên lần tải và không cho xuất candidate.
- Record answer có `source_question_id`, `source_answer_id`, `answer_id`, `reply_dom_id`, `identity_status`, `identity_evidence` với locator link/container và raw hash.
- Follow-up vẫn gắn vào object/container answer trước khi dùng khóa mới. `parent_answer_id` được cập nhật nhất quán trong danh sách toàn trang và từng answer.
- Audit tự đọc lại ID nguồn và kiểm khóa/evidence, header metadata, parent và cấu trúc; không gọi hàm định danh của parser để tự xác nhận.
- Gate V2 chỉ nhận hợp đồng V2; record V1 accepted không được đi qua nếu chưa reparse. Check nhận diện extractor V2; notebook production chưa thay đổi.

## Replay 250 raw

| Chỉ số | Kết quả |
| --- | ---: |
| Trang replay | 250 |
| Answer / ID nguồn xác minh được | 343 / 343 |
| Follow-up giữ đủ và đúng parent nguồn | 22 / 22 |
| Text hash khớp V1 | 250 / 250 |
| QC trích xuất đạt | 250 |
| Candidate local theo gate | 244 |
| REVIEW nguồn | 6 |
| Xuất production | 0 |

So với 48 candidate baseline + 195 candidate holdout trước đó, chỉ ca **2401990** rời REVIEW, tổng candidate 243 → 244. Mọi `source_flags` của 250 trang giữ nguyên: hai trang quảng bá đã bị rule cũ giữ REVIEW và bốn trang chức danh chưa nhận diện vẫn REVIEW.

**Hai claim F5 tại 2229930 và 2252991 vẫn chưa được sửa ở đợt A**, còn trong 244 candidate theo gate hiện tại. File candidate là bằng chứng thử nghiệm, chưa được phê duyệt release. Readiness đợt này là `FIX_A_PASSED_FIX_B_PENDING`; readiness tổng thể vẫn chưa đạt để sang F6.

## Test trực tiếp trong notebook

Đã thêm **13 test A** tại phần “Fix A — candidate V2: định danh answer độc lập với header tác giả” của `notebooks/check_ask.39.net.ipynb`:

- 250 trang giữ text, 343 ID nguồn và evidence đúng; 22 message giữ parent theo container.
- Ca 2401990 có hai ID/thời điểm riêng; cùng header/cùng text ở hai thread không bị trộn.
- ID nguồn trùng thật tiếp tục bị chặn; nhiều link cùng ID được chấp nhận.
- Thiếu/mâu thuẫn/sai ID câu hỏi dùng provisional; không lấy ID của answer khác hoặc sidebar.
- Handler không nhận diện không được tin hoặc thực thi; cùng số answer ở hai câu hỏi có khóa khác nhau.
- Sửa giả ID/evidence/parent bị gate/audit bắt; record V1 bị gate V2 từ chối.
- Source flags không thay đổi, bảo đảm không sửa ngầm claim/chức danh trong bước A.

Đã thực thi toàn bộ code cell bằng IPython local, lưu output ngay trong notebook. **50 test F1–F5 chạy với payload V1 đóng băng + 13 test V2 mới = 63/63 pass.** Ba test check/audit có sẵn cũng pass. Không tạo file test Python mới, không gọi lại website.

## Bằng chứng

- Run: `runs/ask39_identity_a_replay250_20261022T020525469544Z`.
- `summary.json`, 250 raw/record, `identity_mapping.json` theo từng container, candidate Parquet và quyết định đầy đủ, manifest cùng code snapshot.
- Parser SHA-256: `bfc1669571542fd4b339a68803c156f70de7c944d6eccc92820390fa8bf8409f`.
- Gate SHA-256: `1c628a8b4617cde4eb1d787e6dbb5a27d001c975012979583c6aef1c078066bd`.
- Auditor SHA-256: `414a32a1f1ba7057df71da81731704ba391556b2f3e8dfafc43cf6f690508454`.

Notebook tiếp tục được Git bỏ qua. Bước tiếp theo là fix B về claim; sau đó replay tổng hợp và holdout xác nhận mới theo plan.
