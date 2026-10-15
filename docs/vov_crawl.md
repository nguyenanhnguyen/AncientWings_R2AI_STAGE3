# Crawl VOV bằng curl/Chrome

`crawl_corpus_kaggle_hf_upload.ipynb` và `crawl_domain_samples.ipynb` mặc định có
`VOV_USE_CURL = True`. Cả `vov.vn` và các subdomain như `vov2.vov.vn`, `www.vov.vn`
dùng `curl_cffi.requests.Session(impersonate="chrome", verify=True)` ngay từ request đầu.
Corpus nguồn hiện có 9.784 URL `vov.vn` và 6.899 URL `vov2.vov.vn`.

Session/cookie được dùng lại trong nhóm VOV. Nhóm này chạy một request tại một thời điểm,
kể cả khi `WORKERS` lớn hơn 1; các domain khác vẫn có thể chạy song song.
Giữ nhịp `DELAY`, `PAGE_ATTEMPTS`, timeout và budget đang cấu hình cho lượt HTTP
(mặc định delay 1 giây, timeout 20/45 giây, budget 180 giây). Profile Chrome của curl
giữ header mặc định, không bị ghi đè bằng header Requests. Redirect được ghi từng hop,
xác minh địa chỉ công khai, giới hạn body 10 MiB và giữ TLS verification.
`RESPECT_ROBOTS` / `DIRECT_PUBLIC_PROBE` vẫn điều khiển kiểm tra robots; robots VOV cũng đi qua curl.

Giữ parser hiện có và schema corpus: ID/URL gốc không đổi, redirect nằm ở `final_url`,
raw gzip và text có SHA-256. Record VOV mới ghi `engine="curl_cffi"`, `impersonate="chrome"`.
VOV không đi vào lượt Selenium khi bật flag, kể cả `BROWSER_TEST_MODE="all"`.
Đặt `VOV_USE_CURL=False` sẽ dùng lại route Requests/Selenium cho VOV; thay đổi cấu hình cần run mới.
IP đo bằng Requests/Selenium trong domain samples vẫn là phép đo riêng, không chứng minh IP của curl.

HTTP 429 dừng nhóm VOV ngay từ response đầu, không thử tiếp bằng Selenium.
403/challenge cũng dừng nhóm. `Retry-After` dạng số giây hoặc HTTP-date được lưu ở
`vov_request_gate.json`; khi cooldown vượt budget thì hoãn để resume, không chờ vô hạn.
Timeout/lỗi kết nối/5xx vẫn có retry hữu hạn theo cấu hình; lỗi TLS không bỏ qua xác minh.
URL VOV đã extracted được giữ lại khi resume. Checkpoint lỗi được lưu lịch sử trong
`vov_previous_records/` trước khi thử lại. Gián đoạn vẫn lưu các record đã hoàn tất
và checkpoint chung của runner. Báo cáo có `vov_curl` riêng, không đếm vào `longchau_curl`.

Run VOV cũ cần **RUN_TAG mới + RECOVERY_RUN_PATH** (domain samples: `RECOVERY_RUN_DIR`).
Recovery tái trích raw thành công đã xác minh hash, giữ gate cũ và thử lại phần lỗi/thiếu.
Notebook corpus chặn resume code cũ trước khi thay snapshot hay records để không âm thầm
tiếp tục VOV bằng Requests. Dùng ZIP đầy đủ để recovery; diagnostics ZIP chỉ có raw mẫu.

Sửa code và tạo lại notebook bằng:

```powershell
python scripts/build_longchau_notebooks.py
```

Ngày 15/10/2026 đã chạy thật từ nguồn corpus trên **Windows local**, seed `20261015`,
3 URL mỗi hostname: **6/6 HTTP 200, 6 extracted/accepted**, giữ ID/URL/hash raw,
không khởi động Selenium dù cấu hình browser là `all`. Đây là kiểm tra truy cập và QC
tự động trên mẫu nhỏ, chưa phải đánh giá nội dung chuyên gia hoặc bảo đảm IP Kaggle.
Artifact ngoài Git: `runs/vov_curl_check_20261015T121836Z/live_vov_result.json` cùng
raw/records và checkpoint ZIP đầy đủ cạnh thư mục run. Không upload HF trong test này.
