# EDA và nghiên cứu corpus crawl

Thư mục này là workspace cô lập cho phân tích dữ liệu đã crawl. Code và kết quả nghiên cứu mới cần được đặt ở đây để không làm thay đổi `nguyen/output`, `nguyen/shards`, pipeline chính hoặc dữ liệu nguồn.

## Nội dung

```text
data/research/
  README.md                     # hướng dẫn thư mục
  data_research.md              # ghi chú nghiên cứu retrieval/chunking trước đó
  eda/
    README.md                   # hướng dẫn EDA crawl
    analyze_crawl.py            # EDA streaming, chỉ đọc dữ liệu crawl
    results/<timestamp>/        # báo cáo, thống kê CSV/JSON và mẫu phân tầng
```

### Kết quả EDA gần nhất

Ngày 2026-10-08, EDA lấy 3.000 ID cách đều từ mỗi run có sẵn: 9.000 mẫu trên tổng 271.616 record files. Xem [REPORT.md](eda/results/20261008_103159/REPORT.md), [diễn giải và việc cần kiểm chứng](eda/results/20261008_103159/ANALYSIS_NOTES.md), [summary.json](eda/results/20261008_103159/summary.json), và [mẫu record phân tầng](eda/results/20261008_103159/stratified_samples.jsonl).

Kết quả nổi bật: hai shard mới chủ yếu là tài liệu tiếng Trung (`cnkang.com`/`wujue.com`), ngắn hơn rõ rệt theo số ký tự so với batch tiếng Việt; toàn bộ 3.000 mẫu shard 01 có `quality_status=review` cùng `domain_parser_fallback`. Cần audit riêng cohort và parser này trước khi gộp thẳng vào corpus retrieval. Mẫu cũng có nhiều tín hiệu Q&A, đủ cơ sở để thử trích cặp hỏi–đáp thành metadata/offset sidecar, nhưng chưa đủ để tự động tách mọi câu hỏi thành nhãn.

## Chạy EDA

Từ thư mục gốc repo trong PowerShell:

```powershell
.\env\Scripts\python.exe data\research\eda\analyze_crawl.py
```

Mặc định chương trình quét `nguyen/output` và `nguyen/shards`, tìm các thư mục `records/`, rồi chọn đều theo ID tối đa 3.000 record mỗi run để EDA trải rộng mà không phải mở hàng trăm nghìn file JSON nhỏ. Kết quả được ghi vào thư mục timestamp mới dưới `data/research/eda/results/`. Nguồn được mở chỉ đọc; script không xóa, sửa, copy hay giải nén dữ liệu gốc. Thống kê mặc định là ước lượng trên mẫu đều, không phải tổng chính xác toàn bộ run.

Có thể chỉnh kích thước mẫu mỗi nhóm:

```powershell
.\env\Scripts\python.exe data\research\eda\analyze_crawl.py --sample-per-stratum 50
```

Để tính số liệu chính xác trên mọi JSON record (sẽ lâu do có hàng trăm nghìn file nhỏ):

```powershell
.\env\Scripts\python.exe data\research\eda\analyze_crawl.py --full-scan
```

Hoặc chỉ định rõ root và output:

```powershell
.\env\Scripts\python.exe data\research\eda\analyze_crawl.py `
  --input nguyen\output nguyen\shards `
  --out data\research\eda\results\manual_run
```

Không dùng lại `--out` của một lần chạy trước nếu muốn giữ lịch sử kết quả; mỗi lần mặc định tạo thư mục mới.

## Kết quả

- `REPORT.md`: tổng quan nhanh, số record theo run và top domain.
- `summary.json`: mode và số lượng file có sẵn/được đọc, trạng thái, QC, extractor, độ dài, tín hiệu lỗi mã hóa/HTML, duplicate text, năm xuất bản và số lượng theo run/domain.
- `domain_counts.csv`: phân bố domain đầy đủ theo run.
- `stratified_samples.jsonl`: reservoir sample tái lập theo `run × domain × status × quality_status`; mỗi body bị giới hạn 5.000 ký tự.
- `suspect_mojibake_samples.json`, `suspect_html_samples.json`: ví dụ để kiểm tra thủ công, không tự động kết luận record lỗi.

EDA quét metadata/text trong record, không đọc nội dung gzip raw. Default chọn file cách đều theo ID trong từng run trước khi parse; do đó mẫu bao phủ đầu–giữa–cuối mỗi shard. Nếu crawl vẫn đang chạy, kết quả phản ánh trạng thái tại thời điểm liệt kê; chạy lại sau khi crawl xong để có snapshot ổn định.

## Nguyên tắc tổ chức nghiên cứu

- Đặt notebook/script phân tích, schema phụ trợ, nhãn thủ công, manifest thí nghiệm và báo cáo mới trong `data/research/`.
- Không ghi kết quả EDA vào `nguyen/output` hoặc `nguyen/shards`; không sửa corpus gốc bằng notebook EDA.
- Mỗi thí nghiệm nên có cấu hình nguồn/hash, ngày chạy, seed, phiên bản code, metric và thư mục output riêng.
- Giữ raw crawl và record provenance tách khỏi dữ liệu derived (cleaned corpus, tags, chunks, index, labels).
