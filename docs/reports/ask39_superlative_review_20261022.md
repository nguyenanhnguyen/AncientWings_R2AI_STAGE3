# ask.39.net — phương pháp đặc thù và claim tốt nhất

**Bước 2 đã sửa và replay đạt.** Readiness: `REPLAY_PASSED_FRESH_HOLDOUT_PENDING`; chưa xác nhận bằng holdout mới, chưa tích hợp F6 hoặc xuất production. URL 2458259 chưa có raw hợp lệ từ lượt transport trước vẫn được theo dõi riêng.

## Ca nguồn và rule

Ca **2214666**, URL `https://ask.39.net/question/22982276.html`, answer nguồn `ask39:22982276:answer:56051730`, chuyển **accepted → REVIEW**. Extraction vẫn accepted; không sửa hoặc xóa text nguồn. Câu của responder:

> 从你发上来的激素水平看，你这个有可能是多囊的，最好的方法是采用腹腔镜微创术转基因来治疗的

Rule `source_specific_method_superlative_review`, version `ask39-specific-method-superlative-v1`, ghép phương pháp đặc thù và claim 最好/最佳. Phạm vi phương pháp gồm tổ hợp nội soi/vi phẫu + chuyển gene/điều trị gene, và nhóm 靶位定向/定点祛炎 đã nhận diện trước. Không gắn REVIEW chỉ vì có từ “tốt nhất” hoặc nhắc một phương pháp thông thường. Không chứa ID trang hay tên tác giả trong rule.

Xét hai thứ tự method–claim trong cùng mệnh đề, khoảng ghép tối đa 160 ký tự. Qua câu liền kề phải có tham chiếu rõ như 该方法; không nối qua newline, dấu chấm phẩy, message hoặc answer khác. Từ “có thể” ở mệnh đề mô tả bệnh trước đó không triệt tiêu claim khẳng định riêng ở mệnh đề sau.

Chỉ lời responder được đánh giá. Phủ định/không khuyến nghị, câu hỏi, mô tả có điều kiện, lời thuật lại, trích dẫn và bác bỏ được lưu với quyết định suppressed cùng lý do. Với rule mới, dấu trích dẫn bao toàn bộ message cũng được triệt tiêu. Phạm vi lời thuật lại theo mệnh đề và dấu chuyển ý; lời bệnh nhân hoặc phủ định ở mệnh đề trước không tự hủy khẳng định riêng của responder sau đó.

Bằng chứng: method `腹腔镜微创术转基因` tại span `[31, 40]`, claim `最好的方法` tại span `[23, 28]`, locator `/html/body/div[2]/div[2]/div[4]/div`; raw SHA-256 `35275090c6788d0f106053e1051d60373518c0d4ead9b6e62b5eb7f042903cd1`. Assessment giữ answer/message ID, vai, rule/version, quote/span và quan hệ ngữ cảnh. Các assessment suppressed không thêm source flag; assessment review chặn export.

Đây là triage nội dung nguồn cần review, không phải kết luận đúng/sai lâm sàng của phương pháp. Parser, audit, allowlist chức danh và các rule nguồn cũ giữ nguyên; chỉ gate version đổi thành `ask39-gate-v3-superlative-context`.

## Replay 649 raw

| Chỉ số | Kết quả |
| --- | ---: |
| Raw đã kiểm hash / record trích xuất không đổi | 649 / 649 |
| Answer / follow-up | 833 / 50 |
| Extraction accepted | 649 |
| Candidate trước → sau | 625 → 624 |
| REVIEW trước → sau | 24 → 25 |
| Quyết định quality thay đổi | Chỉ 2214666 |
| Request mới / production export | 0 / 0 |

Toàn bộ text, ID nguồn, tác giả, thứ tự, vai/parent, normalization và DOM locator giữ nguyên. Không có parser/audit flag mới; tất cả source flag cũ giữ nguyên. Ca recovery 2203985 tiếp tục accepted với đủ text. Export kiểm lại raw/gate dù record còn accepted cache; Parquet đọc lại có đúng 624 ID đủ điều kiện và không chứa 2214666. Quyết định QC mới nằm trong `candidate.decisions.jsonl`; records giữ nguyên snapshot trích xuất đầu vào.

## Test và bằng chứng

21 test mới nằm trực tiếp ở cell `ask39-fix-superlative` của [notebook check](../../notebooks/check_ask.39.net.ipynb): 18 test rule/gate/export và 3 test replay. Bao phủ ca raw thật, hai thứ tự, các biến thể method/claim, method thường và từ khóa đơn lẻ, patient/unknown, phủ định trước/sau/lồng, câu hỏi, lời thuật lại, trích dẫn, bác bỏ, ranh giới mệnh đề/câu/đoạn/message, follow-up parent và span. Không tạo file test Python mới.

Payload bước recovery và E/holdout được đóng băng riêng để tái hiện các quyết định trước sửa. Notebook vẫn gitignore và Run All offline không crawl lại website.

Run All: **176 test notebook + 3 helper pass**, toàn bộ 42 code cell thực thi thành công.

Artifact: `runs/ask39_superlative_replay649_20261022T123316560002Z`. Gồm `summary.json`, `manifest.json`, `decision_diff.json`, `raw/`, `records/`, `code/`, `candidate.parquet`, `candidate.decisions.jsonl` và `verification.json` sau kiểm chứng cuối.

Bước tiếp: giữ nguyên kết quả holdout cũ; thử lại riêng URL lỗi mạng khi làm transport, rồi đóng băng bản sửa để kiểm 200 URL mới và loại toàn bộ 650 ID/URL đã chọn trước đây. Chỉ xét readiness trước F6 sau lượt xác nhận mới.
