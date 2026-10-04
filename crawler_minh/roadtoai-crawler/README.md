# Crawl corpus Road to AI theo id

3 người crawl song song 1,5 triệu id đầu tiên của `links_corpus.parquet`. Mỗi người nhận một đợt 500.000 id liên tiếp, không trùng nhau. Dừng giữa chừng rồi chạy tiếp được, cuối cùng gộp kết quả của cả nhóm.

| File | Việc |
|---|---|
| `try_crawl.py` | chạy thử một mình trên khoảng 100 id, xuất bảng CSV để xem kết quả |
| `make_batches.py` | chia corpus thành các đợt, thống kê domain, phân công |
| `crawl.py` | crawl một đợt |
| `merge.py` | gộp kết quả của cả nhóm, báo độ phủ, xuất danh sách id cần thử lại |
| `export_json.py` | xuất kết quả crawl ra file JSON đọc được bằng trình soạn thảo |
| `reextract.py` | trích lại văn bản từ HTML đã lưu, không cần crawl lại |
| `quality.py` | báo cáo chất lượng văn bản theo từng site |
| `extract.py` | cách trích văn bản, gồm quy tắc riêng cho từng site |
| `tests/selftest.py` | kiểm tra toàn bộ quy trình trên web giả lập, không cần mạng |

| Đợt | id | Người chạy |
|---|---|---|
| 0 | 500.000 id đầu tiên | Minh |
| 1 | 500.000 id tiếp theo | An |
| 2 | 500.000 id tiếp theo | Binh |

Khoảng id chính xác của từng đợt nằm trong `batches/manifest.csv`.

## Chạy thử một mình (khoảng 100 id)

Không cần chia đợt hay GitHub. Cài thư viện, đặt `links_corpus.parquet` vào `data/`, rồi chạy:

```
pip install -r requirements.txt
python try_crawl.py
```

- Mặc định script lấy ngẫu nhiên 100 id trải khắp corpus, để thấy được nhiều site khác nhau. Muốn lấy 100 id đầu tiên theo thứ tự id (bắt đầu từ 583): `python try_crawl.py --pick first`.
- Đổi số lượng bằng `--n 200`. Các tham số của `crawl.py` vẫn dùng được, ví dụ `--interval 2`.
- Kết quả gồm:
  - `json_out/try_random_100.json`: nội dung đầy đủ của từng URL (tiêu đề, toàn văn, trạng thái), mở được bằng VS Code;
  - `try_random_100_report.csv`: bảng tóm tắt mở bằng Excel (trạng thái, ngôn ngữ, độ dài, tiêu đề, 300 ký tự đầu);
  - các file gốc trong `crawl_out/try_random_100/`.
- Thường mất từ vài chục giây đến vài phút. Chạy lại cùng lệnh thì script chạy tiếp phần còn dở; muốn chạy lại từ đầu thì xóa thư mục `crawl_out/try_...` tương ứng.

## Quy trình qua GitHub

### Người tạo repo (làm một lần)

1. Tạo một repo **private** trên GitHub, ví dụ `roadtoai-crawler`. Vào Settings → Collaborators để mời 2 bạn còn lại.
2. Giải nén bộ code, đặt `links_corpus.parquet` vào thư mục `data/`, rồi chạy:
   ```
   pip install -r requirements.txt
   python tests/selftest.py
   python make_batches.py --people Minh,An,Binh --max-batches 3
   git init
   git add .
   git commit -m "Crawler va 3 dot dau"
   git branch -M main
   git remote add origin https://github.com/<tai-khoan>/roadtoai-crawler.git
   git push -u origin main
   ```
3. Bắt đầu crawl đợt của mình:
   ```
   python crawl.py --batch 0 --worker Minh
   ```

File `.gitignore` đã loại `data/`, `crawl_out/`, `json_out/` và `merged/`, nên corpus và kết quả crawl không bị đẩy lên GitHub. Thư mục `batches/` (3 file nhỏ) thì được đẩy lên, nên 2 bạn còn lại không cần tải corpus hay chạy lại bước chia đợt.

### Hai bạn còn lại

```
git clone https://github.com/<tai-khoan>/roadtoai-crawler.git
cd roadtoai-crawler
pip install -r requirements.txt
python tests/selftest.py
python crawl.py --batch 1 --worker An
```

Bạn thứ ba đổi dòng cuối thành `python crawl.py --batch 2 --worker Binh`.

Khi code trên GitHub được cập nhật: chạy `git pull`, rồi chạy lại đúng lệnh crawl cũ. Script tự chạy tiếp từ chỗ đã dừng.

## Chạy crawl

- `tests/selftest.py` mất khoảng 1 phút. Thấy dòng `SELFTEST PASSED` là máy đã sẵn sàng.
- Kết quả ghi vào `crawl_out/batch_XX/`, mỗi file `part-*.parquet` chứa 1.000 dòng. Khi đợt chạy xong, bản JSON được ghi vào `json_out/` (xem mục "Xuất JSON").
- **Dừng:** nhấn Ctrl+C. Phần đã crawl được lưu lại.
- **Chạy tiếp:** gõ lại đúng lệnh cũ. Các id đã có kết quả tự được bỏ qua.
- Cứ 30 giây script in tiến độ (số trang, tốc độ, tỷ lệ ok, domain còn nhiều URL nhất) và ghi vào `progress-<tên>.json`.
- Muốn chạy thử nhanh trước: thêm `--limit 2000`.
- Nên ghi email nhóm vào user agent để quản trị site liên hệ được khi cần:
  ```
  python crawl.py --batch 1 --worker An --user-agent "Mozilla/5.0 (compatible; RoadToAI-ResearchBot/1.0; +mailto:email-nhom@gmail.com)"
  ```

**Giữ máy chạy liên tục**
- Windows: Settings → System → Power, đặt Sleep thành Never khi cắm sạc, và không đóng cửa sổ terminal.
- macOS: `caffeinate -i python crawl.py --batch 1 --worker An`
- Linux hoặc server: chạy trong `tmux` hoặc `screen`.

## Xuất JSON

Khi một lượt crawl chạy hết phần việc của nó, script tự ghi thêm một bản JSON vào `json_out/`, mỗi id một bản ghi:

```json
{
  "id": 82491,
  "url": "https://...",
  "status": "ok",
  "lang": "vi",
  "n_chars": 3573,
  "title": "...",
  "text": "toàn bộ nội dung chính của trang",
  "final_url": "...", "domain": "...", "http_status": 200, "content_type": "...",
  "error": "", "extractor": "trafilatura", "published_at": "2023-12-06", "text_sha256": "...",
  "fetched_at": "...", "worker": "...", "batch": 0
}
```

- Đợt nhỏ ra một file, ví dụ `json_out/batch_00.json`. Đợt lớn được chia thành các file 10.000 bản ghi: `json_out/batch_00-0001.json`, `batch_00-0002.json`… Một đợt 500.000 id cho khoảng 50 file, tổng cỡ 1,5–2 GB.
- Nếu dừng giữa chừng bằng Ctrl+C thì chưa có JSON. Muốn xuất phần đã crawl: `python export_json.py --input crawl_out/batch_00`.
- Nếu một id được crawl nhiều lần, JSON giữ kết quả tốt nhất. Sau khi chạy `--retry-failed`, JSON được ghi lại.
- Không muốn tạo JSON (để tiết kiệm ổ đĩa): thêm `--no-json` vào lệnh `crawl.py`.
- File parquet trong `crawl_out/` vẫn là dữ liệu gốc: script dùng nó để chạy tiếp và để gộp kết quả, nên đừng xóa. Khi gửi kết quả cho nhóm, chỉ cần gửi `crawl_out/batch_XX`.

Tùy chọn của `export_json.py`:

| Tham số | Ý nghĩa |
|---|---|
| `--input` | thư mục kết quả crawl hoặc file parquet, ví dụ `crawl_out/batch_00`, `merged/docs.parquet` |
| `--only-ok` | chỉ các trang lấy được văn bản |
| `--rows-per-file` | số bản ghi mỗi file (mặc định 10.000) |
| `--jsonl` | ghi một file `.jsonl`, mỗi dòng một bản ghi; tiện khi xử lý bằng code |
| `--with-html` | kèm cả HTML đã lưu (file lớn hơn nhiều) |
| `--compact` | không thụt dòng, file nhỏ hơn |

## Thử lại lỗi tạm thời

Khi đợt đã chạy xong, đợi vài giờ rồi chạy:

```
python crawl.py --batch 1 --worker An --retry-failed
```

Lệnh này chỉ crawl lại các id bị lỗi tạm thời (timeout, mất kết nối, lỗi 5xx, bị giới hạn tốc độ, domain bị tạm bỏ qua…).

## Gửi kết quả và gộp

Kết quả crawl không đưa lên GitHub vì quá lớn.

1. Mỗi người nén thư mục `crawl_out/batch_XX` của mình và đẩy lên Drive chung. Có thể đẩy dần mỗi ngày.
2. Người gộp tải tất cả về, giải nén vào `crawl_out/` (giữ nguyên tên thư mục `batch_XX`), rồi chạy:
   ```
   python merge.py --inputs crawl_out --out merged
   ```
3. Kết quả trong `merged/`:
   - `docs.parquet`: các trang lấy được văn bản, gồm `id, url, final_url, domain, title, text, lang, n_chars, extractor, published_at, text_sha256, canonical_id, dup_count, batch, worker, fetched_at`. Đây là đầu vào cho bước chia đoạn.
   - `duplicates.parquet`: các nhóm trang trùng nội dung, mỗi nhóm một dòng (xem mục "Chất lượng văn bản").
   - `status.parquet`: trạng thái của mọi id đã thử.
   - `report.txt`: độ phủ theo đợt, phân bố trạng thái, ngôn ngữ, cách trích, trang trùng, site có nhiều văn bản lặp, các domain lỗi nhiều nhất.
   - `retry_ids_bXX.txt`: id bị lỗi tạm thời của từng đợt.
   - `missing_ids_bXX.txt`: id chưa ai crawl.

   Nếu một id được crawl nhiều lần, script giữ kết quả tốt nhất.

Crawl lại một danh sách id cụ thể, ví dụ các id còn thiếu của đợt 1:

```
python crawl.py --batch 1 --worker An --ids-file merged/missing_ids_b01.txt
```

## Chất lượng văn bản

**Cách trích văn bản** (cột `extractor` ghi lại cách đã dùng cho từng trang):

| `extractor` | Ý nghĩa |
|---|---|
| `site:120ask` | quy tắc riêng cho trang hỏi đáp 120ask.com: lấy tiêu đề, câu hỏi, mọi câu trả lời của bác sĩ và phần hỏi thêm |
| `trafilatura` | trích nội dung chính bằng trafilatura ở chế độ mặc định |
| `trafilatura-recall` | chế độ mặc định ra dưới 200 ký tự, nên dùng chế độ lấy rộng hơn; nên kiểm tra các trang này |
| `html2txt` | không trích được nội dung chính, lấy toàn bộ chữ trên trang (thường lẫn menu) |
| `pypdf`, `plain` | file PDF, file văn bản thuần |

Trang trích bằng quy tắc riêng được tính là `ok` từ 20 ký tự; các trang khác cần `--min-chars` ký tự (mặc định 100).

**Trích lại không cần crawl lại.** File crawl có lưu HTML, nên khi `extract.py` được cải tiến, chạy:

```
python reextract.py --input crawl_out
```

Script ghi đè các file trong `crawl_out/` với văn bản mới (và bổ sung cột mới cho file do bản cũ tạo ra). Nên chạy khi không có lượt crawl nào đang ghi vào thư mục đó. Sau đó chạy lại `export_json.py` và `merge.py`.

**Trang trùng nội dung.** `merge.py` so văn bản sau khi bỏ khác biệt về chữ hoa/thường và khoảng trắng:
- `canonical_id`: id nhỏ nhất trong nhóm trang cùng nội dung (bằng chính `id` nếu trang không trùng với trang nào).
- `dup_count`: số trang trong nhóm (1 nếu không trùng).
- `duplicates.parquet`: mỗi nhóm một dòng, gồm `canonical_id, size, doc_ids, domains, final_url, n_chars, preview`.
- `text_sha256`: SHA-256 của `text` nguyên dạng.

Cách dùng: chỉ lập chỉ mục các dòng có `id == canonical_id`; khi nộp bài, tra `duplicates.parquet` để lấy mọi id cùng nội dung. Nhóm lớn gồm nhiều trang giống hệt nhau trên một site thường là trang báo lỗi hoặc trang giữ chỗ, nên loại khỏi chỉ mục.

**Site có nhiều văn bản lặp.** Báo cáo của `merge.py` liệt kê các site mà từ 20% văn bản là những dòng lặp lại trên nhiều trang (menu, hộp thoại, danh sách bài liên quan). Xem riêng bằng:

```
python quality.py --docs merged/docs.parquet
```

Site nào bị nêu tên thì nhiều khả năng cần thêm quy tắc riêng trong `extract.py` (danh sách `SITE_RULES`). Hãy xuất vài trang của site đó kèm HTML (`python export_json.py --input crawl_out/batch_00 --with-html`) để viết quy tắc.

**Cả nhóm dùng cùng một phiên bản code.** Văn bản phụ thuộc vào `extract.py`. Ai còn dữ liệu crawl bằng bản cũ thì chạy `reextract.py` một lần.

## Domain nằm ở hai đợt

Cuối output của `make_batches.py` có danh sách domain nằm ở nhiều đợt (cột `batches` trong `batches/domains.csv`). Khi hai người cùng crawl, site đó nhận request từ cả hai. Với domain lớn trong danh sách này, cả nhóm thống nhất để một người crawl trước. Người kia thêm `--skip-domains ten-domain` vào lệnh của mình, rồi crawl phần đó sau bằng `--domains ten-domain`.

## Muốn crawl thêm sau này

Người tạo repo chạy lại `make_batches.py` không có `--max-batches`, với cùng các tham số còn lại. Ranh giới của 3 đợt đầu giữ nguyên, các đợt 3, 4, 5… xuất hiện thêm trong `batches/`. Sau đó commit và push để cả nhóm `git pull`.

## Ý nghĩa cột `status`

| status | Ý nghĩa | Thử lại bằng `--retry-failed`? |
|---|---|---|
| `ok` | lấy được văn bản | |
| `empty_text` | tải được nhưng văn bản quá ngắn (dưới 100 ký tự, hoặc dưới 20 với trang có quy tắc riêng) | không |
| `not_found` | lỗi 404 hoặc 410 | không |
| `blocked` | lỗi 401, 403 hoặc 451, site chặn truy cập | không |
| `robots_disallowed` | robots.txt không cho phép | không |
| `skipped_type` | không phải HTML, PDF hay text (ảnh, video…) | không |
| `too_large` | lớn hơn `--max-mb` | không |
| `extract_error` | tải được nhưng trích văn bản bị lỗi | không |
| `bad_url`, `http_4xx`, `http_other` | URL hỏng, lỗi 4xx khác, chuyển hướng quá nhiều | không |
| `timeout`, `conn_error`, `dns_error`, `ssl_error`, `http_5xx`, `rate_limited`, `error` | lỗi mạng, lỗi phía site hoặc lỗi không xác định | có |
| `robots_unreachable` | không đọc được robots.txt sau 3 vòng thử, mỗi vòng cách nhau 60 giây (lý do ghi ở cột `error`) | có |
| `domain_skipped` | domain lỗi liên tiếp nên tạm bỏ qua | có |

Trang PDF được trích văn bản bằng pypdf. Với trang HTML, script lưu thêm bản HTML đã bỏ style và script (cột `html` trong các file `part-*.parquet`), để sau này trích lại bằng `reextract.py` mà không phải crawl lại. Các thẻ script chứa dữ liệu (JSON-LD, JSON) được giữ lại vì một số trang đặt nội dung và ngày đăng ở đó. Trang không trích được chữ nào thì được lưu nguyên HTML để tìm nguyên nhân.

## Tham số hay dùng

| Tham số | Mặc định | Ghi chú |
|---|---|---|
| `--interval` | 1.0 | số giây giữa hai request tới cùng một domain |
| `--per-domain` | 2 | số request song song tối đa tới một domain |
| `--concurrency` | 64 | tổng số request song song |
| `--timeout` | 25 | giây |
| `--retries` | 2 | số lần thử lại trong cùng một lượt chạy |
| `--domains`, `--skip-domains` | | chỉ crawl, hoặc tạm bỏ qua, các domain liệt kê (cách nhau bằng dấu phẩy) |
| `--robots-rounds`, `--robots-wait` | 3, 60 | khi robots.txt của một site không trả lời, tạm dừng site đó 60 giây rồi đọc lại, tối đa 3 vòng |
| `--no-html` | tắt | không lưu HTML, tiết kiệm ổ đĩa |
| `--no-json` | tắt | không ghi bản JSON khi crawl xong |
| `--extract-workers` | số CPU − 1 | giảm nếu máy nóng hoặc chậm |
| `--strict-ssl` | tắt | mặc định, khi chứng chỉ TLS của site lỗi, script tải lại mà không kiểm tra chứng chỉ và ghi `tls not verified` vào cột `error`; bật cờ này để không làm vậy |

Xem đầy đủ: `python crawl.py --help`

## Crawl lịch sự

- robots.txt luôn được tôn trọng, kể cả `Crawl-delay`; không có tùy chọn tắt.
- Không giảm `--interval` dưới 1 giây với site nhỏ. Site trả 429 hoặc 503 thì script tự giảm tốc.
- Site chủ động chặn bot (nhiều `blocked`): ghi lại, không tìm cách vượt, báo cả nhóm để tìm nguồn thay thế.
- Ghi lại thời gian crawl và cách lấy dữ liệu để đưa vào working notes.

## Ước lượng thời gian và dung lượng

- Thời gian của mỗi đợt thường do domain lớn nhất trong đợt quyết định. Ví dụ 500.000 URL cùng một domain, ở 1 request/giây, mất khoảng 5,8 ngày. Đợt gồm nhiều domain nhỏ có thể xong trong vài giờ đến một ngày. Bảng top domain mà `make_batches.py` in ra cho biết trước đợt nào sẽ lâu. Sau khoảng một giờ chạy, xem dòng tiến độ để ước lượng lại.
- Dung lượng: sau 10.000 trang đầu, xem kích thước thư mục `crawl_out/batch_XX` rồi nhân 50 để ra cả đợt. Nếu ổ đĩa không đủ, chạy tiếp với `--no-html`.

## Xử lý sự cố

- `SELFTEST FAILED`: gửi toàn bộ output cho người tạo repo.
- `input not found`: thiếu file `batches/batch_XX.parquet`. Chạy `git pull`, hoặc kiểm tra lại số `--batch`.
- Máy tắt đột ngột: chạy lại lệnh cũ. File đang ghi dở không bao giờ được tính, vì script ghi ra file tạm rồi mới đổi tên.
- Mọi domain cùng lúc báo `dns_error` hoặc `ssl_error`: kiểm tra mạng, VPN hoặc DNS của máy.
