# Kiểm tra URL corpus

- Bản nguồn: [Hugging Face, revision 71be0e1239a19dfd7a717e2bc13e3bec21bd0334](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/blob/71be0e1239a19dfd7a717e2bc13e3bec21bd0334/links_corpus_vi_en_zh.parquet).
- Toàn snapshot có 1.220.598 URL; riêng 8 nguồn được yêu cầu có 781.086 URL, khớp đủ 8 số lượng đã cung cấp.
- Thực kiểm tra 353 URL: 50 URL mỗi nguồn trong 7 nguồn và 3 URL của 120ask. Không kiểm tra hết toàn bộ corpus.
- Thời gian: 2026-10-13T21:22:48+07:00 đến 2026-10-13T21:29:47+07:00 (giờ Việt Nam).
- Nguồn: data\research\eda\results\url_health_20261013\links_corpus_vi_en_zh.parquet; SHA-256: `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`.
- Kế hoạch mẫu: reservoir ngẫu nhiên 50 URL mỗi nguồn, seed=20261013; GET theo redirect, TLS được xác minh, tối đa 2 lần cho URL lỗi. Số thực kiểm tra hiển thị trong bảng; dừng nguồn nếu kết nối liên tục thất bại.
- Kết quả phản ánh đường mạng/IP và user agent của máy kiểm tra. `http_ok` nghĩa là tải được phản hồi 2xx, không đảm bảo parser lấy được nội dung bài phù hợp.
- Không ngoại suy tỷ lệ lỗi từ mẫu thành số link lỗi chính xác toàn corpus.

| Nguồn | URL toàn nguồn | Mẫu | HTTP ổn, chưa thấy lỗi bài | 404/410 | Trang lỗi/rỗng 200 | Chặn/challenge | Về trang chủ | Khác |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pubmed.ncbi.nlm.nih.gov | 240,000 | 50 | 0 | 0 | 0 | 50 | 0 | 0 |
| suckhoecongdongonline.vn | 154,503 | 50 | 50 | 0 | 0 | 0 | 0 | 0 |
| www.120ask.com | 98,160 | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| suckhoedoisong.vn | 85,823 | 50 | 50 | 0 | 0 | 0 | 0 | 0 |
| nhathuoclongchau.com.vn | 79,598 | 50 | 50 | 0 | 0 | 0 | 0 | 0 |
| thanhnien.vn | 72,111 | 50 | 50 | 0 | 0 | 0 | 0 | 0 |
| www.vinmec.com | 26,129 | 50 | 49 | 0 | 1 | 0 | 0 | 0 |
| medlatec.vn | 24,762 | 50 | 50 | 0 | 0 | 0 | 0 | 0 |

Chi tiết và lịch sử thử lại: `*.jsonl`; bảng URL: `url_results.csv`; URL lỗi hoặc chưa xác minh: `failed_or_uncertain.csv`.

Chú ý: `suspected_soft_404`, `suspected_missing_article` và `challenge_200` là cờ kiểm tra nội dung; chưa đủ để kết luận URL chết vĩnh viễn.

API NCBI EFetch trả HTTP 200: 50 bản ghi và 50 bản ghi có abstract; PMID thiếu: []. 403 từ trang PubMed không đồng nghĩa bản ghi đã bị xóa. Xem `pubmed_api_verification.json` và `pubmed_efetch.xml`.

URL Vinmec cần kiểm tra nội dung: https://www.vinmec.com/vie/bai-viet/tre-tron-bo-co-sao-khong-vi. Hai lần GET tiếp theo vẫn HTTP 200 nhưng title chỉ `| Vinmec`, h1 rỗng; extractor trả chủ yếu thông báo chọn ngôn ngữ. Đặt Accept-Language tiếng Việt không khôi phục bài. Công cụ web trả phiên bản có bài từ cache 7 tháng trước; chưa xác minh được nội dung bài hiện tại trên đường mạng này. Xem `vinmec_suspect_verification.json` và `vinmec_suspect_vi_verification.json`.

Nguồn www.120ask.com: thực kiểm tra 3/50 URL; 47 URL mẫu chưa thử. Dừng mở rộng vì các kiểm tra kết nối ban đầu lỗi lặp lại; không gán trạng thái lỗi cho URL chưa thử.
