# Kết quả crawl 1.000 ID ViBioMIR

Ngày thực hiện: **03/10/2026**. Phạm vi: **583 <= id < 1583**, tức ID **583–1582**, đúng 1.000 URL. Có 999 URL Bạch Mai và 1 URL VietnamPlus. Đây là mẫu tập trung theo ID người dùng chọn; không đại diện cho toàn bộ corpus đa ngôn ngữ.

## Kết quả cuối cùng

| Chỉ số | Kết quả |
| --- | ---: |
| ID đã xử lý | **1.000 / 1.000** |
| ID còn chờ / sai ánh xạ | **0 / 0** |
| HTTP 2xx | **1.000 / 1.000** |
| Tài liệu vượt kiểm tra tự động | **976 (97,6%)** |
| Tài liệu cần xem lại | **13 (1,3%)** |
| Tài liệu bị loại khỏi accepted | **11 (1,1%)** |
| Bài có excerpt và giữ đủ excerpt | **425 / 425** |
| Bài có bảng trong HTML nguồn | **155** |
| Nhóm trùng text không rỗng | **2**, vẫn giữ mọi ID |
| Độ dài text trung vị / P95 | **3.684 / 7.018 ký tự**, tính trên tất cả bản ghi extraction |
| Kiểm tra code | **17 tests đạt** |

ID/URL đã đối chiếu lại với Parquet nguồn. Raw và text đã kiểm tra SHA-256. Chỉ số 425/425 đo bảo toàn excerpt sau gộp whitespace, **không phải recall toàn thân bài**. Chưa có gold passages hoặc 100 bài được người đánh giá chấm để khẳng định chất lượng extraction tổng thể; 97,6% là tỷ lệ qua heuristic, không phải điểm contest.

## Corpus dùng tiếp

- **[corpus.parquet](runs/ids_583_1582_clean/corpus.parquet)**: 976 tài liệu, ID `int64`, khoảng 1,93 MB; đã kiểm tra đọc–ghi lại không đổi dữ liệu.
- **[corpus.jsonl](runs/ids_583_1582_clean/corpus.jsonl)**: cùng 976 tài liệu, khoảng 5,82 MB; UTF-8, mỗi record trên một dòng LF/CRLF.
- [export_manifest.json](runs/ids_583_1582_clean/export_manifest.json): số bản ghi, dung lượng và SHA-256 hai file.
- [documents.jsonl](runs/ids_583_1582_clean/documents.jsonl): đủ 1.000 kết quả extraction và metadata/quality flags, gồm cả bản rỗng.
- [quarantine.jsonl](runs/ids_583_1582_clean/quarantine.jsonl): 24 ID chưa được đưa vào corpus accepted.

Schema gọn gồm `id`, `url`, `final_url`, `title`, `text`, `domain`, `extractor`, `published_at`, `raw_path`, `raw_sha256`, `text_sha256`, `duplicate_doc_ids`. Nội dung trùng vẫn giữ ID gốc riêng; bản raw/checkpoint và request trace nằm trong thư mục run.

```python
import pyarrow.parquet as pq

corpus = pq.read_table("runs/ids_583_1582_clean/corpus.parquet")
assert corpus.num_rows == 976
```

## Các lỗi đã sửa

1. **Ngắt quãng:** kiểm tra checkpoint cũ không hỏng; giữ snapshot code đúng hash để resume lượt tải v3; bản v4 thêm khóa hệ điều hành chống hai crawler ghi cùng run. Tái sử dụng 8 raw đã có thay vì tải lại.
2. **Mất phần mở đầu Bạch Mai:** parser lấy `content-excerpt` và `content-editor-post`; giữ đủ excerpt của 425 bài có trường này.
3. **Mã Word/HTML comment lọt vào text:** bỏ node comment khỏi văn bản đọc được. Text của **61 tài liệu** được sửa từ raw; ví dụ ID 1255 loại phần định dạng Office. Không phải tóm tắt hoặc viết lại bài.
4. **Charset:** ưu tiên encoding khai báo, hỗ trợ GB2312/GBK qua GB18030; đã kiểm tra trên raw của pilot trước.
5. **JSONL bị tách sai:** đọc theo dòng file, không dùng `str.splitlines()` cho toàn file vì U+2028/U+0085 có thể nằm trong chuỗi JSON hợp lệ. JSONL và Parquet đã round-trip thành công.

## 24 ID cần xử lý tiếp

Các nhóm dưới đây không chồng lấn, cộng lại đúng 24 ID:

| Nhóm quan sát | ID | Hướng xử lý |
| --- | --- | --- |
| Text ít/rỗng và có ảnh trong thân bài | 791, 797, 800, 801, 878, 1093, 1311, 1386, 1388, 1453, 1525, 1538, 1539 | Kiểm tra ảnh nguồn, cân nhắc OCR; giữ URL ảnh trong metadata |
| Trang không trích được title/text, thiếu selector | 906, 1305, 1347 | Kiểm tra trang lỗi hoặc cần JavaScript; chưa khẳng định browser sẽ phục hồi được |
| Không trích được text thân bài | 1275, 1376 | Xem raw để xác định nội dung nhúng hoặc nội dung không còn tồn tại |
| Fallback vì không có đúng container Bạch Mai | 802, 803 | Kiểm tra loại trang và viết parser phù hợp |
| Văn bản hoặc thân bài quá ngắn | 724, 799, 1287 | Đối chiếu nguồn; có thể là bài ngắn hợp lệ |
| Nhiều dòng lặp | 1327 | Kiểm tra nội dung lặp thật hay nhiễu template |

Không loại ID khỏi manifest và không thay bằng URL khác. Chưa chạy OCR hoặc browser fallback trong lượt này.

Hai nhóm trùng text: `[801, 1453]` và `[1350, 1351]`. Nhóm đầu là nội dung ngắn cần xem lại, không được hiểu là hai tài liệu đầy đủ giống nhau. Nhóm sau vẫn giữ cả hai ID trong corpus accepted.

## Báo cáo và khả năng tái lập

- [Pipeline tổng thể](CRAWL_PIPELINE.md) và [lệnh chạy đúng 1.000 ID](CRAWL_1000_IDS.md).
- [Báo cáo crawl tự động](runs/ids_583_1582_clean/QUALITY_REPORT.md).
- [Báo cáo kiểm tra offline](runs/ids_583_1582_clean/AUDIT_REPORT.md), [chi tiết từng ID](runs/ids_583_1582_clean/audit_cases.jsonl).
- [Phiếu đọc nguồn và corpus cạnh nhau](runs/ids_583_1582_clean/review_100.html), [phiếu chấm 100 bài](runs/ids_583_1582_clean/review_100.jsonl). Phiếu chưa có nhãn của người đánh giá.
- Run tải gốc: `runs/ids_583_1582`; run làm sạch: `runs/ids_583_1582_clean`. Raw gzip của bản clean chiếm 55.591.476 byte. Mã nguồn crawler và dependency lock đã lưu cùng bản clean.

Các artifact sinh ra nằm trong `runs/` và được `.gitignore` bỏ qua; tài liệu, code và dependency files có thể đưa vào Git. Không có bước train/index trong công việc này.
