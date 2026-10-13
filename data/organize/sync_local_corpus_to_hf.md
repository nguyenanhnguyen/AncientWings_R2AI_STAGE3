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
python data\organize\sync_local_corpus_to_hf.py --max-new 100
```

Upload toàn bộ record mới tìm được:

```powershell
python data\organize\sync_local_corpus_to_hf.py --push
```

Chạy lại chính lệnh trên để đồng bộ lần tiếp theo. Script đọc lại corpus HF tại một commit cố định, bỏ qua ID đã có cùng URL và `text_sha256`. Không cần nhớ số lượng đã upload. Nếu mạng lỗi giữa các đợt, đợt đã commit được giữ lại; chạy lại để làm tiếp.

Mặc định quét `nguyen\output` và `nguyen\shards`, tìm các thư mục có `manifest.json` + `records\`. Nếu máy dùng tên thư mục khác, chỉ định:

```powershell
python data\organize\sync_local_corpus_to_hf.py --sources nguyen\output nguyen\shards --push
```

Hoặc chỉ một run:

```powershell
python data\organize\sync_local_corpus_to_hf.py --sources nguyen\output\runs\batch01_nguyen --push
```

Kiểm tra offline khi chưa cài/đăng nhập HF:

```powershell
python data\organize\sync_local_corpus_to_hf.py --local-only --max-new 10
```

Chế độ offline chưa biết ID trên HF, nên số record mới chỉ có ý nghĩa trong local.

## Danh sách chính thức của BTC đã đổi (13/10/2026)

BTC thay `links_corpus.parquet` (4.394.718 dòng) bằng `links_corpus_vi_en_zh.parquet` (1.220.598 dòng), tại revision `71be0e12` của `AIGuruTinix/ViBioMIR`. Đối chiếu hai file:

| | Số lượng |
|---|---:|
| id cũ được giữ, **URL y hệt** | 980.598 |
| id cũ bị bỏ | 3.414.120 |
| id mới hoàn toàn | 240.000 |
| id bị đổi URL | 0 |

Vì không có id nào bị đổi URL, cặp (id, url) là khóa an toàn để đối chiếu.

**Chỉ sync bản ghi khớp cả id lẫn URL.** Script nạp danh sách chính thức vào bảng `official` trong `plan.sqlite`, rồi loại mọi bản ghi không khớp trước khi lên kế hoạch upload. Hai lý do loại được đếm riêng trong `sync_result.json` và ghi chi tiết ở `not_official.jsonl`:

- `id_not_in_official_list`: id không còn trong danh sách mới.
- `url_differs`: id còn nhưng URL trong bản ghi khác URL chính thức.

**Run crawl cũ vẫn dùng được.** `manifest.json` của mỗi run ghi lại danh sách nó được lập kế hoạch theo. Run chốt theo `links_corpus.parquet` (đã nghỉ) vẫn được nhận, vì mọi bản ghi đều bị kiểm tra lại theo danh sách hiện hành. Danh sách đã nghỉ nằm trong `RETIRED_SOURCE_SHA256`; một sha lạ vẫn bị từ chối.

Đo trên dữ liệu crawl hiện có (13/10): batch01 còn 154.835/154.843 bản ghi hợp lệ (100%), shard_01 còn 3.235/120.835 (2,7%), shard_02 còn 12.310/135.100 (9,1%). Hai shard chủ yếu là trang Trung Quốc mà BTC đã bỏ khỏi danh sách.

## Dọn dữ liệu đã lên HF: `prune_hf_corpus.py`

Sync chỉ chặn dữ liệu mới. Dữ liệu đã upload trước ngày BTC đổi danh sách phải dọn bằng công cụ riêng:

```powershell
# Xem trước: tải các shard corpus, không sửa gì trên Hub
python data\organize\prune_hf_corpus.py

# Áp dụng
python data\organize\prune_hf_corpus.py --apply
```

Với mỗi `corpus/<name>.parquet`:

| Tình huống | Xử lý |
|---|---|
| Mọi dòng đều hợp lệ | Không chạm tới, không upload lại |
| Một phần bị loại | Ghi lại shard chỉ còn dòng hợp lệ (giữ nguyên schema và thứ tự dòng); `corpus_jsonl/<name>.jsonl` được **sinh lại từ các dòng đó** (nên không phải tải 5 GiB JSONL về); hai manifest trong `manifests/<name>/` được cập nhật số lượng, khoảng id, hash file và thêm mục `pruning` |
| Mọi dòng bị loại | Xóa shard, jsonl và manifest của nó |

Tên file giữ nguyên dạng `ids_<min>_<max>_synced` dù khoảng id co lại, để các báo cáo cũ còn tra được; manifest ghi cả khoảng cũ (`pruning.id_range_before`) và khoảng mới.

`archives/<name>.zip` là bằng chứng raw, **mặc định không bị sửa** và chỉ được báo cáo, vì rewrite ZIP phải tải về hàng GB. Dùng `--archives delete` để xóa archive của các shard bị sửa. `code/`, `inputs/`, `diagnostics/`, `teach/` không bị chạm tới.

Các tùy chọn khác: `--shards-per-commit` (mặc định 20 shard mỗi commit), `--limit-shards N` (chỉ xem N shard đầu, để thử), `--attempts`, `--out`. Mỗi commit ghim `parent_commit`, nên nếu người khác vừa push thì script dừng và yêu cầu chạy lại để lập kế hoạch trên revision mới; các commit đã xong được giữ. Chạy lại an toàn: shard đã dọn sẽ hiện là `unchanged`.

Báo cáo: `work\hf_prune\prune_result.json` (kế hoạch và các commit) và `removed_records.jsonl` (mỗi bản ghi bị xóa một dòng, kèm lý do).

Đo thử ngày 13/10 trên 6 shard đầu: 43.782 bản ghi, giữ 23.060, xóa 20.722; 2 shard không đổi, 4 shard phải ghi lại.

## Dữ liệu nào được hợp nhất?

- Chỉ record `status=extracted`, `quality_status=accepted`, text không rỗng được đưa vào corpus, giống chính sách `accepted_only` của notebook. `review`, `rejected` và crawl lỗi vẫn ở local.
- Có thể chạy khi crawler còn hoạt động. Script chụp nội dung các record đọc được; JSON đang ghi/hỏng được ghi vào `deferred.jsonl` để kiểm tra và thử lại ở lần sau. Đây không phải snapshot nguyên tử của toàn bộ run.
- Kiểm tra ID/URL với danh sách chính thức hiện hành `data\links_corpus_vi_en_zh.parquet` (đúng SHA-256 đã chốt); bản ghi có id không còn trong danh sách, hoặc có id nhưng URL khác, bị **bỏ khỏi đợt sync** và ghi vào `not_official.jsonl`. Trước khi upload còn một cửa chặn cuối (`verify_source`) đối chiếu lại toàn bộ kế hoạch với danh sách đó; kiểm tra hash text và raw giải nén, kiểm tra Parquet đọc lại khớp dữ liệu đã ghi. Các kiểm tra này xác nhận tính toàn vẹn, không chấm độ đúng y khoa hoặc đầy đủ nội dung.
- Cùng ID + URL + hash text: bỏ qua. Cùng ID nhưng URL/text khác: ghi `conflicts.jsonl` và dừng trước upload mới để người dùng chọn bản phù hợp. Không tự ghi đè, không tự chọn bản crawl mới nhất. Metadata khác nhưng URL/text giống nhau được xem là đã đồng bộ.
- Hai ID khác nhau nhưng text giống nhau vẫn giữ hai ID nguồn. Nếu HF đã có ID trùng từ notebook cũ, script không xóa hoặc viết lại các shard đó.

Mỗi đợt mặc định có tối đa 1.000 record accepted mới:

```text
corpus/ids_<min_id>_<max_id>_synced.parquet
corpus_jsonl/ids_<min_id>_<max_id>_synced.jsonl
manifests/ids_<min_id>_<max_id>_synced/notebook_manifest.json
manifests/ids_<min_id>_<max_id>_synced/upload_manifest.json
```

Hợp nhất ở đây là bổ sung shard vào `corpus/`. Khi đọc toàn bộ `corpus/*.parquet`, dữ liệu mới cùng tồn tại với shard Kaggle cũ; không tạo một file `merged.parquet` hoặc sửa dataset card. Chọn glob `corpus/*.parquet` rõ ràng khi nạp, tránh đọc cả JSONL/manifest vào corpus.

Mặc định không tạo/upload `archives/*.zip`; records/raw vẫn được kiểm tra hash và giữ ở thư mục crawl local. Chỉ thêm ZIP lên HF khi chủ động dùng `--archive`. Notebook Kaggle cũng mặc định `HF_UPLOAD_ARCHIVE = False` nhưng vẫn tạo ZIP checkpoint trong Output.

Mỗi shard được commit cùng các artifact của nó. Script truyền `parent_commit` để phát hiện repo thay đổi trong lúc đồng bộ; khi người khác vừa upload, chạy lại để kiểm tra trùng ID trên phiên bản mới. Cơ chế này bảo vệ lượt upload của script; các uploader khác cũng cần kiểm tra ID để tránh tự thêm trùng sau đó. Tham khảo [HF create_commit](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#huggingface_hub.HfApi.create_commit).

## ZIP và tài nguyên local

### Khi báo Conflicting IDs

Cùng ID và URL có thể có text khác vì thời điểm crawl hoặc cách trích xuất khác nhau. Hash khác không tự chứng minh bản nào tốt hơn. Mặc định script dừng; có thể chọn giữ bản trên HF và chỉ bổ sung ID mới:

```powershell
python data\organize\sync_local_corpus_to_hf.py --max-new 100 --on-conflict keep-remote
python data\organize\sync_local_corpus_to_hf.py --push --on-conflict keep-remote
```

Các bản local bị bỏ qua vẫn nằm nguyên trong output crawl; `conflicts.jsonl` ghi `action=keep_remote` để review sau. Không ghi đè corpus HF. Xung đột URL hoặc giữa hai bản local chưa có trên HF vẫn chặn upload. `conflicts_kept_remote` là số bản đã xử lý theo lựa chọn này, không phải số bản đã upload.

Khi bật `--archive`, ZIP chứa **records và raw liên quan của các record mới trong đợt này**, cùng corpus và manifest. Record nguyên bản được lưu dưới `sources/<namespace>/records/`; các đường dẫn raw trong corpus được thêm namespace tương ứng để phân biệt các run. Giải nén ZIP để truy vết raw theo `raw_path`.

Đây là archive snapshot accepted, **không đủ để resume toàn bộ crawler** như full ZIP của notebook Kaggle. Manifest ghi rõ `snapshot_scope=new_accepted_records_only`, `full_crawl_resume_supported=false`; `pending=0` chỉ mô tả snapshot, không có nghĩa run local đã crawl xong. Không tạo diagnostics ZIP và không chạy lại audit DOM/review của notebook. Muốn backup/resume toàn run, tiếp tục giữ full output và ZIP của crawler riêng.

Preview cũng đóng gói dữ liệu và cần dung lượng đĩa. Tất cả cache HF, SQLite, báo cáo và staging ở `work\hf_local_sync\` (đã nằm trong `.gitignore`). Lần đầu phải tải các Parquet trong `corpus/` về để xác định ID trùng; không tải ZIP HF. Các lần sau dùng cache blob của HF. Raw đã nén gzip được đưa vào ZIP không nén lại. Không dùng GPU.

Tùy chọn hữu ích:

| Cờ | Tác dụng |
| --- | --- |
| `--max-new 100` | Chỉ lấy tối đa 100 record mới; báo cáo không phải thống kê toàn bộ nguồn |
| `--batch-size 5000` | Tối đa 5.000 record mỗi shard/commit |
| `--out D:\hf_sync_work` | Chuyển cache/staging sang ổ khác; đặt ngoài thư mục crawl |
| `--archive` | Chủ động tạo/upload ZIP raw/records lên HF; mặc định tắt |
| `--no-archive` | Giữ mặc định chỉ upload corpus/manifest; raw vẫn kiểm tra hash local |
| `--no-jsonl` | Chỉ xuất corpus Parquet, bỏ bản JSONL |
| `--source-parquet PATH` | Đường dẫn khác tới danh sách chính thức (mặc định `data\links_corpus_vi_en_zh.parquet`) |

Xem `sync_result.json` cho số lượng và các commit thành công; `conflicts.jsonl` cho ID cần xử lý; `deferred.jsonl` cho record chưa đọc được. Các báo cáo được tạo lại mỗi lần chạy. Staging/cache được giữ lại, không tự xóa output hoặc dữ liệu HF.

## Kiểm tra offline

```powershell
python -m unittest discover -s data/organize -p test_sync_local_corpus_to_hf.py
```

Các test kiểm tra trùng/xung đột ID, JSON chưa ghi xong, raw hỏng, đường dẫn raw, archive truy vết, schema HF và commit đồng thời. Không upload dữ liệu thật.

## Chuẩn hóa tên các đợt sync cũ

Các lượt sync mới dùng `ids_<min_id>_<max_id>_synced`, cùng mẫu với notebook Kaggle. Hai ID là min/max thực sự có trong shard; không ngụ ý có đủ mọi ID ở giữa. `--prefix` cũ đã bỏ. Khi tên đích đã tồn tại, script dừng để tránh ghi đè.

Để đổi tên các đợt `local-nguyen_..._<hash>` (hoặc prefix tùy chỉnh cũ) đã có trên HF, chạy công cụ riêng. Nên kết thúc các lượt sync/upload khác trước khi áp dụng:

```powershell
# Chuẩn bị và xem kế hoạch, chưa thay đổi HF
python data\organize\normalize_hf_corpus_names.py

# Áp dụng đổi tên trên HF
python data\organize\normalize_hf_corpus_names.py --apply
```

Công cụ chỉ xử lý các snapshot do script sync local tạo theo mẫu tên cũ; các đợt notebook đã đúng tên và đợt recovery được giữ nguyên. Nó đổi tên Parquet, JSONL, ZIP, diagnostics nếu có, thư mục manifests; cập nhật `run_name`, `path_in_repo`, tên thư mục trong ZIP và hash/size artifact đã thay đổi. ID, URL và text corpus được giữ nguyên. Tên run gốc trong `parent_runs` giữ nguyên để truy vết.

Các tên cũ được bỏ khỏi nhánh hiện tại trong cùng commit tạo tên mới; lịch sử Git HF vẫn còn. Corpus Parquet/JSONL dùng thao tác copy của Hub; ZIP phải tải về, sửa nội dung tên bên trong rồi upload lại. Mỗi đợt đổi tên là một commit có kiểm tra phiên bản cha. Nếu repo thay đổi hoặc mất kết nối, chạy lại để dựng kế hoạch mới; đợt đã đổi tên thành công được bỏ qua. Khi hai tên cũ cùng trở thành một tên đích hoặc đích đã tồn tại, công cụ dừng trước commit.

Cache, ZIP đã chuẩn hóa và báo cáo nằm ở `work\hf_name_normalization\` trên ổ dự án; cần dung lượng cho cả ZIP cũ và mới. Lệnh preview cũng chuẩn bị ZIP để kiểm tra. Công cụ không đổi tên file trong cache do HF quản lý, không sửa thư mục crawler hoặc lịch sử log cũ.

Nếu cần bản staging local có tên mới (không đụng HF):

```powershell
python data\organize\normalize_hf_corpus_names.py --local-staging work\hf_local_sync\staging
python data\organize\normalize_hf_corpus_names.py --local-staging work\hf_local_sync\staging --apply
```

Chế độ này tạo các thư mục staging tên mới, giữ nguyên thư mục tên cũ làm backup. Báo cáo kế hoạch ở `work\hf_name_normalization\local_rename_plan.json`; không chạy đồng thời với sync đang ghi staging. Nếu tên đích đã tồn tại, dừng để người dùng kiểm tra.
