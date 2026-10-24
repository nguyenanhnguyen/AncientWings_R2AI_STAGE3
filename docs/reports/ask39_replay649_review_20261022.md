# ask.39.net — bước 3: replay độc lập 649 HTML

**Replay đạt, không còn thay đổi chưa giải thích.** Parser/gate/audit giữ nguyên SHA-256 so với bước 2. Readiness: `REPLAY_649_PASSED_FRESH_HOLDOUT_PENDING`; chưa tích hợp F6, chưa xuất production.

## Phạm vi và phương pháp

Trích xuất lại từ **649 raw HTML**, không dùng text đã lưu làm đầu vào parser. Kiểm từng raw hash, tính lại gate và audit DOM độc lập, rồi export Parquet và đọc lại. Không crawl thêm URL. 649 raw đến từ 450 trang regression cũ và 199 raw của lượt xác nhận sau E. URL corpus **2458259** vẫn chưa có raw hợp lệ, không được thay bằng URL khác; tổng URL đã chọn vẫn là 650.

So ba mốc: trước recovery/claim fix, sau recovery (bước 1), sau superlative (bước 2). 649 quyết định trước fix được nhúng và pin hash riêng trong notebook. Chỉ các trường bao ID/URL trong file JSONL được chuẩn hóa trước so dictionary; mọi field quyết định/audit và leaf diff vẫn được lưu. Hai trường quality_status/quality_flags ở record được so qua gate vì parser dùng trạng thái candidate-only tạm, còn một số record cũ chứa trạng thái gate cache.

## Text, ID và parent

| Chỉ số | Kết quả |
| --- | ---: |
| Raw đã xác minh hash | 649 |
| Answer có ID nguồn xác minh | 833 |
| Follow-up | 50 |
| ID answer thay đổi | 0 |
| Follow-up đổi text/vai/thứ tự/ID/parent | 0 |
| Orphan / vai không rõ | 0 / 0 |
| Trang đổi text so với trước hai fix | 1: 2203985 |
| Trang đổi dữ liệu parser so với sau bước 1 | 0 |
| Parser/audit flag sau replay | 0 |

**2203985**: khôi phục text answer thứ ba từ `p#content2831302` ngay sau `sele_txt` rỗng, trong đúng container. Số container answer vẫn là ba; không tạo answer mới và không đổi ID `ask39:14579504:answer:392262374`. Chỉ bốn trường trong answer này đổi: `text`, `source_text`, `text_sha256`, `body_locators`. Render trang, char count, text hash, normalization action và trạng thái/flag thiếu text đổi theo nội dung vừa khôi phục. Hai answer trước và câu hỏi giữ nguyên.

Ngoài version parser, 648 trang còn lại giữ nguyên mọi trường trích xuất. Toàn bộ tác giả, ID nguồn/header, thứ tự answer, câu hỏi và DOM exclusions giữ nguyên. Map `answer_mapping833.jsonl` có đủ 833 hàng; `followup_mapping50.jsonl` lưu đầy đủ before/after của 50 message, bao gồm parent, role, order và locator. Flat follow-up và danh sách nested dưới từng answer khớp chính xác.

## Giải thích quyết định QC

| Mốc | Extraction accepted | Candidate | REVIEW |
| --- | ---: | ---: | ---: |
| Trước hai fix | 648 | 624 | 25 |
| Sau recovery | 649 | 625 | 24 |
| Sau superlative | 649 | 624 | 25 |
| Replay độc lập hiện tại | 649 | 624 | 25 |

Tổng candidate trước/sau cùng là 624 nhưng tập ID thay đổi đúng hai ca:

| ID | Trước fix → hiện tại | Giải thích |
| --- | --- | --- |
| 2203985 | REVIEW → accepted | Nội dung answer đã khôi phục; các parser/audit flag thiếu nội dung được gỡ sau kiểm raw |
| 2214666 | accepted → REVIEW | Phương pháp đặc thù đi kèm claim “tốt nhất” trong lời responder; thêm source flag và evidence/span |

Không có source flag cũ nào bị gỡ hoặc đổi. So với bước 1 chỉ 2214666 đổi quality; so với bước 2 **mọi field của kết quả gate fresh replay khớp chính xác**, không chỉ status hay tổng số. Chỉ số QA/thống kê không được dùng thay thế kiểm từng ID.

## Metadata được giải thích riêng

- Version parser đổi ở 649 trang khi so với trước recovery; version gate đổi khi so với hai mốc cũ. Đây là pin phiên bản, không phải thay đổi text/ID/parent hay một policy mới trong bước 3.
- **640** diff lịch sử chỉ ở `/audit/baseline_qc`: audit ghi lại `quality_status` của input. Cache cũ từng đưa accepted vào audit, còn fresh parser đưa candidate-only review. Đây không phải kết luận audit hoặc quality_status của gate. Mọi flag, review_decision và field policy vẫn được so riêng; không bỏ field này khỏi diff.
- Khi export kiểm gate lần nữa trên record đã áp QC, **624** trường echo đổi review → accepted ở đúng 624 candidate. Mọi field khác giữ nguyên. `export_gate_diff.json` giữ từng ID và leaf diff; `fresh_gate.decisions.jsonl` giữ kết quả trước export, `candidate.decisions.jsonl` giữ kết quả export. Record cuối áp gate export để metadata QC nhất quán.

Các diff nội dung/audit thực tế ở 2203985 và source evidence ở 2214666 được giải thích theo từng field trong `parser_field_diff.json` và `gate_field_diff.json`. Không chấp nhận một field mới chỉ vì nó thuộc hai ID này: danh sách field được phép thay đổi được kiểm rõ, còn metadata echo chỉ được phân loại khi đúng leaf `/audit/baseline_qc`.

## Export và kiểm chứng

Parquet có đúng **624 ID** đủ điều kiện, không trùng, không chứa REVIEW, text/title/URL/hash khớp record. 2203985 có mặt, 2214666 không có mặt. 25 REVIEW tiếp tục bị chặn. Tất cả `corpus_eligible=False`, production export bằng 0.

**10 test replay mới + 3 helper pass**. Test mới nằm trực tiếp ở cell tag `ask39-replay-649` trong [notebook check](../../notebooks/check_ask.39.net.ipynb), vẫn gitignore; không tạo file test Python mới. Parser/gate/audit không sửa trong bước này; hash được đối chiếu với artifact bước 2. `verification.json` ghi hash notebook/core và kết quả kiểm lại raw, mapping, diff và export.

Artifact: `runs/ask39_replay649_audit_20261022T130332959141Z`.

- `page_comparison.json`: đủ 649 trang, ba mốc so sánh và before/after status/hash.
- `parser_field_diff.json`, `gate_field_diff.json`, `export_gate_diff.json`: field/leaf diff và giải thích.
- `answer_mapping833.jsonl`, `followup_mapping50.jsonl`: kiểm định danh và parent.
- `audits.json`, `unexplained_changes.json`: audit độc lập; danh sách chưa giải thích rỗng.
- `raw/`, `records/`, `code/`, `manifest.json`, `summary.json`, hai file decisions và Parquet: bằng chứng tái hiện.

Bước tiếp theo là xử lý riêng URL lỗi transport rồi đóng băng code để kiểm 200 URL mới, loại toàn bộ 650 ID/URL đã chọn trước đây. Chưa xác nhận readiness trước F6 bằng replay nội bộ này.
