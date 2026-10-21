# Thí nghiệm và review lại cnkang.com — 20/10/2026

Hướng tốt nhất trong các phương án đã thử là **Requests tuần tự + parser DOM riêng + khôi phục thứ tự theo `formattext` đã xác minh + ghép trang tiếp có kiểm tra cùng bài**. Có bằng chứng cụ thể cho việc giữ Requests làm transport và sửa tầng trích xuất; chưa có lý do từ các mẫu này để chạy Selenium cho toàn domain.

Đây là kết luận về độ đầy đủ, thứ tự và độ sạch của dữ liệu crawl. Chưa xác minh tính đúng y khoa hoặc độ phù hợp của mọi bài với corpus huấn luyện.

## Cell và cách chạy

Theo yêu cầu tổ chức lại, hiện chỉ giữ **`notebooks/check_cnkang.com.ipynb`**, là file local đã ignore. Code/helper và output thí nghiệm đều nằm trong phần cuối notebook, có thể bắt đầu riêng từ cell cấu hình mà không chạy lại 500 URL. Các bản notebook/helper rời trước đây được lưu trong thư mục output đã ignore. Sáu cell code thí nghiệm gồm:

1. Chọn run nguồn, thư mục kết quả, quyền gọi mạng và giới hạn tối đa 6 trang/bài.
2. Nạp snapshot parser/transport/helper đã kiểm SHA-256 và ghi cấu hình.
3. Tải hoặc xác minh JavaScript gốc.
4. Replay cùng raw cho ba phương án A/B/C; thực thi hàm JavaScript làm đối chứng.
5. Thử ghép chuỗi trang tiếp có kiểm tra danh tính bài.
6. Tổng hợp chỉ số, mẫu trước/sau và liên kết artifact.

**Đã thực thi cả 6 cell, không có cell lỗi**. Output hiện được giữ ngay trong `notebooks/check_cnkang.com.ipynb`, kèm một cell chạy 10 test hồi quy thí nghiệm. Mặc định không gọi mạng; bật `EXP_ALLOW_NETWORK=True` khi cần tải bằng chứng chưa có trong cache. Khi chưa có JS và không bật mạng, các thí nghiệm được bỏ qua với thông báo rõ ràng.

Run nguồn gồm 491 trang parse được từ mẫu cũ 500 URL và 30 trang live của lượt review trước, tổng **521 trang khác nhau**. Lượt này tải mới JavaScript và **17 trang tiếp**; sau đó notebook sử dụng cache đã kiểm checksum để tái lập. Không crawl lại toàn bộ các URL nguồn. Lịch sử lấy mẫu còn thiếu, nên không coi đây là holdout độc lập hoàn toàn với các lượt trước.

## Thí nghiệm 1 — Xác minh quy tắc JavaScript

Nguồn: `https://www.cnkang.com/images/jkpl.js`, HTTP 200, robots cho phép. SHA-256 raw:

```text
55e84799edcefd67fa1f98addc24e1eed6b803d44824054bad1aa2040b7b674f
```

Hàm `formattext(count)` đi từ `count` xuống 0 nhưng chèn `innerHTML` của mỗi khối vào đầu chuỗi. Kết quả là nội dung theo ID **tăng dần**. Sau đó hàm ghi chuỗi vào `jkpl` và ẩn các khối cũ. Do vậy thứ tự DOM raw không phải thứ tự hiển thị ở các bài này; đây không còn chỉ là nghi ngờ từ cờ đánh số giảm dần.

Phương án B chỉ áp dụng khi có đúng lời gọi hợp lệ, đúng script nguồn, đúng vùng bài, ID duy nhất và các khối cùng cấp. Trường hợp cấu trúc lạ bị giữ ở trạng thái lỗi/review, không đoán thứ tự từ ý nghĩa câu. Hàm JS tải thật được thực thi trong Node VM trên DOM tối thiểu để đối chiếu kết quả ghép `innerHTML`: **85/85 trường hợp khớp**, mọi khối cũ được hàm gốc đặt ẩn.

Đây là xác minh trực tiếp hàm định dạng; chưa phải benchmark render toàn trang bằng browser. Mã JS được lấy ngày 20/10 và áp dụng lên raw lưu ngày 18–20/10; chưa có snapshot JS lịch sử riêng từng trang.

## Thí nghiệm 2 — A/B/C trên cùng HTML

| Phương án | Trang | Không cờ parser | Cụm từ menu theo heuristic |
|---|---:|---:|---:|
| A: parser hiện tại, DOM tĩnh | 521 | 383 (73,5%) | 0 |
| B: parser riêng + thứ tự JS đã xác minh | 521 | 398 (76,4%) | 0 |
| C: trafilatura, giữ bảng (`include_tables=True`) | 521 | Không chấm bằng QC của parser riêng | 308 |

Heuristic menu đếm trang có ít nhất 2 trong 4 cụm cố định của menu: `男性健身`, `专题推荐`, `医学药学`, `老人健康`. Đây là chỉ báo nhiễu để đối chiếu, không phải precision/recall đã gán nhãn.

Kết quả B:

- **79 trang thay đổi text**, gồm **55 trang A vốn không có cờ parser**. Sáu trong 85 trang có `formattext` không đổi text vì thứ tự/phần có nội dung đã tương đương.
- **521/521** giữ nguyên tập ký tự kèm số lần xuất hiện, cả khi tính và khi bỏ khoảng trắng. Chỉ số này được dùng cùng đối chiếu JS và đọc mẫu; bản thân nó không chứng minh toàn văn đúng.
- Cờ đánh số giảm dần: **67 → 51**; dấu hiệu bị cắt cuối: **2 → 1**. Không tự bỏ các cờ còn lại.
- Không xuất hiện lỗi chuyển đổi hay text rỗng.

Hai ví dụ đọc lại:

- ID **1869305**, `/nkwk/ganglie/386336.html`: A bắt đầu bằng `⑤`, `④`, `③` rồi xuống `①`; B đi `①` đến `⑤`, đúng quy tắc JS.
- ID **1733228**, `/jibing/biantaotiyan/324306.html`: A mở đầu bằng câu kết “bây giờ đã hiểu…”, trong khi B mở đầu bằng câu giới thiệu rồi mới tới giải thích và kết luận.
- ID **1780432**, `/jibing/shengjingxing/401573.html`: B đưa phần giới thiệu về đầu, sau đó đến từng nhóm điều trị; không đảo toàn bộ bài một cách mù quáng.

Phương án C có **113 trang dài hơn A trên 1,5 lần**, **4 trang ngắn dưới một nửa A**, chỉ **43 trang** trùng text sau bỏ khoảng trắng. Đọc ID **1694432** và **1812989** cho thấy phần dài thêm có bảng menu điều hướng. Do đó không chọn cấu hình C này làm mặc định. Chưa thử hết cấu hình trafilatura, đặc biệt trường hợp tắt bảng; không suy luận rằng mọi cấu hình của thư viện đều kém.

## Thí nghiệm 3 — Ghép trang có xác minh

Mỗi liên kết tiếp phải cùng hostname tương đương `www`, cùng path/ID bài, chỉ số đúng trang kế tiếp, không query lạ; sau tải phải khớp tiêu đề chuẩn hóa, template và ngày khi cả hai trang có ngày. Không ghép body trùng, redirect đổi danh tính, vòng lặp, bài liên quan hoặc vượt quá giới hạn 6 trang. Robots/cooldown vẫn áp dụng; không đổi giao thức để né 403/429.

| Chỉ số | Kết quả |
|---|---:|
| Bài có liên kết trang tiếp | 9 |
| Chuỗi kết thúc hợp lệ | 9/9 |
| Trang nguồn + trang tiếp | 26 |
| Trang mới bổ sung | 17 |
| Ký tự trang đầu sau bỏ pager | 3.558 |
| Ký tự sau ghép | 9.723 (**2,73 lần**) |
| Khối điều hướng được loại có bằng chứng | 5 |
| Bài sau ghép không còn cờ parser | 8/9 |

Trong vòng đọc đầu, phát hiện pager còn nằm trong `endText`. Đã thêm quy tắc chỉ xóa khối `<b>` có toàn bộ text là nút trang/số trang và mọi link vẫn thuộc cùng bài, rồi chạy lại từ raw cache. Số ký tự trang đầu trước bỏ pager là 3.579; số 3.558 ở bảng đã loại phần giao diện này. Không xóa câu có số hoặc link bài liên quan một cách tổng quát. Không thấy đoạn trùng liền kề tại biên trang trong 9 bài; cơ chế loại trùng chỉ xử lý phần đuôi/đầu đoạn khớp chính xác.

Bài còn cờ là ID **1684761**, `/dzjk/201404/628851.html`: số thứ tự khởi động lại giữa hai nhóm nội dung (`2.高纤牛奶` rồi `1.断食中要补充足够的水分。`). Đọc mẫu cho thấy đây có thể là báo động do chuyển nhóm, không có bằng chứng chuỗi trang sai. Vẫn giữ cờ để tránh nới QC chỉ nhằm tăng tỷ lệ sạch.

Chuỗi được coi là hoàn tất khi trang cuối không còn liên kết tiếp theo mà parser nhận diện. Chưa có sitemap/nhãn toàn văn độc lập để khẳng định tuyệt đối không thiếu trang ẩn. 7/9 bài phân trang nằm trong `/xinwen/`; các bài tin tức, đời sống hoặc quảng bá vẫn cần gate nguồn riêng dù ghép đúng.

Nếu thay 9 record trang đầu bằng kết quả ghép và giữ nguyên QC còn lại, số bài không cờ parser là **406/521 (77,9%)**, so với A là 383/521. Đây là phép tổng hợp trên mẫu, không phải tỷ lệ dữ liệu đúng y khoa hoặc đạt chuẩn huấn luyện.

## Test và giới hạn còn lại

**36/36 test cnkang pass**, gồm 26 test production sẵn có và 10 test thí nghiệm. Sau khi gộp file, 10 test thí nghiệm nằm trong notebook check, không còn là file trong `tests/`. Các test này kiểm tra encoding khi khôi phục JS, inline text, ID thiếu/trùng/lồng/sai phạm vi, JS nguồn không hợp lệ, checksum bị đổi, link sang bài/host khác, nhảy trang/vòng lặp/query, lệch title và xóa pager có kiểm chứng. Test đổi title xác nhận không có text ghép được xuất khi phát hiện sai bài.

Các vấn đề metadata của review trước vẫn còn: `meta author` bỏ sót byline trong body; so khớp nguyên chuỗi chữ Hán gây cờ title/body sai. Không dùng việc tăng tỷ lệ parser sạch để gỡ những cờ nguồn này. Bảng/encoding, claim quảng bá, ngày cũ và dạng bài cần tiếp tục kiểm tra riêng.

## Hướng triển khai rút ra

1. Giữ transport Requests hiện tại: một worker, gap tối thiểu 1,5 giây, robots, timeout/retry hữu hạn và raw/checkpoint.
2. Khi đưa quy tắc JS vào parser chính, nhận diện đúng cấu trúc và lưu thứ tự trước/sau, phiên bản quy tắc cùng bằng chứng JS; cấu trúc lạ phải review. Không cần thực thi JS toàn website cho mỗi URL.
3. Đưa pagination vào tầng runner để mỗi trang có raw/checksum/URL riêng, ghép sau khi xác minh, kiểm QC lại toàn bài; lỗi giữa chuỗi không được xuất thành bài hoàn chỉnh.
4. Tách gate trích xuất khỏi gate nguồn, cải thiện tác giả/title-body bằng tập nhãn thủ công và chạy holdout mới trước khi mở rộng.

Lượt này thực hiện các thay đổi trong cell thí nghiệm; **chưa thay parser hay runner production**. Builder có `--check-only` để tạo một notebook check, bảo toàn phần thí nghiệm local có tag, mà không build lại notebook crawl của domain khác. Chi tiết triển khai dự kiến ở [kế hoạch áp dụng](../plans/cnkang_main_crawler_rollout_20261020.md).

## Artifact

- Notebook duy nhất, có code nhúng/test/output: `notebooks/check_cnkang.com.ipynb` (gitignored).
- Bản cũ để đối chiếu: `runs/cnkang_experiments_20261020/consolidation_backup/legacy_files/` (gitignored).
- Output: `runs/cnkang_experiments_20261020/` gồm snapshot/config, JS/HTML cache và SHA-256, `variants.jsonl`, `documents.jsonl`, `order_evidence.jsonl`, `oracle_results.jsonl`, `pagination_results.jsonl`, hai summary và `experiment_report.md`.
- Tái lập: mở phần thí nghiệm trong file check duy nhất, chọn `EXP_SOURCE_RUNS` và `EXP_OUTPUT_DIR`, chạy các cell theo thứ tự. Bật mạng khi thiếu bằng chứng cache; khi cache đầy đủ không tải lại. Sửa code nhúng phải dùng thư mục thí nghiệm mới để giữ kết quả trước. Builder bảo toàn các cell local đã có; checkout mới không chứa phần thí nghiệm đã ignore.
