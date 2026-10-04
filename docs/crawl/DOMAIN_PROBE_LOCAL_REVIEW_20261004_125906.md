# Review và sửa lỗi truy cập từ run local mới nhất

Review ngày 04/10/2026. Phạm vi: 25 URL mẫu của 5 domain, tập trung vào `http_error` và `network_error`.

## Nguồn và kết quả

- Run người dùng: `notebooks/runs/domain_probe_20261004_125906_1b2697`, Requests bắt đầu khoảng 19:59 giờ Việt Nam.
- Notebook có output được giữ tại [baseline_local_notebook.ipynb](../../runs/domain_probe_review_20261004_125906/baseline_local_notebook.ipynb) trước khi cập nhật notebook.
- Lượt kiểm chứng: [recovery/ket_qua.html](../../runs/domain_probe_review_20261004_125906/recovery/ket_qua.html), hoàn tất báo cáo lúc 20:30 ngày 04/10/2026.
- Recovery kiểm tra và tái trích xuất raw của 18 URL đã tải thành công; chỉ request lại 7 URL lỗi. Giữ nguyên 25 checkpoint và raw của run gốc.

| Domain, xếp theo số URL nguồn | Số URL trong dataset | Requests run gốc | Requests sau sửa | Lỗi truy cập còn lại |
| --- | ---: | ---: | ---: | --- |
| www.cnkang.com | 963.438 | 5/5 | 5/5, reuse raw | Không |
| www.120ask.com | 918.479 | 5/5 | 5/5, reuse raw | Không; 3 mẫu vẫn có cờ QC như trước |
| www.familydoctor.com.cn | 447.453 | 5/5 | 5/5, reuse raw | Không |
| ask.39.net | 337.375 | 3/5 | 5/5 | Hai mẫu lỗi mạng được phục hồi |
| zysjonline.com | 243.347 | 0/5 | 0/5 | 5 HTTP 403/challenge |

Run gốc có 18 `extracted`, 2 `network_error`, 5 `http_error`. Selenium trong run gốc tải được thêm một mẫu `ask.39.net`, nên nếu tính kết quả cuối cả hai engine thì baseline là 19/25; bảng cũ chỉ đếm Requests nên hiện 18/25.

Sau sửa: Requests 20/25, `network_error` 0, `http_error` 5. QC: 17 accepted, 3 review. Selenium thử 5 mẫu zysjonline còn lỗi, cả 5 vẫn HTTP 403; không có mẫu nào phục hồi thêm. Đây là kết quả của các mẫu đã chạy, không phải kiểm chứng toàn bộ URL của 5 domain.

## 1. ask.39.net: lỗi mạng tạm thời đã phục hồi trong lượt kiểm chứng

Hai ID cần sửa trước khi chạy lại:

| ID | URL | Run gốc | Lượt Requests sau sửa |
| ---: | --- | --- | --- |
| 2211756 | https://ask.39.net/question/20931974.html | 2 ReadTimeout; Selenium sau đó HTTP 200 | Lần 1 ConnectTimeout 20,027 giây; lần 2 HTTP 200 sau 30,300 giây; 683 ký tự, accepted |
| 2243902 | https://ask.39.net/question/36416578.html | ReadTimeout rồi RemoteDisconnected; Selenium timeout, about:blank | Lần 1 ReadTimeout 45,920 giây; lần 2 HTTP 200 sau 4,639 giây; 694 ký tự, accepted |

Trong cả hai trường hợp kiểm chứng, retry thứ hai dùng session/pool kết nối mới, giữ cookies và cấu hình HTTP, chờ backoff khoảng 2,3 giây. Dữ liệu cho thấy các URL có thể tải được; lỗi gốc không chứng minh chúng đã bị xóa. Vì điều kiện mạng thay đổi theo thời điểm, lượt kiểm chứng này không tách riêng được mức đóng góp của timeout, kết nối mới và thay đổi phía server.

## 2. zysjonline.com: HTTP 403/challenge còn tồn tại

Các ID: `4182981`, `4178992`, `4186497`, `4382993`, `4307342`.

Requests nhận HTTP 403, `Server: cloudflare`, HTML có tiêu đề `Just a moment...`. Selenium Chrome 154.0.8037.93, dùng User-Agent thực của phiên bản đang chạy và chờ nội dung tối đa 15 giây, vẫn nhận HTTP 403 và trang `Performing security verification` cho cả 5 URL.

Đây là phản hồi chặn truy cập/challenge, không phải lỗi parser hay thiếu JavaScript đơn thuần. Thay đổi retry không sửa được quyền truy cập trong các thử nghiệm này. Code giữ nguyên HTTP 403, `challenge_detected=true`, `error_kind=http_403_challenge`, raw, screenshot và lỗi gốc; không đưa nội dung trang challenge vào corpus. Không retry liên tục 401/403. Những URL này cần giải quyết khả năng truy cập với website hoặc nguồn dữ liệu được website hỗ trợ trước khi đưa vào crawl diện rộng.

## Các thay đổi đã áp dụng

- `priority_probe.py` v2: Requests mặc định 3 attempts, connect 20 giây, read 45 giây, budget 180 giây mỗi URL. Các URL cùng registered domain vẫn chạy tuần tự.
- Network retry đóng pool lỗi và tạo session mới, giữ cookies/header/cấu hình; phân biệt connect/read timeout, DNS, SSL, connection closed/reset. Lỗi SSL không được retry hay bỏ kiểm tra chứng chỉ.
- HTTP 408/429/5xx được retry trong budget, tôn trọng cooldown/Retry-After. Nếu chờ vượt budget, ghi `retry_deferred` và giữ lỗi để thử trong recovery khác.
- Lưu raw/hash của cả HTTP response trung gian trước khi retry; ghi thời gian request riêng với thời gian backoff.
- Nhận diện challenge kể cả khi trả HTTP 200; recovery cũng kiểm tra raw để tránh reuse challenge bị bản cũ coi là thành công.
- Selenium mặc định dùng UA của Chrome thực, page-load timeout 45 giây, tối đa 2 attempts cho lỗi điều hướng/mạng tạm thời. Giữ lịch sử và screenshot theo attempt. Không retry challenge liên tục.
- `RECOVERY_RUN_DIR` tạo run mới, kiểm tra ID/URL và hash raw 2xx trước khi reuse; checkpoint lỗi được để pending và request lại. Resume bình thường vẫn bỏ qua checkpoint đã có.
- Bảng CSV/HTML/Markdown tính `access_result` cuối theo Requests hoặc Selenium phục hồi. Giữ các cột Requests gốc; bổ sung engine, HTTP, QC và số ký tự của kết quả cuối. Thứ tự ưu tiên vẫn theo số URL dataset giảm dần.

Requests có connection pooling và timeout connect/read riêng; chúng không phải một giới hạn thời gian tổng tuyệt đối. Budget của probe được kiểm tra giữa các bước, còn DNS/thử nhiều IP có thể vượt thời gian đặt. Xem [tài liệu Requests](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts). Việc đợi DOM/challenge kết thúc được thực hiện bằng explicit wait theo [tài liệu Selenium](https://www.selenium.dev/documentation/webdriver/waits/).

## Cách chạy lại nhóm lỗi trong notebook

Mở [crawl_domain_samples.ipynb](../../notebooks/crawl_domain_samples.ipynb), đặt ở ô cấu hình:

```python
RESUME_RUN_DIR = None
RECOVERY_RUN_DIR = r"D:\code\R2AI2026-stage3\notebooks\runs\domain_probe_20261004_125906_1b2697"
```

Sau đó Run All. Trên Kaggle, dùng đường dẫn run đã giải nén trong Kaggle Input thay cho đường dẫn Windows. Để chạy lại toàn bộ 25 URL, đặt cả hai biến trên thành `None`.

## Xác minh và bằng chứng

- 53 tests pass, gồm retry kết nối mới, giữ cookies, SSL, Retry-After/budget, raw của HTTP trung gian, phân biệt lỗi lưu raw với lỗi mạng, challenge HTTP 200, recovery/hash, Selenium retry và báo cáo cuối sau browser fallback.
- Toàn bộ 25 checkpoint gốc không thay đổi; hash raw/text của recovery và cấu trúc ZIP đã được kiểm tra.
- [Requests so với Selenium, CSV](../../runs/domain_probe_review_20261004_125906/recovery/requests_vs_selenium.csv).
- [Các URL còn lỗi](../../runs/domain_probe_review_20261004_125906/recovery/khong_vao_duoc.csv).
- [Log kiểm chứng](../../runs/domain_probe_review_20261004_125906/recovery.log).
- [Metadata kiểm chứng](../../runs/domain_probe_review_20261004_125906/recovery_validation.json).
- [ZIP recovery](../../runs/domain_probe_review_20261004_125906/recovery.zip).

Run kiểm chứng lưu snapshot code thực thi. Notebook cuối có thêm kiểm tra raw challenge khi reuse và phân biệt lỗi lưu raw với lỗi mạng; các guard này được xác minh bằng test riêng, không thay đổi hai request ask.39.net đã phục hồi. Các test báo cáo dùng dữ liệu giả lập, không được tính như lượt kiểm chứng mạng thật.
