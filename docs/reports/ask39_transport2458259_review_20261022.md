# ask.39.net — bước 4: retry riêng URL 2458259

**Đã thu raw thành công.** Đúng URL cũ `https://ask.39.net/question/_tj3ab5.html`, không chọn lại mẫu hoặc thay URL. Requests trả **HTTP 200**, tổng thời gian **1.045 giây**, không cần browser fallback.

| Chỉ số | Kết quả |
| --- | --- |
| ID corpus | 2458259 |
| Thời điểm request (UTC) | 2026-10-22T13:24:26.773694+00:00 |
| Engine / lần request | Requests / 1 |
| Content-Type | text/html;charset=utf-8 |
| Raw bytes | 44922 |
| SHA-256 | `dcbd3095c923ffc29258942c86cbfb9e396ae17035998b44df49a1acdb568161` |
| Answer / follow-up | 1 / 0 |
| Answer ID nguồn | `ask39:_tj3ab5:answer:162339113` |
| Extraction / gate quality | accepted / accepted |
| Parser/audit/source flag | Không có |
| Candidate supplement local | 1 |
| Production export | 0 |

## Bằng chứng và kiểm tra

Đã kiểm raw hash với event request, trích xuất lại offline và so text/question/answer/follow-up/ID với record. Answer có định danh nguồn verified, DOM locator khớp raw, audit độc lập không phát hiện thiếu text, sai ownership hoặc UI contamination. Gate và export đọc lại raw; một candidate local có đúng ID và text hash. Accepted ở đây là kết quả extraction/source QC hiện tại.

Lỗi TLS/SSLEOFError của lượt cũ và lỗi browser ERR_EMPTY_RESPONSE vẫn được giữ trong artifact lịch sử. Lượt bổ sung này lưu riêng, không sửa kết quả holdout cũ thành thành công. Không thay địa chỉ URL, tắt TLS hoặc nới URL validation. DNS vẫn giới hạn 5 giây; request timeout 8/20 giây, budget 60 giây; browser chỉ được phép fallback tối đa một lần nếu cần.

## Giữ nguyên mẫu

Mẫu xác nhận cũ vẫn có **200 URL**, cùng SHA-256 `8d328519b913ce85e9cc6f8b019a03385e1d44328733ca69d4f4d81fe9d3e58d`. Đã so hash trước/sau của sample, results, manifest, summary, danh sách 450 URL loại trừ và artifact replay 649: tất cả giữ nguyên. Parser/gate/audit/check helper/DNS cũng giữ nguyên hash.

Tổng URL từng chọn vẫn là **650**. Số raw hỏi–đáp hợp lệ đã có tăng **649 → 650**, nhờ supplement của đúng slot thiếu; không tạo URL thứ 651. Inventory gồm replay 649 trước đó và raw mới, tổng cộng **834 answer + 50 follow-up** theo hai artifact. Chưa ghép lại hoặc gọi đây là một lượt replay 650 mới.

`supplement_inventory.json` liên kết raw mới với replay 649. Mẫu và kết quả holdout cũ không bị ghi đè; bước kiểm 200 URL mới tiếp theo vẫn phải loại toàn bộ 650 ID/URL này.

## Test và artifact

**8 test notebook mới + 3 helper pass**. Test nằm ở cell tag `ask39-transport-2458259` trong [notebook check](../../notebooks/check_ask.39.net.ipynb), vẫn gitignore. Cell nhúng bằng chứng/raw để replay offline; Run All không gửi lại request này. Không tạo file test Python mới.

Artifact: `runs/ask39_transport2458259_20261022T132425879258Z`.

- `target.json`, `sample200_original.jsonl`, `manifest.json`: URL gốc, mẫu và hash/config.
- `requests_attempt.json`, `raw/requests/`: response 200, headers, elapsed time và raw nén.
- `selected_record.json`, `gate_decision.json`, `dom_audit.json`: trích xuất và QC.
- `candidate.parquet`, `candidate.decisions.jsonl`: candidate supplement local.
- `summary.json`, `supplement_inventory.json`, `verification.json`, `code/`: inventory, kiểm chứng và mã đóng băng.

**Readiness: TRANSPORT_RETRY_COMPLETED_HOLDOUT_PENDING.** Còn bước kiểm 200 URL mới trước khi xác nhận readiness cho F6; chưa tích hợp F6 hoặc xuất production.
