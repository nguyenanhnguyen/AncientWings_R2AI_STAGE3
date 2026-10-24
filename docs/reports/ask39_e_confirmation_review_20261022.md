# ask.39.net — xác nhận 200 URL mới sau fix E

**Readiness: `NEEDS_FIX`**. Gate `ask39-gate-v3-source-context`; chưa tích hợp F6 hoặc xuất production.

## Mẫu và code đóng băng

200 URL mới, seed `20261024`, phân bổ 100 numeric + 100 underscore. Loại cả ID và URL của toàn bộ 450 trang đã dùng; overlap bằng 0. Phân bổ đều nhằm kiểm template, không suy tỷ lệ toàn domain từ tỷ lệ mẫu.
Parser/gate/audit giữ nguyên hash sau replay 450 raw trong toàn bộ crawl/review. Lượt chính dùng check helper đóng băng; retry dùng thêm transport DNS có timeout 5 giây và cache 60 giây. Hash helper cũ/mới và module DNS được ghi riêng trong `transport_revision`; không đổi luật, địa chỉ DNS trả về, TLS hoặc kiểm tra URL.

## Kết quả

| Chỉ số | Kết quả |
| --- | ---: |
| URL đã thử / truy cập được | 200 / 199 |
| Raw đã kiểm hash | 199 |
| Answer / follow-up | 238 / 12 |
| Answer có ID nguồn xác minh | 238 |
| Orphan follow-up / vai không rõ | 0 / 0 |
| Extraction accepted | 198 |
| Candidate / REVIEW theo gate | 193 / 7 |
| Trang đã đọc / packet bắt buộc đã đọc đủ | 79 / 73 |
| Accepted ngẫu nhiên đã đọc | 20 |
| Phát hiện mới cần sửa/triage | 2 |

Source flags: `{"source_qualification_unrecognized": 5}`.

193 candidate là kết quả gate đóng băng, vẫn chứa ca claim mới 2214666; review tổng thể chặn release. Không dùng file candidate này để xuất production. Năm REVIEW chức danh, một REVIEW thiếu answer và một REVIEW lỗi mạng tạo thành bảy REVIEW của gate.
Access/parser/audit flags: `{"page_not_verified_accessible": 1, "raw_evidence_missing_or_mismatch": 1}` / `{"empty_main_answer": 1, "empty_message": 1, "parser_not_complete": 2, "answer_count_mismatch": 1, "char_count_mismatch": 1, "followup_count_mismatch": 1, "legacy_or_unsupported_parser": 1, "no_main_answers": 1, "question_identity_mismatch": 1, "question_missing": 1, "rendered_text_mismatch": 1, "text_hash_mismatch": 1}` / `{"main_answer_text_missing": 1, "raw_audit_not_verified": 1}`.
Audit độc lập: `{"main_answer_text_missing": 1}`.

Review bao phủ toàn bộ REVIEW/error, đại diện mọi nhóm template, 20 accepted ngẫu nhiên cố định seed và các ca screen tín hiệu nguồn. Review do assistant thực hiện, không gắn nhãn human review hoặc xác nhận đúng/sai lâm sàng cho mọi tư vấn nguồn.

## Readiness

Còn phát hiện chưa được xử lý; giữ nguyên candidate/decisions đóng băng làm bằng chứng. Chưa được coi là ready trước F6.

- **2203985 / `ask39:14579504:answer:392262374`**: Parser bỏ sót nội dung answer thứ ba trong p#content2831302 ngay sau sele_txt rỗng; QC/audit đã chặn REVIEW. Cần mở rộng recovery theo biên container, không lấy UI.
  Claim: `猪胰就是猪的胰腺，您的血糖那么高  最好还是正规治疗 以免耽误病情`; locator `/html/body/div[2]/div[2]/div[5]/div`; raw SHA-256 `4dfb60e33e6ca52b9d2751aa1301fe1dc03f958d9b78fcb682783037763181d5`.

- **2214666 / `ask39:22982276:answer:56051730`**: Người trả lời khẳng định phương pháp cụ thể có chuyển gene là phương pháp tốt nhất. Luật E chưa triage dạng superlative + phương pháp này; cần REVIEW nguồn, chưa kết luận đúng/sai lâm sàng.
  Claim: `最好的方法是采用腹腔镜微创术转基因来治疗的`; locator `/html/body/div[2]/div[2]/div[4]/div`; raw SHA-256 `35275090c6788d0f106053e1051d60373518c0d4ead9b6e62b5eb7f042903cd1`.

## Lỗi khiến tiến trình treo

Request của ID 2300752 đã mất 2570,429 giây ở phân giải DNS, vượt budget request 60 giây. Bản sửa `ask39-bounded-dns-v1` tách DNS sang daemon thread, giới hạn chờ 5 giây, coalesce lookup trùng, cache 60 giây và tối đa 2 worker. Giữ nguyên lỗi/địa chỉ trả về từ OS; không thay DNS, tắt TLS hoặc nới URL validation.
7 test offline mới nằm trong cell `ask39-transport-dns`: DNS treo, daemon, cache/copy/TTL, lỗi và phục hồi, coalesce/worker cap, install/restore và tham số không hợp lệ. Ca giả lập treo phải trả lỗi trong dưới 0,5 giây với timeout 0,04 giây.

Run All offline hoàn tất: **139 test notebook + 3 test helper pass**, toàn bộ 36 code cell chạy thành công. Trong đó có 22 test fix E, 7 test DNS và 10 test bằng chứng xác nhận mới. Notebook vẫn được gitignore; không tạo file test Python mới. `confirmation_verification.json` ghi hash notebook/source và kết quả xác minh lại 199 raw.
Đã hoàn thành 200 lần thử, thu được 199 raw. ID 2458259 vẫn lỗi TLS sau request và browser fallback; không thay URL để đủ mẫu. Không xem 238 container answer là 238 answer có đầy đủ text: còn một answer rỗng do lỗi recovery đã nêu.

Ở ID 2458259, request ghi `SSLEOFError`; browser ghi `ERR_EMPTY_RESPONSE` trong chromedriver log và lưu screenshot/trang lỗi riêng. Các bằng chứng transport thất bại không được tính vào 199 raw hỏi–đáp đã xác minh.

## Hướng tiếp theo

1. Khôi phục `p#content…` nằm ngay sau `sele_txt` rỗng trong đúng answer container; thêm test dương/âm ở notebook và so diff trên 649 raw đã có.
2. Triage tổ hợp phương pháp đặc thù + lời khẳng định tốt nhất theo người nói/ngữ cảnh; giữ ca âm phủ định, trích dẫn và lời bệnh nhân.
3. Thử lại riêng URL lỗi TLS ở một lượt transport độc lập; sau sửa replay, dùng một holdout mới và loại toàn bộ 650 URL đã chọn. Không đổi kết quả holdout này.

## Bằng chứng

Artifact: `runs/ask39_e_holdout200_completed_20261022T054952718633Z`.
Code đóng băng: `runs/ask39_e_confirmation_frozen_20261022T041725193873Z`.
- Mẫu, source/hash và cấu hình: `sample.jsonl`, `manifest.json` và `freeze_manifest.json` trong thư mục code đóng băng.
- Raw/records và export: `raw/`, `records/`, `results.jsonl`, `candidate.parquet`, `candidate.decisions.jsonl`.
- Audit/review: `confirmation_review_data.json`, `confirmation_review_packet.md`, `confirmation_signal_screen.json`, `confirmation_assistant_review.json`, `confirmation_final_summary.json`.
- Notebook check tiếp tục được gitignore; phần xác nhận nhúng bằng chứng/raw để replay offline, không crawl lại khi Run All.
Requests HTTP lượt chính: `{"None": 34, "200": 166}`; browser attempts: 3. Retry bổ sung (nếu có) được giữ trong manifest, không thay URL lỗi bằng URL khác.
