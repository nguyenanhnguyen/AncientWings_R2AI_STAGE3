# Kế hoạch sửa các vấn đề cnkang còn lại — 20/10/2026

Trạng thái: **R1, R2, F2/F3, Q1, Q2 và Q3 report_only đã triển khai.**
Parser cnkang-v6-spec-7, helper cnkang-article-4, policy cnkang-source-1.
Kiểm cuối Q3: 179/179 test đạt, audit/raw/text 611/611 giữ nguyên so với Q2,
9 chuỗi/26 trang và 122 oracle JS F1 khớp. 57 short text có nhận xét theo ID;
còn tập nhãn độc lập 80/40 trước enforce mặc định. 5 bài vẫn incomplete/review.
Xem [review Q3](../reports/cnkang_q3_review_20261021.md); các phần dưới giữ kết
quả theo từng mốc triển khai, không cộng chúng thành số URL mới đã crawl.

Cơ sở: [review 615 URL/F1](../reports/cnkang_f1_fix_review_20261020.md). Đã xử lý 615 URL: 611 parse được, 4 lỗi vận hành; 119 trang có cờ parser. 492 trang sạch parser vẫn có 14 trang mang tín hiệu nguồn cần đọc lại. Các nhóm cờ chồng nhau và chưa có nhãn độc lập cho toàn bộ 611 trang.

Không đặt mục tiêu xóa hết 119 cờ hoặc ép tỷ lệ accepted tăng. Mỗi thay đổi phải sửa đúng nguyên nhân, có bằng chứng và test trước/sau.

Trước triển khai Q3, kiểm ngày 21/10/2026: **155/155 test đạt**, audit 611/611 record,
9/9 chuỗi và 122/122 oracle JS F1 khớp. Q3 khi đó chưa triển khai; 5 bài incomplete
và các cờ chưa đủ bằng chứng còn giữ review. Xem [báo cáo kiểm toàn bộ](../reports/cnkang_full_verification_20261021.md).

## Thứ tự triển khai

**R1 → R2 → F2 kèm F3 → Q1 → Q2 → Q3 → kiểm chứng tích hợp.**

| Hạng mục | Vấn đề cần xử lý | Ưu tiên | Kết quả cần đạt |
|---|---|---|---|
| R1 | DNS/reset, request có log elapsed khoảng 8.446 giây dù timeout 8/20 | P0 | Có deadline toàn request/URL, dừng hữu hạn, phân loại lỗi đúng |
| R2 | WinError 5 khi replace file state | P0 | Checkpoint bền vững, retry ghi có giới hạn, không mất state/cooldown |
| F2 + F3 | 4 bài còn phân trang; audit hiện chủ yếu một trang | P1 | Ghép đúng toàn bài, checkpoint từng phần, audit/resume được |
| Q1 | 47 cờ đánh số giảm, 7 cờ lặp đoạn | P1 | Phân biệt lỗi thật với danh sách/lượt trả lời/nhóm nội dung hợp lệ |
| Q2 | 8 PUA, 2 encoding uncertain, 1 unknown layout | P2 | Chuẩn hóa ký tự đã xác minh; hỗ trợ bố cục cụ thể, giữ review khi chưa rõ |
| Q3 | 57 short text; metadata/title-body/claim nguồn chưa chính xác | P1 trước export dữ liệu chuẩn | Gate nguồn riêng, quyết định có ngữ cảnh và tập kiểm nhãn |

Q3 có thể chuẩn bị tập nhãn từ đầu, nhưng chỉ hiệu chuẩn gate trên văn bản đã qua các bước khôi phục/toàn văn. F3 là phần bắt buộc của F2, không phát hành pagination rồi mới bổ sung audit sau.

## 0. Chốt baseline, fixture và cách đánh giá

1. Giữ bất biến run runs/cnkang_f1_1000_20261020, manifest 1.000 URL và toàn bộ raw/checkpoint của 615 record. Dùng phiên bản mới/thư mục mới khi triển khai, không sửa đè bằng chứng của F1.
2. Lưu fixture đúng SHA-256 theo từng lỗi: 4 record vận hành, 4 bài phân trang, các nhóm 47/57/8/7/2 và unknown 1690503. Không bịa trang tiếp chưa tải hoặc text y khoa thiếu.
3. Chốt kỳ vọng theo raw/DOM và phạm vi nội dung: text nào phải giữ, UI nào được bỏ, vì sao cờ nên còn/gỡ. Phân biệt nhãn review của AI với nhãn được con người xác nhận.
4. 611 raw hiện có là tập hồi quy đã biết. Khi hiệu chuẩn Q1–Q3, dùng khoảng 80 mẫu phát triển và 40 mẫu kiểm có nhãn đóng băng trước khi chọn ngưỡng; các ví dụ đã dùng để đề xuất rule phải nằm trong nhóm phát triển. Không điều chỉnh theo lỗi tập kiểm rồi vẫn gọi kết quả là holdout độc lập.
5. 385 URL chưa chạy là phần còn lại của manifest cũ, không phải 385 URL mới. Không tự tiếp tục chúng trong yêu cầu chỉ lập plan này.

## R1 / P0 — Deadline thật và dừng an toàn khi lỗi mạng

**Đã làm:** deadline 45 giây/request và 120 giây/URL, worker mạng có thể kết thúc,
giữ stage/exception gốc, kiểm hash snapshot và ngừng lượt khi deadline/worker lỗi.
47/47 test đạt; hai lượt dùng cùng 50 URL ngẫu nhiên, lượt cuối 51/51 HTTP 200,
85,836 giây, request tối đa 1,879 giây. Đã kiểm Windows/IPython; còn xác nhận trực
tiếp trên Kaggle/Linux khi chuyển môi trường. Chi tiết và giới hạn trong review R1.

**Điểm sửa:** scripts/cnkang_transport.py; nếu cần một worker mạng riêng thì thêm entry point production có snapshot/hash; tích hợp scripts/corpus_runner.py, scripts/cnkang_check.py và builder.

**Cách sửa:**

1. Phân biệt connect/read timeout với deadline toàn request/URL. Đề xuất cấu hình khởi điểm: 45 giây/request gồm DNS/connect/read; 120 giây/URL gồm robots, redirect, retry và khoảng nghỉ. Mỗi request phải nhận phần budget còn lại của URL.
2. Tách thao tác mạng có thể treo sang worker process do supervisor kiểm soát; giữ tối đa một request hoạt động. Supervisor sở hữu việc ghi raw/checkpoint, robots policy, throttle và cooldown.
3. Worker duy trì session khi còn hợp lệ; khi quá deadline phải terminate/join worker, bỏ kết quả đến muộn và bảo đảm không còn request hoặc thao tác ghi ngầm. Không dùng chỉ một future/thread timeout rồi để DNS/request tiếp tục chạy phía sau.
4. Entry point phải chạy được với Windows spawn và notebook Kaggle; không dựa vào closure trong cell hoặc module động không import được ở process con. Nếu thêm file worker, nhúng và kiểm hash cùng snapshot.
5. Retry hữu hạn nằm trong cùng budget, không nhân deadline qua từng attempt. DNS lỗi không được xử lý bằng đổi sang HTTP hoặc đổi IP/DNS; giữ HTTPS trước, robots và quy tắc không né 403/429.
6. Ghi riêng loại/stage lỗi: DNS, connect/reset, read, robots, deadline, checkpoint. Giữ nguyên exception gốc; không để nhãn “robots unverifiable” che mất nguyên nhân DNS trước đó.
7. Đưa circuit breaker vào runner production: dừng khi gặp block/challenge, deadline nghiêm trọng hoặc chuỗi lỗi theo cấu hình; lưu lý do dừng và pending. Không tự mở một retry-run.
8. Khi máy/process bị tạm dừng rồi hoạt động lại, kết quả quá deadline phải bị từ chối. Không hứa deadline vật lý trong lúc hệ điều hành không lập lịch được supervisor; log đủ để nhận diện gián đoạn thời gian.

**Nghiệm thu:**

- Test resolver treo, stream trả từng phần quá chậm, reset, nhiều redirect và retry: URL kết thúc trong budget cộng khoảng dọn worker hữu hạn.
- Sau timeout không còn worker/request nền và không có ghi muộn; không vượt một request đồng thời.
- Robots cũng chịu deadline; 403/429/challenge giữ đúng stop/cooldown, không đổi giao thức để vượt chặn.
- Kiểm trên Windows và môi trường notebook/Linux; trước live dùng server/fault giả lập, không làm website thật quá tải.

## R2 / P0 — Ghi checkpoint chịu được khóa file Windows

**Đã làm:** temp riêng, flush/fsync, replace tối đa 3 lần trong budget 2 giây;
giữ file cũ và bản .recovery khi hết retry; một writer; state/cooldown hợp nhất
bảo thủ; raw/text theo content hash; phục hồi response/record trước khi GET.
66/66 test đạt, gồm khóa Windows thật, process exit và recovery qua ZIP.
Replay offline cùng 50 raw đạt 50/50 sau 80 sự kiện lỗi chèn, không GET lần hai;
text hash/audit đều 50/50 khớp. Không chạy mạng trong R2. Chi tiết ở review R2.

**Điểm sửa:** scripts/cnkang_transport.py:write_json/append và các chỗ cập nhật state/record; cập nhật adapter/runner để phân biệt lỗi lưu với fetch.

**Cách sửa:**

1. Chỉ một writer trong supervisor. Dùng temp duy nhất cùng thư mục đích, flush và replace nguyên tử; tránh tên .tmp cố định dùng chung.
2. Với PermissionError/sharing violation: retry riêng thao tác replace theo backoff ngắn và tổng budget nhỏ; không phát lại GET chỉ vì lưu state lỗi. Ví dụ tối đa 3 lần trong khoảng 2 giây, kiểm bằng test trước khi chốt mặc định.
3. Không xóa state tốt đang có để né replace lỗi. Nếu hết budget, giữ bản cũ hợp lệ/temp có thể phục hồi, dừng với CHECKPOINT_WRITE_FAILED; không đếm thành công trước khi commit.
4. Chỉ raw đã ghi và kiểm hash mới được đưa vào manifest/record. Giữ thứ tự commit để crash giữa các bước có thể phục hồi mà không nhân đôi URL/text.
5. Phân loại lỗi ghi state của ID 1853035 là lỗi lưu local, không báo như bằng chứng website không truy cập được. Khi phục hồi giữ not_before/cooldown theo giá trị bảo thủ nhất.

**Nghiệm thu:**

- Replace lỗi tạm thời rồi thành công: JSON cuối hợp lệ, GET chỉ một lần.
- Lỗi vĩnh viễn: state cũ không mất, không record accepted giả, runner dừng rõ nguyên nhân.
- Test crash sau ghi temp/raw/manifest/record và resume: không mất dữ liệu, không lặp text/ID, không reset cooldown.

## F2 + F3 / P1 — Toàn văn phân trang kèm audit/recovery

**Đã làm:** cùng bài/số trang/title/template/date/body được xác minh; checkpoint
và raw từng phần; manifest bất biến; audit tái dựng toàn chuỗi trước export;
resume/recovery không GET lại phần đã lưu, offline không gọi mạng.
Mặc định 6 trang và deadline chuỗi 360 giây. Replay 9/9 chuỗi/26 trang và 611/611
raw F1 đạt. Ba bài thiếu trang tiếp, unknown 1690503 và pager mâu thuẫn 1405611
giữ incomplete/review; chưa nghiệm thu live ba chuỗi mới. Chi tiết ở review F2/F3.
Kiểm cuối: 128/128 test đạt, gồm 88 test cnkang và 40 test tích hợp/hồi quy liên quan;
snapshot main/domain/check khớp production. Lượt F2/F3 không gọi mạng bên ngoài.

**Điểm sửa:** scripts/cnkang_transport.py, scripts/corpus_runner.py, scripts/cnkang.py:audit, scripts/corpus_audit.py, scripts/cnkang_check.py và builder. Chi tiết kiến trúc đã có trong [plan tích hợp](cnkang_main_crawler_rollout_20261020.md).

**Cách sửa:**

1. Tách trạng thái parse một trang khỏi article_complete của cả bài. Bốn case mới: 1851609, 3529935, 3530118 và 1690503.
2. Chỉ theo next link đã xác minh cùng bài: host/path gốc, số trang kế tiếp, redirect, title, template và ngày khi có; chống vòng lặp/body trùng/nhảy bài.
3. Mỗi phần có raw/hash/URL/status/checkpoint riêng. Trang phụ không sinh ID corpus và không làm tăng MAX_NEW như một record nguồn mới.
4. Ghép theo thứ tự; chỉ bỏ overlap biên khớp chính xác. F1 tiếp tục xử lý thứ tự/pager từng phần. Kiểm QC lại toàn bài thay vì dùng SHORT_TEXT của một trang thành phần làm kết luận cuối.
5. Audit tái dựng từ tất cả raw và manifest. Thiếu/đổi phần, sửa thứ tự hoặc đánh complete sai phải fail audit và chặn export như bài đầy đủ.
6. Resume reuse phần đã lưu; lỗi giữa chuỗi vẫn giữ pending/review. POSTPROCESS_ONLY không gọi mạng.
7. Với unknown layout 1690503, chỉ theo pagination sau khi Q2 xác nhận biên bài/template. F2 không dùng fallback mơ hồ để ghép đại; case này được giữ review trong khi triển khai các template đã biết.

**Nghiệm thu:**

- Replay offline 9 chuỗi/26 raw cũ, giải thích mọi khác biệt với mốc 9.723 ký tự.
- Test next link giả, redirect sai, title đổi, vòng lặp, thiếu raw, sửa hash và ngắt giữa chuỗi; không accepted khi chưa đủ.
- Ba case phân trang có template đã biết trong mẫu mới được xác minh toàn văn khi có lượt live được yêu cầu; unknown chỉ nghiệm thu sau Q2.

## Q1 / P1 — QC theo cấu trúc danh sách và lượt trả lời

**Đã làm:** QC theo scope DOM/danh sách/marker/lượt trả lời; bỏ nhầm do phân cấp,
outline và số đo trong bảng; phân biệt câu lặp theo nhóm với khối lặp chưa rõ.
Giữ nguyên toàn bộ text/số/bảng/provenance F1 trên 611 raw. 31/47 cờ đánh số và
5/7 cờ lặp được gỡ/phân loại lại; 16 và 2 cờ còn lại giữ review. Parser sạch
492→526, không clean→review. Hai ca lặp theo nhóm thêm tín hiệu nguồn để đọc lại.
13 test Q1 với 16 raw fixture và ca âm; bộ kiểm cuối 141/141 đạt.
Đây là hồi quy đã biết, chưa nghiệm thu tập nhãn độc lập 80/40 để hiệu chuẩn
ngưỡng. Không tự gỡ các cờ còn lại theo suy đoán ngữ nghĩa; Q2/Q3 vẫn tách riêng.

**Điểm sửa:** scripts/cnkang.py:node_text/review_text và sidecar/provenance; audit và test production tương ứng.

**Cách sửa:**

1. Giữ ranh giới đoạn, heading, list level/style, DOM path và lượt trao đổi có dấu hiệu rõ ràng; không flatten hết rồi so mọi số trong toàn tài liệu.
2. Chỉ coi số giảm là bất thường trong cùng list/scope. Chuyển danh sách cha → con, heading mới hoặc lượt trả lời mới được đánh giá riêng, không đảo nội dung.
3. Case 1782034 là danh sách con bắt đầu lại; 1544618 là một lượt trả lời khác bắt đầu từ 1. Thêm ca âm thật: 3→2→1 trong cùng nhóm, không có heading/lượt mới.
4. Với 7 cờ lặp đoạn, xét phạm vi: lặp dưới các mục khác nhau có thể hợp lệ. Case 1759215 giữ câu lặp thuộc các nhóm riêng; chỉ bỏ duplication có bằng chứng UI/ghép trùng, còn lại lưu cờ nội dung nguồn.
5. Các case chưa đủ dấu hiệu cấu trúc giữ review; không gỡ toàn bộ 44 trang chỉ có DESCENDING_NUMBERING_REVIEW để đạt số sạch cao hơn.

**Nghiệm thu:**

- Fixture reset hợp lệ hết cờ sai; ca đảo thật vẫn bị giữ review.
- Không thay thứ tự/text ngoài hành động đã chứng minh; 122 ca JS F1 tiếp tục khớp.
- Báo bảng giữ/gỡ cờ theo ID và lý do, không chỉ tổng số accepted.

## Q2 / P2 — PUA, encoding và bố cục chưa hỗ trợ

**Đã làm:** 24 glyph được chuẩn hóa theo ngữ cảnh, giữ 5 glyph chưa rõ ở 3 record;
giải thích được uncertain của 1708607, giữ cả PUA/uncertain cho 1772904.
1850128/1906646 giữ PUA. Chặn chọn decoder khác chỉ để giảm PUA và bảo vệ ký hiệu
trong ô bảng. Xác minh legacy_table của 1690503 bằng ID/title/date và cột header/body;
F2 nhận next nhưng recovery offline vẫn incomplete. 14 test Q2 với 9 raw fixture
và ca âm; raw, charset/candidates và formatter F1 giữ nguyên trên toàn mẫu.
Kiểm cuối 155/155 test đạt; audit/raw 611/611, text đổi đúng whitelist ở 7 record,
604 record còn lại giữ nguyên. 9 chuỗi/26 trang vẫn khớp 9.723 ký tự.
Đây là nghiệm thu những rule đủ bằng chứng, không phải gỡ mọi glyph chưa rõ hoặc
xác nhận toàn văn của 1690503. Q3 vẫn tách riêng.

**Điểm sửa:** scripts/cnkang.py:decode_bytes/clean_node/choose_body/review_text; fixture và audit.

**Cách sửa:**

1. Với 8 PUA, chỉ chuẩn hóa glyph đã xác nhận bằng raw/DOM/font/vị trí. Ví dụ 1844705 có glyph ở vị trí bullet, 1728042 ở vị trí đệm. Không xóa toàn bộ vùng Unicode PUA.
2. Lưu ký tự gốc, vị trí, rule và text trước/sau. Không sửa số, liều lượng, ký hiệu/gene hoặc nội dung y khoa để “làm sạch”.
3. Hai case encoding uncertain 1772904 và 1708607 đều có PUA: kiểm strict decode và nguồn của glyph; phân biệt formatting với hỏng byte thật. Chỉ gỡ cờ encoding khi có bằng chứng, giữ metadata encoding gốc.
4. Đọc raw 1690503 để xác định heading và biên body của biến thể thực tế. Chỉ thêm selector/template có anchor đúng bài; test menu/sidebar/ads không lọt vào text.
5. Nếu chưa xác định được biên bài thì tiếp tục unknown/review. Không mở rộng trafilatura hoặc tự xóa pager trên fallback chỉ để hết cờ.

**Nghiệm thu:**

- Bullet/khoảng đệm đã xác minh được chuẩn hóa có provenance; glyph lạ vẫn review.
- Các fixture chứa ký hiệu khoa học và nội dung có số giữ nguyên; audit tái lập đúng.
- Template mới giữ heading/body/next link đúng nguồn và không lấy menu; đủ điều kiện mới đưa 1690503 sang kiểm F2.

## Q3 / P1 — Short text, metadata và gate nguồn

**Cập nhật 21/10/2026 — đã triển khai report_only:** xem [review Q3](../reports/cnkang_q3_review_20261021.md)
và [kế hoạch Q3 chi tiết](cnkang_q3_source_gate_20261021.md) để đối chiếu điểm sửa,
fixture/tiêu chí và phần nhãn độc lập còn lại. Baseline Q2 trước triển khai:
531 parser accepted/80 review, 57 short text (2 incomplete), 611 thiếu meta author,
368 cờ title–body và 16 parser accepted có claim/experience flag. Mốc 14 ở phần
cơ sở F1 là số lịch sử. Sau Q3, title–body còn 185 cờ, claim 9, experience 13;
source KEEP/REVIEW 399/212 và corpus KEEP/REVIEW 384/227 đều là đề xuất. Parser
vẫn 531 accepted/80 review; không đổi text hoặc tăng accepted để nghiệm thu.

**Điểm sửa:** metadata/source signals trong scripts/cnkang.py; một policy module production riêng nếu cần; chỗ quyết định export ở runner/audit. Giữ hợp đồng cột corpus, trường chẩn đoán có thể ở sidecar.

**Cách sửa:**

1. Tách kết quả fetch, extraction, completeness và source/corpus decision. Parser sạch chỉ tạo ứng viên; không đồng nghĩa đã đạt chuẩn nguồn.
2. Với 57 short text, xác minh body đầy đủ trước: 19 dưới 50 ký tự, 7 từ 50–99, 31 từ 100–199. Ba case 1716739/1792421/1889767 thực sự ngắn trong raw: giữ lý do thiếu thông tin/nguồn, không đoán phần thiếu từ title, không crawl bài liên quan để bù và không hạ ngưỡng toàn cục.
3. Lấy author/reviewer/respondent từ meta/byline/DOM có locator và mức xác minh; phân biệt người được trích dẫn với tác giả tài liệu. Case 1544618 có người trả lời trong body nhưng không có meta author.
4. Title/body dùng tín hiệu phù hợp tiếng Trung như char n-gram/term coverage, hiệu chuẩn trên tập nhãn. Case 1782034 cùng chủ đề nhưng không lặp nguyên câu title phải được xử lý; thêm ca ghép nhầm bài thực để bảo đảm không gỡ cờ sai.
5. Claim quảng bá/trải nghiệm cần bối cảnh, phủ định và nhiều tín hiệu. 1740065 là ca cần gate nguồn; 1516530 chỉ có từ khóa “điều trị dứt điểm” không đủ để kết luận quảng cáo hoặc xác nhận y khoa.
6. Xét loại nguồn như bài phổ thông, trao đổi hỏi đáp, tin tức, trải nghiệm/quảng bá. Không hard-drop toàn bộ nhánh theo path; không hard-drop 611 bài chỉ vì thiếu meta author.
7. Chốt policy và chạy ở chế độ báo cáo trước, rồi mới bật gate cứng sau đánh giá tập kiểm có nhãn. Mỗi KEEP/REVIEW/EXCLUDE cần lý do/provenance; chưa rõ thì review, không tự xác nhận tính đúng chuyên môn.

**Nghiệm thu:**

- 16 trang sạch parser có cờ claim/trải nghiệm ở baseline Q2 được review/phân loại riêng (F1 trước đây là 14); không đi thẳng vào corpus chuẩn chỉ nhờ parser sạch. Đây là hợp tín hiệu, chưa phải nhãn nguồn xấu.
- Có bảng lỗi trước/sau cho author, title/body, claim và short text trên tập kiểm đóng băng; báo cả giữ nhầm và loại nhầm.
- Không đổi quyết định bằng cách tối ưu số accepted; không biến kết quả heuristic thành nhãn gold.

## Kiểm chứng, phát hành và điểm dừng

Mỗi hạng mục là một vòng riêng: đóng băng code/fixture → sửa trong phạm vi → test liên quan → replay offline → review diff. Có lỗi thì ghi kết quả và dừng hạng mục; không tự mở các vòng sửa/retry mạng vô hạn.

1. R1/R2: fault injection/local server trước, kiểm deadline và dữ liệu checkpoint. Không cần crawl lại 611 URL.
2. F2/Q1/Q2/Q3: dùng 611 raw, 9 chuỗi cũ và tập nhãn; audit lại bằng code mới, mọi thay đổi nội dung/decision có diff theo ID.
3. Sau test đạt, đồng bộ snapshot production và kiểm hash/diff cả hai notebook crawler. F1 đã đạt phải tiếp tục qua bộ hồi quy; không thay hành vi domain khác.
4. Lượt live tiếp theo chỉ thực hiện khi người dùng yêu cầu. Có thể ưu tiên phần pending của manifest cũ để hoàn tất mục tiêu ban đầu, giữ bất biến 615 record/bằng chứng của run cũ và dùng run mới/recovery khi code đổi; không gọi phần pending là mẫu mới. Nếu cần holdout mới thì chọn manifest mới và loại toàn bộ 1.000 URL đã chọn cùng mọi URL lịch sử/trang phụ đã biết.
5. Báo riêng processed/fetched/parsed/article_complete/parser_review/source_review/pending và lý do dừng. Không công bố “test đủ 1.000 URL” khi mới hoàn tất một phần.

Phần thử nghiệm tiếp tục chỉ nằm trong **notebooks/check_cnkang.com.ipynb**, gitignored, gồm code nhúng và output. Không tạo notebook check hoặc helper thí nghiệm rời trong repo. Code/rule/test production và tài liệu plan/review vẫn được giữ trong Git.
