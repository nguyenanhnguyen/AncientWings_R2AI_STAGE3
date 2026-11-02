# README — Tài liệu thuyết minh sản phẩm (R2AI 2026 Stage 3, ViBioMIR)

Tài liệu này được tổ chức theo đúng 5 mục mà BTC yêu cầu trong "Hướng dẫn nộp Tài liệu Thuyết minh sản phẩm" (hạn 23:59 04/11/2026). Thông tin chi tiết hơn về tham số từng bước, manifest và các thử nghiệm đã loại bỏ nằm ở [`SYSTEM.md`](SYSTEM.md) cùng thư mục — README này là điểm vào, SYSTEM.md là tài liệu kỹ thuật đầy đủ mà README này trích dẫn lại, không chép lại toàn bộ để tránh hai bản lệch nhau.

> **Hai phần còn thiếu, không thể tự điền:**
> 1. **Mục 1.1/1.2 — mô tả khâu crawler** (cách crawl, làm sạch) đang để trống, sẽ được bổ sung riêng.
> 2. **Đường dẫn Google Drive/OneDrive** cho dữ liệu (mục 1.2) và checkpoint tự huấn luyện nếu có (mục 1.3) chưa có — cần tải lên và điền trước khi gửi email. Các mục `[ĐƯỜNG DẪN CẦN ĐIỀN]` dưới đây đánh dấu đúng những chỗ đó.

---

## 1.1. Tổng quan hệ thống

### Kiến trúc chung

Hệ thống gồm hai pha: **xây dựng cơ sở dữ liệu ngoại tuyến** (crawl → chuẩn hoá corpus → chia đoạn → lập chỉ mục, theo từng *run*) và **xử lý truy vấn** (truy hồi lai → xếp hạng lại bằng reranker lớn → lựa chọn đầu ra bằng pseudo-relevance feedback và ngưỡng thích ứng). Không có bước huấn luyện lại (fine-tune) nào; mọi mô hình học sâu được dùng ở dạng tải sẵn (zero-shot).

```
crawl (Kaggle) ──> corpus từng lô ──> pipeline từng run (14 run) ──> ứng viên + điểm reranker 0.6B
      │                                                                     │
      └─ trang bị chặn: tìm theo URL ─> 4B chấm ─> Wayback ─> 3 run archive ┘
                                                                            v
                        Qwen3-Reranker-4B chấm lại pool ứng viên (Kaggle, 5 lượt + 1 lượt bổ sung)
                                                                            v
     prf_rerank.py: PRF theo chủ đề + số tài liệu theo từng câu (quy tắc f2) + cửa sổ chunk
                                                                            v
                                 rezip_lzma.py (LZMA, từ điển 512 MB) ──> submission.zip < 100 MB
```

*(Sơ đồ ASCII trên lấy nguyên văn từ `SYSTEM.md` mục 4; sơ đồ hình ảnh minh hoạ — nếu BTC yêu cầu định dạng hình — chưa được vẽ, có thể bổ sung nếu cần.)*

### Luồng xử lý từ câu hỏi đến kết quả trả về

1. **Truy hồi lai (hybrid retrieval), theo từng run** — mỗi run (một phần của corpus, crawl/chuẩn hoá riêng) được tìm kiếm độc lập bằng BM25 (từ khoá) + hai kênh dense (`bge-m3`, `Qwen3-Embedding-0.6B`), gộp bằng Reciprocal Rank Fusion (RRF) vì điểm BM25 và cosine không cùng thang đo. Kết quả được chấm lại bằng hai reranker nhỏ (`bge-reranker-v2-m3`, `Qwen3-Reranker-0.6B`) ngay trong từng run. Một run riêng (`run_zh_a`) dịch câu hỏi tiếng Việt sang tiếng Trung bằng `Qwen3-4B` trước khi tìm, vì phần lớn corpus là tiếng Trung.
2. **Hợp nhất và xếp hạng lại bằng reranker lớn** — ứng viên của toàn bộ 14 run được gộp theo từng câu hỏi; `Qwen3-Reranker-4B` (chạy trên Kaggle, 2×T4) chấm lại tối đa 3 đoạn tốt nhất của mỗi tài liệu ứng viên, vì model này đắt hơn nhiều nên chỉ chấm trên pool đã rút gọn, không chấm toàn corpus.
3. **Pseudo-relevance feedback (PRF) + lựa chọn thích ứng** (`prf_rerank.py`, không cần GPU):
   - Điểm tài liệu = trộn tuyến tính điểm reranker lớn và reranker nhỏ (0,5/0,5).
   - Vector chủ đề của câu hỏi = trung bình embedding `bge-m3` của đoạn tốt nhất trong 10 tài liệu đầu; điểm cuối = z-score(điểm tài liệu) + z-score(cosine với vector chủ đề).
   - **Số tài liệu trả về khác nhau theo từng câu hỏi**: chọn N tối đa hoá F2 kỳ vọng dựa trên tổng điểm reranker (xem công thức ở `SYSTEM.md` mục 4, bước B4.3), kẹp trong 60–400 tài liệu.
   - **Đoạn nội dung**: mỗi tài liệu trả về một cửa sổ ≤1.000 token quanh đoạn chấm điểm cao nhất, là một lát cắt nguyên văn liên tục từ văn bản gốc (không viết lại); 50 tài liệu xếp hạng cao nhất của mỗi câu được thêm cửa sổ thứ hai nếu đoạn tốt thứ hai nằm ngoài cửa sổ đầu.
4. **Đóng gói** — JSON kết quả được nén LZMA (từ điển 512 MB) và kiểm tra khớp từng byte với bản chưa nén trước khi dùng, để file nộp dưới 100 MB mà không làm sai lệch nội dung đã chọn.

### Lập chỉ mục

Mỗi run: văn bản được chia đoạn 320 token mục tiêu, overlap 80, trần cứng 768 token (ưu tiên cắt theo câu/đoạn văn); mỗi đoạn giữ offset ký tự gốc để tra lại nguyên văn. Mỗi run có một chỉ mục BM25 (thưa) và hai chỉ mục dense (`bge-m3`, `Qwen3-Embedding-0.6B`) xây riêng, không gộp thành một chỉ mục toàn cục — xem lý do trong `SYSTEM.md` mục 4 (B1).

---

## 1.2. Tài liệu mô tả dữ liệu

### Nguồn dữ liệu

| Thành phần | Nguồn | Vai trò |
|---|---|---|
| Danh sách tài liệu chính thức | `data/links_corpus_vi_en_zh.parquet` của BTC | Mọi `doc_id` nộp đều phải thuộc danh sách này (script tự kiểm tra, xem `src/vibiomir/common/schema.py` và `scripts/submit.py`) |
| Câu hỏi | `data/query.parquet` (1.200 câu) | Đầu vào truy vấn |
| Văn bản tài liệu | Đội tự crawl các URL trong danh sách trên | Nguồn chính của corpus |
| Dữ liệu bổ sung | Wayback Machine (web.archive.org), cho các URL không tải trực tiếp được | Bù một phần độ phủ (xem `SYSTEM.md` mục 3, 4-B2) |

### Thu thập, làm sạch, phân đoạn

> **[ĐANG CHỜ BỔ SUNG]** — Mô tả chi tiết khâu crawler (cách crawl, cấu hình, làm sạch/QC) sẽ được cung cấp riêng và chèn vào đây trước hạn nộp. Mã nguồn của khâu này đã có sẵn trong `notebooks/crawl_corpus_kaggle.ipynb`, `notebooks/crawl_corpus_kaggle_hf_upload.ipynb`, `notebooks/crawl_domain_samples.ipynb` và `notebooks/archive_fetch_kaggle.ipynb`.

Phân đoạn văn bản (chunking) — đã có đầy đủ, không chờ bổ sung: xem `src/vibiomir/corpus/chunk.py` (tham số 320/80/768 mô tả ở mục 1.1 trên). Mỗi đoạn lưu `char_start`/`char_end` để tra lại đúng lát cắt nguyên văn khi dựng bài nộp (`src/vibiomir/submission/`), đảm bảo `chunk_text` không bị viết lại.

### Hướng dẫn truy cập dữ liệu

- **Danh sách nguồn và câu hỏi gốc của BTC**: tải trực tiếp từ trang dữ liệu chính thức của cuộc thi (không cần tài khoản riêng).
- **Corpus đã crawl (văn bản đã qua QC)**: lưu trên Hugging Face dataset `AncientWings/AncientWings_R2AI_STAGE3_ds`, dạng nhiều file `ids_<đầu>_<cuối>_synced.parquet`.
- **Bản sao đầy đủ để BTC kiểm tra** (corpus + dữ liệu trung gian theo yêu cầu "chia sẻ qua Google Drive/OneDrive"):
  **[ĐƯỜNG DẪN CẦN ĐIỀN — Google Drive/OneDrive]**
  *(Cần tải lên: `data/links_corpus_vi_en_zh.parquet`, `data/query.parquet`, và export corpus từ Hugging Face dataset nêu trên; dung lượng corpus ước tính theo tổng các run — xem bảng số liệu ở `SYSTEM.md` mục 4 — nên nén trước khi tải lên.)*

---

## 1.3. Mô hình sử dụng

Toàn bộ là mô hình mở, ≤15B tham số, phát hành trước 01/08/2026 theo đúng thể lệ (mục này đối chiếu với `docs/note/RULE.txt` và cần kiểm tra lại ngày phát hành trên Hugging Face trước khi nộp chính thức).

| Mô hình | Định danh Hugging Face | Kích thước | Vai trò trong hệ thống |
|---|---|---|---|
| Qwen3-4B (4-bit) | `Qwen/Qwen3-4B` | 4B | Dịch câu hỏi tiếng Việt → tiếng Trung cho run `run_zh_a`; chấm điểm pool ứng viên cấp slug trong bước tìm trang bị chặn |
| BGE-M3 | `BAAI/bge-m3` | 568M | Embedding dense; đồng thời dùng để tính vector chủ đề PRF |
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B` | 0.6B | Embedding dense, kênh thứ hai mỗi run |
| BGE-reranker-v2-m3 | `BAAI/bge-reranker-v2-m3` | 568M | Reranker cấp run (điểm "cũ" trước khi gộp pool) |
| Qwen3-Reranker-0.6B | `Qwen/Qwen3-Reranker-0.6B` | 0.6B | Reranker cấp run (điểm "cũ") |
| Qwen3-Reranker-4B | `Qwen/Qwen3-Reranker-4B` | 4B | Bộ xếp hạng chính trên pool đã gộp (chạy trên Kaggle, 2×T4) |

Ngoài ra: BM25 tự cài (không phải checkpoint tải sẵn, xem `src/vibiomir/index/bm25.py`). **Không sử dụng LLM mã nguồn đóng** (GPT, Gemini...) ở bất kỳ khâu nào. **Không fine-tune** bất kỳ mô hình nào — mọi checkpoint là bản gốc do nhà phát hành công bố.

### Tải và dùng checkpoint

Vì tất cả đều là mô hình mở, không cần đường dẫn riêng (Drive/OneDrive) cho checkpoint — tải trực tiếp bằng `transformers`/`huggingface_hub` theo đúng định danh ở cột 2 bảng trên, ví dụ:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-Reranker-4B")
model = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen3-Reranker-4B", load_in_4bit=True, device_map="auto")
```

Cấu hình 4-bit dùng `bitsandbytes` (NF4) cho `Qwen3-4B` và `Qwen3-Reranker-4B`; chi tiết nạp model nằm trong `src/vibiomir/retrieval/translate.py` (dịch) và `rerank_worker.py`/`notebooks/rerank_kaggle.ipynb` (reranker lớn, chạy trên Kaggle). Không dùng prompt API bên ngoài — toàn bộ suy luận chạy local/Kaggle bằng trọng số đã tải.

**Checkpoint tự huấn luyện:** không có — mọi mô hình ở trên là nguyên bản của nhà phát hành, nên mục "đường dẫn chia sẻ checkpoint" của BTC không áp dụng cho phần này. Nếu BTC vẫn cần một bản sao lưu dự phòng của trọng số (đề phòng Hugging Face không truy cập được lúc kiểm tra): **[ĐƯỜNG DẪN CẦN ĐIỀN — Google Drive/OneDrive, nếu BTC yêu cầu]**.

---

## 1.4. Mã nguồn

Toàn bộ nằm trong thư mục này (`final_system/`):

| Thư mục/file | Nội dung |
|---|---|
| `src/vibiomir/` | Thư viện chính: `corpus/` (chuẩn hoá, chunk), `index/` (BM25, dense), `retrieval/` (truy hồi lai, dịch, rerank), `submission/` (dựng file nộp), `evaluation/` |
| `scripts/` | CLI gọi từng khâu: `prepare.py`, `chunk.py`, `index.py`, `retrieve.py`, `submit.py`, `evaluate.py`, `pipeline.py` (điều phối toàn bộ 14 run) |
| `notebooks/` | Notebook Kaggle: crawl (`crawl_corpus_kaggle*.ipynb`, `crawl_domain_samples.ipynb`), khôi phục trang qua Wayback (`archive_fetch_kaggle.ipynb`), chấm điểm reranker lớn (`rerank_kaggle.ipynb`) |
| `slug_retrieval.py`, `slug_rerank.py`, `slug_targets.py` | Tìm và xếp hạng URL chưa crawl được, theo chữ trong URL (bước B2, mục 1.1) |
| `export_pool_pairs.py`, `export_rerank_candidates.py` | Xuất cặp (câu hỏi, đoạn) để chấm bằng `Qwen3-Reranker-4B` trên Kaggle |
| `prf_rerank.py` | PRF + lựa chọn thích ứng + dựng bài nộp (bước cuối, mục 1.1) |
| `merge_ids.py`, `merge_submissions.py`, `build_rerank_submission.py`, `make_submission.py` | Gộp/dựng các biến thể bài nộp |
| `rezip_lzma.py` | Nén lại bài nộp bằng LZMA, kiểm tra khớp byte |
| `chunk_stats.py`, `collect_manifests.py` | Công cụ kiểm tra: thống kê đoạn/bài nộp, gom manifest của mọi bước |
| `requirements/rag.txt` | Danh sách thư viện Python (mục dưới) |

### Thư viện, framework và phụ thuộc

Xem [`requirements/rag.txt`](requirements/rag.txt) — danh sách đã rà lại theo đúng các lệnh `import` thật trong mã nguồn ở thời điểm soạn tài liệu này:

```
numpy>=1.26
pyarrow>=19.0
torch>=2.4
transformers>=4.51,<5
tokenizers>=0.20
safetensors>=0.4
sentencepiece>=0.2
protobuf>=4.25
accelerate>=0.30
bitsandbytes>=0.43
scipy>=1.11
# faiss-cpu>=1.8  (tuỳ chọn; không có thì retrieval tự dùng numpy)
```

Môi trường đã dùng để chạy: Python 3.13 (`env/` trong thư mục gốc repo), Windows local cho các bước không cần GPU lớn (`prf_rerank.py`, `rezip_lzma.py`, `chunk_stats.py`), Kaggle (2×T4) cho `rerank_kaggle.ipynb` và các notebook crawl/archive.

### Tệp cấu hình để tái lập

- Tham số từng bước của 14 run: `work/run_*/stages/*.json` (sinh tự động khi chạy `scripts/pipeline.py`, không phải file soạn tay).
- Tham số dựng bài nộp cuối: cờ dòng lệnh của `prf_rerank.py` (xem mục 1.5, lệnh tái lập) — không có file cấu hình riêng vì toàn bộ tham số được truyền qua CLI và ghi lại trong `prf_manifest.json` sau mỗi lần chạy.

---

## 1.5. Tài liệu hướng dẫn

### Yêu cầu môi trường

- Python 3.13 (khớp `env/` của repo gốc).
- Windows (đã kiểm chứng) hoặc Linux tương đương cho các bước không cần GPU.
- GPU: không bắt buộc cho `prf_rerank.py`/`rezip_lzma.py`/`chunk_stats.py` (bước cuối, dựng bài nộp). Cần GPU (khuyến nghị 2×T4 trên Kaggle) cho bước chấm `Qwen3-Reranker-4B` và cho dịch câu hỏi bằng `Qwen3-4B`.
- RAM: dựng bài nộp cuối (`prf_rerank.py`) đã chạy được trên máy 16 GB RAM, khoảng 20 phút; nén LZMA thêm khoảng 15 phút.

### Cài đặt

```powershell
cd final_system
python -m venv env          # hoặc dùng env/ đã có sẵn ở thư mục gốc repo
.\env\Scripts\pip install -r requirements/rag.txt
```

### Tải dữ liệu/checkpoint

1. Checkpoint model: tải tự động từ Hugging Face theo định danh ở mục 1.3 (không cần bước tải tay).
2. Corpus đã crawl: tải từ Hugging Face dataset `AncientWings/AncientWings_R2AI_STAGE3_ds` (xem mục 1.2) hoặc từ đường dẫn Drive/OneDrive sẽ được bổ sung.
3. Danh sách nguồn và câu hỏi gốc: `data/links_corpus_vi_en_zh.parquet`, `data/query.parquet` (tải từ trang dữ liệu chính thức của BTC).

### Tạo/tải chỉ mục và chạy lại từng run

Với mỗi run (xem danh sách 14 run ở `SYSTEM.md` mục 4):

```powershell
.\env\Scripts\python.exe scripts\pipeline.py --source <corpus_của_run> --out work\run_<tên>
```

Lệnh này tự thực hiện: chuẩn hoá corpus → chia đoạn → lập chỉ mục BM25 + 2 dense → truy hồi lai + RRF → rerank bằng 2 model nhỏ. Tham số lưu lại trong `work\run_<tên>\stages\*.json`.

### Lệnh tái lập bài nộp cuối cùng

Yêu cầu đã có sẵn trước khi chạy: 14 thư mục `work/run_*`, 5 lượt chấm `work/rerank_*` + `work/rerank_extra/`, `lo_004/submission.zip`, `data/query.parquet`, `data/links_corpus_vi_en_zh.parquet`.

```powershell
.\env\Scripts\python.exe prf_rerank.py --docs 190 --adaptive --adaptive-rule f2 --chunk-mb 1050 --extra-windows 50 --out work\prf\f2_x50_rx
.\env\Scripts\python.exe rezip_lzma.py work\prf\f2_x50_rx\submission.zip work\prf\f2_x50_rx_small\submission.zip --dict-mb 512
```

Kết quả phải khớp: `docs_per_query` = 190.0; `extra_windows` = 50; dòng log "Cặp có điểm 4B: 2,067,495"; file `_small` ≈ 95 MB. Chi tiết đầy đủ, gồm lệnh chuẩn bị lượt chấm bổ sung và cách kiểm tra manifest, nằm ở [`SYSTEM.md`](SYSTEM.md) mục 5–6 — **không chép lại ở đây để tránh hai bản lệch nhau khi một trong hai được sửa.**

### Kiểm tra sau khi chạy

```powershell
.\env\Scripts\python.exe collect_manifests.py --out system_submission/manifests
.\env\Scripts\python.exe chunk_stats.py work\prf\f2_x50_rx_small\submission.zip
```

`collect_manifests.py` gom mọi manifest (tham số từng bước) vào một thư mục kèm `INDEX.md` để BTC hoặc người khác đối chiếu lại toàn bộ con số đã báo cáo. `chunk_stats.py` in số tài liệu/đoạn mỗi câu hỏi và độ dài đoạn của bài nộp, để kiểm tra nhanh file trước khi gửi.

### Kết quả của bài nộp chính

| Bài nộp | FINAL | DOCS\_F2 | CHUNKS\_F2 |
|---|---|---|---|
| `work/prf/f2_x50_rx_small/submission.zip` (chính) | 0,3060 | 0,3381 | 0,2739 |

Điểm trên public leaderboard, 1.200 câu hỏi. Chi tiết các bước đã thử và các phương án bị loại: `SYSTEM.md` mục 7.
