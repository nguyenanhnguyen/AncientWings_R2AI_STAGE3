# Rà lại 120ask sau F1–F5 — 23/10/2026

**Vẫn còn lỗi lọt candidate.** Đợt rà này xác nhận **15 thread ở 15 trang đang INCLUDE** cần sửa hoặc hold: **F3: 7; F1: 6; F4: 1; F6 mới: 1**. Có thêm **2 trang lặp nội dung từ nguồn** cần QC. Đây là số ca đã xác nhận, không phải tổng lỗi toàn domain.

Kết luận review nội dung: **`NEEDS_PARSER_AND_GATE_FIX`**. Những ca cũ F1–F5 đã qua test vẫn đạt trong phạm vi đã kiểm trước đây; các biến thể tìm thêm dưới đây cho thấy chưa thể đóng lỗi cho toàn domain.

## Phạm vi và bằng chứng

- Rà lại run `ask120_f4_20261023T142240359846Z`: **1.000 raw, 644 candidate document, 922 thread INCLUDE**. Run review: `ask120_postfix_review_20261023T145532112516Z`, bắt đầu 21:55:32 ngày 23/10/2026, giờ Việt Nam.
- Kiểm lại hash raw và trích xuất từ HTML trên **1.000/1.000 trang**, đối chiếu 47.467 span context và admission của toàn bộ 922 INCLUDE. **0 lỗi toàn vẹn/cấu trúc, 0 request mạng**. Source hiện tại khớp parser/gate SHA của run F4.
- Đọc đầy đủ title, question và toàn bộ turn được INCLUDE của **50 trang bổ sung**, seed `2026102306`. Mẫu này tránh các packet review trước được nạp vào script nhưng có thể trùng fixture; không phải tập đánh giá độc lập. Xác nhận 3 trang có lỗi trong mẫu: `1058170`, `926446`, `1276393`.
- Rà thêm các lead contact/quảng bá, claim và UI trong INCLUDE; kiểm ngữ cảnh từng câu rồi xác nhận các ca trong bảng. Regex rộng tạo 9 lead contact, 50 lead claim và 11 lead UI, **không coi tất cả lead là lỗi**. Có 379 lead câu hỏi, chưa đọc thủ công toàn bộ.
- Mỗi ca xác nhận có source ID, URL, thread, raw hash, DOM locator/HTML, đoạn bằng chứng và quyết định thực tế. Không có nhãn người thật hoặc đánh giá độ đúng y khoa.

## Các lỗi còn lại

| Ưu tiên | Nhóm | Số ca xác nhận | Vấn đề và hướng sửa |
|---|---|---:|---|
| **P1** | F3 — chỉ dẫn liên hệ thay câu trả lời | **1** | Reply chỉ yêu cầu fax bệnh án và liên hệ riêng nhưng đủ ngưỡng 20 ký tự nên INCLUDE. CTA cá nhân độc lập phải REVIEW, không bắt buộc có thêm cụm “cần giúp đỡ”. |
| **P1** | F1 — boilerplate làm vượt ngưỡng | **1** | Bỏ footer website bằng thao tác chẩn đoán thì nội dung thật chỉ còn 15 ký tự và chuyển REVIEW. Mở rộng chuẩn hóa có bằng chứng, rồi tính lại độ dài/media. |
| **P2** | F3 — tự quảng bá/cam kết chưa gắn cờ | **6** | Bỏ sót miễn phí nhận sản phẩm, dịch vụ của “bệnh viện chúng tôi”, phương pháp/sản phẩm có cam kết tuyệt đối. Bổ sung mẫu theo ngữ cảnh, lưu span; không dùng từ lâm sàng đơn lẻ. |
| **P2** | F1 — nhiễu nhắc thao tác/điều hướng | **5** | Các biến thể nhắc chấp nhận câu trả lời và dẫn sang tư vấn trực tuyến vẫn nằm trong text. Bỏ đúng span, giữ phần trả lời thật và raw/actions. |
| **P2** | F4 — tham chiếu kết quả không có dữ liệu | **1** | Câu hỏi yêu cầu xem xét nghiệm nhưng không có kết quả, vẫn `context_present` vì các từ đệm chưa bị nhận diện. Tách nội dung xác định được vấn đề khỏi lời dẫn “xem giúp kết quả”. |
| **P2** | **F6 mới — câu trả lời lệch chủ đề** | **1** | Nguồn trả lời bằng một đoạn về chủ đề khác; parser trích đúng nhưng gate vẫn nhận. Thêm QC quan hệ hỏi–đáp; ca nghi vấn REVIEW, không xóa hoặc viết lại lời nguồn. |
| **P3** | Lặp nội dung trong nguồn | **2 trang** | Question lặp nguyên văn hoặc paragraph answer lặp hai lần. Thêm cờ exact repetition và provenance; tránh dedup nhầm câu hỏi bổ sung/đối thoại. |

### F3: 7 thread hiện `source_flags=[]`

| Source ID / thread | URL | Bằng chứng |
|---|---|---|
| **1354101** / `card1:reply2188005` | [question/720611.htm](http://www.120ask.com/question/720611.htm) | Toàn bộ reply: “请将患儿的详细病历传真于我们，及时与我们联系。” — fax bệnh án và liên hệ, không có phần giải đáp. |
| **1289147** / `card2:reply1371825` | [question/493556.htm](http://www.120ask.com/question/493556.htm) | Nêu sản phẩm `仁寿堂止咳贴`, kết thúc `欢迎免费索取` — mời nhận miễn phí. |
| **1297030** / `card2:reply1496752` | [question/533572.htm](http://www.120ask.com/question/533572.htm) | Đề nghị CD thôi miên, rồi `我们医院可以提供` — cơ sở của người trả lời có cung cấp. |
| **1290838** / `card2:reply1399442` | [question/502912.htm](http://www.120ask.com/question/502912.htm) | `我院有安静、温暖、温馨的取精室` và so sánh xét nghiệm ở bệnh viện khác với cơ sở mình. |
| **1035081** / `card1:reply988531` | [question/1330708.htm](http://www.120ask.com/question/1330708.htm) | `完全可以百分百取出`, kèm khẳng định phương pháp nâng ngực “tốt nhất”; chưa có cờ review claim. |
| **1058170** / `card4:reply481180` | [question/14096676.htm](http://www.120ask.com/question/14096676.htm) | Nêu cơ sở/phương pháp và cao dán cụ thể, rồi hứa `从而不留任何后遗症` — không để lại bất kỳ di chứng nào. |
| **926446** / `card1:reply526157` | [question/10212084.htm](http://www.120ask.com/question/10212084.htm) | `对身体不会产生任何毒副作用` — khẳng định không có bất kỳ độc tính/tác dụng phụ; biến thể này lọt rule hiện tại. |

Đây là căn cứ yêu cầu **review nguồn**, không phải kết luận y khoa đúng/sai. `DIRECT_CONTACT` hiện còn đòi ngữ cảnh phụ, `FREE_OFFER` thiếu “索取” và cần self-reference, còn các claim rule chưa phủ các biến thể trên. Không nên sửa bằng cách bắt mọi từ “根治”, “保证” hoặc tên thuốc.

### F1: 6 thread còn boilerplate

| Source ID / thread | URL | Đoạn còn dư |
|---|---|---|
| **2979729** / `card1:reply2823805` | [question/927451.htm](https://www.120ask.com/question/927451.htm) | Footer bắt đầu `有问必答网为全民公益网站…`; phần giải đáp thật chỉ là `可以测量了，准确率还是挺高的。` |
| **1305910** / `card5:reply1602995` | [question/569059.htm](http://www.120ask.com/question/569059.htm) | `如果你对我的回答感到满意的话请及时点击为“采纳答案”谢谢！` |
| **1350615** / `card1:reply2086292` | [question/700041.htm](http://www.120ask.com/question/700041.htm) | `以上回答如果满意…点击“采纳为答案”` |
| **1015641** / `card2:reply255117` | [question/1088941.htm](http://www.120ask.com/question/1088941.htm) | Cảm ơn website, lời chúc chung và `如果满意我的回答请及时采纳答案` |
| **2881366** / `card1:reply1393284` | [question/501145.htm](https://www.120ask.com/question/501145.htm) | `上边是我的叙述，你如果满意的话，请及时采纳。` |
| **2770682** / `card5:reply153085` | [question/25056662.htm](https://www.120ask.com/question/25056662.htm) | `医生询问` dẫn vào hướng dẫn vào trang chủ → `在线咨询` |

Đã thử **chỉ trong bản sao bộ nhớ** với `2979729`: bỏ đúng footer đã đọc, giữ 15 ký tự nội dung → `review_thread()` trả **REVIEW / SHORT_MAIN_ANSWER_REVIEW** với policy hiện tại. Điều này chứng minh boilerplate đang làm thay đổi admission. Source/records/candidate gốc không bị sửa. Năm ca còn lại cần normalize rồi đánh giá lại; không mặc định xóa cả answer.

Sáu reply audio-only của finding F1 ban đầu vẫn không lọt INCLUDE. Các ca mới ở đây là biến thể boilerplate, không phải bằng chứng sáu ca audio cũ tái phát.

### F4: câu yêu cầu xem xét nghiệm nhưng thiếu chính kết quả

**2619509 / `card1:reply1004012`** — [question/108498543.htm](https://www.120ask.com/question/108498543.htm).

Title: `乳腺科医生帮我看下化验单，急有高倍悬赏`. Body chỉ nói “giúp xem xét nghiệm”, “phát hiện ba năm”, “kết quả này có nghiêm trọng không”, “có cần mổ không”; không có mô tả tổn thương, chỉ số hoặc kết luận xét nghiệm. Question DOM không chứa ảnh, `question_media=[]`, nhưng context là `context_present/both`, thread INCLUDE và không có lý do review.

Answer đề cập một nốt tuyến vú và mức 4A. Những chi tiết ở answer không bổ sung được bằng chứng còn thiếu trong question. Hướng sửa là nhận diện yêu cầu giải thích báo cáo/“kết quả này” thiếu dữ liệu, giữ raw và chuyển REVIEW; đối chứng phải giữ báo cáo có chỉ số thật và câu hỏi ngắn nêu rõ vấn đề. `1063641` (nhắc cuộc trao đổi trước và tên xịt da) được giữ làm lead cần xem thêm, không cộng vào số lỗi xác nhận.

### F6 mới: trích đúng nguồn nhưng answer không khớp câu hỏi

**1276393 / `card1:reply1124872`** — [question/44441946.htm](http://www.120ask.com/question/44441946.htm).

Question nói mắt có máu tụ, `视网膜堵塞`, hỏi hồi phục sau laser và khi nào đi làm. Answer lại là đoạn mẫu về `急性角膜炎`, kháng sinh và xem TV/máy tính; không xử lý câu hỏi laser/khả năng đi làm. Raw HTML đã có nội dung này, không phải parser ghép nhầm card. Đề nghị REVIEW vì không khớp chủ đề, chưa khẳng định chẩn đoán nào đúng.

Gate hiện kiểm nguồn, ngữ cảnh question, độ dài answer, vai tác giả và các cờ; chưa có kiểm quan hệ hỏi–đáp. Thêm bước sàng lọc quan hệ này cần bộ đối chứng cho câu trả lời chẩn đoán phân biệt, xin thêm thông tin và theo dõi sau điều trị, để không loại câu trả lời hợp lệ chỉ vì dùng từ khác.

### Lặp nguồn, ưu tiên thấp hơn

- **1285425** — [question/47708751.htm](http://www.120ask.com/question/47708751.htm): toàn question là hai bản liên tiếp giống nhau, gồm dấu `|` đầu câu.
- **1152769** — [question/22606975.htm](http://www.120ask.com/question/22606975.htm), `card1:reply1586761`: ba paragraph dài, mỗi paragraph xuất hiện hai lần trong answer. Chỉ nêu vấn đề lặp; không gán quảng bá chỉ vì đoạn có tên phương pháp PDT.

Cả hai đều đã lặp trong source. Nên gắn cờ và đo ảnh hưởng trước khi thay text, giữ action/offset/raw nếu chuẩn hóa.

## Phần chưa thấy tái phát và thứ tự xử lý

Trong audit này không thấy vi phạm author admission F2 trong INCLUDE, BR>/footer question đã sửa ở F5 tái phát, hoặc sáu ca audio-only ban đầu quay lại INCLUDE. Không suy điều đó thành toàn bộ 120ask đã sạch. 528 mục review bắt buộc của run F4 vẫn chưa có nhãn người thật.

Ưu tiên sửa **CTA thuần liên hệ + footer làm vượt ngưỡng**, sau đó phủ 6 biến thể F3 còn lại và 5 boilerplate còn lại; tiếp theo F4 báo cáo thiếu dữ liệu, rồi F6 hỏi–đáp lệch chủ đề và QC lặp. Mỗi bước cần fixture raw thực vừa tìm, đối chứng âm, replay mới và delta; chưa sửa source production trong lượt review này.

Test 120ask đã chạy lại trong lượt rà: **106/106 pass**. Các lỗi mới chưa nằm trong kỳ vọng fixture của bộ test này; việc bộ cũ pass không phủ nhận các counterexample từ raw. Hai lỗi setup `CNKANG_TRANSPORT` của PubMed/VOV đã xác nhận có trước ở lượt F4, tách khỏi các finding 120ask trên.

## Artifact

- [Tóm tắt audit](../../runs/ask120_postfix_review_20261023T145532112516Z/audit_summary.json).
- [15 ca xác nhận, kèm URL](../../runs/ask120_postfix_review_20261023T145532112516Z/confirmed_findings.md).
- [Bằng chứng có raw hash, HTML, locator và span](../../runs/ask120_postfix_review_20261023T145532112516Z/confirmed_findings.jsonl).
- [Thử nghiệm footer làm vượt ngưỡng](../../runs/ask120_postfix_review_20261023T145532112516Z/boilerplate_threshold_counterexample.json).
- [Ghi nhận review 50 trang đầy đủ hỏi–đáp](../../runs/ask120_postfix_review_20261023T145532112516Z/sample50_ai_review.jsonl).
- [Hai ca lặp nguồn](../../runs/ask120_postfix_review_20261023T145532112516Z/source_repetition_cases.jsonl).

Hash parser: `3bad0c32a95a10cc834afdeb37db8e5f90e64ee5f6e358a8a8e812b01aa7aa1e`; gate: `14cf8c29a88cdff81d55cb13abac6d16d1413da0f9c0dfef15ed8c9f4ff13c98`. Candidate vẫn là 644 document của run F4 vì đây là lượt kiểm tra; chưa áp các quyết định đề nghị vào corpus.
