# Review domain samples: khôi phục đủ 97 hostname

Ngày 04/10/2026. Notebook [crawl_domain_samples.ipynb](../../notebooks/crawl_domain_samples.ipynb) hiện mặc định chạy **97 URL, một URL gốc cho mỗi hostname**. Các ID/URL đúng bộ reservoir seed 42 ban đầu, đã đối chiếu trực tiếp với `links_corpus.parquet` và bộ mẫu cũ. Dataset có 4.394.718 dòng; giữ riêng các subdomain.

## Review lượt chạy mới nhất của người dùng

Run `notebooks/runs/domain_probe_20261004_134438_e4efbb`, báo cáo lúc 20:50 ngày 04/10/2026, chạy lại 25 URL của 5 hostname bằng priority-probe-v2:

- Requests: 20 HTTP 200, 5 HTTP 403; không còn network_error.
- cnkang, 120ask, familydoctor.com.cn và ask.39.net: mỗi hostname 5/5 URL tải được.
- zysjonline: cả 5 URL vẫn có Cloudflare challenge trong Requests và Selenium; header `Cf-Mitigated: challenge` được giữ trong trace.
- QC: 17 accepted, 3 review. Hash raw/text của 25 Requests records và 5 browser records đã được kiểm tra.

Notebook có output được lưu trước khi cập nhật tại [baseline_local_notebook.ipynb](../../runs/domain_97_review_20261004/baseline_local_notebook.ipynb). Các run của người dùng được giữ nguyên.

## Kết quả probe mới cho đủ 97 hostname

Run mới: `runs/domain_97_review_20261004/probe`. Tất cả 97 URL được request mới, không reuse kết quả cũ. Báo cáo hoàn tất lúc **21:12 ngày 04/10/2026**, giờ Việt Nam.

| Chỉ số | Kết quả |
| --- | ---: |
| URL / hostname đã chạy | 97 / 97 |
| Pending | 0 |
| Requests tải được | 84 |
| Requests http_error / network_error | 12 / 1 |
| Selenium thử các URL Requests lỗi | 13 |
| Selenium phục hồi thêm | 3 |
| Tải được sau cả hai engine | **87/97 (89,69%)** |
| Lỗi truy cập còn lại | **10: 8 HTTP 403, 2 HTTP 521** |
| QC cuối của 87 URL tải được | 82 accepted, 3 review, 2 rejected |

Các lỗi Requests vẫn được giữ nguyên trong cột `crawl_status`, `error_detail`, `http_status`. `access_result` và các cột `effective_*` tính cả kết quả Selenium. Vì vậy summary vẫn có 1 network_error của Requests, nhưng URL đó đã được browser phục hồi; không có lỗi mạng chưa được phục hồi trong kết quả cuối của lượt này.

| Hostname được Selenium phục hồi | ID | Requests | Selenium | Ký tự trích xuất | QC |
| --- | ---: | --- | ---: | ---: | --- |
| vov.vn | 710247 | HTTP 403 | HTTP 200 | 5.496 | accepted |
| suckhoeviet.org.vn | 565289 | 3 timeout | HTTP 200 | 16.052 | accepted |
| special.vietnamplus.vn | 583 | HTTP 429 sau retry | HTTP 200 | 11.719 | accepted |

## Ưu tiên lỗi truy cập theo số URL dataset

Số URL nguồn là số dòng của hostname, chưa loại URL trùng; không phải số URL đã chứng minh bị lỗi. Cả Requests và Selenium đều chưa phục hồi các mẫu dưới đây.

| Ưu tiên | Hostname | Số URL dataset | ID mẫu | Requests / Selenium |
| ---: | --- | ---: | ---: | --- |
| 1 | zysjonline.com | 243.347 | 4182981 | 403 / 403; challenge |
| 2 | nhathuoclongchau.com.vn | 79.598 | 268030 | 403 / 403; challenge |
| 3 | bingli.iiyi.com | 24.990 | 2501085 | 521 / 521 |
| 4 | article.iiyi.com | 5.641 | 2136074 | 521 / 521 |
| 5 | pmc-ecm-healthblog.beta.pharmacity.io | 5.333 | 319666 | 403 / 403 |
| 6 | baidianfeng.familydoctor.com.cn | 3.798 | 2475161 | 403 / 403 |
| 7 | qy.familydoctor.com.cn | 40 | 900894 | 403 / 403 |
| 8 | v.familydoctor.com.cn | 10 | 2551069 | 403 / 403 |
| 9 | ask.familydoctor.com.cn | 3 | 766444 | 403 / 403 |
| 10 | yanglao.familydoctor.com.cn | 2 | 2131080 | 403 / 403 |

403/challenge cần xử lý khả năng truy cập với website; tăng attempts hoặc chỉ đổi User-Agent chưa phục hồi được các mẫu này. Hai hostname iiyi trả trang lỗi 521 trong cả hai engine. Theo [tài liệu Cloudflare về 521](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-5xx-errors/error-521/), đây là lỗi origin từ chối kết nối từ Cloudflare; có thể do origin ngừng phục vụ hoặc chặn Cloudflare. Chưa có log phía origin để phân biệt nguyên nhân cụ thể. Giữ raw lỗi và retry ở một recovery run vào thời điểm khác thay vì tăng tải liên tục.

## Các mẫu tải được nhưng nội dung cần xem lại

| Hostname | ID | Cờ / vấn đề |
| --- | ---: | --- |
| www.120ask.com | 2843944 | boilerplate_suspect; 558 ký tự |
| khoahocphothong.vn | 140282 | redirect_review; có bài và 1.706 ký tự, cần xác minh nguồn đích |
| thaythuocvietnam.vn | 660759 | redirect_review; tiêu đề cuối là Trang chủ, có dấu hiệu mất bài gốc |
| laodong.vn | 154292 | HTTP 200 nhưng text rỗng, missing_title; rejected |
| baotayninh.vn | 90572 | HTTP 200 nhưng text rỗng, missing_title; rejected |

Selenium mặc định chỉ thử các URL Requests không hoàn tất trích xuất, nên hai mẫu HTTP 200/text rỗng chưa được browser thử trong lượt này. Có thể dùng `BROWSER_TEST_MODE = 'all'` hoặc `first_each_domain_and_failures` để đối chiếu thêm. Với bộ một mẫu mỗi hostname, cả hai chế độ này sẽ thử browser cho đủ 97 URL. Bảng `uu_tien_fix_domain` gồm cả lỗi truy cập và nội dung, nên có 15 hostname cần xử lý; bảng trên chỉ có 10 lỗi truy cập.

## Các cải thiện được giữ trong notebook 97 hostname

- Dùng Requests với User-Agent/header trình duyệt, tải trực tiếp các URL mẫu để kiểm tra truy cập; snapshot core v5 và parser hiện tại vẫn được nhúng. Probe này không dùng robots để chặn bước kiểm tra URL; luồng crawl corpus riêng vẫn có chính sách robots và retry/cache v5.
- Connect/read timeout 20/45 giây, budget 180 giây mỗi URL, tối đa 3 attempts. Mỗi registered domain chỉ có một sample đang chạy; 8 workers cho các domain khác nhau.
- Lỗi mạng retry với session/pool mới và giữ cookies; backoff, cooldown/Retry-After, raw/hash mỗi response, phân loại timeout/DNS/SSL/connection closed và challenge.
- Selenium dùng Chrome thực, page-load timeout 45 giây, tối đa 2 attempts cho lỗi tạm thời; giữ raw, screenshot và lịch sử. Không đưa challenge vào corpus hay retry 403 liên tục.
- Recovery sang run mới bằng `RECOVERY_RUN_DIR`, chỉ reuse raw 2xx đã kiểm tra hash; checkpoint lỗi được request lại. Chạy mới toàn bộ bằng cách để cả `RECOVERY_RUN_DIR` và `RESUME_RUN_DIR` là `None`.
- Bảng CSV/HTML/Markdown tính cả browser phục hồi, giữ riêng lỗi Requests; xếp hostname lỗi theo số URL dataset giảm dần.
- `network_check.json` ghi DNS của đủ 97 hostname. Notebook tự chứa samples và snapshot, chạy được trên local/Kaggle mà không cần clone repo.

Builder mặc định tạo bộ 97 hostname. Có thể tạo lại bộ 25 URL cũ bằng `python scripts/build_domain_probe_notebook.py --priority-five`, hoặc bộ follow-up bằng `--failed-followup`. Các lệnh đó thay nội dung cùng notebook; để khôi phục 97, chạy builder không có cờ. `--refresh-all-hosts` lấy lại đúng mẫu reservoir từ Parquet.

## Xác minh và output

- **54 tests pass**, gồm ID/URL nguồn của 97 hostname, giữ 5 mẫu gốc của nhóm ưu tiên, browser fallback, thứ tự domain và toàn bộ regression retry/cache/parser. Test notebook Kaggle đã hỗ trợ cả `source` dạng chuỗi và danh sách dòng do Jupyter lưu, không chỉnh notebook corpus của người dùng.
- Notebook thực thi trong probe có cùng hash với notebook cuối. Snapshot priority probe khớp source hiện tại. Tất cả raw/text hash và raw của response trung gian đã được kiểm tra; ZIP hợp lệ.
- [Bảng kết quả 97 hostname](../../runs/domain_97_review_20261004/probe/ket_qua.html).
- [Requests so với Selenium, CSV](../../runs/domain_97_review_20261004/probe/requests_vs_selenium.csv).
- [10 URL còn lỗi truy cập](../../runs/domain_97_review_20261004/probe/khong_vao_duoc.csv).
- [Bảng ưu tiên cả lỗi truy cập và nội dung](../../runs/domain_97_review_20261004/probe/uu_tien_fix_domain.html).
- [Báo cáo lỗi sinh từ notebook](../../runs/domain_97_review_20261004/probe/WEB_ERRORS.md).
- [ZIP đầy đủ](../../runs/domain_97_review_20261004/probe.zip).
- [Log probe](../../runs/domain_97_review_20261004/probe.log), [metadata xác minh](../../runs/domain_97_review_20261004/validation.json), [log tests](../../runs/domain_97_review_20261004/tests.log).

Đây là kiểm chứng một URL mỗi hostname, chưa đánh giá toàn bộ đường dẫn của từng website hay chất lượng chuyên môn của nội dung. Không so trực tiếp tỷ lệ này với run cũ có robots gate như một phép đo riêng hiệu quả retry: phạm vi chính sách và engine đã khác nhau.
