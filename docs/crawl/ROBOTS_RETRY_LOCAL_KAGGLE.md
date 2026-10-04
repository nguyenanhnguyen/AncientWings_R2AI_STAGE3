# Retry/cache robots — đối chiếu Kaggle và local

Cập nhật từ log Kaggle ngày 04/10/2026: v5 đã chạy đủ 227 mẫu, vẫn 47 URL HTTP 2xx;
có 5 kết quả lỗi hết ngân sách chờ domain lock. Chưa có ZIP để xác minh DNS và từng lần retry.
Xem [review log v5 và bước debug tiếp theo](KAGGLE_V5_LOG_REVIEW_20261004.md).
Phần bên dưới ghi lại kết quả và kiểm tra local trước khi nhận log mới.

Ngày: 04/10/2026 (Asia/Saigon). Đã sửa crawler và notebook domain samples; đã chạy kiểm tra thật trên local. Chưa chạy bản sửa trong Kaggle.

## Nguồn đối chiếu

- **Local của bạn:** kết quả được lưu trong `notebooks/crawl_domain_samples.ipynb`, thư mục `notebooks/runs/domain_probe_20261003_205546_4622cd`.
- **Kaggle:** ZIP `C:\Users\HP\Downloads\domain_probe_20261003_205700_459ab8.zip` và log `crawl-domain-samples (1).log`.
- Notebook local đã chạy được giữ nguyên tại [bản sao lưu](../../runs/robots_retry_fix_20261004/baseline_local_notebook.ipynb); thư mục kết quả local cũ được giữ nguyên.
- [Bảng đối chiếu 227 URL](../../runs/robots_retry_fix_20261004/local_vs_kaggle.csv) và [bằng chứng JSON](../../runs/robots_retry_fix_20261004/comparison_evidence.json).

Đã xác nhận cùng 227 ID/URL, cùng hash sample, cùng snapshot v4 và cùng browser User-Agent. Hash sample/snapshot và toàn bộ artifact trong ZIP đều hợp lệ.

| Kết quả trên cùng 227 URL | Local của bạn | Kaggle |
|---|---:|---:|
| HTTP bài viết 2xx | 52 | 47 |
| Không có HTTP bài viết 2xx | 175 | 180 |
| Dừng trước request bài viết | 170 | 175 |
| QC accepted / review / rejected | 39 / 8 / 5 | 37 / 5 / 5 |

## Kết luận từ bằng chứng mạng

- Chênh lệch truy cập nằm đúng ở **5 URL `www.120ask.com`**, hostname có **918.479 dòng URL dataset**, ưu tiên số 1. Local tải cả 5; Kaggle timeout khi kết nối robots.txt trên cả origin HTTP và HTTPS (connect timeout cũ 8 giây). Kaggle chưa request bài viết.
- `bingli.iiyi.com` (**24.990 dòng**) và `article.iiyi.com` (**5.641 dòng**) đều chưa tải được bài trên cả hai môi trường. Kaggle lỗi kết nối/timeout; local đã nhận HTTP 521 từ robots. Trạng thái crawl cùng `robots_unknown`, nhưng nguyên nhân mạng khác nhau.
- Đây là bằng chứng về hành vi kết nối khác nhau giữa hai môi trường ở những thời điểm chạy. Chưa đủ dữ liệu để quy lỗi chắc chắn cho DNS, firewall, IP Kaggle hay chặn địa lý. V4 chưa lưu DNS/địa chỉ đích trên Kaggle.
- Tăng timeout và retry có thể xử lý lỗi tạm thời. Nếu đường mạng Kaggle không tới được origin, retry vẫn có thể thất bại; local tải được không chứng minh Kaggle đã được sửa.

| Package | Local cũ | Kaggle cũ |
|---|---|---|
| pyarrow | 25.0.1 | 23.0.1 |
| pymupdf | 1.28.2 | 1.28.2 |
| requests | 2.34.2 | 2.34.2 |
| trafilatura | 2.3.0 | 2.3.0 |

Khác biệt package, nếu có, chưa chứng minh là nguyên nhân timeout: lỗi xảy ra trước bước parse/extract nội dung.

## Lỗi code và phần đã sửa

V4 chỉ tải robots một lần mỗi origin. `ATTEMPTS=3` chỉ áp dụng cho bài viết; lỗi robots được cache suốt invocation. Vì nhiều worker dùng chung cache, một lần timeout có thể khiến cả 5 URL của hostname dừng mà không thử kết nối lại.

- **Retry riêng cho robots:** tối đa 3 lần cho lỗi Requests/kết nối/DNS và HTTP 408/429/5xx; backoff tăng dần có jitter. Mỗi lần retry bắt đầu từ robots URL gốc và kiểm tra an toàn từng redirect.
- **Timeout riêng:** connect 15 giây, read 30 giây; ngân sách retry 90 giây, tính cả chờ domain lock, cooldown và backoff trong quá trình tải. Chờ robots lock được ghi riêng. Đây không phải hard deadline cho DNS/OS socket.
- **Cache lỗi tạm thời có TTL:** mặc định 30 giây sau khi fetch kết thúc; dài hơn nếu Retry-After yêu cầu. Sau TTL, URL tiếp theo có thể fetch lại. Cache dùng riêng từng origin (scheme + host); worker cùng origin chia sẻ một fetch.
- HTTP 401/403, chứng chỉ SSL lỗi, robots HTML và robots disallow vẫn được phân loại riêng; retry không biến các trường hợp này thành quyền tải bài. Robots HTTP 404/410 giữ policy hiện có.
- **Giữ bằng chứng mỗi lần thử:** URL, số attempt, redirect hop, HTTP/header chọn lọc, exception class, thời gian và raw gzip. Tên raw riêng theo origin/fetch/attempt tránh ghi đè giữa worker.
- **Báo cáo CSV/HTML:** thêm `robots_attempt_count`, `robots_cache_hit`, `robots_fetch_id`, `robots_error_kind`, thời gian fetch và chờ robots lock. Cache hit dùng lại trace của fetch trước; không phải một request mới.
- **So sánh môi trường:** notebook xuất `network_check.json` với DNS ba hostname, Python/platform và cờ có biến proxy; `crawl_config.json` ghi cấu hình retry/timeout và package. User-Agent vẫn là browser UA của notebook.

Các tham số ở ô cấu hình: `ROBOTS_ATTEMPTS`, `ROBOTS_CONNECT_TIMEOUT`, `ROBOTS_READ_TIMEOUT`, `ROBOTS_RETRY_BUDGET`, `ROBOTS_FAILURE_TTL`, `NETWORK_CHECK_DOMAINS`.

## Chạy thật bản sửa trên local

[Bảng kết quả 15 URL](../../runs/robots_retry_fix_20261004/live_focused/ket_qua.html) · [CSV](../../runs/robots_retry_fix_20261004/live_focused/ket_qua.csv) · [ZIP raw và trace](../../runs/robots_retry_fix_20261004/live_focused.zip).

Giữ đúng 5 ID/URL của mỗi hostname, cùng browser UA; chạy snapshot v5 của notebook. Đây là lượt tập trung 15 URL, không phải chạy lại toàn bộ 227 URL.

| Ưu tiên theo số dòng dataset | Hostname | Local cũ | Kaggle cũ | Local bản sửa |
|---:|---|---|---|---|
| 918.479 | www.120ask.com | 5/5 tải được | 0/5; robots timeout | 5/5 tải được; robots 200 ngay lần 1 trên HTTP/HTTPS |
| 24.990 | bingli.iiyi.com | 0/5; robots 521 | 0/5; robots timeout | 0/5; robots 521 sau đủ 3 lần thử |
| 5.641 | article.iiyi.com | 0/5; robots 521 | 0/5; robots timeout | 0/5; robots 521 sau đủ 3 lần thử |

120ask giữ QC như local cũ: 2 accepted, 3 review do `boilerplate_suspect`. Retry/cache không sửa phần trích xuất Q&A. Hai hostname iiyi chưa request bài viết; nguyên nhân cuối được báo đúng là robots HTTP 521.

DNS local tại lần kiểm tra mới phân giải cả ba hostname về `219.239.89.30`, `219.239.89.31`, `219.239.89.32`; không có biến proxy HTTP/HTTPS/ALL_PROXY/NO_PROXY được đặt. Đây là giá trị quan sát tại lượt local này, chưa có DNS Kaggle tương ứng để kết luận mapping đúng/sai.

## Kiểm tra và cách xác nhận trên Kaggle

- `python -m unittest discover -s tests -v`: **29 test pass**, gồm 8 test mới về timeout phục hồi, TTL/refetch, lỗi không retry, HTTP tạm thời, Retry-After, ngân sách/cooldown, worker dùng chung cache và robots disallow.
- Notebook chạy được đủ 227 mẫu với HTTP giả lập, xuất CSV/HTML/ZIP, giữ thứ tự ưu tiên theo số dòng dataset. Các kết quả giả lập chỉ dùng kiểm tra cấu trúc, không phải bằng chứng truy cập website.
- Kiểm tra thật 15 URL ở bảng trên; hash của raw robots từng lần thử đều khớp trace.

1. Dùng [notebook cập nhật](../../notebooks/crawl_domain_samples.ipynb), bật Internet trên Kaggle, giữ `RESUME_RUN_DIR = None` rồi Run All. Không resume run v4, vì checkpoint lỗi cũ sẽ bị bỏ qua và snapshot/config đã đổi.
2. Đối chiếu 5 mẫu 120ask và 10 mẫu iiyi trong `ket_qua.csv`; xem `network_check.json`, `crawl_config.json`, `records/*.json` và `robots/*.json`.
3. Với lỗi timeout, xem số lần thử thực tế, exception class và từng URL/origin. Nếu vẫn timeout sau retry, tiếp tục kiểm tra đường mạng Kaggle. Nếu nhận 521/403, lỗi đã chuyển sang HTTP server; không ghi là lỗi timeout.
4. Cache hit có cùng `robots_fetch_id` chỉ là tái sử dụng kết quả. TTL chỉ cho phép fetch lại khi có lần gọi robots tiếp theo sau TTL; không tự sửa checkpoint đã ghi, cũng không tự chạy lại các URL đã hoàn tất.

Các nhóm robots HTML, robots 403, page Cloudflare 403 và parser/QC vẫn nằm trong [plan fix theo ưu tiên](DOMAIN_SAMPLES_FIX_PLAN.md). Lượt này xử lý retry/cache và bằng chứng mạng trước.

Tài liệu kỹ thuật: [Requests — Timeouts](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts) giải thích timeout đọc/kết nối không phải giới hạn tổng thời gian tải; [RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html) phân biệt robots không truy cập được với policy cho phép tải.
