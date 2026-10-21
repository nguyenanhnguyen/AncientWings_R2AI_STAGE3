# Cnkang F1: khôi phục formattext và loại pager — 20/10/2026

**Kết luận: F1 đạt kiểm chứng trên dữ liệu nhận được; lượt kiểm 1.000 URL chưa hoàn tất.**
Đã dừng đúng một pass ở 615/1.000 URL vì 3 lỗi fetch liên tiếp, không retry-run:
611 trang nhận được/parse được, 4 record lỗi, 385 URL chưa kiểm tra. Không suy rộng kết quả này thành đã kiểm đủ 1.000 URL.

## Phạm vi bản sửa

Parser production scripts/cnkang.py tăng từ cnkang-v6-spec-2 lên cnkang-v6-spec-3.

- Khôi phục kết quả ghép innerHTML của formattext theo quy tắc JS đã ghim SHA-256; chỉ nhận cấu trúc endText, nguồn script chính xác, một lời gọi, jkpl duy nhất/rỗng và các khối jbk cùng cấp có ID hợp lệ.
- Cấu trúc formatter không xác minh được giữ text DOM và chuyển review, không âm thầm accepted.
- Decode nguồn một lần, sửa cây DOM trong bộ nhớ; giữ charset gốc, metadata và các nội dung inline/bảng/tail.
- Chỉ bỏ khối pager có mẫu đã xác minh và mọi liên kết thuộc cùng bài. Giữ liên kết trang tiếp và PAGINATION_REVIEW; chưa ghép phân trang.
- Sidecar lưu source_dom_text/hash, formattext_evidence, pager_removals và cleaning_actions. Audit tái dựng/kiểm cả các trường này và parser version.
- Hai notebook crawler chính và notebook check đã đồng bộ snapshot parser; so với bản trước lượt sửa, payload của domain khác không đổi.

Không thay transport, retry policy, rule tác giả/title-body hoặc gate nguồn. Không chạy Selenium/Node trên từng request; Node chỉ dùng làm oracle trong kiểm chứng offline.

## Kiểm thử trước live

Lệnh:

    .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p '*cnkang*' -v

**37/37 pass**, 57,711 giây. Gồm 26 test cũ và 11 test production mới trong test_cnkang_f1.py. Bốn fixture HTML thật được giữ SHA-256: 1869305, 1733228, 1780432 và 1816933; JS gốc cũng được ghim hash. Test mới kiểm thứ tự, charset gốc, inline/bảng/tail, ID thiếu/trùng/lồng/sai phạm vi, nguồn/lời gọi không hợp lệ, pager giả, giữ liên kết trang tiếp, và audit phát hiện sửa provenance.

## Mẫu live đã chốt

- Nguồn links_corpus_vi_en_zh.parquet: 40.043 URL detail canonical của cnkang.
- Chọn đúng **1.000 URL duy nhất**, seed 2026102003, không thay URL lỗi bằng URL khác.
- Loại **1.171 URL** lịch sử/biến thể cùng bài, tổng hợp từ 125 nguồn local gồm manifest, output, trang tiếp đã tải và notebook cũ; không có lỗi đọc lịch sử.
- Mẫu không trùng danh sách đã biết; lịch sử cũ thiếu manifest vẫn chưa thể bảo đảm hoàn toàn chưa từng được thử ở mọi session.
- Phân bố: dise 202, myjk 191, jibing 181, nkwk 150, fuke 107, nxjk 57, dzjk 34, nrjk 33, yxzs 21, xinwen 14, cm 10. Bốn nhánh còn lại không còn mẫu mới đủ điều kiện sau loại lịch sử.
- Một worker, nghỉ tối thiểu 1,5 giây/request, connect/read timeout 8/20 giây, tối đa 2 attempts theo transport hiện có.
- Một pass; dừng khi parser exception, 403/429/challenge, robots không xác minh được hoặc ba fetch lỗi liên tiếp. Không tự retry-run hay sửa thêm để tối ưu số accepted.

## Artifact

- File check duy nhất: notebooks/check_cnkang.com.ipynb, gitignored; phần F1 production giữ config, code kiểm chứng và output.
- Run: runs/cnkang_f1_1000_20261020/; baseline/snapshot được giữ trước crawl.
- Manifest bất biến, known_prior_urls.jsonl/history_scope.json, raw/checkpoint, summary, pass_outcome.json.
- Sau lượt chạy: baseline_comparison.jsonl, oracle_results.jsonl, f1_review_summary.json và audit_errors.json.

## Kết quả live và lý do dừng

| Chỉ số | Kết quả |
|---|---:|
| Chọn trước lượt chạy | 1.000 URL |
| Record đã xử lý | 615 |
| HTTP/HTML nhận được và parse thành công | 611 |
| Parser exception | 0 |
| Fetch/ghi trạng thái không thành công | 4 |
| URL chưa kiểm tra | 385 |
| Không cờ parser | 492/611 (80,5%) |
| Có cờ parser | 119/611 (19,5%) |

Ba record cuối liên tiếp lỗi nên pass dừng, giữ nguyên mẫu còn lại:

| ID | Bằng chứng lỗi |
|---|---|
| 1853035 | Lỗi local trước đó: Windows WinError 5 khi replace cnkang_transport_state.json.tmp sang state JSON; record lỗi vẫn được lưu. |
| 1829198 | HTTPS ConnectionResetError 10054; fallback HTTP không xác minh được robots, không tiếp tục lấy trang HTTP. |
| 1889799 | HTTPS NameResolutionError/getaddrinfo 11001; fallback HTTP robots không xác minh được. |
| 3436985 | Hai attempt HTTPS đều NameResolutionError/getaddrinfo 11001. Đây là lỗi thứ ba liên tiếp làm dừng pass. |

Không có HTTP 403/429 hay challenge được ghi nhận trong pass này; các lỗi DNS/reset không chứng minh website chặn IP. Không đổi DNS, đổi IP, né robots hoặc chạy lượt thử lại sau khi dừng.

Log của request tại ID 1889799 ghi elapsed_seconds khoảng 8.446 giây dù cấu hình timeout 8/20 giây. Không đủ bằng chứng để tách riêng thời gian resolver, hệ điều hành bị treo/tạm dừng hoặc điều kiện mạng khác; vì vậy không dùng tổng wall time này để suy luận tốc độ/quota website. Đây cũng là hạn chế runtime cần xử lý riêng nếu muốn deadline toàn request/bài chặt hơn, ngoài phạm vi F1 hiện tại.

## Review cùng raw: baseline cũ so với bản sửa

So sánh trên đúng **611 raw đã tải**, với baseline v2 đóng băng trước khi sửa:

| Kiểm chứng | Kết quả |
|---|---:|
| Raw SHA-256 + audit tái trích mới | 611/611 khớp |
| Thay đổi encoding/ngày/title ngoài dự kiến | 0 |
| Mất/thêm ký tự ngoài pager được chứng minh | 0/611 |
| Formatter được áp dụng | 122 trang |
| Đối chiếu với hàm JS gốc, VM DOM tối thiểu | 122/122 khớp |
| Trang thực sự đổi thứ tự text | 115 |
| Formatter áp dụng nhưng text vốn tương đương | 7 |
| Trang loại pager có bằng chứng | 1 |
| Tổng trang đổi text | 116 |
| Trong nhóm đổi text, trước đó không có cờ parser | 81 |
| Không cờ parser: baseline → F1 | 469 → 492 |
| Cờ đánh số giảm dần: baseline → F1 | 71 → 47 |

Tổng ký tự sau bỏ khoảng trắng: **531.384 → 531.375**; chênh 9 ký tự chính là pager đã xác minh, không phải thân bài. Cả 611 record giữ nguyên tập ký tự có số lần xuất hiện, sau khi trừ đúng pager. Chỉ số này được dùng cùng oracle JS, audit và đọc mẫu; không đứng một mình như ground truth.

Ví dụ đã đọc lại:

- ID **1756519**, /jibing/jsycs/333909.html: baseline mở đầu bằng câu kết luận; bản sửa đưa phần giới thiệu về đầu và câu kết xuống cuối. ID khối 5→0 được tái tạo 0→5 theo JS.
- ID **1744947**, /jibing/fmxzey/206180.html: baseline bắt đầu bằng phần cuối; bản sửa phục hồi trình tự phần giới thiệu, nội dung và câu hỏi tiếp theo, khối 7→0 thành 0→7. Cả hai ví dụ đều vốn không có cờ parser.
- ID **1851609**, /myjk/mm/fqzj/200905/124725.html: chỉ xóa text pager gồm số trang và nút tiếp, **969 → 960 ký tự**; next URL 124725_2.html và PAGINATION_REVIEW vẫn còn. Không tải/ghép trang 2 trong F1.

## Chưa được giải quyết

- **385 URL chưa kiểm tra**, nên chưa nghiệm thu mục tiêu đủ 1.000 URL. Không lấy URL khác để bù hoặc chạy tiếp sau lỗi.
- Còn 4 trang có PAGINATION_REVIEW; F1 chỉ bỏ pager, chưa tạo toàn văn từ chuỗi trang.
- ID **1690503** là unknown layout: fallback vẫn chứa pager, được giữ UNKNOWN_LAYOUT_REVIEW/TITLE_HEADING_MISSING_REVIEW/PAGINATION_REVIEW, không accepted. Không mở rộng rule xóa sang bố cục chưa xác minh trong lượt này.
- Còn 47 cờ đánh số giảm dần, 57 short text, 8 PUA, 7 lặp đoạn, 2 encoding uncertain. Các nhóm có thể chồng nhau; không tự bỏ cờ để tăng tỷ lệ sạch.
- 611 trang đều có cờ tác giả chưa xác minh; 367 cờ title/body, 17 claim quảng bá và 4 trải nghiệm cá nhân. Những heuristic nguồn chưa được sửa, không diễn giải parser sạch thành dữ liệu đạt chuẩn y khoa/huấn luyện.
- Không có nhãn gold toàn corpus; mẫu dừng sớm là prefix của manifest phân tầng, không phải kết quả đủ cả mẫu hoặc tỷ lệ toàn domain.

**Dừng tại F1 theo yêu cầu:** giữ bản sửa đã pass, giữ toàn bộ bằng chứng và danh sách chưa chạy; không triển khai F2/F3/F4, không sửa transport/DNS/file locking và không chạy thêm vòng kiểm mạng.

## Review sâu phần hơn 600 URL

Phần này chỉ đọc lại artifact/raw đã lưu, không gọi mạng, không sửa parser và không chạy thêm pass. Kết luận: **giữ bản sửa F1**, vì có tác dụng đúng với bằng chứng; **chưa coi 492 trang sạch parser là 492 bài đạt chuẩn nguồn**.

### Tác động thực tế của F1

- 469 trang sạch trước sửa vẫn sạch sau sửa; **không có chuyển clean → review** trong 611 trang này.
- 23 trang chuyển review → clean; 119 trang vẫn review. Mức tăng là **3,76 điểm phần trăm**, từ 76,8% lên 80,5%.
- **81 trang đổi text vốn được QC cũ đánh dấu sạch**. Vì vậy lợi ích của F1 lớn hơn mức tăng 23 trang sạch: nó sửa cả những bài đảo thứ tự mà heuristic cũ không bắt được.
- 122 ca formatter đều có đối chiếu JS; 7 ca không đổi text vì thứ tự/phần có nội dung vốn tương đương. Chỉ một pager thật được xóa, nên bằng chứng live cho pager còn ít; test fixture và việc giữ cờ phân trang bổ sung cho kiểm chứng này.

### Đánh giá 119 trang còn review

| Nhóm | Số trang | Nhận định sau đọc mẫu |
|---|---:|---|
| Short text | 57 | 19 trang dưới 50 ký tự; 7 trang 50–99; 31 trang 100–199. Cần xem chất lượng/thông tin nguồn trước khi giữ. |
| Đánh số giảm dần | 47 | 44 trang chỉ có cờ này. Có false positive do phân cấp danh sách và lượt trả lời mới, không được tự đảo đoạn/xóa cờ toàn cục. |
| PUA formatting | 8 | Một số ký tự là dấu đầu dòng hoặc khoảng đệm font cũ; chưa đủ để gọi cả trang hỏng encoding. |
| Lặp đoạn | 7 | Có trường hợp cùng câu xuất hiện trong các nhóm nội dung khác nhau; chưa đủ bằng chứng để dedup tất cả. |
| Phân trang | 4 | Chưa ghép trang tiếp nên chưa thể coi là toàn văn. |
| Encoding uncertain | 2 | Cùng có PUA; giữ review, chưa có bằng chứng F1 làm thay encoding. |
| Unknown layout/mất heading | 1 | Cùng một bài; fallback còn pager và bị giữ review đúng cách. |

Các nhóm chồng nhau, không cộng số dòng để tính tổng trang.

Bằng chứng đọc mẫu:

- **1716739, 1792421, 1889767:** thân endText trong raw thật chỉ chứa câu/cụm 5, 6 và 7 ký tự sau bỏ khoảng trắng. Raw SHA-256 khớp. Đây là dữ liệu gốc quá ngắn trong ba mẫu này; không phải F1 cắt mất thân bài.
- **1782034:** cờ phát sinh khi đi từ mục 3 của danh sách cha sang mục 1 của danh sách con. **1544618:** mục 3 của một câu trả lời chuyển sang mục 1 ở lượt trả lời tiếp theo. Cả hai giữ trình tự DOM; không có căn cứ đảo nội dung.
- **1759215:** câu bị báo lặp nằm dưới nhiều nhóm phân loại riêng. Không tự xóa chỉ vì chuỗi giống nhau.
- **1844705:** PUA xuất hiện ở vị trí dấu đầu dòng; **1728042** có PUA ở vị trí khoảng đệm. Các quan sát này chỉ giải thích hình thức, không xác minh tính đúng chuyên môn của văn bản.
- **1690503:** unknown layout, thiếu heading và còn pager trong fallback; record không được accepted. Đây là giới hạn bố cục chưa được F1 hỗ trợ.

### Chất lượng nguồn của nhóm parser sạch

**14/492 trang sạch parser** vẫn có ít nhất một cờ claim quảng bá/trải nghiệm cá nhân. Đọc mẫu **1740065** thấy văn phong chào mời và lời hứa kết quả; cần gate nguồn trước khi dùng. Ngược lại, có mẫu như **1516530** bị regex bắt chỉ vì chứa từ tương ứng với “điều trị dứt điểm”; bản thân từ khóa chưa chứng minh đó là quảng cáo. Do đó giữ tín hiệu để review, không dùng mọi match làm lệnh loại tự động.

Cờ AUTHOR_UNAVAILABLE_REVIEW trên 611/611 trang phản ánh thiếu meta author theo bộ đọc hiện tại. Ví dụ **1544618** có tên bệnh viện/người trả lời trong body; không thể diễn giải 611 cờ thành 611 bài không có thông tin người viết. Cờ title/body 367 trang cũng dùng so nguyên cụm chữ Hán: **1782034** có title và body cùng chủ đề nhưng vẫn bị cờ. Tỷ lệ này không phải tỷ lệ sai chủ đề đã xác nhận.

Theo template: endtext 456 trang/94 review; detailc 141/23; conmain 13/1; unknown 1/1. Mẫu conmain quá nhỏ để xếp hạng chất lượng template.

### Đánh giá và thứ tự ưu tiên sau review

1. F1 đạt trong phạm vi rule đã kiểm chứng; không cần mở thêm vòng sửa F1 chỉ để tăng số sạch.
2. Chất lượng dữ liệu còn cần xử lý theo nhóm: toàn văn cho 4 bài phân trang, cấu trúc danh sách/lượt trả lời cho các cờ đánh số, và quyết định giữ/review bài quá ngắn.
3. Metadata và gate nguồn cần hiệu chuẩn riêng trước khi xuất tập dữ liệu có yêu cầu nguồn chặt; không hard-drop toàn domain theo cờ meta author hay nguyên cụm tiêu đề.
4. Độ ổn định crawl chưa đạt mục tiêu kiểm đủ 1.000 URL: 3 lỗi kết nối/DNS cuối và 1 lỗi ghi state local phải được tách khỏi lỗi parser khi đánh giá vận hành.

Đây là review chỉ số toàn bộ 611 record kết hợp đọc mẫu có chủ đích ở các nhóm rủi ro, không phải 611 nhãn đánh giá thủ công độc lập hoặc chứng nhận y khoa. Không triển khai thêm các ưu tiên trên trong lượt review này.
