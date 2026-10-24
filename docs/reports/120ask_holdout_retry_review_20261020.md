# Chạy lại mẫu 1.000 URL 120ask — 20/10/2026

**Kết luận: vẫn chưa đánh giá được F1/F2/F3 trên mẫu mới.** Đã gửi request mới sau khi người dùng báo mạng ổn định. Cả 5 URL đầu của mẫu tiếp tục trả **HTTP 521 với body rỗng**; crawl dừng theo ngưỡng 5 lỗi liên tiếp. Kiểm tra bổ sung thấy trang đối chứng trả HTTP 200, trong khi trang chủ và URL câu hỏi 120ask vẫn trả 521.

Run mới: `runs/ask120_holdout_retry_20261020T061428172365Z`. Crawl mẫu lúc **13:14–13:15**, kiểm tra kết nối bổ sung lúc **13:21**, ngày 20/10/2026 giờ Việt Nam. Mọi request mạng ở lượt này chạy ngoài sandbox.

## Đúng mẫu cũ, tải lại từ đầu

- Dùng **đúng 1.000 ID/URL đã cố định** ở lượt holdout trước; `sample.jsonl` giống từng byte, SHA-256 `b7007a60a2b9406831892a28232303e695f6224b3f974b624e7bb25442bb3474`.
- Không sao chép checkpoint fetch/parse hoặc raw lỗi cũ. Cả 5 URL từng lỗi được tải lại bằng request mới, có timestamp và response riêng.
- Mẫu vẫn gồm 1.000 canonical question duy nhất và không trùng 1.086 câu hỏi trong lịch sử trước khi chọn mẫu. Việc retry cùng mẫu được ghi riêng trong `retry_provenance.json`.
- Parser V4, gate/admission v3.1, ruleset `120ask-source-signals-v1` giữ nguyên. Hash source và policy được đối chiếu với manifest, không thay đổi rule F1/F2/F3.

## Kết quả crawl mẫu

| Chỉ số | Kết quả |
|---|---:|
| URL trong mẫu | 1.000 |
| URL có request mới | 5 |
| HTTP 521, body 0 byte | 5/5 |
| HTML sử dụng được | 0 |
| URL chưa thử | 995 |
| Thread/candidate mới | 0/0 |

Năm source ID được tải lại: **1266388, 1353680, 1073444, 2908421, 2873663**. Các response của run mới đều được lưu và kiểm hash. Crawl dùng một worker, delay 2 giây, một attempt/URL.

## Kiểm tra kết nối bổ sung

| Request đối chứng, tách khỏi số liệu mẫu | HTTP | Body |
|---|---:|---:|
| `https://example.com/` | **200** | 577 byte |
| `https://www.120ask.com/question/4191214.htm` | **521** | 0 byte |
| `https://www.120ask.com/` | **521** | 0 byte |

Các request này dùng Requests với `trust_env=True`, TLS verification bật và User-Agent `Mozilla/5.0`. Không có proxy trong environment hoặc cấu hình proxy hệ thống mà Requests đọc được. Kiểm tra này xác nhận kết nối tới trang đối chứng hoạt động; đường truy cập 120ask từ môi trường chạy vẫn trả 521. Response hiện có chưa đủ để phân biệt nguyên nhân ở site, lớp trung gian hay tuyến mạng tới site.

Tổng cộng lượt này có **5 request mẫu và 3 request chẩn đoán**, không có HTML câu hỏi 120ask sử dụng được. Không đổi proxy/IP, không tắt TLS verification và không dùng browser để vượt challenge.

## Review F1/F2/F3

| Finding | Kết luận lượt retry |
|---|---|
| F1: audio chỉ có lời nhắc vẫn INCLUDE | **Chưa đánh giá được trên mẫu mới** |
| F2: nghề nghiệp thiếu bằng chứng | **Chưa đánh giá được trên mẫu mới** |
| F3: quảng bá bỏ sót / bắt nhầm lâm sàng | **Chưa đánh giá được trên mẫu mới** |

Không có reply, header hoặc nội dung mới để đối chiếu. Những checkpoint EXCLUDE ở đây là lỗi fetch/raw, không phải kết luận về nội dung. Các regression cố định thuộc bộ cũ vắng mặt theo thiết kế holdout; `summary.json` có thể trả nhãn tổng quát `NEEDS_PARSER_FIX` vì dữ liệu chưa đầy đủ. Kết luận riêng của lượt này là **`NOT_ASSESSED_ACCESS_BLOCKED`**.

Không chạy lại unit test trong lượt retry vì parser/gate không đổi và không có dữ liệu nội dung mới. Kết quả 76/76 regression ở lượt trước không được tính thành kiểm chứng trên 1.000 URL này. Không thêm nhãn con người và không sửa parser khi chưa có bằng chứng mới.

[Notebook check chung](../../notebooks/check_120ask_50.ipynb), chế độ MODE='holdout_1000', vẫn sẵn để chạy từ môi trường truy cập được 120ask. Cần lấy được HTML mới rồi mới review ngữ nghĩa, nhất là các ca quảng bá không có cờ; không kết luận hết lỗi chỉ từ số cờ bằng 0.

- [Tóm tắt retry](../../runs/ask120_holdout_retry_20261020T061428172365Z/holdout_review_summary.json).
- [Kết quả chẩn đoán kết nối](../../runs/ask120_holdout_retry_20261020T061428172365Z/connection_diagnostics.json).
- [Bằng chứng cùng mẫu, checkpoint mới](../../runs/ask120_holdout_retry_20261020T061428172365Z/retry_provenance.json).
- [ZIP run retry](../../runs/ask120_holdout_retry_20261020T061428172365Z.zip).
