# ask.39.net — kết quả sửa F1 ngày 21/10/2026

Đã triển khai parser candidate `scripts/ask39.py`, version `ask39-parser-v1-f1`, dùng DOM để lấy câu hỏi và từng câu trả lời chính. Replay cùng 50 HTML baseline đã kiểm SHA-256 cho kết quả **72/72 answer được giữ đủ text**, không còn ba answer mất trước đây.

## Thay đổi

- Lấy câu hỏi và các phần bổ sung; chỉ bỏ bản mô tả lặp đúng nội dung, giữ nội dung bổ sung khác biệt.
- Mỗi answer có ID nguồn, thứ tự, locator, text/hash, tên người trả lời, profile và chức danh/header nguyên văn nếu có. Không suy mọi người trả lời là bác sĩ.
- Khôi phục paragraph bị đẩy thành sibling do HTML lồng `<p>` không hợp lệ, giới hạn trong container answer và dừng tại ranh giới metadata/answer khác.
- Check local mặc định dùng candidate; `--parser baseline` vẫn cho phép chạy bộ trích xuất cũ. Candidate chỉ được nạp vào snapshot trong bộ nhớ của check, không sửa notebook corpus chính hoặc domain samples.
- Candidate luôn `quality_status=review`, `corpus_eligible=false`; trang có follow-up mang cờ `followups_pending_f2`.
- Audit cho phép bỏ nhãn trường `补充说明：` khi mô tả trùng được render một lần; vẫn kiểm nội dung câu hỏi và phần bổ sung.

## Kết quả replay

| Chỉ số | Baseline | Candidate F1 |
| --- | ---: | ---: |
| Trang | 50 | 50 |
| Khối answer chính đối chiếu nguồn | 72 | 72 |
| Khối answer chính bị thiếu | 3 | 0 |
| Khối answer chính giữ đủ text | 69 | 72 |
| Khối hỏi bổ sung đã nhận diện bị thiếu | 0 | 0 |
| Khối answer cần khôi phục paragraph lồng sai | 6 | 6, giữ đủ |
| Trang thiếu follow-up | 3 | 3, chờ F2 |

Ba ca ID **2201880**, **2246297**, **2212484** đều giữ lại answer bị mất. Đối chiếu không chỉ dựa vào count: toàn bộ text sau khi bỏ khoảng trắng, thứ tự và ID của 72 answer đều khớp kỳ vọng đóng băng từ HTML nguồn; header người trả lời được đối chiếu riêng theo container.

Text candidate được dựng từ câu hỏi/answer nên audit không còn phát hiện bách khoa và UI trong mẫu này. Đây là tác động của ranh giới DOM F1, chưa thay cho việc nghiệm thu đầy đủ F3 trên template khác.

## Test nằm trong notebook

Theo yêu cầu, **10 test mới được viết trực tiếp trong cell** tại phần **“F1 — test parser DOM và replay 50 HTML (offline)”** của `notebooks/check_ask.39.net.ipynb`. Không tạo file test Python mới cho F1.

Các test phủ:

1. Toàn bộ 72 answer: text chính xác, ID, thứ tự, header tác giả và text hash.
2. Ba answer từng bị mất được khôi phục và xác nhận chúng thực sự thiếu ở baseline.
3. Câu hỏi và phần bổ sung không mất nội dung.
4. Sáu ca paragraph lồng sai, không kéo UI/metadata sang answer.
5. Candidate luôn REVIEW; follow-up còn chờ F2 được ghi rõ.
6. Giới hạn hostname/path và trang lỗi HTTP 200 không có template.
7. Câu trả lời ngắn, inline tag/line break, hai answer có text giống nhau và ranh giới ngoài container.
8. Biên paragraph lồng sai và charset GB2312/GB18030.
9. Audit nguồn độc lập đối chiếu câu hỏi và answer candidate.
10. Check route dùng candidate, giữ REVIEW, không thay route domain khác và không fallback accepted với URL ask39 không hỗ trợ.

Đã thực thi tuần tự các code cell của notebook bằng IPython trong Python local, mode `replay_f1`; output test và replay được lưu ngay trong notebook. Không gọi lại website hoặc tải nguồn HF. **10/10 test pass.** Ba test check/audit đã có từ trước cũng pass.

Notebook nhúng 50 raw fixture và kỳ vọng/hash, mặc định chạy offline replay; đặt `MODE='crawl_new'` để thử URL mới. Builder giữ các cell F1 và output khi cập nhật payload. Notebook vẫn được Git bỏ qua theo yêu cầu trước đó.

## Bằng chứng và giới hạn

- Replay cuối: `runs/ask39_f1_replay_20261021T165047990822Z` — `summary.json`, `dom_audit.jsonl`, raw, 50 candidate record, parser snapshot và manifest.
- Parser SHA-256: `204997f38a2e3bc47ec4f852cb11eb8f4fec7897020fc77c62ff374a0402ac1d`.
- Fixture payload SHA-256: `3fe3ab6704efe6d3444d1747a1262af3249292606abec3992193a8f5e9dfe1db`.
- Baseline và corpus production giữ nguyên. Chưa triển khai F2, gate admission cuối cùng, holdout hoặc tích hợp production.
- Kết quả đạt tiêu chí F1 trên 50 HTML baseline; chưa chứng minh đúng trên toàn domain hoặc độ đúng y khoa của câu trả lời.
