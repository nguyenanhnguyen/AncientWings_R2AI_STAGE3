"""Generate a standalone notebook; helper code is embedded as a normal code cell."""
from pathlib import Path
import hashlib
import json
import textwrap

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'notebooks' / 'review_hf_data_quality.ipynb'
CELLS = []


def cell(kind, source):
    source = textwrap.dedent(source).strip() + '\n'
    item = {'cell_type': kind, 'id': hashlib.sha256(source.encode()).hexdigest()[:12],
            'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code':
        item.update(execution_count=None, outputs=[])
    CELLS.append(item)


cell('markdown', """
# Review chất lượng corpus AncientWings trên Hugging Face

Tìm bằng chứng dữ liệu làm train/retrieval kém: text lỗi, duplicate, sai ID/URL,
mất cân bằng nguồn/ngôn ngữ, độ phủ và truncation. Chạy độc lập trên **Kaggle, Colab hoặc Jupyter**,
không cần GPU hay clone repo. Chạy các ô từ trên xuống.

Kaggle: bật Internet, thêm Secret **HF_TOKEN** có quyền đọc dataset.
Local: dùng hf auth login hoặc biến môi trường HF_TOKEN; không dán token vào notebook.
Mặc định đọc toàn bộ corpus/*.parquet ở một commit được ghim. Không đọc corpus_jsonl/
vì thường là bản sao Parquet. Notebook chỉ đọc HF, ghi báo cáo local, không thay đổi dataset.

Quét theo batch vào SQLite; không giữ toàn bộ text trong RAM. Cần đủ disk cho Parquet cache,
SQLite và báo cáo. Có thể giới hạn shard/rows để smoke test; khi đó báo cáo ghi rõ subset.
Chỉ phân tích near-duplicate/query/tokenizer trên mẫu có thể tái lập.

**Giới hạn:** corpus không có nhãn relevance hoặc split train/validation. Không thể tính
recall/F2 thật hay chứng minh data gây train kém. Cờ nội dung và script language là heuristic
để chọn mẫu review. Cần kiểm tra riêng nhãn positive/negative và teacher data trong teach/
nếu đó là dữ liệu thực sự đưa vào fine-tune.
""")

cell('code', """
# Cài thư viện còn thiếu vào đúng kernel; không nâng cấp thư viện đã có.
import importlib.util
import importlib.metadata
import subprocess
import sys
packages = {
    'huggingface_hub': 'huggingface_hub>=0.34,<2', 'pyarrow': 'pyarrow>=17',
    'pandas': 'pandas>=2.2', 'numpy': 'numpy>=1.26', 'matplotlib': 'matplotlib>=3.8',
    'sklearn': 'scikit-learn>=1.5', 'datasketch': 'datasketch>=1.6',
}
missing = [package for module, package in packages.items()
           if importlib.util.find_spec(module) is None]
if missing:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', *missing])
print('Dependencies OK; Python', sys.version.split()[0])
""")

cell('code', """
# ===== CẤU HÌNH: sửa trước Run All =====
import os
from pathlib import Path
from datetime import datetime, timezone

HF_REPO = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
HF_REVISION = None # điền commit trong pinned.json/fetch_manifest.json của run train cần review.
SOURCE_REPO = 'AIGuruTinix/ViBioMIR'
SOURCE_REVISION = '0148f6f80ffafed5c005af6d506ccfd9d3fb47a7'
SOURCE_LINKS_SHA256 = 'dee1153f5b9d9010dea18e1b7724b4915ff847b711d036bec8b933486802a971'
SOURCE_QUERY_SHA256 = 'ce13508b893bbd6b9169679d540630bc37eb5950cad08b4d5e0e5d7063670c08'
# Snapshot thay thế chỉ có query cùng hash; links mới khác tập ID, không đổi nguồn ngầm.
QUERY_FALLBACK_REVISION = '71be0e1239a19dfd7a717e2bc13e3bec21bd0334'
REQUIRE_SOURCE = False # True: dừng sớm trước khi quét nếu thiếu link tham chiếu đúng hash.
RESUME_REVIEW_DIR = None # thư mục run cũ có config.json + features.sqlite để bỏ qua quét.

LOCAL_CORPUS_DIR = None # offline: thư mục corpus/ của snapshot đã tải, chứa *.parquet.
LOCAL_SOURCE_DIR = None # bản gốc: thư mục có query.parquet và links_corpus.parquet, ví dụ Kaggle Input.
MAX_FILES = None # ví dụ 2: giới hạn shard, không suy rộng ra toàn HF.
cfg = {
    'max_rows_per_file': None, # ví dụ 3000: prefix mỗi file, KHÔNG phải mẫu ngẫu nhiên.
    'batch_size': 1024, 'min_chars': 200, 'long_chars': 30000,
    'sample_size': 3000, 'sample_char_cap': 12000, 'seed': 20261012,
    'manual_per_stratum': 3, 'manual_random_cap': 250, 'manual_suspect_cap': 150,
}
RUN_NEAR_DUPLICATES = True
NEAR_DUP_THRESHOLD = 0.85
RUN_QUERY_PROBE = True
RUN_TOKENIZER = False # bật để đo tokenizer thật; chỉ tải tokenizer, không tải model.
TOKENIZER_ID = 'BAAI/bge-m3' # đổi đúng tokenizer đang train.
TOKENIZER_REVISION = None # model SHA được resolve và ghi vào báo cáo khi bật.
TOKEN_LENGTHS = [512, 1024, 2048]
TOKENIZER_SAMPLE_SIZE = 200

ON_KAGGLE = os.name != 'nt' and Path('/kaggle/working').is_dir()
base = Path('/kaggle/working') if ON_KAGGLE else Path.cwd() / 'work'
OUT = base / 'hf_data_review' / datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
OUT.mkdir(parents=True, exist_ok=False)
CACHE = base / 'hf_data_review_cache'
resume_config = None
if RESUME_REVIEW_DIR:
    resume_root = Path(RESUME_REVIEW_DIR).expanduser().resolve()
    import json
    resume_config = json.loads((resume_root / 'config.json').read_text(encoding='utf-8'))
    if not (resume_root / 'features.sqlite').is_file():
        raise ValueError('Run cũ không có features.sqlite; không thể resume.')
    if not LOCAL_CORPUS_DIR:
        LOCAL_CORPUS_DIR = resume_config.get('local_corpus_dir')
    if not HF_REVISION and not LOCAL_CORPUS_DIR:
        HF_REVISION = resume_config['resolved_revision']
for key in ['batch_size', 'sample_size', 'sample_char_cap', 'manual_per_stratum']:
    if cfg[key] < 1:
        raise ValueError(f'{key} phải >= 1')
if MAX_FILES is not None and MAX_FILES < 1:
    raise ValueError('MAX_FILES phải >= 1 hoặc None')
if cfg['max_rows_per_file'] is not None and cfg['max_rows_per_file'] < 1:
    raise ValueError('max_rows_per_file phải >= 1 hoặc None')
if not 0 < NEAR_DUP_THRESHOLD < 1:
    raise ValueError('NEAR_DUP_THRESHOLD phải nằm giữa 0 và 1')
print('Output:', OUT.resolve())
""")

cell('markdown', """
## 1. Code kiểm tra độc lập

Ô dưới chứa toàn bộ helper đã nhúng sẵn, không tải code từ Internet.
Lần lượt kiểm tra structure, hash/count/status, HTML, mojibake, error/challenge page,
lặp dòng, boilerplate, độ dài và lệch metadata ngôn ngữ.
**hard_flags** là lỗi cấu trúc/metadata xác minh trực tiếp.
**review_flags** cần xem nội dung; bài/Q&A ngắn hoặc thiếu title vẫn có thể hữu ích.
""")
cell('code', (ROOT / 'scripts' / 'hf_data_quality.py').read_text(encoding='utf-8'))

cell('markdown', """
## 2. Ghim snapshot và quét tất cả shard

Để phân tích một run train cụ thể, điền đúng HF_REVISION của run đó. Latest có thể chứa
data mới. Parquet và manifest được tải ở cùng một SHA. Hash mỗi file được lưu để tái lập
kể cả khi dùng LOCAL_CORPUS_DIR. Không tải archives, raw hoặc checkpoint ZIP.

Nguồn ViBioMIR cũ có thể không còn trên HF. Notebook kiểm tra nguồn **trước khi quét**;
nếu thiếu nguồn đúng SHA thì ghi rõ bước bị bỏ qua và vẫn xuất review corpus. Dùng
LOCAL_SOURCE_DIR trỏ tới hai file gốc từ data/ trong repo để đối chiếu đầy đủ.
Nguồn mới links_corpus_vi_en_zh.parquet có số link/hash khác, không được thay thế ngầm.

Sau run lỗi, đặt RESUME_REVIEW_DIR tới thư mục output cũ có config.json/features.sqlite.
Notebook sao lưu SQLite sang output mới, xác minh cấu hình và tiếp tục phân tích;
không quét lại text. Cần cache Parquet/snapshot cũ để lấy mẫu text. Nếu mất cache, chỉ tải
lại file ở commit cũ, không tính lại features. Giữ nguyên min_chars, long_chars, seed và giới hạn quét.
""")
cell('code', """
import os
import pyarrow.parquet as pq
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from huggingface_hub import HfApi, hf_hub_download, get_token
from IPython.display import display, Markdown, FileLink

token = os.environ.get('HF_TOKEN') or get_token()
if not token and ON_KAGGLE:
    try:
        from kaggle_secrets import UserSecretsClient
        token = UserSecretsClient().get_secret('HF_TOKEN')
    except Exception:
        pass
api = HfApi(token=token)
CACHE.mkdir(parents=True, exist_ok=True)

def hf_read(repo, name, revision):
    return Path(hf_hub_download(repo_id=repo, filename=name, repo_type='dataset',
                               revision=revision, token=token, cache_dir=str(CACHE)))

links_path, query_path, source_status = prepare_source_files(
    hf_read, SOURCE_REPO, SOURCE_REVISION, SOURCE_LINKS_SHA256, SOURCE_QUERY_SHA256,
    LOCAL_SOURCE_DIR, QUERY_FALLBACK_REVISION)
write_json(OUT / 'source_status.json', source_status)
if links_path is None:
    print('Nguồn link ViBioMIR gốc chưa khả dụng: bỏ qua đối chiếu ID/URL/độ phủ, '
          'không dùng links mới có hash khác. Đặt LOCAL_SOURCE_DIR tới hai file gốc trong data/.')
if query_path is None:
    print('Query đúng hash chưa khả dụng: bỏ qua query probe, vẫn review corpus.')
if REQUIRE_SOURCE and (links_path is None or query_path is None):
    raise RuntimeError('Thiếu nguồn tham chiếu đúng hash; xem source_status.json. Chưa quét corpus.')

remote = {}
if LOCAL_CORPUS_DIR:
    root = Path(LOCAL_CORPUS_DIR).expanduser().resolve()
    all_names = sorted(p.name for p in root.glob('*.parquet'))
    resolved_revision = HF_REVISION or 'local-unverified'
    get_corpus = lambda name: root / name
else:
    try:
        info = api.dataset_info(HF_REPO, revision=HF_REVISION, files_metadata=True)
    except Exception as error:
        raise RuntimeError('Không đọc được HF. Kiểm tra Internet và HF_TOKEN có quyền đọc '
                           'AncientWings hoặc dùng LOCAL_CORPUS_DIR. '
                           f'Loại lỗi: {type(error).__name__}') from None
    resolved_revision = info.sha
    remote = {item.rfilename: item for item in info.siblings}
    all_names = sorted(name for name in remote if name.startswith('corpus/') and name.endswith('.parquet'))
    get_corpus = lambda name: hf_read(HF_REPO, name, resolved_revision)
    size = sum(remote[name].size or 0 for name in all_names)
    print('Commit:', resolved_revision, '| Parquet:', round(size / 2**30, 2), 'GiB')
names = all_names if MAX_FILES is None else all_names[:MAX_FILES]
if not names:
    raise ValueError('Không có corpus/*.parquet; kiểm tra đúng dataset/thư mục corpus.')
scan_all_input = len(names) == len(all_names) and cfg['max_rows_per_file'] is None
# A local directory may hold only a few HF shards, even if all its files were scanned.
full_scope = not LOCAL_CORPUS_DIR and scan_all_input
scope_label = ('LOCAL: quét toàn bộ file trong thư mục; chưa xác minh đủ snapshot HF'
               if LOCAL_CORPUS_DIR and scan_all_input else
               'TOÀN BỘ corpus Parquet trên HF' if full_scope else 'SUBSET: không suy rộng ra toàn HF')
config = {**cfg, 'hf_repo': HF_REPO, 'resolved_revision': resolved_revision,
    'requested_revision': HF_REVISION, 'source_repo': SOURCE_REPO, 'source_revision': SOURCE_REVISION,
    'local_corpus_dir': LOCAL_CORPUS_DIR, 'local_source_dir': LOCAL_SOURCE_DIR, 'full_scope': full_scope,
    'selected_shards': len(names), 'available_shards': len(all_names), 'max_files': MAX_FILES,
    'input_mode': 'local' if LOCAL_CORPUS_DIR else 'hf', 'scope_label': scope_label,
    'run_near_duplicates': RUN_NEAR_DUPLICATES, 'near_dup_threshold': NEAR_DUP_THRESHOLD,
    'run_query_probe': RUN_QUERY_PROBE, 'run_tokenizer': RUN_TOKENIZER,
    'tokenizer_id': TOKENIZER_ID, 'tokenizer_revision': TOKENIZER_REVISION,
    'token_lengths': TOKEN_LENGTHS, 'tokenizer_sample_size': TOKENIZER_SAMPLE_SIZE,
    'feature_version': 1, 'source_status': source_status}
if resume_config:
    validate_resume(resume_config, config)
write_json(OUT / 'config.json', config) # Không ghi token.
write_json(OUT / 'environment.json', {key: importlib.metadata.version(key) for key in [
    'huggingface_hub', 'pyarrow', 'pandas', 'numpy', 'matplotlib', 'scikit-learn', 'datasketch']})
print('Scope:', scope_label)

db = sqlite3.connect(OUT / 'features.sqlite')
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA temp_store=FILE')
if resume_config:
    # Read the prior SQLite without modifying it, including runs stopped before CSV export.
    from contextlib import closing
    with closing(sqlite3.connect((resume_root / 'features.sqlite').as_uri() + '?mode=ro', uri=True)) as prior_db:
        prior_db.backup(db)
    counts = dict(db.execute('SELECT file_name, COUNT(*) FROM features GROUP BY file_name'))
    if set(counts) - set(names):
        raise ValueError('SQLite cũ có shard không thuộc snapshot đang chọn.')
    inventory, file_lookup = [], {}
    for name in names:
        local = get_corpus(name)
        file_lookup[name] = local
        parquet = pq.ParquetFile(local)
        expected_rows = (parquet.metadata.num_rows if cfg['max_rows_per_file'] is None else
                         min(parquet.metadata.num_rows, cfg['max_rows_per_file']))
        if counts.get(name, 0) != expected_rows:
            raise ValueError(f'Features của {name} chưa quét đủ; cần run mới để quét lại.')
        inventory.append({'file_name': name, 'bytes': local.stat().st_size,
            'sha256': file_sha256(local), 'rows_available': parquet.metadata.num_rows,
            'rows_scanned': counts.get(name, 0), 'schema': str(parquet.schema_arrow),
            'missing_core_fields': '|'.join(sorted({'id', 'url', 'text'} - set(parquet.schema_arrow.names)))})
        parquet.close()
    print('Đã resume SQLite; không quét lại text.')
else:
    inventory, file_lookup = scan_corpus(db, names, get_corpus, cfg)
total_rows = int(db.execute('SELECT COUNT(*) FROM features').fetchone()[0])
unique_ids = int(db.execute('SELECT COUNT(DISTINCT id) FROM features').fetchone()[0])
if not total_rows:
    raise ValueError('Không có rows trong phạm vi đã chọn.')
reports = {'shard_inventory': pd.DataFrame(inventory)}
save_reports(OUT, reports)
display(reports['shard_inventory'].drop(columns=['schema', 'sha256']).head(30))
print(f'Quét {total_rows:,} rows; {unique_ids:,} ID hợp lệ khác nhau.')

manifest_rows = []
for name in names:
    run_name = Path(name).stem
    for kind in ['notebook_manifest.json', 'upload_manifest.json']:
        remote_name = f'manifests/{run_name}/{kind}'
        if remote_name not in remote:
            continue
        # Chỉ đọc manifest nhỏ; kích thước lớn/không rõ được ghi lại để review riêng.
        size = remote[remote_name].size
        if size is None or size > 2 * 1024 * 1024:
            manifest_rows.append({'file': remote_name, 'read_status': 'skipped_size'})
            continue
        try:
            manifest = json.loads(hf_read(HF_REPO, remote_name, resolved_revision).read_text(encoding='utf-8'))
            counts = manifest.get('counts') or manifest
            manifest_rows.append({'file': remote_name, 'read_status': 'ok',
                'complete': manifest.get('complete'), 'snapshot_scope': manifest.get('snapshot_scope'),
                'source_sha256': manifest.get('source_sha256'), 'accepted': counts.get('accepted'),
                'selected': counts.get('selected'), 'pending': counts.get('pending'),
                'id_from': manifest.get('id_from_inclusive'), 'id_to': manifest.get('id_to_inclusive')})
        except Exception as error:
            manifest_rows.append({'file': remote_name, 'read_status': type(error).__name__})
reports['hf_manifests'] = pd.DataFrame(manifest_rows, columns=['file', 'read_status', 'complete',
    'snapshot_scope', 'source_sha256', 'accepted', 'selected', 'pending', 'id_from', 'id_to'])
display(reports['hf_manifests'].head(20))
save_reports(OUT, reports)
""")

cell('markdown', """
## 3. Duplicate xuyên shard, lỗi dữ liệu và phân bố

Duplicate ID giống nhau là overlap shard; ID có nhiều URL/text là xung đột cần đối chiếu
provenance. Text giống nhau ở nhiều ID có thể là bài đăng lại hoặc template.
Chuẩn hóa duplicate giữ số, dấu tiếng Việt; không dùng normalized text thay bản gốc.

Khi dedup train/index vẫn giữ ánh xạ document ID chính thức. Script hint **latin_other**
không xác nhận tiếng Anh, **cjk** chưa phân biệt Trung/Nhật. Approx tokens đếm từng ký tự
CJK và nhóm chữ/số Latin; không phải token của model.
""")
cell('code', """
reports.update(quality_tables(db))
save_reports(OUT, reports) # giữ kết quả corpus ngay cả khi bước tiếp theo gặp lỗi.
display(reports['quality_flags'], reports['duplicate_ids'].head(15),
        reports['duplicate_text_groups'].head(15), reports['language_metadata'])
duplicate_excess = int((reports['duplicate_text_groups']['rows'] - 1).sum())
ids = reports['duplicate_ids']
conflicting_ids = int(((ids['text_versions'] > 1) | (ids['url_versions'] > 1)).sum())
print('Normalized duplicate rows dư:', duplicate_excess, '| ID xung đột:', conflicting_ids)
write_json(OUT / 'corpus_summary.json', {'rows': total_rows, 'unique_ids': unique_ids,
    'duplicate_excess_rows': duplicate_excess, 'conflicting_ids': conflicting_ids})

lengths = table(db, 'SELECT chars, approx_tokens, script_hint FROM features')
stats = lengths.groupby('script_hint')[['chars', 'approx_tokens']].describe(percentiles=[.1, .5, .9, .95, .99])
stats.columns = ['_'.join(map(str, column)) for column in stats.columns]
reports['length_stats'] = stats.reset_index()
display(reports['length_stats'])
fig, axes = plt.subplots(2, 2, figsize=(15, 10))
reports['by_domain'].head(20).iloc[::-1].plot.barh(x='domain', y='rows', ax=axes[0, 0], legend=False)
axes[0, 0].set_title('Top domains: rows, có thể chứa duplicate')
reports['by_language'].plot.bar(x='script_hint', y='rows', ax=axes[0, 1], legend=False, rot=0)
axes[0, 1].set_title('Script hint, chưa phải language classifier')
axes[1, 0].hist(np.log10(1 + lengths['chars']), bins=60)
axes[1, 0].set(xlabel='log10(1 + chars)', ylabel='Rows', title='Độ dài text')
flags = reports['quality_flags']
if not flags.empty:
    flags.head(15).iloc[::-1].plot.barh(x='flag', y='row_share', ax=axes[1, 1], legend=False)
axes[1, 1].set_title('Tỷ lệ cờ cần review')
fig.tight_layout()
fig.savefig(OUT / 'quality_overview.png', dpi=160)
plt.show()
del lengths # chỉ các cột số vào RAM, không có toàn bộ text.
""")

cell('markdown', """
## 4. Đối chiếu ID/URL và độ phủ link nguồn

Quét ViBioMIR gốc theo batch, chỉ lưu link có ID trong corpus. Denominator lấy mọi link
nguồn, numerator là unique ID đã có trong corpus. Cả hai dùng hostname URL gốc.
**Độ phủ link không phải crawl success rate hoặc recall**: gồm cả link chưa crawl, link chết,
và không có nhãn relevance. Manifest accepted-only không cho biết crawl thất bại.
URL được so khớp nguyên văn với link nguồn, nên khác http/https cũng xuất ra để đối chiếu.
Nếu nguồn gốc không khả dụng, kết quả là **skipped / chưa đo**, không ghi độ phủ/lỗi ID bằng 0.
""")
cell('code', """
if links_path is not None:
    coverage_tables, coverage_summary = source_coverage(db, links_path)
    reports.update(coverage_tables)
    coverage_summary.update(status='ready', full_corpus_scope=full_scope,
        source_links_sha256=file_sha256(links_path),
        query_sha256=file_sha256(query_path) if query_path is not None else None)
    display(reports['source_coverage_by_domain'].head(30),
            reports['ids_not_in_source'].head(10), reports['source_url_mismatches'].head(10))
    print('Độ phủ link:', f'{coverage_summary["link_coverage"]:.2%}', '(không phải recall)')
else:
    coverage_summary = {'status': 'skipped', 'reason': 'original_source_unavailable_or_hash_mismatch',
        'source_rows': None, 'matched_ids': None, 'link_coverage': None,
        'unknown_ids': None, 'url_mismatch_rows': None, 'full_corpus_scope': full_scope}
    print('Chưa đo đối chiếu ID/URL và độ phủ: thiếu link gốc đúng hash. Review corpus tiếp tục.')
write_json(OUT / 'source_coverage.json', coverage_summary)
save_reports(OUT, reports)
""")

cell('markdown', """
## 5. Mẫu đều theo row và phiếu review thủ công

Analysis sample dùng hash ổn định của seed/shard/row number, tránh bias ID đầu shard.
Duplicate rows có thể tăng trọng số mẫu; downstream lexical probe dedup exact text.

Phiếu manual lấy mẫu theo domain × script và thêm bản ghi lỗi/duplicate. **Phiếu này có
bias về mẫu nghi ngờ**, không dùng tỷ lệ trong phiếu làm tỷ lệ lỗi corpus. Điền usable,
extraction_ok, medical_relevance, duplicate_template và review_notes.
Mẫu cap 12.000 chars có cờ sample_truncated; dữ liệu gốc và stats toàn corpus không bị cap.
""")
cell('code', """
sample_meta, sample_df, manual_review = make_samples(db, file_lookup, cfg)
reports['analysis_sample'] = sample_df
reports['manual_review'] = manual_review
write_json(OUT / 'sample_scope.json', {'analysis_rows': len(sample_df), 'seed': cfg['seed'],
    'sampling_unit': 'row', 'sample_text_char_cap': cfg['sample_char_cap'],
    'truncated_analysis_rows': int(sample_df['sample_truncated'].sum()),
    'manual_rows': len(manual_review), 'manual_sample_biased_to_suspects': True})
display(manual_review[['id', 'domain', 'script_hint', 'chars', 'hard_flags', 'review_flags',
                       'sample_reason', 'preview']].head(20))
save_reports(OUT, reports)
""")

cell('markdown', """
## 6. Near-duplicate trên mẫu

MinHash LSH trên char 5-grams tạo candidate, xác minh bằng Jaccard thật; bỏ exact duplicate,
chỉ xét text >= 100 chars. LSH có thể bỏ sót. Tối đa 10.000 pairs để giữ RAM ổn định.
Mẫu bị cap chỉ so sánh prefix, cần review full text trước kết luận. Kết quả không phải tỷ lệ
near-duplicate toàn corpus. Nếu split train/validation theo row, duplicate có nguy cơ leakage;
corpus không có split để xác minh leakage thực tế.
""")
cell('code', """
near_df = pd.DataFrame()
near_pair_cap_hit = False
if RUN_NEAR_DUPLICATES:
    near_df, near_pair_cap_hit = near_duplicates(sample_df, NEAR_DUP_THRESHOLD, cfg['seed'])
reports['near_duplicate_sample_pairs'] = near_df
display(near_df.head(20))
print('Pairs trong mẫu:', len(near_df), '| Cap hit:', near_pair_cap_hit,
      '| Check đã chạy:', RUN_NEAR_DUPLICATES)
""")

cell('markdown', """
## 7. Query gốc và lexical probe

Kiểm tra query rỗng, trùng ID/text và script. TF-IDF char 3–5 grams tìm top-3 trong mẫu corpus
để xem tay mức liên quan. **Không phải đánh giá model, semantic coverage, recall hay F2**.
Điểm thấp có thể vì khác ngôn ngữ hoặc bài relevant nằm ngoài mẫu. Điền human_relevant và
review_notes trong query_probe.csv. Không coi 1.200 query gốc là nhãn train.
""")
cell('code', """
queries = pq.read_table(query_path).to_pandas() if query_path is not None else pd.DataFrame(columns=['id', 'query'])
if not {'id', 'query'}.issubset(queries.columns):
    raise ValueError('query.parquet cần id và query')
queries['query'] = queries['query'].fillna('').astype(str)
queries['normalized'] = queries['query'].map(norm_match)
queries['chars'] = queries['query'].str.len()
queries['script_hint'] = queries['query'].map(script_hint)
query_summary = {'rows': len(queries), 'empty_rows': int(queries['normalized'].eq('').sum()),
    'status': 'ready' if query_path is not None else 'skipped',
    'duplicate_id_rows_excess': int(queries['id'].duplicated().sum()),
    'duplicate_query_rows_excess': int(queries.loc[queries['normalized'].ne(''), 'normalized'].duplicated().sum()),
    'by_script_hint': queries['script_hint'].value_counts().to_dict()}
write_json(OUT / 'query_summary.json', query_summary)
reports['query_inventory'] = queries
query_probe_ran = RUN_QUERY_PROBE and query_path is not None
reports['query_probe'] = query_probe(queries, sample_df) if query_probe_ran else pd.DataFrame()
display(queries.groupby('script_hint')['chars'].describe(), reports['query_probe'].head(12))
save_reports(OUT, reports)
""")

cell('markdown', """
## 8. Tùy chọn: truncation với tokenizer thật

Bật RUN_TOKENIZER và dùng tokenizer/max_length đúng với train. Tokenizer sample đọc text
**đầy đủ** từ Parquet, không dùng text đã cap. Báo tỷ lệ document vượt limit và phần tokens
bị mất nếu chỉ giữ prefix. Nếu chunk trước train, phải đo lại trên chunk/pair thực tế:
con số nguyên document ở đây chỉ là tín hiệu nguy cơ. Cross-encoder cần đo query + passage
kèm special tokens; ô này chỉ đo một document với special tokens.
""")
cell('code', """
token_summary = []
reports['tokenizer_sample'] = pd.DataFrame(columns=['id', 'domain', 'script_hint', 'token_count'])
if RUN_TOKENIZER:
    if TOKENIZER_SAMPLE_SIZE < 1 or not TOKEN_LENGTHS or min(TOKEN_LENGTHS) < 1:
        raise ValueError('Token sample và max_length phải > 0')
    if importlib.util.find_spec('transformers') is None:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'transformers>=4.45,<6'])
    from transformers import AutoTokenizer
    tokenizer_revision = api.model_info(TOKENIZER_ID, revision=TOKENIZER_REVISION).sha
    tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_ID, revision=tokenizer_revision,
        token=token, cache_dir=str(CACHE / 'tokenizer'), trust_remote_code=False)
    tokenizer.model_max_length = int(1e12) # không truncate; chỉ tránh cảnh báo length.
    token_samples = load_selected(sample_meta.head(TOKENIZER_SAMPLE_SIZE), file_lookup,
                                  cfg['batch_size'], char_cap=None)
    token_df = token_samples[['id', 'domain', 'script_hint']].copy()
    token_df['token_count'] = [len(tokenizer(text, add_special_tokens=True, truncation=False)['input_ids'])
                              for text in token_samples['text_sample']]
    reports['tokenizer_sample'] = token_df
    for limit in TOKEN_LENGTHS:
        counts = token_df['token_count']
        token_summary.append({'max_length': limit, 'sample_rows': len(counts),
            'document_truncation_share': float((counts > limit).mean()) if len(counts) else None,
            'token_loss_share': float((counts-limit).clip(lower=0).sum() / max(1, counts.sum()))})
    write_json(OUT / 'tokenizer_config.json', {'id': TOKENIZER_ID, 'revision': tokenizer_revision,
                                             'input': 'full document; special tokens included'})
else:
    print('Bỏ qua tokenizer; bật RUN_TOKENIZER nếu cần đo theo cấu hình train thật.')
reports['truncation_risk'] = pd.DataFrame(token_summary, columns=[
    'max_length', 'sample_rows', 'document_truncation_share', 'token_loss_share'])
display(reports['truncation_risk'])
""")

cell('markdown', """
## 9. Báo cáo và bước tiếp theo

Ưu tiên lỗi ID/URL/hash/status, rồi review domain nhiều cờ, dedup train và cân bằng nguồn.
Thử ablation trên cùng validation độc lập với split theo document/nhóm duplicate:
data hiện tại → bỏ lỗi chắc chắn → dedup → cân bằng nguồn/ngôn ngữ. Giữ model, seed,
số bước và ngân sách token cố định để phân biệt hiệu ứng data với training config.

Tài liệu API: [Hugging Face HfApi](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api)
và [PyArrow ParquetFile/iter_batches](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetFile.html).
""")
cell('code', """
hard_rows = int(db.execute('SELECT COUNT(*) FROM features WHERE n_hard>0').fetchone()[0])
review_rows = int(db.execute('SELECT COUNT(*) FROM features WHERE n_review>0').fetchone()[0])
summary = {
    'repo': HF_REPO, 'revision': resolved_revision, 'full_scope': full_scope,
    'scope_label': scope_label, 'scanned_rows': total_rows,
    'unique_valid_ids': unique_ids, 'hard_flag_rows': hard_rows, 'review_flag_rows': review_rows,
    'duplicate_id_groups': len(ids), 'conflicting_id_groups': conflicting_ids,
    'normalized_duplicate_groups': len(reports['duplicate_text_groups']),
    'normalized_duplicate_excess_rows': duplicate_excess,
    'normalized_duplicate_excess_share': duplicate_excess / total_rows,
    'analysis_sample_rows': len(sample_df), 'near_duplicate_sample_pairs': len(near_df),
    'near_duplicate_pair_cap_hit': near_pair_cap_hit,
    'checks_run': {'near_duplicates': RUN_NEAR_DUPLICATES, 'query_probe': query_probe_ran,
                   'tokenizer': RUN_TOKENIZER},
    'quality_flag_counts': {row.flag: int(row.rows) for row in flags.itertuples()},
    'source_coverage': coverage_summary, 'source_status': source_status, 'query_summary': query_summary,
    'limits': ['Không có relevance labels: không tính recall/F2 hay kết luận nguyên nhân train.',
               'review_flags/script_hint là heuristic, cần review nội dung.',
               'Near-duplicate, lexical probe, tokenizer chỉ chạy trên mẫu.',
               'Không có split/positive/negative: chưa kiểm tra leakage và label noise train.'],
}
write_json(OUT / 'summary.json', summary)
save_reports(OUT, reports)

lines = [
    '# Review corpus AncientWings', '', f'- Repo: {HF_REPO}; commit: {resolved_revision}.',
    f'- Phạm vi: {scope_label}.',
    f'- Quét **{total_rows:,} rows**, **{unique_ids:,} ID hợp lệ khác nhau**.',
    f'- Lỗi cấu trúc/metadata: **{hard_rows:,} rows ({hard_rows/total_rows:.2%})**.',
    f'- Cờ cần review nội dung: **{review_rows:,} rows ({review_rows/total_rows:.2%})**.',
    f'- ID xung đột: **{conflicting_ids:,} nhóm**.',
    f'- Dư theo text chuẩn hóa trùng: **{duplicate_excess:,} rows ({duplicate_excess/total_rows:.2%})**.',
]
if coverage_summary['status'] == 'ready':
    lines += [f'- ID ngoài nguồn: **{coverage_summary["unknown_ids"]:,}**; '
              f'URL lệch nguồn: **{coverage_summary["url_mismatch_rows"]:,} rows**.',
              f'- Độ phủ link: **{coverage_summary["link_coverage"]:.2%}** (không phải recall/crawl success rate).']
else:
    lines += ['- **Chưa đo ID/URL/độ phủ:** thiếu link nguồn gốc đúng hash. '
              'Đặt LOCAL_SOURCE_DIR tới hai file gốc của repo, không dùng link mới có hash khác.']
if query_summary['status'] == 'skipped':
    lines.append('- **Chưa chạy query probe:** thiếu query đúng hash.')
lines += ['', '## Các cờ phổ biến', '', '| Cờ | Rows | Tỷ lệ trong phạm vi |', '|---|---:|---:|']
lines += [f'| {row.flag} | {row.rows:,} | {row.row_share:.2%} |' for row in flags.itertuples()]
lines += ['', '## Hành động theo bằng chứng', '']
if hard_rows or conflicting_ids or coverage_summary['unknown_ids'] or coverage_summary['url_mismatch_rows']:
    lines.append('- Ưu tiên đối chiếu ID/URL/hash/status và provenance; cô lập bản ghi sai trước train/index.')
if duplicate_excess:
    lines.append('- Review duplicate_text_groups.csv; dedup train và giữ ánh xạ ID phục vụ retrieval.')
if review_rows:
    lines.append('- Đọc manual_review.csv và by_domain.csv để sửa parser/domain sinh text lỗi.')
domains = reports['by_domain']
if len(domains) and domains.iloc[0]['rows'] / total_rows > .5:
    lines.append('- Một domain chiếm hơn 50% rows; thử cân bằng nguồn với cùng ngân sách token.')
lines += [
    '- Review query_probe.csv; điểm lexical không chứng minh semantic coverage.',
    '- Dùng tokenizer/max_length thật để kiểm tra truncation trên chunk/pair đưa vào train.',
    '- Audit riêng teacher/train pairs: positive sai, false-negative, phân bố score, split document.',
    '- Chạy ablation cùng validation độc lập, model, seed, số bước và ngân sách token.',
    '', '## Giới hạn', '', *[f'- {limit}' for limit in summary['limits']],
    '', 'Chưa đủ bằng chứng để kết luận data là nguyên nhân làm train kém.',
]
report = '\\n'.join(lines) + '\\n'
(OUT / 'REPORT.md').write_text(report, encoding='utf-8')
display(Markdown(report))

# ZIP chứa báo cáo/mẫu/chart, không chứa full corpus, cache hoặc SQLite.
import zipfile
db.commit()
db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
with zipfile.ZipFile(OUT / 'data_quality_review.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(OUT.iterdir()):
        if path.suffix in {'.csv', '.json', '.md', '.png'}:
            archive.write(path, arcname=path.name)
display(FileLink(str(OUT / 'REPORT.md')), FileLink(str(OUT / 'manual_review.csv')),
        FileLink(str(OUT / 'data_quality_review.zip')))
print('features.sqlite giữ toàn bộ features để query tiếp; không nằm trong ZIP.')
""")


def build():
    notebook = {'cells': CELLS, 'metadata': {
        'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python', 'version': '3.11'},
        'kaggle': {'isGpuEnabled': False, 'isInternetEnabled': True, 'language': 'python'},
    }, 'nbformat': 4, 'nbformat_minor': 5}
    TARGET.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(TARGET)


if __name__ == '__main__':
    build()

