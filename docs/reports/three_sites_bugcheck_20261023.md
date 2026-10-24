# Kiểm lỗi quy mô lớn: 120ask, cnkang, ask.39.net — 23/10/2026

**Kết luận: NEEDS_FIX.** Đã replay **2.661 URL có raw** và tải/kiểm **1.000 URL mới có raw**, tổng **3.661 URL**. 120ask F4/F5 vẫn còn; cnkang Q3 có 9 ca mới thể hiện 8 nhóm lỗi; ask.39.net giữ nguyên 5 ca chưa sửa và có thêm 3 ca coverage nguồn tổ chức/phương pháp + superlative/claim an toàn trong follow-up. Không sửa parser/policy trong lượt kiểm; không tích hợp F6 hoặc xuất production.

## Quy mô và truy cập thực tế

| Nguồn | Replay raw cũ | Mẫu mới đã chọn | URL mới thực sự gửi request | URL mới có raw hợp lệ |
| --- | ---: | ---: | ---: | ---: |
| 120ask | 1.000 | 500 | 5 | 0 |
| cnkang | 611 | 500 | 500 | 500 |
| ask.39.net | 1.050 | 500 | 500 | 500 |

Seed mới **2026102301**. Mỗi domain một worker, khoảng cách request 2 giây, một attempt, timeout/deadline hữu hạn, TLS bật; cnkang giữ checkpoint/cooldown và phân trang tối đa 6 trang/bài. Các mẫu mới không overlap ID hoặc canonical URL với baseline tương ứng; đã kiểm độc nhất 500 ID/canonical mỗi mẫu. Loại lịch sử có sẵn trong workspace và các ZIP check 120ask đã có. Riêng cnkang khai báo đúng `known_urls_only`, đã loại 1.596 URL lịch sử biết được, không tự nhận lịch sử ngoài workspace đầy đủ. Không đổi URL khi lỗi.

Cnkang: **500 bài / 521 component pages**, 498 complete và 2 incomplete. Ask39: **663 answer + 23 follow-up** trên 500 URL mới. Cả hai có 0 lỗi audit raw và 0 parse failure trên mẫu mới.

120ask: 5 request đầu trả **HTTP 521, body rỗng**; 495 URL chưa gửi. Hai phép chẩn đoán HTTPS trên đúng hai URL vừa lỗi cũng trả 521/0 byte, lưu riêng, không cộng thành URL nội dung mới. Không dùng số checkpoint để giả định đã crawl 500 URL. Guard dừng bằng RuntimeError ban đầu bị lớp probe bắt lại, sinh 173 checkpoint cho slot không gửi request; đã dừng đúng process kiểm 120ask và lưu receipt phân biệt request thật/slot bị chặn trong `verified_access_summary.json`. Các slot đó không phải bằng chứng nội dung.

## Bộ test chạy mới

| Bộ | Kết quả |
| --- | --- |
| 120ask: audio/role/source, gate, notebook | **83/83 pass** |
| cnkang: deadline/checkpoint/pagination/Q1/Q2/Q3/F1 + tích hợp notebook | **179/179 pass** ở UTF-8 |
| Toàn bộ notebook check ask39, chế độ offline | **311 test pass**, chạy hết code cells |
| Helper ask39 | **3/3 pass** |

Lượt cnkang đầu bằng encoding mặc định Windows có một `UnicodeDecodeError` trong test đọc `results.jsonl` không truyền encoding. Chạy lại đầy đủ 179 test bằng `-X utf8` pass, không sửa code để làm test xanh. Đây là hạn chế test runner trên Windows, tách khỏi lỗi parser.

Các test hiện có gồm fixture/baseline đã biết, trong đó một số test ask39 chủ ý tái hiện lỗi đang mở. **Test pass không có nghĩa các lỗi bên dưới đã được sửa.** Không báo precision/recall hoặc gold y khoa từ fixture do agent đọc.

## 120ask — đối chiếu từng hạng mục

| Hạng mục | Kết luận | Bằng chứng hiện tại |
| --- | --- | --- |
| F1 audio boilerplate | PASS hồi quy; chưa kiểm được live mới | Sáu reply lỗi đều audio-only/EXCLUDE; toàn bộ 9 fixture F1 khớp text/media/decision, mixed thật giữ nội dung. |
| F2 bằng chứng nghề nghiệp | PASS hồi quy; chưa kiểm được live mới | 0 thread INCLUDE có author-admission reason; role/qualification/header fixture và 83 test đạt. |
| F3 quảng bá/ngữ cảnh | PASS fixture đã biết; chưa kết luận hết lỗi ngoài mẫu | 20/20 ca HTML F3 đạt quyết định/flag, 0 source span sai. Live mới không có raw để đánh giá. |
| F5 `BR>`/footer question | **CÒN LỖI** | 50 câu hỏi còn literal `BR>`, **27 trang có candidate**. Footer `投诉 / 评价(0` còn trong question 1404664, dù trang này bị EXCLUDE bởi audio. |
| F4 thiếu ngữ cảnh | **CÒN LỖI** | 1205311 chỉ hỏi “怎么治疗啊!” vẫn INCLUDE; 1183810 chỉ có “9年 没治过 能治好吗” vẫn INCLUDE_PARTIAL. 2686938 title-only/body “谢谢” cũng chưa có QC riêng theo plan. |

Replay đủ 1.000 raw, **1.558 thread**; **657 candidate document**, thread decisions `{"INCLUDE": 936, "REVIEW": 541, "EXCLUDE": 81}`. Đây là candidate local, không phải bộ dữ liệu được duyệt. Nhãn readiness tự động trong gate không thay kết luận review NEEDS_FIX của lượt này.

## Cnkang — đối chiếu từng hạng mục

| Hạng mục | Kết luận | Bằng chứng/giới hạn |
| --- | --- | --- |
| R1 deadline DNS/read | PASS bộ hồi quy | Test worker treo/kill/deadline/cause chạy mới. Live 500 thành công không chứng minh mọi tuyến DNS ngoài môi trường đã hết lỗi. |
| R2 checkpoint Windows | PASS bộ hồi quy | Test khóa Windows thật, retry hữu hạn, crash/recovery/cooldown và resume trong suite 179. |
| F2/F3 phân trang/audit | PASS cơ chế đã kiểm; còn bài incomplete được chặn | Replay 611 raw không drift; fixture 9 chuỗi/26 trang; 5 incomplete cũ vẫn giữ, live mới thêm 2 bài incomplete REVIEW. |
| Q1 cấu trúc | PASS fixture; còn cờ cần review | Replay cũ giữ 15 đánh số + 2 lặp đoạn; mẫu mới có 26 đánh số + 8 lặp. Không coi số cờ này là số bug hoặc tự gỡ cho accepted. |
| Q2 PUA/encoding/layout | PASS phần đã có bằng chứng; còn unresolved được giữ | Cũ 3 PUA/1 encoding uncertain; mới 5 PUA/1 encoding uncertain, unknown layout 0. Không tự xóa glyph chưa rõ. |
| Q3 short/metadata/title-body/source | **CHƯA ĐẠT** | 57 short cũ và 44 short mới được giữ review; policy có code/evidence nhưng còn các ca mới bên dưới và chưa có tập nhãn độc lập để nghiệm thu ngưỡng/title-body. |
| F1 formatter/pager | PASS hồi quy | Oracle JavaScript đã ghim, fixture và 611 raw vẫn khớp; không tải/chạy JS từ web. |

Replay cũ: source KEEP/REVIEW **399/212**, corpus KEEP/REVIEW **384/227**, không đổi raw/text/decision. Live mới: source KEEP/REVIEW **323/177**, corpus KEEP/REVIEW **295/205**. Mặc định **report_only**, local export theo parser có **417** bài, gồm **122** bài mà corpus policy đề xuất REVIEW. Không trình bày 417 parser accepted thành 417 nguồn đạt QC. Hai record 1621925/1621934 còn cho thấy duplicate flag được thêm ở export nhưng quality_status vẫn accepted; cần rà lại sự nhất quán này trước enforce/rollout.

## Ask.39.net — đối chiếu các bước đã ghi done

Replay đủ **1.050 raw**, **1.364 answer + 81 follow-up**, 5 đánh giá metadata; không đổi text/ID/parent/role/order so với bản code đóng băng trước lượt này. Gate local **1.006 accepted / 44 REVIEW**. Toàn bộ notebook offline chạy lại đạt 311 test.

| Nhóm yêu cầu | Kết luận |
| --- | --- |
| Parser DOM, giữ answer/follow-up, loại bách khoa/UI, QC/export | PASS hồi quy các ca đã sửa; audit còn false positive riêng 2208116. |
| A định danh 2401990 | Hai answer ID nguồn riêng, follow-up giữ parent, audit xác minh từ container. |
| B phương pháp + claim | 2229930/2252991 vẫn REVIEW, ca âm phủ định/bệnh nhân trong notebook pass. |
| Recovery 2203985, superlative 2214666, retry 2458259 | Recovery giữ nội dung; 2214666 vẫn REVIEW; raw supplement 2458259 còn kiểm hash được. |
| UI follow-up 2211175, đánh giá span 2205416/2207135/2207389 | PASS: UI bị loại theo DOM, source_text/parent/order còn; metadata đánh giá có provenance. |
| Product/device 2249721/2252713/2381257 | Cả ba vẫn REVIEW, evidence và ca âm giữ đúng. |
| Nguồn tổ chức 2203052, pending 2407658/2459843 | Các ca đã chỉ định vẫn REVIEW; coverage tên tổ chức còn thiếu ở ca mới. |
| Replay/holdout được ghi undone | Đã thực hiện và chạy lại; **readiness chưa đạt**, không đồng nghĩa chưa chạy. |

**Năm ca sau holdout trước vẫn chưa sửa:** 2208116 audit bỏ sót phần nối khi sele_txt đã có mở đầu; 2212096 metadata `p.pingjia` bị mất; 2203959 nguồn tổ chức lọt accepted; 2450406 claim chỉnh nha không gây hại; 2351750 claim an toàn tham chiếu qua câu trung gian. Raw và quyết định hiện tại của từng ca nằm trong `known_bug_checks.json`. Tám trang chờ review chính sách/chuyên môn từ holdout trước vẫn là công việc chưa kết thúc, không được đổi thành gold y khoa.

Live mới: **663 answer + 23 follow-up**, frozen gate `{"accepted": 486, "review": 14}`. Không có lỗi parser/audit trong 500 trang mới; đã tìm được 2272062 cùng nhóm thiếu coverage tên tổ chức, 2256749 phương pháp đặc thù + claim “tốt nhất” và 2261082 claim an toàn đảo thứ tự trong follow-up responder.

## Phát hiện mới có raw/evidence

| Nguồn | ID | Loại | Đánh giá |
| --- | --- | --- | --- |
| cnkang | 1906778 | `product_efficacy_rate_missed` | Bài giới thiệu 诺喘欣, nói 100% hiệu quả/98,2% chữa khỏi nhưng source gate phân loại percentage_without_treatment_claim và KEEP. Rule chỉ xem từ sau 100%, bỏ lỡ 有效率为 đứng trước; 彻底治愈 cũng chưa được phủ bởi regex CLAIM. Cần REVIEW theo ngữ cảnh quảng bá, không suy ra độ đúng y khoa. |
| cnkang | 1928766 | `reported_phone_action_false_cta` | Nguồn kể phóng viên đã gọi điện cho gia đình, không mời người đọc liên hệ/mua. Gate gắn COMMERCIAL_CTA asserted và COMMERCIAL_CTA_REVIEW chỉ vì 拨打. Đây là false positive tín hiệu CTA; chưa khẳng định mọi lý do REVIEW khác đều sai. |
| cnkang | 1821514 | `reported_phone_action_false_cta` | Câu tường thuật phóng viên gọi số y tế công ích bị coi là CTA thương mại. Cùng lỗi ngữ cảnh hành động đã xảy ra, không phải lời mời người đọc liên hệ. |
| cnkang | 1471156 | `procedure_term_false_promotional_claim` | Tên phẫu thuật 根治术 bị gắn absolute_treatment_claim/asserted. Rule chỉ nhận một số dạng 根治性/手术, bỏ sót dạng viết gọn 根治术; false positive PROMOTIONAL_CLAIM_REVIEW. Không xóa thuật ngữ khỏi nội dung. |
| cnkang | 1474950 | `coordinated_negation_scope_false_claim` | Nguồn phủ định khả năng bảo đảm điều trị tuyệt đối; 百分之百 là bổ ngữ song song sau dấu phẩy của 无法做到. Rule cắt clause ở dấu phẩy làm mất phủ định, gắn claim asserted và PROMOTIONAL_CLAIM_REVIEW. Cần xử lý phạm vi phủ định có bằng chứng, không mở sang mọi câu tiếp theo. |
| cnkang | 3337244 | `explicit_denial_false_claim` | Phủ định rõ 尚无根治…方法 vẫn bị gắn absolute_treatment_claim/asserted vì bộ phủ định thiếu 尚无. Đây là false positive claim, không phải bằng chứng quảng bá. |
| cnkang | 1877385 | `reported_uncertain_claim_misattributed` | Nguồn thuật lại ý kiến người khác và nói còn bất đồng, nhưng 没有副作用 bị gán article_voice/asserted. Cần nhận diện attribution/stance được kể lại; không tự đồng nhất với quan điểm tác giả. |
| cnkang | 1908807 | `unrelated_negation_hides_safety_claim` | Mô tả phương pháp 五位一体 khẳng định 无副作用, nhưng từ 不住院 ở mục liệt kê trước làm gate gán negated và KEEP. Phủ định việc nhập viện không phủ định claim an toàn; cần ràng buộc phạm vi phủ định theo quan hệ cú pháp/list có bằng chứng. |
| cnkang | 1758095 | `qa_guest_patient_role_misattributed` | Lời người hỏi có nhãn guest trong hội thoại với 陈福国 bị gán PERSONAL_NARRATIVE/article_voice và PERSONAL_EXPERIENCE_REVIEW. Cần nhận diện vai hội thoại guest; không coi trải nghiệm của người hỏi là tự sự của tác giả. Các lý do REVIEW khác chưa được tự gỡ. |
| ask39 | 2272062 | `organization_management_center_missed` | Ca mới cùng nhóm thiếu coverage 管理中心: account là trung tâm sức khỏe và affiliation công ty dược, vẫn accepted dù policy yêu cầu nguồn tổ chức REVIEW; không dựa vào nhãn 医师 để kết luận là bác sĩ cá nhân. |
| ask39 | 2256749 | `specific_method_superlative_coverage_gap` | Ca mới phương pháp 三镜联合微创技术 đi kèm 最好的办法 và thành công cao trong cùng lời responder, không phủ định/trích dẫn/lời bệnh nhân. Rule hiện mới phủ tổ hợp phương pháp hẹp và không có mẫu 办法 nên lọt accepted; cần REVIEW phương pháp đặc thù + superlative theo ngữ cảnh. |
| ask39 | 2261082 | `safety_word_order_variant_missed` | Follow-up responder khẳng định phẫu thuật không ảnh hưởng đời sống tình dục bằng cấu trúc 性生活没影响. Gate chỉ phủ 不影响性生活, thiếu biến thể 没影响 và đảo thứ tự; vẫn accepted. Giữ đúng parent và phân biệt câu hỏi của bệnh nhân với claim của responder. |

Cnkang có **9 ca / 8 nhóm lỗi Q3**: 2 ca source KEEP cần REVIEW (1906778, 1908807), 7 ca có signal bị gán sai. Các ca bị gán sai có thể vẫn cần REVIEW vì lý do khác; không tự gỡ toàn bộ REVIEW. Ask39 có thêm 2272062 cùng lỗi tên tổ chức đã thấy ở 2203959; 2256749 lọt tổ hợp 三镜联合微创技术 + 最好的办法; 2261082 lọt 性生活没影响 trong lời responder. Đây là kết luận extraction/source-policy, không phán quyết đúng/sai điều trị.

## Phạm vi đọc nguồn và tính toàn vẹn

Đã audit tự động tất cả raw mới, đọc toàn văn **20 parser-accepted ngẫu nhiên cnkang** và **20 gate-accepted ngẫu nhiên ask39** từ dân số cuối, seed 2026102302; đọc đại diện template và mọi quote của broad screen liên quan các lỗi đang kiểm. Review này không phải đọc tay toàn bộ mọi REVIEW/error trên cả 1.000 trang mới, không dùng làm chứng nhận F6.

Review cnkang: `{"reviewer": "assistant", "human_approval": false, "random_accepted_ids": [1448462, 1724709, 1853141, 1863007, 1792750, 1781181, 1887512, 1885391, 3481914, 1558483, 1432443, 1955109, 1983467, 3471338, 3481102, 1998188, 1585180, 1758095, 1695343, 3243997], "random_accepted_reviewed": 20, "random_population": "parser accepted under report_only", "full_pages_read": 26, "template_groups": 4, "reviewed_signal_quotes": 54, "scope": "Automated raw/parser/audit/gate on all 500; targeted source-signal review plus templates and final random20. Not full manual review of all REVIEW pages or clinical validation."}`.

Review ask39: `{"reviewer": "assistant", "human_approval": false, "random_accepted_ids": [2161184, 2454068, 2244980, 2399990, 2402346, 2287466, 2274142, 2405504, 2460965, 2404661, 2447886, 2199075, 2154749, 2421182, 2425126, 2447006, 2447278, 2431363, 2201119, 2260798], "random_accepted_reviewed": 20, "random_population": "frozen gate accepted", "full_pages_read": 38, "template_groups": 18, "reviewed_signal_quotes": 117, "scope": "Automated raw/parser/audit/gate on all 500; targeted source-signal review plus templates and final random20. Not full manual review of all REVIEW pages or clinical validation."}`.

Đóng băng toàn bộ Python source scripts theo hash trong `freeze_manifest.json`; dùng bản copy cho replay/live; hash production trước/sau khớp. Không thay rule giữa lượt chạy. Notebook gốc không bị ghi đè; bản execution ask39 có output lưu riêng trong run. Raw/record cũ giữ nguyên; mọi output mới ở run độc lập.

## Hướng tiếp theo

1. **120ask:** sửa F5 rồi F4; giữ F1/F2/F3 làm hồi quy. Cần môi trường nhận được HTML thật để nghiệm thu live, hiện 521 không cho phép kết luận nguồn mới hết lỗi.
2. **Cnkang:** ưu tiên hai ca lọt KEEP, sau đó phạm vi phủ định/thuật ngữ/tường thuật/người nói; thêm các ca mới thành fixture. Giữ report_only cho đến khi có nhãn độc lập và đối chiếu title-body; kiểm lại duplicate/export consistency.
3. **Ask39:** thực hiện plan 5 lỗi gần nhất, thêm 2272062 vào nhóm tổ chức và 2256749 vào nhóm phương pháp/superlative; giữ các pending chuyên môn. Replay inventory đã mở rộng rồi đóng băng/holdout tiếp, không tích hợp F6 chỉ vì test cũ pass.

Run: `runs/three_sites_bugcheck_20261023T092000436086Z`. Artifact chính: `final_summary.json`, `known_bug_checks.json`, `fresh_confirmed_findings.json`, `*_replay/bugcheck_summary.json`, `cnkang_final_tests.json`, `ask39_notebook_tests.json`, hai `*_fresh500/bugcheck_screen.json`, raw/manifest/sample/source decisions và review progress. Bằng chứng 120ask: `verified_access_summary.json`, `verified_network_events.json`, `120ask_https_diagnostics.json`.
