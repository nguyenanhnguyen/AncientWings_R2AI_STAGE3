# Review chất lượng cnkang.com — 20/10/2026

Kết luận: truy cập và trích xuất cơ bản hoạt động; chưa nên đưa toàn bộ domain vào corpus chỉ dựa trên `quality_status=accepted`. Cần ưu tiên xác minh thứ tự hiển thị các bài có JavaScript, hoàn chỉnh bài phân trang và sửa cách đánh giá metadata. Đây là review crawl/parser và đặc điểm dữ liệu, không phải thẩm định tính đúng y khoa.

## Phạm vi và kết quả chạy

- Chạy `.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p '*cnkang*' -v`: **26/26 pass**, 31,264 giây. Bao phủ parser, encoding, sampling, robots, HTTP/challenge, checkpoint/resume và tích hợp notebook. Có DeprecationWarning của thư viện `tld`, không làm test fail.
- Replay dữ liệu cũ: `runs/cnkang_offline_fixed_20261018`, mẫu 500 URL thuộc 15 nhánh. Kiểm tra SHA-256 của raw, tái trích text/encoding/selector/metadata/tables/flags và hash text: **491/491 trang đã parse khớp**, không có lỗi replay. Replay dùng cùng parser nên chứng minh tính nhất quán, không chứng minh trích xuất đúng với giao diện hiển thị.
- Live mới: **30 URL/12 nhánh**, seed 20261020, loại 500 URL của run cũ và 60 URL lịch sử đã biết. Ba nhánh hiếm đã hết URL mới sau loại lịch sử. **30/30 HTTP 200, 30/30 parse**, không lỗi fetch/parser. **23/30 (76,7%)** không có cờ parser; **7/30 (23,3%)** cần review: 3 short text, 2 đánh số giảm dần, 2 phân trang. Thiếu ngày 1/30; cả 30 có cờ tác giả, 20 có cờ title/body.
- Live dùng transport chung: một worker, nghỉ tối thiểu 1,5 giây/request, timeout 8/20 giây, tối đa 2 attempts, kiểm tra robots. Lượt trong sandbox lỗi socket `WinError 10013` tại robots; lượt ngoài sandbox sau cấp quyền thành công. Không dùng kết quả sandbox để suy luận domain bị chặn.
- Lịch sử chưa đầy đủ; mẫu mới chỉ chắc chắn không trùng các URL đã biết. Mẫu phân tầng nhỏ không cho phép suy rộng tỷ lệ sang toàn domain.

| Chỉ số run cũ | Kết quả |
|---|---:|
| URL được chọn/hoàn tất | 500/500 |
| Fetch + parse được | 491/500 (98,2%) |
| Không cờ parser | 360/491 (73,3%); 360/500 (72,0%) |
| Có cờ parser | 131/491 (26,7%) |
| Fetch không thành công | 9: 8 robots không xác minh được, 1 HTTP 404 |
| Thiếu ngày | 20/491 (4,1%) |
| Cờ thiếu tác giả | 491/491 |
| Cờ title/body | 291/491 |

| Template run cũ | Parse được | Không cờ parser |
|---|---:|---:|
| endtext | 358 | 255 (71,2%) |
| detailc | 113 | 86 (76,1%) |
| conmain | 20 | 19 (95,0%) |

Các tỷ lệ trên là thống kê của mẫu; `conmain` ít mẫu nên chưa thể kết luận template này tốt nhất.

## Phát hiện ưu tiên

### P1 — Thứ tự DOM tĩnh có thể khác thứ tự bài được JavaScript hiển thị

`scripts/cnkang.py:103` lấy text theo DOM. HTML của ID **1901295** (`/nkwk/tnbsb/393299.html`) và **1780432** (`/jibing/shengjingxing/401573.html`) đặt khối `jbk` theo ID giảm dần. Bài thứ hai có `jbk12` đến `jbk0`, tiếp theo gọi `formattext(13)`. Text hiện tại bắt đầu bằng mục 3 rồi 2, 1; phần giới thiệu nằm cuối. Đây là bằng chứng cần đối chiếu hàm JavaScript/thứ tự sau render, không đủ để tự động đảo toàn bộ đoạn.

Run cũ có **65 trang** bị cờ đánh số giảm dần, nhưng cờ này dựa vào số ở đầu dòng nên không bảo đảm bắt mọi bài có cơ chế `jbk`/`formattext`. Quét raw phát hiện **81 trang** có chuỗi `formattext(`, trong đó **56 trang không có cờ parser**; **44 trang trong nhóm sạch này có ID khối `jbk` giảm dần**. Đây là nhóm cần kiểm tra thứ tự, chưa phải 44 lỗi thứ tự đã được xác nhận bằng render. Danh sách ID/URL nằm ở `javascript_order_candidates.jsonl`. Cần xác minh quy tắc JavaScript trên mẫu HTML và lưu thứ tự trước/sau; bổ sung QC cấu trúc trước khi cho các trang này vào corpus accepted. Không sửa nội dung hoặc suy đoán thứ tự theo ý nghĩa y khoa.

### P1 — Bài phân trang chưa đầy đủ

Run cũ có **7 trang** có liên kết trang tiếp; live mới có **2 trang**. Ví dụ ID **1816933**, `/myjk/201109/84408.html`, chứa `下一页` trỏ tới `84408_2.html#t`; ID **1994369**, `/xinwen/201909/1620283.html`, trỏ tới `1620283_2.html`. Parser giữ trang đầu và gắn cờ, chưa ghép các trang. Cách này tránh nhập nhầm bài liên quan nhưng chưa đáp ứng tiêu chí toàn văn. Cần giữ review cho đến khi xác minh cùng bài và ghép trang có thứ tự, loại nội dung lặp.

### P2 — Cờ thiếu tác giả không đồng nghĩa nguồn không có tác giả

`scripts/cnkang.py:339` chỉ đọc `meta[name=author]`. ID **1600264**, `/dise/575/491103.html`, có ngay đầu nội dung tên bác sĩ, chức danh và bệnh viện nhưng vẫn bị `AUTHOR_UNAVAILABLE_REVIEW`. Do đó tỷ lệ 100% là tỷ lệ không tìm thấy meta theo quy tắc hiện tại. Cần tách tác giả khỏi byline/DOM có bằng chứng, giữ nguyên raw và ghi mức xác minh; không suy ra mọi bài vô danh.

### P2 — Cờ title/body có false positive rõ ràng

`scripts/cnkang.py:345` gom một chuỗi chữ Hán liên tục trong tiêu đề thành nguyên cụm rồi tìm nguyên văn trong body. ID **1600264** có tiêu đề về nghe âm thanh để nhận biết ù tai và body cùng chủ đề, nhưng vẫn bị cờ vì không lặp nguyên câu tiêu đề. Không được diễn giải **291/491** thành tỷ lệ bài sai chủ đề. Nên dùng tín hiệu từ vựng phù hợp tiếng Trung và tập mẫu gán nhãn thủ công trước khi dùng cờ này làm gate.

### P2 — Parser sạch chưa đảm bảo nguồn phù hợp corpus

- Run cũ: **55 short text**, **5 PUA formatting**, **2 encoding uncertain**, **1 corrupt text**, **2 có dấu hiệu bị cắt**, **2 lặp đoạn**; các cờ có thể chồng nhau.
- **14** trang có cờ phát biểu quảng bá và **10** trang có cờ trải nghiệm cá nhân; **17 trang không có cờ parser vẫn có ít nhất một trong hai cờ nguồn này**. `quality_status` hiện dựa vào parser flags nên các trang đó vẫn có thể accepted ở tầng parser.
- ID **1699399**, `/fuke/duanxiaobiyun/12615.html`, lặp tên sản phẩm và lời mời gọi mang tính quảng bá; không có cờ `PROMOTIONAL_CLAIM_REVIEW` vì regex chỉ bắt một số từ khóa hẹp. Đây là giới hạn recall của heuristic quảng bá, không phải kết luận về hiệu quả thuốc.
- **417/491** trang có ít nhất một ngày metadata từ 2000–2015. Metadata này chưa được xác minh là ngày xuất bản/cập nhật; vẫn cho thấy cần lưu provenance và ngày để đánh giá độ phù hợp theo mục đích sử dụng.

Nên giữ riêng ba kết quả: truy cập thành công, parser trích xuất đạt yêu cầu, nguồn phù hợp cho corpus. Hiện tại không có ground truth để tính precision/recall trích xuất hay độ đúng chuyên môn.

## Artifact và tái lập

- Script review cũ được chuyển vào `runs/cnkang_experiments_20261020/consolidation_backup/legacy_files/review_cnkang_quality.py` để lưu lịch sử; phần thí nghiệm hiện chỉ dùng `notebooks/check_cnkang.com.ipynb`, là file đã ignore.
- Offline mới: `runs/cnkang_quality_review_20261020/offline_summary.json`, `replay.jsonl`, `manual_review_candidates.jsonl`, `javascript_order_candidates.jsonl`.
- Live thành công: `runs/cnkang_quality_review_20261020_network/live/summary.json`, `results.jsonl`, `results.parquet`, `review.csv`, `summary_by_branch.csv`, `review_report.md`, raw và checkpoint.
- Lượt sandbox thất bại được giữ ở `runs/cnkang_quality_review_20261020/live/`; không trộn với lượt live thành công.

Không thay đổi parser hay các notebook trong lượt review này. Nên xử lý P1 về thứ tự và phân trang trước khi mở rộng crawl; sau đó cải thiện metadata và hiệu chuẩn QC trên tập kiểm tra có nhãn.
