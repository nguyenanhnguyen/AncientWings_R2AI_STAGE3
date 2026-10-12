# So sánh chất lượng và chi phí truy hồi — 11/10/2026

Điểm người dùng báo trên `nguyen/all.parquet`:

| Final | Docs F2 | Chunks F2 | Docs precision | Docs recall | Chunks precision | Chunks recall |
|---:|---:|---:|---:|---:|---:|---:|
| .0676 | .0768 | .0584 | .2617 | .0683 | .2632 | .0511 |

Manifest `work/run_all_parquet` có 62.338 tài liệu, trong đó 62.336 tiếng Việt,
2 tiếng Anh. Corpus 100k cũ có gần 60k tài liệu Trung. Precision tăng, docs recall
giảm giữa hai lần nộp; chưa thể quy nguyên nhân cho kiến trúc vì dữ liệu cũng đổi.
`accepted` trong prepare mặc định cho schema thiếu quality_status, không chứng minh
toàn bộ 62k tài liệu đều có nội dung tốt. Lượt này giữ cùng corpus để đối chiếu.

## Chạy thật

```powershell
.\env\Scripts\python.exe -m pip install -r requirements/search.txt
.\env\Scripts\python.exe scripts/vibiomir.py rebuild --suite scale --base work/run_all_parquet --out work/scale_all_parquet
```

Lệnh dùng snapshot đã kiểm SHA của all.parquet. Muốn đối chiếu trên corpus 100k
cũ, đổi `--base work/run_local_100k --out work/scale_local_100k`.
Giữ nguyên câu hỏi đánh giá và cách xuất bài; không gọi LLM rewrite/HyDE/teacher.
Mặc định chỉ dùng câu hỏi gốc. `--translations` vẫn nhận bản dịch có sẵn nếu cần,
và yêu cầu output mới khi đổi cấu hình để không trộn thí nghiệm.

Đầu ra: `RESULTS.md`, `summary.json`, `logs/`, `stages/` và ZIP từng lượt dưới
`work/scale_all_parquet`. Chạy lại cùng lệnh để resume. Quá trình encode mới,
FAISS build và cache reranker đều có artifact riêng; không ghi đè run cũ.

## Các lượt

| Lượt | Parent | Khác biệt cần đo |
|---|---|---|
| 01_full_hybrid | mốc mới | Chunk toàn corpus + BM25 + BGE-M3 + BGE reranker50 |
| 02_keyword | 01 | Thêm keyword BM25 |
| 03_rerank100 | 02 | Chấm100, giữ50 |
| 04_ensemble | 03 | Thêm Qwen3-Reranker-0.6B, trung bình điểm |
| 05_ann16 | 03 | FAISS IVF, thăm16 cụm thay tìm chính xác |
| 06_ann64 | 05 | Thăm64 cụm |
| 07_dual_dense | 03 | Thêm E5-base qua RRF, vẫn chấm100 và giữ50 |
| 08_dual_ensemble | 07 | Thêm Qwen reranker |

Lượt ANN và lượt model bổ sung là hai nhánh cùng mốc03. Đọc `parent` để so sánh
đúng. Không tự chọn model/phương pháp tốt nhất khi chưa có điểm. Có thể bỏ E5
bằng `--extra-encoder none`, hoặc bỏ model reranker bổ sung bằng
`--extra-reranker none` ngay từ đầu.

E5-base dùng mean pooling có attention mask, prefix `query: `/`passage: ` và
giới hạn512 token đúng [model card](https://huggingface.co/intfloat/multilingual-e5-base).
E5 là một nguồn ứng viên khác để thử, chưa chứng minh tốt hơn BGE trên dữ liệu này.
Hai encoder cần hai lần encode corpus và hai bộ vector. Model nạp tuần tự;
BGE/Qwen rerank vẫn dùng batch2 và có giảm batch khi OOM. Model pretrained tải
theo cache HF hiện tại, có thể nằm ở C nếu chưa cấu hình HF_HOME/HF_HUB_CACHE.

## Thời gian và bộ nhớ

- ANN build đọc embedding memmap, lấy mẫu tối đa50k vectors để train các cụm và
  thêm vectors từng batch8192. Số cụm thực tế hạ xuống nếu ít mẫu train.
- `nprobe` xác định số cụm được thăm; tăng nó thường tăng độ bao phủ và chi phí.
  Đây là cơ chế của [FAISS IVF](https://github.com/facebookresearch/faiss/wiki/Faster-search).
- `ann_audit=16` chọn16 query variants trải đều để so top-k ANN với exact trên
  cùng vectors; `overlap_with_exact_at_k` không phải recall theo nhãn cuộc thi.
  Số đo `search_seconds` tách khỏi thời gian encode câu hỏi và rerank; tổng thời
  gian retrieval vẫn bao gồm kiểm hash, audit, cache và nạp model.
- `--disk-text` tự tạo sidecar SQLite từ chunk Parquet theo batch4096. RAM chỉ
  giữ metadata và cache8192 passage texts. Reranker đọc text của ứng viên được chọn.
  File SQLite ghi trong index của run, không phải HF. Không dùng cùng sidecar
  cho hai tiến trình build đồng thời. Chế độ này hiện không kết hợp với feedback.
- FAISS IVFFlat vẫn giữ vector float32 trong RAM (~4GB cho 1 triệu vectors1024d,
  chưa tính metadata). Đây không phải chỉ mục nén PQ hoặc toàn bộ index trên đĩa.

**Giới hạn thực tế:** chưa benchmark hàng triệu tài liệu. Chunk build, BM25 build,
dense build và bước xuất bài hiện vẫn có chỗ nạp toàn bảng vào RAM. Bộ thử này
giảm RAM ở retrieval và đo đường ANN trước; chưa chứng minh toàn bộ pipeline
chạy vừa RAM hoặc hoàn thành trong thời gian cụ thể ở quy mô triệu mẫu. Nếu ANN
giữ chất lượng đủ tốt, bước sau là shard corpus/build theo luồng hoặc IVF-PQ,
cần phép đối chiếu chất lượng riêng.

## Kiểm tra kết quả

- `summary.json`: thời gian, cache mới/cũ, model, mức đổi candidates so parent.
- `retrieval/retrieval_manifest.json`: `dense_search` chứa thời gian search và
  độ trùng với exact cho từng encoder.
- `retrieval/candidate_trace.jsonl`: số ứng viên trước/sau giới hạn mỗi doc,
  số cặp được rerank và danh sách doc IDs đã vào reranker.
- `index/ann_manifest.json`: số cụm thực tế, kích thước, thời gian build,
  hash vector/chunk/index. Thay vector mà chưa build lại ANN sẽ bị từ chối.
- Có nhãn thật: thêm `--labels <labels.jsonl>` từ đầu để chấm từng ZIP. Không có
  nhãn: ghi7 cột leaderboard cho từng ZIP. Kiểm tra độ phủ gold doc trong corpus
  trước khi kết luận lỗi do retrieval; model không tìm được doc nằm ngoài corpus.

Các dependency FAISS là tùy chọn của suite scale; pipeline mặc định vẫn dùng
tìm chính xác. Không thay torch/CUDA bằng file requirements/search.txt.
