# Thử nghiệm embedding trên tập 60k cố định

## Kết quả đã chấm

| Phương pháp | FINAL | Docs F2 | Chunks F2 |
|---|---:|---:|---:|
| contextual | 0.0072 | 0.0097 | 0.0048 |
| contextual, selection25 | 0.0078 | 0.0104 | 0.0052 |

`results/scoring_result.zip` chứa scores.txt và metadata, xác nhận lượt 0.0078 chấm xong (exitCode 0). Không chứa nhãn hay điểm từng câu. Giữ làm bằng chứng kết quả; không dùng làm ground truth.

## Lượt adjacent — 2026-10-28

Giả thuyết: phần mở đầu tài liệu có thể làm loãng ý nghĩa chunk ở xa đầu bài. Kiểm tra bằng cách bỏ riêng phần lead khỏi đầu vào embedding, giữ tiêu đề, chunk và ngữ cảnh liền trước không trùng overlap. Đây là giả thuyết, chưa có kết quả chấm.

- Cố định chính xác 60.000 tài liệu theo manifest tại `nguyen/pipeline_runs/balanced_60k/dataset`.
- Giữ chunk 320 token, overlap 80, giới hạn đầu vào 768; giữ Qwen3 Embedding 0.6B và Qwen3 Reranker 0.6B.
- Chạy lại embedding, index và retrieval/rerank; top rerank 50, keep 25.
- Đối chứng trực tiếp với contextual 0.0072 bằng cùng cấu hình submission. Không so trực tiếp với selection25 0.0078 vì khác cả cách chọn đầu ra.
- Lưu thêm `retrieval/before_rerank.jsonl` và `after_rerank_all.jsonl` để xác định bước nào loại ứng viên theo ngôn ngữ; chúng không phải nhãn liên quan.
- Output riêng: `nguyen/pipeline_runs/balanced_60k/adjacent`. Không ghi đè lượt trước.

Lệnh chạy/resume:

```powershell
.\env\Scripts\python.exe -X utf8 -u scripts\compare_embeddings.py --balanced20k --arms adjacent --require-contextual --out nguyen\pipeline_runs\balanced_60k
```

Không chạy lệnh thứ hai khi tiến trình hiện tại còn hoạt động. Log khởi chạy nền: `adjacent/experiment.stdout.log`, `experiment.stderr.log`; log từng bước trong `adjacent/logs`.

Lần khởi chạy đầu bị dừng tại chunk vì Transformers yêu cầu kiểm tra tokenizer qua Hugging Face trong khi kết nối từ tiến trình không hoạt động. Không có vector hay submission của lần này. Đã xác nhận tokenizer Qwen3 Embedding 0.6B nằm trong cache và nạp được trực tiếp từ snapshot. Runner dùng snapshot này khi có đúng một bản cache; lần chạy tiếp theo thiết lập `HF_HUB_OFFLINE=1` để tránh yêu cầu mạng cho model đã lưu.

## Giới hạn diễn giải

Audit trong `eda/balanced60k_retrieval_audit/audit.json` cho thấy tập Việt tập trung 97,825% ở một domain. Cân bằng số lượng ba ngôn ngữ không đồng nghĩa đại diện toàn bộ dataset. Giữ tập này để đối chứng, nhưng phải kiểm chứng trên tập độc lập trước khi kết luận tổng quát. Không có nhãn thì không suy ra được coverage tài liệu đúng hay chứng minh vượt SOTA từ các thống kê ứng viên.
