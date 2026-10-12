# Thử từng kỹ thuật trên snapshot 100k

## Mốc đối chiếu

`pipeline.txt` giữ thiết kế tổng thể, nhưng không phải bản cũ chưa sửa:
Git có commit `062f3db` ngày 10/10/2026 sửa 7 dòng và thêm 7 dòng.
Code chạy thực tế là `src/vibiomir/pipeline.py`.

Điểm người dùng báo (chưa được code gắn với SHA bài nộp):

| Final | Docs F2 | Chunks F2 | Docs precision | Docs recall | Chunks precision | Chunks recall |
|---:|---:|---:|---:|---:|---:|---:|
| 0.1258 | 0.1958 | 0.0558 | 0.1555 | 0.2417 | 0.068 | 0.0631 |

Snapshot local giữ 99.507 documents từ 100.000 records. Retrieval đang tìm trên
107.607 chunks của tập tài liệu được cards chọn. Đây là **hợp các tài liệu được
chọn cho mọi câu hỏi**, không phải toàn bộ corpus và cũng không giới hạn mỗi câu
hỏi chỉ vào 100 tài liệu riêng của nó. Kênh card là tín hiệu bổ sung trong RRF.

Chưa có nhãn để phân biệt mất recall do thiếu tài liệu trong corpus, cards,
retrieval, reranker, hay chọn/mở rộng đoạn. 100k là số records đầu vào, không phải
số câu hỏi đánh giá; hiện có 1.200 câu hỏi.

## Chạy xuyên đêm

Từ thư mục gốc, dùng env đã chạy pipeline thành công; không cần cài model mới:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py experiments --dry-run
.\env\Scripts\python.exe scripts/vibiomir.py experiments
```

Lệnh thứ hai chạy tuần tự các lượt bên dưới. Không chạy đồng thời pipeline khác
trên GPU 4GB. Tắt sleep của máy trong thời gian chạy. Ctrl+C để dừng; chạy lại
đúng lệnh để tiếp tục. Stage hoàn tất được kiểm tra hash; cặp rerank đã chấm được
lưu SQLite. Nếu đổi code, stage có thể chạy lại, còn cache điểm phù hợp vẫn dùng được.

Không crawl/prepare/dịch hay encode lại corpus. Mỗi lượt retrieval vẫn encode
câu hỏi và tìm kiếm lại. Dùng lại BGE-M3 và BGE reranker có sẵn; model cache vẫn
theo cấu hình HF hiện có. Output và cache thí nghiệm mặc định ở ổ D trong
`work/ablation_100k/`. Cache gốc được backup qua SQLite một lần, không copy riêng
file SQLite khi WAL đang mở. Cần thêm dung lượng cho bản backup và các bài nộp.

Muốn chỉ thử chọn đoạn/profile, dùng thư mục khác:

```powershell
.\env\Scripts\python.exe scripts/vibiomir.py experiments --suite selection --out work/ablation_selection
```

## Các lượt thử

| Tên | So với | Thay đổi |
|---|---|---|
| baseline | Bài hiện tại | Dựng lại bài nộp từ candidates hiện tại |
| window0 | baseline | Giữ span chunk đã index, không mở rộng lên 768 token |
| balanced | baseline | Chọn theo profile balanced |
| precision | baseline | Chọn theo profile precision |
| rerank100 | baseline | Chấm 100 ứng viên thay vì 50, vẫn giữ ngân sách output cũ |
| no_card | baseline | Bỏ kênh card trong RRF; vẫn cùng index subset |
| original_question | baseline | Rerank bằng câu hỏi Việt, không thay bằng bản dịch theo ngôn ngữ chunk |
| feedback1 | baseline | Một lượt feedback từ candidates đã rerank của baseline |
| feedback2 | feedback1 | Lượt feedback tiếp theo từ candidates của feedback1 |

Các thay đổi không được tự động cộng dồn, trừ chuỗi feedback có chỉ rõ cha.
`no_card` không đo tác động của việc bỏ tầng lọc cards khỏi toàn pipeline.
Hai vòng feedback có thể hội tụ về cùng kết quả; đó cũng là kết quả cần ghi nhận.

Log baseline ghi retrieval khoảng 2.674 giây (~45 phút). Đây là số đo của một lượt
trước, không phải ETA cho toàn bộ thí nghiệm. Suite có 5 lượt retrieval mới;
rerank100 có thể chấm tối đa 120.000 cặp trước cache. Các lượt 50 có tối đa
60.000 cặp/lượt. Cache giảm số cặp mới tùy mức trùng nhau; xem `cache_hits`,
`cache_misses`, `retrieval_seconds` trong báo cáo. Không đảm bảo hoàn tất qua một đêm.

## Feedback hoạt động thế nào

1. Lấy tối đa 5 tài liệu khác nhau từ kết quả đã rerank của lượt trước.
2. Lấy text của chunk đại diện mỗi tài liệu; tính điểm term:
   `sum((tf / số token chunk) × IDF / log2(rank + 1))`.
3. Chỉ giữ term có ở ít nhất 2 tài liệu nguồn, dài >=2 ký tự, không phải số,
   không nằm trong câu hỏi/bản dịch, có document frequency <=20% index chunk.
4. Chọn tối đa 8 term, thêm vào token câu hỏi + bản dịch để tìm BM25.
5. Thêm một kênh RRF trọng số 0,3; các kênh gốc vẫn giữ nguyên.
6. Rerank ứng viên mới bằng câu hỏi gốc hoặc bản dịch đã có, **không** dùng câu
   hỏi đã thêm term để tự xác nhận feedback. Chọn đoạn nguồn và xuất ZIP như cũ.

Đây là heuristic TF-IDF cho pseudo relevance feedback, không phải RM3 và không
phải term/entity y khoa đã được xác minh. Chưa dùng LLM viết lại truy vấn.
File `feedback_trace.jsonl` ghi term, support, điểm và ID tài liệu nguồn.
Feedback chỉ tìm trong index hiện có: không cứu được tài liệu chưa được index.
PRF có thể lệch chủ đề khi seed sai; xem
[Stanford IR book: pseudo relevance feedback](https://nlp.stanford.edu/IR-book/html/htmledition/pseudo-relevance-feedback-1.html).

## Đọc kết quả

- `work/ablation_100k/RESULTS.md`: danh sách ZIP và độ thay đổi candidates so baseline.
- `summary.json`: thống kê output, thời gian retrieval, cache và metrics nếu có nhãn.
- `<tên lượt>/submission/submission.zip`: bài nộp riêng, đã qua validator.
- `logs/`: log từng stage; `plan.json`: lệnh, hash dữ liệu, quan hệ các thí nghiệm.
- Mọi cột `vs_baseline` so với baseline, kể cả dòng feedback2; parent của nó vẫn
  là feedback1 để đối chiếu vòng lặp. Jaccard/top1 thay đổi không phải điểm chất lượng.

Nếu có nhãn validation thật, thêm `--labels đường_dẫn_labels.jsonl` từ đầu và
chọn thư mục output mới. Bộ chạy gọi evaluator hiện có cho từng bài và không
tự sinh pseudo labels. Không dùng cùng nhãn để vừa hiệu chuẩn vừa báo điểm test.
Nếu chỉ có leaderboard, ghi 7 metric cho từng ZIP theo cùng thứ tự bảng trên;
tuân thủ giới hạn lượt nộp của cuộc thi. Bộ chạy không tự upload/nộp bài hay
tự chọn “bản tốt nhất” khi thiếu nhãn.

## Lượt tiếp theo sau khi có đối chiếu

1. Đo coverage tài liệu nhãn trong corpus và subset trước khi tăng model.
2. So toàn corpus chunk index với cards subset; đây là thí nghiệm riêng, cần encode
   thêm tài liệu và có thể tăng RAM/VRAM/time đáng kể.
3. Thử chunk theo cấu trúc Q&A/heading và kích thước khác trên cùng corpus; dựng
   index riêng, không dùng chung embedding của chunk cũ.
4. Đánh giá HyDE, model reranker khác/ensemble, rồi teacher/student. Mỗi lượt có
   baseline và dữ liệu huấn luyện/validation tách biệt; chưa bật các bước đó trong
   suite này vì sẽ không biết kỹ thuật nào gây tăng/giảm điểm nếu thêm cùng lúc.
