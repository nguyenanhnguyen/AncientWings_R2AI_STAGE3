# 120ask V4.2 và xét nhập candidate corpus

## Cập nhật F4 / gate v3.3 — 23/10/2026

Parser `120ask-parser-v4.2`, gate `120ask-gate-v3.3`, admission v3.3 ghim
`question_context_ruleset=120ask-question-context-v1`. Extractor vẫn là
`120ask_qa_dom_v4`. Kiểm title và body **sau chuẩn hóa F5**, độc lập với tính hợp lệ DOM.

`question_context` lưu text/hash/DOM locator của từng trường, các span lời hỏi chung,
thời gian/tuổi/nhãn trường và phần nội dung còn lại để đối chiếu. Mask chỉ phục vụ
phân tích, không sửa title/body, không lấy thông tin từ answer và không đặt ngưỡng
độ dài. `context_present` nghĩa là bộ rule giới hạn quan sát được nội dung ngoài
mẫu chung; không xác nhận đầy đủ bệnh sử hoặc đúng y khoa.

| `question_context_status` | `question_context_source` | Admission |
|---|---|---|
| `context_present` | `body` hoặc `both` | Tiếp tục các gate khác |
| `title_only` | `title` | `QUESTION_TITLE_ONLY_REVIEW` |
| `insufficient` | `unresolved` | `QUESTION_CONTEXT_MISSING_REVIEW` |
| `unresolved` | `unresolved` | `QUESTION_CONTEXT_UNRESOLVED_REVIEW` |

Body chỉ có yêu cầu chữa trị, thời gian, cảm ơn, tuổi/giới hoặc tham chiếu chưa rõ
được giữ nguyên. Chỉ title nêu vấn đề thì ghi `title_only` và REVIEW theo policy
hiện tại. Rule tham chiếu báo cáo/thuốc chỉ giữ để review khi thiếu dữ liệu cụ thể;
câu hỏi định nghĩa và báo cáo có kết quả/tên bệnh/tên thuốc vẫn được bảo toàn.

Các lý do F4 áp dụng mọi thread đủ điều kiện chữ; hard blocker/audio/DOM thiếu vẫn
EXCLUDE. Manual INCLUDE không vượt các blocker này; invariant cuối tính lại context
từ title/body để chặn checkpoint bị thay đổi. Candidate JSONL giữ context/status/source;
schema Parquet production không đổi. Hash mới yêu cầu run mới, không chuyển nhãn cũ.

Đã replay 1.000 raw: 31 trang có cờ context, 14 thread INCLUDE → REVIEW,
candidate **657 → 644**. Toàn bộ 16 câu ngắn baseline và 52 fixture HTML đã đối chiếu;
106/106 test 120ask đạt. Xem [báo cáo F4](reports/120ask_f4_fix_review_20261023.md).

## Cập nhật F5 / gate v3.2 — 23/10/2026

Parser `120ask-parser-v4.1`, extractor vẫn `120ask_qa_dom_v4` vì hợp đồng turn không đổi.
Gate/admission v3.2 ghim `question_normalizer=120ask-question-normalization-v1`.
Question giữ xuống dòng từ DOM; chỉ bỏ mảnh `BR>` đầu question khi đúng đoạn đầu
`p.crazy_new`/span nhãn nguồn. Header trong đoạn sau không chứng minh prefix của đoạn trước.
Footer `| 投诉 | 评价(n` chỉ được bỏ khi có chuỗi hai `br` cuối và đúng template nguồn.
Escaped formatting được xử lý theo allowlist, tối đa hai lớp entity cho từng token;
không unescape toàn câu hoặc xóa mọi dấu `<`/`>`/từ 投诉.

`ask120_question_raw` cũ giữ nguyên để tương thích. `question_provenance` bổ sung raw
paragraph text, serialized source DOM, hash raw/DOM/clean, locator và action chain.
Mỗi action có rule/version, span text/replacement và hash trước/sau; offset tính trên
text trước action đó. Raw response gốc vẫn có path/hash riêng, không phải serialized DOM.

`question_qc` tách markup/UI còn dư khỏi tính hợp lệ DOM. `QUESTION_MARKUP_REVIEW`
và `QUESTION_UI_CONTAMINATION_REVIEW` đưa mọi thread đủ điều kiện chữ của trang REVIEW;
các hard blocker/audio-only vẫn EXCLUDE. Manual INCLUDE không vượt blocker cấu trúc
question. Invariant cuối tính lại QC để chặn checkpoint INCLUDE bị thay đổi.

Candidate JSONL giữ `question_provenance`, `question_qc`, `question_source_span`;
Parquet không thêm cột. Audit raw kiểm cả metadata mới và replay action chain.
Ở mốc F5, question context/đủ thông tin còn là F4; xem cập nhật v3.3 phía trên. Thay hash cần run mới;
không tự chuyển nhãn review hoặc resume checkpoint cũ.

Xem [báo cáo F5](reports/120ask_f5_fix_review_20261023.md). Notebook check chung đã có
cell QC question và chạy đủ 17/17 cell code trong kernel sạch, chặn Requests.

## Cập nhật gate v3.1 / F3 — 20/10/2026

Parser V4 giữ nguyên; gate/admission là v3.1 với ruleset `120ask-source-signals-v1`.
`source_flags` xét từng turn `speaker_role=responder`, không ghép câu hỏi hoặc lời
bệnh nhân thành lời quảng bá của người trả lời. Dùng ngữ cảnh câu, cặp tín hiệu có
khoảng cách giới hạn, phủ định/cảnh báo/câu hỏi và các mẫu claim cụ thể; từ “根治”
đơn lẻ không đủ tạo cờ. Không coi phần trăm chẩn đoán hoặc câu an toàn có điều
kiện “一般” như một lời hứa điều trị tuyệt đối.

Cờ gồm tự quảng bá cơ sở/phương pháp, CTA liên hệ và claim điều trị/an toàn.
Mỗi cờ giữ rule/version, turn/reply/DOM locator, raw hash/path, text hash, excerpt
và evidence spans. Offset tính trên clean text của turn. Giữ nguyên lời nguồn;
cờ mặc định đưa REVIEW, không kết luận nguồn sai y khoa hoặc tự xóa cả trang.

Candidate JSONL giữ `source_claim_flags` khi policy hoặc nhãn hợp lệ cho phép nhập
thread đã gắn cờ; Parquet không thêm cột. Invariant cuối chặn cờ chưa review lọt
candidate khi policy yêu cầu review. Thay đổi gate/hash yêu cầu run mới.

Xem [báo cáo F3](reports/120ask_f3_fix_review_20261020.md), test
`tests/test_ask120_source_signals.py` và 20 ca HTML trong `tests/fixtures/120ask_f3/`.

## Cập nhật V4 / F2 — 20/10/2026

Parser/extractor là `120ask-parser-v4` / `120ask_qa_dom_v4`, gate và admission v3.
Role hội thoại là `responder_answer`, `responder_followup`, `patient_followup`,
`unknown_followup`; có `turn_kind` và `speaker_role` riêng. Không dùng vị trí
answer DOM hoặc nickname để khẳng định người trả lời là bác sĩ.

Metadata thread/turn giữ `author_name`, `author_profile_url`, `header_raw`,
`qualification_raw`, `qualification_title`, `source_role`, `source_role_status`
và `author_evidence`. Header/qualification text thu gọn khoảng trắng; HTML DOM,
locator và raw response đã hash giữ bằng chứng nguồn. Chức danh chỉ do nguồn
công bố (`credential_verification=source_only`), không phải giấy phép đã xác minh.

Text dùng nhãn trung tính và có thể ghi `来源职称` khi header hỗ trợ. Nghề được
phép mặc định gồm bác sĩ/y sĩ, dược sĩ, điều dưỡng; vẫn phải qua mọi gate khác.
`其他`, chưa ánh xạ, nghề ngoài allowlist hoặc identity chưa rõ chuyển REVIEW.
Card nhiều reply giữ `card_author` làm quan sát cấp card, không gán tác giả đó
cho từng reply. Lời bệnh nhân không kế thừa nghề của người trả lời; follow-up có
tên người trả lời khác phải review identity.

Counter `responder_followups` thay `doctor_followups`. Candidate JSONL có
`thread_authors` và author metadata trong từng source span; cột Parquet không đổi.
Phiếu INCLUDE không vượt blocker author chưa giải quyết; invariant cuối chặn
candidate không đạt admission của tác giả. Không resume hoặc tự chuyển nhãn V3.
Baseline V3 đóng băng trong thí nghiệm vẫn do engine cũ đọc để so sánh với V4.

Xem [báo cáo kiểm chứng F2](reports/120ask_f2_fix_review_20261020.md).

## Cập nhật V3.2 / F1 — 20/10/2026

Parser `120ask-parser-v3.2` bỏ các mẫu lời nhắc chấp nhận câu trả lời, dẫn sang
tư vấn trực tuyến và lời chúc chung đã được đối chiếu từ raw. Bỏ đúng đoạn trước
khi phân loại media/đếm độ dài, giữ text thực cạnh nó. Không áp bước này cho lời
bệnh nhân hoặc follow-up chưa rõ vai. Raw text/hash/media URL được giữ; action
ghi rule ID, đoạn bị bỏ, offset trên text trước action và hash trước/sau.

Reply chỉ còn nhãn hoặc boilerplate và audio thành audio-only/EXCLUDE; text thực
quá ngắn tiếp tục REVIEW. Media type được tính lại sau khi bỏ tail khớp title.
Extractor family, gate/admission v2 và các cột Parquet production giữ nguyên.
Parser hash mới yêu cầu tạo run mới, không resume checkpoint V3.1.

Fixture/test riêng: `tests/fixtures/120ask_f1/` (chín mixed reply thực) và
`tests/test_ask120_audio_boilerplate.py`. Xem [báo cáo kiểm chứng F1](reports/120ask_f1_fix_review_20261020.md).
Các finding F2–F5 tiếp tục theo plan, không được coi là đã giải quyết bởi cập nhật này.

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

Hai notebook check/holdout đã gộp vào notebooks/check_120ask_50.ipynb, giữ tên
legacy nhưng LIMIT mặc định là 1.000. Notebook vẫn được gitignore. Một cấu hình,
một bộ snapshot/parser/gate, sáu ô A/B và một ô ZIP dùng chung cho ba chế độ:

| MODE | Input và hành vi |
|---|---|
| replay, mặc định | ZIP/thư mục raw cũ; không crawl hoặc tạo Parquet holdout |
| crawl_new | SOURCE_PARQUET và HISTORY_PATHS do người chạy cung cấp |
| holdout_1000 | Mẫu cố định 1.000 câu hỏi, lịch sử 1.086 câu hỏi đã nhúng; không cần Parquet gốc |

Holdout dùng seed 2026102003, một attempt, delay 2 giây; dừng sau năm lỗi truy
cập liên tiếp hoặc challenge/429. Có holdout_quality_audit.json và review packet.
A/B mặc định chỉ bật ở replay vì cần chín regression cũ; holdout không ép thêm
các URL này vào mẫu độc lập. Đổi MODE trước khi Run All và dùng output riêng.

Mẫu/lịch sử được giữ nguyên trong docs/references/120ask/holdout_1000_20261020.json,
kiểm SHA-256 khi nạp trong notebook. Builder có thể tạo lại file chung sau khi
clone repo; không cần giữ notebook holdout thứ hai. Tái tạo bằng:

    .venv/Scripts/python.exe -X utf8 scripts/build_120ask_notebooks.py

Builder cập nhật có giới hạn parser/core route ở hai notebook production/domain,
rồi build notebook check từ source hiện tại. Không gọi builder chung để tái tạo
các engine không liên quan. Hash parser trong cả ba notebook phải bằng source
scripts/ask120.py. Có thể chỉ build lại check bằng build_120ask_gate_notebook.py.
Lệnh build_120ask_holdout_notebook.py cũng cập nhật cùng file check; truyền đường
dẫn run nếu muốn đóng băng một mẫu holdout thay thế. Hai bản notebook trước gộp
được sao lưu tại runs/120ask_notebook_merge_20261021/.

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

scripts/ask120.py V4 giữ riêng card, reply và turn; reply ID được lấy cả ở thẻ p.
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
người trả lời thành một khuyến nghị. Ngày là ngày hỏi, không đổi thành ngày trả lời.
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
  gán tay, thứ tự/ownership, tail, route, snapshot và audit với V4.
- tests/test_ask120_author_roles.py: nguồn nghề nghiệp, nickname, header mất/mơ hồ,
  card nhiều reply, author follow-up, provenance và cổng duyệt thủ công.
- Run replay 1.000 HTML dùng Requests mock sẽ fail nếu có request, rồi kiểm
  candidate và regression. Báo cáo thực tế nằm ở docs/reports/120ask_v3_replay_20261018.md.
