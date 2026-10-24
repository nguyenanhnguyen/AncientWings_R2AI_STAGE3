# ask.39.net — holdout 200 URL mới, loại toàn bộ 650 URL cũ

**Readiness: NEEDS_FIX. Chưa xét đạt F6.** Crawl đủ 200 URL mới; review xác minh 7 ca lỗi còn mở trên 7 trang: 3 claim sản phẩm/thiết bị lọt gate, 1 follow-up lẫn nút UI và 3 answer lẫn đánh giá của bệnh nhân. Có thêm 3 ca cần review chính sách nguồn hoặc chuyên môn. Toàn bộ batch bị chặn release; production export = 0.

## Phạm vi đóng băng và chọn mẫu

Parser, audit, gate, helper crawl, DNS và transport pack được pin hash trước request; hash sau kiểm giữ nguyên. Không sửa rule hoặc nới điều kiện accepted trong đợt holdout. Chỉ bổ sung cell bằng chứng/test offline, giữ tag trong builder notebook và cập nhật báo cáo/plan. Notebook vẫn gitignore.

Nguồn `data/links_corpus_vi_en_zh.parquet`, SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`. Seed **20261025**, chọn **100 numeric + 100 underscore** sau khi loại đủ 650 ID và 650 URL cũ. Đây là mẫu chia đều hai strata, không phải ước lượng tỷ lệ lỗi theo trọng số toàn miền. Loại trừ gồm 450 URL trước đó và 200 URL của E confirmation, bao gồm 2458259 dù từng lỗi transport.

Sample actual khớp sample đóng băng; 200 ID/URL duy nhất, overlap ID = 0, overlap URL = 0. Không thay URL khi lỗi. Các hash artifact cũ được theo dõi trước/sau đều giữ nguyên.

| Mã đóng băng | SHA-256 |
| --- | --- |
| `ask39.py` | `26b221f4d98787d1a145dec12a09d17239151375c4d45e9e205bb611bd48f718` |
| `ask39_audit.py` | `878272c133e262801cca35971ade0c57e62f219e3179db3ba98de975afd8105f` |
| `ask39_gate.py` | `233f28dd2fae59c8d46c6fe17fd4047cd0c4c4b1a7c185b93ae7c45eb9a4fec3` |
| `check_ask39.py` | `99ad093069cc5cf6fc5d14298833d19723b292c062278416390a1711e2d795ca` |
| `ask39_dns.py` | `cf309a7159fb817ec45d7d7986e2453e4b2c908d91777459e0a5be9340cdcc88` |

Transport pack: `96f6d0ed430a8e7c5838c82230e6508004858eb343998f96f62e46c9f68cb16c`.

## Kết quả request, extraction và gate

| Chỉ số | Kết quả |
| --- | --- |
| URL đã thử / pending | 200 / 0 |
| Requests | 199 HTTP 200; 1 HTTP 404 |
| Browser fallback | 1, thành công trên đúng URL 2248345 |
| Raw hỏi–đáp hợp lệ cuối cùng / raw hash kiểm đủ | 200 / 200 |
| Answer / follow-up | 269 / 21 |
| Orphan / unknown role | 0 / 0 |
| Gate đóng băng | 194 accepted, 6 REVIEW |
| Candidate local đóng băng | 194 |
| Production / F6 integration | 0 / chưa tích hợp |

Ca 2248345: Requests 404 được giữ nguyên ở `records/2248345.json` và raw requests; browser render đúng trang `https://ask.39.net/question/38376788.html`, có 2 answer. Đã đọc lại text, DOM và screenshot; không thay địa chỉ hoặc slot mẫu. `results.jsonl` chọn record browser, review/test dùng đúng raw đã chọn.

Replay offline của 200 raw tái lập đúng text, question, answer ID, parent, follow-up và normalization. Audit tự động hiện không báo lỗi, **nhưng review DOM chứng minh audit/parser có chung điểm mù** ở các ca UI/rating dưới đây. Không dùng “audit pass” làm chứng nhận readiness.

## Coverage review

Assistant đã review **69 trang** (các nhóm có giao nhau): toàn bộ 6 REVIEW; mọi ca lỗi request và ca browser phục hồi; đại diện của **20 chữ ký DOM** quan sát được; **20 accepted ngẫu nhiên** từ tập 194 accepted cuối cùng với seed 20261025; mọi trang có tín hiệu nguồn hoặc DOM cần kiểm. Chữ ký DOM gồm đường dẫn answer, số answer/follow-up, role, encoding và normalization, không khẳng định bao phủ mọi template tồn tại ngoài mẫu.

Screen độc lập gồm regex claim/CTA/negation để tìm ca cần đọc, sau đó kiểm ngữ cảnh/người nói; bổ sung `没有任何毒副作用` khi review template tìm ra ca thiết bị, và scan DOM `i.hfu`/`span.pingjia` trên toàn bộ 200 raw để tìm các ca cùng nhóm. Đây là mở rộng **review screening**, không sửa policy/gate đã đóng băng. Tổng 56 hit (có thể nhiều hit/trang).

20 ID accepted ngẫu nhiên: `2406811, 2397900, 2262997, 2252713, 2452980, 2462901, 2432332, 2408603, 2200907, 2400019, 2393050, 2241777, 2454661, 2238636, 2183384, 2365420, 2407658, 2398507, 2442917, 2473610`. Ca 2252713 nằm trong tập ngẫu nhiên và có finding; không thay thế nó bằng accepted khác. Mỗi trang review lưu raw hash, lý do, thời điểm và disposition. Đây là review của assistant, chưa có phê duyệt con người.

| Ca gate REVIEW | Header nguồn chưa đủ nhận diện | Xử lý |
| --- | --- | --- |
| [2153080](https://ask.39.net/question/103795367.html) | 孔子登 / , 南沙区南沙街社区卫生服务中心 | Giữ REVIEW; không mở rộng allowlist |
| [2203214](https://ask.39.net/question/13940922.html) | 玉林制药 / , 玉林制药 | Giữ REVIEW; không mở rộng allowlist |
| [2207135](https://ask.39.net/question/17730621.html) | 邢中林 / , 冠县中医院 | Giữ REVIEW; không mở rộng allowlist |
| [2264689](https://ask.39.net/question/51340539.html) | 强身药业 / , 强身药业 | Giữ REVIEW; không mở rộng allowlist |
| [2267793](https://ask.39.net/question/5545480.html) | 王功兵 / , 其他 | Giữ REVIEW; không mở rộng allowlist |
| [2268865](https://ask.39.net/question/5612223.html) | 王功兵 / , 其他 | Giữ REVIEW; không mở rộng allowlist |

Ca 2207135 vẫn có claim “唯一的办法只能靠中医中草药治疗” cần thẩm định nguồn; page đã bị gate chặn vì chức danh thiếu. Không coi đó là accepted bị lọt thêm. Đánh giá bệnh nhân trong cùng answer là lỗi ownership riêng đã xác minh.

## Các lỗi đã xác minh từ raw

| ID | Loại | Bằng chứng | Gate đóng băng |
| --- | --- | --- | --- |
| [2249721](https://ask.39.net/question/39195186.html) | `branded_anticancer_claim` | 人参皂苷Rh2(护命素) → 具有抗肿瘤、提高免疫力逆转肿瘤细胞耐药性等功效 | accepted |
| [2252713](https://ask.39.net/question/40729058.html) | `absolute_safety_device` | 韩氏疼痛治疗仪 → 没有任何毒副作用 | accepted |
| [2381257](https://ask.39.net/question/94816498.html) | `branded_anticancer_claim` | 人参皂苷G35 → 防止术后肿瘤的复发和转移，有很好的预防作用 | accepted |
| [2211175](https://ask.39.net/question/20576256.html) | `followup_hidden_reply_ui` | i.hfu[style="display: none"] → 回复 | accepted |
| [2205416](https://ask.39.net/question/15782940.html) | `patient_rating_in_responder` | span.pingjia: đánh giá/cảm ơn của bệnh nhân nằm trong answer responder | accepted |
| [2207135](https://ask.39.net/question/17730621.html) | `patient_rating_in_responder` | span.pingjia: đánh giá/cảm ơn của bệnh nhân nằm trong answer responder | review |
| [2207389](https://ask.39.net/question/17962702.html) | `patient_rating_in_responder` | span.pingjia: đánh giá/cảm ơn của bệnh nhân nằm trong answer responder | accepted |

Ba claim đầu đều nằm trong lời responder, không phải câu hỏi bệnh nhân, phủ định, trích dẫn hay lời phản bác. Narrative Rh2 và G35 gắn tên sản phẩm cụ thể với claim khối u/tái phát/di căn; thiết bị 韩氏疼痛治疗仪 gắn với claim tuyệt đối không có độc/tác dụng phụ. Kết luận ở đây là cần REVIEW nguồn, không phải xác nhận hay bác bỏ hiệu quả lâm sàng.

Ba `span.pingjia` nằm ngay trong `p.sele_txt`: parser gộp lời bệnh nhân vào text bác sĩ. Ca 2211175 có `i.hfu` ẩn bên trong `span.zw2`: nút “回复” bị giữ trong follow-up bệnh nhân. Audit hiện dùng ranh giới tương tự nên cũng bỏ sót. Cần sửa cả parser lẫn kiểm độc lập, không xóa chuỗi bằng regex trên toàn trang.

`holdout650_pending_findings.json` lưu answer/message ID, locator, raw hash, method/claim span hoặc HTML node và đánh giá từng ca. Kết quả gate/candidate đóng băng vẫn nguyên bản; review đặt blocker riêng, không sửa lịch sử để làm đẹp số accepted. 6/7 trang finding đang accepted, 2207135 vốn đã REVIEW.

## Các ca review thêm

- **2203052**: Tài khoản 汉森制药 có nhãn 医师, tên tổ chức là công ty dược, và giới thiệu 四磨汤口服液. Cần review chính sách nguồn tổ chức/quảng bá; allowlist chức danh hiện vẫn cho accepted.
- **2407658**: Nguồn khẳng định không có kháng thể thì vaccine không tạo đáp ứng. Đề nghị thẩm định chuyên môn trước sử dụng; lượt này không xác minh đúng/sai lâm sàng.
- **2459843**: Nguồn suy luận HBsAg âm tính thường không cần vaccine. Đề nghị thẩm định chuyên môn; accepted hiện chỉ phản ánh extraction/source QC.

Các ca này vẫn pending; chưa gộp vào 7 lỗi đã xác minh. Accepted của gate chỉ là extraction/source QC, không bảo đảm tính đúng đắn y khoa. Review này không thực hiện kiểm chứng chuyên môn toàn bộ nội dung.

## Kiểm thử và artifact

**12 test bằng chứng mới trong cell `ask39-holdout650` + 3 helper test hiện có pass.** Các cell nhúng raw/evidence và replay offline, không gửi request khi Run All. Chưa chạy lại toàn bộ các section lịch sử trong lượt này; 5 file logic chính không thay đổi. Test xác nhận tính toàn vẹn và tái lập lỗi hiện có, không có nghĩa các lỗi đã được fix.

Gate replay khớp mọi quyết định, flag, claim evidence và eligibility của export. Chỉ `audit.baseline_qc` khác ở 194 record: export nhận input quality `review`, replay đọc record sau gate thành `accepted`; đây là echo metadata, được ghi rõ và loại duy nhất leaf này khi so sánh. Không có policy drift khác. Candidate parquet có đúng 194 ID và text/hash tương ứng, không xuất 6 REVIEW; mọi record `corpus_eligible=False`.

Run: `runs/ask39_holdout650_new200_20261022T133921537030Z`.

- Freeze/sample/excluded650: `runs/ask39_holdout650_frozen_20261022T133921537030Z`.
- `results.jsonl`, `raw/`, `records/`, `browser_records/`, `browser_screenshots/`: bằng chứng gốc và lựa chọn engine.
- `candidate.parquet`, `candidate.decisions.jsonl`: kết quả nguyên bản của gate đóng băng.
- `holdout650_review_data.json`, `holdout650_signal_screen.json`, `holdout650_review_packet.md`: audit, template, screening và tập review.
- `holdout650_assistant_review.json`, `holdout650_pending_findings.json`: coverage/disposition và bằng chứng lỗi.
- `holdout650_release_hold_ids.json`: 15 ID cần giữ REVIEW/pending theo gate hoặc review; toàn batch vẫn bị chặn release.
- `holdout650_final_summary.json`, `holdout650_verification.json`: kết luận và kiểm chứng.

## Hướng tiếp theo trước F6

| Thứ tự | Hướng sửa | Tiêu chí nghiệm thu |
| --- | --- | --- |
| 1 | Làm sạch UI trong follow-up theo node DOM | 2211175 bỏ đúng i.hfu ẩn, giữ nguyên câu hỏi bệnh nhân, parent và thứ tự; không xóa từ 回复 trong nội dung thật |
| 2 | Tách đánh giá bệnh nhân khỏi answer | 2205416/2207135/2207389 không còn span.pingjia trong text responder; lưu provenance/role rõ hoặc metadata đánh giá riêng; không mất text bác sĩ |
| 3 | Mở coverage claim theo phương pháp/người nói | 2249721/2252713/2381257 chuyển REVIEW; có evidence span và source ID; không bắt nhầm phủ định, trích dẫn, bệnh nhân hoặc liệt kê thuốc thông thường |
| 4 | Review nguồn tổ chức và ca chuyên môn pending | 2203052 có quyết định policy rõ; 2407658/2459843 được thẩm định hoặc giữ REVIEW, không mặc nhiên tin chức danh/accepted |
| 5 | Replay và holdout sau fix | Replay 850 raw hỏi–đáp hiện có (650 cũ + 200 mới), giải thích mọi thay đổi text/ID/parent/QC; sau đó đóng băng bản mới, chọn holdout loại đủ 850 URL và review lại trước F6 |

F6 vẫn bị chặn bởi các lỗi parser/audit và source triage đã nêu. Không thay code giữa holdout hoặc dùng lại 200 URL này làm mẫu xác nhận độc lập cho bản fix tiếp theo.
