# 120ask V3 và xét nhập candidate corpus

## Cập nhật V3.1 — 20/10/2026

Parser hiện là `120ask-parser-v3.1`, gate `120ask-gate-v2`, policy
`120ask-admission-v2`; extractor family và schema Parquet giữ nguyên.
Tạo output run mới để replay raw cũ; không resume checkpoint hoặc tự chuyển nhãn
review có parser/policy hash cũ sang bản này.

- `manual_review_cohort.json` giữ tập mục review bắt buộc theo parser/gate/policy/sample
  hash. Mục cũ và nhãn EXCLUDE vẫn còn khi bổ sung mẫu thay thế; PARSER_ERROR trong
  mọi nhãn hợp lệ chặn readiness. Vẫn phải truyền MANUAL_REVIEW_PATH khi tổng hợp
  với nhãn đã điền; không tự tạo nhãn reviewer.
- Replay khóa cả hash record nguồn, kiểm mapping/metadata/raw trước khi skip,
  khôi phục raw output từ source hợp lệ nếu bản output mất/hỏng. Crawl mới kiểm
  fetch checkpoint và raw, không âm thầm gửi request bù khi resume; có thể tiếp
  tục từ fetch đã lưu nếu bị ngắt trước khi ghi parsed record. 429/challenge đã
  dừng run vẫn được giữ khi resume.
- Câu hỏi lưu `question_media`, `question_attachment_urls` với DOM locator,
  thuộc tính gốc và alt; nhận diện img/audio/video/source, src/data-src/data-original,
  poster và srcset/data-srcset. Media chưa giải quyết chuyển ESSENTIAL_MEDIA_REVIEW;
  không tự coi ảnh alt rỗng là trang trí. Raw auditor và candidate JSONL giữ các
  trường này; Parquet không thêm cột.
- Tổng hợp từ chối runtime/checkpoint khác hash hoặc raw đã mất/hỏng trước khi
  xuất lại candidate.
- Check notebook giữ sáu cell A/B: baseline V3 trước fix được đóng băng và kiểm
  hash trong `scripts/ask120_experiment_baseline.json`; candidate là source hiện tại.
  Baseline này chỉ phục vụ thí nghiệm, không dùng cho crawl production.

Test bổ sung: `tests/test_ask120_fixes.py`. Báo cáo triển khai:
[120ask_fixes_20261020.md](reports/120ask_fixes_20261020.md).

Notebook check giữ tên legacy notebooks/check_120ask_50.ipynb, nhưng LIMIT mặc định
là 1.000. MODE mặc định replay. Notebook vẫn được gitignore; tái tạo bằng:

    .venv/Scripts/python.exe -X utf8 scripts/build_120ask_notebooks.py

Builder cập nhật có giới hạn parser/core route ở hai notebook production/domain,
rồi build notebook check từ source hiện tại. Không gọi builder chung để tái tạo
các engine không liên quan. Hash parser trong cả ba notebook phải bằng source
scripts/ask120.py. Có thể chỉ build lại check bằng build_120ask_gate_notebook.py.

## Chạy trên Kaggle

1. Gắn ZIP check_120ask_20261018T022128241058Z.zip vào Kaggle Input.
2. Tải bản check_120ask_50.ipynb mới; để MODE='replay'.
3. Đặt INPUT_RUN_ZIP nếu tự tìm thấy nhiều/không có đúng filename. Chỉ chọn một
   trong INPUT_RUN_ZIP và INPUT_RUN_DIR.
4. Restart & Run All. Replay không cần Parquet/HF/Internet và không thực thi code
   trong ZIP; chỉ đọc manifest, sample, records và raw response cuối.
5. Đọc report.md, regression_comparison.csv, corpus_decisions.csv, summary.json.
   Tải ZIP đầy đủ và manual_review_sheet.csv.

Local tự tìm đúng ZIP trong Downloads nếu còn. Source/run cũ được giữ nguyên.
Output mới có timestamp dưới runs/; input raw được kiểm SHA-256 và copy vào output,
không thay text cũ bằng kết quả mới. Raw thiếu/hash sai thành EXCLUDE có reason,
không âm thầm gửi request để bù.

RESUME_OUTPUT_DIR chỉ trỏ tới output gate mới có cùng input, parser và policy.
Không trỏ tới run source v2. Checkpoint khác hash bị từ chối. Tổng hợp lại không
nhân đôi report, thread hoặc candidate.

## Parser và ba lớp quyết định

scripts/ask120.py V3 giữ riêng card, reply và turn; reply ID được lấy cả ở thẻ p.
Lưu DOM locator, quan hệ sở hữu, text gốc/clean/hash, normalization actions và
media URLs. Không tải audio hoặc phiên âm.

- Audio-only không còn được đếm là câu trả lời chữ.
- Mixed giữ text thực; fallback trong audio không đi vào text sạch.
- Markup legacy chỉ xử lý tag định dạng có bằng chứng, tối đa hai lượt entity
  normalization, giữ paragraph break và bất đẳng thức/gene.
- Published count so với card khi template quan sát khớp; card/block/reply count
  đều được giữ để audit. Không ép khớp bằng xóa nội dung.
- Không đoán tác giả cho từng reply khi card có nhiều reply. Follow-up không đủ
  bằng chứng sở hữu được lưu unresolved và không đi vào candidate hoàn chỉnh.
- Trùng main answer, lặp follow-up bệnh nhân/người trả lời và nghi render DOM
  lặp được phân loại riêng. Giữ dữ liệu nguồn để review, không tự xóa lời lặp.

Access status, parser status và corpus decision độc lập. QC accepted của production
không phải cổng nhập candidate. baseline_* giữ kết quả v2 của run đầu vào.

Thread INCLUDE cần câu hỏi thực, câu trả lời chữ, provenance, đúng sở hữu/vai/thứ tự,
không còn blocker/review áp dụng. Ngắn dưới 20 ký tự sau bỏ nhãn là REVIEW, không
kết luận sai y khoa. Nguồn có claim quảng bá được SOURCE_CLAIM_REVIEW mặc định.
Thiếu ngày hỏi đơn lẻ là warning. Audio-only, câu hỏi trống, thiếu câu trả lời trong
HTML đã tải hoặc raw lỗi không vào bản text lần này; diagnostics vẫn được giữ.

Trang INCLUDE_PARTIAL chỉ xuất các thread INCLUDE. Lỗi câu hỏi chung chặn tất cả
thread; lỗi audio/short ở thread độc lập không loại thread chữ tốt bên cạnh.

## Đầu ra và hợp đồng ID

results_baseline.jsonl và results_reparsed.jsonl ở hai file riêng.
qa_threads_all.jsonl (và tên diagnostics legacy qa_threads.jsonl) giữ mọi thread;
qa_threads_include/review/exclude.jsonl là các tập riêng.

corpus_candidates.jsonl giàu provenance: source ID, raw hash/path, parser/policy
hash, danh sách thread đã nhập/bỏ và reasons, source spans/DOM locator.
corpus_candidates.parquet là adapter đúng DOCUMENT_FIELDS hiện tại của
src/vibiomir/common/schema.py; không tự thêm cột production.

Một document mỗi ID nguồn, không lấy question ID trong URL hoặc thread index thay
ID. Text giữ câu hỏi và ranh giới từng người trả lời/lượt. Không tổng hợp lời nhiều
bác sĩ thành một khuyến nghị. Ngày là ngày hỏi, không đổi thành ngày trả lời.
Aliases cùng canonical question được báo, không tự mất mapping ID.

## Review và kết luận

READY_FOR_FILTERED_PILOT yêu cầu regression/invariant tự động đạt; không có nghĩa
con người đã đọc hoặc nguồn đúng y khoa.

Phiếu review chọn ít nhất 50 thread INCLUDE với seed, phủ tuổi/độ dài/template và
partial; cộng regression, nhóm reason mới và các cờ nguồn. Chưa có nhãn giữ
MANUAL_REVIEW_PENDING. Điền reviewer_decision, reviewer_notes, reviewed_at sau khi
đối chiếu raw; nếu phát hiện lỗi parser trọng yếu, ghi PARSER_ERROR trong notes.
Đặt MANUAL_REVIEW_PATH tới CSV đã điền rồi chạy lại tổng hợp/ZIP. Hash raw/parser/
policy không khớp sẽ bị từ chối; nhãn thủ công không vượt hard blocker audio,
câu hỏi trống, raw lỗi hoặc sở hữu chưa xác định.

READY_FOR_FILTERED_CORPUS chỉ áp dụng nhóm INCLUDE theo policy sau review cần
thiết, không phải toàn bộ 1.000 trang hoặc toàn domain. Không tự upload/publish.

## Crawl mẫu khác

MODE='crawl_new' yêu cầu SOURCE_PARQUET rõ ràng. Một worker, delay tối thiểu 2 giây,
retry/timeout hữu hạn; STOP_ON_BLOCK cho 429/challenge, không browser.
HISTORY_PATHS nhận ZIP run, JSONL hoặc thư mục sample.jsonl. Lấy mẫu reservoir theo
canonical question, loại khác biệt HTTP/HTTPS/www và giữ aliases ID nguồn.
Seed mới không bảo đảm mẫu chưa từng crawl; thiếu/toàn bộ lịch sử không được chứng
minh đầy đủ thì manifest ghi rõ giới hạn. Mẫu cố định khi resume.
Mẫu độc lập không có đủ regression chuẩn sẽ không tự được chứng nhận readiness
chỉ vì HTTP/QC tốt.

## Xác minh

- tests/test_ask120_corpus_gate.py: fixture của chín ca thực, media/mixed/markup,
  replay không network hoặc đọc Parquet, raw lỗi/thiếu, ZIP traversal, schema và
  ID, tổng hợp idempotent, resume/hash, manual labels, crawl_new loại canonical.
- tests/test_notebook_120ask_parser_v2.py: giữ tên legacy, tiếp tục kiểm ba fixture
  gán tay, thứ tự/ownership, tail, route, snapshot và audit với V3.
- Run replay 1.000 HTML dùng Requests mock sẽ fail nếu có request, rồi kiểm
  candidate và regression. Báo cáo thực tế nằm ở docs/reports/120ask_v3_replay_20261018.md.
