"""Embed this repository's code into the Kaggle notebooks, so Kaggle runs exactly the laptop code.

    kaggle   writes notebooks/for_kaggle.ipynb: the whole pipeline, data from Hugging Face.
    teach    refreshes the code cell of notebooks/teach_kaggle.ipynb (block T, paused).

src/ and scripts/vibiomir.py are zipped (fixed timestamps: same code, same bytes) and
base64-embedded in one cell. After any code change: rerun this script and upload the notebook.

    python scripts/build_notebooks.py            # both
    python scripts/build_notebooks.py kaggle     # only for_kaggle.ipynb
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks' / 'for_kaggle.ipynb'
TEACH_NOTEBOOK = ROOT / 'notebooks' / 'teach_kaggle.ipynb'
CODE_MARKER = '# Sinh tự động bởi scripts/build_notebooks.py: code của repo, nhúng trong notebook.'
# Code cells written by the two builders this file replaced are recognised, so an old notebook is
# updated in place instead of gaining a second code cell.
OLD_MARKERS = ('# Sinh tự động bởi scripts/build_kaggle_notebook.py',
               '# Sinh tự động bởi scripts/build_teach_notebook.py')


def build_zip():
    files = sorted(p for p in (ROOT / 'src').rglob('*.py') if '__pycache__' not in p.parts)
    files.append(ROOT / 'scripts' / 'vibiomir.py')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            # Fixed timestamp: the same code always yields the same bytes and hash.
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue(), len(files)


def code_cell(data, code_dir=None):
    """The embedded-code cell. `code_dir` defines CODE_DIR when the notebook does not."""
    encoded = base64.b64encode(data).decode('ascii')
    lines = [encoded[i:i + 120] for i in range(0, len(encoded), 120)]
    return (CODE_MARKER + '\n'
            '# Không sửa tay ô này; sửa code trong repo rồi chạy lại script đó.\n'
            'import base64, hashlib, io, shutil, zipfile\n'
            'from pathlib import Path\n'
            f"CODE_SHA256 = '{hashlib.sha256(data).hexdigest()}'\n"
            'CODE_ZIP = (\n' + ''.join(f"    '{line}'\n" for line in lines) + ')\n'
            'payload = base64.b64decode(CODE_ZIP)\n'
            'if hashlib.sha256(payload).hexdigest() != CODE_SHA256:\n'
            "    raise ValueError('Code nhúng bị hỏng; build lại notebook.')\n"
            + (f'CODE_DIR = {code_dir}\n' if code_dir else '') +
            'shutil.rmtree(CODE_DIR, ignore_errors=True)\n'
            'zipfile.ZipFile(io.BytesIO(payload)).extractall(CODE_DIR)\n'
            "print('Code:', CODE_SHA256[:12], sum(1 for _ in CODE_DIR.rglob('*.py')), 'file .py')\n")


INTRO = """# ViBioMIR trên Kaggle: từ corpus HF đến `submission.zip`

Notebook chạy **toàn bộ pipeline** trong một lần Run All, không cần clone repo:

1. `fetch`: tải `query.parquet`, `links_corpus.parquet` của BTC (revision cố định, kiểm tra SHA-256) và corpus đã crawl của nhóm (`corpus/*.parquet` trên Hugging Face). Commit của corpus được **ghim** cho run này; laptop chạy đúng lệnh này với cùng code.
2. `prepare` → `cards` (thẻ tài liệu: tiêu đề + đoạn mở đầu).
3. Một LLM (Qwen3-4B) dịch 1.200 truy vấn sang tiếng Trung, chạy theo batch. Chỉ dùng để **tìm**, không bao giờ được nộp.
4. **Truy xuất thác:** tìm trên thẻ của toàn corpus → giữ tài liệu ứng viên → chỉ chunk và lập chỉ mục đoạn cho các tài liệu đó.
5. **Một reranker** (bge-reranker-v2-m3), đọc đoạn tiếng Trung cùng bản dịch tiếng Trung của câu hỏi.
6. Chọn tài liệu/đoạn theo **ngưỡng tối ưu F2**, mở rộng đoạn nộp thành cửa sổ ≤ `WINDOW_TOKENS` (vẫn là đoạn trích nguyên văn), kiểm tra và đóng ZIP.

**Cài đặt notebook:** Accelerator **GPU T4 x2**, **Internet** bật, và Secret `HF_TOKEN` (Add-ons → Secrets) có quyền đọc dataset nhóm: dataset này **private**.

**Kết quả:** `/kaggle/working/submission.zip`. Pipeline giữ tối giản (một encoder, một reranker, một LLM dịch, không pilot) để dành thời gian cho nhiều dữ liệu hơn.

Code trong ô thứ 4 được sinh bởi `scripts/build_notebooks.py` từ repo. Sửa code trên laptop, build lại, upload lại; không sửa tay ô đó.

Thời gian chạy **chưa đo thật**; phụ thuộc số tài liệu trên HF. Để thử nhanh, đặt `LIMIT_ROWS = 20000` ở ô cấu hình."""

CONFIG = """# ===== CẤU HÌNH =====
HF_CORPUS_REPO = 'AncientWings/AncientWings_R2AI_STAGE3_ds'   # corpus crawl của nhóm: corpus/*.parquet
HF_CORPUS_REVISION = None    # None: commit mới nhất (được ghim cho RUN); điền commit để chạy lại snapshot cũ

# Model cố định: encoder bge-m3, reranker bge-reranker-v2-m3, LLM dịch Qwen3-4B (fp16 trên T4).
HYDE = []                            # ['zh', 'vi'] để sinh thêm đoạn trả lời giả (chậm hơn)
DOCS_PER_QUERY = 200                 # tài liệu ứng viên mỗi truy vấn sau tầng thẻ
RERANK_K = 60                        # số đoạn reranker chấm mỗi truy vấn
WINDOW_TOKENS = 768                  # cửa sổ đoạn nộp; 0 = giữ nguyên chunk
LIMIT_ROWS = None                    # None: cả corpus; ví dụ 20000 để chạy thử
CALIBRATION = None                   # đường dẫn calibration.json (vibiomir.py evaluate calibrate) nếu có

from pathlib import Path
WORK = Path('/kaggle/working')
CODE_DIR = WORK / 'vibiomir_code'
RUN = WORK / 'run'   # chạy lại notebook trong cùng phiên: các khâu đã xong được dùng lại"""

INSTALL = """import importlib.metadata, os, subprocess, sys

def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

need = []
current = version('transformers')
major_minor = tuple(int(x) for x in current.split('.')[:2]) if current else (0, 0)
if not (4, 51) <= major_minor < (5, 0):
    need.append('transformers>=4.51,<5')   # Qwen3 cần >=4.51; code chưa kiểm thử với 5.x
if need:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', *need], check=True)

try:
    from kaggle_secrets import UserSecretsClient
    os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')
    print('Đã nạp HF_TOKEN từ Kaggle Secrets.')
except Exception:
    print('CẢNH BÁO: không có Secret HF_TOKEN; dataset corpus của nhóm là private nên khâu fetch sẽ báo 401.')

import torch
GPUS = torch.cuda.device_count()
print('torch', torch.__version__, '| transformers', version('transformers'), '| GPU:',
      [torch.cuda.get_device_name(i) for i in range(GPUS)])
if GPUS == 0:
    raise RuntimeError('Không thấy GPU. Bật Accelerator GPU T4 x2 trong Settings.')"""

RUN_CELL = """# Chạy lại ô này sau khi bị ngắt: bước nào đã xong (kiểm tra SHA-256) được dùng lại.
command = [sys.executable, '-u', str(CODE_DIR / 'scripts' / 'vibiomir.py'), 'pipeline', '--profile', 'kaggle',
           '--gpus', str(min(GPUS, 2)), '--source', 'hf', '--hf-repo', HF_CORPUS_REPO,
           '--out', str(RUN), '--hyde', *HYDE, '--docs-per-query', str(DOCS_PER_QUERY), '--rerank-k', str(RERANK_K),
           '--window-tokens', str(WINDOW_TOKENS)]
if HF_CORPUS_REVISION:
    command += ['--hf-revision', HF_CORPUS_REVISION]
if LIMIT_ROWS:
    command += ['--limit', str(LIMIT_ROWS)]
if CALIBRATION:
    command += ['--calibration', str(CALIBRATION)]
env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'TOKENIZERS_PARALLELISM': 'false'}
process = subprocess.Popen(command, cwd=CODE_DIR, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
for line in process.stdout:
    print(line, end='', flush=True)
if process.wait():
    raise RuntimeError(f'Pipeline dừng với mã {process.returncode}; xem {RUN / "logs"}')"""

RESULT_CELL = """import json, shutil
from IPython.display import FileLink, display

fetched = json.loads((RUN / 'hf' / 'fetch_manifest.json').read_text(encoding='utf-8'))
print(f"Dữ liệu: {fetched['corpus_repo']}@{fetched['corpus_revision'][:12]}, "
      f"{fetched['corpus_files']} file, {fetched['corpus_rows']:,} dòng; BTC {fetched['source_revision'][:12]}")

for name, target in (('submission', 'submission.zip'),):
    source = RUN / name / 'submission.zip'
    if source.exists():
        shutil.copyfile(source, WORK / target)
        manifest = json.loads((RUN / name / 'submission_manifest.json').read_text(encoding='utf-8'))
        print(f'\\n== {target} ==')
        print(json.dumps({'submission': manifest['submission'],
                          'window_tokens': manifest['validation'].get('window_tokens'),
                          'chunk_tokens_median': manifest['validation'].get('chunk_tokens_median'),
                          'chunk_tokens_max': manifest['validation'].get('chunk_tokens_max'),
                          'warnings': manifest['validation']['warnings'][:5]},
                         ensure_ascii=False, indent=2))
        display(FileLink(str((WORK / target).relative_to(WORK))))
print('\\nFile nộp: /kaggle/working/submission.zip')"""


def cell(kind, source):
    base = {'cell_type': kind, 'metadata': {}, 'source': source.splitlines(keepends=True)}
    if kind == 'code':
        base.update(execution_count=None, outputs=[])
    return base


def build_kaggle():
    data, count = build_zip()
    notebook = {
        'cells': [cell('markdown', INTRO), cell('code', CONFIG), cell('code', INSTALL),
                  cell('code', code_cell(data)), cell('code', RUN_CELL),
                  cell('code', RESULT_CELL)],
        'metadata': {'kernelspec': {'display_name': 'Python 3', 'language': 'python',
                                    'name': 'python3'},
                     'language_info': {'name': 'python'},
                     'kaggle': {'accelerator': 'nvidiaTeslaT4', 'isInternetEnabled': True,
                                'isGpuEnabled': True, 'language': 'python',
                                'sourceType': 'notebook'}},
        'nbformat': 4, 'nbformat_minor': 5,
    }
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'{NOTEBOOK.relative_to(ROOT)}: {count} file code, {len(data) / 1024:.0f} KB nén, '
          f'sha256 {hashlib.sha256(data).hexdigest()[:12]}')


def build_teach():
    """Replace only the code cell of the hand-written teach notebook; its other cells stay."""
    notebook = json.loads(TEACH_NOTEBOOK.read_text(encoding='utf-8'))
    data, count = build_zip()
    new = cell('code', code_cell(data, code_dir="Path('/kaggle/working/vibiomir/code')"))
    cells = notebook['cells']
    found = [i for i, c in enumerate(cells)
             if ''.join(c['source']).startswith((CODE_MARKER,) + OLD_MARKERS)]
    if found:
        cells[found[0]] = new
    else:
        # Right after the install cell (the one that reads the HF_TOKEN secret).
        install = next(i for i, c in enumerate(cells) if 'get_secret' in ''.join(c['source']))
        cells.insert(install + 1, new)
    TEACH_NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n',
                              encoding='utf-8')
    print(f'{TEACH_NOTEBOOK.relative_to(ROOT)}: {count} file code, {len(data) / 1024:.0f} KB nén, '
          f'sha256 {hashlib.sha256(data).hexdigest()[:12]}')


def main():
    targets = sys.argv[1:] or ['kaggle', 'teach']
    unknown = set(targets) - {'kaggle', 'teach'}
    if unknown:
        raise SystemExit(f'Unknown notebook(s): {sorted(unknown)}; choose kaggle and/or teach.')
    if 'kaggle' in targets:
        build_kaggle()
    if 'teach' in targets:
        build_teach()


if __name__ == '__main__':
    main()
