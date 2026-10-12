# Chọn model cho Kaggle — 11/10/2026

## Quyết định

Kaggle: **Qwen3-Embedding-4B + Qwen3-Reranker-4B**, FP16, mỗi GPU một replica, xử lý hai phần không trùng. Local giữ BGE-M3 + BGE-reranker-v2-m3. Chỉ inference; không khối T, dịch, feedback hoặc ensemble.

Đây là lựa chọn phù hợp để thử trên T4×2 với code hiện tại, **chưa phải model tốt nhất đã được chứng minh cho ViBioMIR**. Chưa có nhãn dev độc lập hay số đo T4 của cấu hình này.

## Bằng chứng và các phương án đã xem

| Vai trò / benchmark do Qwen công bố | BGE ~0,6B | Qwen3 4B | Qwen3 8B |
|---|---:|---:|---:|
| Embedding: MTEB multilingual, retrieval | 54,60 | 69,60 | 70,88 |
| Reranker: MMTEB-R | 58,36 | 72,74 | 72,94 |
| Reranker: CMTEB-R | 72,16 | 75,94 | 77,45 |

Nguồn: [Embedding model card](https://huggingface.co/Qwen/Qwen3-Embedding-4B), [reranker model card](https://huggingface.co/Qwen/Qwen3-Reranker-4B). Hai loại benchmark đo khác nhau, không so điểm giữa hai hàng vai trò. Reranking dùng cùng top-100 ứng viên của Qwen3-Embedding-0.6B. Đây không phải F2 cuộc thi hoặc kết quả riêng cho câu hỏi y khoa Việt–Trung.

| Phương án khác | Nhận xét cho lần triển khai này |
|---|---|
| Qwen3 8B | Thêm chất lượng benchmark nhưng khoảng 16 GB trọng số FP16/model, chưa tính activation. T4 không đủ dư địa batch; phải lượng tử hóa hoặc chia model. Chưa có số đo cho thấy lợi hơn hai replica 4B trong cùng ngân sách giờ. |
| [PPLX-embed-v1-4B](https://huggingface.co/perplexity-ai/pplx-embed-v1-4b) | 4B, mean pooling, vector INT8 không chuẩn hóa và custom code; không thay trực tiếp vào luồng vector chuẩn hóa hiện tại mà bỏ qua kiểm tra tương đương. Là ứng viên thử nghiệm sau. |
| [zerank-2](https://huggingface.co/zeroentropy/zerank-2-reranker) | 4B, có benchmark biomedical; quy tắc điểm là sigmoid(logit/5). Chưa có so sánh trên dữ liệu Việt–Trung của nhóm để chọn thay Qwen. |
| [Jina reranker v3](https://huggingface.co/jinaai/jina-reranker-v3) | 0,6B, listwise, cần đường xử lý riêng; không phải lựa chọn tăng tham số theo yêu cầu lần này. |
| [Querit-4B](https://huggingface.co/Querit/Querit-4B) | Model card nêu kết quả ngày 29/08/2026 và 8 ngôn ngữ không gồm Việt; chưa xác minh được checkpoint thích hợp trước mốc cuộc thi nên chưa chọn. |

## Phiên bản và cách nạp

Theo [RULE.txt](../note/RULE.txt), model phải công khai trước 01/08/2026 và không quá 15B. Qwen công bố dòng này ngày **05/06/2025**, Apache-2.0: [thông báo chính thức](https://qwenlm.github.io/blog/qwen3-embedding/).

Ghim checkpoint đã kiểm tra qua API HF; không tự lấy `main` mới mỗi phiên:

| Model | Revision |
|---|---|
| [Embedding-4B](https://huggingface.co/api/models/Qwen/Qwen3-Embedding-4B) | `5cf2132abc99cad020ac570b19d031efec650f2b` — cập nhật 20/06/2025 |
| [Reranker-4B](https://huggingface.co/api/models/Qwen/Qwen3-Reranker-4B) | `22e683669bc0f0bd69640a1354a6d0aebcfeede5` — cập nhật 16/04/2026 |

- Embedding: instruction tiếng Anh theo nhiệm vụ y khoa chỉ thêm vào query; passage giữ nguyên; left padding → lấy token cuối → L2 normalize, đủ 2.560 chiều.
- Reranker: prompt Instruct/Query/Document, giữ suffix khi truncate; tính softmax trên hai logit `no`/`yes` ở vị trí cuối. Không gọi `generate()`. [Ví dụ chính thức](https://github.com/QwenLM/Qwen3-Embedding).
- FP16 và PyTorch SDPA; không ép FlashAttention 2 vì backend đó yêu cầu GPU mới hơn T4. [Hỗ trợ CUDA của FlashAttention](https://github.com/Dao-AILab/flash-attention#nvidia-cuda-support).
- `accelerate` nạp model trực tiếp vào GPU để giảm đỉnh RAM CPU. Giải phóng encoder trước reranker; không offload CPU âm thầm, không đổi về BGE.

## Ngân sách trong notebook

- Batch encode **16**, rerank **8**; tự giảm nếu CUDA OOM. Độ dài đầu vào tối đa vẫn 1.024 token, không dùng context 32K chỉ vì model hỗ trợ.
- Rerank 60 chunk/query: tối đa 72.000 cặp với 1.200 query. Hai GPU chia query; cache tránh chấm lại cặp đã xong.
- Deadline notebook 8 giờ thực, chỉnh theo tài khoản; không phải cam kết hoàn thành hay thước đo quota GPU.
- Khoảng 7,5 GiB trọng số/model là **ước tính từ tham số × 2 byte**, không phải tổng VRAM đo được. Mỗi GPU cần chỗ cho activation và bộ nhớ CUDA nữa.
- Cache hai model khoảng 16 GB ở `/kaggle/temp/vibiomir_hf_cache`, không đóng vào Output; phiên mới có thể tải lại. Corpus/index/checkpoint ở `/kaggle/working`.
- Vector 2.560 chiều tốn khoảng 2,5 lần dung lượng BGE 1.024 chiều với cùng dtype/số chunk. Vẫn phải theo dõi ổ đĩa khi mở rộng corpus.
- Run mới mang tiền tố `run_qwen4b_`; không restore index BGE vào đó. Muốn đánh giá A/B, giữ nguyên corpus/query/chunk/selection; so F2 và thời gian thực, không chỉ benchmark chung.

Kiểm thử source dùng mô hình Qwen3 cấu hình nhỏ khởi tạo ngẫu nhiên trên CPU để kiểm tra pooling, padding và công thức logits. Không coi đó là đo chất lượng checkpoint 4B hoặc thông lượng T4.
