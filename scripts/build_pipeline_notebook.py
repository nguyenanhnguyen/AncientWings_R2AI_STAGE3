"""Build the standalone Kaggle pipeline notebook from the current src/ and scripts/ code.

Run after changing pipeline code: python scripts/build_pipeline_notebook.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from build_notebooks import build_zip, code_cell

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'notebooks' / 'pipeline.ipynb'


def markdown(source):
    return {'cell_type': 'markdown', 'metadata': {}, 'source': source.splitlines(keepends=True)}


def code(source):
    return {'cell_type': 'code', 'execution_count': None, 'metadata': {}, 'outputs': [],
            'source': source.splitlines(keepends=True)}


def build():
    payload, count = build_zip()
    cells = [markdown('''# ViBioMIR — pipeline Kaggle 500k tài liệu tiếng Việt

Bật **Internet** và **GPU T4 × 2**, thêm Kaggle Secret `HF_TOKEN` có quyền đọc dataset riêng của nhóm, rồi Run All. Notebook nhúng đúng `src/` và `scripts/vibiomir.py` ở thời điểm build. Mọi file trung gian và `submission.zip` nằm trong `/kaggle/working/vibiomir_pipeline`.

Luồng: HF corpus tại revision cố định → đối chiếu cặp ID/URL với BTC → lấy mẫu 500k tiếng Việt trải trên các shard → prepare/QC → chunk có offset → BM25 + dense → RRF → **Qwen3-Reranker-4B một lần** → kiểm tra nguồn và xuất ZIP. Không dịch query, không có vòng feedback. Lần đầu này dựng chỉ mục và chạy mô hình có sẵn; không cập nhật trọng số nếu chưa có nhãn teacher khớp đúng chunk.

Mẫu được chọn bằng hash ID để tránh thiên lệch khoảng ID thấp. Nếu HF hiện có ít hơn 500k tài liệu tiếng Việt hợp lệ, notebook dừng và báo số thực; giảm `LIMIT` nếu muốn chạy trên toàn bộ phần có sẵn. Resume trong session bằng Run All. Để resume sau Save Version, thêm output run trước làm Kaggle Input và đặt `RESUME_FROM` tới thư mục run đó; không đổi cấu hình của cùng run.

Qwen3-Embedding-4B và Qwen3-Reranker-4B đều chạy fp16 trên **một T4 16 GB vào từng giai đoạn**, dùng tối đa 512 token và batch nhỏ. Lượt 500k có thể vượt giới hạn thời gian Kaggle; embedding lưu checkpoint mỗi 2048 chunk, rerank cache theo query. Phiên đầu hãy theo dõi log và dung lượng Output. Để thử thông lượng ngắn hơn, giảm `LIMIT` và dùng `OUT` mới.
'''),
    code('''# ===== CẤU HÌNH DUY NHẤT CẦN SỬA =====
HF_REPO = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
HF_REVISION = 'main'             # resolved to a fixed commit on first run
LIMIT = 500_000                  # exact number of valid vi input documents
SEED = 13                       # deterministic hash sample over all HF shards
OUT = '/kaggle/working/vibiomir_pipeline'
RESUME_FROM = None              # e.g. '/kaggle/input/previous-output/vibiomir_pipeline'
ENCODER = 'qwen3-embedding-4b'   # T4: 4B fp16; use new OUT if changing model
RERANKER = 'qwen3-reranker-4b'  # exactly one 4B reranker
CHUNK_TARGET = 320
CHUNK_OVERLAP = 64
RERANK_K = 40                    # 1,200 * 40 = at most 48k expensive pairs
KEEP = 40
FEEDBACK_ROUNDS = 0             # reserved for a later experiment
'''),
    code('''import os, sys, subprocess, shutil
from pathlib import Path
from kaggle_secrets import UserSecretsClient

token = UserSecretsClient().get_secret('HF_TOKEN')
if not token:
    raise RuntimeError('Missing Kaggle Secret HF_TOKEN')
os.environ['HF_TOKEN'] = token
os.environ['HF_HOME'] = '/kaggle/temp/hf_home'  # model weights stay out of saved notebook Output
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
os.environ['PYTHONIOENCODING'] = 'utf-8'
subprocess.run([sys.executable, '-m', 'pip', 'install', '-q',
                'transformers>=4.51,<5', 'accelerate>=1.6', 'huggingface_hub>=0.30',
                'pyarrow>=19', 'sentencepiece>=0.2', 'protobuf>=4.25'], check=True)
import torch
if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
    raise RuntimeError('Select Kaggle accelerator GPU T4 x2 before Run All.')
print('torch', torch.__version__, 'GPU', [torch.cuda.get_device_name(i) for i in range(2)])
'''),
    code(code_cell(payload, "Path('/kaggle/working/vibiomir_code')")),
    code('''import hashlib, json, time

OUT = Path(OUT)
if RESUME_FROM and not OUT.exists():
    origin = Path(RESUME_FROM)
    if not origin.is_dir():
        raise FileNotFoundError(origin)
    shutil.copytree(origin, OUT)
OUT.mkdir(parents=True, exist_ok=True)
CODE = CODE_DIR / 'scripts' / 'vibiomir.py'
if not CODE.is_file():
    raise FileNotFoundError(CODE)
if ENCODER != 'qwen3-embedding-4b' or RERANKER != 'qwen3-reranker-4b':
    raise ValueError('This first Kaggle profile is fixed to one 4B encoder and one 4B reranker.')
if FEEDBACK_ROUNDS != 0 or not 1 <= KEEP <= RERANK_K:
    raise ValueError('This first trial requires FEEDBACK_ROUNDS=0 and KEEP<=RERANK_K.')

state_dir = OUT / 'stages'
state_dir.mkdir(exist_ok=True)
from huggingface_hub import HfApi
model_revisions_path = OUT / 'model_revisions.json'
if model_revisions_path.exists():
    model_revisions = json.loads(model_revisions_path.read_text())
else:
    api = HfApi(token=os.environ['HF_TOKEN'])
    model_revisions = {
        ENCODER: api.model_info('Qwen/Qwen3-Embedding-4B').sha,
        RERANKER: api.model_info('Qwen/Qwen3-Reranker-4B').sha,
    }
    model_revisions_path.write_text(json.dumps(model_revisions, indent=2))
print('Pinned models:', {k: v[:12] for k, v in model_revisions.items()})
def run_stage(name, arguments, outputs, gpu=None, key_extra=None):
    command = [sys.executable, '-u', str(CODE), *map(str, arguments)]
    record = state_dir / (name + '.json')
    key = hashlib.sha256(json.dumps({'code': CODE_SHA256, 'cmd': command,
                                     'extra': key_extra}, sort_keys=True).encode()).hexdigest()
    if record.exists():
        previous = json.loads(record.read_text())
        if previous['key'] != key:
            raise ValueError(f'{name}: configuration/code changed; use a new OUT.')
        if all(Path(p).is_file() and hashlib.file_digest(open(p, 'rb'), 'sha256').hexdigest() == h
               for p, h in previous['outputs'].items()):
            print(f'[{name}] verified; reuse')
            return
    env = os.environ.copy()
    if gpu is not None:
        env['CUDA_VISIBLE_DEVICES'] = str(gpu)
    print(f'[{name}]', ' '.join(map(str, arguments)), flush=True)
    started = time.monotonic()
    subprocess.run(command, cwd=CODE_DIR, env=env, check=True)
    missing = [str(p) for p in outputs if not Path(p).is_file()]
    if missing:
        raise RuntimeError(f'{name} completed without required output: {missing}')
    hashes = {str(p): hashlib.file_digest(open(p, 'rb'), 'sha256').hexdigest()
              for p in outputs}
    record.write_text(json.dumps({'key': key, 'outputs': hashes,
                                  'seconds': time.monotonic()-started}, indent=2))
'''),
    markdown('''## 1. Chốt corpus HF và dữ liệu BTC

Đọc tất cả shard `corpus/*.parquet` của repo nhóm tại **một commit**, giữ đúng ID và URL ở danh sách BTC, chọn 500k tài liệu tiếng Việt và lưu Parquet local. Không dùng `archives/`, `diagnostics/`, `teach/`. Cache tải shard tạm được xóa sau khi snapshot hoàn tất.
'''),
    code('''source = OUT / 'source'
run_stage('hf_snapshot', ['hf-snapshot', '--repo', HF_REPO, '--revision', HF_REVISION,
                          '--limit', LIMIT, '--seed', SEED, '--out', source],
          [source/'source_manifest.json', source/'input_vi.parquet',
           source/'links_corpus_vi_en_zh.parquet', source/'query.parquet'])
shutil.rmtree(source/'hf_cache', ignore_errors=True)
print('Source:', json.loads((source/'source_manifest.json').read_text())['counts'])
'''),
    markdown('''## 2. Chuẩn hóa, QC, chia chunk

`prepare` loại trang lỗi/template và chốt `corpus.parquet`; `chunk` giữ `char_start`, `char_end`, `chunk_order` để bài nộp cắt lại chính xác từ văn bản nguồn.
'''),
    code('''corpus_dir = OUT / 'corpus'
corpus = corpus_dir / 'corpus.parquet'
chunks_dir = OUT / 'chunks'
chunks = chunks_dir / 'chunks.parquet'
run_stage('prepare', ['prepare', '--source', source/'input_vi.parquet', '--out', corpus_dir,
                      '--limit', LIMIT], [corpus, corpus_dir/'prepare_manifest.json'],
          key_extra=json.loads((source/'source_manifest.json').read_text())['input_sha256'])
run_stage('chunk', ['chunk', '--corpus', corpus, '--out', chunks_dir,
                    '--target-tokens', CHUNK_TARGET, '--overlap-tokens', CHUNK_OVERLAP,
                    '--max-tokens', 768],
          [chunks, chunks_dir/'chunk_manifest.json'],
          key_extra=hashlib.file_digest(open(corpus, 'rb'), 'sha256').hexdigest())
print('Documents:', json.loads((corpus_dir/'prepare_manifest.json').read_text())['documents_kept'])
print('Chunks:', json.loads((chunks_dir/'chunk_manifest.json').read_text())['chunks'])
'''),
    markdown('''## 3. Chỉ mục BM25 và dense

BM25 chạy CPU. Qwen3-Embedding-4B fp16 mã hóa chunk trên GPU 0, ghi ma trận theo shard 2048 chunk. Giai đoạn này có thể mất nhiều giờ; chạy lại cùng Output dùng checkpoint đã ghi.
'''),
    code('''index = OUT / 'index'
chunk_hash = hashlib.file_digest(open(chunks, 'rb'), 'sha256').hexdigest()
run_stage('bm25', ['index', 'bm25', '--chunks', chunks, '--out', index],
          [index/'bm25.npz', index/'bm25_manifest.json'], key_extra=chunk_hash)
run_stage('dense', ['index', 'dense', '--chunks', chunks, '--out', index,
                    '--encoder', ENCODER, '--device', 'cuda', '--max-length', 512,
                    '--batch-size', 4, '--shard', 2048, '--resume',
                    '--revision', model_revisions[ENCODER]],
          [index/'embeddings.npy', index/'dense_manifest.json'], gpu=0,
          key_extra=chunk_hash)
'''),
    markdown('''## 4. BM25 + dense → RRF → một lần rerank

Qwen3-Reranker-4B trên GPU 1 chỉ chấm tối đa `RERANK_K` chunk cho mỗi query. Cache `scores.sqlite` giữ điểm query đã xong. Không có vòng feedback/rewrite ở lần đầu.
'''),
    code('''retrieval = OUT / 'retrieval'
queries = source / 'query.parquet'
run_stage('retrieve', ['retrieve', '--chunks', chunks, '--index', index,
                       '--queries', queries, '--out', retrieval,
                       '--reranker', RERANKER, '--reranker-revision', model_revisions[RERANKER],
                       '--device', 'cuda',
                       '--search-device', 'cuda', '--keyword-variant',
                       '--top-k', 200, '--fuse-k', 250, '--rerank-k', RERANK_K,
                       '--keep', KEEP, '--candidate-per-doc', 3,
                       '--rerank-max-length', 512, '--batch-size', 4,
                       '--rerank-batch', 2, '--search-block', 8192,
                       '--query-block', 32],
          [retrieval/'candidates.jsonl', retrieval/'retrieval_manifest.json'], gpu=1,
          key_extra={'chunks': chunk_hash,
                     'bm25': hashlib.file_digest(open(index/'bm25.npz','rb'), 'sha256').hexdigest(),
                     'dense': hashlib.file_digest(open(index/'dense_manifest.json','rb'), 'sha256').hexdigest(),
                     'queries': hashlib.file_digest(open(queries,'rb'), 'sha256').hexdigest()})
'''),
    markdown('''## 5. Kiểm tra và tạo ZIP nộp

Xuất hai profile từ **cùng một lượt rerank**. `submission/submission.zip` là bản recall mặc định; `submission_balanced/submission.zip` là phương án so sánh. Notebook không tự gửi bài lên ban tổ chức.
'''),
    code('''links = source/'links_corpus_vi_en_zh.parquet'
for profile, folder in [('recall', 'submission'), ('balanced', 'submission_balanced')]:
    target = OUT / folder
    run_stage('submit_'+profile,
              ['submit', '--candidates', retrieval/'candidates.jsonl',
               '--chunks', chunks, '--corpus', corpus, '--queries', queries,
               '--links', links, '--profile', profile, '--require-complete',
               '--out', target],
              [target/'submission.zip', target/'submission.json',
               target/'submission_manifest.json'],
              key_extra=hashlib.file_digest(open(retrieval/'candidates.jsonl','rb'), 'sha256').hexdigest())
    summary = json.loads((target/'submission_manifest.json').read_text())
    if summary['queries_without_candidates'] or summary['validation']['dropped_docs'] or summary['validation']['dropped_chunks']:
        raise RuntimeError(f'{profile}: incomplete or invalid submission; inspect manifest')
    print(profile, 'ready:', target/'submission.zip', summary['submission'])
from IPython.display import FileLink, display
display(FileLink(str(OUT/'submission'/'submission.zip')))
display(FileLink(str(OUT/'submission_balanced'/'submission.zip')))
''')]
    notebook = {'cells': cells, 'metadata': {'kernelspec': {'display_name': 'Python 3',
                 'language': 'python', 'name': 'python3'},
                 'language_info': {'name': 'python'}}, 'nbformat': 4, 'nbformat_minor': 5}
    TARGET.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n',
                      encoding='utf-8')
    print(f'{TARGET.relative_to(ROOT)}: {count} code files, '
          f'{len(payload)/1024:.0f} KiB zipped, sha256 {hashlib.sha256(payload).hexdigest()}')


if __name__ == '__main__':
    build()
