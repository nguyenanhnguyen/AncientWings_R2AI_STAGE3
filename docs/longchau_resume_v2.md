# Long Châu v2 — checkpoint chung, cleaner và tiến độ

Bản sửa ngày 15/10/2026 được nhúng vào notebook corpus chính, domain samples và notebook
check local ngoài Git. Parser là `longchau-v2`, runner là `corpus-runner-v7`.

## Các thay đổi

- Checkpoint do runner chung quản lý cho EFetch, Long Châu/curl, Requests và Selenium.
  Callback lưu engine record và canonical record trước khi đóng gói; cadence đếm mỗi source ID mới một lần.
  Không tạo backup 0 record khi bước EFetch rỗng. Backup cuối lượt chứa tiến độ của tất cả engine,
  kể cả khi dừng do cooldown hoặc KeyboardInterrupt; lỗi report vẫn cho bước backup cuối cơ hội chạy.
- Cadence mặc định vẫn mỗi 10.000 URL mới hoặc 900 giây, kiểm tra ở ranh giới record/batch.
  `failure_retry_seconds` chỉ hạn chế thử lại backup lỗi, không làm sai cadence sau backup thành công.
  HF vẫn publish ZIP và checksum JSON trong một commit; thiếu token/upload lỗi giữ ZIP local.
- Cleaner loại nhóm liên kết ngay sau nhãn “Xem thêm”/“Tìm hiểu thêm”/“Tham khảo thêm”,
  gồm cả dạng list và các paragraph chỉ chứa link. Giữ paragraph y khoa có liên kết, list chứa prose
  và heading/prose sau nhóm liên quan; không xóa từ khóa trên toàn text.
- Log engine có `completed_this_invocation`; runner còn in counter chung theo source ID cho toàn lượt.
  Diagnostics ưu tiên counter chung để bước Long Châu không che tiến độ PubMed trước đó.
  Tốc độ được tính từ wall time; ETA không suy từ tốc độ khi đang hoãn vì cooldown.
- Delay Long Châu mặc định **5 giây**, 1 worker, giữ Retry-After và gate qua cả resume lẫn recovery.
  Delay thấp hơn có thể vẫn bị rate limit; 5 giây cũng không bảo đảm quota của website.
  [Cloudflare 1015](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1015/)
  là giới hạn truy cập tạm thời; chờ cooldown, không thử liên tục hoặc xóa gate để ép chạy.

## Phục hồi run `204274–205274`

Log (14) chọn **1.001 URL**, xử lý 555: 553 accepted, 1 review, 1 HTTP 429; còn 446 chưa thử.
429 ở ID `204828` có `Retry-After: 86400`, Error 1015; gate của run đó là
**2026-10-16 02:14:46 giờ Việt Nam**. Đây là mốc được lưu, không bảo đảm website sẽ bỏ chặn đúng lúc đó.
Backup HF ghi trong diagnostics chỉ chứa 0 completed do bug EFetch-only đã được sửa.

1. Lấy **ZIP đầy đủ** `ids_204274_205274_synced_vi_en_zh_efetch_longchau.zip` từ Kaggle Output,
   giải nén/thêm vào Kaggle Input. ZIP `_diagnostics.zip` chỉ có 7 records/raw mẫu, không đủ phục hồi 555 URL.
2. Dùng notebook corpus mới và cấu hình:

```python
ID_FROM = 204274
ID_TO = 205274
RESUME_RUN_PATH = None
RECOVERY_RUN_PATH = '/kaggle/input/<ten-input>/ids_204274_205274_synced_vi_en_zh_efetch_longchau'
RUN_TAG = 'ids_204274_205274_longchau_v2_recovery'
POSTPROCESS_ONLY = False
LONGCHAU_DELAY = 5.0
MAX_NEW = None
```

`RECOVERY_RUN_PATH` trỏ tới thư mục có `manifest.json`, `records/`, `raw/`, `longchau_request_gate.json`.
Giữ Internet bật để lấy nguồn/URL còn lại; Secret `HF_TOKEN` quyền ghi cho backup HF nếu sử dụng.

3. Recovery xác minh ID/URL/raw SHA rồi tái trích **554 HTML thành công** bằng parser v2,
   không GET lại chúng. Bao gồm bài review thiếu sapo: vẫn giữ review khi nguồn thiếu thật.
   Nguồn cũ không bị sửa; record cũ được giữ trong `recovery_records/` của output mới.
   Có 447 URL cần thử: ID 204828 lỗi 429 và 446 URL chưa crawl.
4. Recovery copy gate bằng `max(gate hiện tại, gate nguồn)`, không bỏ cooldown khi đổi run/config.
   Nếu còn cooldown, lượt mạng hoãn; checkpoint mới vẫn backup các record đã phục hồi.
   Kiểm tra `checkpoint_upload_state.json`: completed phải phản ánh records hiện tại,
   `upload_status=uploaded` mới là backup HF thành công.
5. Lượt sau dùng ZIP đầy đủ của **run v2** làm `RESUME_RUN_PATH`, tắt `RECOVERY_RUN_PATH`
   và giữ cùng `RUN_TAG`/cấu hình. Resume giữ các kết quả thành công, chỉ thử phần chưa lấy được.

Run mới tự có hậu tố `_longchau_v2`. Khi dùng RESUME cho run Long Châu cũ, ô snapshot sẽ báo cần
recovery **trước khi thay runtime hoặc dữ liệu**. Không sửa SHA/config cũ để ép dùng parser mới.
Run PubMed thuần cũ vẫn giữ runner/probe đã lưu và cơ chế EFetch transport upgrade tương thích.

## Kiểm chứng và giới hạn

Test offline kiểm tra backup theo URL/thời gian, run chỉ Long Châu, tắt EFetch, run mixed PubMed/Long Châu,
checkpoint Requests, Selenium/KeyboardInterrupt, 429 nghỉ 24 giờ, resume giữ record tốt, recovery giữ gate,
cleaner không mất prose y khoa, guard notebook không ghi đè run cũ và progress/ETA không đếm trùng engine.
Bộ **173 test notebook** và **11 test domain/IP** đều qua. Builder tạo lại không đổi notebook;
cả ba notebook có schema/code hợp lệ. Startup checkpoint PubMed thật vẫn nhận 6.000 completed/104.000 pending,
giữ runner v5 và toàn bộ dữ liệu được bảo vệ không đổi, không thực thi phần crawl 104.000 URL.

Đối chiếu 6 HTML thành công trong diagnostics thật: 5 bài có text giống hệt; ID 204780 bỏ đúng
3 block liên quan, giữ title/heading/nội dung cuối bài, thiếu sapo vẫn review. Raw/text SHA đầu vào đúng,
ZIP nguồn của người dùng không đổi. Chưa có đủ raw để xác minh hoặc tái trích toàn bộ 554 HTML trong lượt sửa này.
Không chạy lại mạng Long Châu hoặc upload checkpoint thật lên HF khi kiểm thử; retry/upload là mô phỏng.

Sửa helper rồi chạy `python scripts/build_longchau_notebooks.py` để đồng bộ notebook.
`scripts/corpus_diagnostics.py` là source canonical của diagnostics snapshot.
