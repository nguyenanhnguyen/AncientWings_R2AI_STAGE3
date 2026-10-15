# Cell đo nhịp truy cập Long Châu

Tạo lại notebook local (vẫn được gitignore):

```powershell
python scripts/build_longchau_smoke_notebook.py
```

Trong `notebooks/check_longchau_50.ipynb`, cell **Đo nhịp truy cập và header giới hạn**
chạy trước cell crawl 50 URL. Bật Internet trên Kaggle; không cần GPU hay Chrome.
Fetcher/parser lấy từ đúng snapshot notebook corpus chính, dùng `curl_cffi`, 1 worker,
TLS được xác minh. Cell không upload Hugging Face.

| Giai đoạn | Nghỉ sau mỗi response | Số URL mặc định |
| --- | ---: | ---: |
| 1 | 10 giây | 20 |
| 2 | 7,5 giây | 20 |
| 3 | 5 giây | 20 |

Đây là 60 URL duy nhất được chọn phân tầng từ nguồn đang cấu hình, giữ nguyên `id`/`url`.
Tốc độ thực còn gồm thời gian tải và xử lý; phép đo không tạo burst để tìm ngưỡng chặn.
Mỗi request có 1 attempt; redirect được ghi từng hop và vẫn giữ nhịp.
`RATE_CHECK_STAGES` cho phép đổi số mẫu/nhịp trong giới hạn 5–60 giây và tối đa 500 URL.
`RATE_CHECK_MAX_SECONDS = 1200` giới hạn thời gian một lượt.

Cell dừng ở 429, 403, challenge kể cả HTTP 200, lỗi kết nối hoặc trang không xác minh được.
`Retry-After` được lưu thành gate; gate từ run hiện tại/resume/recovery được đọc và giữ lại.
Gate quan sát được cũng chuyển sang run crawl phía sau. Khi rate check chưa hoàn tất,
Run All hoãn cell crawl 50 URL. Không reset cooldown hay thay IP để tiếp tục.

`RATE_CHECK_RUN_TAG` phải khác `RUN_TAG`. Chạy lại với cùng tag/cấu hình sẽ bỏ qua URL
đã thành công sau khi xác minh raw/text hash. Mẫu hoặc code/cấu hình thay đổi cần tag mới;
gate của run crawl vẫn được tôn trọng. Giữ nguyên thư mục rate check và thư mục run crawl
để resume. Với Kaggle session mới, giải nén ZIP rate check vào đúng `RATE_CHECK_RUN_TAG`
trong `/kaggle/working/runs/`, đồng thời trỏ `RESUME_RUN_DIR` đến run crawl cũ nếu có.

Các file trong `runs/<RATE_CHECK_RUN_TAG>/` và ZIP đầy đủ cạnh thư mục:

- `rate_check_summary.json`: kết quả từng nhịp, HTTP, số URL truy cập được, lý do dừng,
  thời gian được thử lại và header giới hạn nếu server cung cấp.
- `rate_check_requests.jsonl`: từng request/hop, nhịp, HTTP, `Retry-After`,
  `RateLimit-*`/`X-RateLimit-*`, dấu hiệu Cloudflare/challenge. Không ghi cookie/token.
- `rate_check_results.csv`, `probe_records/`, `raw/`: ID/URL, trạng thái, toàn bộ text,
  HTML gốc và SHA-256. Đây là dữ liệu chẩn đoán, không tự nhập vào corpus accepted.
- `rate_check_config.json`, `rate_check_snapshot.py`, `_runtime/`: mẫu và code đã dùng,
  có hash để kiểm tra resume.

`accessible` chỉ có nghĩa lấy được trang HTTP 2xx đúng bài, không phải kết luận QC accepted.
Nhịp thành công trên mẫu nhỏ **không xác định quota của website** hoặc bảo đảm crawl hết
79.598 URL. `Retry-After` chỉ cho biết thời gian nghỉ. Không thấy header hạn mức thì báo
không có bằng chứng server công bố quota; không suy ra quota từ số URL trước khi bị chặn.
Kết quả phụ thuộc thời điểm và mạng/IP chạy, nên test Windows không thay cho test Kaggle.

Muốn chỉ chạy phép đo từ CLI:

```powershell
python scripts/longchau_rate_check.py --out runs/longchau_rate_local
```

Có thể thêm `--cooldown-dir <run-cu>` để đọc gate có sẵn; nguồn này không bị ghi đè.
`--share-cooldown-dir <run-tiep-theo>` chỉ định thư mục output được nhận gate.
Tắt `RATE_CHECK_ENABLED` nếu chỉ chạy smoke cũ; crawler vẫn tôn trọng gate hiện có.

## Kết quả chạy thật ngày 15/10/2026

Đã chạy chính các cell setup/chọn nguồn/rate check từ notebook sinh ra, trên **Windows local**,
nguồn ViBioMIR đã ghim hash (1.220.598 URL), không chạy thêm lượt smoke 50 URL.
Phép đo mất 485,226 giây, 60 URL/60 HTTP requests, giữ đúng nhịp sau mỗi response.

| Nghỉ sau response | HTTP 200 | Tốc độ thực quan sát |
| --- | ---: | ---: |
| 10 giây | 20/20 | 5,602 request/phút |
| 7,5 giây | 20/20 | 7,413 request/phút |
| 5 giây | 20/20 | 10,554 request/phút |

Không có 403/429/challenge; không có header công bố quota. Đây là kết quả truy cập trên mẫu
và mạng local đã thử, chưa xác nhận khả năng chạy toàn bộ domain hay IP Kaggle.
QC nội dung độc lập: 59 accepted, 1 review vì `longchau_dom_cms_content_mismatch` (ID 235085).
Đã xác minh mapping ID/URL, hash raw/text, khoảng nghỉ và CRC của ZIP.
`cooldown_not_before_utc` cuối phép đo chỉ là khoảng nghỉ 5 giây bình thường, không phải bị chặn.

Artifact local ngoài Git: `tmp/longchau_rate_live_20261015T024452Z/`, gồm log và thư mục/ZIP
`runs/longchau_50_seed20261014_v2_rate_v1`. Đã sửa lỗi nhận diện Windows thành Kaggle do
đường dẫn `/kaggle/working` tồn tại trên Windows; `environment_correction.json` ghi việc sửa
duy nhất nhãn môi trường, giữ nguyên số đo và bản gốc để đối chiếu.
11 test cho rate check và 25 test Long Châu đã đạt; có kiểm tra cả notebook tự chứa,
429/challenge, gián đoạn/resume, gate và nhận diện môi trường.
