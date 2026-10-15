# Crawl Long Châu — triển khai và kết quả 14/10/2026

**Cập nhật 15/10:** parser v2 sửa nhóm link paragraph, default delay 5 giây; runner v7 lưu checkpoint cho
mọi engine và sửa progress. Run cũ cần recovery để tái trích raw đã lưu, giữ cooldown.
[Hướng dẫn v2 và phục hồi run Kaggle 204274–205274](longchau_resume_v2.md).
Các số liệu/config dưới đây là kết quả trước v2 ngày 14/10.

Đã tích hợp vào [notebook corpus chính](../notebooks/crawl_corpus_kaggle_hf_upload.ipynb) và
[domain samples](../notebooks/crawl_domain_samples.ipynb). Notebook riêng
`check_longchau_50.ipynb` thử mẫu phân tầng, không upload HF. File này nằm ngoài Git;
tạo local bằng `python scripts/build_longchau_smoke_notebook.py`
([builder](../scripts/build_longchau_smoke_notebook.py)).

Notebook hiện có thêm cell đo 3 nhịp 10 → 7,5 → 5 giây/request, 20 URL/nhịp,
dừng khi gặp chặn và giữ cooldown. [Cấu hình, báo cáo và giới hạn của phép đo](longchau_rate_check.md).

## Client, parser và checkpoint

[scripts/longchau.py](../scripts/longchau.py) dùng `curl_cffi.requests.Session(impersonate='chrome')`,
TLS `verify=True`, reuse session/cookie, 1 worker, delay mặc định 1,75 giây sau request.
Timeout connect/read 10/45 giây, ngân sách 180 giây/URL, tối đa 3 attempts.
408/429/5xx và lỗi kết nối/timeout dùng backoff; tôn trọng `Retry-After` số giây hoặc HTTP-date.
Cooldown dài ghi checkpoint/gate để hoãn và tiếp tục sau; 403 không retry trong cùng lượt.
Resume thử lại checkpoint lỗi Long Châu, giữ lịch sử ở `longchau_previous_records/`.
SSL lỗi không bị bỏ qua. Redirect ghi từng hop và kiểm tra địa chỉ đích trước request.
API client tham khảo [tài liệu curl-cffi](https://curl-cffi.readthedocs.io/en/latest/quick_start.html).

`RESPECT_ROBOTS` giữ cơ chế robots/cache/deny hiện có; robots Long Châu cũng dùng curl,
ghi lỗi riêng với lỗi bài viết. Default giữ public-page probe của repo (`False`).
Không thay client các hostname khác. PubMed vẫn EFetch; domain khác giữ Requests/Selenium.
IP report ghi đúng engine curl; IP Requests/Chrome không được coi là IP riêng của curl.

Bài viết: lấy `[data-theme-element="article"][data-scale-font]`, h1 duy nhất, sapo/metadata từ object
đúng bài trong `__NEXT_DATA__`; xác minh slug/canonical và đối chiếu description với DOM.
Không dùng câu mở/kết riêng từng URL hoặc longest string. Trang `/benh/` chỉ render một phần trong
HTML ban đầu: lấy đủ sáu trường HTML y khoa `description`, `symptom`, `aetiologies`, `risk`,
`diagnoseAndTreaty`, `livingAndPreventive` và FAQs từ object đã xác minh, đối chiếu ba phần hiển thị.
Giữ paragraph/heading/list/table/caption, dấu câu, số, đơn vị, phủ định và cảnh báo y khoa.
Không lấy JSON bài liên quan. Template/identity/biên không chắc có review/rejected/error và giữ raw;
không fallback trafilatura/Selenium cho Long Châu trong route mặc định.

Profile/font controls/related links/signature/disclaimer chung được loại theo component/block;
không xóa “dược sĩ”, ngày hay cảnh báo trên toàn bài. Author/reviewer/published/updated lưu riêng,
nguồn không có author giữ null. Title là h1, có thể khác SEO title trong fixture.
Heading/block nguồn là vùng y khoa sau loại component, gồm sapo, không đếm menu/UI toàn trang.
Export giữ schema cũ, bổ sung nullable `author`, `reviewed_by`, `updated_at`.
Giữ ID/URL nguồn, redirect ở `final_url`, raw gzip hash theo bytes gốc, text hash UTF-8.
Snapshot/code/config có SHA-256; checkpoint atomic theo ID. Success hợp lệ giữ nguyên qua resume.

## Nguồn và kết quả thật

Đã đọc `data/links_corpus_vi_en_zh.parquet`, 1.220.598 dòng; ViBioMIR revision
`71be0e1239a19dfd7a717e2bc13e3bec21bd0334`, SHA-256
`87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`.
Long Châu có 79.598 URL, hostname nguồn đều là `nhathuoclongchau.com.vn`; hỗ trợ alias `www`.
Không tìm thấy `missing_links.parquet` hoặc ZIP `longchau_clean_check_*` trong workspace lúc khảo sát.

| Dạng đường dẫn | URL nguồn | Mẫu 50 | Accepted | Review |
| --- | ---: | ---: | ---: | ---: |
| `/bai-viet/…html`, không đuôi `-số.html` | 44.456 | 13 | 13 | 0 |
| `/bai-viet/…-số.html` | 33.619 | 13 | 12 | 1 |
| `/benh/…html`, không đuôi `-số.html` | 741 | 12 | 12 | 0 |
| `/benh/…-số.html` | 782 | 12 | 12 | 0 |

Mẫu seed `20261014`, URL duy nhất, giữ ID nguồn, loại ba URL fixture được chỉ định.
Đuôi số là hình dạng URL, không chứng minh CMS ID hay tuổi bài. Metadata mẫu có published 2018–2025,
updated 2023–2026. Cố ý tăng tỷ trọng trang bệnh để thử parser; 98% là tỷ lệ trên mẫu này, không phải
ước lượng tỷ lệ toàn bộ domain.

Mạng thật tại máy local Windows, curl_cffi 0.16.3: **50/50 HTTP 200**, không challenge/403/404;
**49 accepted, 1 review, 0 rejected**, không khởi động Chrome.
Ba fixture yêu cầu và hai fixture trang bệnh cũng tải thật HTTP 200; gzip bytes gốc/SHA ở
[tests/fixtures/longchau](../tests/fixtures/longchau/manifest.json).
Sau hoàn thiện code, recovery **offline từ 50 raw này**, không tải lại website:
ID/URL và hash raw/text đúng, 50/50 sapo giữ đủ, đối chiếu lại 3.306 block và 590 heading vùng y khoa;
không phát hiện font-control lines còn sót. Parquet/JSONL round-trip giữ text/ID đầy đủ.
Audit dùng cùng quy tắc biên với parser, không phải gold độc lập hoặc đánh giá chuyên gia.

| Mẫu cần đọc | ID | Title | Body chars | Heading / block | QC |
| --- | ---: | --- | ---: | ---: | --- |
| Ngắn | 257576 | Phác đồ điều trị bệnh tay chân miệng theo hướng dẫn của bộ y tế | 3.144 | 3 / 17 | accepted |
| Dài | 283325 | Thoái hóa thần kinh và những điều cần biết | 14.222 | 19 / 97 | accepted |
| Review | 235085 | Giới thiệu tổng quan về bệnh viện 30/4 | 6.554 | 14 / 71 | review |

Review khác ở email: DOM có `[email protected]`, JSON có email thật. Giữ
`longchau_dom_cms_content_mismatch`, không nới QC. Bài này có đầy đủ raw/text trong records/quarantine.
CSV/JSONL báo cáo có 600 ký tự đầu/cuối, metadata, selector/version, block/heading, HTTP/QC/lý do lỗi.
Text lưu của 50 bài dài **3.209–14.266 ký tự**, không bị giới hạn theo preview. 49 accepted được export.
Đọc toàn bài và tham chiếu raw cạnh nhau tại `review_100.html` hoặc `records/<id>.json`.
Không có bảng trong 50 HTML này; giữ bảng/đơn vị/superscript/caption được kiểm tra bằng fixture mô phỏng.

Artifact local, ngoài Git và không upload HF:

- `runs/longchau_50_20261014_release/`: corpus thử, toàn bộ records/raw, audit/report/selection/snapshots.
- `runs/longchau_50_20261014_release.zip`: ZIP đầy đủ (~4,97 MB), dùng giữ checkpoint/recovery.
- `runs/longchau_50_20261014_release_diagnostics.zip`: báo cáo/code và một số raw mẫu (~0,58 MB).

## Chạy Kaggle/local và phục hồi

Kaggle: upload `check_longchau_50.ipynb`, bật Internet, Run All. Không cần clone repo/GPU/Chrome.
`LIMIT = 100` thử 100 URL. `SOURCE_PARQUET` nhận file `id`, `url` tự cung cấp, gồm `missing_links.parquet`;
default tải nguồn HF đã ghim revision/hash. Token optional từ môi trường/Kaggle Secret, không in log.
`MAX_NEW`, `ID_FROM`/`ID_TO` inclusive, delay/timeout/retry/robots ở ô cấu hình.

Local, từ root repo với môi trường có dependencies notebook:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_notebook_longchau.py' -v
.venv\Scripts\python.exe scripts/check_longchau.py --limit 50 --seed 20261014 --out runs/longchau_smoke
.venv\Scripts\python.exe scripts/check_longchau.py --source data/missing_links.parquet --limit 100 --id-from 200000 --id-to 300000 --out runs/longchau_100
```

Resume: chạy lại cùng lệnh/output, giữ nguồn/mẫu/code/delay/retry/robots; `MAX_NEW` có thể đổi.
Kaggle đặt `RESUME_RUN_DIR` tới thư mục run đầy đủ đã giải nén trong Input, giữ cấu hình.
Lỗi được thử lại, success hợp lệ không gọi mạng lại. Cooldown chưa hết có thể tiếp tục hoãn.
ZIP diagnostics chỉ giữ một số raw mẫu, không đủ phục hồi toàn run.

Đổi parser/config hoặc tái trích text trafilatura cũ: dùng output/RUN_TAG mới và recovery:

```powershell
.venv\Scripts\python.exe scripts/check_longchau.py --limit 50 --out runs/longchau_reextract --recovery-source runs/longchau_smoke
```

Recovery chỉ reuse 2xx raw đúng hash và ID/URL, chạy parser/QC mới; 403/challenge/error còn pending.
Auditor chặn legacy Long Châu accepted chưa re-extract, không mặc nhiên coi text trafilatura cũ là đúng.
Notebook chính dùng `RECOVERY_RUN_PATH` + `RUN_TAG` mới, default hậu tố `_efetch_longchau`;
`RESUME_RUN_PATH` chỉ cho cùng run. `POSTPROCESS_ONLY` không nâng cấp text: run Long Châu legacy
cần recovery trước export. Upload HF/config repo/token giữ cơ chế hiện có ở notebook chính.

Sửa `scripts/longchau.py`, `scripts/priority_probe.py`, `scripts/corpus_runner.py`, `scripts/corpus_audit.py`;
nhúng lại cả ba notebook bằng `python scripts/build_longchau_notebooks.py`.
Builder chạy lặp lại không đổi notebook. `build_domain_samples_notebook.py` vẫn tái lập
94 hostname/1.764 URL và giữ route Long Châu mới.

## Test và giới hạn

115 test notebook cũ + 25 Long Châu: **140 tests passed**. Sau thay đổi cuối chạy lại
25 Long Châu và 16 domain/IP/inventory: tất cả passed. Test bao gồm ba fixture thật với title/sapo/
đoạn kết/medical blocks/headings đối chiếu độc lập qua DOM, hai trang bệnh chứa phần chưa render,
ngày/số/“dược sĩ”/phủ định/cảnh báo/table/caption; session/TLS/header, backoff/cooldown qua resume,
robots/403/SSL, gián đoạn giữ success và sửa publication, re-extract raw cũ, hash/truncation,
thực thi notebook smoke độc lập với nguồn local. Retry/403/SSL/gián đoạn là mô phỏng offline,
không trình bày thành kết quả mạng thật.

Chưa chạy trực tiếp trên Kaggle, chưa crawl hết 79.598 URL, đo tốc độ tối đa hoặc chấm expert gold.
Chưa kiểm chứng layout ngoài mẫu này. Không suy ra IP Kaggle bị chặn/không bị chặn từ test local
hay lỗi setup Chrome. Cấu trúc website đổi sẽ có review/error; không dùng generic extraction để tăng PASS.
