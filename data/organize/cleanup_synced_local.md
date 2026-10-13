# Dọn bản crawl local đã có trong corpus HF

Script: [cleanup_synced_local.py](cleanup_synced_local.py). Chạy ở thư mục gốc dự án, bằng Python trong `env`.

## Điều kiện xóa

Một record local chỉ được đưa vào kế hoạch dọn khi:

1. `id` và `url` của record khớp **chính xác** với `data/links_corpus_vi_en_zh.parquet` của BTC (file này được kiểm SHA-256).
2. Trong `corpus/*.parquet` của dataset HF hiện tại đã có đúng `id`, `url` và `text_sha256` của record.
3. File checkpoint local không thay đổi từ lúc lập kế hoạch đến lúc áp dụng.

Script chỉ đọc HF, **không xóa hay upload lên HF**. Cache Parquet, chỉ mục SQLite và báo cáo ở `work/hf_local_cleanup/` trên ổ dự án. Có thể cần tải lại nhiều shard HF ở lần đầu; không dùng GPU.

## Chạy

Chỉ chạy khi crawler đã dừng hẳn và **không định resume** run cũ. Xóa `records/<id>.json` có nghĩa crawler cũ có thể crawl lại ID đó nếu chạy tiếp.

```powershell
.\env\Scripts\hf.exe auth whoami
.\env\Scripts\python.exe data\organize\cleanup_synced_local.py
```

Xem `work/hf_local_cleanup/cleanup_result.json` (tổng số) và `cleanup_plan.jsonl` (từng ID, file sẽ xóa). Sau khi xem kế hoạch:

```powershell
.\env\Scripts\python.exe data\organize\cleanup_synced_local.py --apply
```

`--apply` chỉ chạy nếu revision HF và **toàn bộ kế hoạch** vẫn giống lần preview ngay trước đó. Nếu có dữ liệu local/HF thay đổi, chạy preview lại. Có thể giới hạn nguồn bằng `--sources nguyen\output` hoặc một thư mục run cụ thể.

## File được dọn và giới hạn

- Xóa `records/<id>.json`, `requests_records/<id>.json`, `browser_records/<id>.json` của ID đã xác minh.
- Xóa raw `.gz` được các checkpoint đó tham chiếu **chỉ khi không còn record local khác dùng chung**. Raw thường **không được upload lên HF** bởi script sync mặc định; xóa raw là mất bằng chứng gốc local.
- Lọc các dòng có `id` tương ứng trong `documents.jsonl`, `corpus.accepted.jsonl`, `corpus.jsonl`, `quarantine.jsonl`, `manual_review.jsonl`, `logs/*.jsonl`, `logs/corpus_runner_snapshot.log` (log JSON theo mẫu) và `corpus.parquet` nếu chúng tồn tại. `duplicates.jsonl` được cập nhật danh sách ID trong từng nhóm.
- Giữ `sample.jsonl`, manifest kế hoạch crawl, báo cáo tổng hợp, log văn bản chung, robot cache và các tệp không thể quy thuộc an toàn cho một ID. Chúng có thể còn nhắc đến ID đã dọn; `quality_report.json` và `artifact_manifest.json` trở thành báo cáo lịch sử, không còn phản ánh trạng thái file sau dọn. **Không dùng run đã dọn để resume hoặc export lại theo quy trình crawl cũ.**

Vì vậy đây là công cụ giải phóng phần lớn dung lượng **theo từng mẫu đã có trong corpus HF**, không phải phương pháp xóa mọi dấu vết của mẫu khỏi toàn bộ máy hay lịch sử HF.
