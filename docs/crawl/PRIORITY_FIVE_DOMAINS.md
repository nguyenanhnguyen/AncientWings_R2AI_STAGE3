# 5 hostname ưu tiên — Requests và Selenium

Ngày 04/10/2026, Asia/Saigon. Đã kiểm tra thật trên local; bản notebook tập trung mới chưa chạy trên Kaggle.

5 hostname chứa **2.910.092 / 4.394.718 dòng URL = 66,22% dataset**. Mỗi hostname giữ 1 URL cũ, thêm 4 URL khác nhau từ Parquet; tổng 25 URL, giữ ID/URL nguồn.

[Notebook cập nhật](../../notebooks/crawl_domain_samples.ipynb) · [Bảng kết quả từng URL](../../runs/priority_five_20261004/report/ket_qua.html) · [CSV Requests/Selenium](../../runs/priority_five_20261004/report/requests_vs_selenium.csv) · [ZIP](../../runs/priority_five_20261004/report.zip).

## Kết quả thực tế

Tải trực tiếp các URL mẫu công khai, HTTP User-Agent Mozilla/Chrome và header Accept/Accept-Language theo trình duyệt. Chế độ probe này kiểm tra HTTP của trang, không dùng robots để chặn request mẫu. Output HTTP và QC được tách riêng.

| Ưu tiên | Hostname | URL dataset | Tỷ trọng | Requests HTTP 2xx | QC Requests | Selenium |
|---:|---|---:|---:|---:|---|---|
| 1 | www.cnkang.com | 963,438 | 21.92% | 5/5 | 5 accepted | Mẫu đầu HTTP 200; nội dung 1.774 ký tự, giống Requests |
| 2 | www.120ask.com | 918,479 | 20.90% | 5/5 | 2 accepted, 3 review | Mẫu đầu timeout điều hướng; DOM trống, không có HTTP cuối |
| 3 | www.familydoctor.com.cn | 447,453 | 10.18% | 5/5 | 5 accepted | Mẫu đầu HTTP 200; nội dung 1.805 ký tự, giống Requests |
| 4 | ask.39.net | 337,375 | 7.68% | 5/5 | 5 accepted | Mẫu đầu timeout điều hướng; DOM trống, không có HTTP cuối |
| 5 | zysjonline.com | 243,347 | 5.54% | 0/5 | Chưa lấy được bài | Cả 5 mẫu vẫn HTTP 403 / Cloudflare sau khi chờ JS 20 giây |

**Requests: 20/25 tải được; 17 accepted, 3 review.** Cả 4 hostname đầu tải được 5/5 mẫu sau khi thử lại theo lịch mỗi domain một request. Không suy từ 20 mẫu này rằng toàn bộ 2.666.745 URL của 4 hostname đã được xác minh crawl được.

**Selenium không phục hồi thêm mẫu nào trong lượt kiểm tra này.** Đối chiếu 1 mẫu đầu của 4 hostname và cả 5 URL zysjonline. cnkang/familydoctor đã có đủ nội dung trong HTML Requests. Hai mẫu 120ask/ask.39 timeout trong Chrome, trong khi Requests tải được. Chúng không bị ghi nhầm là rendered thành công khi chỉ có about:blank.

Với zysjonline, đã thử Chrome 154 với UA Chrome 130 và sau đó UA Chrome 154 khớp bản browser, chờ 20 giây tới khi trang xác minh kết thúc. Cả 5 vẫn HTTP 403, title `Just a moment...`, nội dung `Performing security verification`. Đây là security challenge, không phải thiếu parser nội dung. [Ảnh chụp một mẫu](../../runs/priority_five_20261004/report/browser_screenshots/4182981.png).

## Chọn Requests hay Selenium

- **cnkang:** Requests trước; nội dung đã có trong HTML. Cần khảo sát thêm URL/template trước khi crawl số lượng lớn.
- **120ask:** Requests trên môi trường kết nối được. Việc cần sửa kế tiếp là parser Q&A/boilerplate: 3/5 mẫu bị `boilerplate_suspect`, cùng QC của local cũ. Selenium chưa cải thiện mẫu thử.
- **familydoctor.com.cn:** Requests trước; mẫu thử đều accepted, không có bằng chứng cần JavaScript để lấy nội dung chính.
- **ask.39.net:** Requests trước; cả 5 mẫu được accepted sau khi xử lý tuần tự. Kết quả này áp dụng riêng hostname `ask.39.net`, không suy sang các subdomain `.39.net` đang lỗi robots HTML.
- **zysjonline:** có lý do thử browser để chạy JS, nhưng Selenium thông thường đã không phục hồi 5 mẫu. Bước tiếp theo là kiểm tra quyền truy cập/session bình thường và nguồn bài/PDF công khai tương ứng; chưa nên đưa cả 243.347 URL vào hàng đợi Selenium chỉ dựa trên lỗi 403.

[Selenium WebDriver](https://www.selenium.dev/documentation/webdriver/) điều khiển trình duyệt thật. Dựa trên kết quả local ở đây, chỉ nên dùng nó cho URL cần đối chiếu trình duyệt/render JavaScript; không chuyển cả dataset sang Selenium.

## ZIP Kaggle v5 đã xác minh được gì

- Artifact hashes trong ZIP `domain_probe_20261004_100557_3b2d54.zip` đều khớp manifest.
- Kaggle và local phân giải `www.120ask.com` về cùng 3 IP: `219.239.89.30`, `.31`, `.32`; không có proxy environment flags trong hai lần kiểm tra. Khác DNS đích không giải thích được chênh lệch này; chưa đủ dữ liệu để kết luận firewall/IP/địa lý.
- Trace robots 120ask cho thấy các lần request connect timeout khoảng 45 giây, fetch robots thường chỉ thực hiện 2 attempt trong ngân sách 90 giây, không phải chắc chắn 3. Suy luận: 3 IP × timeout connect 15 giây giải thích được phần lớn thời gian. [Requests — Timeouts](https://requests.readthedocs.io/en/latest/user/advanced/#timeouts) xác nhận timeout connect áp dụng cho từng IP được thử, không phải hard wall-clock deadline.
- Chờ domain lock trong v5 vẫn tiêu hao ngân sách. Probe nhóm ưu tiên mới xử lý từng URL tuần tự theo registered domain và chạy song song giữa các domain; tránh việc các mẫu cùng domain tranh lock ngay từ đầu.
- Chế độ tải trang trực tiếp mới cần chạy trên Kaggle để biết bài 120ask có kết nối được ở đó hay không. Local HTTP 200 chưa chứng minh đường mạng Kaggle đã được sửa.

## Notebook và output

Giữ `RESUME_RUN_DIR = None`, bật Internet trên Kaggle rồi Run All. Mặc định notebook nhúng đúng 25 mẫu ưu tiên; `BROWSER_TEST_MODE = "failed_only"` chỉ thử browser cho mẫu Requests lỗi. Đặt `off` để bỏ Selenium; dùng `first_each_domain_and_failures` để đối chiếu cả mẫu đầu mỗi hostname.

Selenium Manager tìm/tải Chrome/driver. Nếu thiếu browser/dependencies hoặc download bị lỗi, kết quả Requests vẫn được xuất và lỗi setup nằm trong `browser_setup_error.json`. [Tài liệu Selenium Manager](https://www.selenium.dev/documentation/selenium_manager/).

- `ket_qua.csv` / `requests_vs_selenium.csv`: HTTP, lỗi gốc, QC, số ký tự và kết quả browser riêng.
- `records/`, `browser_records/`, `raw/`, `browser_screenshots/`: bằng chứng của từng ID.
- `network_check.json`, `priority_probe_config.json`, `browser_environment*.json`: môi trường, DNS và UA/config.
- `WEB_ERRORS.md` và bảng ưu tiên giữ thứ tự theo số dòng URL dataset. Hostname chỉ có QC review vẫn nằm trong danh sách cần sửa nội dung.

Bộ 227 mẫu lỗi cũ vẫn nằm trong `data/domain_probe_followup_samples.json`; có thể tạo lại notebook đó bằng `python scripts/build_domain_probe_notebook.py --failed-followup`.

## Kiểm tra và provenance

- **40 unit tests pass**, gồm 6 test mới cho probe trực tiếp, giữ QC/hash, HTTP 403 không retry, lịch theo domain, HTTP main-frame của browser, DOM trống và chờ security challenge.
- Notebook chạy đủ 25 mẫu với HTTP giả lập; xác minh ID/URL thật trong Parquet, CSV/HTML/ZIP, hash snapshot và thứ tự ưu tiên. Kết quả giả lập không dùng để kết luận khả năng truy cập.
- Kết quả thật được giữ riêng trong `runs/priority_five_20261004/`. Một lỗi gán QC ở probe ban đầu đã được sửa; 15 response HTTP 200 đã lưu được trích xuất lại offline, 5 mẫu timeout được thử lại và đều HTTP 200. Các request HTTP 403 giữ nguyên bằng chứng cũ; Selenium được chạy thật riêng, có lần chờ bổ sung 20 giây.
- Raw hash và text hash của các record hợp lệ; `processing_provenance.json` ghi rõ nguồn gốc. Notebook local cũ và toàn bộ các run Kaggle trước được giữ nguyên.
