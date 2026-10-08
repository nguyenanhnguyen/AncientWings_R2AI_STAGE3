# Nghiên cứu dữ liệu và truy xuất phân cấp cho ViBioMIR

**Ngày nghiên cứu:** 2026-10-08  
**Phạm vi:** corpus crawl ViBioMIR, truy vấn tiếng Việt, tìm tài liệu và đoạn trích nguyên văn cho R2AI.  
**Mục đích:** context lâu dài cho các lần nghiên cứu data/retrieval tiếp theo. Đây là tổng hợp nghiên cứu và kế hoạch kiểm chứng, không khẳng định đề xuất nào đã tăng điểm.

## Kết luận điều hành

Dự án có baseline hybrid: BM25 + dense embeddings → RRF → cross-encoder rerank. Tầng đáng nghiên cứu thêm là **retrieval phân cấp document → section → evidence span**, kết hợp metadata y khoa đa nhãn như bệnh/chủ đề, triệu chứng, nguyên nhân, xét nghiệm/chẩn đoán, điều trị, thuốc/an toàn, phòng tránh và tiên lượng.

Dùng facet như **tín hiệu tìm kiếm mềm**: giữ query gốc và global retrieval, thêm kênh theo facet khi query có nhiều ý định, rồi merge/deduplicate/rerank. Không hard-filter theo một nhãn duy nhất: query y khoa thường hỏi nhiều khía cạnh, và phân loại sai có thể loại mất tài liệu đúng trước khi reranker nhìn thấy.

Không có kích thước chunk tối ưu phổ quát. Benchmark phải dùng đúng nhãn/metric của cuộc thi, cùng query split và candidate budget. Kết quả ROUGE của một tác vụ LegalQA sinh câu trả lời không thể trực tiếp xác định chunk tốt cho tác vụ retrieval trích xuất hiện tại.

## Dữ liệu và code hiện tại

### Query

- `data/query.parquet`: 1.200 dòng (`id: int64`, `query: string`).
- Các query là câu hỏi sức khỏe tiếng Việt, độ dài và số ý rất khác nhau. Đo trực tiếp trên file: median khoảng 81 ký tự, p95 khoảng 365, max khoảng 1.243.
- Có câu ngắn một ý (“Răng có lỗ chấm đen, chảy máu khi thức dậy là sao?”) và câu dài nêu bệnh nền, triệu chứng, thuốc, kết quả hoặc lo ngại. Vì thế decomposition chỉ nên áp dụng có điều kiện cho query dài/nhiều ý.
- Facet ban đầu nên multi-label: disease/topic; symptom/sign; cause/risk; diagnosis/test interpretation; treatment/intervention; drug/safety; prevention/transmission/vaccination; prognosis/complication; care-seeking. Đây là taxonomy cần được người gán nhãn kiểm tra, không phải nhãn có sẵn trong dataset.

### Corpus và snapshot 60k

- `data/links_corpus.parquet` là ID/URL nguồn; giữ nguyên ID gốc đến submission.
- `work/rtx2050_60k/corpus/prepare_manifest.json`: 60.000 record đầu vào, giữ 57.563 tài liệu; 56.990 accepted, 573 review; loại 2.437 (2.238 homepage redirect, 102 unsupported content, 89 template, 8 HTTP error). Snapshot này được nhận diện toàn tiếng Việt.
- `work/rtx2050_60k/chunks/chunk_manifest.json`: 224.939 chunks, trung bình 3,91/tài liệu, median 287 token theo bộ đếm nội bộ, p95 319, max 740. Profile pipeline đặt target 320, overlap 80, max 768. CLI chunker nếu chạy riêng mặc định overlap 64/max 1024.
- `prepare.py` lưu `title` tách khỏi body `text`; chưa tạo taxonomy/facet hay cấu trúc semantic riêng.
- `chunk.py` hiện dùng paragraph-aware sliding windows: tách theo dòng trống, gộp paragraph đến cỡ target với overlap; paragraph dài được chia theo dấu câu, cuối cùng hard-cut nếu cần. Lưu `char_start/char_end` và `text` là span liên tục từ nguồn. Title metadata được dùng cho retrieval nhưng không ghép vào text nộp.
- `index/` tạo BM25 và dense vectors; `retrieval/run.py` hợp nhất ứng viên, rerank rồi ghi candidates. Pipeline 60k là indexing/inference, không cập nhật trọng số model.

## Metric thi và hệ quả với chunking

Theo `docs/note/RULE.txt`, điểm document-level và chunk-level dùng Precision/Recall/F2 macro-average trên query. Chunk được tính đúng nếu LCS token sau chuẩn hóa giữa chunk nộp và ít nhất một reference chunk **cùng query, cùng doc_id** đạt ≥40% chiều dài reference.

Hệ quả:

- Document retrieval cần Recall tốt; sai ở tầng coarse không thể được passage reranker cứu.
- Chunk quá nhỏ có thể không đạt 40% reference; chunk quá rộng đưa thêm nội dung ngoài bằng chứng và có thể làm giảm precision.
- Bài nộp cần đoạn nguồn nguyên văn. Summary/label/heading tổng hợp có thể làm metadata để tìm, không thay thế span nguồn.
- Đánh giá chunking không chỉ bằng “đoạn đọc có vẻ hợp lý”; phải chạy proxy metric chính thức trên nhãn dev.

## Kỹ thuật có cơ sở để nghiên cứu

### 1. Hierarchical document → passage retrieval

Tạo document card gồm title, intro ngắn, domain, heading/section path, thực thể (bệnh/thuốc/xét nghiệm), facet nhiều nhãn và chất lượng crawl. Lấy ứng viên tài liệu bằng BM25 + title/document vector; sau đó tìm passage/section trong các tài liệu đó. Giữ thêm một global child-level retrieval channel và merge hai pool để bảo vệ recall.

Điểm mạnh tiềm năng: passage được hiểu trong ngữ cảnh tài liệu, truy vấn chủ đề tổng quát tìm được tài liệu trước khi phải khớp đúng một đoạn nhỏ, và reranker có thể chạy trên ít cặp hơn. Rủi ro: coarse-stage recall thấp sẽ mất tài liệu đúng; cần đo document Recall@K trước khi tối ưu tốc độ.

### 2. Section/facet-aware soft routing

Nếu extractor giữ heading, lưu `section_path` riêng và ưu tiên ranh giới heading → paragraph → sentence khi tạo evidence spans. Có thể index title/heading/facet như field hoặc prefix cho retrieval, nhưng giữ raw source span tách biệt để nộp chính xác.

Tạo các query view bổ sung có kiểm soát, ví dụ “triệu chứng và dấu hiệu”, “diễn giải xét nghiệm”, “điều trị và an toàn”, chỉ khi có bằng chứng query chứa các ý đó. Giữ query gốc làm kênh chính. Merge bằng RRF hoặc trọng số được tune trên dev; không để model tự thêm facts ngoài query.

### 3. Variable granularity, không chọn một con số theo cảm tính

Benchmark source-aware chunks ở các dải khoảng 200, 320 và 500 internal tokens, overlap theo paragraph/sentence; so với current 320/80. Dải này là ứng viên thử nghiệm, không phải đáp án tối ưu. Thêm variant FAQ answer-sized nếu cấu trúc nguồn cho phép nhận diện cặp câu hỏi–trả lời.

Parent document/section có thể lớn để search/coarse context; child evidence span nhỏ hơn để định vị/nộp. Đây là một dạng hierarchy hữu ích hơn việc ép mỗi tài liệu thành một kích thước duy nhất. Giới hạn số chunk tương tự trên một tài liệu để tránh các overlap trùng lặp làm giảm precision.

### 4. Conditional query decomposition

Tách query nhiều câu/điều kiện thành các facet độc lập (ví dụ triệu chứng + khả năng nguyên nhân + phải làm gì), chạy retrieval cho từng facet, union và khử trùng, rồi rerank. Query một câu đơn giản đi thẳng qua đường thường. Decomposition có thể tăng coverage nhưng cũng sinh nhiễu và thêm latency; đo lợi ích trên query nhiều ý riêng, không áp dụng mù quáng cho toàn bộ 1.200 query.

### 5. Dữ liệu huấn luyện nếu sau này làm student

Nếu huấn luyện retriever/reranker: cần cặp query–evidence được người gán nhãn hoặc dữ liệu ngoài được phép dùng. Hard negatives nên lấy từ cả BM25 và dense retrievers; nếu chỉ lấy một kênh, student có thể yếu trước kênh kia. Synthetic doc2query/facet labels là augmentation để tìm kiếm, không phải nhãn đánh giá độc lập. Tách human dev, pseudo/teacher train và official test rõ ràng.

## Vì sao LegalQA 450 từ/ROUGE không chuyển trực tiếp

- Từ, token model, câu và paragraph không cùng đơn vị; số “450 từ” có độ dài token thay đổi.
- Luật thường có cấu trúc điều/khoản/điểm rõ. Trang sức khỏe web có thể là bài báo, FAQ, danh sách, trang template hoặc extractor đã làm phẳng heading.
- ROUGE cho câu trả lời sinh ra khác metric retrieval của cuộc thi này (document/chunk F2 và LCS span). Điểm ROUGE thấp có thể đến từ generation, reference, truy hồi, split hoặc decoding; không chứng minh một mình chunking sai.
- Chunk dài thường tăng cơ hội phủ reference nhưng có thể làm precision kém; chunk ngắn có thể chọn đúng trọng tâm nhưng hụt ngưỡng LCS. Chỉ nhãn dev mới xác định trade-off trên bộ này.

RAPTOR-style generated summaries có thể hữu ích làm lớp điều hướng chủ đề, nhưng summary không phải đoạn evidence nguồn và có thể bỏ chi tiết y khoa. Nếu thử, chỉ dùng summary/tree nội bộ để chọn document/section, rồi lấy child span nguyên văn để rerank/nộp.

## Quy trình đánh giá khuyến nghị

### Nhãn dev và bảo vệ test

Tạo một dev set do người gán nhãn, phân tầng theo query ngắn/dài, 1 ý/nhiều ý, facet, domain/answerability. Nhãn tối thiểu: doc IDs liên quan, evidence span/chunk, facet cần phủ, confidence. Hai người gán và phân xử một tập con giúp đo độ đồng thuận. Chia theo query; pseudo labels/teacher outputs không được xem như ground truth độc lập. Không dùng hidden/private labels để train hoặc tune.

### Baseline và error analysis

Ghi macro document Recall@K, chunk Recall@K theo đúng ngưỡng LCS, Precision/F2 ở cutoff nộp, MRR/nDCG, số cặp rerank, latency/query và VRAM. Phân loại lỗi: tài liệu đúng chưa crawl; doc retrieval miss; tìm đúng doc sai section/chunk; chunk quá hẹp/rộng; facet bị bỏ sót; text lỗi mã hóa/trích xuất. Reranker không thể khôi phục evidence không lọt qua first-stage pool.

### Ablation có kiểm soát

| Thử nghiệm | Thay đổi | Câu hỏi |
|---|---|---|
| A | Baseline 320/80 hiện tại | Mốc tái lập |
| B | Heading/paragraph/sentence boundaries, cùng budget | Giữ cấu trúc nguồn có ích không? |
| C | Child 200/320/500 tokens | Recall–precision theo metric chunk thi |
| D | BM25+vector trên document title/intro, hợp nhất child retrieval | Coarse doc signal có giúp tìm đúng nguồn không? |
| E | Section path/title chain trong metadata/vector | Ngữ cảnh chủ đề cải thiện định vị passage không? |
| F | Facet multi-label, soft query channels, global channel giữ nguyên | Routing có tăng Recall mà không loại doc đúng? |
| G | Decomposition chỉ cho query nhiều ý | Coverage có đáng chi phí/nhiễu không? |
| H | Doc top-K → child top-K → rerank union | Giảm số cặp rerank mà vẫn giữ recall không? |
| I | Parent-child hoặc late chunking embeddings | Ngữ cảnh rộng có đáng compute không? |

Mỗi lần chỉ đổi một yếu tố. Giữ corpus snapshot, query split, metric implementation và candidate budget cố định. Ghi cả recall trước rerank, chất lượng sau rerank và thời gian.

### Thứ tự triển khai nghiên cứu

1. Audit data trước: mojibake/encoding tiếng Việt, title/body, heading/FAQ preservation, duplicates/template, domain coverage, accepted/review.
2. Thử chunk boundaries theo cấu trúc nguồn và multi-granularity trên 1 phần corpus cố định.
3. Thêm document-level index và so Recall@K; giữ global passage channel.
4. Tạo facet annotations sidecar multi-label và query expansion có điều kiện; audit false negatives do routing.
5. Chỉ sau đó thử teacher doc2query/student fine-tune; training data, dev labels và official query test phải tách biệt.

## Nghiên cứu đã đọc (nguồn gốc)

1. [Dense Hierarchical Retrieval for Open-domain QA, Findings EMNLP 2021](https://aclanthology.org/2021.findings-emnlp.19/) — document retriever rồi passage retriever; dùng ngữ cảnh document để cải thiện passage representation/ranking.
2. [Hybrid Hierarchical Retrieval, Findings ACL 2023](https://aclanthology.org/2023.findings-acl.679/) — sparse+dense ở cả document và passage, rerank passage trong tài liệu top; hỗ trợ ý tưởng hierarchy hybrid.
3. [Document-Aware Passage Retrieval (DAPR), ACL 2024](https://aclanthology.org/2024.acl-long.236/) — benchmark và phân tích ảnh hưởng document context với passage retrieval.
4. [RAPTOR, 2024](https://arxiv.org/abs/2401.18059) — cây chunks/cluster summaries cho truy xuất nhiều mức trừu tượng; summary chỉ nên là navigation layer với bài nộp extractive.
5. [Late Chunking, 2024](https://arxiv.org/abs/2409.04701) — contextualize token representations trên text dài trước khi pool theo chunk; cần long-context encoder phù hợp và offset alignment.
6. [Question Decomposition for RAG, ACL SRW 2025](https://aclanthology.org/2025.acl-srw.32/) — retrieve per subquestion, merge/deduplicate, rerank; liên quan query nhiều ý, không phải lý do để decompose mọi query.
7. [Annotating Question Decomposition on Complex Medical Questions, LREC 2014](https://aclanthology.org/L14-1156/) — gán disease focus và category như symptoms/treatments/family history trên consumer health questions; taxonomy phải điều chỉnh cho ViBioMIR.
8. [HYRR, LREC-COLING 2024](https://aclanthology.org/2024.lrec-main.748/) — hard/positive training data từ hybrid retrievers giúp reranker robust giữa first-stage retrievers.
9. [Expand, Rerank, and Retrieve (EAR), Findings ACL 2023](https://aclanthology.org/2023.findings-acl.768/) — query expansion kết hợp reranking cho open-domain QA.
10. [Leveraging Structured Metadata for Web QA, AACL-IJCNLP 2020](https://aclanthology.org/2020.aacl-main.55/) — structured page metadata giúp passage selection/reranking.

## Reproducibility, quyền dữ liệu và repository map

- Trước khi dùng external medical data/model/teacher, kiểm tra thể lệ mới nhất, ngày phát hành model và trích dẫn nguồn. Giữ raw data/teacher artifacts private đến khi phạm vi chia sẻ được xác nhận.
- Mỗi experiment lưu corpus revision/hash, query split/hash, code commit, chunk config, model revision, retrieval budgets, metric/version, labels protocol, runtime và output hashes.
- Chunker: `src/vibiomir/corpus/chunk.py`; normalization: `src/vibiomir/common/schema.py`; prepare: `src/vibiomir/corpus/prepare.py`; indexes/retrieval: `src/vibiomir/index/`, `src/vibiomir/retrieval/`.
- Snapshot evidence: `work/rtx2050_60k/corpus/prepare_manifest.json`, `work/rtx2050_60k/chunks/chunk_manifest.json`, logs; scoring rules: `docs/note/RULE.txt`; pipeline documentation: `docs/solution/training_design.md`, `docs/solution/run_guide.md`.
