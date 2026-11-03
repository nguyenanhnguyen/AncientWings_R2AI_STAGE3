# AncientWings — hệ thống truy hồi y sinh đa ngôn ngữ (R2AI2026 vòng 3, ViBioMIR)

Tài liệu nộp kèm hệ thống: mô hình, dữ liệu, quy trình và lệnh tái lập bài nộp cuối.
Tham số chính xác của từng bước được lưu trong các file manifest; gom chúng bằng `collect_manifests.py` (mục 6).

## 1. Kết quả

| Bài nộp | FINAL | DOCS_F2 | CHUNKS_F2 |
|---|---|---|---|
| **`work/prf/f2_x50_rx_small/submission.zip`** (bài chính) | **0,3060** | 0,3381 | 0,2739 |
| `work/prf/f2_x50_1050_small/submission.zip` (dự phòng) | 0,3055 | 0,3375 | 0,2734 |
| `work/prf/f2_x50_rx_8b2_small/submission.zip` (thêm Qwen3-Reranker-8B, mục 4 B5) | chưa có | – | – |

Điểm public leaderboard, 1.200 câu, bài nộp ≤ 100 MB. Bài 8B làm sau khi vòng public đóng nên chưa có điểm public.

## 2. Mô hình

Tất cả là mô hình mở, mỗi mô hình ≤ 15B tham số, phát hành trước 01/08/2026 (đối chiếu lại trên Hugging Face trước khi nộp).

| Mô hình | Kích thước | Phát hành | Vai trò |
|---|---|---|---|
| `Qwen/Qwen3-4B` (4-bit) | 4B | 04/2025 | Dịch câu hỏi sang tiếng Trung cho `run_zh_a` |
| `BAAI/bge-m3` | 568M | 01/2024 | Embedding dense; vector chủ đề cho PRF |
| `Qwen/Qwen3-Embedding-0.6B` | 0.6B | 06/2025 | Embedding dense, kênh thứ hai |
| `BAAI/bge-reranker-v2-m3` | 568M | 2024 | Reranker trong pipeline (điểm "cũ") |
| `Qwen/Qwen3-Reranker-0.6B` | 0.6B | 06/2025 | Reranker trong pipeline (điểm "cũ") |
| `Qwen/Qwen3-Reranker-4B` | 4B | 06/2025 | Bộ xếp hạng chính (Kaggle, 2×T4) |
| `Qwen/Qwen3-Reranker-8B` (4-bit nf4) | 8B | 06/2025 | Reranker thứ hai cho tài liệu sát hạng cắt (chỉ bài 8B, mục 4 B5) |

Ngoài ra: BM25 (kênh từ khoá). Không dùng LLM đóng, không fine-tune.

## 3. Dữ liệu

- **Danh sách nguồn:** `data/links_corpus_vi_en_zh.parquet` của BTC. Mọi `doc_id` nộp đều thuộc danh sách này (script tự kiểm tra).
- **Câu hỏi:** `data/query.parquet` (1.200 câu).
- **Văn bản tài liệu:** đội tự crawl các URL trong danh sách bằng `notebooks/crawl_corpus_kaggle_hf_upload.ipynb`. Kết quả lưu ở HF dataset `AncientWings/AncientWings_R2AI_STAGE3_ds`, dạng file `ids_<đầu>_<cuối>_synced.parquet`, chỉ giữ trang qua QC.
- **Dữ liệu ngoài (web.archive.org):** các trang không tải được trực tiếp được lấy bản lưu trên Wayback Machine (`notebooks/archive_fetch_kaggle.ipynb`). Danh sách trang và nguồn trích dẫn nằm trong `work/archive*/` (`targets.parquet`, provenance). Nội dung vẫn là nguyên văn của đúng URL trong danh sách BTC.
- **`lo_004` (lô 0,04):** đã chạy lại qua pipeline thành `run_h`. Các lượt chấm 4B xuất trước đó vẫn ghi nguồn là `lo_004` và chứa sẵn văn bản đoạn đã chấm trong `pairs.parquet`, nên khi dựng bài không cần thư mục `lo_004`; tài liệu có ở cả hai nguồn chỉ được tính một lần (lấy đoạn điểm cao nhất).
- **Không dùng:** PubMed (đã thử, không có lợi) và mọi nhãn bên ngoài.

`chunk_text` luôn là một lát cắt liên tục, nguyên văn của văn bản tài liệu (không viết lại).

## 4. Quy trình

```
crawl (Kaggle) ──> corpus từng lô ──> pipeline từng run (14 run) ──> ứng viên + điểm reranker 0.6B
      │                                                                     │
      └─ trang bị chặn: tìm theo URL ─> 4B chấm ─> Wayback ─> 3 run archive ┘
                                                                            v
                        Qwen3-Reranker-4B chấm lại pool ứng viên (Kaggle, 5 lượt + 1 lượt bổ sung)
                                                                            v
     prf_rerank.py: PRF theo chủ đề + số tài liệu theo từng câu (f2) + cửa sổ chunk + cửa sổ thứ hai
                                                                            v
                                 rezip_lzma.py (LZMA, từ điển 512 MB) ──> submission.zip < 100 MB
```

**B1. Pipeline từng run** (`scripts/pipeline.py`, cấu hình lưu trong `work/run_*/stages/`):
- chuẩn hoá corpus;
- chia chunk 320/80/768 token;
- truy hồi lai BM25 + bge-m3 + Qwen3-Embedding-0.6B, gộp RRF;
- chấm lại bằng bge-reranker-v2-m3 và Qwen3-Reranker-0.6B.

`run_zh_a` dịch câu hỏi sang tiếng Trung bằng Qwen3-4B. Có 14 run: `run_vi`, `run_b`…`run_g`, `run_zh_a/b/c`, `run_h`, `run_archive`, `run_archive2`, `run_archive3`.

**B2. Tìm trang chưa crawl được theo URL:**
- `slug_retrieval.py`: BM25 trên chữ của URL.
- `slug_rerank.py`: 4B chấm cặp (câu hỏi, tiêu đề lấy từ URL).
- `slug_targets.py`: lập danh sách trang cần lấy.
- `archive_fetch_kaggle.ipynb`: tải bản lưu từ Wayback.
- Các trang lấy được chạy pipeline thành `run_archive*`.

**B3. Chấm lại bằng Qwen3-Reranker-4B** (`export_pool_pairs.py` → `notebooks/rerank_kaggle.ipynb`):
- Mỗi tài liệu ứng viên được chấm 3 đoạn tốt nhất. Có 5 lượt chấm: `work/rerank_pool4`, `rerank_pool5`, `rerank_h_arch`, `rerank_arch2`, `rerank_arch3`, mỗi lượt gồm `pairs.parquet` và `scores.parquet`.
- Lượt bổ sung `work/rerank_extra`: mỗi tài liệu sát hạng cắt được chấm thêm 1 đoạn, chọn đoạn chưa chấm giống chủ đề nhất (`prf_rerank.py --export-extra`). Lượt này chạy trên 2 tài khoản, `SHARD_COUNT = 2`.

**B4. Dựng bài nộp** (`prf_rerank.py`, không cần GPU). Mỗi câu hỏi:
1. **Điểm tài liệu** = 0,5 × điểm 4B + 0,5 × điểm reranker 0.6B. Mỗi tài liệu lấy đoạn tốt nhất.
2. **PRF:** vector chủ đề = trung bình embedding bge-m3 của đoạn tốt nhất ở 10 tài liệu đầu. Điểm cuối = z(điểm tài liệu) + 1 × z(cosine cao nhất giữa các chunk của tài liệu và vector chủ đề).
3. **Số tài liệu nộp khác nhau theo từng câu (quy tắc `f2`):**
   - Coi điểm 4B ≈ xác suất đúng (nhân hệ số c), ước lượng số đáp án của câu.
   - Chọn số tài liệu cho F2 kỳ vọng lớn nhất, kẹp trong 60–400 tài liệu.
   - c được chọn sao cho trung bình 190 tài liệu/câu.
4. **Chunk:**
   - Mỗi tài liệu nộp một cửa sổ ≤ 1.000 token quanh đoạn 4B tốt nhất.
   - 50 tài liệu đầu mỗi câu được thêm cửa sổ thứ hai quanh đoạn 4B tốt thứ hai, nếu đoạn đó nằm ngoài cửa sổ đầu.
   - Dung lượng JSON được giới hạn ở 1.050 MB.
5. **Nén:** `rezip_lzma.py`, LZMA với từ điển 512 MB. Nội dung được kiểm tra trùng khớp từng byte sau khi nén.

**B5. (Bài 8B) Chấm lại vùng sát hạng cắt bằng Qwen3-Reranker-8B** (`prf_rerank.py --export-band` →
`notebooks/rerank_8b_kaggle.ipynb` → `prf_rerank.py --scores8b`):
- Với N = số tài liệu của câu (bước B4.3), lấy các tài liệu ở hạng **0,5N–2,0N** theo thứ tự PRF. Mỗi tài liệu
  chấm lại **đoạn đại diện** (đoạn quyết định điểm của nó, cùng khoá cặp với điểm 4B): 304.239 cặp.
- Chấm trên Kaggle bằng Qwen3-Reranker-8B lượng tử 4-bit (bitsandbytes nf4), cùng prompt và cùng độ dài tối đa
  768 token như lượt 4B; khoảng 4 cặp/giây trên 2×T4, chia theo khoảng id câu (1–600, 601–1200). Notebook bỏ qua
  các cặp đã có điểm, nên lượt sau chỉ chấm phần còn thiếu.
- Phần 4B của đoạn được thay bằng trung bình hai mô hình: s(p) = 0,5·(0,5·s_4B + 0,5·s_8B) + 0,5·s_old
  (`--w8b 0.5`). Sau đó chạy lại B4.2–B4.5 như cũ (PRF, số tài liệu theo câu, chunk, nén).
- Trên 5.095 cặp đo thử: Spearman 8B–4B 0,72 (trung vị trong từng câu 0,57).
- So với bài 0,3060 (`rank_drop.py`): đổi khoảng **10,8 tài liệu/câu**, gần như toàn bộ ở hạng 0,7N–1,0N
  (bị bỏ: 6% ở 0,7–0,8N, 14% ở 0,8–0,9N, 34% ở 0,9–1,0N; 0% ở nửa trên danh sách). Vì F2 tính trên tập tài liệu,
  chấm lại phần đầu danh sách không đổi được kết quả nên không làm. Bản dải hẹp 0,7N–1,5N (179.160 cặp) đổi
  10,5 tài liệu/câu; mở rộng lên 0,5N–2,0N chỉ đổi thêm khoảng 2,6 tài liệu/câu.

## 5. Lệnh tái lập bài cuối

Ở thư mục gốc repo, PowerShell, Python trong `env`. Cần có sẵn:
- `work/run_*` (14 run);
- `work/rerank_*` (5 lượt) và `work/rerank_extra/` (`pairs.parquet`, `scores_0.parquet`, `scores_1.parquet`);
- `lo_004/submission.zip`, `data/query.parquet`, `data/links_corpus_vi_en_zh.parquet`.

```powershell
.\env\Scripts\python.exe prf_rerank.py --docs 190 --adaptive --adaptive-rule f2 --chunk-mb 1050 --extra-windows 50 --out work/prf/f2_x50_rx
.\env\Scripts\python.exe rezip_lzma.py work/prf/f2_x50_rx/submission.zip work/prf/f2_x50_rx_small/submission.zip --dict-mb 512
```

`prf_rerank.py` tự dùng bộ mặc định: 5 lượt 4B, lượt bổ sung nếu có, 14 run, `lo_004`. Kết quả phải khớp:
- `docs_per_query` = 190.0;
- `extra_windows` = 50;
- dòng `Cặp có điểm 4B: 2,067,495`;
- file `_small` ≈ 95 MB.

Thời gian trên laptop (16 GB RAM): dựng khoảng 20 phút, nén khoảng 15 phút.

Chuẩn bị lượt bổ sung (đã chạy; chỉ cần nếu tái lập từ đầu):
```powershell
.\env\Scripts\python.exe prf_rerank.py --docs 190 --adaptive --adaptive-rule f2 --export-extra work/rerank_extra --band 0.8 1.8
```
Lệnh này xuất 165.331 cặp. Chấm trên Kaggle (`rerank_kaggle.ipynb`) với tốc độ khoảng 6,5 cặp/giây trên 2×T4.

Bài 8B (mục 4 B5). Cần thêm 2 file điểm 8B (`scores_8b*.parquet`, mỗi file chứa điểm của mọi lượt trước) trong
`work/rerank_8b_band/`:
```powershell
# Xuất cặp (đã chạy; chỉ cần nếu tái lập từ đầu): 304.239 cặp
.\env\Scripts\python.exe prf_rerank.py --docs 190 --adaptive --adaptive-rule f2 --band 0.5 2.0 --export-band work/rerank_8b_band
# Chấm trên Kaggle: notebooks/rerank_8b_kaggle.ipynb, MAX_QUERIES = 0, QID_FROM/QID_TO = 1/600 và 601/1200
.\env\Scripts\python.exe prf_rerank.py --docs 190 --adaptive --adaptive-rule f2 --chunk-mb 1050 --extra-windows 50 --scores8b "work/rerank_8b_band/scores_8b*.parquet" --w8b 0.5 --out work/prf/f2_x50_rx_8b2
.\env\Scripts\python.exe rezip_lzma.py work/prf/f2_x50_rx_8b2/submission.zip work/prf/f2_x50_rx_8b2_small/submission.zip --dict-mb 512
```
Kết quả phải có dòng `Mô hình thứ hai: 304,239 điểm`.

## 6. Manifest và kiểm tra

```powershell
.\env\Scripts\python.exe collect_manifests.py --out system_submission/manifests
.\env\Scripts\python.exe chunk_stats.py work/prf/f2_x50_rx_small/submission.zip
```

- `collect_manifests.py` chép mọi manifest (tham số từng bước, số tài liệu, số cặp, cấu hình bài cuối) và provenance vào một thư mục, kèm `INDEX.md`.
- `chunk_stats.py` in số tài liệu/chunk mỗi câu và độ dài chunk của bài nộp.

Công cụ phân tích (không cần GPU, không cần đáp án):

| Script | Dùng để |
|---|---|
| `compare_submissions.py A B` | Hai bài nộp khác nhau bao nhiêu tài liệu/chunk mỗi câu |
| `rank_drop.py A B` | Tài liệu của A bị B bỏ nằm ở đâu trong danh sách của A (theo hạng / N) |
| `source_breakdown.py BÀI [--per-query FILE.csv]` | Bài nộp lấy tài liệu/chunk từ lô nào, theo từng câu |
| `coverage_check.py --crawl "…"` | Dữ liệu đã crawl có nằm hết trong 14 run chưa |

## 7. Các bước đã thử và đóng góp

Đo trên public leaderboard. Các bước được giữ:

| Bước | FINAL | Ghi chú |
|---|---|---|
| PRF + chunk từ thứ tự 4B | 0,2851 | docs .3158 |
| Số tài liệu theo từng câu (quy tắc đếm) | ~0,294 (ước tính, chỉ nộp phần docs) | docs .3336 |
| Chunk chia theo từng câu, thứ tự PRF | 0,3003 | chunk .2669 |
| Quy tắc `f2` + JSON 1.000 MB | 0,3033 | docs .3375 |
| Cửa sổ thứ hai (20 → 50 tài liệu) | 0,3050 → 0,3055 | chunk .2725 → .2734 |
| Chấm 4B bổ sung vùng sát hạng cắt | **0,3060** | docs .3381, chunk .2739 |

Các thử nghiệm bị loại, DOCS_F2 so với mốc .3336 hoặc .3375:

| Thử nghiệm | Kết quả |
|---|---|
| Mở rộng tài liệu ngoài pool theo chủ đề | .3121 |
| Encoder Qwen cho PRF | .3327 |
| Trung bình 230 tài liệu/câu | .3324 |
| Tối đa 600 tài liệu/câu | .3306 |
| Tối thiểu 30 tài liệu/câu | .3324 |
| Hạ điểm tài liệu tiếng Trung ×0,6 | .3294 |
| Tính thêm đoạn thứ hai vào điểm | .3360 |
| Trộn 0,6 điểm 4B | thấp hơn |
| Tối thiểu 90 tài liệu/câu | thấp hơn |
| Thêm tài liệu tiếng Anh (`run_en`) | .3323 (FINAL 0,3009) |

## 8. Danh sách nộp kèm

- **Code:** các script ở thư mục gốc, cùng `src/`, `scripts/`, `notebooks/` và tài liệu này.
- **Manifest:** `system_submission/manifests/`.
- **Bài nộp:** `work/prf/f2_x50_rx_small/submission.zip`.
- **Dữ liệu trung gian:** điểm 4B (`work/rerank_*`) và điểm 8B (`work/rerank_8b_band/scores_8b*.parquet`) để tái lập mà không cần GPU. Nộp hay chỉ giữ là tuỳ yêu cầu của BTC.
