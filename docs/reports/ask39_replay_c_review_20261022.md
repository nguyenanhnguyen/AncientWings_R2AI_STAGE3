# ask.39.net — replay C: 250 HTML sau fix A–B

Ngày 22/10/2026. Replay offline 50 HTML baseline và 200 HTML holdout cũ, không tải URL mới. Hai tập này hiện là regression; 200 URL cũ không còn là holdout độc lập sau khi dùng để sửa lỗi.

## Kết quả

**Replay C đạt:** giữ đủ **343 answer + 22 follow-up**, hash nội dung của **250/250 trang không đổi**, không có thay đổi ngoài các nhóm được giải thích dưới đây.

| Chỉ số | F5 đóng băng | Candidate A–B |
| --- | ---: | ---: |
| Trang | 250 | 250 |
| Answer | 343 | 343 |
| Follow-up | 22 | 22 |
| Extraction accepted | 249 | 250 |
| Candidate local | 243 | 242 |
| REVIEW | 7 | 8 |

Đối chiếu từ F5 gốc, không chỉ từ kết quả B. Mỗi raw được kiểm SHA-256 rồi parse lại bằng parser hiện tại; audit độc lập đọc DOM để kiểm câu hỏi, answer, follow-up, định danh, vai và parent. Giữ nguyên các artifact F5/A/B cũ.

## Giải thích mọi thay đổi

### Định danh và schema ở 250 trang

- Bổ sung `source_question_id` vào record; đổi `extractor` từ `ask39_qa_dom_v1` sang `ask39_qa_dom_v2`, `parser_version` từ `ask39-parser-v1-f4` sang `ask39-parser-v2-identity`.
- **343 answer** chuyển `answer_id` từ header tác giả sang khóa theo câu hỏi và ID answer nguồn xác minh trong đúng container. Bổ sung `source_answer_id`, `source_question_id`, `reply_dom_id`, `identity_status`, `identity_evidence`; giữ header cũ trong `reply_dom_id`.
- **22 follow-up** đổi `parent_answer_id` sang khóa answer mới, trên cả danh sách phẳng lẫn thread của answer. Giữ nguyên `message_id`, locator, vai người nói, thứ tự và text. Mapping giữ từng container nên không làm mất quan hệ một header → nhiều answer.
- Text, hash, title, khối câu hỏi, tác giả, chức danh thô, profile URL, thời điểm, vị trí DOM, thứ tự answer, raw source text, encoding, normalization actions và DOM exclusions đều giữ nguyên. Các metadata tải trang ngoài parser cũng không đổi khi đối chiếu record.

### Ba trang đổi quyết định so với F5

| ID | Trước → sau | Lý do |
| --- | --- | --- |
| 2401990 | REVIEW → accepted | Hai container dùng chung `reply_41561620` nhưng ID answer nguồn là `168259322` và `163288714`; fix A xác minh hai khóa riêng. |
| 2229930 | accepted → REVIEW | Fix B: `靶位定向给药` + `从根本上治愈`, trong lời responder; answer `ask39:30435163:answer:71027728`. |
| 2252991 | accepted → REVIEW | Fix B: `定点 祛炎` + chặn tiến triển/ít tái phát, trong lời responder; answer `ask39:40831155:answer:128775128`. |

Riêng 2401990: `parser_status` chuyển `review` → `parsed`; bỏ `duplicate_answer_id` khỏi parser flags và quality flags của parser. Gate cũng bỏ các lỗi cấu trúc phát sinh từ khóa header trùng. Hai text và hai thời điểm nguồn vẫn giữ nguyên.

Hai trang claim vẫn extraction accepted; chỉ chất lượng nguồn chuyển REVIEW. Hai ca promotion cũ và bốn ca chức danh chưa nhận diện giữ nguyên. Tổng cộng **247/250 quyết định quality không đổi**; không có thêm thay đổi quyết định so với fix B. `gate_version` đổi có chủ đích từ `ask39-gate-v1` sang `ask39-gate-v2-claims`; source evidence dùng khóa answer mới và thêm bằng chứng claim theo fix B.

Diff toàn bộ trường gate: thêm `claim_assessments` và đổi version ở 250 trang; `source_evidence` đổi ở 8 trang (6 trang cũ đổi khóa answer, 2 trang thêm evidence claim); `candidate_eligible`, `quality_status`, `quality_flags` đổi ở đúng 3 trang trên; `source_flags` đổi ở 2 trang claim; `extraction_status` và parser flags của gate đổi ở riêng 2401990. Không có trường gate nào khác đổi.

## Kiểm tra export và bằng chứng

Export đọc lại raw và chạy lại gate. Đọc lại Parquet xác nhận đúng 242 ID/URL duy nhất đủ điều kiện; các trường ID, URL, title, text và text hash khớp record vừa parse. Không có trang REVIEW trong candidate. `corpus_eligible=False`; production export bằng 0.

Các test mới và output chạy nằm trực tiếp trong cell tag `ask39-fix-c` của [notebook check](../../notebooks/check_ask.39.net.ipynb). Notebook vẫn được gitignore theo yêu cầu. Builder bảo toàn các cell C khi cập nhật payload; F1–F5 và A giữ snapshot riêng để tái hiện lịch sử.

**90 test notebook pass** (50 F1–F5 + 13 A + 19 B + 8 C), cùng 3 test helper có sẵn. Cell bổ sung diff mọi trường gate cũng đã chạy và xác nhận đúng các nhóm thay đổi ở trên. Artifact: `runs/ask39_replay_c_250_20261022T030738521787Z`; hash parser/gate/audit trùng source hiện tại.

Artifact replay C gồm:

- `summary.json`, `manifest.json`: số liệu, hash code/raw fixture và baseline đóng băng.
- `page_diff.json`: đủ 250 trang, thay đổi trường parser và quyết định trước/sau kèm lý do.
- `gate_field_diff.json`: giá trị trước/sau của mọi trường gate thay đổi trên cả 250 trang.
- `answer_identity_mapping.json`: 343 dòng theo container, header cũ → ID answer mới và bằng chứng nguồn.
- `followup_parent_mapping.json`: 22 message, parent trước/sau, vai, thứ tự và text hash.
- `independent_audit.json`: audit độc lập đủ 250 HTML.
- `raw/`, `records/`, source parser/gate/audit và candidate Parquet/decisions để kiểm lại.

## Readiness

**`REPLAY_C_PASSED_FRESH_HOLDOUT_PENDING`**. A–C đạt trên regression hiện có; bước D còn mở: đóng băng code rồi kiểm 200 URL mới, loại cả ID và URL của 250 trang đã dùng. Kết quả này chưa thay thế bước xác nhận đó hoặc cho phép F6/production.
