# Hướng dẫn chạy pipeline từ dữ liệu crawl đến `submission.zip`

Tài liệu cho người trong nhóm cần chạy lại toàn bộ pipeline. Mỗi bước có lệnh, đầu vào, đầu ra và cách kiểm tra. Chi tiết thiết kế từng khâu nằm ở [training_design.md](training_design.md).

Các lệnh đã chạy nguyên văn ngày 05/10/2026 trên Windows, với 30.000 bản ghi đầu tiên của `nguyen/output/runs/batch01_nguyen`. Lượt đó dùng `--encoder hash` và `--reranker identity` vì máy chưa cài `torch`; phần chạy với model thật ở mục 9 **chưa được chạy thử**.

## 1. Mọi thứ nằm ở đâu

```text
nguyen/output/runs/batch01_nguyen/   Dữ liệu crawl thô (đầu vào), không bị sửa
work/                                Mọi thứ pipeline sinh ra, bị .gitignore bỏ qua
  corpus/      corpus.parquet, dropped.jsonl, prepare_manifest.json
  chunks/      chunks.parquet, chunk_manifest.json
  index/       bm25.npz, embeddings.npy, doc_ids.npy, chunk_ids.jsonl, *_manifest.json
  retrieval/   candidates.jsonl, retrieval_manifest.json
  submission/  submission.json, submission.zip, submission_manifest.json
  eval/        label_sheet.*, labels.jsonl, metrics.json, EVAL_REPORT.md, ...
```

Mọi lệnh đều có đường dẫn mặc định trỏ vào `work/`, nên chạy từ thư mục gốc repo thì không cần truyền đường dẫn. Trọng số model **không** nằm trong `work/`: chúng nằm ở bộ nhớ đệm Hugging Face (`C:\Users\<tên>\.cache\huggingface`).

Mỗi thư mục có một file `*_manifest.json` ghi tham số đã dùng và SHA-256 của file đầu ra. Chạy lại một bước với cùng `--out` sẽ **ghi đè** kết quả cũ (trừ phiếu gán nhãn); muốn giữ nhiều phiên bản thì đổi `--out`.

## 2. Chuẩn bị môi trường

Chạy ở thư mục gốc repo, PowerShell. Repo đang dùng môi trường `env\`:

```powershell
.\env\Scripts\python.exe -m pip install -r requirements/rag.txt
.\env\Scripts\python.exe -m unittest discover -s tests
```

Kết quả mong đợi: `Ran 38 tests ... OK`. Các bước 3–8 chạy được **không cần `torch`**; `torch` chỉ cần khi dùng model thật (mục 9). Nếu `pip` lỗi vì mạng chập chờn, chạy lại với `--retries 20 --timeout 120`.

## 3. Tiền xử lý: dữ liệu crawl → corpus

```powershell
.\env\Scripts\python.exe scripts/prepare.py --source nguyen/output/runs/batch01_nguyen --limit 30000
```

| | |
| --- | --- |
| Đầu vào | Thư mục run có `records/<id>.json` (định dạng crawler hiện tại trong `nguyen/`), hoặc file `.parquet`/`.json`/`.jsonl` xuất từ crawler của nhóm. Truyền nhiều nguồn được; nguồn đứng trước thắng khi trùng `id` |
| Đầu ra | `work/corpus/corpus.parquet`, `dropped.jsonl` (ID bị loại và lý do), `prepare_manifest.json` |
| Thời gian đo được | ~37 giây cho 30.000 bản ghi |

`--limit 30000` đọc 30.000 ID nhỏ nhất. Bỏ cờ này để đọc hết.

Bước này loại những hàng **không phải bài viết mà ID trỏ tới**: lỗi tải, văn bản rỗng, bị chuyển hướng về trang chủ, và văn bản giống hệt nhau ở quá nhiều ID (mặc định hơn 20, coi là trang mẫu). Bài chỉ bị crawler đánh dấu `review` vẫn được giữ, vì F2 coi trọng Recall.

**Kiểm tra:** mở `work/corpus/prepare_manifest.json`. Lượt chạy mẫu: đọc 30.000, giữ 29.990, loại 10 (6 chuyển về trang chủ, 4 lỗi HTTP), 100% tiếng Việt, 4 domain.

> Trong toàn bộ 46.456 bản ghi của batch này có **2.236 bản ghi bị chuyển về trang chủ** suckhoedoisong.vn, 2.230 cái chung một văn bản "Trang chủ". Chúng nằm ở ID cao hơn 30.000 bản ghi đầu nên lượt mẫu chỉ gặp 6. Khi bỏ `--limit`, bước này sẽ loại chúng; nếu để lại, chúng sẽ khớp với rất nhiều truy vấn và chiếm chỗ bài thật trong bài nộp.

## 4. Chia đoạn

```powershell
.\env\Scripts\python.exe scripts/chunk.py
```

| | |
| --- | --- |
| Đầu vào | `work/corpus/corpus.parquet` |
| Đầu ra | `work/chunks/chunks.parquet`, `chunk_manifest.json` |
| Thời gian đo được | ~80 giây; 29.990 tài liệu → 112.438 đoạn, trung vị 285 token, lớn nhất 946 |

Tham số chính: `--target-tokens 320 --overlap-tokens 64 --max-tokens 1024`. **Kiểm tra:** `chunks_over_1024_tokens` trong manifest phải bằng 0.

## 5. Lập chỉ mục

```powershell
.\env\Scripts\python.exe scripts/index.py all --encoder hash --device cpu --fp32
```

| | |
| --- | --- |
| Đầu vào | `work/chunks/chunks.parquet` |
| Đầu ra | `work/index/`: `bm25.npz` (~140 MB), `embeddings.npy` (~55 MB với `hash` 256 chiều), các manifest |
| Thời gian đo được | ~105 giây |

`--encoder hash` chỉ để chạy thử đường ống; nó **không** cho chất lượng truy hồi thật. Với model thật dùng `--encoder bge-m3` (mục 9); `embeddings.npy` khi đó khoảng số đoạn × 1024 × 2 byte, tức ~230 MB cho 112.438 đoạn.

## 6. Truy xuất

```powershell
.\env\Scripts\python.exe scripts/retrieve.py --reranker identity --device cpu --fp32 --keyword-variant
```

| | |
| --- | --- |
| Đầu vào | `work/chunks/chunks.parquet`, `work/index/`, `data/query.parquet` |
| Đầu ra | `work/retrieval/candidates.jsonl` (50 ứng viên mỗi truy vấn), `retrieval_manifest.json` |
| Thời gian đo được | ~16 giây cho 1.200 truy vấn với `identity` |

Lệnh tự dùng encoder đã ghi trong `dense_manifest.json` và **từ chối** nếu `--encoder` khác encoder đã dựng chỉ mục, hoặc nếu chunk đã đổi sau khi lập chỉ mục. `--keep` không được lớn hơn `--rerank-k`.

## 7. Dựng bài nộp

```powershell
.\env\Scripts\python.exe scripts/submit.py --links data/links_corpus.parquet --profile recall
```

| | |
| --- | --- |
| Đầu vào | `candidates.jsonl`, `chunks.parquet`, `work/corpus/corpus.parquet`, `data/query.parquet`, `data/links_corpus.parquet` |
| Đầu ra | `work/submission/submission.zip` (**file để nộp**), `submission.json`, `submission_manifest.json` |
| Thời gian đo được | ~26 giây |

Mọi đoạn được cắt lại từ corpus và so khớp; lệch là dừng ngay. **Kiểm tra** trong manifest: `queries` = 1200, `resliced_from_offsets` bằng số đoạn đã nộp, `dropped_docs` và `dropped_chunks` bằng 0.

Profile: `recall` (trả rộng), `balanced` (mặc định), `precision`. Lượt mẫu với `identity` cho 30 đoạn mỗi truy vấn và JSON 60 MB, vì điểm `identity` giảm đều nên ngưỡng không cắt được gì. Với reranker thật, điểm là xác suất 0–1 và ngưỡng sẽ cắt; nếu file vẫn quá lớn, thử `--profile balanced` hoặc `--chunk-max 15`.

Đổi profile chỉ cần chạy lại bước này, không cần chạy lại bước 6.

## 8. Đánh giá

```powershell
.\env\Scripts\python.exe scripts/evaluate.py sheet --limit 50     # xuất phiếu gán nhãn
# mở work/eval/label_sheet.html để đọc, điền "relevant": true/false trong label_sheet.jsonl
.\env\Scripts\python.exe scripts/evaluate.py collect               # phiếu đã điền -> labels.jsonl
.\env\Scripts\python.exe scripts/evaluate.py score                 # -> EVAL_REPORT.md
```

BTC không phát hành nhãn, nên điểm có nghĩa chỉ đến từ nhãn do **người** gán. `evaluate.py pseudo` sinh nhãn từ chính pipeline để chạy thử, và báo cáo sẽ ghi rõ điểm đó là vòng tròn. Lượt mẫu chạy `pseudo` cho F2 tài liệu 0,37 và đoạn 0,36; các con số này **không** nói gì về chất lượng.

`EVAL_REPORT.md` xếp mỗi tài liệu bị mất vào một nguyên nhân (`not_crawled`, `not_retrieved`, `not_selected`, `chunk_too_narrow`) để biết nên sửa ở block nào.

## 9. Chạy với model thật (chưa chạy thử)

Máy có RTX 2050 4 GB đủ cho `bge-m3` và `bge-reranker-v2-m3` ở fp16, nhưng chậm. Kaggle T4 là nơi hợp lý cho bước 5 và 6.

```powershell
# Cài torch theo bản CUDA của máy từ https://pytorch.org, rồi:
.\env\Scripts\python.exe scripts/index.py all --encoder bge-m3
.\env\Scripts\python.exe scripts/retrieve.py --keyword-variant
.\env\Scripts\python.exe scripts/submit.py --links data/links_corpus.parquet --profile recall
```

`retrieve.py` mặc định dùng `bge-reranker-v2-m3`. Lần đầu chạy sẽ tải trọng số từ Hugging Face.

Trên Kaggle: đưa repo và thư mục `work/corpus` (hoặc `work/chunks`) lên dưới dạng Dataset, chạy các lệnh trên với `python` của Kaggle, rồi lưu `work/index` và `work/retrieval` ra Output hoặc Dataset trước khi phiên kết thúc. Bước 7 và 8 chạy lại trên laptop được.

Những gì có thể lộ lỗi ở lần chạy thật đầu tiên: bộ nhớ GPU với `--batch-size 16` (code tự giảm một nửa khi hết bộ nhớ), thời gian encode thật, và việc tải model trong môi trường mạng chậm.

## 10. Sự cố thường gặp

| Thông báo | Nguyên nhân | Cách xử lý |
| --- | --- | --- |
| `was built from a different chunks file; rebuild Block B` | Đã chạy lại bước 4 sau bước 5 | Chạy lại bước 5 |
| `The index was encoded with ... not ...` | `--encoder` ở bước 6 khác bước 5 | Bỏ `--encoder` ở bước 6 |
| `does not re-slice from the corpus` | Corpus hoặc chunk đổi sau khi lập chỉ mục | Chạy lại từ bước 4 với đúng corpus |
| `Every document produced zero chunks; check the corpus text column` | Corpus không có cột văn bản quen thuộc | Thêm `--text-field <tên cột>` ở bước 3 |
| `label_sheet.jsonl already exists` | Phiếu gán nhãn cũ còn đó, được bảo vệ khỏi ghi đè | Đổi tên hoặc chuyển phiếu cũ đi |
| `UnicodeEncodeError` | Console Windows không phải UTF-8 | Đã được xử lý trong code; nếu vẫn gặp, đặt `$env:PYTHONIOENCODING='utf-8'` |
| File `*.tmp` còn sót trong `work/` | Lần chạy trước bị ngắt | Xóa được an toàn |
