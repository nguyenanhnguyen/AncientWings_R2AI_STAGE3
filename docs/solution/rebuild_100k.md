# Dựng lại pipeline trên cùng snapshot 100k

Bổ sung 11/10/2026: `--suite scale` so exact/FAISS IVF và E5+BGE trên cùng
corpus. Xem [scale_search.md](scale_search.md) cho lệnh chạy trên all.parquet.

Lệnh mới: `scripts/vibiomir.py rebuild`. Bộ `experiments` trước chỉ đổi retrieval/
submission trên subset đã có; bộ này dựng lại **chunk + BM25 + dense index cho
toàn bộ 99.507 documents đã qua prepare của đúng 100.000 records cũ**.
Không đọc lại crawler đang chạy, không lấy 100k mới, không dùng subset/index/cache
reranker của lần cũ. Kiểm tra SHA corpus từ checkpoint prepare trước khi bắt đầu.

## Chạy

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py rebuild --dry-run
.\env\Scripts\python.exe scripts/vibiomir.py rebuild
```

Đầu ra: `work/rebuild_100k/RESULTS.md`, `summary.json`, `logs/`, và
`<tên_lượt>/submission/submission.zip`. Chạy lại đúng lệnh để resume; muốn lượt
hoàn toàn mới thì dùng `--out work/rebuild_100k_v2`. Không xóa kết quả cũ.

## Thứ tự thêm kỹ thuật

| Lượt | So với | Kỹ thuật/model |
|---|---|---|
| 01_full_hybrid | Mốc mới | Chunk toàn corpus → BM25 + BGE-M3 → RRF → BGE reranker top50 |
| 02_keyword | 01 | Thêm kênh keyword BM25, trọng số 0,7 |
| 03_rerank100 | 02 | Chấm top100 thay top50, vẫn giữ top50 sau rerank |
| 04_ensemble | 03 | Thêm Qwen3-Reranker-0.6B, lấy trung bình điểm hai model |

Mỗi lượt giữ nguyên bước chọn profile f2 và cửa sổ nộp 768 token. So sánh với
**parent** ghi trong summary để biết tác động của kỹ thuật mới. Ensemble dùng
điểm chưa hiệu chuẩn nên có thể giảm điểm, phải đánh giá. Mốc 01 khác pipeline
cũ cả phạm vi index, bỏ kênh card và mặc định chỉ dùng câu hỏi gốc: không dùng
chênh lệch giữa hai mốc để quy toàn bộ tác động cho một kỹ thuật.

Chunker hiện có tách đoạn, chia đoạn dài theo câu, rồi đóng gói theo ngân sách
target384/overlap32/max768; giữ offsets để trích nguyên văn. Bộ này chưa thêm
chunker semantic/LLM hay mô hình embedding thứ hai.

## Không có LLM viết lại truy vấn

Không gọi translate, HyDE, generate, query rewrite hay feedback. Qwen chỉ chạy
forward để chấm xác suất yes/no cho cặp question–passage, không gọi generate.
Đăng ký model và prompt theo [model card chính thức](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B).

Mặc định chỉ dùng câu hỏi Việt, nên BM25 không tự tìm được từ tương đương Trung;
BGE-M3 đảm nhiệm tìm kiếm xuyên ngôn ngữ. Nếu muốn giữ bản dịch đã có mà không
chạy LLM dịch lại, thêm từ đầu:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py rebuild --out work/rebuild_100k_translated --translations work/run_local_100k/translations/translations.jsonl
```

File bản dịch có HyDE sẽ bị từ chối. Các lượt đều dùng cùng bản dịch để giữ đối chiếu.

## Tài nguyên và cache

- Dựng embedding corpus mới một lần; các lượt sau dùng cùng index mới.
- Cache reranker mới bắt đầu rỗng; các lượt sau chia sẻ điểm đã tính trong bộ này.
  Không cố tính lại cùng cặp chỉ để tăng thời gian chạy.
- Model nạp tuần tự. Batch encode8, rerank2, SDPA, tự giảm batch khi OOM;
  Qwen chỉ lấy logits cuối để giảm bộ nhớ. Chưa benchmark Qwen trên GPU máy này.
- Model pretrained vẫn dùng cache HF hiện có. Qwen0.6B sẽ tải nếu chưa có;
  vị trí tải tuân theo HF_HUB_CACHE/HF_HOME hiện tại, **có thể là ổ C nếu chưa cấu hình**.
  Đổi HF_HUB_CACHE sang D có thể khiến model đang cache ở C phải tải lại.
- Có thể bỏ lượt model thứ hai bằng `--extra-reranker none` ngay từ đầu.
  Thay đổi cấu hình sau khi chạy cần thư mục output mới.
- Full corpus cần thêm RAM, disk, thời gian encode; chưa có ETA đo trên máy này.
  Không chạy đồng thời hai bộ dùng GPU 4GB.

## Huấn luyện và đánh giá

**Dựng index/inference không phải fine-tune.** Lệnh này chưa cập nhật trọng số.
`work/teach` hiện mới có seeds, chưa có groups/judged để train student theo
module hiện có. Chưa tự sinh nhãn từ 1.200 câu hỏi thi và không gọi teacher tạo
query khi chưa xác định phạm vi huấn luyện.

Nếu có nhãn validation thật, thêm `--labels <file.jsonl>` từ đầu; evaluator sẽ
chạy sau mỗi ZIP. Khi chưa có nhãn, summary chỉ cho biết model, thời gian, cache,
thống kê đầu ra và thay đổi candidates so với lượt trước, không tự kết luận tăng điểm.
