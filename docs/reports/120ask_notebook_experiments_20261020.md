# 120ask: thí nghiệm trong notebook và đề xuất fix — 20/10/2026

Đây là báo cáo giai đoạn thí nghiệm trước sửa. Source production sau đó đã được
cập nhật theo [báo cáo V3.1](120ask_fixes_20261020.md). Các số liệu bên dưới là
kết quả A/B ban đầu; notebook hiện so baseline V3 đóng băng với source đã sửa.

Đã thêm 6 cell code thí nghiệm vào `notebooks/check_120ask_50.ipynb`, ngay sau ô tổng hợp và trước ô ZIP. Notebook giữ cả baseline, bản sửa thử, kết quả A/B và báo cáo trong output. Source builder và helper cũng được cập nhật để build lại không mất các cell mới.

Kết luận kỹ thuật: nên sửa cả ba lỗi theo thứ tự **manual review → resume → media câu hỏi**. Bản sửa thử đạt toàn bộ 14 ca kiểm tra A/B; replay 1.000 HTML không đổi 775 candidate ID hoặc text, không đổi quyết định trang, đạt 9/9 regression. Chưa áp dụng patch vào parser/gate production.

## Kết quả thí nghiệm

| Thí nghiệm | Baseline đạt | Bản sửa thử đạt | Ý nghĩa |
|---|---:|---:|---|
| EXCLUDE + PARSER_ERROR, kèm kiểm stale provenance | 0/1 | 1/1 | Giữ nhãn lỗi và chuyển readiness thành NEEDS_PARSER_FIX |
| Resume: 7 biến thể dữ liệu/checkpoint | 2/7 | 7/7 | Từ chối nguồn đổi, bỏ qua nguồn không đổi, khôi phục raw output bị mất |
| Media: 6 dạng câu hỏi/template | 2/6 | 6/6 | Text thuần vẫn INCLUDE; ảnh chưa được giải quyết chuyển REVIEW |

Baseline FAIL ở những ca tái hiện lỗi là kết quả mong đợi của phép so sánh. Một dòng manual review gộp kiểm nhãn còn trong audit, readiness chặn lỗi và stale provenance bị từ chối. Đây là nhãn tổng hợp để kiểm tra luồng xử lý; không phải nhãn thẩm định nội dung của reviewer.

**Manual review:** dùng 44 trang thật, gồm cả chín regression và ít nhất 60 thread INCLUDE thông thường trước lấy mẫu. Cả hai phiên bản bắt đầu ở READY_FOR_FILTERED_PILOT. Khi gắn nhãn EXCLUDE + PARSER_ERROR cho thread `card1:reply960409`, source ID `1229338`, baseline làm mất dòng nhãn và vẫn báo PILOT. Bản sửa thử giữ dòng nhãn, trả NEEDS_PARSER_FIX; cả hai vẫn từ chối nhãn sai raw hash.

**Resume:** nguồn không đổi và raw hash nguồn sai là hai ca baseline đã xử lý đúng. Baseline thất bại khi đổi raw+hash, final URL, charset, HTTP status, hoặc xóa raw bản output. Bản sửa thử từ chối bốn kiểu thay đổi nguồn; source không đổi không parse lại; mất raw output thì parse lại từ source hợp lệ; hash nguồn sai bị chặn.

**Media:** baseline chỉ đạt text thuần và private placeholder. Ảnh y khoa, ảnh lazy-load, ảnh chưa rõ vai trò và ảnh trong fallback template đều bị INCLUDE. Bản sửa thử lưu URL/DOM locator/alt, chuyển cả bốn dạng đó sang REVIEW, đồng thời giữ hai hành vi đúng sẵn có.

## Tác động trên 1.000 HTML thật

| Chỉ số | Baseline | Bản sửa thử |
|---|---:|---:|
| Raw được kiểm hash và parse | 1.000 | 1.000 |
| Candidate document | 775 | 775 |
| Trang INCLUDE | 680 | 680 |
| Trang INCLUDE_PARTIAL | 95 | 95 |
| Trang REVIEW | 94 | 94 |
| Trang EXCLUDE | 131 | 131 |
| Regression đạt | 9/9 | 9/9 |
| Vi phạm kiểm tra audio fallback/legacy markup/corruption ở candidate | 0 | 0 |

Không có candidate ID thêm/bớt, không có candidate text thay đổi. Phát hiện 18 trang có media câu hỏi; các trang này đã được baseline chặn bởi privacy placeholder nên chưa làm thay đổi quyết định trong mẫu thật. Vì thế, kết quả không chứng minh mọi loại media ngoài mẫu đều đã được hỗ trợ.

## Nên fix thế nào

### 1. P1 — Giữ bằng chứng review và kiểm PARSER_ERROR trên toàn bộ nhãn hợp lệ

Trong `scripts/ask120_gate.py`, thêm mọi khóa nhãn đã có `reviewer_decision` vào tập review cần giữ. Tính `critical_manual` từ toàn bộ kết quả `load_manual()`, thay vì chỉ từ `review_rows` vừa chọn lại. Giữ kiểm raw/parser/policy hash và các hard blocker hiện tại.

Bản thử đã chứng minh thay đổi này sửa lỗi. Khi đưa vào production, nên lưu cohort review ban đầu theo run/parser/policy hash; nếu cần thêm mẫu INCLUDE thay thế thì bổ sung cohort, không xóa nhãn cũ. Thêm regression cho EXCLUDE + PARSER_ERROR, nhiều nhãn EXCLUDE liên tiếp, chạy tổng hợp lại và stale provenance. Không tự tạo nhãn reviewer thật.

### 2. P2 — Resume chỉ skip nếu bằng chứng nguồn và raw output vẫn hợp lệ

Trước khi `continue`, so `id`, `url`, `final_url`, `content_type`, `http_status`, `raw_sha256` giữa nguồn và checkpoint. Nếu khác, báo lỗi yêu cầu run mới để giữ provenance nhất quán. Kiểm hash raw bản output bên cạnh raw nguồn; output thiếu/hỏng thì tái tạo từ source đã xác thực.

Bản thử đã kiểm nhánh replay. Bản production cần áp dụng hợp đồng tương tự cho `crawl_new`, bổ sung test thay metadata, output raw hỏng, source raw thiếu và resume sau interrupt. Nếu cho phép reparse khi nguồn đổi thì phải cập nhật identity và mọi nhãn/downstream artifact có liên quan; hướng từ chối resume dễ kiểm chứng hơn.

### 3. P2 — Lưu media câu hỏi và review khi còn thiếu ngữ cảnh

Trong `scripts/ask120.py`, trích media từ chính question node đã nhận diện bằng cả selector chính và fallback, lưu URL, DOM locator và alt. Bản thử hỗ trợ `img/audio/video/source`, `src`, `data-src`, `data-original`. Gate đánh dấu `essential_media_missing` khi có question media, dùng reason `ESSENTIAL_MEDIA_REVIEW` hiện có ở cả replay và crawl.

Không mặc định coi ảnh có alt rỗng là trang trí. Nếu sau này muốn bỏ qua icon, cần bằng chứng template và test riêng. `srcset`, `picture` không có src, media CSS, ảnh nền và các kiểu lazy khác chưa được kiểm trong lần này; bổ sung theo mẫu quan sát thực tế. Đồng bộ field media mới vào raw auditor và sidecar, giữ schema Parquet production hiện tại. Không tải/phiên âm media trong bước fix này.

### 4. Kiểm tra sau khi sửa source

Đồng bộ snapshot bằng builder 120ask, đổi version/hợp đồng phù hợp với field và hành vi mới, dùng output run mới do parser/gate hash đổi. Chạy lại regression, bộ test 120ask và notebook replay. Các nhãn review cũ không được tự chuyển sang parser hash mới. Hoàn tất manual review trước khi xác nhận corpus đã duyệt; run thật hiện vẫn có 144 mục cần review và 0 nhãn.

## Cách dùng lại notebook

1. Để `MODE='replay'`, `RUN_EXPERIMENTS=True`, `EXPORT_CANDIDATE_CORPUS=True`.
2. Chọn ZIP đầu vào 1.000 URL, Restart & Run All. Bộ thí nghiệm cần đủ chín regression và ít nhất 50 thread INCLUDE thông thường.
3. Đọc kết quả tại các ô thí nghiệm 1–4 và ô báo cáo; ZIP cuối bao gồm thí nghiệm và `suggested.patch`.
4. Muốn chạy lại thí nghiệm trên run đang mở, chạy lại ô khởi tạo để tạo thư mục mới rồi chạy các ô thí nghiệm theo thứ tự. Không dùng thư mục thí nghiệm làm output/resume production.

Build lại notebook bằng `.venv\Scripts\python.exe -X utf8 scripts/build_120ask_gate_notebook.py`. Builder đọc `scripts/ask120_experiments.py`, nhúng helper và hash vào notebook; Kaggle không cần source repo để chạy thí nghiệm.

## Xác minh và artifact

- Bộ test 120ask hiện có: 28/28 đạt.
- Chạy riêng 16 test parser/gate hiện có với module candidate thay thế: 16/16 đạt. Các test snapshot vẫn kiểm nguồn production; candidate không được nhúng vào notebook production/domain.
- Cả lần đầu và bản cuối: 14/14 cell code hoàn tất, không có error output. Bản cuối được chạy lại sau khi bổ sung dependency Requests và diff tải về; đã validate nbformat, kiểm helper nhúng khớp source và kiểm toàn bộ ZIP (2.681 member, không lỗi CRC).
- Phạm vi: dữ liệu replay đã lưu; không crawl live, không upload, không thẩm định y khoa. Mọi request trong các cell thí nghiệm đều bị mock chặn và đếm; số lần thử request là 0.

Notebook được lưu kèm output tại `notebooks/check_120ask_50.ipynb`. Run bản cuối: `runs/ask120_gate_20261019T221240441581Z/`. Tên thư mục do runtime UTC sinh, không phải ngày ghi báo cáo theo giờ Việt Nam. Bên trong `experiments/ab_20261019T221321406844Z/` có `experiment_report.md`, `experiment_results.json`, `suggested.patch`, `suggested_patch/`, JSON A/B và audit media. Log thực thi: `tmp/120ask_experiment_notebook_execution_final.log`.

[Diff bản sửa thử](../../runs/ask120_gate_20261019T221240441581Z/experiments/ab_20261019T221321406844Z/suggested.patch) · [Kết quả JSON](../../runs/ask120_gate_20261019T221240441581Z/experiments/ab_20261019T221321406844Z/experiment_results.json) · [ZIP run](../../runs/ask120_gate_20261019T221240441581Z.zip).

Các file parser/gate production và notebook production/domain giữ nguyên. File check hiện được gitignore; builder và helper là phần source để tái tạo thay đổi này.
