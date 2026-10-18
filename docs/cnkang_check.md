# Cnkang: notebook check và đồng bộ crawl chính

Notebook mới: [check_cnkang.com.ipynb](../notebooks/check_cnkang.com.ipynb).
Mặc định 500 URL, seed 20261020, một worker và khoảng nghỉ tối thiểu 1,5 giây
sau mỗi request, gồm robots, redirect và retry. Không tự chạy toàn corpus.

## Lịch sử và bản v6 được lưu

Notebook người dùng cung cấp được giữ nguyên tại
[check-r2ai-link.original.ipynb](references/cnkang/check-r2ai-link.original.ipynb);
cell v6 được lưu riêng tại
[parser_v6_original.txt](references/cnkang/parser_v6_original.txt).
Không thực thi notebook tham chiếu khi build hoặc khi chạy notebook mới.
Vì vậy xóa bản Downloads không làm mất mã gốc.

Notebook tham chiếu có log hai vòng 120 URL, nhưng chỉ in một phần URL và không
nhúng raw HTML hoặc manifest đầy đủ. Đã giữ 60 URL xuất hiện trong output hoặc
danh sách fallback trong known_history_partial.jsonl. Danh sách này không chứng
minh đầy đủ mọi lượt cũ, cũng không chứng minh tất cả URL fallback đã được tải.
Nó được dùng để loại trừ bảo thủ, không dùng làm mẫu thay cho 500 URL mới.
Thử tái dựng theo seed trên corpus hiện có không khớp tất cả URL hiển thị của
vòng thứ hai, nên không coi mẫu tái dựng là lịch sử đầy đủ.

Để chạy 500 URL mới:

1. Gắn dataset lighth/r2ai-stage3 và bật Internet.
2. Gắn output cũ chứa review.jsonl, samples.jsonl hoặc sample_manifest.jsonl.
3. Đặt HISTORY_PATHS tới các file/thư mục này và HISTORY_COMPLETE=True sau khi
   kiểm tra đã bao phủ các lượt chạy trước.
4. Restart & Run All. Giữ ZIP đầy đủ để resume trong phiên Kaggle sau.

Nếu chưa có lịch sử, Run All vẫn tạo báo cáo/CSV/Parquet rỗng đúng schema và ZIP,
với trạng thái history_required, không gửi request. Đây là trạng thái có chủ đích,
không phải lỗi biến/hàm hoặc âm thầm dùng lại URL cũ. Có thể bổ sung lịch sử rồi
chạy lại trong cùng output nếu chưa có manifest mẫu thật.

## Mã dùng chung

- scripts/cnkang.py: port quy tắc v6 sang parser dùng chung; strict encoding
  candidates, detailc/endText/conmain, đường dẫn DOM, bảng, synopsis có anchor,
  parser/source flags và tái trích raw để audit.
- scripts/cnkang_transport.py: Requests tuần tự, robots theo origin, HTTPS trước,
  fallback HTTP chỉ cho lỗi kết nối/server; không fallback để né 403/429.
- scripts/cnkang_check.py: canonical giữ path/query, gom ID, phân tầng đủ nhánh,
  manifest bất biến, checkpoint, báo cáo và schema artifact ổn định.
- scripts/build_cnkang_notebooks.py: nhúng snapshot/hash vào notebook check và
  notebook crawl chính. Domain samples dùng cùng parser/QC.

Crawl chính có cấu hình CNKANG_* riêng. Cnkang luôn kiểm robots và không dùng
Selenium, độc lập với cấu hình chung của các domain khác. Source flags giữ riêng;
quality_status của cnkang thể hiện lỗi parser, không xác nhận chất lượng nguồn.
Raw và trường chẩn đoán ở sidecar record, hợp đồng cột corpus không thay đổi.
Auditor tái trích raw bằng cùng parser, có kiểm tra text, encoding, selector, bảng,
metadata và cờ nguồn. Run cũ cần RUN_TAG mới + RECOVERY_RUN_PATH; cooldown được giữ.

Đọc review_report.md, summary_by_branch.csv và bằng chứng trong results.jsonl.
Thiếu ngày không biến thành fetch thất bại; short text, thứ tự giảm, phân trang và
bố cục mơ hồ cần đọc lại raw. Không tự đảo đoạn, đoán nội dung y khoa hoặc crawl
link bài liên quan như phần tiếp theo.

## Xác minh

Chạy:

    .venv/Scripts/python.exe -X utf8 scripts/build_cnkang_notebooks.py
    .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_cnkang_v6_check.py -v
    .venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -p test_notebook_cnkang_parser.py -v

Các kiểm thử dùng HTML mẫu và HTTP giả lập; có kiểm tra phân bổ đúng 500, resume
không chọn mẫu/tải lại, encoding, conmain lồng sâu/mơ hồ, synopsis cùng dòng,
abstract/bảng/URL hợp lệ, PUA, 403/429, và không dùng browser trong runner chính.
Không có raw 120 trang cũ để xác nhận các mốc v6 trên cùng baseline, và chưa crawl
live 500 trang bằng notebook mới.
