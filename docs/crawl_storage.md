# Giữ dung lượng cho Parquet và chẩn đoán

Notebook `notebooks/crawl_corpus_kaggle_hf_upload.ipynb` ưu tiên `corpus.parquet`
(Zstandard, kiểm tra round-trip và SHA-256) và `<run>_diagnostics.zip`.

- Báo cáo `documents.jsonl`, `quarantine.jsonl`, `source_decisions.jsonl` bỏ nội dung
  và các trace lớn bị lặp; `corpus.accepted.jsonl` chỉ giữ các trường cần cho export.
  Raw và record gốc vẫn giữ trong run để audit và resume.
- Trước khi lập báo cáo, xóa các bản báo cáo trung gian cũ có thể tái tạo.
  JSONL được ghi từng dòng qua file tạm và thay thế khi ghi xong.
- Mặc định chỉ xuất và upload Parquet, không tạo thêm `corpus.jsonl`.
  Nếu cần JSONL, chạy exporter với `--jsonl`, rồi đặt `HF_UPLOAD_JSONL=True`.
- ZIP checkpoint định kỳ bỏ các báo cáo/export trùng. Chỉ xóa ZIP local sau khi
  commit lên HF thành công; khi upload lỗi, giữ ZIP local. Raw/records không bị xóa.
- Kiểm tra dung lượng trước khi đóng ZIP, giữ dự phòng 1 GiB. ZIP cuối của run
  hoàn tất chỉ chứa kết quả và báo cáo, không nhân đôi toàn bộ raw/records.
  Nếu không đủ chỗ, bỏ qua ZIP phụ; Parquet và ZIP chẩn đoán vẫn là output riêng.
- Khi còn dưới 1 GiB, thử dọn báo cáo trung gian rồi tạm dừng crawl để resume.
  Mục 7 xuất `corpus.partial.parquet` nếu còn pending và đã có tài liệu accepted.
  File partial chưa qua audit toàn run, không được upload như corpus hoàn tất.

## Áp dụng và cứu run cũ

Upload notebook đã cập nhật lên Kaggle. Với run mới, chạy như bình thường.
Để chỉ cứu/export run cũ, gắn thư mục run vào Input, dùng cấu hình
`POSTPROCESS_ONLY=True` và `RESUME_RUN_PATH` theo phần cấu hình notebook,
rồi chạy các ô thiết lập và mục 7–10. Trình báo cáo mới nạp crawler snapshot cũ
và thu gọn báo cáo mà không sửa raw/records hay hash snapshot cũ.
Nếu thư mục chỉ có checkpoint HF, giải nén checkpoint vào Input trước.

Muốn tiếp tục crawl bằng runtime mới, dùng `RUN_TAG` mới và `RECOVERY_RUN_PATH`
trỏ tới thư mục run cũ theo kiểm tra phiên bản sẵn có trong notebook.
Không ghi đè hash cấu hình để ép resume snapshot khác phiên bản.

Không tự động xóa dữ liệu của run khác, cache toàn máy hay file nguồn Parquet.
Ngưỡng dự phòng giúp dừng trước khi đầy đĩa; một response đơn lẻ quá lớn hoặc
tiến trình khác đồng thời dùng hết ổ đĩa vẫn có thể gây lỗi I/O.

Đồng bộ code nhúng sau khi sửa helper:

```powershell
.venv\Scripts\python.exe scripts/build_storage_notebooks.py
```
