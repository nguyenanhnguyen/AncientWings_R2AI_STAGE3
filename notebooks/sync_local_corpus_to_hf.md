# Đồng bộ corpus local lên Hugging Face

Script: [`sync_local_corpus_to_hf.py`](sync_local_corpus_to_hf.py). Chạy lệnh từ thư mục gốc dự án.
Repo mặc định: `AncientWings/AncientWings_R2AI_STAGE3_ds`, nhánh `main`, loại `dataset`.
Cấu trúc và schema Parquet dựa trên mục 10 của `crawl_corpus_kaggle_hf_upload.ipynb`.

## Cài đặt và chạy

Chỉ cần PyArrow và Hugging Face Hub, không cần Torch/GPU:

```powershell
python -m pip install pyarrow "huggingface_hub>=0.34,<3"
hf auth login
```

Nhập token có quyền đọc/ghi dataset đích khi CLI yêu cầu. Có thể dùng biến môi trường `HF_TOKEN` đã thiết lập thay cho login. Không ghi token vào script hoặc Git.

Thử với tối đa 100 record mới; lệnh này đọc HF, kiểm tra dữ liệu và đóng gói local nhưng **chưa upload**:

```powershell
python notebooks\sync_local_corpus_to_hf.py --max-new 100
```

Upload toàn bộ record mới tìm được:

```powershell
python notebooks\sync_local_corpus_to_hf.py --push
```

Chạy lại chính lệnh trên để đồng bộ lần tiếp theo. Script đọc lại corpus HF tại một commit cố định, bỏ qua ID đã có cùng URL và `text_sha256`. Không cần nhớ số lượng đã upload. Nếu mạng lỗi giữa các đợt, đợt đã commit được giữ lại; chạy lại để làm tiếp.

Mặc định quét `nguyen\output` và `nguyen\shards`, tìm các thư mục có `manifest.json` + `records\`. Nếu máy dùng tên thư mục khác, chỉ định:

```powershell
python notebooks\sync_local_corpus_to_hf.py --sources nguyen\output nguyen\shard\output --push
```

Hoặc chỉ một run:

```powershell
python notebooks\sync_local_corpus_to_hf.py --sources nguyen\output\runs\batch01_nguyen --push
```

Kiểm tra offline khi chưa cài/đăng nhập HF:

```powershell
python notebooks\sync_local_corpus_to_hf.py --local-only --max-new 10
```

Chế độ offline chưa biết ID trên HF, nên số record mới chỉ có ý nghĩa trong local.

## Dữ liệu nào được hợp nhất?

- Chỉ record `status=extracted`, `quality_status=accepted`, text không rỗng được đưa vào corpus, giống chính sách `accepted_only` của notebook. `review`, `rejected` và crawl lỗi vẫn ở local.
- Có thể chạy khi crawler còn hoạt động. Script chụp nội dung các record đọc được; JSON đang ghi/hỏng được ghi vào `deferred.jsonl` để kiểm tra và thử lại ở lần sau. Đây không phải snapshot nguyên tử của toàn bộ run.
- Kiểm tra ID/URL với `data\links_corpus.parquet` đúng SHA-256 của notebook; kiểm tra hash text và raw giải nén, kiểm tra Parquet đọc lại khớp dữ liệu đã ghi. Các kiểm tra này xác nhận tính toàn vẹn, không chấm độ đúng y khoa hoặc đầy đủ nội dung.
- Cùng ID + URL + hash text: bỏ qua. Cùng ID nhưng URL/text khác: ghi `conflicts.jsonl` và dừng trước upload mới để người dùng chọn bản phù hợp. Không tự ghi đè, không tự chọn bản crawl mới nhất. Metadata khác nhưng URL/text giống nhau được xem là đã đồng bộ.
- Hai ID khác nhau nhưng text giống nhau vẫn giữ hai ID nguồn. Nếu HF đã có ID trùng từ notebook cũ, script không xóa hoặc viết lại các shard đó.

Mỗi đợt mặc định có tối đa 1.000 record accepted mới:

```text
corpus/local-nguyen_<min_id>_<max_id>_<hash>.parquet
corpus_jsonl/local-nguyen_<min_id>_<max_id>_<hash>.jsonl
archives/local-nguyen_<min_id>_<max_id>_<hash>.zip
manifests/local-nguyen_<min_id>_<max_id>_<hash>/notebook_manifest.json
manifests/local-nguyen_<min_id>_<max_id>_<hash>/upload_manifest.json
```

Hợp nhất ở đây là bổ sung shard vào `corpus/`. Khi đọc toàn bộ `corpus/*.parquet`, dữ liệu mới cùng tồn tại với shard Kaggle cũ; không tạo một file `merged.parquet` hoặc sửa dataset card. Chọn glob `corpus/*.parquet` rõ ràng khi nạp, tránh đọc cả JSONL/manifest vào corpus.

Mỗi shard được commit cùng các artifact của nó. Script truyền `parent_commit` để phát hiện repo thay đổi trong lúc đồng bộ; khi người khác vừa upload, chạy lại để kiểm tra trùng ID trên phiên bản mới. Cơ chế này bảo vệ lượt upload của script; các uploader khác cũng cần kiểm tra ID để tránh tự thêm trùng sau đó. Tham khảo [HF create_commit](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#huggingface_hub.HfApi.create_commit).

## ZIP và tài nguyên local

### Khi báo Conflicting IDs

Cùng ID và URL có thể có text khác vì thời điểm crawl hoặc cách trích xuất khác nhau. Hash khác không tự chứng minh bản nào tốt hơn. Mặc định script dừng; có thể chọn giữ bản trên HF và chỉ bổ sung ID mới:

```powershell
python notebooks\sync_local_corpus_to_hf.py --max-new 100 --on-conflict keep-remote
python notebooks\sync_local_corpus_to_hf.py --push --on-conflict keep-remote
```

Các bản local bị bỏ qua vẫn nằm nguyên trong output crawl; `conflicts.jsonl` ghi `action=keep_remote` để review sau. Không ghi đè corpus HF. Xung đột URL hoặc giữa hai bản local chưa có trên HF vẫn chặn upload. `conflicts_kept_remote` là số bản đã xử lý theo lựa chọn này, không phải số bản đã upload.

ZIP chứa **records và raw liên quan của các record mới trong đợt này**, cùng corpus và manifest. Record nguyên bản được lưu dưới `sources/<namespace>/records/`; các đường dẫn raw trong corpus được thêm namespace tương ứng để phân biệt các run. Giải nén ZIP để truy vết raw theo `raw_path`.

Đây là archive snapshot accepted, **không đủ để resume toàn bộ crawler** như full ZIP của notebook Kaggle. Manifest ghi rõ `snapshot_scope=new_accepted_records_only`, `full_crawl_resume_supported=false`; `pending=0` chỉ mô tả snapshot, không có nghĩa run local đã crawl xong. Không tạo diagnostics ZIP và không chạy lại audit DOM/review của notebook. Muốn backup/resume toàn run, tiếp tục giữ full output và ZIP của crawler riêng.

Preview cũng đóng gói dữ liệu và cần dung lượng đĩa. Tất cả cache HF, SQLite, báo cáo và staging ở `work\hf_local_sync\` (đã nằm trong `.gitignore`). Lần đầu phải tải các Parquet trong `corpus/` về để xác định ID trùng; không tải ZIP HF. Các lần sau dùng cache blob của HF. Raw đã nén gzip được đưa vào ZIP không nén lại. Không dùng GPU.

Tùy chọn hữu ích:

| Cờ | Tác dụng |
| --- | --- |
| `--max-new 100` | Chỉ lấy tối đa 100 record mới; báo cáo không phải thống kê toàn bộ nguồn |
| `--batch-size 5000` | Tối đa 5.000 record mỗi shard/commit |
| `--prefix local-minh` | Nhãn tên shard cho thành viên khác |
| `--out D:\hf_sync_work` | Chuyển cache/staging sang ổ khác; đặt ngoài thư mục crawl |
| `--no-archive` | Chỉ upload corpus/manifest; raw vẫn kiểm tra hash nhưng chỉ giữ local |
| `--no-jsonl` | Chỉ xuất corpus Parquet, bỏ bản JSONL |
| `--source-parquet PATH` | Đường dẫn khác tới nguồn gốc đã chốt hash |

Xem `sync_result.json` cho số lượng và các commit thành công; `conflicts.jsonl` cho ID cần xử lý; `deferred.jsonl` cho record chưa đọc được. Các báo cáo được tạo lại mỗi lần chạy. Staging/cache được giữ lại, không tự xóa output hoặc dữ liệu HF.

## Kiểm tra offline

```powershell
python -m unittest discover -s notebooks -p test_sync_local_corpus_to_hf.py
```

Các test kiểm tra trùng/xung đột ID, JSON chưa ghi xong, raw hỏng, đường dẫn raw, archive truy vết, schema HF và commit đồng thời. Không upload dữ liệu thật.
