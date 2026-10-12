"""Embed this repository's code into the Kaggle notebooks, so Kaggle runs exactly the laptop code.

    kaggle   writes notebooks/pipeline_for_kaggle.ipynb: inference, data from Hugging Face.
    teach    refreshes the code cell of notebooks/teach_kaggle.ipynb (block T, paused).

src/ and scripts/vibiomir.py are zipped (fixed timestamps: same code, same bytes) and
base64-embedded in one cell. After any code change: rerun this script and upload the notebook.

    python scripts/build_notebooks.py            # both
    python scripts/build_notebooks.py kaggle     # only pipeline_for_kaggle.ipynb
"""
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks' / 'pipeline_for_kaggle.ipynb'
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


INTRO = """# ViBioMIR: corpus HF → bài nộp, không khối T

Cùng kiến trúc với local; riêng Kaggle dùng hai model Qwen3 4B, không khối T:

1. Ghim commit HF; tải shard giao khoảng ID, lọc **ID nguồn, bao gồm hai đầu**, rồi mới giới hạn số dòng.
2. Làm sạch → chunk theo đoạn/câu, mục tiêu 384 token, overlap 64, giữ vị trí nguồn.
3. BM25 đa ngôn ngữ + **Qwen/Qwen3-Embedding-4B** trên toàn corpus đã chọn.
4. Query gốc + từ khóa bằng quy tắc → RRF → tối đa 3 chunk/doc trong tập rerank.
5. **Qwen/Qwen3-Reranker-4B**, một lượt chấm yes/no; không sinh văn bản, dịch, feedback, ensemble hoặc train.
6. Heuristic F2 (chưa hiệu chỉnh khi không có nhãn dev), trích đoạn nguồn, validate đủ truy vấn → ZIP.

Hai GPU chia dữ liệu encode và chia truy vấn rerank **không trùng nhau**. Không có hai vòng rerank.
Mỗi GPU giữ một bản model FP16; encoder được giải phóng trước khi nạp reranker. SDPA, không FlashAttention 2/BF16.
4B được chọn để chừa VRAM cho batch trên T4; 8B FP16 gần hết VRAM chỉ với trọng số. Không tự hạ xuống BGE.
Model đã ghim revision. Cấu hình local vẫn BGE-M3 + BGE reranker.
Nguồn: [Embedding-4B](https://huggingface.co/Qwen/Qwen3-Embedding-4B),
[Reranker-4B](https://huggingface.co/Qwen/Qwen3-Reranker-4B).
Dense mặc định tìm chính xác. `USE_ANN=True` dùng FAISS IVF xấp xỉ; báo overlap với exact trên 5 query variants mỗi shard, không phải Recall nhãn đúng. ANN không giảm thời gian encode.

**Settings:** Internet bật, GPU T4 x2, Secret `HF_TOKEN` có quyền đọc dataset nhóm.
Đổi ID ở ô đầu; khoảng mặc định là ví dụ từ batch local trước. ID không liên tục, không phải số thứ tự dòng.
`LIMIT_ROWS` là trần sau lọc ID, trước lọc chất lượng; 0 = hết khoảng đã chọn.

**Thời gian:** ngân sách là giờ thực từ ô cấu hình, không phải quota GPU còn lại của tài khoản.
Đặt thấp hơn thời gian phiên và quota còn lại hiển thị trên Kaggle, chừa thời gian Save Version.
Chưa đo tốc độ T4 với corpus này; không đảm bảo xong trong ngân sách. Hết giờ dừng mã 124, giữ checkpoint.
4B tốn thời gian encode/rerank hơn BGE, không thể suy ra điểm thi từ số tham số hoặc benchmark công bố.
Hai bộ trọng số tải lần đầu khoảng 16 GB. Cache model nằm ở `/kaggle/temp/vibiomir_hf_cache`,
không đóng vào Output; phiên mới có thể cần tải lại. Corpus/index/checkpoint vẫn ở `/kaggle/working`.

**Chạy tiếp:** cùng phiên chạy lại ô pipeline. Qua phiên mới, Save Version giữ Output, gắn Output cũ vào Input,
đặt `RESTORE_RUN` tới thư mục run cũ. Giữ nguyên `RUN_NAME`, ID, code, số GPU, thư viện và cấu hình.
Không restore run BGE cũ vào run Qwen4B: embedding khác model cần dựng lại index.
Notebook không tự upload checkpoint lên HF. Đổi ID/commit cần tên run mới và `RESTORE_RUN=None`.

Chỉ khi hoàn tất mới xuất `/kaggle/working/submission.zip`. Sửa source rồi chạy
`python scripts/build_notebooks.py kaggle` để cập nhật code nhúng."""

CONFIG = """# ===== INPUT: ĐỔI HAI ID TRƯỚC KHI RUN ALL =====
ID_START = 504799                    # ID đầu, inclusive; None = không chặn đầu
ID_END = 568887                      # ID cuối, inclusive; None = không chặn cuối
LIMIT_ROWS = 100000                  # trần số dòng trong khoảng; 0 = hết khoảng
HF_CORPUS_REPO = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
HF_CORPUS_REVISION = None            # ghim commit mới nhất khi khởi tạo RUN

# ===== NGÂN SÁCH / CHẤT LƯỢNG =====
MAX_WALL_HOURS = 8.0                 # chỉnh theo thời gian/quota thật còn lại
MAX_GPUS = 2                        # 1 hoặc 2; giữ nguyên khi resume
ENCODER = 'qwen3-embedding-4b'
RERANKER = 'qwen3-reranker-4b'        # duy nhất một reranker, không teacher
RERANK_K = 60                        # 1.200 query × 60 = tối đa 72.000 cặp mới
ENCODER_BATCH = 16                   # FP16; tự hạ batch nếu CUDA OOM
RERANK_BATCH = 8
USE_ANN = False                      # True: FAISS IVF xấp xỉ; encode vẫn như cũ
NPROBE = 64
WINDOW_TOKENS = 0                    # giữ chunk đã chấm, không tự mở rộng
CALIBRATION = None                  # calibration từ nhãn dev độc lập, nếu có
RESTORE_RUN = None                  # ví dụ '/kaggle/input/previous-output/run_...'
RUN_NAME = f'run_qwen4b_{ID_START}_{ID_END}_n{LIMIT_ROWS}'  # run mới, không ghi đè BGE

import os, time, math
from pathlib import Path
if 'SESSION_STARTED' not in globals():
    SESSION_STARTED = time.monotonic()  # không reset khi Run All trong cùng kernel
if not math.isfinite(MAX_WALL_HOURS) or MAX_WALL_HOURS <= 0:
    raise ValueError('MAX_WALL_HOURS phải hữu hạn và > 0.')
if MAX_GPUS not in (1, 2):
    raise ValueError('MAX_GPUS phải là 1 hoặc 2.')
if ID_START is not None and ID_END is not None and ID_START > ID_END:
    raise ValueError('ID_START phải <= ID_END.')

def seconds_left():
    left = MAX_WALL_HOURS * 3600 - (time.monotonic() - SESSION_STARTED)
    if left <= 0:
        raise RuntimeError('Hết ngân sách đã đặt. Giữ Output để chạy tiếp phiên sau.')
    return left

WORK = Path('/kaggle/working')
CODE_DIR = WORK / 'vibiomir_code'
RUN = WORK / RUN_NAME
MODEL_CACHE = Path('/kaggle/temp/vibiomir_hf_cache')
MODEL_CACHE.mkdir(parents=True, exist_ok=True)
os.environ['HF_HOME'] = str(MODEL_CACHE)
os.environ['HF_HUB_CACHE'] = str(MODEL_CACHE / 'hub')
os.environ['HF_HUB_ETAG_TIMEOUT'] = '30'
os.environ['HF_HUB_DOWNLOAD_TIMEOUT'] = '60'
os.environ['TOKENIZERS_PARALLELISM'] = 'false'
PIPELINE_COMPLETE = False
(WORK / 'submission.zip').unlink(missing_ok=True)
print('IDs:', ID_START, '→', ID_END, '| row cap:', LIMIT_ROWS, '| RUN:', RUN)"""

INSTALL = """import importlib.metadata, subprocess, sys, shutil

def version(name):
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None

# Giữ torch CUDA có sẵn; không tải lại wheel torch nhiều GB.
need = []
current = version('transformers')
major_minor = tuple(int(x) for x in current.split('.')[:2]) if current else (0, 0)
if not (4, 51) <= major_minor < (5, 0):
    need.append('transformers>=4.51,<5')
current_accelerate = version('accelerate')
if not current_accelerate or tuple(int(x) for x in current_accelerate.split('.')[:2]) < (1, 6):
    need.append('accelerate>=1.6')  # tải 4B trực tiếp vào GPU, giảm đỉnh RAM CPU
for package in ('numpy', 'pyarrow', 'huggingface-hub', 'sentencepiece', 'protobuf'):
    if version(package) is None:
        need.append(package)
if USE_ANN and version('faiss-cpu') is None:
    need.append('faiss-cpu>=1.8,<2')
if need:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', *need],
                   check=True, timeout=seconds_left())
try:
    from kaggle_secrets import UserSecretsClient
    os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')
    print('Đã nạp HF_TOKEN (không in token).')
except Exception:
    if not os.environ.get('HF_TOKEN'):
        raise RuntimeError('Thêm Secret HF_TOKEN có quyền đọc dataset nhóm rồi chạy lại.')

import torch
GPUS = min(torch.cuda.device_count(), MAX_GPUS)
print('torch', torch.__version__, '| transformers', version('transformers'), '| GPU:',
      [torch.cuda.get_device_name(i) for i in range(GPUS)])
if GPUS == 0:
    raise RuntimeError('Bật Accelerator GPU trong Settings.')
vram = [torch.cuda.get_device_properties(i).total_memory / 2**30 for i in range(GPUS)]
if min(vram) < 14:
    raise RuntimeError(f'Profile Qwen4B cần GPU khoảng 16 GB/card; đang có {vram}. Chọn T4 x2.')
print('Models:', ENCODER, '+', RERANKER, '| fp16 | VRAM GiB:', vram)
print('Model cache (không lưu trong Output):', MODEL_CACHE)
if RESTORE_RUN and not RUN.exists():
    previous = Path(RESTORE_RUN)
    if not (previous / 'pipeline_status.json').is_file():
        raise ValueError('RESTORE_RUN phải trỏ vào thư mục run, không phải Output cha.')
    import json
    old = json.loads((previous / 'pipeline_config.json').read_text(encoding='utf-8'))
    if old.get('encoder') != ENCODER or old.get('reranker') != RERANKER:
        raise ValueError('Run restore dùng model khác. Với Qwen4B, bắt đầu run mới hoặc chọn checkpoint Qwen4B.')
    # copyfile keeps the destination writable even when Input files are read-only.
    shutil.copytree(previous, RUN, copy_function=shutil.copyfile)
    print('Đã khôi phục run:', RUN)
seconds_left()"""

RUN_CELL = """# Chạy thật một cấu hình, không mock hoặc suite ablation.
PIPELINE_COMPLETE = False
(WORK / 'submission.zip').unlink(missing_ok=True)
command = [sys.executable, '-u', str(CODE_DIR / 'scripts' / 'vibiomir.py'), 'pipeline',
           '--profile', 'kaggle', '--architecture', 'full', '--skip-translation',
           '--gpus', str(GPUS), '--source', 'hf', '--hf-repo', HF_CORPUS_REPO,
           '--encoder', ENCODER, '--reranker', RERANKER,
           '--out', str(RUN), '--limit', str(LIMIT_ROWS), '--rerank-k', str(RERANK_K),
           '--encoder-batch', str(ENCODER_BATCH), '--rerank-batch', str(RERANK_BATCH),
           '--window-tokens', str(WINDOW_TOKENS), '--max-hours', str(seconds_left() / 3600)]
for flag, value in (('--id-start', ID_START), ('--id-end', ID_END),
                    ('--hf-revision', HF_CORPUS_REVISION), ('--calibration', CALIBRATION)):
    if value is not None:
        command += [flag, str(value)]
if USE_ANN:
    command += ['--ann', '--nprobe', str(NPROBE)]
env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
process = subprocess.Popen(command, cwd=CODE_DIR, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
try:
    for line in process.stdout:
        print(line, end='', flush=True)
    result = process.wait()
except BaseException:
    import signal
    process.send_signal(signal.SIGINT)
    process.wait()
    raise
finally:
    process.stdout.close()
if result == 124:
    print('Hết ngân sách; CHƯA có bài nộp mới. Save Version giữ Output để tiếp tục.')
elif result:
    raise RuntimeError(f'Pipeline lỗi mã {result}; xem {RUN / "logs"}')
else:
    PIPELINE_COMPLETE = True"""

RESULT_CELL = """import json, hashlib, shutil
from IPython.display import FileLink, display

status_path = RUN / 'pipeline_status.json'
status = json.loads(status_path.read_text(encoding='utf-8')) if status_path.exists() else {}
if PIPELINE_COMPLETE and status.get('status') == 'complete':
    source = RUN / 'submission' / 'submission.zip'
    if hashlib.sha256(source.read_bytes()).hexdigest() != status['submission_sha256']:
        raise ValueError('ZIP không khớp kết quả đã hoàn tất.')
    shutil.copyfile(source, WORK / 'submission.zip')
    prepared = json.loads((RUN / 'corpus' / 'prepare_manifest.json').read_text(encoding='utf-8'))
    manifest = json.loads((RUN / 'submission' / 'submission_manifest.json').read_text(encoding='utf-8'))
    print('Corpus giữ lại:', prepared['documents_kept'], '| ID thực tế:',
          prepared['id_min'], '→', prepared['id_max'])
    print(json.dumps(manifest['submission'], ensure_ascii=False, indent=2))
    display(FileLink('submission.zip'))
    print('File nộp: /kaggle/working/submission.zip')
else:
    print('CHƯA HOÀN TẤT:', status.get('status', 'chưa chạy'), '| checkpoint:', RUN)
    print('Save Version giữ Output; phiên mới gắn Output vào Input và đặt RESTORE_RUN.')"""


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
