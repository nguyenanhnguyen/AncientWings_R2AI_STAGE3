# Q3 — Kế hoạch gate nguồn cnkang, 21/10/2026

Trạng thái: **đã triển khai code/fixture và đồng bộ production ở report_only**.
179/179 test đạt; 611 raw/text/audit giữ nguyên, 9 chuỗi và 122 oracle F1 khớp.
Đã đọc/phân loại đủ 57 short text. Còn nghiệm thu tập nhãn độc lập 80/40 và hiệu
chuẩn trước khi bật enforce mặc định; không gọi fixture đã biết là gold.
Xem [review Q3](../reports/cnkang_q3_review_20261021.md). Các mục dưới đây giữ
baseline Q2 và tiêu chí thiết kế để đối chiếu phần đã làm/phần kiểm nhãn còn lại.

Mục tiêu là đánh giá mức phù hợp nguồn sau khi trích đúng toàn bài. Giữ F1 làm
hồi quy; không lấy số cờ được gỡ hoặc số accepted tăng làm điều kiện đạt.
Kế hoạch này cụ thể hóa [Q3 trong kế hoạch sửa còn lại](cnkang_remaining_fixes_20261020.md#q3--p1--short-text-metadata-và-gate-nguồn).

## 1. Baseline và phạm vi

Dùng runs/cnkang_q2_20261020_pass2/f1_replay làm baseline gần nhất, với parser
cnkang-v6-spec-6 và helper cnkang-article-3. Giữ nguyên run F1 và Q2 gốc.

| Chỉ số đọc lại | Baseline Q2 |
|---|---:|
| Record có raw | 611 |
| Parser accepted / review | 531 / 80 |
| Bài complete / incomplete | 606 / 5 |
| SHORT_TEXT_REVIEW | 57 |
| Độ dài compact dưới 50 / 50–99 / 100–199 | 19 / 7 / 31 |
| AUTHOR_UNAVAILABLE_REVIEW | 611 |
| TITLE_BODY_ALIGNMENT_REVIEW | 368 |
| PROMOTIONAL_CLAIM_REVIEW / PERSONAL_EXPERIENCE_REVIEW | 17 / 4 |
| CONTEXTUAL_REPETITION_REVIEW | 2 |
| Parser accepted có claim hoặc experience flag, đếm hợp | 16 |

Các nhóm chồng nhau. 16 chỉ là tín hiệu cần đọc, chưa phải 16 quảng cáo hoặc 16
bài phải loại. Mốc 14 trong review F1 là số lịch sử, không dùng làm tổng Q3.
Hai short text 1405611 và 3530118 đang incomplete; 55 bài còn lại complete theo
bằng chứng phân trang hiện có, chưa đồng nghĩa đã đạt chất lượng nguồn.

Định danh baseline bổ sung: SHA-256 của review_summary.json là
597a347613df8d43274b575f6405c6ca98fd9d8200c0f7e69a67ed3bf23ab026;
run_config.json là 4046813e6e2a8a22d010e267021213be215040a9ef9309b40ce846e3cd684946.
Khi triển khai, lập manifest theo ID/canonical article/raw hash/text hash và
snapshot hash; kiểm khớp trước replay, không chỉ dựa vào tên thư mục.

## 2. Short text — đánh giá đủ 57 bài

**Điểm sửa dự kiến:** scripts/cnkang.py:review_text giữ phép đo compact và cờ
độ dài; scripts/cnkang_article.py:assemble tiếp tục đo trên toàn bài;
scripts/cnkang_source_gate.py là module production dự kiến để phân loại nguồn.

Lập bảng đủ 57 ID với độ dài, title, template, body locator, raw/text hash,
completeness và lý do. Kiểm raw/DOM để tách: trích thiếu, thiếu trang, nguồn thực
sự ngắn, trả lời ngắn phụ thuộc câu hỏi và nội dung ngắn có thể tự đứng độc lập.
Nếu thấy trích thiếu, mở lỗi extraction có fixture riêng; không bù text bằng
title hoặc bài liên quan. Chưa thay ngưỡng 200 hoặc gỡ SHORT_TEXT_REVIEW.

**Fixture dự kiến:**

- Raw thật 1716739, 1792421, 1889767: lần lượt 5, 6, 7 ký tự compact; giữ nguyên
  text, ghi thiếu thông tin/ngữ cảnh. Nhãn corpus cuối cần được đối chiếu policy.
- 1606857 (88 ký tự) và 1622860 (158 ký tự): đại diện hai khoảng còn lại để đọc
  đầy đủ trước khi chốt nhãn; không mặc định chúng tốt hoặc xấu từ độ dài.
- 1405611 và 3530118: incomplete ưu tiên hơn kết luận nguồn ngắn thật.
- Fixture tổng hợp, ghi rõ synthetic: mỗi trang dưới 200 nhưng bài ghép trên
  200; trang cuối thiếu; body bị thay bằng synopsis; câu trả lời mất câu hỏi.

**Nghiệm thu:** 57/57 có phân loại và bằng chứng, chưa đủ bằng chứng phải ghi
UNRESOLVED/REVIEW. Đo lại sau ghép; bài thiếu trang không KEEP. Không đổi text
hoặc nâng parser accepted chỉ vì nguồn được đánh giá tốt. Báo riêng bao nhiêu
trích thiếu, incomplete, ngắn thật và chưa rõ; không ép tổng REVIEW về 0.

## 3. Metadata — đúng người và đúng vai trò

**Điểm sửa dự kiến:** scripts/cnkang.py:metadata/extract, audit metadata và
scripts/cnkang_article.py:assemble/audit. Bổ sung attributions có name, role,
title/institution nếu hiện diện, page, DOM locator, quote và mức bằng chứng.
Vai trò gồm article_author, reviewer, respondent, quoted_person và unknown.

Ưu tiên meta/byline trong vùng bài đã xác minh; nhãn người trả lời trong body
chỉ tạo respondent của lượt đó. Metadata trang đầu là mặc định cho bài; trang
sau chỉ bổ sung bằng chứng, không âm thầm ghi đè khi mâu thuẫn. Thiếu ngày hoặc
tác giả vẫn là thông tin chưa xác minh. Không suy tên tác giả từ tên website,
menu bác sĩ, người được nhắc đến hoặc chữ ký không rõ vai trò.

Scalar author chỉ được điền khi có bằng chứng article_author. Người trả lời
được lưu riêng; thiếu meta author không đủ để loại toàn domain. Các trường mới
phải có schema/version và được tái dựng trong audit, không chỉ thêm vào report.

**Fixture dự kiến:** raw 1544618 có nhãn 江西省儿童医院神经内科陈勇 trong lượt
trả lời: nhận respondent cùng locator, không tự gán article_author. Bổ sung ca
tổng hợp meta/byline rõ, reviewer riêng, sidebar có tên bác sĩ, người được trích
dẫn, nhiều tác giả, thiếu metadata và metadata các trang mâu thuẫn. Dùng lại
1690503 để bảo vệ heading/date/layout Q2; incomplete vẫn giữ nguyên.

**Nghiệm thu:** đúng vai trò ở toàn bộ fixture; scalar author không nhận tên từ
ca âm. Mọi tên/ngày được thêm hoặc sửa có bằng chứng và diff theo ID. Không suy
ngày từ nội dung bài hay lấy ngày ở sidebar. Audit phát hiện sửa tên, vai trò,
locator hoặc provenance. Không đổi body để phục vụ metadata.

## 4. Title–body — thay heuristic khớp nguyên cụm

**Điểm sửa dự kiến:** thay phần tạo TITLE_BODY_ALIGNMENT_REVIEW trong
scripts/cnkang.py:extract bằng evidence phù hợp tiếng Trung; module gate nhận
heading đã xác minh và text toàn bài. scripts/cnkang_article.py:assemble phải
đánh giá lại trên bài ghép, không lấy hợp các cờ title–body của từng trang làm
kết luận cuối. Giữ bằng chứng từng trang để audit.

Tách thiếu heading, metadata mâu thuẫn, ít tín hiệu từ vựng và ghép sai body.
Thử char n-gram/coverage cùng các đoạn có liên quan; chỉ chuẩn hóa bản dùng để
so sánh. Chọn ngưỡng trên dev có nhãn, lưu feature/threshold/version. Cùng một
từ bệnh hoặc điểm overlap cao không chứng minh body đúng. Không sửa title/body
để tăng điểm; selector sai chỉ sửa khi raw/DOM chứng minh được vùng đúng.

**Fixture dự kiến:** raw 1782034 cùng chủ đề dù không lặp nguyên title; 1544618
là Q&A, cần đọc cả câu hỏi/lượt đáp. Thêm ca âm synthetic ghép title của
1782034 với body 1516530; thêm ca cùng từ bệnh nhưng khác câu hỏi, heading rỗng,
chỉ có boilerplate chung và đoạn liên quan nằm ở trang 2. Nếu tìm được mismatch
thật, bổ sung raw thật và nhãn riêng, không gọi ca ghép tổng hợp là lỗi website.

**Nghiệm thu:** ca cùng chủ đề không bị kết luận mismatch chỉ vì thiếu nguyên
cụm title; ca tráo body vẫn REVIEW. Các ca thiếu/mâu thuẫn giữ lý do riêng.
Báo bảng lỗi trước/sau trên tập kiểm đóng băng, gồm bỏ sót mismatch và báo nhầm;
không lấy việc gỡ 368 cờ làm đích. Quyết định title–body không tự xác nhận tính
đúng chuyên môn hoặc toàn bộ source_decision.

## 5. Claim/trải nghiệm — phân loại theo ngữ cảnh

**Điểm sửa dự kiến:** tách regex hiện có trong scripts/cnkang.py:review_text
khỏi kết luận nguồn; scripts/cnkang_source_gate.py đánh giá source_signals
trên toàn bài. Tín hiệu phải có page/paragraph/span, đoạn trích, chủ thể phát
ngôn và trạng thái asserted, negated, quoted hoặc uncertain.

Phân biệt quảng bá thương mại, khẳng định tuyệt đối, mô tả có điều kiện,
trải nghiệm cá nhân, câu hỏi của bệnh nhân và nội dung bác bỏ claim. Tìm thêm
tín hiệu CTA/liên hệ/sản phẩm hoặc cam kết; không yêu cầu phải có thương mại mới
giữ cờ khẳng định tuyệt đối. Phủ định chỉ áp dụng đúng mệnh đề, không phủ định
cả bài; lời trích dẫn vẫn cần biết bài đang tán thành hay phản bác. Chưa rõ thì
REVIEW. Loại nguồn có thể nhiều nhãn: expository, Q&A, news, experience,
promotional, unknown; không chốt từ path hoặc một từ khóa.

**Fixture dự kiến:**

- 1740065: giữ REVIEW cho khẳng định/cam kết mạnh và giọng trải nghiệm; không
  chỉ dựa vào từ 根治, chưa gán là quảng cáo thương mại khi thiếu bằng chứng.
- 1516530: cụm có điều kiện quanh 根治 không đủ tự động EXCLUDE quảng cáo;
  đọc cả bài và giữ khả năng REVIEW vì các tín hiệu khác. Không gán gold KEEP.
- Kiểm đủ 17 claim + 4 experience flag, và hợp 16 parser accepted; bổ sung
  1669081/1759215 để giữ source signal lặp theo nhóm của Q1.
- Ca tổng hợp có nhãn rõ: phủ định “không thể bảo đảm 100%”; trích quảng cáo
  rồi bác bỏ; trích rồi tán thành; claim ở trang 2; tên bác sĩ trong lời bệnh
  nhân; cam kết tuyệt đối kèm CTA; bài trải nghiệm không có lời quảng bá.

**Nghiệm thu:** mỗi claim được gắn đúng ngữ cảnh trong fixture; phủ định/trích
dẫn bác bỏ không bị tự động EXCLUDE chỉ từ khóa. Ca cam kết/CTA rõ không thành
KEEP do bỏ sót hoặc phủ định sai scope. Báo confusion matrix và support riêng
cho promotion, experience, negation/quotation; không dùng heuristic làm gold
và không gọi việc phát hiện claim là xác minh y khoa.

## 6. Hợp đồng gate và các điểm tích hợp

Giữ quality_status/quality_flags cho extraction/parser, article_complete cho
toàn văn. Thêm sidecar source_type, source_signals, source_decision
(KEEP/REVIEW/EXCLUDE), source_reason_codes và source_policy_version/hash.
source_flags cũ được giữ như baseline trong replay; quyết định mới không suy
trực tiếp từ việc có bất kỳ source_flag nào. Metadata/rule mới có version riêng
và baseline mới, không dùng snapshot mới để chứng thực record lịch sử.

corpus_decision là kết quả tổng hợp: audit lỗi thì chặn export; gate nguồn
EXCLUDE thì loại khỏi tập chuẩn nhưng giữ raw/record; incomplete, parser chưa
accepted, policy thiếu/cũ hoặc nguồn REVIEW thì REVIEW. Chỉ KEEP khi audit đạt,
bài complete, parser accepted và nguồn KEEP. Dedupe vẫn chạy theo hợp đồng
crawler hiện tại. KEEP chỉ nghĩa là đạt policy nguồn đã định nghĩa.

| Điểm sửa dự kiến | Vai trò và fixture tích hợp | Tiêu chí nghiệm thu |
|---|---|---|
| scripts/cnkang_source_gate.py, cnkang.py và cnkang_article.py | Sinh evidence/policy sau ghép; thiếu trang, claim trang 2, metadata mâu thuẫn | Tái lập cùng quyết định từ cùng input/version; không dùng cờ cục bộ sai scope |
| scripts/corpus_runner.py:publish_record | Lưu cả trạng thái parser và corpus; record parser sạch nhưng source REVIEW/EXCLUDE | Giữ record/raw và lý do; không coi parser accepted là đủ vào tập chuẩn |
| scripts/corpus_audit.py và audit cnkang | Tính lại quyết định từ raw/manifest, metadata và policy snapshot; sửa decision/evidence/hash | Phát hiện tampering và policy cũ; không tin decision chỉ vì được ghi sẵn |
| scripts/cnkang_check.py:export và core report trong scripts/build_cnkang_notebooks.py:core_upgrade | Main, domain, check và POSTPROCESS_ONLY dùng cùng policy; fixture incomplete, thiếu policy, source REVIEW/EXCLUDE | Cùng corpus_decision; chế độ enforce chặn mọi đường xuất tập chuẩn chưa đạt |
| Builder, config/resume/checkpoint | Snapshot module gate kèm hash; policy đổi, resume từ cache, crash khi ghi | Đổi policy chỉ tính lại sidecar từ raw cũ, không GET lại; R2/cooldown còn nguyên |

Triển khai hai chế độ explicit trong config: report_only trước, enforce sau
nghiệm thu. report_only giữ hành vi export hiện tại, xuất thêm quyết định đề
xuất và ghi rõ dữ liệu chưa được gate nguồn; không gọi nó là corpus đã đạt Q3.
enforce dùng corpus_decision để lọc tập chuẩn, vẫn xuất báo cáo review/exclude.
Giữ hợp đồng cột corpus; trường chẩn đoán/version ở sidecar và manifest.

## 7. Fixture, tập nhãn và cách đo

1. Dự kiến tạo tests/fixtures/cnkang_q3/manifest.json cùng raw tối thiểu theo
   SHA-256; tests/test_cnkang_source_gate.py, tests/test_cnkang_metadata.py và
   test tích hợp hiện có. Manifest phân biệt real/synthetic, oracle trích xuất,
   nhãn chính sách, người/nguồn nhãn và mục đích dev/test/regression.
2. Inventory đọc đủ 57 short text, các nhóm source flag và đủ 16 ứng viên sạch
   parser nêu trên. Nhận xét của agent chỉ là nhãn đề xuất; chưa có nhãn độc lập
   thì không báo độ chính xác đã được xác nhận.
3. Chuẩn bị khoảng 80 dev/40 test có nhãn độc lập, gồm cả bài không có cờ để
   tìm false negative. Cỡ này là dự kiến; thiếu support cho lớp nào phải báo
   thiếu. Mọi ID đã đọc để chọn rule trong kế hoạch này thuộc dev/regression.
4. Chia theo canonical article/family và duplicate group, không tách trang của
   cùng bài vào hai tập. Đóng băng manifest/hash/nhãn trước khi chọn ngưỡng.
   611 raw đã biết chỉ cho kiểm nội bộ và hồi quy; không gọi là URL mới hoặc
   holdout crawl độc lập. Tập kiểm đã xem để sửa rule phải được thay/ghi nhận
   đã sử dụng, không tiếp tục gọi là blind test.
5. Đo per-task confusion matrix, support, tỷ lệ REVIEW, KEEP sai và EXCLUDE
   sai; có danh sách ID/lý do trước–sau. Báo giới hạn cỡ mẫu và khoảng tin cậy
   khi đủ điều kiện, không suy chất lượng toàn domain từ 40 mẫu nhỏ.

## 8. Nghiệm thu, thứ tự làm và điểm dừng

Thứ tự: đóng băng baseline/inventory → chốt rubric và fixture có nhãn → metadata
→ title–body → claim/context → policy report_only → replay/audit tích hợp →
đánh giá tập kiểm → bật enforce khi đạt tiêu chí. Short text được đọc từ bước
inventory và kết luận sau khi có metadata, completeness và policy.

- Toàn bộ fixture dương/âm có oracle phải đạt; không có ca gold EXCLUDE bị
  KEEP trong tập kiểm đóng băng. Ca chưa phân xử phải REVIEW, không tự chuyển
  thành nhãn tốt. Ngưỡng và tiêu chí lỗi theo lớp phải chốt trước xem tập kiểm.
- Mọi thay đổi decision/metadata có diff và provenance. Nhãn còn thiếu, lỗi
  nghiêm trọng chưa giải thích hoặc kiểm độc lập chưa đạt: dừng ở report_only,
  ghi rõ phần chưa nghiệm thu; không bật enforce để kịp tiến độ.
- F1 tiếp tục qua 122 oracle JS đã biết; raw/hash/formattext/pager không đổi.
  Trên baseline Q2, Q3 không sửa body: 611/611 text hash phải giữ nguyên; mọi lỗi
  extraction mới phát hiện tách thành thay đổi có fixture và review riêng.
- Hồi quy Q1/Q2 và bộ 155 test đã đạt ở bước Q2 phải tiếp tục đạt; 9 chuỗi/26
  trang vẫn giữ 9.723 ký tự và audit/recovery. 5 incomplete không thành KEEP;
  PUA/encoding chưa rõ không bị gate nguồn che mất. Kiểm main/domain/check
  snapshot khớp production và hành vi domain khác giữ nguyên.
- Review cuối báo riêng fetch/parse/complete/parser quality/source decision/
  corpus decision/pending. Có bảng đủ 57 short text và các nhóm nguồn, ma trận
  lỗi, ID thay đổi, giới hạn nhãn và lý do dừng; không đặt mục tiêu tăng accepted.

Khi triển khai, thí nghiệm chỉ bổ sung trong notebooks/check_cnkang.com.ipynb
đã gitignored; output vào runs/ đã ignore. Fixture/test/code production và tài
liệu được track. Không tạo helper thí nghiệm rời, không tự chạy tiếp 385 pending
hoặc gửi request mới trong lượt cập nhật kế hoạch này.
