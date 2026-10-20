# Run mới 120ask V3.1 và review kết quả — 20/10/2026

**Kết luận review: NEEDS_PARSER_FIX.** Run mới chạy thành công và các kiểm tra artifact đạt. Review nội dung/DOM tìm thấy hai blocker: lời nhắc thao tác bị coi là câu trả lời chữ trong một số reply audio, và vai bác sĩ được gán cả khi header nguồn chỉ ghi “其他” (khác). Cần xử lý trước khi đưa candidate thành corpus đã duyệt.

Run: `runs/ask120_review_20261020T013753043042Z/`, tạo lúc **08:37:53 ngày 20/10/2026, giờ Việt Nam**. Mode **offline replay** trên ZIP gốc 1.000 URL; không phải crawl live hay mẫu URL độc lập mới. Không ghi đè run trước, không gửi request hoặc upload. Parser/gate/policy giữ nguyên bản V3.1 đã sửa ở lượt trước.

## Kết quả chạy và kiểm tra artifact

| Chỉ số | Kết quả |
|---|---:|
| Raw kiểm hash / parse | 1.000 / 1.000 |
| Raw/parse error | 0 |
| Regression chuẩn | 9/9 đạt |
| Candidate document / source ID duy nhất | 775 / 775 |
| Thread INCLUDE / REVIEW / EXCLUDE | 1.260 / 223 / 75 |
| Trang INCLUDE / INCLUDE_PARTIAL / REVIEW / EXCLUDE | 680 / 95 / 94 / 131 |
| DOM locator của lượt đã đối chiếu | 1.829 |
| Source span trong candidate đã đối chiếu | 1.498 |
| Sai hash/mapping/schema/span trong kiểm tra này | 0 |
| Parquet và JSONL theo các cột production | Khớp từng record |
| Trang có media câu hỏi / lọt vào candidate | 18 / 0 |
| Review bắt buộc / nhãn thủ công thực sự đã có | 144 / 0 |

So với `ask120_gate_20261020T011215679553Z`: không thêm/bớt candidate ID, không đổi text candidate, không đổi quyết định trang. Không thấy ba lỗi đã sửa trước đó tái xuất hiện trong các đường chạy của lượt này. Lượt này tập trung chạy và review dữ liệu; không chạy lại toàn bộ unit test vì source không đổi.

Gate tự động vẫn trả `READY_FOR_FILTERED_PILOT`. Kết luận AI review được lưu riêng là `NEEDS_PARSER_FIX`, có bằng chứng bên dưới. Các invariant hiện có chưa kiểm hết chất lượng ngữ nghĩa; riêng chỉ số audio fallback bằng 0 không chứng minh mọi đoạn text còn lại là câu trả lời có nội dung.

## Phạm vi review

- Đã đọc/đối chiếu packet **82 thread**: 50 INCLUDE được lấy phân tầng theo thập niên ngày hỏi, độ dài, template và partial-page; thêm 32 thread regression/đại diện reason không trùng.
- Soi thêm toàn bộ **9 mixed reply**, 16 câu hỏi candidate dưới 10 ký tự sau compact, các trang biên được nêu dưới đây và tín hiệu tự quảng bá/liên hệ.
- Quét header tác giả theo DOM trên toàn bộ 1.000 raw; so vị trí nguồn với reply/card, giữ nguyên qualification text làm bằng chứng.
- Đây là review của **AI về trích xuất, vai, nhiễu và mức đầy đủ của dữ liệu**, không phải nhãn con người hoặc thẩm định đúng/sai y khoa. File `manual_review_sheet.csv` không bị điền bằng nhãn AI.

Kết quả ghi chú 82 thread: 35 đạt phần cấu trúc trích xuất, 17 phù hợp với quyết định hold hiện tại, 24 cần review metadata/nội dung/chuẩn hóa nguồn, 6 có lỗi INCLUDE được xác nhận. Các nhóm này có mục đích chẩn đoán; mẫu phân tầng không dùng để ước lượng tỷ lệ lỗi toàn domain.

## Phát hiện cần xử lý

### F1 — P1: sáu reply audio chỉ có lời nhắc thao tác vẫn vào corpus chữ

Source ID: **1025409, 1029798, 1031179, 1053679, 1087866, 1404664**.

Ví dụ `1029798 / card1:reply756152`: phần text sạch chỉ là “如果有了满意的回答请及时采纳，不要辜负了回答者！” — yêu cầu bấm chấp nhận câu trả lời. Raw của reply có audio và fallback trình duyệt. Sau khi bỏ fallback, parser giữ lời nhắc, phân loại mixed; chuỗi dài hơn ngưỡng 20 nên gate INCLUDE.

Các biến thể khác yêu cầu “点击采纳答案”, “采纳为答案” hoặc chuyển sang tư vấn trực tuyến; không có câu trả lời nội dung cho câu hỏi. Đã xác nhận **6 thread trên 6 trang**. Hai document `1031179`, `1404664` chỉ có thread lỗi; bốn document còn lại có thread khác có thể giữ. Nếu chỉ loại sáu thread này, số document còn 773 — đây là phép đếm tác động, chưa phải corpus đã duyệt.

**Nên sửa:** nhận diện boilerplate bằng bằng chứng template/chữ ký cụ thể, bỏ nó trước khi phân loại media và đếm độ dài ngữ nghĩa. Remainder rỗng thì audio-only, không vào corpus chữ. Remainder ngắn thì REVIEW. Phải giữ mixed thật: `1159296` có text nội dung đầy đủ; `1173870` chỉ còn text rất ngắn sau lời chúc nên cần review riêng.

Điểm sửa: `scripts/ask120.py:241`, `scripts/ask120_gate.py:152`. Dùng cả chín mixed reply của run làm fixture, gồm ca text thật và các biến thể lời nhắc; thêm ca text nội dung + lời nhắc để không xóa nhầm cả câu trả lời.

### F2 — P1: nhãn “bác sĩ trả lời” chưa có bằng chứng cho nhiều tác giả

Trong 1.260 thread INCLUDE, header sau khi tách tên cho thấy:

| Bằng chứng trên nguồn | Thread |
|---|---:|
| Có chuỗi chức danh y sĩ/bác sĩ trên header | 842 |
| Ghi rõ “其他” (khác) | 307 |
| Vai khác hoặc chưa xác định (có cả dược sĩ/điều dưỡng…) | 111 |

**307 thread thuộc 222 trang** ghi “其他” vẫn được xuất với role `doctor_answer` và nhãn “医生回答”. Chức danh hiển thị cũng chỉ là thông tin do nguồn đưa ra, chưa xác minh giấy phép bên ngoài. Không kết luận tất cả người ghi “其他” không phải bác sĩ; lỗi là corpus khẳng định vai mà chưa có bằng chứng tương ứng.

Ca rõ: `1351960 / card1:reply2180544`, header là một tên dạng địa chỉ IP và “其他”; nội dung chỉ chia sẻ mình cũng chóng mặt, không biết nguyên nhân, lo chuyện học. Reply này vẫn INCLUDE như câu trả lời bác sĩ.

**Nên sửa:** giữ `author_name`, qualification text, `source_role`, DOM locator và phạm vi card/reply; dùng vai/nhãn người trả lời trung tính nếu nguồn ghi khác/chưa rõ. Không suy từ nickname có chữ “医生”. Đánh dấu REVIEW khi policy cần bác sĩ mà thiếu bằng chứng. Đừng tự loại tất cả dược sĩ/điều dưỡng: cần giữ đúng vai và xét theo mục tiêu corpus.

Điểm sửa: nhãn ở `scripts/ask120.py:25`, `_role()` dòng 136 và phần lấy tên dòng 300. Thêm fixture cho “其他”, tên dạng IP, dược sĩ, điều dưỡng, bác sĩ có chức danh và card có nhiều reply.

### F3 — P2: lọc claim nguồn bỏ sót tự quảng bá và dẫn liên hệ

Tìm thấy **9 thread INCLUDE trên 8 trang** có tín hiệu tự giới thiệu phòng khám/điều trị hoặc dẫn liên hệ mà `source_flags` còn trống. Đây là tập tín hiệu đã quan sát, không phải phép đo recall quảng cáo của toàn domain.

Ví dụ mạnh:

- `1168492 / card2:reply2784152` và `2770682 / card4:reply683558`: văn bản quảng bá cùng cơ sở mắt, nhắc “祖传验方”, “特效系列方剂”, hứa kết quả điều trị theo tháng. Hai câu trả lời giống nhau sau compact dù câu hỏi khác.
- `2899724 / card1:reply1590117`: tự giới thiệu phương pháp “最先进”, kèm claim “1到3个月都能治愈”.
- `1329046`, `1326948`, `1240571`, `1375991`: có lời dẫn bấm tên/ảnh để liên hệ; cần xem ngữ cảnh thay vì chỉ tìm vài từ “根治/无副作用”.

**Nên sửa:** kết hợp tự xưng cơ sở, CTA liên hệ, claim hiệu quả và mẫu hứa chữa khỏi để đưa REVIEW. Không kết luận y khoa sai chỉ từ từ khóa. Cũng cần giảm false positive: `1164309 / card5:reply522282` viết “未彻底根治” trong mô tả diễn tiến, vẫn bị gắn claim quảng bá do regex hiện tại; “根治” trong mô tả điều trị không tự động là marketing.

Điểm sửa: `scripts/ask120_gate.py:32`. Thêm fixture false negative nêu trên và các ca phủ định/thuật ngữ lâm sàng để so precision/recall của cờ nguồn.

### F4 — P2: một số cặp hỏi–đáp không xác định được vấn đề đang hỏi

- Source ID `1205311`: cả title và body chỉ “怎么治疗啊!” — “điều trị thế nào”; câu trả lời nêu cách điều trị mà không còn bệnh/tình huống nguồn để xác định.
- Source ID `1183810`: title “没治过 ,能治好吗”, body “9年 没治过 能治好吗”; đều không nói đang hỏi bệnh/vấn đề gì.

Đây là thiếu ngữ cảnh trong HTML nguồn đã tải, chưa thấy bằng chứng parser làm rơi một phần body khác. `question_valid` hiện chỉ đòi có một node và text khác rỗng.

**Nên sửa:** thêm cờ question-context độc lập, kiểm cả title/body. Không dùng ngưỡng ký tự đơn thuần: 16 candidate có câu hỏi dưới 10 ký tự, nhiều câu vẫn rõ chủ đề như “什么是血性恶露”. Source `2686938` có body “谢谢” nhưng title hỏi rõ về tiếp tục dùng thuốc sau giảm mỡ máu; đây là ca cần hợp đồng title/body minh bạch, không thể gộp với câu hỏi hoàn toàn vô nghĩa.

Điểm sửa: `scripts/ask120.py:281` và admission policy. Không đoán bệnh từ câu trả lời để làm đầy câu hỏi.

### F5 — P2: còn nhiễu trong câu hỏi ngoài coverage markup hiện tại

**31 trang candidate** còn mảnh literal `BR>` trong question; ví dụ `1383704`, `1351960`, `1290838`, `1375991`. Raw của `1383704` thực sự chứa `BR&gt;` rồi đến các thẻ br. Đây là nhiễu nguồn được giữ lại, không phải tag định dạng hoàn chỉnh nên bộ đếm legacy markup hiện tại không bắt.

Source `1404664` còn footer “| 投诉 | 评价(0” trong question. Gate kiểm UI marker ở turn text, chưa kiểm question tương ứng nên cờ cấp parser không chặn candidate này.

**Nên sửa:** áp dụng chuẩn hóa có giới hạn cho question, lưu raw/hash/actions; chỉ sửa mảnh định dạng có bằng chứng. Mở QC sang question, tách footer theo dấu hiệu template. Giữ bất đẳng thức, gene và nội dung thật; không dùng regex xóa mọi chuỗi có dấu lớn/bé.

## Quan sát bổ sung

- Có ba nhóm main answer lặp giữa các trang khác nhau. Một nhóm là lời nhắc thao tác ở F1, một nhóm là quảng bá mắt ở F3; nhóm còn lại là lời đáp ngắn giống nhau cho chủ đề tai. Giữ mapping nguồn, review theo ngữ cảnh; không tự dedup mọi text trùng.
- 348 candidate có ngày hỏi thuộc thập niên 2000, 317 thuộc 2010, 110 thuộc 2020. **85,8% có ngày hỏi trước 2020**; đây không phải ngày viết mọi câu trả lời. Cần metadata/thẩm định chuyên môn nếu dùng như nguồn kiến thức y khoa hiện hành.
- Review này chưa đo retrieval/RAG, chưa thẩm định y khoa và không chứng minh khả năng truy cập website hiện tại.

## Artifact và cách dùng tiếp

Trong thư mục run:

- `summary.json`, `report.md`: số liệu và readiness tự động của gate.
- `artifact_audit.json`: hash/schema/mapping/source-span và so với run trước.
- `agent_review_summary.json`, `agent_review_findings.jsonl`: kết luận AI và năm finding.
- `agent_extraction_review.csv/jsonl`: ghi chú 82 thread, có `reviewer_kind=AI_assistant`.
- `known_problem_threads.csv`: sáu UI-only reply và reply chia sẻ của tác giả “其他” đã xác nhận để ưu tiên xử lý.
- `mixed_answer_audit.json`, `author_role_evidence.jsonl`, `unflagged_promotion_and_contact_signals.json`, `short_question_audit.json`, `question_markup_fragments.json`: bằng chứng từng nhóm.
- `agent_review_packet.md/jsonl`: packet text/raw/DOM của mẫu review.
- `manual_review_sheet.csv`: giữ 144 mục chờ nhãn; không bị điền bằng nhãn AI.

Runner: `tmp/run_120ask_new_review.py`; audit nội dung: `tmp/audit_120ask_result_quality.py`; finalizer: `tmp/finalize_120ask_new_review.py`. Bản sao script/source nằm trong `support/` để truy nguyên. Chạy runner từ root repo tạo thư mục timestamp mới; hai script review đọc đường dẫn tại `tmp/120ask_new_review_location.json`.

[Mở thư mục run](../../runs/ask120_review_20261020T013753043042Z) · [Kết luận AI](../../runs/ask120_review_20261020T013753043042Z/agent_review_summary.json) · [Ghi chú 82 thread](../../runs/ask120_review_20261020T013753043042Z/agent_extraction_review.csv) · [ZIP đầy đủ](../../runs/ask120_review_20261020T013753043042Z.zip).

Ưu tiên vòng sửa tiếp: **F1 → F2 → F3 → F4/F5**, thêm fixture thực tế rồi replay lại cùng mẫu để so tác động ở cấp thread. Lượt này giữ nguyên parser/policy và output candidate để kết quả review có thể đối chiếu; chưa áp các đề xuất mới vào source hoặc tự phê duyệt corpus.
