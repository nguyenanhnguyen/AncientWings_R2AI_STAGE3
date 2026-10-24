# Dùng lại lượt embedding 4B English cũ

Script thử `scripts/finish_offload_run.py` đã được gộp vào entry point chính.
Lệnh thay thế nằm ở [run_guide.md](run_guide.md):

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py pipeline `
  --reuse-run nguyen/pipeline_runs/en_batches_01_08 `
  --precomputed-embeddings nguyen/pipeline_runs/en_batches_01_08/qwen4b_cpu_offload `
  --skip-translation `
  --out nguyen/pipeline_runs/en_4b_reuse_new
```

Embedding cũ gồm 85.841 vector Qwen3 Embedding 4B. Bài nộp public chỉ dùng
79.721 tài liệu PubMed English này đã được BTC chấm 0 ở cả bảy metric; xem
`audit_zero_score_english.md`. Dùng lại vector nhằm nghiên cứu hoặc kiểm tra
luồng xử lý, không có bằng chứng sẽ cải thiện điểm nếu chỉ đổi reranker.
