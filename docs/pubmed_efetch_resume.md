# Sửa EFetch timeout và resume checkpoint — 15/10/2026

Code mới nằm trong `scripts/pubmed_efetch.py`, `scripts/pubmed_resume.py`, `scripts/corpus_checkpoint.py`
và đã được nhúng vào [notebook corpus chính](../notebooks/crawl_corpus_kaggle_hf_upload.ipynb).

## Hành vi mới

- Lưu body gốc của cả response lỗi; HTTP 400 có `Timeout`, `timed out`, `Empty Response` được xem là tạm thời.
  HTTP 400 thường, invalid UID/parameter không retry trong cùng lượt. 403/SSL cũng không retry liên tục.
- Default 100 PMID/batch, 1 worker, gap 0,5 giây, 5 attempts, timeout 10/90 giây, budget 300 giây/batch request.
  Exponential backoff + jitter và Retry-After số giây/HTTP-date; không có redirect/retry ngầm ngoài pacing.
- Batch lỗi ghi `pubmed_batch_failures/`, request log/raw; URL giữ pending, tiếp tục batch khác.
  Batch tạm thời còn lỗi chia 100 → 50 → 25 → … đến 1 PMID; cùng PMID của nhiều corpus ID vẫn được ghép đúng.
- Fallback có tối đa 50 GET và 900 giây/root batch. Cuối lượt thử pending tạm thời thêm một vòng.
  Cooldown server dài hoặc 3 root batch liên tiếp không lấy được bản ghi thì hoãn phần còn lại, không làm notebook lỗi.
  Giới hạn này tránh vòng retry vô hạn khi API lỗi diện rộng; có thể chỉnh ở ô cấu hình.
- `pubmed_pending.csv` và summary ghi pending rõ ràng. Không tạo record hoàn tất từ HTTP/XML lỗi.
  Audit/export/upload corpus chỉ hoàn tất khi đủ checkpoint; batch lỗi không làm `Save & Run All` thất bại.
  Sai hash/dữ liệu/config vẫn là lỗi cần xử lý, không được che thành pending.

Parser/schema XML vẫn `pubmed-efetch-v1`; transport là `pubmed-efetch-transport-v2`.
Title, toàn bộ abstract/nhãn và việc ghép theo PMID giữ nguyên.

## Chạy lại ZIP của bạn trên Kaggle

1. Thêm ZIP đầy đủ `ids_5979207_7061937_synced_vi_en_zh_efetch.zip` vào Kaggle Input và giải nén nếu cần.
   Không dùng `_diagnostics.zip`, vì gói đó chỉ chứa một số raw/record mẫu.
2. Mở notebook corpus chính mới, bật Internet và chỉnh ô cấu hình:

```python
ID_FROM = 5979207
ID_TO = 7061937
RESUME_RUN_PATH = '/kaggle/input/<ten-input>/ids_5979207_7061937_synced_vi_en_zh_efetch'
POSTPROCESS_ONLY = False
PUBMED_USE_EFETCH = True
PUBMED_UPGRADE_EFETCH_SNAPSHOT = True
MAX_NEW = None
```

`RESUME_RUN_PATH` phải trỏ tới **thư mục** có `manifest.json`, `sample.jsonl`, `records/`,
`pubmed_records/`, `pubmed_batches/`, `raw/`, các snapshot và `corpus_config.json`.
Thay `<ten-input>` bằng đường dẫn Input thật. Run được copy sang Working khi chưa có;
output session đang có sẽ được giữ, không copy đè Input.

3. Run All. Mục snapshot sẽ in `completed: 6000`, `pending: 104000` sau kiểm tra dữ liệu,
   và log đầu crawler có `event: resume`, `transport_version: pubmed-efetch-transport-v2`.
   Chỉ URL chưa có record EFetch hợp lệ được lên lịch; batch XML đã lưu phục hồi phần ghi dở mà không GET lại.
4. Khi còn pending, notebook vẫn xuất checkpoint đầy đủ nhưng không đánh dấu corpus complete.
   Lượt sau tiếp tục cùng output/Input checkpoint; kiểm tra `pubmed_pending.csv`, summary và requests/raw.

Upgrade chỉ thay module EFetch và trường transport/config tương ứng trong `corpus_config.json`.
Kiểm tra SHA core/runner/probe cũ, kiểm tra AST của ba hàm XML parser không đổi, xác minh sample/ID/URL,
raw/text SHA và XML trước khi thay code. `records/`, `pubmed_records/`, `raw/`, `pubmed_batches/`,
manifest nguồn/tiến độ không bị ghi đè bởi bước upgrade. Backup code/config và journal nằm ở `snapshot_history/`
và `pubmed_upgrade_journal.json`; gián đoạn giữa cập nhật code/config được hoàn tất lại khi resume.
Giữ runner/core/probe và cấu hình domain khác của run cũ. Đổi parser/schema hay route khác cần recovery trong run mới.
`POSTPROCESS_ONLY=True` không nâng cấp transport hoặc gọi mạng.

## Checkpoint định kỳ bền vững

Default trong notebook: `CHECKPOINT_ENABLED=True`, `CHECKPOINT_UPLOAD_ENABLED=True`,
mỗi 10.000 URL mới hoặc 900 giây, và cuối lượt. Kiểm tra cadence ở ranh giới batch, không ghi ZIP giữa lúc ghi record.
Runner v7 áp dụng checkpoint cho mọi engine, gồm Long Châu/Requests/Selenium, kiểm tra sau khi record
đã ghi atomic. EFetch dùng chung manager; runner legacy vẫn có manager EFetch riêng tương thích.
[Bản sửa checkpoint chung và Long Châu v2](longchau_resume_v2.md).
Kaggle Secret `HF_TOKEN` cần quyền ghi dataset `AncientWings/AncientWings_R2AI_STAGE3_ds`;
có thể chỉnh repo/secret/cadence hoặc tắt upload trong ô cấu hình. Token không được lưu trong config/log.

ZIP đầy đủ local: `<run>_checkpoint.zip`, cùng JSON ghi count/source/sample/checksum.
ZIP được ghi vào file tạm ngoài run, kiểm tra CRC rồi replace; lỗi đóng gói không phá ZIP tốt trước đó.
HF dùng `create_commit` với hai file cùng commit:

- `checkpoints/<run>/latest.zip`
- `checkpoints/<run>/latest.json` (SHA-256/size/count và hash nguồn/sample)

Tham khảo [Hugging Face create_commit](https://huggingface.co/docs/huggingface_hub/package_reference/hf_api#huggingface_hub.HfApi.create_commit).
LFS upload chưa được commit sẽ không thay bản checkpoint đang tham chiếu. Backup giữ `complete=False`,
khác với corpus đã audit/export; file `checkpoint_progress.json` ghi tiến độ của snapshot.
Nếu thiếu token hoặc upload lỗi, crawler tiếp tục và ghi `upload_status=failed`; ZIP local vẫn có.
Kiểm tra `checkpoint_upload_state.json` và log `periodic_checkpoint` để biết backup HF đã thành công hay chưa.
Huỷ phiên ngay trước lần checkpoint kế tiếp có thể mất phần mới chưa được upload; resume từ checkpoint bền vững gần nhất.
Full ZIP có thể lớn; giảm cadence URL quá thấp sẽ tăng thời gian/traffic upload.

Khôi phục từ HF: tải cả `latest.json` và `latest.zip` ở **cùng revision/commit**, kiểm tra size/SHA-256,
giải nén ZIP, rồi dùng thư mục đó làm `RESUME_RUN_PATH`. Không dùng các shard corpus cuối cùng thay ZIP checkpoint.

## Kiểm chứng

Đã đọc ZIP thật 53.881.787 byte: 110.000 URL, 6.000 completed, 5.992 accepted, 8 review,
104.000 pending, 60 batch XML thành công và request thứ 61 HTTP 400.
Body lỗi 295 byte báo `External viewer error: Empty Response` / `Status: Timeout`;
body này được lưu làm regression fixture `tests/fixtures/pubmed/efetch_timeout_400.xml`.

Trên bản sao riêng: upgrade nhận đúng 6.000/104.000, xác minh 60 raw XML,
**12.125 file dữ liệu/manifest được bảo vệ không đổi SHA-256**; upgrade lần hai idempotent.
Đã thực thi ô snapshot và ô chuẩn bị crawl của notebook trên checkpoint thật: nạp transport mới,
giữ runner v5/config tương thích, giữ 6.000 kết quả; subprocess crawl được mock, không chạy 104.000 URL.
Test kiểm tra retry 400, invalid-parameter/SSL, split đến PMID lỗi, pending retry cuối lượt,
cooldown qua resume, giới hạn fallback, batch lỗi không chặn batch sau, MAX_NEW, transaction gián đoạn,
hash/parser khác bị chặn, ZIP/CRC/backup cũ và publish hai file trong một commit.
Bộ 159 test notebook đã qua; chạy lại 20 test resilience cũng qua, gồm regression mới:
batch hết budget thời gian vẫn giữ pending và không chặn batch khỏe phía sau.

Các tình huống retry/split/gián đoạn/upload HF là test mô phỏng offline.
Chưa chạy notebook trực tiếp trên Kaggle hoặc upload checkpoint thật lên HF trong lượt sửa này.
Không báo phần chưa chạy thành kết quả mạng thật.

Sau khi sửa helper, chạy `python scripts/build_longchau_notebooks.py` để nhúng lại notebook corpus,
giữ parser/route Long Châu hiện có và tạo lại notebook check local ngoài Git.
