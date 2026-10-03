# Crawl thử 1.000 ID ViBioMIR: 583–1582

## Phạm vi đã chốt

- Dataset: `AIGuruTinix/ViBioMIR`, file `data/links_corpus.parquet`.
- Điều kiện: **`583 <= id < 1583`**, đúng **1.000 ID**, không thiếu ID nào trong khoảng.
- Gồm 999 URL `bachmai.gov.vn` và 1 URL `special.vietnamplus.vn`.
- Chỉ crawl, trích xuất, xuất corpus và đánh giá chất lượng; chưa chunk/index/train.
- Run tải nguồn: **`runs/ids_583_1582`**; corpus sau sửa parser được xuất riêng ở **`runs/ids_583_1582_clean`**.
- Nếu muốn bao gồm cả ID 1583, phải đặt `--id-stop 1584 --size 1001` và dùng thư mục mới. Không âm thầm lấy 1.001 rồi báo 1.000.

Tài liệu thiết kế đầy đủ, đối chiếu 4 PDF contest và file memory: [`CRAWL_PIPELINE.md`](CRAWL_PIPELINE.md).

**Đã hoàn tất:** xem [`CRAWL_RESULT_1000.md`](CRAWL_RESULT_1000.md). Corpus cuối có 976 tài liệu vượt kiểm tra tự động; 24 ID được giữ trong quarantine để xử lý tiếp.

## Lệnh chạy

Chạy tại thư mục gốc dự án bằng PowerShell:

```powershell
# Chỉ cần thiết lập khi chưa có môi trường.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-crawl.lock.txt

# Kiểm tra parser, ID, lấy mẫu, redirect và retry bằng fixture local.
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

# Chỉ chạy prepare một lần. Không ghi đè run đã tồn tại.
.\.venv\Scripts\python.exe scripts/crawl_corpus.py prepare --source data/links_corpus.parquet --out runs/ids_583_1582 --size 1000 --id-start 583 --id-stop 1583

# Chạy mới hoặc tiếp tục URL chưa có checkpoint.
.\.venv\Scripts\python.exe -u scripts/crawl_corpus.py crawl --out runs/ids_583_1582 --workers 4 --delay 1 --attempts 3

# Tính lại báo cáo, kiểm tra raw/text hash; không cần mạng.
.\.venv\Scripts\python.exe scripts/crawl_corpus.py report --out runs/ids_583_1582
```

Trong workspace hiện tại, **prepare đã hoàn tất**. Lần prepare thực tế có thêm `--reuse-run runs/pilot1000_v2`, tái sử dụng 8 trang đã tải: 583, 667, 821, 873, 1015, 1122, 1146, 1247. Raw được kiểm tra SHA-256 và trích lại bằng parser hiện tại, không copy nguyên text của parser cũ.

### Tiếp tục đúng phiên bản sau ngắt quãng

Run tải nguồn bắt đầu bằng crawler v3; mã nguồn khớp SHA-256 đã lưu tại `runs/ids_583_1582/crawler_snapshot.py`. Trong khi lượt tải đang chạy, code chính được nâng lên v4 để sửa comment Word và thêm khóa tiến trình. Vì vậy **không dùng code v4 để ép resume checkpoint v3**. Dùng snapshot khi cần tiếp tục lượt tải cũ:

```powershell
.\.venv\Scripts\python.exe -u runs/ids_583_1582/crawler_snapshot.py crawl --out runs/ids_583_1582 --workers 4 --delay 1 --attempts 3

# Chỉ thực hiện khi lượt tải đủ 1.000 checkpoint; output mới phải chưa tồn tại.
.\.venv\Scripts\python.exe scripts/crawl_corpus.py reprocess --source-run runs/ids_583_1582 --out runs/ids_583_1582_clean
.\.venv\Scripts\python.exe scripts/audit_corpus.py --out runs/ids_583_1582_clean
.\.venv\Scripts\python.exe scripts/export_corpus.py --out runs/ids_583_1582_clean
```

Reprocess v4 không truy cập mạng; giữ nguyên mẫu ID/URL/raw, bỏ mã Word trong HTML comments, thêm cờ các bài chủ yếu là ảnh. Nếu thư mục clean đã có kết quả, chỉ chạy `report`/`audit_corpus.py`, hoặc chọn tên phiên bản khác khi cần reprocess lần nữa.

4 worker không có nghĩa là 4 request đồng thời đến Bạch Mai: crawler giữ một request cho mỗi registered domain, nghỉ ít nhất 1 giây giữa các request và tuân thủ robots. Thời gian pilot vì vậy bị chi phối bởi một website.

## Xử lý ngắt quãng và các bug đã phát hiện

1. Đã kiểm tra run cũ sau lần ngắt: 1.000 JSON hợp lệ, không có checkpoint hỏng và không còn file `.tmp`. Kết quả cũ được giữ nguyên để đối chiếu.
2. Checkpoint `records/<id>.json` được ghi atomic. Resume chỉ nhận ID/URL khớp sample; record đã hoàn tất được bỏ qua. Nếu bị ngắt giữa lúc tải một URL, URL đó chưa có checkpoint và sẽ tải lại khi resume.
3. Hash `sample.jsonl` không được thay đổi. Nếu sửa script/config, guard sẽ từ chối ghép với run cũ; tạo phiên bản mới bằng `reprocess` thay vì sửa manifest bằng tay.
4. Bug giải mã GB2312 thành Cyrillic đã sửa ở v2 bằng ưu tiên charset khai báo; giữ lại trong crawler tổng quát dù mẫu ID hiện tại gần như chỉ tiếng Việt.
5. Bug bỏ phần mở đầu bài Bạch Mai đã sửa ở v3: kết hợp `div.content-excerpt` với `div.content-editor-post`. Ví dụ ID 1015 bổ sung lại 233 ký tự excerpt, ID 1122 là 348, ID 1247 là 90 từ raw gốc.
6. Trang redirect về trang chủ, text ngắn, body rỗng, thiếu selector hoặc dấu hiệu challenge được đưa vào nhóm cần xem lại/rejected; không xem HTTP 200 là đủ tốt.
7. Bug HTML comment chứa định dạng Word lọt vào corpus đã sửa ở v4. Kiểm tra raw ID 1255: loại 3.826 ký tự mã Office, giữ văn bản bài; không phải cắt ngắn bài bằng ngưỡng độ dài.
8. Crawler v4 thêm khóa file ở cấp hệ điều hành; lần crawl thứ hai vào cùng run bị từ chối. Khóa được nhả khi tiến trình đóng, kể cả do ngắt. Test kiểm tra khóa trùng và khả năng lấy lại khóa sau lỗi đã chạy thành công.

Không chạy hai lệnh `crawl` cùng một thư mục đồng thời. Snapshot v3 của run tải cũ chưa có khóa toàn run; kiểm tra tiến trình/tiến độ trước khi khởi động thêm. Code chính v4 đã có khóa. Khi bị ngắt chat, tiến trình shell có thể vẫn đang chạy.

## Đầu ra cần dùng

| File | Vai trò |
| --- | --- |
| [`sample.jsonl`](runs/ids_583_1582/sample.jsonl) | 1.000 ID/URL gốc đã chốt |
| [`manifest.json`](runs/ids_583_1582/manifest.json) | Hash Parquet và mẫu, giới hạn ID |
| [`reuse_manifest.json`](runs/ids_583_1582/reuse_manifest.json) | Nguồn và 8 ID đã reuse |
| [`corpus.parquet`](runs/ids_583_1582_clean/corpus.parquet) | Corpus gọn 976 tài liệu, ID int64, thuận tiện để đọc bằng PyArrow |
| [`corpus.jsonl`](runs/ids_583_1582_clean/corpus.jsonl) | Cùng corpus gọn ở dạng JSONL UTF-8 |
| [`corpus.accepted.jsonl`](runs/ids_583_1582_clean/corpus.accepted.jsonl) | Corpus v4 ứng viên qua kiểm tra tự động |
| [`documents.jsonl`](runs/ids_583_1582_clean/documents.jsonl) | Toàn bộ kết quả extraction v4, kèm quality flags |
| [`quarantine.jsonl`](runs/ids_583_1582_clean/quarantine.jsonl) | Trang lỗi hoặc cần review |
| [`QUALITY_REPORT.md`](runs/ids_583_1582_clean/QUALITY_REPORT.md) | Báo cáo kết quả sau sửa parser |
| [`quality_report.json`](runs/ids_583_1582_clean/quality_report.json) | Thống kê chi tiết máy đọc |
| `records/`, `raw/`, `robots/` | Checkpoint, body nguồn nén gzip và bằng chứng tải |

**Bản dùng tiếp:** các file tương ứng trong [`runs/ids_583_1582_clean`](runs/ids_583_1582_clean) sau reprocess. Bản clean bổ sung `AUDIT_REPORT.md`, `audit_summary.json`, `audit_cases.jsonl`, `review_100.jsonl` và `review_100.html` để đọc nguồn/đầu ra cạnh nhau. Phiếu 100 bài chưa có nhãn của người đánh giá; không tự báo là 100 bài đã được audit thủ công.

Không xóa ID khi text trùng. Mọi tài liệu vẫn giữ ID nguyên của contest; nhóm trùng nằm riêng trong `duplicates.jsonl`.

## Đánh giá và điều kiện hoàn tất

Kiểm tra kỹ thuật:

- Có đúng 1.000 checkpoint, ID là tập `range(583, 1583)`; không có ID ngoài mẫu.
- ID và URL khớp Parquet, raw/text khớp hash.
- `accepted + review + rejected + lỗi tải/trích xuất = 1000` khi hoàn tất.
- Thống kê HTTP success, extraction, accepted trên mẫu số **1.000 URL đã chọn**.
- Trang lỗi không được lấp bằng văn bản sinh mới hoặc URL khác.

Kiểm tra nội dung:

- Đối chiếu title, phần mở đầu và thân bài với DOM nguồn.
- Rà các bài có bảng, số/đơn vị, văn bản ngắn, ký tự lạ, redirect hoặc fallback.
- Ghi rõ số bài đã audit. Accepted tự động chưa chứng minh đạt độ đầy đủ 95% hay điểm F2 của contest.
- Mẫu gần như chỉ Bạch Mai: không suy rộng tỷ lệ sang 4,39 triệu URL hoặc chất lượng crawl tiếng Trung/Anh.

Kết quả đo cuối cùng và các điểm còn cần xem lại được ghi trong báo cáo run; không dùng kết quả 529 accepted của run cân bằng website cũ để mô tả dải ID này.

Lưu ý khi đọc JSONL bằng Python: dùng `for line in open(path, encoding="utf-8")` rồi `json.loads(line)`. Không dùng `read_text().splitlines()` vì ký tự U+2028/U+0085 trong nội dung có thể bị hiểu nhầm là ranh giới record.
