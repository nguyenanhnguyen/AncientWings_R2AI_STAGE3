# ask.39.net — kết quả sửa F4 ngày 22/10/2026

Đã triển khai `scripts/ask39_gate.py`, policy `ask39-gate-v1`, và nối gate vào report/export của check. **Thiếu answer hoặc follow-up phải REVIEW và không được vào candidate Parquet**, kể cả text dài, số đếm bị sửa hoặc record cũ mang nhãn accepted.

## Hợp đồng QC và export

- `extraction_status`: kết quả kiểm truy cập/nguồn, parser và audit nội dung/cấu trúc.
- `quality_status`: accepted chỉ khi extraction đạt và không có source flag cần review.
- `candidate_eligible`: điều kiện xuất file candidate local.
- `corpus_eligible=false`: chưa release production; holdout F5 và tích hợp F6 còn mở.

Mỗi lần export đọc lại raw gzip, đối chiếu SHA-256 và ID/URL với bộ bằng chứng nguồn. Gate không dùng nhãn accepted/candidate_eligible đã lưu làm quyền xuất. Record legacy/trafilatura, version cũ, raw thiếu/sai hash, redirect khác bài, HTTP/challenge lỗi hoặc record hỏng đều bị giữ ở REVIEW.

Gate kiểm số lượng và nội dung từng khối, locator/thứ tự/ID answer, metadata tác giả, parent/vai/thứ tự follow-up, câu hỏi/title/phần bổ sung, hash message/text và text render. Audit đọc lại DOM độc lập với parser. Vì vậy sửa số đếm hoặc chèn thêm text cho dài không bù được nội dung bị mất.

Không có ngưỡng ký tự tối thiểu để tự quyết định accepted: test answer một ký tự `好` với nguồn/cấu trúc đầy đủ đi qua QC và đủ điều kiện candidate.

Tác giả/chức danh chưa rõ hoặc tín hiệu quảng bá/liên hệ được ghi riêng trong `source_flags` cùng locator/quote. Đây là lý do review nguồn, không phải kết luận sai y khoa. Rule hiện tại còn giới hạn, cần holdout để đánh giá và mở rộng.

## Kết quả replay và xuất Parquet thực

| Chỉ số | Kết quả |
| --- | ---: |
| Trang replay / QC trích xuất đạt | 50 / 50 |
| Answer chính / follow-up giữ đủ | 72 / 6 |
| Candidate local được xuất | 48 |
| REVIEW, không xuất candidate | 2 |
| Xuất production | 0 |
| Test notebook | 42/42 pass |

Hai trang REVIEW vì `source_promotion_signal`:

- **2263361**, answer `reply_14315166`: đoạn giới thiệu/sử dụng sản phẩm 今幸 và 人参皂苷Rh2.
- **2212484**, answer `reply_17825428`: câu đề xuất “镜C联合下中医”疗法.

Cả hai trang vẫn giữ đủ nội dung trích xuất; gate giữ toàn trang ngoài candidate theo policy hiện tại, chưa chia quyết định xuất từng thread. Bằng chứng cụ thể có trong `candidate.decisions.jsonl` → `source_evidence`.

## Test mới trong notebook

**14 test F4 mới viết trực tiếp trong cell** tại phần “F4 — QC cấu trúc và export candidate (raw-backed)” của `notebooks/check_ask.39.net.ipynb`; không tạo file test Python mới:

1. Replay 50 raw: extraction đạt; source flags là quyết định riêng.
2. Mất answer, sửa count và kéo text hơn 10.000 ký tự vẫn bị chặn.
3. Mất follow-up và sửa mọi count vẫn bị raw audit phát hiện.
4. Giữ count nhưng thay text/ID/tác giả answer không qua gate.
5. Sai vai/parent/thứ tự hoặc message rỗng bị chặn.
6. Legacy accepted, raw thiếu/sai hash, redirect/challenge/HTTP lỗi không được xuất.
7. Answer ngắn đủ cấu trúc đi qua, không ép độ dài.
8. Chức danh chưa nhận diện/tín hiệu liên hệ giữ extraction đạt nhưng quality REVIEW.
9. Xuất Parquet thật từ tập trộn: chỉ record tốt được ghi; record mất follow-up và legacy accepted bị loại.
10. Raw thay đổi sau lần accepted vẫn bị kiểm lại; từ chối ID trùng và path ra ngoài run.
11. Title hoặc phần bổ sung không khớp nguồn bị chặn.
12. Đường report của check thực sự gọi gate và ghi candidate Parquet.
13. Gate snapshot chạy lại được khi chỉ có audit snapshot bên cạnh.
14. Record sai cấu trúc, parser flag chưa hiểu hoặc text bị thêm sidebar không đi qua.

Đã thực thi tuần tự code cell bằng IPython local, lưu output ngay trong notebook: **10 F1 + 9 F2 + 9 F3 + 14 F4 = 42 test pass**. Ba test check/audit có sẵn cũng pass. Không gọi lại website hoặc upload HF.

## Bằng chứng và bước còn lại

- Replay cuối: `runs/ask39_f4_replay_20261022T010154240781Z`.
- `candidate.parquet`: 48 dòng candidate đã kiểm lại raw.
- `candidate.decisions.jsonl`: quyết định cho đủ 50 ID; access/parser/audit/source flags và quote/locator.
- `summary.json`, `source_evidence.json`, `manifest.json`, raw, record, parser/gate/audit snapshot và hash phục vụ tái kiểm.
- Parser: `ask39-parser-v1-f4`, SHA-256 `678522a7098a51539058f37c8ef63771ad4d5c0b953a892dc18236747779efa1`.
- Gate SHA-256: `d865c65d64f11a62b073bc43c1c883abb32ada0aec859e37d8129ab1962154d6`.

Notebook vẫn được Git bỏ qua. Chưa sửa/export corpus production; tiếp theo là F5 replay diff và holdout mới, sau đó F6 tích hợp các đường crawl/postprocess/recovery production.
