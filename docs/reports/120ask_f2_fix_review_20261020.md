# Sửa F2 và kiểm chứng trên 1.000 HTML — 20/10/2026

**Kết luận: F2 đã sửa được trong các kiểm tra và tập replay này.** Không còn gán vai hội thoại thành nghề bác sĩ. Tất cả thread INCLUDE có nghề thuộc allowlist và bằng chứng tác giả từ qualification header. Tác giả khác/chưa rõ hoặc chưa chứng minh được quan hệ với reply được giữ REVIEW; dược sĩ và điều dưỡng không bị loại đồng loạt.

Run: `ask120_f2_20261020T041719385491Z`, tạo lúc **11:17:19 ngày 20/10/2026, giờ Việt Nam**. Offline replay cùng 1.000 HTML, **0 request mạng**. So sánh chính với run sau F1 `ask120_review_20261020T023349637321Z` / parser V3.2. Không phải mẫu URL độc lập mới.

## Thay đổi đã triển khai

- Parser/extractor V4, gate/admission v3. Vai hội thoại dùng `responder_answer`, `responder_followup`, `patient_followup`, `unknown_followup`, cùng `turn_kind` và `speaker_role` độc lập với nghề nghiệp.
- Lưu tên/profile URL quan sát được, text header, qualification nguyên văn, chức danh được nhận diện, `source_role`, trạng thái và DOM evidence. Không đọc nghề từ nickname. Header/qualification text thu gọn whitespace; raw response và header HTML/locator được giữ để đối chiếu.
- Text hiển thị nhãn người trả lời trung tính. Chức danh nếu hiển thị có nhãn `来源职称` — chức danh do nguồn công bố, không khẳng định đã xác minh giấy phép.
- Allowlist ban đầu: bác sĩ/y sĩ, dược sĩ, điều dưỡng. `其他`, không nhận diện được chức danh, nghề ngoài allowlist hoặc identity mơ hồ chuyển REVIEW. Giữ nguyên nội dung và header để review.
- Card nhiều reply chỉ giữ tác giả quan sát được trong `card_author`, không truyền tên/nghề cho từng reply. Lời bệnh nhân không kế thừa nghề; follow-up có tên người trả lời khác hoặc marker hội thoại xung đột được giữ review.
- Chặn nhãn INCLUDE thủ công vượt lỗi author chưa giải quyết; thêm invariant author trước xuất candidate. JSONL có `thread_authors` và author trong source span; schema Parquet giữ nguyên.
- Thay counter cũ bằng `responder_followups`, cập nhật consumer, regression, builders và snapshot của hai notebook crawl/domain cùng notebook check. Run/checkpoint và nhãn có hash cũ không được dùng lại như kết quả V4.

## Kết quả dữ liệu so với V3.2 sau F1

| Chỉ số | Trước | Sau |
|---|---:|---:|
| Candidate document | 772 | **651** |
| Thread INCLUDE | 1.253 | **928** |
| Thread REVIEW | 224 | **549** |
| Thread EXCLUDE | 81 | **81** |
| Thread INCLUDE có nghề ngoài allowlist/không đủ bằng chứng tác giả | Chưa được chặn bằng gate F2 | **0** |

Có **325 thread chuyển INCLUDE → REVIEW**; không có thay đổi quyết định theo hướng ngược lại. Nhóm này gồm:

| Bằng chứng nghề mới | Thread chuyển REVIEW |
|---|---:|
| `其他` được nhận diện | 305 |
| Nghề xét nghiệm được nhận diện, ngoài allowlist | 11 |
| Tư vấn tâm lý được nhận diện, ngoài allowlist | 2 |
| Qualification chưa ánh xạ được | 7 |

Trong bảy qualification chưa ánh xạ có `三级公共营养师`, `四级检验师` và header có tên cơ sở + `其他`. Các chuỗi này được giữ nguyên và REVIEW, không suy thành bác sĩ. Con số 305 tính trên baseline V3.2 sau F1; mốc 307 trong báo cáo trước F1 thuộc một trạng thái candidate khác.

Nhóm **928 INCLUDE** còn lại có chức danh nguồn:

| Vai nghề nghiệp | Thread |
|---|---:|
| Bác sĩ/y sĩ | 837 |
| Điều dưỡng | 85 |
| Dược sĩ | 6 |

121 document rời candidate vì không còn thread INCLUDE. Trang còn thread đủ điều kiện được giữ theo cơ chế INCLUDE_PARTIAL; trang chỉ còn REVIEW tiếp tục nằm ngoài candidate. **ID nguồn, thread identity, thứ tự turn, text nội dung từng turn, raw text/hash và media URL giữ nguyên** khi so hai run. Text document đổi do nhãn trung tính/chức danh nguồn và tập thread được nhập thay đổi.

## Kiểm thử và audit

| Kiểm tra | Kết quả |
|---|---:|
| Nhóm unittest `*120*.py` | **65/65 đạt** |
| Nhóm unittest `test_notebook_*.py` | **198/198 đạt** |
| Test độc lập sau bỏ 12 test trùng | **251 đạt** |
| Test riêng F2 trong các nhóm trên | 13 method, gồm 7 fixture HTML thực và các ca tổng hợp |
| A/B manual-review / resume / media, phía candidate | **1/1 + 7/7 + 6/6** |
| A/B impact replay | **1.000/1.000, đạt** |
| Gate regression cũ | **9/9 đạt** |
| Ca đối chứng F1 trong replay | **9/9 đạt** |
| Raw kiểm hash và re-extraction audit | **1.000/1.000** |
| DOM turn locator / candidate source span | **1.829 / 1.124** |
| Đối chiếu metadata tác giả với header DOM | **4.734 lượt kiểm** |
| Raw/parse error, lỗi artifact/invariant | **0** |
| Parquet và JSONL theo cột production | Khớp từng record |

4.734 là số lượt kiểm metadata ở card/thread/turn, có lặp cùng header; không phải 4.734 người khác nhau. Audit dựng lại qualification từ text/tail cạnh node tên, kiểm tên/header/DOM ownership và đối chiếu toàn bộ parsed record với raw re-extraction.

Trước khi sửa, bộ test mới tái hiện gán `doctor_answer` từ vị trí DOM, thiếu provenance và khả năng duyệt INCLUDE một tác giả chưa rõ vai. Sau sửa, test phủ chức danh hợp lệ, nickname gây nhầm, header mất/mơ hồ, card nhiều reply, bệnh nhân/người trả lời follow-up, nhãn thủ công và sidecar. Các fixture cũ chỉ có nickname giờ được kỳ vọng REVIEW; test duyệt claim dùng một tác giả có qualification rõ để kiểm riêng luồng đó.

Thí nghiệm A/B tiếp tục giữ baseline V3 đóng băng trước các fix cũ, nên mốc candidate của thí nghiệm là 775 → 651. Bảng chính ở trên so trực tiếp V3.2 sau F1: **772 → 651**. Đã chạy các hàm được cell thí nghiệm gọi và replay pipeline thực tế; không chạy lại toàn notebook trong kernel ở lượt này.

## Review bằng chứng và giới hạn

Đã đọc packet **69 header**: 50 INCLUDE phân tầng theo nghề với seed mới, thêm các thread thuộc fixture thực chưa trùng. Ví dụ `徐医生` có header `副主任护师` được nhận diện là điều dưỡng; nickname `张永斌医师` nhưng header `其他` được giữ REVIEW. Đã đối chiếu thêm bảy qualification chưa ánh xạ từng ở INCLUDE và thống kê toàn bộ 325 delta quyết định.

Ca peer-sharing `1351960 / card1:reply2180544` vẫn giữ nguyên lời nguồn, source role `other`, quyết định REVIEW; không còn hiển thị như câu trả lời bác sĩ. Các ca multiple-reply và mismatch follow-up có test riêng. Ghi chú AI được lưu riêng, không điền phiếu con người.

**F1 và F2: đã xử lý. F3–F5: còn mở.** Gate tự động vẫn `READY_FOR_FILTERED_PILOT`; kết luận tổng thể tiếp tục `NEEDS_PARSER_FIX` theo các finding còn lại. Run mới có **532 mục cần review, 0 nhãn con người**. Kết quả này xác nhận trích xuất/attribution theo nguồn trong phạm vi đã kiểm, không xác minh giấy phép hoặc nội dung y khoa của tác giả.

## Artifact

- [Tóm tắt F2](../../runs/ask120_f2_20261020T041719385491Z/f2_review_summary.json).
- [Audit tác giả toàn bộ thread](../../runs/ask120_f2_20261020T041719385491Z/f2_author_audit.jsonl).
- [325 thay đổi quyết định](../../runs/ask120_f2_20261020T041719385491Z/f2_thread_decision_delta.jsonl).
- [Packet header đã review](../../runs/ask120_f2_20261020T041719385491Z/f2_header_review_packet.md).
- [Audit artifact](../../runs/ask120_f2_20261020T041719385491Z/artifact_audit.json).
- [ZIP run đầy đủ](../../runs/ask120_f2_20261020T041719385491Z.zip).

Source: `scripts/ask120.py`, `scripts/ask120_gate.py`; test F2: `tests/test_ask120_author_roles.py`, fixture tại `tests/fixtures/120ask_f2/`. Log test, runner/source và kết quả A/B được lưu trong run để truy nguyên.
