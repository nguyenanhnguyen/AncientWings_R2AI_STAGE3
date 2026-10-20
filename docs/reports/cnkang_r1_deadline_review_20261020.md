# Review R1: deadline mạng cnkang.com — 20/10/2026

R1 bổ sung giới hạn tổng thời gian cho request và URL, thay cho việc chỉ dựa vào
connect/read timeout của Requests. Phần thí nghiệm và output nằm trong một notebook
local đã được gitignore: notebooks/check_cnkang.com.ipynb.

## Thay đổi

- scripts/cnkang_request_worker.py chạy Requests trong tiến trình riêng, giữ session
  giữa các request thành công. Worker chỉ trả dữ liệu và trạng thái qua pipe.
- scripts/cnkang_network.py giám sát deadline, terminate/kill và chờ worker kết thúc.
  Thread trong supervisor chỉ đọc pipe; DNS/socket nằm trong worker có thể kết thúc.
  Kết quả đến sau deadline bị từ chối; budget hết trước lúc chạy sẽ không mở worker.
- scripts/cnkang_transport.py mặc định 45 giây/request, 120 giây/URL. Robots,
  throttle, crawl-delay, redirect và retry dùng cùng budget URL. Mỗi request bị
  chặn bởi phần budget còn lại. Supervisor giữ toàn bộ ghi raw/checkpoint.
- Lỗi có error_kind, error_stage, chuỗi exception gốc và mã errno/WinError khi
  có. Các giai đoạn gồm DNS, connect, read_headers, read_body, worker_start và
  throttle. Robots không che nguyên nhân mạng bằng nhãn unverifiable chung.
- Hết deadline hoặc worker hỏng sẽ dừng lượt cnkang; chuỗi ba URL lỗi mạng cũng
  dừng. DNS không kích hoạt fallback HTTP. Quy tắc robots và cooldown được giữ.
- Crawler chính và notebook check nhúng cùng supervisor/worker, kiểm SHA-256 và
  đưa cả hai vào identity của run. Run cũ cần thư mục mới/recovery.

## Vòng sửa và test

1. Bộ test ban đầu đạt 45/45. Lượt live đầu xử lý 50/50 URL trong 84,040 giây,
   có 51 phản hồi HTTP 200 gồm robots; không có lỗi mạng hoặc vượt deadline.
2. Review bổ sung tìm thấy nhánh khởi động worker thất bại có thể bị gắn nhãn
   checkpoint. Test giả lập OSError khi khởi động đã tái hiện lỗi này.
3. Đã sửa thành network_worker_error, giữ errno/nguyên nhân và dừng ngay cả
   khi lỗi xảy ra lúc lấy robots. Bổ sung kiểm tra không khởi động worker khi
   budget đã hết. Bộ test sau sửa đạt **47/47**.
4. Chạy lại cùng manifest 50 URL với snapshot cuối trong run riêng để kiểm hồi quy;
   lượt đầu và raw/checkpoint F1 được giữ nguyên.

Lệnh test:

    .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p '*cnkang*' -v

Các ca lỗi dùng tiến trình thật và mạng giả lập, không gây treo website thật:
DNS treo, chờ header, body nhỏ giọt, DNS lỗi 11001, reset 10054, read timeout bị bọc
trong ConnectionError, worker không khởi động được, budget robots/redirect/throttle,
kết quả đến muộn, giữ session và giới hạn kích thước. Ba ca treo dùng deadline 1,5
giây và kiểm kết thúc dưới 3,5 giây gồm dọn worker; kiểm process đã chết, thread đọc
pipe đã dừng và request mới không nhận kết quả muộn. Các test 403/429, resume,
parser F1 và tích hợp crawler không Selenium tiếp tục đạt.

## Mẫu kiểm

Seed 2026102007, chọn ngẫu nhiên đồng đều 50 canonical URL từ 38.074 URL còn lại.
Loại 2.171 canonical URL trong lịch sử đã biết và toàn bộ manifest F1 1.000 URL;
1.969 trong số đó hiện diện trong population 40.043 URL. Hai lượt R1 dùng **cùng
50 URL**, không phải 100 URL độc lập.

Manifest SHA-256:
32d461683fd4b4e746003149918541305754d6c24515e2d3860416f4c6edcd65.
Lịch sử xa hơn chưa được chứng minh đầy đủ. Run config lưu hash input parquet,
hai nguồn lịch sử, parser, transport, supervisor và worker.

## Kết quả bản cuối

Lượt cuối hoàn tất **50/50 URL trong 85,836 giây**, không còn pending.

| Chỉ số | Kết quả |
|---|---:|
| Request gồm robots + 50 trang | 51 |
| HTTP 200 | 51/51 |
| Lỗi DNS/connect/read/deadline | 0 |
| Request chậm nhất | 1,879 giây |
| Request p50 / p95 | 0,091 / 0,697 giây |
| URL p50 / chậm nhất, gồm khoảng nghỉ | 1,593 / 3,492 giây |
| Khoảng nghỉ nhỏ nhất quan sát được | 1,501 giây |
| Raw đúng SHA-256 / audit parser | 50/50 / 50/50 |
| Text SHA-256 giống giữa hai lượt | 50/50 |
| Sạch parser / còn cờ review | 35 / 15 |

Toàn bộ 51 request dùng một worker/session; mỗi trang có một attempt, không redirect
hoặc fallback. Snapshot của lượt cuối khớp source production và các payload dùng
trong crawler/check. Không có kết quả thành công đến quá budget.

15 trang cần review là cờ parser/nội dung, không phải lỗi deadline:

| Cờ | Số trang | ID |
|---|---:|---|
| SHORT_TEXT_REVIEW | 9 | 1718613, 1718877, 1724221, 1727265, 1734447, 1783274, 1823958, 1858577, 1919975 |
| DESCENDING_NUMBERING_REVIEW | 5 | 1701278, 1722273, 1728966, 1865596, 1998296 |
| PUA_FORMATTING_REVIEW | 1 | 1701278 |
| POSSIBLY_TRUNCATED_REVIEW | 1 | 1848793 |

Các cờ chồng nhau ở ID 1701278. Source flags: 50 thiếu tác giả xác minh được, 31 cờ
title/body alignment, 1 tín hiệu quảng bá và 2 trải nghiệm cá nhân. Đây là tín hiệu
heuristic cần review, không phải kết luận nguồn sai hoặc nội dung đúng y khoa.
R1 không gỡ những cờ này.

Kiểm thêm ID 1848793: raw dài 20.592 byte có thẻ đóng HTML, text 2.748 ký tự kết
thúc bằng dấu ba chấm và giống ở cả hai lượt. Chưa thấy bằng chứng worker cắt body;
cờ POSSIBLY_TRUNCATED ở đây có khả năng là dương tính giả do cách kết câu của nguồn.
Giữ nguyên cờ để đánh giá trong phần QC sau.

Nguồn số liệu: r1_review_summary.json và final_verification.json trong run cuối.

## Phạm vi kết luận

Test lỗi chứng minh cơ chế cắt DNS/read treo và giữ nguyên nhân; lượt live kiểm
đường chạy thông thường. Không suy ra lỗi DNS của môi trường bên ngoài đã biến mất.
Deadline cần supervisor được hệ điều hành lập lịch; khi máy bị suspend, kết quả
quá hạn bị từ chối lúc chạy lại. Thời gian dọn worker được giới hạn riêng.

Đã kiểm trên Windows/Python 3.14 và runner notebook IPython. Snapshot độc lập không
phụ thuộc pickle closure của notebook; chưa chạy trực tiếp trên Kaggle/Linux.
R2 xử lý khóa file checkpoint và các mục parser/QC còn lại thuộc lượt sửa riêng.

Artifacts local:

- runs/cnkang_r1_50_20261020/: lượt đầu, snapshot trước sửa nhánh worker_start.
- runs/cnkang_r1_50_20261020_pass2/: lượt kiểm cuối, raw, records, journal,
  run_config.json, sample_manifest.jsonl, summary.json, results.parquet,
  pass_outcome.json, r1_review_summary.json và final_verification.json.
- Notebook duy nhất giữ riêng output từng lượt; mặc định xem lại, không tự phát
  request khi đọc kết quả.
