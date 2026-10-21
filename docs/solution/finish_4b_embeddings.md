# Chạy từ embedding 4B đã hoàn tất đến bài nộp

Tại thư mục gốc dự án:

```powershell
.\env\Scripts\python.exe scripts/finish_offload_run.py
```

Lệnh kiểm tra checkpoint đủ 85.841 dòng, SHA-256 của chunks và snapshot câu hỏi/URL,
shape, giá trị hữu hạn và chuẩn vector. Dùng lại `qwen4b_cpu_offload/embeddings.npy`;
không mã hóa lại corpus. Không khởi chạy song song nhiều bản lệnh này.

Luồng: dựng BM25 → mã hóa 1.200 câu hỏi bằng đúng revision Qwen3 Embedding 4B
(FP16, GPU 2 GiB + CPU offload, batch 1) → tìm kiếm dense + BM25 → hợp nhất
→ Qwen3 Reranker 0.6B FP16 chấm tối đa 100 ứng viên/câu → xuất hai bài nộp.
Không có bước dịch hoặc fine-tune trong lệnh tiếp nối này. Dense đa ngôn ngữ
đảm nhiệm khớp câu hỏi tiếng Việt với corpus tiếng Anh; BM25 ít hữu ích hơn khi khác ngôn ngữ.

File nộp:

```text
nguyen/pipeline_runs/en_batches_01_08/finish_4b_rerank06b_k100/submission_recall/submission.zip
nguyen/pipeline_runs/en_batches_01_08/finish_4b_rerank06b_k100/submission_balanced/submission.zip
```

Log nằm trong `finish_4b_rerank06b_k100/logs/`. Model tải thêm nằm trong
`nguyen/hf_pipeline/hf_home/hub`. Lần đầu cần tải Qwen3 Reranker 0.6B.

Chạy lại cùng lệnh để tiếp tục: các stage hoàn tất được xác minh checksum và dùng lại;
rerank dùng lại điểm trong SQLite. Nếu ngắt giữa retrieve, embedding câu hỏi và tìm
ứng viên được tính lại, nhưng embedding corpus không bị tính lại.

Muốn giảm số cặp rerank xuống tối đa 60.000 thay vì 120.000:

```powershell
.\env\Scripts\python.exe scripts/finish_offload_run.py --rerank-k 50
```

Kết quả của cấu hình này nằm trong thư mục riêng có hậu tố `k50`. Giảm ứng viên
có thể làm mất tài liệu liên quan; không có bảo đảm tăng điểm.

Chỉ kiểm tra dữ liệu, không nạp model/chạy retrieval:

```powershell
.\env\Scripts\python.exe scripts/finish_offload_run.py --check-only
```

Đã kiểm tra dữ liệu embedding thực tế. Chưa chạy toàn bộ retrieve/rerank/submission
của lượt này. ETA phải dựa vào log rerank sau khi model chạy, không suy từ tốc độ
embedding 4B sang reranker 0.6B.
