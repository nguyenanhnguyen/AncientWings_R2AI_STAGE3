# ask.39.net — holdout xác nhận D sau A–C

Ngày 22/10/2026. **Readiness: `NEEDS_FIX`**. Chưa tích hợp F6 hoặc xuất production.

## Mẫu và tính độc lập

- Chọn 200 URL mới với seed `20261023`: 100 numeric + 100 underscore; loại cả ID và URL của toàn bộ 250 trang regression. Không có overlap ID hoặc URL.
- Nguồn Parquet cố định SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`; 1.220.598 dòng, 32.772 URL domain. Sau loại 250: 27.472 numeric và 5.050 underscore.
- Phân bổ đều hai strata để kiểm template; tỷ lệ trong mẫu không phải ước lượng theo dân số URL toàn domain.
- Đóng băng parser/gate/audit và check helper trước crawl. Hash đầu/cuối và payload notebook trùng nhau; không sửa rule trong lượt holdout.

## Kết quả

| Chỉ số | Kết quả |
| --- | ---: |
| URL đã thử | 200 / 200 |
| URL truy cập được cuối lượt | 200 |
| Raw kiểm hash và audit độc lập | 200 |
| Answer / follow-up | 252 / 16 |
| Extraction accepted | 200 |
| Candidate theo gate đóng băng | 194 |
| REVIEW theo gate đóng băng | 6 |
| Trang assistant đã đọc | 106 |
| Trang bắt buộc trong packet đã đọc đủ | 62 |
| Accepted ngẫu nhiên trong mẫu cuối đã đọc | 20 |
| Phát hiện mới chặn release | 5 |

Audit độc lập: `{}`. Source flags gate: `{"source_qualification_unrecognized": 6}`.
Access flags cuối lượt: `{}`. Parser/audit flags của gate: `{}` / `{}`.

Lượt đầu bị sandbox chặn socket, không nhận HTML; lượt mạng được cấp quyền dùng lại đúng mẫu đã chọn. Các lỗi timeout/TLS ở lượt chính được lưu nguyên. Retry chỉ áp dụng URL lỗi mạng, không đổi mẫu hay rule.
Lượt chính: 189 requests thành công, 11 lỗi mạng; browser khôi phục 3 URL. Retry requests khôi phục thêm 7 URL; URL cuối được khôi phục bằng browser. Cuối cùng đủ 200 raw: 196 qua requests và 4 qua browser. Mọi lượt thử, lỗi ban đầu và chuỗi retry đều được giữ trong manifest/raw, không thay thế mẫu bằng URL khác.

## Phát hiện cần sửa trước F6

### 2138096 — claim an toàn chưa được gate chặn

[URL nguồn](https://ask.39.net/question/100223288.html)

- Answer: `ask39:100223288:answer:213517505`; vai `responder`; locator `/html/body/div[2]/div[2]/div[3]/div`.
- Phương pháp/thuốc: `激光治疗`; claim: `不损伤周围健康组织`.
- Tác giả/header nguồn: 李红冬; chức danh thô: `["副主任医师", "深圳市宝安人民医院"]`.
- Raw SHA-256: `68ac5d9efdd6f8c1357561c30cf2d11bb6b0faae67f46f0487e258f646675137`. Đã đối chiếu câu trực tiếp với DOM nguồn.
- Gate đóng băng vẫn accepted, chưa có source flag cho nhóm claim này. Assistant gán disposition **REVIEW_REQUIRED** và chặn release; không kết luận đúng/sai y khoa.

### 2173132 — claim an toàn chưa được gate chặn

[URL nguồn](https://ask.39.net/question/10672412.html)

- Answer: `ask39:10672412:answer:20644539`; vai `responder`; locator `/html/body/div[2]/div[2]/div[3]/div[1]`.
- Phương pháp/thuốc: `脉络舒通颗粒`; claim: `不增加出血风险`.
- Tác giả/header nguồn: 全民健康管理中心; chức danh thô: `["医师", "鲁南制药集团股份有限公司"]`.
- Raw SHA-256: `52e568298cfef3890586893004c773582284e5f3aeda515eca0dc3fa76046c1f`. Đã đối chiếu câu trực tiếp với DOM nguồn.
- Gate đóng băng vẫn accepted, chưa có source flag cho nhóm claim này. Assistant gán disposition **REVIEW_REQUIRED** và chặn release; không kết luận đúng/sai y khoa.

### 2213438 — claim an toàn chưa được gate chặn

[URL nguồn](https://ask.39.net/question/22035428.html)

- Answer: `ask39:22035428:answer:54411981`; vai `responder`; locator `/html/body/div[3]/div[2]/div[5]/div`.
- Phương pháp/thuốc: `延长手术`; claim: `不会影响性生活`.
- Tác giả/header nguồn: 刘秀芝; chức danh thô: `["副主任医师", "北京曙光医院-男科"]`.
- Raw SHA-256: `4c1d925cbff6a221c424f8bfdcb410b21d64a5e620e747bcabc3fdc3f24f5f81`. Đã đối chiếu câu trực tiếp với DOM nguồn.
- Gate đóng băng vẫn accepted, chưa có source flag cho nhóm claim này. Assistant gán disposition **REVIEW_REQUIRED** và chặn release; không kết luận đúng/sai y khoa.

### 2223535 — CTA tư vấn chưa được gate chặn

[URL nguồn](https://ask.39.net/question/28677254.html)

- Answer: `ask39:28677254:answer:67314806`; vai `responder`; locator `/html/body/div[2]/div[2]/div[4]/div[1]`.
- Phương pháp/thuốc: `中医针对病因治疗`; claim: `点击右下方的【在线咨询】`.
- Tác giả/header nguồn: 王玉堂; chức danh thô: `["主任医师", "北京军颐中医医院"]`.
- Raw SHA-256: `89df8e3fbcd5eb054b4bcb17f0c51cd8caacf1cbffca61cc89a18b6a4abdc589`. Đã đối chiếu câu trực tiếp với DOM nguồn.
- Gate đóng băng vẫn accepted, chưa có source flag cho nhóm claim này. Assistant gán disposition **REVIEW_REQUIRED** và chặn release; không kết luận đúng/sai y khoa.

### 2402453 — claim an toàn chưa được gate chặn

[URL nguồn](https://ask.39.net/question/_2e5y05.html)

- Answer: `ask39:_2e5y05:answer:168860978`; vai `responder`; locator `/html/body/div[2]/div[2]/div[3]/div`.
- Phương pháp/thuốc: `放射疗法`; claim: `不会损伤周围健康组织`.
- Tác giả/header nguồn: 雷钧皓; chức danh thô: `["主治医师", "武汉大学中南医院"]`.
- Raw SHA-256: `a6b0b340aae9645870cf1c762b5cf4220050290a926db01a51280ef813f640d1`. Đã đối chiếu câu trực tiếp với DOM nguồn.
- Gate đóng băng vẫn accepted, chưa có source flag cho nhóm claim này. Assistant gán disposition **REVIEW_REQUIRED** và chặn release; không kết luận đúng/sai y khoa.

Bốn ca có cấu trúc khẳng định không gây hại/không tăng rủi ro; chữ `不/不会` ở đây thể hiện lời bảo đảm an toàn, không phải phủ định một claim chữa khỏi. Một ca quảng bá điều trị và mời tư vấn một-một ngay trong answer. Rule B hiện chỉ bao phủ tổ hợp phương pháp và hiệu quả đã quan sát trước đó; contact rule cũ chỉ bao phủ một số dạng liên hệ.

Không sửa gate để đổi kết quả ngay trên holdout này. Candidate Parquet là bằng chứng của gate đóng băng và còn chứa các ca trên; **không phải tập đã qua review để release**. Mọi record vẫn `corpus_eligible=False`.

## Bằng chứng và kiểm chứng

**100 test notebook + 3 test helper pass**, gồm 10 test D mới viết trực tiếp trong cell notebook. Tất cả code cell đã chạy thành công. Test D kiểm overlap, hash raw/code, replay quyết định gate, export, độ bao phủ review, vị trí claim trong DOM và readiness vẫn NEEDS_FIX khi còn findings. Kết quả/hash notebook thực thi nằm trong `d_verification.json` của artifact cuối.

Artifact cuối: `runs/ask39_d_holdout200_completed_20261022T034210926073Z`.
Lượt chính: `runs/ask39_d_holdout200_20261022T031918689744Z`.
Code đóng băng: `runs/ask39_d_frozen_20261022T031918689744Z`.
- `sample.jsonl`, `manifest.json`, raw và records: mẫu, nguồn/hash, cấu hình crawl và provenance retry.
- `candidate.parquet`, `candidate.decisions.jsonl`: export và quyết định gate giữ nguyên.
- `d_review_data.json`, `d_review_packet.md`, `d_signal_screen.json`: audit toàn bộ raw có được; tất cả REVIEW/error, đại diện từng nhóm template, 20 accepted ngẫu nhiên và screen bổ sung.
- `d_assistant_review.json`, `d_final_summary.json`: danh sách đã đọc, findings, bằng chứng source ID/locator/raw hash và kết luận readiness.
- Cell mới tag `ask39-fix-d` trong [notebook check](../../notebooks/check_ask.39.net.ipynb) nhúng raw/evidence để kiểm lại offline; notebook tiếp tục được gitignore theo yêu cầu. Review do assistant thực hiện, không gắn nhãn human review hay xác nhận độ chính xác lâm sàng của nội dung nguồn.

## Hướng tiếp theo

1. Thêm rule review claim an toàn tuyệt đối theo phương pháp/thuốc và vai responder; giữ bằng chứng riêng. Bao phủ các ca mới và biến thể không gây hại/không tăng rủi ro, đồng thời kiểm phủ định lồng, lời thuật lại và lời bệnh nhân. Không bắt mọi nhắc tên thuốc hoặc mô tả giảm rủi ro.
2. Mở rộng contact/promotion rule cho lời mời click tư vấn trực tuyến theo người nói và ngữ cảnh. Giữ nguyên text nguồn, không xóa CTA trong answer để né REVIEW; không bắt nhầm lời bệnh nhân hoặc mô tả giáo dục một-một như ca âm 2444995.
3. Đưa 200 URL D thành regression và replay tổng 450 URL sau sửa; đối chiếu text, source ID, parent và toàn bộ quyết định. Các ca mới phải REVIEW; các ca âm phải giữ đúng.
4. Đóng băng lại rồi kiểm một mẫu 200 URL mới khác, loại toàn bộ 450 ID/URL đã dùng. Chỉ cân nhắc F6 khi không còn phát hiện chưa xử lý trong lượt xác nhận mới.
