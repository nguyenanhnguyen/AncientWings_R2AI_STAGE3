# Kiểm tra lượt English 4B sau khi leaderboard trả 0

Lượt: `nguyen/pipeline_runs/en_batches_01_08/finish_4b_rerank06b_k100`.
Người dùng báo cả bảy metric bằng 0 ngày 19/10/2026.

Người dùng đã xác nhận: dashboard chấm thành công ở **public phase**, file nộp
đúng là `finish_4b_rerank06b_k100/submission_recall/submission.zip`.
Vì vậy không còn coi nhầm file hoặc trạng thái đang xử lý là giả thuyết chính.

## Đã kiểm tra trên dữ liệu local

- Submission recall chứa đủ 1.200 câu hỏi; tập ID trùng với `data/query.parquet`.
- Query snapshot của lượt chạy giống hoàn toàn bảng query local hiện tại.
- 79.721/79.721 tài liệu corpus có ID và URL khớp chính xác
  `data/links_corpus_vi_en_zh.parquet` (1.220.598 dòng).
- 13.705 ID tài liệu khác nhau trong submission đều thuộc bảng links local.
- ZIP chỉ chứa `submission.json`; kiểm tra CRC và checksum stage đều thành công.
- Validation nội bộ không có cảnh báo, không loại tài liệu/chunk, không có câu trả lời rỗng.
- Một số kết quả đầu có nội dung liên quan về chủ đề: câu 1 về thực quản/dạ dày
  trả bài về reflux/peptic ulcer; câu 3 về beta-HCG trả bài về xét nghiệm beta-HCG.
  Đây là kiểm tra thủ công hạn chế, không phải nhãn relevance.

## Giới hạn của kết luận

Đây là corpus chỉ gồm PubMed tiếng Anh, không bao phủ toàn bộ corpus chính thức.
Đúng chủ đề không bảo đảm đúng ID tài liệu có nhãn. Không có nhãn đánh giá hoặc
log scorer từ BTC nên chưa xác định được nguyên nhân duy nhất của điểm 0.
Không có bằng chứng hiện tại cho phép kết luận cần đổi kiểu ID sang string,
đổi model hoặc chạy lại embedding.

Luồng tiếp nối không dịch truy vấn, dùng BM25 tiếng Việt trên corpus tiếng Anh và
dense đa ngôn ngữ, rồi rerank 0.6B. Kênh BM25 có thể đưa ứng viên nhiễu vào fusion;
ảnh hưởng cần đánh giá riêng, không được suy ra là nguyên nhân chắc chắn của điểm 0.

Cần đối chiếu phiên bản query/links mà scorer dùng. Trạng thái chấm, public phase
và file thực tế đã nộp đã được người dùng xác nhận. Kiểm tra độ phủ tài liệu có nhãn
trước khi dành thêm thời gian cho model lớn. Không tự động khởi chạy lại GPU.
