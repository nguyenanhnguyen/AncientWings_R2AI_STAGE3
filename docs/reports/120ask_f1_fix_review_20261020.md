# Sửa F1 và kiểm chứng trên 1.000 HTML — 20/10/2026

**Kết luận: F1 đã sửa được trên các ca đã xác nhận và tập replay này.** Cả sáu reply audio chỉ có lời nhắc thao tác đã chuyển từ INCLUDE/mixed sang EXCLUDE/audio-only. Mixed có nội dung thực được giữ; text quá ngắn sau khi bỏ lời chúc được chuyển REVIEW.

Run mới: `runs/ask120_review_20261020T023349637321Z`, tạo lúc **09:33:49 ngày 20/10/2026, giờ Việt Nam**. Đây là offline replay cùng 1.000 HTML của lần review trước, không phải crawl một mẫu URL mới. Có **0 request mạng**. Mốc so sánh F1 là `ask120_review_20261020T013753043042Z` / parser V3.1.

## Thay đổi

- Parser nâng thành `120ask-parser-v3.2`; extractor family vẫn V3, gate/admission v2 và schema Parquet giữ nguyên.
- Bỏ đúng đoạn khớp năm mẫu đã quan sát: nhắc chấp nhận câu trả lời, hai biến thể hỗ trợ bác sĩ trả lời lúc rảnh, nhắc chuyển sang tư vấn trực tuyến và lời chúc sức khỏe chung. Dùng ranh giới câu và nội dung template cụ thể.
- Chuẩn hóa trước khi phân loại media và áp ngưỡng độ dài; tính lại media type sau khi bỏ tail khớp title. Remainder chỉ có nhãn cũng không được coi là câu trả lời.
- Giữ nguyên raw text/hash, URL audio và DOM locator. Normalization action ghi rule ID, đoạn bị bỏ, offset trên text trước action và hash trước/sau. Không áp bỏ template người trả lời cho lời bệnh nhân hoặc follow-up chưa xác định vai.
- Build lại snapshot trong hai notebook crawl/domain và notebook check. Thêm chín fixture HTML thực, manifest SHA-256 và test riêng cho F1.

## Kết quả kiểm thử

Trước khi sửa, test mới tái hiện sáu false INCLUDE cùng lỗi độ dài bị lời chúc làm sai lệch. Sau khi sửa:

| Kiểm tra | Kết quả |
|---|---:|
| Unittest nhóm `*120*.py` | 52/52 đạt |
| Unittest nhóm `test_notebook_*.py` | 198/198 đạt |
| Test độc lập sau bỏ 12 test trùng giữa hai nhóm | 238 đạt |
| Ca mixed thực trong fixture và replay | 9/9 đúng kỳ vọng |
| Regression cũ của gate | 9/9 đạt |
| Raw kiểm hash / parse thành công | 1.000/1.000 |
| Raw/parse error | 0 |
| DOM turn locator đã kiểm | 1.829 |
| Candidate source span đã kiểm | 1.491 |
| Lỗi hash/ID/schema/locator/span | 0 |
| Parquet và JSONL theo cột production | Khớp từng record |

Test mới còn phủ text thật nằm trước/sau template, footer nằm liền sau dấu câu ASCII, text-only, audio không có URL, nhãn rỗng, câu trích dẫn, từ tương tự trong nội dung thật, lời bệnh nhân và media type sau bỏ tail. Sau khi xem delta replay, bổ sung assertion cho footer inline và chạy lại riêng 9 test F1: đạt toàn bộ. Không chạy lại toàn notebook trong kernel ở lượt này; đã kiểm snapshot bằng test notebook và chạy pipeline replay/audit thực tế.

## Tác động dữ liệu so với V3.1

| Chỉ số | Trước | Sau |
|---|---:|---:|
| Candidate document | 775 | **772** |
| Thread INCLUDE | 1.260 | **1.253** |
| Thread REVIEW | 223 | **224** |
| Thread EXCLUDE | 75 | **81** |
| Sáu UI-only audio lọt INCLUDE | 6 | **0** |

Đã đọc/đối chiếu toàn bộ **10 thread thay đổi**:

- `1025409`, `1029798`, `1031179`, `1053679`, `1087866`, `1404664`: sáu main answer bỏ lời nhắc rồi rỗng, giữ evidence audio, chuyển EXCLUDE với `AUDIO_ONLY`. Bốn trang có thread tốt bên cạnh vẫn còn candidate.
- `1159296`: chỉ bỏ lời chúc, giữ nguyên nội dung thật, vẫn mixed/INCLUDE.
- `1173870`: bỏ lời chúc còn `伊可新钙尓奇d`, giữ text để review, chuyển `SHORT_MAIN_ANSWER_REVIEW`.
- `941868`, `1389898`: chỉ bỏ footer nhắc thao tác nằm sau nội dung, giữ phần trả lời trước đó và quyết định INCLUDE.

Có **7 thread đổi quyết định**, 3 thread chỉ đổi text. Không thêm/bớt thread identity; raw text, raw hash, media URL, role và DOM locator của mọi turn giữ nguyên khi so hai run. Không thấy nội dung thực bị xóa trong 10 delta đã kiểm; đây là kiểm trích xuất, không xác nhận các lời nguồn đúng y khoa.

Ba document rời candidate là `1031179`, `1404664` (không còn main answer chữ hợp lệ) và `1173870` (không còn thread INCLUDE sau khi chuyển câu ngắn sang REVIEW). Vì vậy kết quả thực là **772**, thay vì mốc 773 chỉ tính riêng việc bỏ sáu UI-only reply trong plan.

Không còn match của năm chữ ký template này trong các turn người trả lời thuộc INCLUDE. Kết luận này áp dụng cho các mẫu đã định nghĩa và dữ liệu đã replay; template mới vẫn cần bằng chứng và test bổ sung.

## Trạng thái và artifact

**F1: PASS. F2–F5: còn mở.** Gate tự động vẫn trả `READY_FOR_FILTERED_PILOT`; đánh giá tổng thể tiếp tục `NEEDS_PARSER_FIX` vì những finding còn lại chưa xử lý, đặc biệt attribution bác sĩ ở F2. Có 144 mục review bắt buộc, 0 nhãn con người; không điền phiếu thủ công bằng kết quả AI.

- [Tóm tắt kiểm chứng F1](../../runs/ask120_review_20261020T023349637321Z/f1_review_summary.json).
- [Đối chiếu trước/sau của 10 thread](../../runs/ask120_review_20261020T023349637321Z/f1_thread_delta.md).
- [Audit artifact](../../runs/ask120_review_20261020T023349637321Z/artifact_audit.json).
- [ZIP run](../../runs/ask120_review_20261020T023349637321Z.zip).

Các script runner/audit và log test được lưu trong `support/` của run để truy nguyên. Source fix ở `scripts/ask120.py`; test ở `tests/test_ask120_audio_boilerplate.py`.
