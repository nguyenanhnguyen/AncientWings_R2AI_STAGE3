# Review R2: checkpoint Windows cnkang.com — 20/10/2026

**Đã sửa và đồng bộ vào crawler chính.** Bộ test cuối đạt 66/66; replay offline
50 raw với lỗi ghi/crash được chèn đạt 50/50 sau resume, audit 50/50, text hash
50/50 giữ nguyên. Không gửi request mạng trong lượt R2.

## Cơ chế ghi và dừng

Module production mới scripts/cnkang_checkpoint.py dùng temp duy nhất trong cùng
thư mục đích, ghi đủ dữ liệu, flush và fsync trước replace nguyên tử. Chỉ retry
PermissionError/access denied/sharing violation: tối đa 3 lần, backoff 0,1 và 0,2
giây, budget retry 2 giây. Retry dùng lại chính dữ liệu đã flush, không phát GET
lại. Lỗi khác như hết dung lượng dừng ngay.

Nếu replace vẫn lỗi, file đích cũ không bị xóa/truncate. Bản tạm hoàn chỉnh được
giữ với hậu tố .recovery khi có thể đổi tên riêng; nếu đổi tên cũng bị từ chối thì
giữ temp gốc. .recovery được bộ ZIP checkpoint giữ lại và không bị nhận nhầm là
record *.json đã commit.

Lỗi được đưa ra dưới dạng CHECKPOINT_WRITE_FAILED với đường dẫn, thao tác, số lần
thử, bản tạm và nguyên nhân/errno/WinError gốc. Luồng crawl dừng, không biến lỗi
lưu local thành fetch_failed của website, không gọi callback thành công trước
khi record được commit. Chẩn đoán được in ra và lưu best effort vào
cnkang_checkpoint_error.json.

Một OS lock giữ một writer cho mỗi run. Writer thứ hai dừng với
CHECKPOINT_WRITER_BUSY. Khi process chết, hệ điều hành nhả lock; không cần xóa
file .cnkang_writer.lock để chạy lại.

## State, raw và resume

- State đọc từ file chính và các bản .tmp/.recovery, kể cả tên .json.tmp cũ.
  not_before và last_request được hợp nhất bằng giá trị lớn nhất; việc ghi mới
  không làm giảm cooldown đã có. State hỏng/ghi dở sẽ chặn chạy tiếp thay vì
  tự reset thành trạng thái rỗng.
- HTTP 429 cập nhật cooldown trước khi ghi raw, để lỗi raw/checkpoint không làm
  mất Retry-After. Recovery từ run cũ cũng đọc state pending và hợp nhất bảo thủ.
- Raw HTML, raw gzip và text được ghi nguyên tử, tên chứa content hash. Bản ghi
  cùng URL hoặc một lần thử sau không sửa mất raw/text mà record cũ đang tham chiếu.
- Response 2xx được lưu kèm body hash vào cnkang_pending trước khi ghi raw/parse.
  Sau crash, có thể dựng lại raw và text từ response này, hoặc commit bản record
  tạm hoàn chỉnh đã kiểm hash. Không tải lại trang khi đã có checkpoint hợp lệ.
- Record theo ID là căn cứ resume. Journal flush/fsync; lần append sau sửa dòng
  cuối bị ghi dở. Journal không được dùng để đếm số tài liệu độc lập.
- Chỉ dữ liệu đã ghi/kiểm hash mới được đưa vào record cuối. Crawler chính dùng
  cùng writer cho publication của cnkang. Helper mới có snapshot/hash trong
  crawler, notebook check và identity của run.

## Kiểm thử

Lệnh đã chạy, kết quả **66/66 đạt**, gồm 19 test R2 và 47 test/parser/tích hợp
đã có:

    .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p '*cnkang*' -v

Các ca R2 bao gồm:

- Khóa deny-delete thật qua Windows kernel: giữ khóa đến hết ba lần thử; nhả khóa
  sau lỗi đầu và retry thành công. File cũ giữ nguyên khi bị khóa.
- Disk full không bị retry như sharing violation; temp khác tên giữa các lần ghi.
- Cooldown mới trong bản pending không mất khi restart, hợp nhất với state cũ
  hoặc khi lấy từ ZIP vốn bỏ qua .tmp.
- Lỗi trước GET không phát request; lỗi state sau khi nhận response vẫn giữ được
  response để resume; 429 giữ cooldown kể cả khi ghi raw thất bại.
- Crash tại các mốc response bundle, raw, temp record, record commit và journal.
  Có test process con gọi os._exit sau ghi raw/temp record; writer được nhả và
  process sau phục hồi mà không GET.
- Record chưa commit không được callback/publication; resume từ run và ZIP không
  nhân đôi ID. Publication trong crawler chính chịu được khóa tạm thời.
- Deadline R1, F1 formattext/pager, audit, 403/429 và resume vẫn qua hồi quy.

Một test R1 dùng budget giả lập 1,5 giây từng kết thúc ở worker_start khi chạy
cùng tác vụ I/O, thay vì tới DNS. Đã làm nóng worker ở riêng test kiểm stage DNS;
test startup/deadline vẫn giữ nguyên. Đây là điều chỉnh để test đúng giai đoạn,
không nới deadline production.

## Replay 50 raw thực tế

Dùng đúng manifest/raw từ runs/cnkang_r1_50_20261020_pass2, SHA manifest:
32d461683fd4b4e746003149918541305754d6c24515e2d3860416f4c6edcd65.
Đây là replay dữ liệu đã có, không phải 50 URL live mới.

| Tình huống | Số record |
|---|---:|
| Record bị khóa tạm thời, hai lỗi rồi thành công | 10 |
| Record bị khóa hết ba lần thử, dừng rồi resume | 5 |
| Raw bị khóa hết ba lần thử, dừng rồi resume | 5 |
| State hoàn tất request bị khóa, dừng rồi resume | 5 |
| Crash sau raw | 5 |
| Crash sau flush temp record, trước replace | 5 |
| Crash sau commit record | 5 |
| Luồng thông thường | 10 |

Lượt cuối hoàn tất trong 37,065 giây: 80 sự kiện sharing/crash được chèn;
15 lần dừng đúng CHECKPOINT_WRITE_FAILED, 15 crash giả lập; 50/50 khôi phục
không cần gọi GET lần nữa. Có đúng 50 ID/record, 50/50 raw audit đạt và 50/50
text hash khớp baseline. Cơ chế trả response offline được gọi đúng một lần/ID;
không có request ra website.

35 trang sạch parser và 15 còn cờ review, giống R1. R2 không thay parser/QC.
Lượt replay đầu được giữ riêng; sau khi thêm bảo toàn .recovery qua ZIP đã chạy
lại cùng 50 raw với snapshot cuối.

## Artifacts và sử dụng

- Code, config và output thử nghiệm chỉ ở notebooks/check_cnkang.com.ipynb,
  đã gitignore; giữ riêng output hai lượt.
- Lượt đầu: runs/cnkang_r2_checkpoint_50_20261020/.
- Lượt cuối: runs/cnkang_r2_checkpoint_50_20261020_pass2/, gồm run_config.json,
  sample_manifest.jsonl, case_results.jsonl, r2_review_summary.json,
  pass_outcome.json, records/raw/text, results.parquet và support snapshots.

Sau khi xử lý nguyên nhân khóa file, resume với cùng run/config/code để dùng
record/response đã lưu; giữ nguyên state và các bản recovery. Nâng phiên bản code
vẫn theo quy tắc RUN_TAG mới + RECOVERY_RUN_PATH, không ghi đè bằng chứng run cũ.
Đã kiểm trên Windows/Python 3.14/IPython; chưa chạy trực tiếp trên Linux/Kaggle.
F2/F3 và Q1–Q3 giữ cho các lượt sửa riêng.
