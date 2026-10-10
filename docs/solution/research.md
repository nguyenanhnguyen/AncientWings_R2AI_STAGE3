# Nghiên cứu phương pháp tối ưu cho ViBioMIR với dữ liệu rất lớn và tài nguyên hạn chế

**Ngày:** 2026-10-10  
**Phạm vi:** toàn bộ hệ thống, từ crawl đến bài nộp, với ràng buộc: corpus 4,4 triệu URL, 2 laptop RTX 2050 4 GB, Kaggle T4×2, còn khoảng 3 tuần đến hạn public (31/10) và chỉ giữ **một reranker**.  
**Đọc kèm:** [data/research/data_research.md](../../data/research/data_research.md) (truy xuất phân cấp, facet), [pipeline.txt](pipeline.txt), [training_design.md](training_design.md).

## Cách làm nghiên cứu này và mức độ tin cậy

Không có máy chủ riêng để chạy thử nghiệm, và theo yêu cầu không chạy thử trên laptop. Tài liệu dựa trên ba nguồn:

1. **Kiểm tra chỉ-đọc rất nhẹ trên dữ liệu thật** (vài giây đọc `links_corpus.parquet`, `query.parquet`, kết quả EDA ngày 10/10). Ký hiệu **[dữ liệu]**.
2. **Tài liệu khoa học và model card** (danh sách nguồn ở cuối). Ký hiệu **[tài liệu]**. Phần lớn số liệu benchmark là do tác giả tự báo cáo.
3. **Suy luận có hệ thống từ công thức chấm điểm và ước lượng chi phí.** Ký hiệu **[suy luận]** và **[ước lượng]**. Các ước lượng thời gian GPU dùng giả định nêu rõ ở mục 9 và phải được đo lại.

Mọi đề xuất chưa được kiểm chứng trên dữ liệu của cuộc thi đều ghi **[giả thuyết, cần A/B]**.

---

## 0. Tóm tắt điều hành

**Kết luận chính:** với bài toán này, điểm số bị quyết định bởi **độ phủ crawl** và **cách đóng gói bài nộp theo đúng công thức chấm**, nhiều hơn là bởi model lớn hay kiến trúc phức tạp. GraphRAG đầy đủ không phù hợp: chi phí lập chỉ mục vượt ngân sách hàng chục lần, và dạng câu hỏi (một ý hỏi, đáp án nằm trong một trang) là dạng mà GraphRAG không thắng RAG thường.

Bảy quyết định xếp theo tác động dự kiến:

| # | Quyết định | Vì sao | Chi phí |
|---|---|---|---|
| 1 | **Crawl theo làn domain, ưu tiên theo truy vấn**, chạy ngay các domain dài nhất | Recall bị chặn trên bởi tỷ lệ tài liệu đúng đã crawl. Domain lớn nhất cần ~11 ngày ở 1 request/giây | Tổ chức lại crawl, không tốn GPU |
| 2 | **Nộp cửa sổ rộng gần trần ~1.024 token** quanh đoạn tìm được, thay vì chunk 320 token | Công thức chấm chia LCS cho độ dài **đoạn tham chiếu**, còn Precision đếm theo **số chunk**. Chunk dài hơn (dưới trần) không bị phạt | Gần như 0, chỉ đổi khâu D2 |
| 3 | **Ngưỡng cắt tối ưu F2 trên xác suất đã hiệu chỉnh**: giữ một mục khi xác suất đúng > F2/5 | Lý thuyết ngưỡng F-measure; F2 thưởng Recall nên ngưỡng rất thấp (~0,06–0,12) | Cần một dev set nhỏ |
| 4 | **Một LLM ≤15B xử lý 1.200 truy vấn một lần**: dịch sang tiếng Trung, thuật ngữ y khoa, câu trả lời giả (HyDE), tách ý cho câu dài | 83% corpus là tiếng Trung, 100% truy vấn tiếng Việt. BM25 không vượt được ranh giới ngôn ngữ | ~1–3 giờ GPU, chạy một lần |
| 5 | **Truy xuất dạng thác tập trung theo truy vấn**: chỉ mục cấp tài liệu cho toàn corpus, chỉ mục cấp đoạn chỉ cho vài trăm nghìn tài liệu ứng viên | 1.200 truy vấn đã biết trước. Encode mọi chunk tốn 30–45 giờ GPU, thác chỉ ~12–18 giờ | Viết thêm một tầng chỉ mục |
| 6 | **Một reranker duy nhất**, chấm cùng ngôn ngữ với tài liệu (truy vấn tiếng Trung cho tài liệu tiếng Trung). Mặc định Qwen3-Reranker-4B, dự phòng bge-reranker-v2-m3, chọn bằng A/B trên dev | Reranker là nơi tăng chất lượng lớn nhất trên mỗi giờ GPU khi tập truy vấn cố định | ~2,5 giờ trên T4×2 cho 1.200 × 80 cặp |
| 7 | **Tạm dừng khối T (teacher→student)** | Không có nhãn gold, còn 3 tuần; rủi ro cao hơn lợi ích chưa đo được | Tiết kiệm nhiều ngày công |

---

## 1. Những sự thật định hình thiết kế

### 1.1 Corpus **[dữ liệu]**

| Chỉ số | Giá trị | Hệ quả |
|---|---|---|
| Số URL trong `links_corpus.parquet` | 4.394.718 (thẻ dataset ghi 4.420.561 ID, tức ~25,8 nghìn ID không có dòng) | Chỉ những ID có dòng mới có thể là nhãn |
| Số hostname | 97 | Giới hạn tốc độ theo domain là nút thắt chính của crawl |
| Tiếng Trung | ~3,65 triệu URL (**~83%**) | Phần lớn tài liệu đúng nhiều khả năng là tiếng Trung **[giả thuyết]** |
| Tiếng Việt | ~0,74 triệu URL (~17%) | |
| Tiếng Anh | gần như 0 (BTC hứa bổ sung PubMed) | Pipeline vẫn phải chịu được tiếng Anh |
| URL tiếng Việt có slug mô tả tiêu đề | **99,3%** (727.685 / 732.785) | Có thể khớp truy vấn với URL **trước khi crawl** |
| `a-hospital.com` | 169.339 URL dạng `/w/<tiêu đề tiếng Trung>` | Cũng khớp được trước khi crawl, sau khi dịch truy vấn |
| `120ask.com`, `ask.39.net`, `cnkang.com`, `zhongyibaodian.net`, `youlai.cn` | URL chỉ có ID số | Phải crawl mới biết nội dung |
| `familydoctor.com.cn`, `wujue.com`, 39.net | Đường dẫn có chuyên mục bằng pinyin hoặc subdomain (`ganbing`, `lady`, `woman.39.net`, `cancer.39.net`) | Ưu tiên theo chuyên mục được |
| Mảng y học cổ truyền Trung Quốc (`zysjonline`, `zhongyibaodian`, `zydcd`, một phần `a-hospital`, `wujue/gjwx`) | Hàng trăm nghìn URL về vị thuốc, sách cổ, món ăn, danh bạ bệnh viện | Khả năng khớp truy vấn y khoa hiện đại thấp **[giả thuyết, cần đo]** |

Hai domain lớn nhất là **trang hỏi–đáp của bệnh nhân** (`120ask.com` 918 nghìn, `ask.39.net` 337 nghìn). Truy vấn của cuộc thi cũng là câu hỏi của bệnh nhân. Đây nhiều khả năng là nguồn đáp án quan trọng nhất **[giả thuyết]**.

### 1.2 Truy vấn **[dữ liệu]** và **[tài liệu]**

- 1.200 câu hỏi tiếng Việt kiểu người bệnh hỏi bác sĩ. Trung vị 18 từ, P95 84 từ, dài nhất 283 từ.
- **Cả 1.200 truy vấn đã được phát hành** cho cả hai giai đoạn. Hệ thống được phép biết trước toàn bộ tập truy vấn, nên có thể tối ưu tập trung vào đúng 1.200 câu thay vì xây chỉ mục tổng quát.
- Kiểm tra bằng tìm kiếm web: truy vấn 490 ("Nổi hạch ở cẳng tay và dưới háng có nguy hiểm không?") trùng **nguyên văn** tiêu đề một bài hỏi–đáp Vinmec. Truy vấn 1086 và 614 cũng khớp câu hỏi trên Vinmec. Nhưng **URL của các bài đó không có trong corpus** (đã tìm theo slug).
- Hệ quả **[suy luận]**: truy vấn được lấy từ câu hỏi thật của người bệnh, còn trang gốc chứa câu hỏi đã bị loại khỏi corpus. Không có đường tắt kiểu "khớp tiêu đề trùng khít". Tài liệu đúng là các trang khác, tiếng Việt hoặc tiếng Trung, trả lời cùng vấn đề. Truy xuất xuyên ngôn ngữ theo ngữ nghĩa là bắt buộc.

### 1.3 Công thức chấm và hệ quả **[tài liệu: RULE.txt, Q&A BTC]**

Với mỗi truy vấn, gọi g là số mục đúng, N là số mục nộp, k là số mục nộp trúng:

```
F2 = 5·P·R / (4·P + R) = 5k / (4g + N)
```

Ở cấp đoạn: `overlap(c, g) = LCS_token(c, g) / |g|`, đúng khi ≥ 0,4 với ít nhất một đoạn tham chiếu **cùng doc_id**. Precision = số chunk nộp được tính đúng / số chunk nộp. Recall = số đoạn tham chiếu được tìm thấy / tổng số đoạn tham chiếu. BTC khuyến nghị mỗi chunk không quá khoảng 1.024 token "để tránh chunk gần như toàn bộ tài liệu".

Ba hệ quả **[suy luận]**:

1. **Mẫu số là độ dài đoạn tham chiếu, không phải đoạn nộp.** Nếu đoạn nộp chứa trọn phần tham chiếu thì overlap = 1, bất kể đoạn nộp dài bao nhiêu. Đoạn nộp dài hơn chỉ có thể giữ nguyên hoặc tăng LCS.
2. **Precision đếm theo số chunk, không theo số token.** Một cửa sổ dài không bị phạt về Precision, trong khi xác suất nó vượt ngưỡng 40% và phủ được nhiều đoạn tham chiếu cùng lúc đều tăng.
3. **F2 đặt trọng số Recall gấp 4 lần Precision.** Bỏ sót một tài liệu đúng tốn hơn nhiều so với thêm một tài liệu sai.

### 1.4 Tài nguyên và thời hạn

| Tài nguyên | Ghi chú |
|---|---|
| 2 laptop RTX 2050 4 GB | Crawl, BM25, dựng bài nộp, model ≤0,6B |
| Kaggle T4×2 (16 GB mỗi card, hai bộ nhớ tách rời) | Hạn mức khoảng 30 giờ GPU/tuần, phiên tối đa khoảng 12 giờ theo nguồn thứ ba; **phải tự kiểm tra trên tài khoản** |
| Hạn | Public: 31/10 23:59. Nộp hệ thống: 04/11. Tối đa 10 lần nộp/ngày; private chỉ 5 lần tổng |
| Luật model | Mở, ≤15B mỗi model, phát hành trước 01/08/2026; không dùng LLM đóng ở bất kỳ khâu nào |

---

## 2. Điểm số bị mất ở đâu: ngân sách lỗi

Một tài liệu đúng không vào bài nộp vì một trong bốn lý do, theo thứ tự trong pipeline:

| Tầng | Lỗi | Trần ảnh hưởng | Đòn bẩy |
|---|---|---|---|
| Crawl | `not_crawled`: chưa crawl, bị robots chặn, trích xuất hỏng | Recall ≤ tỷ lệ tài liệu đúng đã crawl | Mục 3 |
| Truy xuất | `not_retrieved`: có trong chỉ mục nhưng không vào nhóm ứng viên | Recall ≤ Recall@K của tầng đầu | Mục 5, 6 |
| Xếp hạng | `not_selected`: vào ứng viên nhưng bị cắt | Phụ thuộc reranker và ngưỡng | Mục 4, 7 |
| Đóng gói | Chunk nộp không đạt 40% đoạn tham chiếu | Ảnh hưởng riêng cấp chunk | Mục 4 |

**Ví dụ về trần độ phủ [suy luận]:** giả sử mọi tầng sau crawl hoàn hảo (P = 1). Nếu chỉ 40% tài liệu đúng đã được crawl thì R = 0,4 và F2 = 5·0,4/(4 + 0,4) ≈ **0,45**. Nếu độ phủ là 80% thì F2 ≈ **0,83**. Không có reranker nào bù được khoảng cách này. Kết quả EDA ngày 10/10 cho thấy khoảng 7% URL của batch01 bị robots.txt từ chối, nên trần thực tế đã thấp hơn 100%.

---

## 3. Đòn bẩy 1: độ phủ crawl

### 3.1 Nút thắt là tốc độ theo domain, không phải số máy **[dữ liệu]** và **[ước lượng]**

Ở 1 request/giây cho mỗi domain (mức lịch sự đang dùng):

| Domain | Số URL | Số ngày nếu chạy liên tục |
|---|---:|---:|
| cnkang.com | 963.438 | ~11,2 |
| 120ask.com | 918.479 | ~10,6 |
| familydoctor.com.cn | 447.453 | ~5,2 |
| 39.net (tất cả subdomain, tính chung một registered domain) | ~459.000 | ~5,3 |
| zysjonline.com | 243.347 | ~2,8 |
| a-hospital.com | 169.339 | ~2,0 |
| suckhoecongdongonline.vn | 154.503 | ~1,8 |
| zhongyibaodian.net | 146.700 | ~1,7 |

Cộng dồn tuần tự là khoảng 51 ngày. **Chạy song song theo domain** thì thời gian bằng domain dài nhất, khoảng 11 ngày. Còn 21 ngày đến hạn public, nhưng cần xong crawl trước khoảng 24/10 để còn thời gian lập chỉ mục. Vì vậy:

- **Tổ chức lại crawl theo làn domain** thay vì theo khoảng ID. Chia theo ID không làm nhanh một domain, vì tốc độ mỗi domain bị giới hạn, và còn khiến hai người cùng gửi request vào một site.
- **Khởi động ngay làn `cnkang.com` và `120ask.com`**, mỗi làn chạy liên tục trên một máy có IP ổn định. Kaggle dễ bị chặn IP hơn IP nhà.
- Một tiến trình crawler duy nhất đã quản lý nhiều domain song song (giới hạn theo từng domain). Không cần mở nhiều cửa sổ cho cùng một domain.
- Giữ `RESPECT_ROBOTS = True` và không giảm dưới 1 request/giây. Những tài liệu bị chặn là phần trần không thể vượt hợp lệ, nên ghi vào working notes.

### 3.2 Ưu tiên theo truy vấn: quyết định **thứ tự**, không quyết định **phạm vi**

Mục tiêu vẫn là crawl toàn bộ corpus. Ưu tiên chỉ quyết định cái gì xong trước, để nếu hết giờ thì phần đã có là phần đáng giá nhất. Cách đặt vấn đề này giữ cho cơ sở tri thức cuối cùng không phụ thuộc vào truy vấn, nên minh bạch khi viết working notes.

| Loại domain | Tín hiệu ưu tiên có sẵn trước khi crawl | Cách làm |
|---|---|---|
| Việt (99,3% có slug) | Tiêu đề bỏ dấu trong slug | BM25 giữa truy vấn đã bỏ dấu và token slug; crawl URL có điểm cao nhất với bất kỳ truy vấn nào trước |
| `a-hospital.com` | Tiêu đề tiếng Trung trong URL | BM25 bigram giữa truy vấn đã dịch sang tiếng Trung (mục 5) và tiêu đề trong URL |
| `familydoctor`, `wujue`, 39.net | Chuyên mục pinyin, subdomain | Ưu tiên chuyên mục theo phân bố chủ đề của 1.200 truy vấn |
| `120ask`, `ask.39.net`, `cnkang`, ... (ID số) | Không có | Dùng **ước lượng năng suất theo mẫu** (mục 3.3) |

### 3.3 Ước lượng năng suất theo mẫu (sample-then-prioritize) **[suy luận]**

Với domain có URL không mang thông tin:

1. Crawl một mẫu ngẫu nhiên đều nhỏ, ví dụ 1–2% mỗi domain hoặc mỗi chuyên mục.
2. Chạy truy xuất 1.200 truy vấn trên mẫu đó.
3. Đo **năng suất** của từng domain hoặc chuyên mục: tỷ lệ tài liệu lọt top-K của ít nhất một truy vấn với điểm reranker cao.
4. Phân bổ thời gian crawl còn lại theo năng suất. Domain năng suất gần 0 (nhiều khả năng là danh bạ bệnh viện, công thức món ăn, vị thuốc cổ) xuống cuối hàng đợi.

Đây là kỹ thuật lấy mẫu thích nghi kinh điển trong focused crawling, phù hợp khi ngân sách thời gian không đủ chắc chắn. Rủi ro: nếu nhãn của BTC ưu tiên domain mà hệ thống của ta đánh giá thấp, ta sẽ đẩy nhầm domain đó xuống. Vì vậy chỉ hạ thứ tự, không loại bỏ.

### 3.4 Chất lượng trích xuất là một phần của độ phủ **[dữ liệu: EDA 10/10]**

- `domain_parser_fallback` xuất hiện ở gần như mọi bản ghi `cnkang.com` trong mẫu. Văn bản tiếng Trung trung vị ~700 ký tự so với ~3.165 ở trang Việt. Cần đọc mẫu để xem do bài ngắn hay do parser cắt mất nội dung. Nếu do parser, viết quy tắc riêng và chạy trích xuất lại từ HTML đã lưu, **không cần crawl lại**.
- Với trang hỏi–đáp tiếng Trung, phải giữ **cả câu hỏi lẫn mọi câu trả lời của bác sĩ**. Câu hỏi giúp khớp truy vấn, câu trả lời là nơi chứa đoạn tham chiếu.
- ~1,4% bản ghi trùng văn bản y hệt trong mẫu. Gom nhóm trước khi lập chỉ mục (mục 7.3).

---

## 4. Đòn bẩy 2: đóng gói bài nộp theo đúng công thức chấm

Đây là đòn bẩy rẻ nhất, vì chỉ đổi khâu D và không phải chạy lại GPU.

### 4.1 Tách đơn vị truy xuất và đơn vị nộp ("small-to-big") **[suy luận]**

- **Truy xuất và rerank trên đoạn nhỏ** (~200–320 token). Đoạn nhỏ cho điểm liên quan chính xác hơn và rẻ hơn khi rerank.
- **Nộp một cửa sổ mở rộng** quanh đoạn nhỏ được chọn: mở rộng sang hai bên theo ranh giới đoạn văn đến khi chạm ngân sách token B, rồi cắt lại nguyên văn từ corpus bằng `char_start`/`char_end`. Ràng buộc "chunk_text là văn bản trích xuất" vẫn được giữ.
- Hai đoạn nhỏ được chọn trong cùng tài liệu mà nằm chung một cửa sổ thì **gộp thành một**, tránh nộp hai chunk cùng khớp một đoạn tham chiếu (tốn Precision mà không tăng Recall).
- Tài liệu ngắn hơn B (đa số trang tiếng Trung, trung vị ~700 ký tự) sẽ nộp nguyên văn cả tài liệu như một chunk. Điều này nằm trong trần BTC nêu, nhưng nên ghi rõ trong working notes.

### 4.2 Chọn ngân sách B

BTC nói "khoảng 1.024 token" nhưng không nói theo bộ tách token nào. Bộ đếm nội bộ coi một âm tiết Việt hoặc một chữ Hán là một token. Bộ tách subword của model thường cho **nhiều token hơn** với tiếng Việt.

Đề xuất **[giả thuyết, cần A/B]**:
- Đặt B theo **giá trị lớn nhất** giữa ba cách đếm: bộ đếm nội bộ, tokenizer XLM-R (bge-m3) và tokenizer Qwen. Giữ biên an toàn: B ≈ 900 token theo cách đếm lớn nhất.
- Là một tham số duy nhất trong D2. Thử trên leaderboard: cùng bài nộp với B = 320 và B ≈ 900, chỉ đo thay đổi ở F2 cấp chunk.
- Nếu BTC làm rõ hoặc siết quy tắc, hạ B mà không đổi gì khác.

### 4.3 Ngưỡng cắt tối ưu F2 **[tài liệu + suy luận]**

Từ `F2 = 5k/(4g + N)`, thêm một mục có xác suất đúng p làm F2 tăng khi và chỉ khi:

```
p > k / (4g + N) = F2_hiện_tại / 5
```

Đây là bản tổng quát cho F-beta của kết quả Lipton và cộng sự (2014): với xác suất đã hiệu chỉnh, ngưỡng tối ưu cho F1 là F1*/2, và cho F-beta là F*/(1+β²). Với β = 2 thì ngưỡng là **F2*/5**. Nếu F2 đạt được cỡ 0,3–0,6, ngưỡng chỉ khoảng **0,06–0,12**: gần như mọi mục có hơn 10% khả năng đúng đều nên được nộp.

Áp dụng:
1. Hiệu chỉnh điểm reranker thành xác suất bằng hồi quy logistic một biến (Platt scaling) trên dev, **tách riêng** cho tài liệu tiếng Việt và tiếng Trung vì điểm xuyên ngôn ngữ thường lệch thang.
2. Với mỗi truy vấn, duyệt theo xác suất giảm dần và dừng khi p ≤ F2 ước lượng/5. Ước lượng g bằng tổng xác suất cộng một phần bù cho tài liệu đúng chưa crawl.
3. Làm riêng cho cấp tài liệu và cấp chunk, vì hai cấp được chấm độc lập.

Cách này thay thế các profile `recall`/`balanced`/`precision` và `adaptive_cutoff` hiện tại bằng một quy tắc có cơ sở. Cảnh báo **[tài liệu]**: lý thuyết giả định xác suất đã hiệu chỉnh tốt và dùng xấp xỉ kỳ vọng; với dev nhỏ, hiệu chỉnh có sai số. Nên làm tròn ngưỡng về một giá trị chung rồi kiểm tra trên leaderboard.

---

## 5. Đòn bẩy 3: xử lý truy vấn bằng một LLM, chạy một lần

### 5.1 Vì sao cần

- 83% corpus là tiếng Trung, truy vấn 100% tiếng Việt. BM25 không bắc cầu được hai ngôn ngữ. Kênh dense xuyên ngôn ngữ tốt, nhưng thường kém truy xuất cùng ngôn ngữ.
- Chỉ có 1.200 truy vấn, nên dùng LLM cho phía truy vấn rất rẻ. Dịch toàn bộ 3,65 triệu tài liệu tiếng Trung thì không khả thi.
- Tài liệu **[tài liệu]**: một nghiên cứu năm 2025 về mở rộng truy vấn bằng LLM đa ngôn ngữ cho truy xuất xuyên ngôn ngữ ghi nhận Hit@10 tăng từ 69,35 lên ~85 trên CLIRMatrix và MRR tăng từ 15,39 lên 20,38 trên mMARCO, chỉ với BM25 và model 4–12B. Nghiên cứu khác lưu ý dịch truy vấn đơn thuần có thể kém vì truy vấn thiếu ngữ cảnh. Vì thế nên sinh **nhiều dạng** chứ không chỉ một bản dịch.

### 5.2 Các đầu ra cần sinh cho mỗi truy vấn

| Đầu ra | Dùng cho | Ghi chú |
|---|---|---|
| Bản dịch tiếng Trung | BM25 tiếng Trung, dense, rerank cùng ngôn ngữ (mục 6) | Văn phong câu hỏi bệnh nhân, giống 120ask |
| Danh sách thuật ngữ y khoa: tiếng Việt chuẩn, tiếng Trung, tiếng Anh | BM25 mở rộng, khớp URL `a-hospital` | Thay vai trò "đồ thị tri thức" của GraphRAG (mục 8) |
| Câu trả lời giả ngắn bằng tiếng Trung và tiếng Việt (HyDE) | Kênh dense | Đưa truy vấn về gần dạng tài liệu; chỉ dùng để tìm, không bao giờ nộp |
| Tách ý (chỉ cho truy vấn dài, nhiều câu hỏi) | Truy xuất theo từng ý rồi gộp RRF | Ví dụ truy vấn 1149 hỏi đồng thời lạc nội mạc tử cung, nang buồng trứng, IUI hay IVF |

### 5.3 Chọn model **[tài liệu]**

| Lựa chọn | Phát hành | Ghi chú |
|---|---|---|
| **Qwen3-14B** (mặc định đề xuất) | 04/2025, Apache 2.0 | Mạnh tiếng Trung, khá tiếng Việt; 4-bit vừa một T4; tắt chế độ thinking để nhanh |
| Qwen3-8B | 04/2025 | Nhanh hơn; 8B fp16 (~16 GB) không vừa một T4, cần 4-bit/8-bit |
| Hunyuan-MT-7B | 09/2025 | Chuyên dịch, hỗ trợ cả tiếng Việt và tiếng Trung, đứng đầu 30/31 cặp ngôn ngữ WMT25 theo Tencent tự báo cáo. Chỉ dùng nếu bản dịch của Qwen3 kém. **Kiểm tra giấy phép** trước khi dùng |

Một model cho mọi tác vụ là đủ. Ước lượng **[ước lượng]**: khoảng 1,5 triệu token sinh ra cho 1.200 truy vấn × 3–4 đầu ra. Với batching trên T4, khoảng 1–3 giờ. Chạy không batch có thể lâu gấp nhiều lần. Kết quả lưu thành file, dùng lại mãi.

---

## 6. Đòn bẩy 4: truy xuất dạng thác, tập trung theo truy vấn

### 6.1 Vấn đề quy mô **[ước lượng]**

Nếu crawl đủ, corpus có khoảng 6–9 triệu chunk ở cỡ 320 token (tài liệu Việt ~2–3 chunk, tài liệu Trung ~1–1,5 chunk).

| Cách lập chỉ mục | Khối lượng | Ước lượng |
|---|---|---|
| Dense mọi chunk, model 0,6B | 6–9 triệu × ~300 token | ~30–45 card-giờ T4, tức 15–22 giờ trên T4×2. Vượt phần lớn hạn mức tuần, và phải làm lại nếu đổi cách chunk |
| BM25 mọi chunk | ~1–1,4 tỷ posting | ~8–11 GB RAM, sát hoặc vượt RAM laptop |
| **Thác (đề xuất)** | Xem dưới | ~12–18 card-giờ tổng, phần lớn chạy một lần |

### 6.2 Thiết kế thác

```text
Tầng 1  — cấp TÀI LIỆU, toàn corpus (chạy một lần, cập nhật khi crawl thêm)
          "Thẻ tài liệu" = tiêu đề + câu hỏi (trang hỏi–đáp) + ~150 token đầu
          BM25 thẻ (tách theo ngôn ngữ) + dense thẻ (model 0,6B)
          Truy vấn: bản gốc Việt, bản dịch Trung, thuật ngữ, HyDE, các ý đã tách
          Hợp nhất RRF → top 200–300 tài liệu mỗi truy vấn
Tầng 2  — cấp ĐOẠN, chỉ trong tài liệu ứng viên (~200–300 nghìn tài liệu duy nhất)
          Chia đoạn ~200–320 token, BM25 + dense trong tập nhỏ này
          → top 60–100 đoạn mỗi truy vấn
Tầng 3  — MỘT reranker, chấm cùng ngôn ngữ với tài liệu
          → xác suất đã hiệu chỉnh cho từng đoạn
Tầng 4  — Điểm tài liệu từ điểm đoạn; cắt theo ngưỡng F2 (mục 4.3)
Tầng 5  — Mở rộng cửa sổ nộp (mục 4.1), cắt lại nguyên văn, kiểm tra, ghi ZIP
```

Vì sao hợp lý **[suy luận]**:
- Với trang hỏi–đáp, khớp **câu hỏi với câu hỏi** (truy vấn với tiêu đề hoặc câu hỏi của trang) là bài toán diễn đạt lại, dễ hơn nhiều so với khớp câu hỏi với câu trả lời. Thẻ tài liệu đặt câu hỏi lên đầu là đúng chỗ.
- Tầng 1 tốn ~9–14 card-giờ cho 4,4 triệu thẻ, chạy một lần. Tầng 2 chỉ tốn ~3–4,5 card-giờ. Tổng nhẹ hơn khoảng 2,5 lần so với encode mọi chunk, và đổi cách chunk chỉ phải làm lại tầng 2.
- Thứ cần đo ngay là **Recall@K cấp tài liệu của tầng 1** trên dev. Tầng 1 bỏ sót thì không tầng nào cứu được. Nếu Recall@300 thấp, tăng K hoặc thêm kênh trước khi tối ưu phần khác.

### 6.3 Chọn model embedding **[tài liệu]**

Với ngân sách trên, chỉ model cỡ ~0,6B là khả thi cho toàn corpus.

| Model | Phát hành | Ghi chú |
|---|---|---|
| bge-m3 (568M) | 2024 | Đã có trong code; mạnh đa ngôn ngữ; một biến thể tinh chỉnh tiếng Việt (AITeamVN) tự báo cáo tốt hơn rõ trên dữ liệu pháp lý Việt, nhưng có thể yếu đi với tiếng Trung |
| **Qwen3-Embedding-0.6B** | 06/2025, Apache 2.0 | Có chỉ dẫn theo tác vụ, hỗ trợ cắt chiều (MRL) để giảm dung lượng; mạnh tiếng Trung. Đã đăng ký trong code |
| harrier-oss-v1-0.6b (Microsoft) | Khoảng đầu 2026, MIT | Xếp hạng cao trên MTEB Multilingual v2 theo nguồn thứ ba. **Cần xác minh ngày phát hành và giấy phép** trước khi dùng |

Đề xuất: A/B giữa bge-m3 và Qwen3-Embedding-0.6B trên Recall@K của dev, rồi chốt một model. Model 4B–8B chỉ dùng ở tầng 2 nếu thừa giờ GPU.

Giảm dung lượng **[tài liệu]**: lượng tử hóa nhị phân kèm chấm lại bằng vector đầy đủ giữ được tới ~96% chất lượng truy xuất theo blog Hugging Face, giảm bộ nhớ 32 lần. Với 4,4 triệu thẻ × 1.024 chiều fp16 (~9 GB), có thể giữ bản int8 trên đĩa và chỉ nạp ứng viên.

---

## 7. Đòn bẩy 5: một reranker duy nhất

### 7.1 Số liệu ứng viên **[tài liệu]**

Theo bảng của báo cáo Qwen3 Embedding (tác giả tự chạy, rerank top-100 của Qwen3-Embedding-0.6B):

| Model | Tham số | MMTEB-R (đa ngữ) | CMTEB-R (Trung) | MLDR |
|---|---|---:|---:|---:|
| bge-reranker-v2-m3 | 0,6B | 58,36 | 72,16 | 59,51 |
| gte-multilingual-reranker-base | 0,3B | 59,44 | 74,08 | 66,33 |
| Qwen3-Reranker-0.6B | 0,6B | 66,36 | 71,31 | 67,28 |
| **Qwen3-Reranker-4B** | 4B | **72,74** | 75,94 | 69,97 |
| Qwen3-Reranker-8B | 8B | 72,94 | 77,45 | 70,19 |

Bằng chứng ngược chiều cần biết:
- Một bảng BEIR độc lập (bài Querit-Reranker, 2026) cho Qwen3-Reranker-0.6B chỉ 48,09 so với 56,42 của bge-reranker-v2-m3, trong khi Qwen3-Reranker-8B đạt 61,81. Model Qwen3-Reranker rất nhạy với mẫu prompt; dùng sai mẫu sẽ cho điểm thấp.
- Trên một phép thử xuyên ngôn ngữ (XQuAD, trong bài LAMAR 2026), bge-reranker-v2-m3 đạt 90,20 trên ứng viên của bge-m3, cao hơn jina-reranker-v3 (82,04). Truy vấn Việt với tài liệu Trung chính là xuyên ngôn ngữ.
- jina-reranker-v3 (0,6B, chấm theo danh sách) có BEIR cao nhưng giấy phép CC BY-NC 4.0. Phù hợp mục đích phi thương mại, nhưng không vượt trội ở phép thử xuyên ngôn ngữ trên.

### 7.2 Khuyến nghị

- **Mặc định: Qwen3-Reranker-4B**, fp16, vừa một T4 (~8 GB trọng số), mỗi card một bản. Dùng **đúng mẫu prompt chính thức**.
- **Dự phòng rẻ: bge-reranker-v2-m3**, đã có trong code, mạnh ở xuyên ngôn ngữ.
- **Chọn một bằng A/B trên dev** trong tuần đầu, rồi bỏ model còn lại. Không giữ hai reranker.
- Model 8B không vừa một T4 ở fp16 và chỉ hơn 4B rất ít trên bảng trên, nên không đáng.

### 7.3 Cách dùng thông minh với một reranker

1. **Chấm cùng ngôn ngữ [giả thuyết, cần A/B]:** tài liệu tiếng Trung chấm với bản dịch tiếng Trung của truy vấn, tài liệu tiếng Việt chấm với truy vấn gốc. Biến bài toán xuyên ngôn ngữ ở bước tốn nhất thành bài toán cùng ngôn ngữ, không tốn thêm cặp nào. Nếu thừa ngân sách, chấm cả hai và lấy giá trị lớn hơn.
2. **Hiệu chỉnh tách theo ngôn ngữ tài liệu** (mục 4.3).
3. **Điểm tài liệu** = xác suất lớn nhất của các đoạn, cộng một phần nhỏ cho đoạn thứ hai, hiệu chỉnh riêng ở cấp tài liệu.
4. **Nhóm trùng lặp:** gom tài liệu trùng (y hệt hoặc gần trùng bằng MinHash) thành một khi truy xuất và rerank để không tốn cặp. Khi nộp, việc có thêm các bản trùng vào `relevant_docs` hay không phụ thuộc BTC gán nhãn cả nhóm hay một bản. Đây là câu hỏi nên gửi BTC, hoặc quyết định bằng một lần A/B trên leaderboard.
5. **Lưu đệm điểm** theo (model, truy vấn, đoạn) để đổi ngưỡng ở khâu D không phải chấm lại.

Ước lượng **[ước lượng]**: 1.200 truy vấn × 80 cặp × ~450 token với model 4B ≈ 4,8 card-giờ, tức ~2,5 giờ trên T4×2. Model 0,6B khoảng 0,7 card-giờ.

---

## 8. GraphRAG và các kỹ thuật khác: giữ gì, bỏ gì

### 8.1 Vì sao không dùng GraphRAG đầy đủ

**Chi phí [ước lượng]:** GraphRAG kiểu Microsoft, LightRAG và HippoRAG 2 đều cần LLM đọc **từng đoạn** để trích thực thể và quan hệ. HippoRAG 2 báo khoảng 1,1 giây mỗi đoạn với model 70B trên phần cứng mạnh hơn nhiều. Với 6–9 triệu đoạn và model 7–8B trên T4, ngay cả ở mức lạc quan 0,5 giây mỗi đoạn có batching, cũng mất khoảng **2–3 tuần trên T4×2**, vượt toàn bộ thời gian còn lại. Chỉ làm trên tài liệu ứng viên (~750 nghìn đoạn) vẫn tốn khoảng **2 ngày** GPU.

**Không khớp bài toán [tài liệu + suy luận]:**
- Đánh giá có hệ thống "RAG vs. GraphRAG" (2025) cho thấy RAG theo đoạn thắng hoặc ngang ở câu hỏi một bước và câu hỏi chi tiết (NQ: 64,78 so với 63,01). GraphRAG chỉ thắng ở câu hỏi nhiều bước, so sánh và thời gian. Biến thể chỉ dùng bộ ba của đồ thị tri thức đạt 41,24, thấp hơn rõ so với RAG thường.
- Truy vấn ViBioMIR là câu hỏi của người bệnh, đáp án thường nằm gọn trong một trang. Đây là dạng một bước.
- Tóm tắt cộng đồng của GraphRAG không phải đoạn nguồn, nên không nộp được. Bài nộp bắt buộc là đoạn trích nguyên văn.
- LazyGraphRAG giảm chi phí lập chỉ mục bằng cách trích cụm danh từ bằng NLP truyền thống thay cho LLM, nhưng dồn LLM sang lúc truy vấn và nhắm vào câu hỏi tổng hợp toàn corpus, không phải định vị đoạn bằng chứng.

### 8.2 Phần "đồ thị" đáng giữ, với chi phí gần 0

| Ý tưởng | Thay cho | Cách làm |
|---|---|---|
| **LLM như đồ thị thuật ngữ theo yêu cầu** | Liên kết thực thể xuyên ngôn ngữ của GraphRAG | Sinh thuật ngữ Việt–Trung–Anh cho 1.200 truy vấn (mục 5.2). Chỉ 1.200 lần gọi thay vì hàng triệu |
| **Nhóm trùng lặp như đồ thị tài liệu** | Lan truyền điểm trên đồ thị | Gom trùng y hệt và gần trùng; tính điểm một lần cho cả nhóm |
| **Tách ý truy vấn** | Truy xuất nhiều bước | Chỉ cho truy vấn dài, nhiều câu hỏi |
| PPR trên đồ thị cụm danh từ–đoạn (kiểu HippoRAG, nhưng trích bằng NLP thường) | — | **Không làm trong 3 tuần này.** Chỉ cân nhắc nếu dev cho thấy lỗi tập trung ở truy vấn nhiều ý mà tách ý không giải quyết được |

### 8.3 Bảng quyết định các kỹ thuật đã xem xét

| Kỹ thuật | Quyết định | Lý do |
|---|---|---|
| BM25 + dense + RRF | **Giữ** | Nền tảng; đã có trong code |
| Truy xuất phân cấp tài liệu → đoạn | **Giữ, làm trục chính** | Mục 6; khớp với [data_research.md](../../data/research/data_research.md) |
| Mở rộng truy vấn bằng LLM (dịch, thuật ngữ, HyDE) | **Giữ** | Mục 5; rẻ vì chỉ 1.200 truy vấn |
| Tách ý có điều kiện | **Giữ** | Truy vấn dài nhiều ý; chỉ áp dụng cho nhóm đó |
| Một reranker, chấm cùng ngôn ngữ | **Giữ** | Mục 7 |
| Ngưỡng tối ưu F2 trên xác suất hiệu chỉnh | **Giữ**, thay `adaptive_cutoff` và profile | Mục 4.3 |
| Nộp cửa sổ mở rộng | **Giữ** | Mục 4.1 |
| Tiêu đề làm ngữ cảnh khi encode đoạn (không ghép vào chunk nộp) | **Giữ** | Miễn phí; code đã tách tiêu đề khỏi `text` |
| Gom trùng MinHash | **Giữ** | Tiết kiệm cặp rerank; giữ Precision |
| GraphRAG / LightRAG / HippoRAG 2 đầy đủ | **Bỏ** | Mục 8.1 |
| RAPTOR (cây tóm tắt) | **Bỏ** | Tốn LLM trên mọi đoạn; tóm tắt không nộp được |
| Contextual retrieval bằng LLM cho từng đoạn | **Bỏ** | Một lần gọi LLM mỗi đoạn, chi phí như GraphRAG |
| Dịch toàn bộ tài liệu tiếng Trung | **Bỏ** | 3,65 triệu tài liệu; đắt hơn mọi thứ khác cộng lại |
| ColBERT / multi-vector | **Bỏ** | Dung lượng nhân hàng trăm lần với hàng triệu đoạn |
| Late chunking | **Bỏ** | Cần encoder ngữ cảnh dài trên toàn tài liệu; lợi ích nhỏ so với chi phí |
| Sparse học được (SPLADE, sparse của bge-m3) | **Tùy chọn** | Có miễn phí nếu dùng bge-m3, nhưng không giúp xuyên ngôn ngữ |
| Rerank danh sách bằng LLM 14B | **Bỏ** | Chậm, và trái mục tiêu một reranker |
| Khối T: teacher → student | **Tạm dừng** | Không có nhãn gold; chỉ quay lại nếu dev chỉ ra reranker yếu rõ rệt ở cặp Việt–Trung và còn thời gian |
| Tách từ tiếng Việt chuyên dụng cho BM25 | **Thay bằng bigram âm tiết** | Bigram âm tiết xấp xỉ từ ghép, không cần công cụ ngoài, rẻ |

---

## 9. Ngân sách tính toán

Giả định **[ước lượng]**: chi phí suy luận ≈ 2 × số tham số × số token phép tính; T4 fp16 đạt hiệu dụng ~20 TFLOPS (đỉnh lý thuyết ~65). Con số thật phải đo ở bước B0, thường chậm hơn ước lượng.

| Việc | Khối lượng | Card-giờ T4 | Ghi chú |
|---|---|---:|---|
| LLM xử lý truy vấn (14B, 4-bit) | 1.200 truy vấn × 3–4 đầu ra | 1–3 | Chạy một lần |
| Dense thẻ tài liệu (0,6B) | ≤4,4 triệu × 128–192 token | 9–14 | Chạy một lần; cập nhật phần crawl thêm |
| Dense đoạn trong tài liệu ứng viên (0,6B) | ~0,6–0,9 triệu đoạn × 300 token | 3–4,5 | Làm lại khi đổi cách chunk |
| Rerank (4B) | 1.200 × 80 cặp × 450 token | ~5 | ~2,5 giờ thực trên T4×2 |
| **Tổng** | | **~18–27** | Vừa hạn mức khoảng 30 giờ/tuần, dư cho chạy lại |
| *So sánh: dense mọi đoạn* | 6–9 triệu đoạn | *30–45* | *Vượt hạn mức tuần* |
| *So sánh: GraphRAG trên ứng viên* | ~750 nghìn đoạn | *~50+* | *Không khả thi* |

Laptop đảm nhận BM25 cấp thẻ (~0,4–0,6 tỷ posting, ~3–5 GB RAM), BM25 cấp đoạn trong tập ứng viên, và toàn bộ khâu D. Lưu ý dung lượng đĩa: văn bản trích xuất khoảng 10–15 GB cho toàn corpus, HTML gốc lớn hơn nhiều.

Lưu ý kỹ thuật: T4 không hỗ trợ bf16 tốt, nên luôn dùng fp16. Chưa xác nhận được tình trạng hỗ trợ T4 của vLLM bản mới; nếu không chạy được, dùng `transformers` với batching.

---

## 10. Đánh giá khi không có nhãn gold

### 10.1 Dev set do người gán nhãn

- **Quy mô tối thiểu:** 60 truy vấn, phân tầng theo ngắn/dài và theo khả năng đáp án tiếng Việt/tiếng Trung.
- **Gộp ứng viên** từ nhiều cấu hình (BM25, dense, bản dịch) để giảm thiên lệch về một hệ thống. Mỗi truy vấn ~20 ứng viên, khoảng 1.200 phán xét, ước lượng 10–15 giờ công.
- Nhãn: tài liệu đúng và đoạn bằng chứng. Người gán cần đọc được tiếng Trung, hoặc dùng bản dịch máy **chỉ để hỗ trợ đọc**.
- Dùng cho ba việc: (1) A/B reranker và embedding, (2) Recall@K của tầng 1, (3) hiệu chỉnh xác suất cho ngưỡng F2.
- Giới hạn: dev gộp từ chính hệ thống của mình sẽ đánh giá thấp lỗi `not_retrieved`.

### 10.2 Dùng leaderboard có kỷ luật

10 lần nộp mỗi ngày là tín hiệu thật duy nhất về nhãn của BTC. Chỉ dùng cho **so sánh cấu hình**, mỗi lần đổi đúng một yếu tố:

| Thử | So sánh | Trả lời câu hỏi |
|---|---|---|
| 1 | Baseline thác + reranker mặc định | Mốc |
| 2 | Cùng bài nộp, cửa sổ B = 320 so với B ≈ 900 | Đòn bẩy 2 thật sự lớn đến đâu |
| 3 | Ngưỡng F2 thấp so với cao | Hiệu chỉnh có lệch không |
| 4 | Có hoặc không thêm bản trùng vào `relevant_docs` | BTC gán nhãn cả nhóm trùng hay không |
| 5 | Có hoặc không có bản dịch tiếng Trung | Đòn bẩy 3 |

Cảnh báo: BTC giới hạn số lần nộp để tránh dò đáp án. Không dùng leaderboard để suy ra nhãn của từng truy vấn hay từng tài liệu. Chỉ so cấu hình ở mức toàn hệ thống, và không tinh chỉnh quá kỹ theo điểm public vì private dùng truy vấn khác.

---

## 11. Kế hoạch theo ngày

| Thời gian | Laptop | Kaggle T4×2 | Mốc |
|---|---|---|---|
| 10–12/10 | Chuyển crawl sang làn domain; chạy ngay làn `cnkang`, `120ask`; xếp thứ tự URL Việt theo slug | LLM xử lý 1.200 truy vấn (dịch, thuật ngữ, HyDE, tách ý) | Có file truy vấn mở rộng; crawl các domain dài đang chạy |
| 12–16/10 | Lấy mẫu 1–2% mỗi domain số; thẻ tài liệu + BM25 cấp thẻ; bắt đầu gán nhãn dev | Dense thẻ trên phần đã crawl; ước lượng năng suất theo domain | **Nộp lần đầu** để có mốc |
| 16–22/10 | Đóng gói cửa sổ rộng + ngưỡng F2; hoàn tất dev 60 truy vấn | A/B reranker (Qwen3-4B và bge-v2-m3), A/B embedding; chốt mỗi loại một model | Các lần nộp 2–5 ở mục 10.2 |
| 22–29/10 | Cập nhật chỉ mục khi crawl xong; sửa parser từ HTML đã lưu nếu cần | Dense phần crawl thêm; chạy lại tầng 2–3 | **Đóng băng cấu hình 29/10** |
| 29–31/10 | Dựng bài nộp cuối, kiểm tra | — | Nộp public |
| 01–04/11 | Chọn cẩn thận 5 lần nộp private; working notes | Chạy lại nếu truy vấn private đổi | Nộp hệ thống |

---

## 12. Đối chiếu với code hiện tại

| Khối | Hiện tại | Đổi |
|---|---|---|
| A1 crawl | Chia theo khoảng ID cho từng người | Chia theo làn domain; thêm thứ tự ưu tiên theo slug/tiêu đề URL/năng suất |
| A3 | Gom trùng y hệt (`merge.py`) | Thêm gần trùng (MinHash) |
| A4 chunk | 320/64, một mức | Mức đoạn ~200–320 cho truy xuất, chỉ làm cho tài liệu ứng viên |
| B | BM25 + dense mọi chunk | Thêm chỉ mục **thẻ tài liệu** cho toàn corpus; chỉ mục đoạn trong tập ứng viên |
| C1 | Hook `--translations` chưa có dữ liệu | Thêm file sinh bởi LLM: dịch, thuật ngữ, HyDE, tách ý |
| C3 | Nhiều reranker đăng ký | Giữ đúng một model sau A/B; chấm cùng ngôn ngữ; lưu đệm điểm |
| D1 | Profile + `adaptive_cutoff` | Ngưỡng F2/5 trên xác suất hiệu chỉnh, tách cấp tài liệu và cấp chunk |
| D2 | Cắt lại đúng span của chunk | Mở rộng thành cửa sổ ≤ B, gộp cửa sổ chồng nhau, vẫn cắt lại nguyên văn |
| T | Teacher → student | Tạm dừng |

---

## 13. Rủi ro và câu hỏi nên gửi BTC

**Câu hỏi:**
1. Giới hạn "khoảng 1.024 token" tính theo bộ tách token nào, và có phải giới hạn cứng không?
2. Khi nhiều ID trong `links_corpus` có nội dung giống hệt nhau, nhãn có bao gồm tất cả các ID đó không?
3. Có chấp nhận việc dùng 1.200 truy vấn đã phát hành để xếp **thứ tự** crawl (vẫn crawl toàn bộ corpus) không?
4. Nguồn PubMed bổ sung sẽ có khi nào, ID có nằm trong `links_corpus.parquet` không?

**Rủi ro:**
- **Crawl bị chặn** ở domain dài nhất (cnkang, 120ask). Giảm thiểu: chạy từ IP nhà, giữ tốc độ lịch sự, ghi nhận phần bị chặn.
- **Cửa sổ rộng bị BTC siết** về sau. Giảm thiểu: B là một tham số, hạ được ngay.
- **Hiệu chỉnh sai trên dev nhỏ.** Giảm thiểu: dùng ngưỡng chung làm tròn, kiểm tra trên leaderboard.
- **Ưu tiên theo năng suất đẩy nhầm domain quan trọng xuống.** Giảm thiểu: chỉ đổi thứ tự, không loại bỏ.
- **Số liệu benchmark của model là tự báo cáo**, chưa có số đo trên cặp Việt–Trung y khoa. Giảm thiểu: A/B trên dev trước khi chốt.

---

## Nguồn

**Dữ liệu và luật của cuộc thi**
- [docs/note/RULE.txt](../note/RULE.txt), [docs/note/Q&A, tools.txt](../note/Q&A,%20tools.txt), [data/source/HF_DATASET_CARD.md](../../data/source/HF_DATASET_CARD.md)
- Kết quả EDA: `data/research/eda/results/20261010_020659/REPORT.md`
- Kiểm tra nguồn gốc truy vấn: [Vinmec — Nổi hạch ở cẳng tay và dưới háng có nguy hiểm không?](https://www.vinmec.com/vie/bai-viet/noi-hach-o-cang-tay-va-duoi-hang-co-nguy-hiem-khong-vi), [Vinmec — Chủ đề X quang phổi](https://www.vinmec.com/vie/chu-de/x-quang-phoi), [Vinmec — Chủ đề Chỉ số ALT](https://www.vinmec.com/vie/chu-de/chi-so-alt)

**Reranker và embedding**
- [Qwen3 Embedding: Advancing Text Embedding and Reranking Through Foundation Models (arXiv 2506.05176)](https://arxiv.org/pdf/2506.05176)
- [Querit-Reranker (arXiv 2606.19037)](https://arxiv.org/pdf/2606.19037)
- [LAMAR: An Open Language-Aware Multilingual Alignment Reranker (arXiv 2607.22042)](https://arxiv.org/pdf/2607.22042)
- [jina-reranker-v3 (arXiv 2509.25085)](https://arxiv.org/abs/2509.25085v4), [model card](https://huggingface.co/collections/jinaai/jina-reranker-v3)
- [VN-MTEB (arXiv 2507.21500)](https://arxiv.org/pdf/2507.21500), [SEA-BED (arXiv 2508.12243)](https://arxiv.org/pdf/2508.12243)
- [Best Embedding Models for RAG 2026 (bài tổng hợp thứ ba)](https://www.premai.io/blog/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting/), [MTEB Leaderboard 2026 (bài tổng hợp thứ ba)](https://www.codesota.com/benchmarks/mteb)
- [Binary and Scalar Embedding Quantization (Hugging Face)](https://huggingface.co/blog/embedding-quantization)

**Truy xuất xuyên ngôn ngữ và mở rộng truy vấn**
- [Generative Query Expansion with Multilingual LLMs for CLIR (arXiv 2511.19325)](https://arxiv.org/html/2511.19325v1)
- [What Drives Cross-lingual Ranking? (arXiv 2511.19324)](https://arxiv.org/html/2511.19324v1)
- [CLIRudit (arXiv 2504.16264)](https://arxiv.org/pdf/2504.16264)
- [Hunyuan-MT Technical Report (arXiv 2509.05209)](https://arxiv.org/abs/2509.05209v2), [model card](https://huggingface.co/tencent/Hunyuan-MT-7B/blob/main/README.md)

**GraphRAG**
- [RAG vs. GraphRAG: A Systematic Evaluation and Key Insights (arXiv 2502.11371)](https://arxiv.org/html/2502.11371v2)
- [LazyGraphRAG (Microsoft Research)](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [HippoRAG (arXiv 2405.14831)](https://arxiv.org/abs/2405.14831), [HippoRAG 2 / From RAG to Memory (arXiv 2502.14802)](https://arxiv.org/pdf/2502.14802)

**Tối ưu F-measure**
- [Thresholding Classifiers to Maximize F1 Score — Lipton, Elkan, Narayanaswamy (arXiv 1402.1892)](https://arxiv.org/pdf/1402.1892)
- [Optimizing F-measure: A Tale of Two Approaches — Ye et al. (arXiv 1206.4625)](https://arxiv.org/pdf/1206.4625)
