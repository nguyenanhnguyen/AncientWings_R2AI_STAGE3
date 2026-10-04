# Đọc log Kaggle v5 — 04/10/2026

Run: `domain_probe_20261004_100557_3b2d54`. Nguồn: `C:\Users\HP\Downloads\crawl-domain-samples (2).log`.

Kaggle đã chạy đủ 227 URL bằng crawler v5, không có pending hay traceback làm dừng notebook. **HTTP bài viết 2xx vẫn là 47/227**, chưa cải thiện so với Kaggle v4. Local trước đó tải được 52/227.

## So sánh với lượt Kaggle trước

| Chỉ số | Kaggle v4 | Kaggle v5 |
|---|---:|---:|
| URL tải được | 47 | 47 |
| URL không có HTTP bài viết 2xx | 180 | 180 |
| Dừng trước request bài viết | 175 | 175 |
| Hostname còn lỗi kể cả QC | 39 | 39 |
| QC accepted / review / rejected | 37 / 5 / 5 | 37 / 5 / 5 |

Mốc hoàn thành crawl trong log: v4 `151.6s`, v5 `270.8s`, tính từ đầu job và có cả thời gian khởi tạo. Không dùng hai mốc này làm benchmark mạng; chúng cho thấy lượt mới lâu hơn mà chưa tăng số URL tải được.

## Các điểm cần xử lý trước

1. **120ask, 918.479 dòng URL:** 4 mẫu báo connect timeout, 1 mẫu báo hết ngân sách chờ domain lock. Timeout connect 15 giây đã được áp dụng trên HTTP/HTTPS, nhưng Kaggle vẫn chưa nhận HTTP từ robots. Cùng các mẫu này local tải được 5/5. Cần đối chiếu DNS/IP đích và đường kết nối trước khi tăng timeout tiếp.
2. **Hết ngân sách chờ domain lock:** 5 kết quả (`www.120ask.com`: 1; `article.iiyi.com`: 4). Trong code, robots cache theo origin nhưng request lock theo registered domain; hai scheme 120ask và hai subdomain iiyi chia sẻ lock. Ngân sách robots bắt đầu trước khi lấy request lock, nên có thể bị tiêu hao vì chờ request khác. Log chứng minh có chờ lock hết hạn, nhưng chưa chứng minh các kết quả đó chưa từng thử mạng hoặc các nguyên nhân cụ thể làm lock bị giữ lâu.
3. **iiyi:** bingli có 5 mẫu connect timeout; article có 1 mẫu connect timeout và 4 mẫu lỗi chờ lock. Local nhận robots HTTP 521. Cần tách lỗi kết nối thật khỏi lỗi hàng đợi rồi mới đánh giá retry phục hồi.
4. **Baidu thay đổi nguyên nhân:** v4 cả 5 mẫu `robots_disallowed`; v5 cả 5 mẫu read timeout. Đây là thay đổi khả năng đọc robots, không chứng minh robots đã cho phép crawl.

Các lỗi HTTP 403/robots HTML còn nguyên theo số mẫu. Nhóm 120ask vẫn đứng đầu về số URL nguồn; không suy từ vài mẫu ra toàn bộ domain đều lỗi.

## Hostname lỗi truy cập theo số URL dataset

| Hostname | Số dòng URL | Mẫu lỗi truy cập | Lỗi trong log |
|---|---:|---:|---|
| www.120ask.com | 918,479 | 5 | robots_timeout: 4; robots_domain_lock_budget: 1 |
| zysjonline.com | 243,347 | 5 | robots_http_403: 5 |
| nhathuoclongchau.com.vn | 79,598 | 5 | page_http_403: 5 |
| laodong.vn | 31,282 | 5 | robots_html_instead_of_txt: 5 |
| baby.39.net | 27,621 | 5 | robots_html_instead_of_txt: 5 |
| bingli.iiyi.com | 24,990 | 5 | robots_timeout: 5 |
| test.pmphai.com | 15,120 | 5 | robots_html_instead_of_txt: 5 |
| fitness.39.net | 12,066 | 5 | robots_html_instead_of_txt: 5 |
| woman.39.net | 11,687 | 5 | robots_html_instead_of_txt: 5 |
| food.39.net | 11,024 | 5 | robots_html_instead_of_txt: 5 |
| fk.39.net | 9,812 | 5 | robots_html_instead_of_txt: 5 |
| vov.vn | 9,784 | 5 | robots_http_403: 5 |
| cancer.39.net | 8,415 | 5 | robots_html_instead_of_txt: 5 |
| khoahocphothong.vn | 8,143 | 5 | robots_html_instead_of_txt: 5 |
| nk.39.net | 6,650 | 5 | robots_html_instead_of_txt: 5 |
| heart.39.net | 5,965 | 5 | robots_html_instead_of_txt: 5 |
| article.iiyi.com | 5,641 | 5 | robots_domain_lock_budget: 4; robots_timeout: 1 |
| pmc-ecm-healthblog.beta.pharmacity.io | 5,333 | 5 | robots_http_403: 5 |
| man.39.net | 5,320 | 5 | robots_html_instead_of_txt: 5 |
| gan.39.net | 5,027 | 5 | robots_html_instead_of_txt: 5 |
| tnb.39.net | 4,178 | 5 | robots_html_instead_of_txt: 5 |
| wei.39.net | 3,894 | 5 | robots_html_instead_of_txt: 5 |
| baidianfeng.familydoctor.com.cn | 3,798 | 5 | robots_http_403: 5 |
| shen.39.net | 3,223 | 5 | robots_html_instead_of_txt: 5 |
| ek.39.net | 3,222 | 5 | robots_html_instead_of_txt: 5 |
| www.baidu.com | 2,631 | 5 | robots_timeout: 5 |
| gk.39.net | 2,059 | 5 | robots_html_instead_of_txt: 5 |
| baolangson.vn | 1,981 | 5 | robots_disallowed: 5 |
| gc.39.net | 1,746 | 5 | robots_html_instead_of_txt: 5 |
| pf.39.net | 1,538 | 5 | robots_html_instead_of_txt: 5 |
| sj.39.net | 942 | 5 | robots_html_instead_of_txt: 5 |
| byby.39.net | 439 | 5 | robots_html_instead_of_txt: 5 |
| www.familydoctor.cn | 44 | 5 | robots_html_instead_of_txt: 5 |
| qy.familydoctor.com.cn | 40 | 5 | robots_http_403: 5 |
| v.familydoctor.com.cn | 10 | 5 | robots_http_403: 5 |
| ask.familydoctor.com.cn | 3 | 3 | robots_http_403: 3 |
| yanglao.familydoctor.com.cn | 2 | 2 | robots_http_403: 2 |

Bảng này có 37 hostname lỗi truy cập. Hai hostname chỉ lỗi QC (`baotayninh.vn`, `thaythuocvietnam.vn`) được tính trong tổng 39 hostname còn lỗi của summary, không phải lỗi kết nối.

## Điều log chưa xác minh được

- Log chỉ in đường dẫn `network_check.json`, không chứa kết quả DNS, proxy flags hoặc platform trong file đó.
- Không có `robots_attempt_count`, `robots_cache_hit`, `robots_fetch_id`, các mốc chờ lock và raw của từng lần thử. Cụm `Max retries exceeded` trong exception không phải bằng chứng đã chạy đủ 3 lần retry của crawler.
- Không có ID/URL của từng mẫu timeout, nên không gán lỗi log cho ID cụ thể hay khẳng định toàn bộ kết quả 227 mẫu giống hệt v4 chỉ dựa trên tổng số.
- Chưa có hash snapshot/config của run mới để kiểm tra provenance đầy đủ; dòng console cho biết v5 và timeout thực tế cho biết cấu hình 15 giây đang có tác dụng.

## Bước debug tiếp theo

Cần ZIP `domain_probe_20261004_100557_3b2d54.zip` đã được tạo thành công. Trong đó:

1. Đối chiếu `network_check.json` Kaggle với file local; so sánh tập IP đích, có lỗi DNS hay không và proxy flags. DNS phân giải được chưa đủ chứng minh kết nối TCP/TLS thành công.
2. Đọc `robots/*.json` cùng `records/*.json` để đếm request thật theo fetch ID, phân biệt cache hit, thời gian request và chờ lock. Tập trung 120ask trước, sau đó iiyi.
3. Tái hiện tranh chấp HTTP/HTTPS và hai subdomain trong test; điều chỉnh lịch chờ/ngân sách lock dựa trên trace. Phân loại lỗi chờ lock riêng trong CSV/log, giữ giới hạn tổng để tránh notebook treo.
4. Nếu có request thật nhưng mọi lần đều connect timeout, kiểm tra cùng origin trên Kaggle/local ở cùng thời điểm. Không coi retry hoặc tăng timeout là bằng chứng đường mạng đã được sửa.

Các cảnh báo frozen modules, mistune và nbconvert xuất hiện quanh khởi tạo/export. Job đã xuất notebook và HTML thành công; chúng không giải thích các lỗi connect/read timeout trong lượt crawl.

Lượt kiểm tra này chỉ phân tích log và cập nhật báo cáo; chưa thay đổi crawler hay notebook. Dữ liệu/trace chưa có không được suy thành kết quả kiểm thử.
