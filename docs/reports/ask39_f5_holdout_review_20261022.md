# ask.39.net — replay 50 HTML và holdout 200 URL ngày 22/10/2026

**Đã hoàn tất phép thử F5; readiness là `NEEDS_FIX`, chưa chuyển sang F6.** Replay baseline đạt, nhưng holdout phát hiện vấn đề định danh answer và review mẫu phát hiện tín hiệu nguồn mà rule hiện tại chưa gắn cờ.

## Phạm vi và tính độc lập của mẫu

- Nguồn Parquet ghim SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`.
- Loại cả ID và URL của 50 baseline; chọn đúng 200 URL mới, không trùng nhau, seed `20261022`.
- Chia 100 URL đường dẫn số và 100 URL bắt đầu bằng `_`. Sau khi loại baseline, hai tầng có 27.572 và 5.150 URL. Đây là phân bổ đều để kiểm template, không phải mẫu theo tỷ trọng dân số; không dùng 195/200 để ước lượng tỷ lệ đạt toàn domain.
- Một worker, delay 2 giây, một attempt/URL. Lượt Requests chạy **08:15:00–08:22:52 ngày 22/10/2026, giờ Việt Nam**, khoảng 472 giây.
- Parser, gate và auditor được sao chép/đóng băng trong `runs/ask39_f5_support_20261022` trước crawl. Không sửa ba module này để làm mẫu holdout đạt.
- Check dừng/hoãn khi gặp 429/challenge; lượt này không gặp các trường hợp đó và không cần Selenium.

## Replay 50 HTML cũ

Đọc lại raw đã kiểm hash, tạo candidate mới và bảng diff từng ID; không ghi đè baseline.

| Chỉ số | Baseline trafilatura | Replay F4 đóng băng |
| --- | ---: | ---: |
| Khối answer chính nguồn | 72 | 72 |
| Answer bị thiếu | 3 | 0 |
| Message follow-up bị thiếu | 6 | 0 |
| Candidate local | Chưa có gate này | 48 |
| REVIEW nguồn | Chưa có gate này | 2 |

Có `baseline_candidate_diff.csv` và 50 file text diff, gồm thay đổi độ dài, số khối phục hồi, phần bị loại, flags và quyết định QC. Đã xem lại sáu trang phục hồi answer/follow-up, sáu ca paragraph lồng sai và thêm 10 trang khác; có danh sách tại `f5_replay_review_selection.json`. Đây là review của assistant, không phải nhãn người dùng hoặc thẩm định y khoa.

## Kết quả 200 URL mới

| Chỉ số | Kết quả |
| --- | ---: |
| Đã thử / pending | 200 / 0 |
| HTTP 200 / truy cập được | 200 / 200 |
| Selenium | 0 |
| Answer chính / follow-up đã trích | 271 / 16 |
| QC trích xuất đạt | 199 |
| Candidate theo gate đóng băng | 195 |
| REVIEW theo gate | 5 |
| Audit báo mất text/sai vai/sai parent | 0 |

| Tầng | URL | Extraction đạt | Candidate | REVIEW |
| --- | ---: | ---: | ---: | ---: |
| Numeric | 100 | 100 | 96 | 4 |
| Underscore | 100 | 99 | 99 | 1 |

`candidate.parquet` giữ nguyên 195 dòng theo gate đóng băng để tái hiện phép thử. **File này chưa được phê duyệt release**; review bổ sung dưới đây phát hiện hai trang trong số 195 còn cần xem xét nguồn.

## Vấn đề mới 1 — nhầm ID header người trả lời với ID answer

**ID 2401990**, `https://ask.39.net/question/_27vnb5.html`:

- Có hai answer của cùng người trả lời, cùng header `reply_41561620`, nhưng ngày trả lời khác nhau.
- Hai answer có ID riêng trong tham số tĩnh của link `showReportModal`: **168259322** và **163288714**.
- Parser hiện dùng header `reply_...` làm `answer_id`, dẫn đến trùng định danh. Gate đã gắn `duplicate_answer_id`/`parser_not_complete` và chặn trang ở REVIEW.
- Text của cả hai answer vẫn được giữ; không được tự gộp chỉ vì text giống nhau.

**Hướng sửa tiếp:** tách ID DOM/header/tác giả khỏi định danh answer/thread; lấy ID answer nguồn khi có bằng chứng, dùng fallback theo locator khi thiếu và giữ REVIEW nếu còn mơ hồ. Cập nhật đồng bộ parent follow-up, audit và export; không chỉ đổi chuỗi ID để vượt cờ trùng.

## Vấn đề mới 2 — chức danh chưa được policy nhận diện

Bốn trang bị gate giữ REVIEW:

- **2259840**, **2264552**, **2267330**: nguồn ghi `助理医师`, chưa có trong rule chức danh hiện tại.
- **2290625**: hai answer có header chức danh trống.

Cần chuẩn hóa role từ header có bằng chứng và test biến thể; không suy nghề từ tên hoặc coi thiếu header là bác sĩ đã xác minh. Ca thiếu thông tin vẫn cần giữ REVIEW.

## Vấn đề mới 3 — review nguồn phát hiện tín hiệu chưa được gate bắt

Đã lập packet **36 trang**: toàn bộ 5 REVIEW, 20 candidate chọn ngẫu nhiên seed cố định và đại diện các nhóm template/cấu trúc. Khi xem đoạn nguồn/candidate, có hai candidate cần review bổ sung:

- **2229930 / reply_21717536**: giới thiệu phương pháp điều trị cụ thể kèm khẳng định chữa từ gốc.
- **2252991 / reply_33885607**: mô tả điều trị và khẳng định chặn tiến triển/ít tái phát; cần đánh giá theo ngữ cảnh nguồn.

Đây là **tín hiệu cần review**, không phải kết luận tự động sai y khoa. Đã lưu text, locator và raw hash tại `f5_assistant_review.json`, `human_labels=false`. Không sửa nhãn gate cũ hoặc xóa hai dòng khỏi candidate để che kết quả holdout.

**Hướng sửa tiếp:** mở rộng rule quảng bá/claim theo câu, đoạn và người nói; có negative fixture cho tư vấn thông thường, phủ định và nội dung bệnh nhân trích dẫn. Không bắt mọi chữ “疗法” hoặc “根治”. Sau khi dùng các ca này để sửa, chúng trở thành regression; lần xác nhận tiếp cần mẫu mới.

## Test và bằng chứng

- **50/50 test trong notebook pass**, gồm 8 test F5 mới: chọn mẫu tái lập/loại baseline, độc lập 200 URL, replay diff, fingerprint đóng băng, export đúng ID, biên nhận kiểm raw hash, packet review và ca định danh mới được chặn an toàn.
- Test pass không đồng nghĩa holdout đạt readiness: test F5 kiểm rằng ca lỗi được phát hiện/giữ REVIEW; trạng thái cuối vẫn `NEEDS_FIX`.
- Tất cả test mới viết trực tiếp trong cell của `notebooks/check_ask.39.net.ipynb`, có output. Run All mặc định kiểm artifact/replay offline, không gọi lại 200 URL. Ba test check/audit có sẵn cũng pass.
- Replay: `runs/ask39_f5_replay50_20261022`.
- Holdout: `runs/ask39_f5_holdout200_20261022`, gồm raw, records, manifest, mẫu, candidate/decisions, `verified_raw.json`, `f5_holdout_summary.json`, audit độc lập và packet review.
- Gói ZIP chứa replay và holdout: `runs/ask39_f5_evidence_20261022.zip`.
- Helper: `scripts/ask39_f5.py`; notebook check vẫn trong `.gitignore`.

Fingerprint parser/gate/audit trong replay và holdout khớp nhau:

```text
ask39.py       678522a7098a51539058f37c8ef63771ad4d5c0b953a892dc18236747779efa1
ask39_gate.py  d865c65d64f11a62b073bc43c1c883abb32ada0aec859e37d8129ab1962154d6
ask39_audit.py 6c77402889beabd94035deb9c5e0d2b586595f5ea3b242ca88a197ac3d457ce4
```

**Bước tiếp theo:** sửa định danh answer và các rule nguồn còn thiếu, replay 250 HTML hiện có, rồi chạy một holdout xác nhận mới. Chưa tích hợp production F6 hoặc upload corpus.
