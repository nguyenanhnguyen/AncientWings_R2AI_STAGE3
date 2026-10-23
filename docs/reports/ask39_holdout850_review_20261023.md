# ask.39.net — holdout mới 200 URL, loại 850 URL cũ (23/10/2026)

**NEEDS_FIX — chưa xét đạt F6.** Đã thử đủ 200 URL mới, không trùng ID hoặc URL với toàn bộ 850 URL đã chọn trước đó. Có **200 raw trang hỏi–đáp hợp lệ**, **261 answer + 10 follow-up**, 1 đánh giá đã lưu metadata. Gate đóng băng cho **195 accepted candidate local / 5 REVIEW**. Review phát hiện **5 lỗi/thiếu coverage đã xác nhận** và **8 trang chờ review chính sách/chuyên môn**. Không tích hợp F6, production export 0.

## Mẫu và bản đóng băng

Chọn trước request, seed **20261026**, 100 URL numeric + 100 URL underscore từ source Parquet có SHA-256 `87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7`. Đây là phân bổ đều hai strata, không phải ước lượng tỷ lệ lỗi theo dân số website. `excluded850.jsonl` lấy đủ 850 baseline record của replay850, kiểm độc nhất và không overlap theo cả ID lẫn URL. Không thay URL khi gặp lỗi. Mẫu gốc, raw và artifact replay850 giữ nguyên hash.

| File | SHA-256 đóng băng |
| --- | --- |
| `ask39.py` | `d78faaaaed7393dd751d5f222650608886cbffb2fe707f32638024aab6a841b2` |
| `ask39_audit.py` | `5bbd6fdf60b674609a2884f58e39c85f4ed269ec568187effec94ea595e3bdcc` |
| `ask39_gate.py` | `ef8cd88c22811059430901a17cbf399ad4be8ba330619c778fe74ce8a47eb475` |
| `check_ask39.py` | `99ad093069cc5cf6fc5d14298833d19723b292c062278416390a1711e2d795ca` |
| `ask39_dns.py` | `cf309a7159fb817ec45d7d7986e2453e4b2c908d91777459e0a5be9340cdcc88` |

Parser v2 patient-evaluations, audit v3 render-roles, gate v8; không sửa rule trong suốt crawl/review. Transport pack `96f6d0ed430a8e7c5838c82230e6508004858eb343998f96f62e46c9f68cb16c`. Requests một attempt, delay 2 giây, connect 8/read 20 giây, budget 60 giây; browser fallback giới hạn 3, TLS verify giữ bật. Bản đóng băng và manifest được lưu trước crawl.

## Transport và tính toàn vẹn

- Requests lượt đầu: `{"None": 18, "200": 182}`; browser attempted **3**.
- Thu raw hợp lệ từ 182 Requests lượt đầu + 1 browser fallback (2455342) + 17 Requests retry = **200**; không còn slot lỗi mạng.
- Retry bổ sung: `{"attempted": 17, "recovered_ids": [2305823, 2351750, 2308535, 2449355, 2426797, 2163245, 2178668, 2414442, 2254826, 2466094, 2461671, 2173761, 2451895, 2462963, 2225968, 2471601, 2213888], "remaining_transport_errors": []}`. Chỉ một lượt có giới hạn trên đúng URL lỗi mạng, giữ cùng code/settings; không proxy/IP bypass, không thay mẫu. Lượt đầu lưu bất biến riêng, merge kết quả tải lại ở run mới nếu có.
- Chưa truy cập được: `[]`. Lỗi mạng không được coi là có raw hợp lệ hoặc accepted.
- Kiểm hash raw và liên kết request-event; reparse offline đối chiếu text/hash/question, answer ID, follow-up ID, parent, role, thứ tự, metadata và DOM exclusions. Mọi quyết định gate được tính lại từ raw và source provenance; export đúng ID/text/hash accepted, không xuất REVIEW.
- Có 17 khác biệt chỉ tại `audit.baseline_qc`: export đọc status trước gate, replay đọc record đã gắn status cuối. Ledger giữ danh sách ID và chỉ cho phép leaf thông tin này khác; các field policy/evidence khác phải bằng nhau.

## Review đã hoàn tất

Assistant đã đọc **80 trang bắt buộc**, gồm mọi REVIEW/error, đại diện của **17 nhóm cấu trúc** quan sát được, mọi signal từ rà soát rộng, mọi ca recovered, và **20 accepted chọn ngẫu nhiên từ dân số cuối cùng** bằng seed 20261026. DOM template được đọc riêng: child của owner, biên paragraph, body locator, nhãn zw1/zw2, parent, UI và metadata đánh giá. Manifest review ghi reviewer là assistant, `human_approval=false`.

20 accepted ngẫu nhiên: `[2212002, 2268261, 2461671, 2217685, 2422248, 2401516, 2432165, 2200585, 2152995, 2400623, 2439988, 2369296, 2345381, 2351750, 2254778, 2453067, 2445884, 2308535, 2423147, 2462980]`. Đây là danh sách accepted **theo gate đóng băng**, không phải nhãn xác thực lâm sàng.

Ngoài screening đã có trước crawl, sau khi thấy template mới đã mở rộng **chỉ bước review** để tìm `p.pingjia` trực tiếp trong owner và tên account tổ chức dạng “中心/管理…”. Parser/audit/gate không đổi. Mỗi trang mới bị screening gọi thêm đều được đọc; không sửa nhãn frozen để làm holdout pass.

| ID | Phát hiện | Frozen gate | Evidence và hướng xử lý |
| --- | --- | --- | --- |
| 2450406 | `absolute_safety_coverage_gap` | accepted | Khẳng định trực tiếp phương pháp chỉnh nha không gây hại răng; không phải phủ định claim, lời bệnh nhân hoặc trích dẫn. Gate v8 thiếu cả tên phương pháp lẫn mẫu gây hại răng. Câu sau thừa nhận khó chịu tạm thời nhưng không giới hạn câu khẳng định đầu. Cần REVIEW theo chính sách claim an toàn; chưa kết luận đúng/sai lâm sàng. |
| 2351750 | `safety_multi_sentence_reference_gap` | accepted | Claim không gây tổn thương mô khỏe nằm trong đúng mục 2.放射治疗, dùng tham chiếu 该技术 sau câu mô tả lịch điều trị. Pattern claim đã tồn tại nhưng gate chỉ nhìn một câu trước, không tìm thấy phương pháp qua câu trung gian nên assessments rỗng và accepted. Cần tham chiếu có giới hạn theo mục/đoạn, không vượt sang mục khác; 无法完全摘除 mô tả khả năng cắt bỏ u, không phủ định claim an toàn. |
| 2208116 | `audit_nonempty_answer_sibling_false_positive` | review | sele_txt có mở đầu không rỗng, ngay sau là đoạn p không class/id trong cùng container. Parser lấy đủ cả hai, dừng trước UI. Audit chỉ ghép sibling khi sele_txt rỗng nên báo hai lỗi giả. Cần sửa audit độc lập theo biên DOM, không hạ gate hoặc bỏ qua flag chung. |
| 2203959 | `organization_author_coverage_gap` | accepted | Account mang tên trung tâm quản lý sức khỏe, affiliation là công ty dược và answer giới thiệu sản phẩm. Gate v8 chỉ bắt một số hậu tố tên tổ chức, bỏ sót 管理中心; nhãn 医师 không đủ để accepted. Cần REVIEW nguồn tổ chức, giữ nguyên lời đáp và provenance, không dùng affiliation bệnh viện của bác sĩ cá nhân làm điều kiện đơn lẻ. |
| 2212096 | `sibling_patient_evaluation_metadata_missing` | accepted | Đánh giá bệnh nhân nằm ở p.pingjia anh em sau sele_txt, cùng container. Không lẫn lời bác sĩ nhưng bị mất khỏi patient_evaluations và không có provenance. Audit chỉ kiểm span.pingjia trong body nên bỏ sót. Cần mở coverage metadata theo đúng owner, không nhập thành answer/follow-up. |

Các finding lưu raw SHA, URL, answer ID, role, owner/body locator và exact source HTML hoặc quote/span. Lỗi metadata không phải mất answer: clinical answer vẫn đủ, nhưng đánh giá bệnh nhân chưa được lưu riêng. Lỗi audit là false positive trên đoạn nối có thật, không phải parser mất text. Candidate local giữ nguyên quyết định frozen để tái hiện lỗi; release bị chặn riêng bởi kết quả review.

Các trang chờ thẩm định thêm, chưa kết luận y khoa đúng/sai:

- **2225312** — Answer 69687245 giới thiệu công nghệ mới có hiệu quả tốt hơn nhưng không nêu phương pháp cụ thể. Ghi chờ review chính sách quảng bá không nêu tên; không suy ra danh tính phương pháp từ ngữ cảnh.
- **2197950** — Các answer cùng trang bất đồng trực tiếp về tính lây nhiễm: 34236681 ghi 传染性强, 34236070 ghi 没有传染性/不用治疗. Raw xác nhận đúng owner; không phải parser gán nhầm. Giữ chờ thẩm định chuyên môn, chưa xác minh đúng/sai lâm sàng.
- **2369296** — Mở đầu liệt kê điều trị hỗ trợ và 巨球蛋白血症治疗 rồi nói 进行根治; thân bài lại mô tả 辅助治疗/缓解 và đổi chủ đề sang 巨球蛋白血症. Raw xác nhận cả đoạn cùng answer, không kéo từ bách khoa hoặc answer khác. Cần thẩm định chuyên môn/chính sách claim; chưa kết luận y khoa.
- **2253640** — Ba answer 96696514/96696513/96696512 lặp đoạn mô tả 空洞…脊髓 trong trang hỏi 先天性脑中风后遗症. Kiểm DOM xác nhận ba owner riêng; nội dung lặp có nguyên trong source, không phải parser copy nhầm. Cần review độ phù hợp chủ đề/chuyên môn trước sử dụng.
- **2231356** — Nguồn trả lời câu hỏi về trẻ sơ sinh nhưng đề xuất áo ngực chuyên dụng và nói về người cho bú ở các mục 3/5. Nội dung có nguyên trong cùng answer; cần thẩm định độ phù hợp đối tượng, chưa kết luận lâm sàng.
- **2473667** — Câu hỏi về xuất huyết não nhưng answer liệt kê 抗凝药 rồi nêu 阿司匹林. Lưu pending chuyên môn để kiểm loại thuốc, chỉ định và thời điểm, không tự sửa lời nguồn hoặc xác nhận tính an toàn.
- **2414442** — Answer của bác sĩ cá nhân kèm đoạn giới thiệu bệnh viện, địa chỉ và lời quảng bá cơ sở. Không phải UI bị kéo vào vì nằm nguyên trong p.sele_txt. Cần review chính sách quảng bá/địa chỉ trong answer; không suy ra đây là tác giả tổ chức chỉ từ affiliation.
- **2462980** — Answer nói thường không cần vaccine ở người lớn không có tiền sử nhiễm và không tiếp xúc gần người nhiễm. Tương tự nhóm vaccine đã pending ở holdout trước; giữ chờ thẩm định chuyên môn, không tự kết luận đúng/sai.

Các artifact văn bản nguồn đã giải thích, không tự xóa vì nhìn giống rác:

- **2225181** — Số 2 cuối answer nằm nguyên trong p.sele_txt sau br ở raw. Giữ nguyên, không có bằng chứng đây là nút UI.
- **2255926** — Chuỗi ?? và các chỗ câu hụt đã có nguyên trong raw p.sele_txt; parser không xóa đoạn. Chưa thẩm định lâm sàng toàn bộ lời khuyên.

Tổng hợp flags từ replay gate cuối:

```json
{
  "access_flags": {},
  "parser_flags": {},
  "audit_flags": {
    "answer_message_text_mismatch": 1,
    "raw_rendered_text_mismatch": 1
  },
  "source_flags": {
    "source_qualification_unrecognized": 4
  }
}
```

## Test và bước tiếp theo

**13 test evidence mới trong cell của `notebooks/check_ask.39.net.ipynb` + 3 helper test pass.** Test tái hiện cả lỗi đã biết và xác minh chặn readiness; “test pass” không có nghĩa holdout đạt F6. Không rerun toàn bộ lịch sử Run All trong lượt bổ sung bằng chứng này. Notebook tiếp tục gitignored và builder giữ section holdout850; không tạo file test Python mới.

Ưu tiên sửa: (1) audit ghép paragraph tiếp nối khi `sele_txt` đã có mở đầu, theo đúng biên owner; (2) metadata cho `p.pingjia` cùng owner và kiểm coverage độc lập; (3) nguồn tổ chức dạng quản lý/trung tâm, không dựa đơn lẻ vào affiliation cá nhân; (4) claim an toàn chỉnh nha theo ngữ cảnh/người nói; (5) tham chiếu phương pháp qua câu trung gian trong cùng mục, không vượt biên sang mục/phương pháp khác. Hai hướng claim đều cần ca âm phủ định/trích dẫn/bệnh nhân. Giữ các trang pending ở REVIEW trước khi dùng. Sau đó replay inventory tích lũy và giải thích mọi thay đổi, rồi đóng băng lại để kiểm holdout khác trước F6. Tập loại trừ lần sau phải gồm **1.050 ID/URL đã chọn**; đã lưu `selected1050.jsonl`.

Run cuối: `runs/ask39_holdout850_completed_20261023T090703196241Z`.

Evidence chính: `holdout850_final_summary.json`, `holdout850_assistant_review.json`, `holdout850_pending_findings.json`, `holdout850_observations.json`, `holdout850_review_data.json`, `holdout850_review_packet.md`, `holdout850_signal_screen.json`, `verification.json`, manifest/sample/results/candidate và raw. Freeze root: `runs/ask39_holdout850_frozen_20261023T070349313892Z`. Lượt đầu: `runs/ask39_holdout850_new200_20261023T070349313892Z`.
