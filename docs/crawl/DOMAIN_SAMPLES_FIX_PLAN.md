# Plan fix lỗi domain samples — ưu tiên số URL nguồn lớn nhất

Ngày lập: 04/10/2026, Asia/Saigon. Bảng ưu tiên bên dưới giữ baseline của lượt Kaggle cung cấp.

Cập nhật: đã hoàn thành bước retry/cache robots và đối chiếu với kết quả local đã lưu trong notebook.
Crawler v5 và notebook domain samples đã được sửa; 29 test pass. Chạy thật 15 URL trên local:
120ask tải được 5/5; hai hostname iiyi vẫn trả robots HTTP 521 sau 3 lần thử.
Đã nhận log Kaggle v5: vẫn 47/227 URL tải được, có 5 kết quả lỗi chờ domain lock;
xem [review log mới](KAGGLE_V5_LOG_REVIEW_20261004.md). Chưa có ZIP run v5 để đối chiếu DNS/trace đầy đủ.
Xem [báo cáo đối chiếu và kiểm tra bản sửa](ROBOTS_RETRY_LOCAL_KAGGLE.md) để xác nhận bước tiếp theo.

Nguồn: `C:\Users\HP\Downloads\domain_probe_20261003_205700_459ab8.zip` và `C:\Users\HP\Downloads\crawl-domain-samples (1).log`.

## Baseline và bằng chứng

- 227/227 URL đã xử lý, thuộc 47 hostname; không có pending.
- 47 URL HTTP 2xx: 37 accepted, 5 review, 5 rejected.
- 180 URL không có HTTP 2xx: 175 dừng trước request bài viết; 5 bài Long Châu trả HTTP 403.
- 39 hostname còn lỗi, 8 hostname phục hồi trong các mẫu. Nhóm hostname còn lỗi có tổng 1.479.179 dòng URL nguồn; không có nghĩa mọi dòng đó đều bị lỗi.
- Hash snapshot, sample và các artifact khớp manifest. Thứ tự ưu tiên khớp host_counts của dataset.
- HTTP User-Agent đã là Mozilla/Chrome. Cùng 227 ID/URL, cùng hash snapshot và User-Agent như run local trước.
- Khác biệt trạng thái crawl duy nhất so với local là cả 5 URL www.120ask.com: local extracted, Kaggle robots timeout. Những hostname khác giữ cùng trạng thái crawl.
- Cảnh báo frozen modules/mistune/nbconvert trong log không làm notebook dừng; không phải mục tiêu sửa cho các lỗi mạng/parser này.

| Nhóm | Hostname | URL mẫu |
|---|---:|---:|
| Robots HTML | 23 | 115 |
| Robots 403 | 8 | 35 |
| Robots timeout | 3 | 15 |
| Robots disallow | 2 | 10 |
| Bài viết 403 | 1 | 5 |
| Nội dung redirect trang chủ | 1 | 5 |
| Nội dung rỗng do parser | 1 | 5 |

## Quy tắc ưu tiên

Giữ hostname riêng như các lượt trước. Xếp giảm dần theo số dòng URL hostname trong toàn dataset, không xếp theo số URL mẫu lỗi. Ba hostname đầu chứa 1.241.424 dòng URL nguồn, khoảng 83,9% tổng số dòng thuộc 39 hostname còn lỗi trong bộ mẫu. Đây là mức ưu tiên khảo sát, không phải dự báo số URL chắc chắn phục hồi.

Các sửa chung cho robots/diagnostics là bước nền phục vụ domain ưu tiên đầu. Khi một patch áp dụng được cho nhiều hostname cùng nguyên nhân thì dùng chung patch; bảng dưới vẫn giữ thứ tự từng hostname.

## Thứ tự xử lý đầy đủ

| Ưu tiên | Hostname | Số URL dataset | Lỗi truy cập / nội dung | Lỗi hiện tại | Hướng xử lý |
|---:|---|---:|---|---|---|
| 1 | www.120ask.com | 918,479 | 5 / 0 | robots_timeout: 5 | Fix retry/cache robots và kiểm tra khác biệt mạng Kaggle/local; sau khi tải được, kiểm tra lại vùng câu hỏi/trả lời và boilerplate. |
| 2 | zysjonline.com | 243,347 | 5 / 0 | robots_http_403: 5 | Lưu body/header robots 403; phân biệt chặn truy cập, origin và robots không tồn tại; kiểm tra session trình duyệt công khai/nguồn hợp lệ. |
| 3 | nhathuoclongchau.com.vn | 79,598 | 5 / 0 | page_http_403: 5 | Robots cho phép nhưng bài bị Cloudflare 403; đối chiếu session trình duyệt bình thường và nguồn dữ liệu chính thức, không chỉnh parser cho body challenge. |
| 4 | laodong.vn | 31,282 | 5 / 0 | robots_html_instead_of_txt: 5 | Lưu robots HTML 200, kiểm tra có rule hợp lệ, trang lỗi trả 200 hay challenge; sửa phân loại/policy theo bằng chứng. |
| 5 | baby.39.net | 27,621 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 6 | bingli.iiyi.com | 24,990 | 5 / 0 | robots_timeout: 5 | Dùng retry/timeout/cache đã sửa; đối chiếu timeout Kaggle với robots HTTP 521 local để phân biệt kết nối và upstream. |
| 7 | test.pmphai.com | 15,120 | 5 / 0 | robots_html_instead_of_txt: 5 | Phân tích robots HTML; kiểm tra origin/session/redirect. Chỉ đánh giá JS hoặc login sau khi có bằng chứng, không kết luận từ tên hostname. |
| 8 | fitness.39.net | 12,066 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 9 | woman.39.net | 11,687 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 10 | food.39.net | 11,024 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 11 | fk.39.net | 9,812 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 12 | vov.vn | 9,784 | 5 / 0 | robots_http_403: 5 | Áp dụng chẩn đoán robots 403 chung; lưu body/header, đối chiếu môi trường và nguồn hợp lệ trước khi gán nguyên nhân WAF. |
| 13 | cancer.39.net | 8,415 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 14 | khoahocphothong.vn | 8,143 | 5 / 0 | robots_html_instead_of_txt: 5 | Robots redirect sang chuyên mục Tuổi Trẻ; xác minh website/URL bài đã chuyển, giữ ID/URL nguồn và mapping có bằng chứng. |
| 15 | nk.39.net | 6,650 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 16 | heart.39.net | 5,965 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 17 | article.iiyi.com | 5,641 | 5 / 0 | robots_timeout: 5 | Dùng retry/timeout/cache đã sửa; đối chiếu timeout Kaggle với robots HTTP 521 local để phân biệt kết nối và upstream. |
| 18 | pmc-ecm-healthblog.beta.pharmacity.io | 5,333 | 5 / 0 | robots_http_403: 5 | Lưu body robots 403; kiểm tra host nguồn còn phục vụ nội dung hay đã chuyển, chỉ map sang nguồn chính thức khi có bằng chứng. |
| 19 | man.39.net | 5,320 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 20 | gan.39.net | 5,027 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 21 | tnb.39.net | 4,178 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 22 | wei.39.net | 3,894 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 23 | baidianfeng.familydoctor.com.cn | 3,798 | 5 / 0 | robots_http_403: 5 | Áp dụng chẩn đoán robots 403 chung; lưu body/header, đối chiếu môi trường và nguồn hợp lệ trước khi gán nguyên nhân WAF. |
| 24 | shen.39.net | 3,223 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 25 | ek.39.net | 3,222 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 26 | thaythuocvietnam.vn | 2,927 | 0 / 5 | qc_review: 5 | Cả 5 bài redirect về trang chủ; giữ redirect_home, tìm URL bài thay thế có bằng chứng, không export text trang chủ như bài nguồn. |
| 27 | www.baidu.com | 2,631 | 5 / 0 | robots_disallowed: 5 | Giữ blocked_by_robots theo rule Disallow; đây là giới hạn nguồn, không phải lỗi parser cần đổi User-Agent để xử lý. |
| 28 | gk.39.net | 2,059 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 29 | baolangson.vn | 1,981 | 5 / 0 | robots_disallowed: 5 | Giữ blocked_by_robots theo rule Disallow; đây là giới hạn nguồn, không phải lỗi parser cần đổi User-Agent để xử lý. |
| 30 | gc.39.net | 1,746 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 31 | pf.39.net | 1,538 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 32 | baotayninh.vn | 1,198 | 0 / 5 | qc_rejected: 5 | Sửa fallback DOM theo domain cho HTML đóng `</html>` sớm; 5 raw đã có nội dung bài, kiểm tra offline trước khi crawl lại. |
| 33 | sj.39.net | 942 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 34 | byby.39.net | 439 | 5 / 0 | robots_html_instead_of_txt: 5 | Dùng chung chẩn đoán robots redirect tới /web/404.html với HTTP 200; xác minh robots thiếu/URL đã chuyển và mapping đúng bài nguồn. |
| 35 | www.familydoctor.cn | 44 | 5 / 0 | robots_html_instead_of_txt: 5 | Phân loại robots HTML 200 và kiểm tra URL/domain đã chuyển trước khi sửa parser. |
| 36 | qy.familydoctor.com.cn | 40 | 5 / 0 | robots_http_403: 5 | Áp dụng chẩn đoán robots 403 chung; lưu body/header, đối chiếu môi trường và nguồn hợp lệ trước khi gán nguyên nhân WAF. |
| 37 | v.familydoctor.com.cn | 10 | 5 / 0 | robots_http_403: 5 | Áp dụng chẩn đoán robots 403 chung; lưu body/header, đối chiếu môi trường và nguồn hợp lệ trước khi gán nguyên nhân WAF. |
| 38 | ask.familydoctor.com.cn | 3 | 3 / 0 | robots_http_403: 3 | Áp dụng chẩn đoán robots 403 chung; lưu body/header, đối chiếu môi trường và nguồn hợp lệ trước khi gán nguyên nhân WAF. |
| 39 | yanglao.familydoctor.com.cn | 2 | 2 / 0 | robots_http_403: 2 | Áp dụng chẩn đoán robots 403 chung; lưu body/header, đối chiếu môi trường và nguồn hợp lệ trước khi gán nguyên nhân WAF. |

## Bước nền — bằng chứng đủ để sửa domain số 1

Thay đổi mục tiêu trong `src/vibiomir/corpus/crawler.py` và cập nhật snapshot qua
`scripts/build_domain_probe_notebook.py`. Chưa thực hiện các thay đổi trong plan này.

1. Lưu cho từng attempt robots: origin, URL, method, timestamp, elapsed, status, content-type,
   header chẩn đoán cần thiết, chain redirect, exception class, raw body giới hạn kích thước và hash.
   Không lưu cookie/token vào báo cáo. Hiện robots HTML/403 chỉ có hash/status/error, chưa có body để phân tích.
2. Ghi cache hit, nguồn evidence và thời gian chờ lock. Phân biệt một lần robots lỗi được dùng cho nhiều URL
   với nhiều lần kiểm tra độc lập. Một số record iiyi có elapsed bằng 0 vì dùng lại cache lỗi.
3. Cho connect/read timeout, robots attempts và tổng retry budget thành cấu hình; ghi chúng cùng
   Python/platform/thư viện vào crawl identity để đối chứng có thể lặp lại.
4. Giữ `page_attempted`, HTTP bài viết và HTTP robots riêng. Thêm lỗi có cấu trúc như
   `robots_timeout`, `robots_invalid_html`, `robots_redirected_to_error`, `blocked_by_robots`,
   `page_security_block`, `redirect_home`, `extraction_empty` và lý do cụ thể.

## Ưu tiên 1 — www.120ask.com, 918.479 URL

**Bằng chứng:** 5 mẫu Kaggle đều chưa request bài viết, robots cả HTTP và HTTPS connect timeout 8 giây.
Đúng 5 ID/URL đã tải được ở local với cùng snapshot và User-Agent. Chưa đủ bằng chứng để khẳng định
nguyên nhân riêng là IP, DNS, route hay server phía website.

**Thay đổi:**

- Thêm retry có giới hạn ngay trong `robot_policy()`. Hiện bước này gọi `request_once()` trực tiếp;
  `ATTEMPTS = 3` trong vòng fetch bài viết không áp dụng cho robots. Dòng exception
  “Max retries exceeded” không chứng minh vòng retry 3 lần của crawler đã chạy.
- Retry lỗi timeout/kết nối tạm thời và HTTP tạm thời, có backoff/jitter, Retry-After và tổng budget.
  Không lặp vô hạn 403/disallow/HTML sai định dạng. Chỉ cache kết quả cuối sau khi hết retry;
  lỗi tạm thời cần thời hạn cache phù hợp, không giữ vô thời hạn trong invocation.
- Thử connect 15 giây, read 30 giây, robots attempts 3 với trần tổng chờ khoảng 90 giây/origin;
  trần phải được kiểm tra thực tế, không chỉ khai báo. Giữ WORKERS/DELAY cố định trong thí nghiệm đầu.
- Chạy cùng 5 URL trên local và Kaggle, ghi riêng DNS/kết nối/response/lock wait.
  Đánh giá HTTP/HTTPS theo URL nguồn và redirect thật, không tự đổi URL gốc.
- Khi tải được, xử lý tiếp chất lượng câu hỏi/trả lời: run local trước có 3 mẫu boilerplate review.
  Xác định vùng câu hỏi, câu trả lời và metadata từ raw; kiểm tra không kéo quảng cáo/menu vào nội dung.

**Tiêu chí:** có trace đầy đủ cho các attempt; tách được lỗi môi trường khỏi lỗi website;
URL chưa lấy được robots vẫn báo thất bại đúng; chỉ accepted khi nội dung đạt QC.
Chưa cam kết 5/5 trên Kaggle nếu kết nối tới website bị chặn ngoài khả năng code.

## Ưu tiên 2 — zysjonline.com, 243.347 URL

**Bằng chứng:** robots HTTPS trả 403; cả 5 mẫu dừng trước request bài. ZIP không giữ body robots,
nên chưa xác định được đây là WAF, giới hạn origin hay phản hồi khác.

**Thay đổi:** bổ sung raw robots trước; so sánh request trực tiếp với truy cập trình duyệt công khai,
headers/session và redirect. Nếu website có nguồn/API chính thức phù hợp, xác minh để dùng nguồn đó.
Nếu vẫn bị từ chối, giữ `robots_denied` và bằng chứng. Không chỉ đổi thêm một User-Agent rồi kết luận đã fix.

**Tiêu chí:** nguyên nhân cụ thể có evidence; phương án truy cập hợp lệ hoặc trạng thái giới hạn nguồn rõ ràng.
Bộ xử lý này áp dụng tiếp cho VOV và các hostname robots 403 thấp hơn trong bảng.

## Ưu tiên 3 — nhathuoclongchau.com.vn, 79.598 URL

**Bằng chứng:** robots HTTP 200 cho phép các URL mẫu. Cả 5 bài HTTP 403 với cùng body
`Attention Required! | Cloudflare`; chuỗi User-Agent trình duyệt hiện tại chưa giải quyết được lỗi.

**Thay đổi:** phân loại riêng `page_security_block`, lưu raw và header để so sánh giữa môi trường.
Thử truy cập bằng session trình duyệt thông thường nếu website cho phép; đánh giá cookie/JS từ bằng chứng
thực tế trước khi thêm browser fallback. Fallback chỉ dùng cho trang public và khi robots cho phép;
không dùng body challenge như nội dung bài. Kiểm tra nguồn công khai/chính thức khác nếu chặn vẫn còn.

**Tiêu chí:** lấy được đúng nội dung của các URL nguồn, hoặc báo giới hạn truy cập rõ ràng;
không coi HTTP 200 của trang challenge là thành công nội dung, không hạ QC để tăng accepted.

## Ưu tiên 4 — laodong.vn, 31.282 URL

**Bằng chứng:** `/robots.txt` HTTP 200 và bị detector nhận là HTML; bài chưa được request.
Không có raw body robots nên chưa kết luận robots thiếu, challenge hay detector nhận nhầm.

**Thay đổi:** lấy body/title/content-type/directives; test classifier với robots hợp lệ, HTML lỗi/challenge,
và robots có đoạn/comment bất thường. Nếu có rule hợp lệ thì parser phải xử lý đúng;
nếu website trả trang lỗi 200 thì gắn nhãn cụ thể và xử lý theo policy đã xác minh cho origin đó.
Không tự coi mọi HTML HTTP 200 là robots cho phép.

**Tiêu chí:** phân biệt nguyên nhân và policy rõ trước khi request bài; các URL được tải phải có article content.

## Ưu tiên 5 và các subdomain 39.net dùng chung lỗi

Bắt đầu từ `baby.39.net` (27.621 URL). Tổng 19 hostname cùng nhóm có **124.828 dòng URL nguồn**,
95 mẫu. Evidence robots redirect tới `https://www.39.net/web/404.html` rồi trả 200.
Các URL bài chưa được thử vì crawler dừng ở robots.

**Thay đổi:** lưu từng bước redirect và body trang cuối; nhận diện trang lỗi trả 200 tách khỏi challenge.
Kiểm tra từng origin HTTP/HTTPS theo nguồn. Xác minh robots không tồn tại, origin đã thay đổi hay URL bài
đã di chuyển; chỉ áp dụng policy cho trường hợp đã có bằng chứng, không dùng một robots domain khác
cho tất cả subdomain. Nếu bài chuyển địa chỉ, chỉ lưu mapping từ redirect/canonical/nguồn authoritative
tới đúng bài; giữ source ID/URL và resolved URL riêng, không tự ghép slug hay thay bằng trang chủ.

Patch chung được kiểm tra trên một vài đại diện trước, sau đó toàn bộ 95 mẫu của 19 hostname.
Thứ tự từng hostname vẫn theo bảng, gồm fitness/woman/food/fk/cancer/nk/heart/man/gan/tnb/wei/shen/ek/gk/gc/pf/sj/byby.

**Tiêu chí:** lỗi robots và tình trạng bài được phân biệt; không export HTML 404, trang chủ hoặc trang khác
như bài nguồn; không khẳng định mọi URL thuộc 19 hostname đã phục hồi từ một vài mẫu.

## Các domain kế tiếp

- **bingli.iiyi.com (ưu tiên 6, 24.990 URL), article.iiyi.com (17, 5.641 URL):**
  áp dụng retry/timeout/cache ở bước số 1. Kaggle connect timeout; local trước trả robots HTTP 521.
  Phân biệt route/kết nối và upstream, không mặc định là lỗi parser.
- **test.pmphai.com (7, 15.120 URL):** robots HTML 200; lấy raw để kiểm tra template/session/redirect.
  Chỉ thêm xử lý JS/login khi evidence cho thấy cần, không suy đoán từ tên `test`.
- **vov.vn (12, 9.784 URL) và nhóm familydoctor:** dùng handler robots 403 ở bước số 2.
- **khoahocphothong.vn (14, 8.143 URL):** robots redirect sang
  `https://tuoitre.vn/tto-khoahocphothong.htm`. Xác minh chuyển website và mapping từng bài,
  không coi text chuyên mục Tuổi Trẻ là bài nguồn.
- **pmc-ecm-healthblog.beta.pharmacity.io (18, 5.333 URL):** kiểm tra raw robots 403 và trạng thái origin;
  nếu nguồn chuyển, mapping cần evidence từ nguồn chính thức.
- **thaythuocvietnam.vn (26, 2.927 URL):** 5/5 URL redirect về trang chủ với cùng body.
  Giữ `redirect_home` và ngoài accepted; kiểm tra bài đổi URL/mất bằng mapping có evidence.
- **Baidu (27, 2.631 URL), Lạng Sơn (29, 1.981 URL):** robots có wildcard disallow.
  Giữ `blocked_by_robots`; đây là giới hạn nguồn, không phải bug parser hay lý do giả danh bot khác.
- **baotayninh.vn (32, 1.198 URL):** 5/5 raw có `</html>` đóng sớm trước `<head>`;
  parser hiện trả text rỗng. Thử DOM trên đúng vùng `div.content-article` lấy được lần lượt
  1.627 / 5.122 / 2.846 / 2.228 / 7.711 ký tự tùy bài. Sửa fallback theo domain,
  trích title/metadata và thân bài; kiểm tra đoạn đầu/cuối, không kéo menu/related articles vào text.
  Đây là hướng đã có bằng chứng offline, chưa phải output đã kiểm duyệt.
- **Các domain nhỏ còn lại:** áp dụng handler cùng nhóm, giữ thứ tự bảng và ghi rõ thiếu mẫu.
  `ask.familydoctor.com.cn` chỉ có 3 mẫu; `yanglao.familydoctor.com.cn` chỉ có 2 mẫu.

## Kiểm tra, cập nhật notebook và chạy đối chứng

1. Test robots timeout rồi thành công, hết retry, HTTP tạm thời, Retry-After và tổng budget;
   cache hit/failure TTL và redirect sang origin khác phải có evidence đúng.
2. Test classifier robots plaintext/HTML challenge/trang lỗi trả 200/redirect website;
   trang bị robots disallow vẫn được giữ đúng trạng thái.
3. Test raw Tây Ninh đủ 5 bài; test Thầy Thuốc Việt Nam không accepted khi về trang chủ;
   challenge/403 không bị coi là nội dung. Kiểm tra QC câu hỏi/trả lời 120ask từ raw local khi kết nối phục hồi.
4. Regenerate **đúng `notebooks/crawl_domain_samples.ipynb`**, giữ bộ 227 ID/URL.
   User-Agent trình duyệt là cấu hình đã được chọn, không quay lại header khai báo crawler.
5. Tạo run mới khi thay đổi code/config. Không sửa hash để ép resume;
   chạy lại run hiện tại sẽ bỏ qua cả checkpoint lỗi, không chứng minh patch đã hoạt động.
6. Chạy đối chứng trước trên 5 URL www.120ask.com, rồi các domain theo thứ tự bảng;
   sau khi patch ổn, chạy lại đầy đủ 227 URL trên local và Kaggle.
7. Xuất before/after theo ID/URL: HTTP robots/bài, attempts, cache hit, failure stage,
   access, content/QC và elapsed. Bảng domain còn lỗi luôn xếp theo số URL nguồn giảm dần.
   Giữ 8 hostname đã phục hồi trong bộ đối chứng để phát hiện regression.

Không đặt mục tiêu tăng accepted bằng cách bỏ QC hoặc coi trang chủ/challenge là bài.
Kết quả có thể gồm domain phục hồi, lỗi môi trường, URL đã chuyển/mất và nguồn không cho phép truy cập.
Plan ưu tiên sửa vấn đề có bằng chứng, chưa cam kết crawl được toàn bộ dataset.
