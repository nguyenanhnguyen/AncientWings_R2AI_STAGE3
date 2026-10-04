# Các website còn lỗi sau lượt test bổ sung

Thời điểm UTC: 2026-10-03T20:54:33.938396+00:00. Run: `domain_probe_20261003_204939_8ede7e`.

Đã chạy 227/227 URL thuộc 47 hostname. HTTP 2xx: 52; không có HTTP 2xx: 175; chưa chạy: 0.

170 URL đã xử lý nhưng chưa request bài viết vì dừng trước bước tải bài. Các trường hợp này được phân biệt với bài viết thực sự trả HTTP lỗi.

HTTP User-Agent: `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36`.

Giữ 1 mẫu cũ và lấy tối đa 4 URL mới mỗi hostname từ dataset, không trùng URL. Gồm lỗi truy cập và lỗi nội dung/QC. Số URL dataset là số dòng của hostname, chưa loại URL trùng.

Ưu tiên theo số URL dataset giảm dần; không suy ra toàn bộ URL của domain đều bị lỗi. Dừng ở robots là chưa request bài viết, không đồng nghĩa website không mở được trong trình duyệt.

| Ưu tiên | Hostname | Số URL dataset | Mẫu đã chạy | Lỗi truy cập | Lỗi nội dung | Loại lỗi |
|---:|---|---:|---:|---:|---:|---|
| 1 | www.120ask.com | 918,479 | 5/5 | 0 | 3 | qc_review: 3 |
| 2 | zysjonline.com | 243,347 | 5/5 | 5 | 0 | robots_http_403: 5 |
| 3 | nhathuoclongchau.com.vn | 79,598 | 5/5 | 5 | 0 | page_http_403: 5 |
| 4 | laodong.vn | 31,282 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 5 | baby.39.net | 27,621 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 6 | bingli.iiyi.com | 24,990 | 5/5 | 5 | 0 | robots_http_521: 5 |
| 7 | test.pmphai.com | 15,120 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 8 | fitness.39.net | 12,066 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 9 | woman.39.net | 11,687 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 10 | food.39.net | 11,024 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 11 | fk.39.net | 9,812 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 12 | vov.vn | 9,784 | 5/5 | 5 | 0 | robots_http_403: 5 |
| 13 | cancer.39.net | 8,415 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 14 | khoahocphothong.vn | 8,143 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 15 | nk.39.net | 6,650 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 16 | heart.39.net | 5,965 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 17 | article.iiyi.com | 5,641 | 5/5 | 5 | 0 | robots_http_521: 5 |
| 18 | pmc-ecm-healthblog.beta.pharmacity.io | 5,333 | 5/5 | 5 | 0 | robots_http_403: 5 |
| 19 | man.39.net | 5,320 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 20 | gan.39.net | 5,027 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 21 | tnb.39.net | 4,178 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 22 | wei.39.net | 3,894 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 23 | baidianfeng.familydoctor.com.cn | 3,798 | 5/5 | 5 | 0 | robots_http_403: 5 |
| 24 | shen.39.net | 3,223 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 25 | ek.39.net | 3,222 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 26 | thaythuocvietnam.vn | 2,927 | 5/5 | 0 | 5 | qc_review: 5 |
| 27 | www.baidu.com | 2,631 | 5/5 | 5 | 0 | robots_disallowed: 5 |
| 28 | gk.39.net | 2,059 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 29 | baolangson.vn | 1,981 | 5/5 | 5 | 0 | robots_disallowed: 5 |
| 30 | gc.39.net | 1,746 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 31 | pf.39.net | 1,538 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 32 | baotayninh.vn | 1,198 | 5/5 | 0 | 5 | qc_rejected: 5 |
| 33 | sj.39.net | 942 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 34 | byby.39.net | 439 | 5/5 | 5 | 0 | robots_html_instead_of_txt: 5 |
| 35 | www.familydoctor.cn | 44 | 5/5 | 5 | 0 | robots_timeout: 5 |
| 36 | qy.familydoctor.com.cn | 40 | 5/5 | 5 | 0 | robots_http_403: 5 |
| 37 | v.familydoctor.com.cn | 10 | 5/5 | 5 | 0 | robots_http_403: 5 |
| 38 | ask.familydoctor.com.cn | 3 | 3/3 | 3 | 0 | robots_http_403: 3 |
| 39 | yanglao.familydoctor.com.cn | 2 | 2/2 | 2 | 0 | robots_http_403: 2 |

## Domain đã phục hồi trong các mẫu

- baohaiphong.vn: 5/5 URL tải được và đạt QC.
- baonghean.vn: 5/5 URL tải được và đạt QC.
- baodanang.vn: 5/5 URL tải được và đạt QC.
- youmed.vn: 5/5 URL tải được và đạt QC.
- suckhoeviet.org.vn: 5/5 URL tải được và đạt QC.
- vnexpress.net: 5/5 URL tải được và đạt QC.
- hanoimoi.vn: 5/5 URL tải được và đạt QC.
- mega.vietnamplus.vn: 2/2 URL tải được và đạt QC.

## Domain thiếu URL bổ sung

- ask.familydoctor.com.cn: lấy được 2/4 URL mới; dataset có 3 dòng.
- mega.vietnamplus.vn: lấy được 1/4 URL mới; dataset có 2 dòng.
- yanglao.familydoctor.com.cn: lấy được 1/4 URL mới; dataset có 2 dòng.

## Chi tiết lỗi theo domain

### 1. www.120ask.com

918,479 URL nguồn; 0 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_timeout`.

- ID 2843944 (original): [URL](<https://www.120ask.com/question/38159402.htm>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: boilerplate_suspect Lỗi gốc: `boilerplate_suspect`.
- ID 1268650 (additional): [URL](<http://www.120ask.com/question/4256835.htm>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: boilerplate_suspect Lỗi gốc: `boilerplate_suspect`.
- ID 2635226 (additional): [URL](<https://www.120ask.com/question/1130106.htm>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: boilerplate_suspect Lỗi gốc: `boilerplate_suspect`.

### 2. zysjonline.com

243,347 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 4182981 (original): [URL](<https://zysjonline.com/articles/misc/16204/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 4178992 (additional): [URL](<https://zysjonline.com/articles/misc/11808/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 4186497 (additional): [URL](<https://zysjonline.com/articles/misc/23145/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 4382993 (additional): [URL](<https://zysjonline.com/books/ziwuliuzhushuonan/78214/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 4307342 (additional): [URL](<https://zysjonline.com/books/shizhaibaiyixuanfang/164162/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 3. nhathuoclongchau.com.vn

79,598 URL nguồn; 0 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `page_http_403`.

- ID 268030 (original): [URL](<https://nhathuoclongchau.com.vn/bai-viet/thong-tin-can-biet-ve-phuong-phap-phau-thuat-lay-duong-ro-luan-nhi-59283.html>) — `page_http_403`. HTTP trang: 403; HTTP robots: 200. Trang đích trả HTTP ngoài khoảng 200–299. Lỗi gốc: `403`.
- ID 209858 (additional): [URL](<https://nhathuoclongchau.com.vn/bai-viet/ban-da-biet-su-dung-nuoc-hoa-hong-dung-cach-de-lam-san-chac-da-25809.html>) — `page_http_403`. HTTP trang: 403; HTTP robots: 200. Trang đích trả HTTP ngoài khoảng 200–299. Lỗi gốc: `403`.
- ID 254230 (additional): [URL](<https://nhathuoclongchau.com.vn/bai-viet/nhung-dieu-can-biet-ve-dut-day-ham-bao-quy-dau-71157.html>) — `page_http_403`. HTTP trang: 403; HTTP robots: 200. Trang đích trả HTTP ngoài khoảng 200–299. Lỗi gốc: `403`.
- ID 265851 (additional): [URL](<https://nhathuoclongchau.com.vn/bai-viet/tao-do-co-tac-dung-gi-mach-ban-mon-an-dinh-duong-lam-tu-tao-do-68414.html>) — `page_http_403`. HTTP trang: 403; HTTP robots: 200. Trang đích trả HTTP ngoài khoảng 200–299. Lỗi gốc: `403`.
- ID 261682 (additional): [URL](<https://nhathuoclongchau.com.vn/bai-viet/sau-khi-tiem-thuoc-bi-ap-xe-phai-lam-sao-bien-phap-phong-ngua-ap-xe-sau-tiem.html>) — `page_http_403`. HTTP trang: 403; HTTP robots: 200. Trang đích trả HTTP ngoài khoảng 200–299. Lỗi gốc: `403`.

### 4. laodong.vn

31,282 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 154292 (original): [URL](<https://laodong.vn/suc-khoe/4-thuc-uong-giai-nhiet-giup-giam-trao-nguoc-axit-1205578.ldo>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 167325 (additional): [URL](<https://laodong.vn/suc-khoe/tai-sao-bua-sang-la-bua-an-quan-trong-nhat-trong-ngay-939866.ldo>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 160848 (additional): [URL](<https://laodong.vn/suc-khoe/duong-chat-giup-bao-ve-va-tang-cuong-chuc-nang-tuyen-giap-1652344.ldo>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 148430 (additional): [URL](<https://laodong.vn/dinh-duong-am-thuc/bai-kiem-tra-duong-ruot-sau-bua-an-giup-phat-hien-som-van-de-tieu-hoa-1509470.ldo>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 169791 (additional): [URL](<https://laodong.vn/thoi-su/hom-nay-so-y-te-hung-yen-se-bao-cao-pho-thu-tuong-vu-duc-dam-ve-vu-tre-mac-sui-mao-ga-541967.ldo>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 5. baby.39.net

27,621 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 772903 (original): [URL](<http://baby.39.net/a/141222/4540983.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 769710 (additional): [URL](<http://baby.39.net/a/130715/4214836.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 769579 (additional): [URL](<http://baby.39.net/a/130626/4196120.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 766957 (additional): [URL](<http://baby.39.net/a/110505/1679803.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 784015 (additional): [URL](<http://baby.39.net/a/2010614/1357753.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 6. bingli.iiyi.com

24,990 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_timeout`.

- ID 2501085 (original): [URL](<https://bingli.iiyi.com/show/64998-1.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2482643 (additional): [URL](<https://bingli.iiyi.com/show/31366-1.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2488198 (additional): [URL](<https://bingli.iiyi.com/show/47078-1.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2500058 (additional): [URL](<https://bingli.iiyi.com/show/63692-1.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2482030 (additional): [URL](<https://bingli.iiyi.com/show/30058-1.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.

### 7. test.pmphai.com

15,120 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 2541313 (original): [URL](<https://test.pmphai.com/jeesitede/appdisease/toPcDetail?sessionId=&knowledgeLibPrefix=disease&id=0001AA100000000EO44K>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2546141 (additional): [URL](<https://test.pmphai.com/jeesitede/appdisease/toPcDetail?sessionId=&knowledgeLibPrefix=disease&id=19705>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2547491 (additional): [URL](<https://test.pmphai.com/jeesitede/appdisease/toPcDetail?sessionId=&knowledgeLibPrefix=disease&id=22500>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2547848 (additional): [URL](<https://test.pmphai.com/jeesitede/appdisease/toPcDetail?sessionId=&knowledgeLibPrefix=disease&id=22993>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2546393 (additional): [URL](<https://test.pmphai.com/jeesitede/appdisease/toPcDetail?sessionId=&knowledgeLibPrefix=disease&id=20008>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 8. fitness.39.net

12,066 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 818281 (original): [URL](<http://fitness.39.net/a/180124/6017569.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 821451 (additional): [URL](<http://fitness.39.net/a/200102/7732818.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 817013 (additional): [URL](<http://fitness.39.net/a/161122/5052371.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 818931 (additional): [URL](<http://fitness.39.net/a/180807/6442869.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 823120 (additional): [URL](<http://fitness.39.net/a/2010823/1454617.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 9. woman.39.net

11,687 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 914722 (original): [URL](<http://woman.39.net/a/140915/4472540.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 918853 (additional): [URL](<http://woman.39.net/a/180929/6557094.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 913469 (additional): [URL](<http://woman.39.net/a/130210/4125437.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 920981 (additional): [URL](<http://woman.39.net/a/20101217/1570289.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 913380 (additional): [URL](<http://woman.39.net/a/121117/4081685.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 10. food.39.net

11,024 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 844242 (original): [URL](<http://food.39.net/a/2010821/1451769.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 837574 (additional): [URL](<http://food.39.net/a/141021/4498000.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 840780 (additional): [URL](<http://food.39.net/a/171026/6252029.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 843207 (additional): [URL](<http://food.39.net/a/2010416/1224599.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 844156 (additional): [URL](<http://food.39.net/a/201077/1376007.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 11. fk.39.net

9,812 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 836246 (original): [URL](<http://fk.39.net/a/241010/i1trnyn.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 827094 (additional): [URL](<http://fk.39.net/a/121011/4064098.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 831693 (additional): [URL](<http://fk.39.net/a/190111/6789031.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 833154 (additional): [URL](<http://fk.39.net/a/201115/1584822.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 834274 (additional): [URL](<http://fk.39.net/a/201216/1876560.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 12. vov.vn

9,784 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 710247 (original): [URL](<https://vov.vn/suc-khoe/nhung-thu-co-the-can-khi-ban-gia-di-post981896.vov>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 711749 (additional): [URL](<https://vov.vn/suc-khoe/ung-thu-vu-ngay-cang-tre-hoa-phat-hien-benh-muon-do-chu-quan-post1072876.vov>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 707111 (additional): [URL](<https://vov.vn/suc-khoe/cuu-song-benh-nhi-bi-di-vat-tu-ken-nhua-do-choi-bit-duong-tho-post1102119.vov>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 709785 (additional): [URL](<https://vov.vn/suc-khoe/nhiem-virus-co-gay-ra-cac-van-de-suc-khoe-lau-dai-post1072595.vov>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 704798 (additional): [URL](<https://vov.vn/suc-khoe/5-ly-do-nguoi-tieu-dung-lua-chon-khop-aka-tam-binh-863998.vov>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 13. cancer.39.net

8,415 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 2507808 (original): [URL](<https://cancer.39.net/a/210407/8822699.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 795748 (additional): [URL](<http://cancer.39.net/a/2011821/1783622.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2509185 (additional): [URL](<https://cancer.39.net/a/260704/b4wnhh4.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2507100 (additional): [URL](<https://cancer.39.net/a/190129/6846888.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 2504854 (additional): [URL](<https://cancer.39.net/a/140729/4435511.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 14. khoahocphothong.vn

8,143 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 140282 (original): [URL](<https://khoahocphothong.vn/phat-hien-khang-the-co-the-ngan-ngua-hau-het-cac-chung-hiv-240586.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 141025 (additional): [URL](<https://khoahocphothong.vn/song-cham-va-suc-khoe-890.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 137053 (additional): [URL](<https://khoahocphothong.vn/chuot-khong-lo-thi-truong-dang-co-nhu-cau-cao-241869.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 135043 (additional): [URL](<https://khoahocphothong.vn/an-gi-cho-da-dep-241270.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 139074 (additional): [URL](<https://khoahocphothong.vn/lao-phan-mem-benh-hiem-va-kho-chan-doan-240472.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 15. nk.39.net

6,650 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 871353 (original): [URL](<http://nk.39.net/a/150617/4640167.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 870983 (additional): [URL](<http://nk.39.net/a/141230/4543681.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 875474 (additional): [URL](<http://nk.39.net/a/260705/e8wnig4.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 869939 (additional): [URL](<http://nk.39.net/a/130927/4264917.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 870717 (additional): [URL](<http://nk.39.net/a/141027/4502463.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 16. heart.39.net

5,965 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 860914 (original): [URL](<http://heart.39.net/a/190801/7350145.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 863351 (additional): [URL](<http://heart.39.net/a/201264/2037255.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 860924 (additional): [URL](<http://heart.39.net/a/190808/7367337.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 858938 (additional): [URL](<http://heart.39.net/a/140508/4385324.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 862538 (additional): [URL](<http://heart.39.net/a/2011518/1692857.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 17. article.iiyi.com

5,641 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_timeout`.

- ID 2136074 (original): [URL](<https://article.iiyi.com/detail/416303.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2132657 (additional): [URL](<https://article.iiyi.com/detail/26065.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2135173 (additional): [URL](<https://article.iiyi.com/detail/411318.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2133004 (additional): [URL](<https://article.iiyi.com/detail/29106.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.
- ID 2132295 (additional): [URL](<https://article.iiyi.com/detail/22025.html>) — `robots_http_521`. HTTP trang: None; HTTP robots: 521. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `robots HTTP 521`.

### 18. pmc-ecm-healthblog.beta.pharmacity.io

5,333 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 319666 (original): [URL](<https://pmc-ecm-healthblog.beta.pharmacity.io/hoat-chat-amitriptylin/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 321959 (additional): [URL](<https://pmc-ecm-healthblog.beta.pharmacity.io/tay-chan-mieng-o-nguoi-lon/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 318867 (additional): [URL](<https://pmc-ecm-healthblog.beta.pharmacity.io/chao-thit-bo-cho-be/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 320654 (additional): [URL](<https://pmc-ecm-healthblog.beta.pharmacity.io/loang-xuong-o-phu-nu-man-kinh-nguyen-nhan-trieu-chung-va-cach-dieu-tri/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 321630 (additional): [URL](<https://pmc-ecm-healthblog.beta.pharmacity.io/sot-xuat-huyet-dengue-co-dau-hieu-canh-bao/>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 19. man.39.net

5,320 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 868618 (original): [URL](<http://man.39.net/a/220924/8244035.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 868996 (additional): [URL](<http://man.39.net/a/240620/l2pnja3.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 864740 (additional): [URL](<http://man.39.net/a/170420/5298779.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 864933 (additional): [URL](<http://man.39.net/a/180901/6500271.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 865180 (additional): [URL](<http://man.39.net/a/20101220/1573937.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 20. gan.39.net

5,027 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 852556 (original): [URL](<http://gan.39.net/a/260621/x3wnanf.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 850353 (additional): [URL](<http://gan.39.net/a/201091/1462781.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 851733 (additional): [URL](<http://gan.39.net/a/240408/c7ob3xh.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 850506 (additional): [URL](<http://gan.39.net/a/20111231/1871336.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 849567 (additional): [URL](<http://gan.39.net/a/160509/4846922.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 21. tnb.39.net

4,178 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 905348 (original): [URL](<http://tnb.39.net/a/130607/4186274.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 906936 (additional): [URL](<http://tnb.39.net/a/190730/7346219.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 909146 (additional): [URL](<http://tnb.39.net/a/240318/l6npfhp.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 908084 (additional): [URL](<http://tnb.39.net/a/2012418/2008303.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 907364 (additional): [URL](<http://tnb.39.net/a/200615/7969298.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 22. wei.39.net

3,894 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 909349 (original): [URL](<http://wei.39.net/a/110821/1781775.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 912097 (additional): [URL](<http://wei.39.net/a/231010/u6hllsh.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 912872 (additional): [URL](<http://wei.39.net/a/260114/w9wck3n.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 909378 (additional): [URL](<http://wei.39.net/a/120821/4038642.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 911287 (additional): [URL](<http://wei.39.net/a/201167/1707521.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 23. baidianfeng.familydoctor.com.cn

3,798 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 2475161 (original): [URL](<https://baidianfeng.familydoctor.com.cn/a/201511/856792.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2476059 (additional): [URL](<https://baidianfeng.familydoctor.com.cn/a/201607/1155860.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2476545 (additional): [URL](<https://baidianfeng.familydoctor.com.cn/a/201611/1457641.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2476324 (additional): [URL](<https://baidianfeng.familydoctor.com.cn/a/201608/1223299.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2477303 (additional): [URL](<https://baidianfeng.familydoctor.com.cn/a/201807/2496185.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 24. shen.39.net

3,223 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 901143 (original): [URL](<http://shen.39.net/a/140114/4326874.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 902801 (additional): [URL](<http://shen.39.net/a/2011321/1639336.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 903033 (additional): [URL](<http://shen.39.net/a/2011629/1733644.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 901422 (additional): [URL](<http://shen.39.net/a/140515/4389313.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 901456 (additional): [URL](<http://shen.39.net/a/140605/4400254.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 25. ek.39.net

3,222 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 812548 (original): [URL](<http://ek.39.net/a/20101018/1506617.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 811939 (additional): [URL](<http://ek.39.net/a/141027/4502829.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 812236 (additional): [URL](<http://ek.39.net/a/160223/4773434.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 814621 (additional): [URL](<http://ek.39.net/a/260617/c4wlpf1.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 813561 (additional): [URL](<http://ek.39.net/a/2011824/1787509.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 26. thaythuocvietnam.vn

2,927 URL nguồn; 0 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `qc_review`.

- ID 660759 (original): [URL](<https://thaythuocvietnam.vn/hen-phe-quan-va-nhung-dieu-khong-the-bo-qua/>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: redirect_review Lỗi gốc: `redirect_review`.
- ID 660622 (additional): [URL](<https://thaythuocvietnam.vn/dieu-tri-viem-dao-bang-la-trau-khong/>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: redirect_review Lỗi gốc: `redirect_review`.
- ID 659640 (additional): [URL](<https://thaythuocvietnam.vn/5-nguyen-nhan-khien-be-bi-tieu-chay-khong-phai-ai-cung-biet/>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: redirect_review Lỗi gốc: `redirect_review`.
- ID 660376 (additional): [URL](<https://thaythuocvietnam.vn/chua-rom-say-bang-la-tia/>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: redirect_review Lỗi gốc: `redirect_review`.
- ID 660757 (additional): [URL](<https://thaythuocvietnam.vn/he-tieu-hoa-o-tre-co-gi-khac-biet-so-voi-nguoi-lon/>) — `qc_review`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: redirect_review Lỗi gốc: `redirect_review`.

### 27. www.baidu.com

2,631 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_disallowed`.

- ID 3160976 (original): [URL](<https://www.baidu.com/bh/dict/ydxx_8424738550787796805?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://www.baidu.com/bh/dict/ydxx_8424738550787796805?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc`.
- ID 3161355 (additional): [URL](<https://www.baidu.com/bh/dict/ydzz_10920235955547793183?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://www.baidu.com/bh/dict/ydzz_10920235955547793183?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc`.
- ID 3159077 (additional): [URL](<https://www.baidu.com/bh/dict/ydxx_10636434201717482014?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://www.baidu.com/bh/dict/ydxx_10636434201717482014?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc`.
- ID 3160776 (additional): [URL](<https://www.baidu.com/bh/dict/ydxx_8268354771339634679?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://www.baidu.com/bh/dict/ydxx_8268354771339634679?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc`.
- ID 3161407 (additional): [URL](<https://www.baidu.com/bh/dict/ydzz_11072597944815470133?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://www.baidu.com/bh/dict/ydzz_11072597944815470133?from=dicta&sf_ref=med_pc&sf_ch=ch_med_pc`.

### 28. gk.39.net

2,059 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 854825 (original): [URL](<http://gk.39.net/a/090624/900447.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 854923 (additional): [URL](<http://gk.39.net/a/091115/1059171.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 854745 (additional): [URL](<http://gk.39.net/a/090420/839723.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 855101 (additional): [URL](<http://gk.39.net/a/100623/1350183.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 854369 (additional): [URL](<http://gk.39.net/a/071226/211281.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 29. baolangson.vn

1,981 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_disallowed`.

- ID 64079 (original): [URL](<https://baolangson.vn/thanh-tra-kiem-tra-kiem-nghiem-san-pham-duoc-tiep-nhan-xu-ly-cac-thong-tin-ve-thuoc-gia-5044678.html>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://baolangson.vn/thanh-tra-kiem-tra-kiem-nghiem-san-pham-duoc-tiep-nhan-xu-ly-cac-thong-tin-ve-thuoc-gia-5044678.html`.
- ID 64127 (additional): [URL](<https://baolangson.vn/thu-hoi-cac-san-pham-khong-dam-bao-an-toan-thuc-pham-dip-tet-trung-thu-5018008.html>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://baolangson.vn/thu-hoi-cac-san-pham-khong-dam-bao-an-toan-thuc-pham-dip-tet-trung-thu-5018008.html`.
- ID 63763 (additional): [URL](<https://baolangson.vn/nhieu-dia-phuong-trien-khai-hieu-qua-cac-hoat-dong-noi-bat-trong-linh-vuc-y-te-1629425.html>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://baolangson.vn/nhieu-dia-phuong-trien-khai-hieu-qua-cac-hoat-dong-noi-bat-trong-linh-vuc-y-te-1629425.html`.
- ID 62986 (additional): [URL](<https://baolangson.vn/chi-so-duong-huyet-tang-nhe-cung-lam-giam-kha-nang-sinh-san-o-nam-gioi-5053147.html>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://baolangson.vn/chi-so-duong-huyet-tang-nhe-cung-lam-giam-kha-nang-sinh-san-o-nam-gioi-5053147.html`.
- ID 63955 (additional): [URL](<https://baolangson.vn/so-ket-cong-tac-y-te-9-thang-dau-nam-1454136.html>) — `robots_disallowed`. HTTP trang: None; HTTP robots: 200. robots.txt không cho phép crawler tải URL này. Lỗi gốc: `https://baolangson.vn/so-ket-cong-tac-y-te-9-thang-dau-nam-1454136.html`.

### 30. gc.39.net

1,746 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 853240 (original): [URL](<http://gc.39.net/a/141221/4540391.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 853524 (additional): [URL](<http://gc.39.net/a/20111215/1863538.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 854213 (additional): [URL](<http://gc.39.net/a/240917/i6swxag.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 852953 (additional): [URL](<http://gc.39.net/a/140328/4364063.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 853516 (additional): [URL](<http://gc.39.net/a/20111129/1850387.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 31. pf.39.net

1,538 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 876479 (original): [URL](<http://pf.39.net/a/2011418/1666222.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 875822 (additional): [URL](<http://pf.39.net/a/121106/4077356.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 876485 (additional): [URL](<http://pf.39.net/a/2011420/1668309.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 876796 (additional): [URL](<http://pf.39.net/a/2011930/1817940.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 876825 (additional): [URL](<http://pf.39.net/a/2012118/1880918.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 32. baotayninh.vn

1,198 URL nguồn; 0 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `qc_rejected`.

- ID 90572 (original): [URL](<https://baotayninh.vn/hanh-trinh-tan-hien-cua-nhung-thay-thuoc-uu-tu-140074.html>) — `qc_rejected`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: short_text, missing_title, low_letter_ratio Lỗi gốc: `short_text; missing_title; low_letter_ratio`.
- ID 91232 (additional): [URL](<https://baotayninh.vn/tuan-le-dinh-duong-va-phat-trien-115160.html>) — `qc_rejected`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: short_text, missing_title, low_letter_ratio Lỗi gốc: `short_text; missing_title; low_letter_ratio`.
- ID 91110 (additional): [URL](<https://baotayninh.vn/thoi-quen-chan-canh-vao-com-co-anh-huong-den-tieu-hoa-can-nang-khong-134737.html>) — `qc_rejected`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: short_text, missing_title, low_letter_ratio Lỗi gốc: `short_text; missing_title; low_letter_ratio`.
- ID 90651 (additional): [URL](<https://baotayninh.vn/khong-can-vai-nam-tri-tue-nhan-tao-co-the-thiet-ke-khang-sinh-moi-trong-vai-ngay-31830.html>) — `qc_rejected`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: short_text, missing_title, low_letter_ratio Lỗi gốc: `short_text; missing_title; low_letter_ratio`.
- ID 91031 (additional): [URL](<https://baotayninh.vn/tan-thanh-tap-huan-nang-cao-nang-luc-ve-phong-chong-tac-hai-thuoc-la-103084.html>) — `qc_rejected`. HTTP trang: 200; HTTP robots: 200. Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: short_text, missing_title, low_letter_ratio Lỗi gốc: `short_text; missing_title; low_letter_ratio`.

### 33. sj.39.net

942 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 904470 (original): [URL](<http://sj.39.net/a/140814/4447769.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 904120 (additional): [URL](<http://sj.39.net/a/090805/947726.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 904794 (additional): [URL](<http://sj.39.net/a/20101214/1567962.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 904181 (additional): [URL](<http://sj.39.net/a/100731/1418411.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 904319 (additional): [URL](<http://sj.39.net/a/140327/4359632.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 34. byby.39.net

439 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 794284 (original): [URL](<http://byby.39.net/a/230524/13823332.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 794379 (additional): [URL](<http://byby.39.net/a/230530/13823942.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 794437 (additional): [URL](<http://byby.39.net/a/231008/q3hfib1.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 794456 (additional): [URL](<http://byby.39.net/a/231127/i8ju7dz.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.
- ID 794080 (additional): [URL](<http://byby.39.net/a/090414/840851.html>) — `robots_html_instead_of_txt`. HTTP trang: None; HTTP robots: 200. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTML instead of robots.txt`.

### 35. www.familydoctor.cn

44 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_html_instead_of_txt`.

- ID 3530740 (original): [URL](<https://www.familydoctor.cn/a/201309/512842.html>) — `robots_timeout`. HTTP trang: None; HTTP robots: None. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTTPSConnectionPool(host='www.familydoctor.cn', port=443): Read timed out. (read timeout=8)`.
- ID 3530756 (additional): [URL](<https://www.familydoctor.cn/a/201508/805147.html>) — `robots_timeout`. HTTP trang: None; HTTP robots: None. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTTPSConnectionPool(host='www.familydoctor.cn', port=443): Read timed out. (read timeout=8)`.
- ID 3530745 (additional): [URL](<https://www.familydoctor.cn/a/201310/526062.html>) — `robots_timeout`. HTTP trang: None; HTTP robots: None. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTTPSConnectionPool(host='www.familydoctor.cn', port=443): Read timed out. (read timeout=8)`.
- ID 3530741 (additional): [URL](<https://www.familydoctor.cn/a/201309/515961.html>) — `robots_timeout`. HTTP trang: None; HTTP robots: None. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTTPSConnectionPool(host='www.familydoctor.cn', port=443): Read timed out. (read timeout=8)`.
- ID 3530730 (additional): [URL](<https://www.familydoctor.cn/a/201308/495263.html>) — `robots_timeout`. HTTP trang: None; HTTP robots: None. Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang. Lỗi gốc: `HTTPSConnectionPool(host='www.familydoctor.cn', port=443): Read timed out. (read timeout=8)`.

### 36. qy.familydoctor.com.cn

40 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 900894 (original): [URL](<http://qy.familydoctor.com.cn/a/201405/609715.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 900888 (additional): [URL](<http://qy.familydoctor.com.cn/a/201404/607267.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 900865 (additional): [URL](<http://qy.familydoctor.com.cn/a/201404/600843.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 900885 (additional): [URL](<http://qy.familydoctor.com.cn/a/201404/606769.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 900859 (additional): [URL](<http://qy.familydoctor.com.cn/a/201404/599786.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 37. v.familydoctor.com.cn

10 URL nguồn; 5 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 2551069 (original): [URL](<https://v.familydoctor.com.cn/a/201509/816823.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2551074 (additional): [URL](<https://v.familydoctor.com.cn/a/201805/2481078.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2551070 (additional): [URL](<https://v.familydoctor.com.cn/a/201711/2432472.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2551068 (additional): [URL](<https://v.familydoctor.com.cn/a/201509/816228.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2551066 (additional): [URL](<https://v.familydoctor.com.cn/a/201506/779925.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 38. ask.familydoctor.com.cn

3 URL nguồn; 3 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 766444 (original): [URL](<http://ask.familydoctor.com.cn/zt/mn.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 766442 (additional): [URL](<http://ask.familydoctor.com.cn/q/10420069.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 766443 (additional): [URL](<http://ask.familydoctor.com.cn/q/3909357.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.

### 39. yanglao.familydoctor.com.cn

2 URL nguồn; 2 mẫu đã xử lý nhưng chưa request bài viết. Lỗi baseline: `robots_http_403`.

- ID 2131080 (original): [URL](<http://yanglao.familydoctor.com.cn/zt/scsjtfz.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
- ID 2131079 (additional): [URL](<http://yanglao.familydoctor.com.cn/a/201601/930045.html>) — `robots_http_403`. HTTP trang: None; HTTP robots: 403. robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots. Lỗi gốc: `robots HTTP 403`.
