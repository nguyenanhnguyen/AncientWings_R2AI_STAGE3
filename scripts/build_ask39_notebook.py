"""Build a self-contained ask.39.net check notebook from production snapshots."""
import base64
import hashlib
import json
from pathlib import Path
import pprint
import zlib

import nbformat as nbf
from build_pubmed_efetch_notebook import literals

ROOT = Path(__file__).resolve().parents[1]


def main():
    production = json.loads((ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
    pack = {}
    for cell in production['cells']:
        if cell['cell_type'] == 'code':
            pack.update({k: v for k, v in literals(''.join(cell['source'])).items()
                         if k in ('EMBEDDED_FILES', 'EMBEDDED_SHA256')})
    minimal = json.dumps({'cells': [{'cell_type': 'code', 'source':
        [k+' = '+pprint.pformat(v)+'\n' for k, v in pack.items()]}]}).encode()
    helper = (ROOT/'scripts/check_ask39.py').read_bytes()
    audit = (ROOT/'scripts/ask39_audit.py').read_bytes()
    parser = (ROOT/'scripts/ask39.py').read_bytes()
    gate = (ROOT/'scripts/ask39_gate.py').read_bytes()
    f5 = (ROOT/'scripts/ask39_f5.py').read_bytes()
    dns = (ROOT/'scripts/ask39_dns.py').read_bytes()
    payloads = {name: (base64.b85encode(zlib.compress(body, 9)).decode(), hashlib.sha256(body).hexdigest())
                for name, body in [('pack.ipynb', minimal), ('check_ask39.py', helper), ('ask39_audit.py', audit), ('ask39.py', parser), ('ask39_gate.py',gate), ('ask39_f5.py',f5), ('ask39_dns.py',dns)]}
    cells = [nbf.v4.new_markdown_cell('''# ask.39.net — kiểm tra 50 URL từ corpus

Bật **Internet**, không cần GPU. Notebook độc lập, nhúng snapshot bộ crawl/trích xuất của corpus chính.
Giữ nguyên ID/URL nguồn; lấy mẫu phân tầng scheme/path với seed cố định. Requests trước,
Selenium tối đa 3 URL lỗi hoặc QC cần review. Lưu raw HTML, record, manifest/hash, summary, báo cáo và ZIP.
Không upload Hugging Face. QC chung chưa xác minh ranh giới câu hỏi/câu trả lời; cần review trước khi nhập corpus.
Mỗi lần chạy tạo thư mục mới; không hỗ trợ resume trong check này.
'''), nbf.v4.new_code_cell('''from pathlib import Path
from datetime import datetime, timezone
import sys

SOURCE_PARQUET = None  # Hoặc đường dẫn Parquet local có cột id, url
MODE = 'replay_fix_e'  # baseline đóng băng + candidate hiện tại; crawl_new: tải URL mới
LIMIT = 50
SEED = 20261021
DELAY = 2.0
ATTEMPTS = 2
BROWSER_LIMIT = 3
RESPECT_ROBOTS = False  # Cùng mặc định check domain hiện tại
TRUST_ENV = False
WORKDIR = Path('/kaggle/working') if sys.platform.startswith('linux') and Path('/kaggle/working').is_dir() else Path.cwd()
RUN_DIR = WORKDIR/'runs'/datetime.now(timezone.utc).strftime('check_ask39_%Y%m%dT%H%M%S%fZ')
'''), nbf.v4.new_code_cell('''import importlib.util
import subprocess
needed = {'pyarrow':'pyarrow', 'requests':'requests', 'trafilatura':'trafilatura',
          'pymupdf':'pymupdf', 'tld':'tld', 'lxml':'lxml', 'selenium':'selenium',
          'huggingface_hub':'huggingface_hub'}
missing = [package for module,package in needed.items() if importlib.util.find_spec(module) is None]
if missing: subprocess.run([sys.executable,'-m','pip','install','--quiet',*missing],check=True)
'''), nbf.v4.new_code_cell('PAYLOADS = '+repr(payloads)+'''
import base64
import hashlib
import json
import zlib
SUPPORT_DIR = WORKDIR/'runs'/'_ask39_support'/PAYLOADS['ask39.py'][1][:12]/PAYLOADS['pack.ipynb'][1][:12]
SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
for name,(payload,expected) in PAYLOADS.items():
    body = zlib.decompress(base64.b85decode(payload))
    if hashlib.sha256(body).hexdigest()!=expected: raise ValueError('Snapshot hash mismatch: '+name)
    (SUPPORT_DIR/name).write_bytes(body)
spec = importlib.util.spec_from_file_location('ask39_check', SUPPORT_DIR/'check_ask39.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
'''), nbf.v4.new_code_cell('''if SOURCE_PARQUET:
    SOURCE_PATH = Path(SOURCE_PARQUET)
else:
    from huggingface_hub import hf_hub_download
    SOURCE_PATH = Path(hf_hub_download(repo_id='AIGuruTinix/ViBioMIR',repo_type='dataset',
        filename='links_corpus_vi_en_zh.parquet',revision='71be0e1239a19dfd7a717e2bc13e3bec21bd0334'))
    with SOURCE_PATH.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!='87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7':
        raise ValueError('Downloaded source hash mismatch')
args = ['--source',str(SOURCE_PATH),'--notebook',str(SUPPORT_DIR/'pack.ipynb'),
        '--out',str(RUN_DIR),'--limit',str(LIMIT),'--seed',str(SEED),'--delay',str(DELAY),
        '--attempts',str(ATTEMPTS),'--browser-limit',str(BROWSER_LIMIT)]
if RESPECT_ROBOTS: args.append('--respect-robots')
if TRUST_ENV: args.append('--trust-env')
try:
    SUMMARY = check.main(args)
finally:
    if RUN_DIR.is_dir():
        if (RUN_DIR/'results.jsonl').is_file():
            audit_spec = importlib.util.spec_from_file_location('ask39_audit', SUPPORT_DIR/'ask39_audit.py')
            audit = importlib.util.module_from_spec(audit_spec)
            audit_spec.loader.exec_module(audit)
            DOM_AUDIT = audit.run(RUN_DIR)
            print('DOM audit:', DOM_AUDIT)
        import shutil
        ARCHIVE = Path(shutil.make_archive(str(RUN_DIR),'zip',root_dir=RUN_DIR))
        print('Saved evidence:', ARCHIVE)
'''), nbf.v4.new_code_cell('''from IPython.display import FileLink, display
display(SUMMARY)
display(DOM_AUDIT)
for path in [RUN_DIR/'report.md', RUN_DIR/'summary.json', RUN_DIR/'dom_audit_summary.json', ARCHIVE]:
    display(FileLink(str(path)))
''')]
    # F1 regression cases and assertions live in the check notebook, as requested.
    # Preserve their source and saved execution evidence when refreshing payloads.
    target = ROOT/'notebooks/check_ask.39.net.ipynb'
    previous = nbf.read(target, as_version=4) if target.exists() else None
    f1_cells = [cell for cell in previous.cells if set(cell.metadata.get('tags', [])).intersection({'ask39-f1', 'ask39-f2', 'ask39-f3', 'ask39-f4', 'ask39-f5', 'ask39-fix-a', 'ask39-fix-b', 'ask39-fix-c', 'ask39-fix-d', 'ask39-fix-e', 'ask39-e-confirmation', 'ask39-transport-dns', 'ask39-d-baseline-setup', 'ask39-e-baseline-setup', 'ask39-fix-content', 'ask39-content-baseline-setup', 'ask39-fix-superlative', 'ask39-replay-649', 'ask39-transport-2458259', 'ask39-holdout650', 'ask39-holdout850', 'ask39-ui-historical-setup', 'ask39-fix-followup-ui', 'ask39-rating-baseline-setup', 'ask39-fix-patient-evaluations', 'ask39-product-baseline-setup', 'ask39-fix-product-claims', 'ask39-org-baseline-setup', 'ask39-fix-source-policy', 'ask39-replay850-baseline', 'ask39-replay850', 'ask39-identity-a-setup'})] if previous else []
    baseline_pack = None
    if previous:
        for cell in previous.cells:
            if 'ask39-baseline-setup' in cell.metadata.get('tags',[]):
                baseline_pack = literals(cell.source)['BASELINE_PAYLOADS']
                break
        if baseline_pack is None:
            baseline_pack = next(literals(c.source)['PAYLOADS'] for c in previous.cells
                                 if c.cell_type=='code' and 'PAYLOADS' in literals(c.source))
    if baseline_pack is None: raise ValueError('Existing F5 baseline notebook is required')
    baseline_cell = nbf.v4.new_code_cell('BASELINE_PAYLOADS = '+repr(baseline_pack)+'''
# Legacy F1–F5 assertions reproduce the frozen parser/gate, independent of V2.
CANDIDATE_PAYLOADS, CANDIDATE_SUPPORT_DIR = PAYLOADS, SUPPORT_DIR
BASELINE_SUPPORT_DIR = WORKDIR/'runs'/'_ask39_baseline_support'/BASELINE_PAYLOADS['ask39.py'][1][:12]
BASELINE_SUPPORT_DIR.mkdir(parents=True,exist_ok=True)
for name,(payload,expected) in BASELINE_PAYLOADS.items():
    body=zlib.decompress(base64.b85decode(payload))
    if hashlib.sha256(body).hexdigest()!=expected: raise ValueError('Baseline snapshot mismatch: '+name)
    (BASELINE_SUPPORT_DIR/name).write_bytes(body)
PAYLOADS,SUPPORT_DIR = BASELINE_PAYLOADS,BASELINE_SUPPORT_DIR
spec=importlib.util.spec_from_file_location('ask39_frozen_check',SUPPORT_DIR/'check_ask39.py')
check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
''')
    baseline_cell.metadata['tags']=['ask39-baseline-setup']
    cells[0].source += '\n\nF4: QC theo raw/DOM trước mỗi lần xuất candidate Parquet local; thiếu answer/follow-up phải REVIEW. Chưa release corpus production. Mặc định replay/test offline 50 HTML nhúng trong notebook.\n'
    cells[4].source = "if MODE == 'crawl_new':\n" + '\n'.join('    '+line for line in cells[4].source.splitlines())
    cells[5].source = "if MODE == 'crawl_new':\n" + '\n'.join('    '+line for line in cells[5].source.splitlines())
    cells[4:4] = [baseline_cell, *f1_cells]
    notebook = nbf.v4.new_notebook(cells=cells, metadata={'kernelspec':
        {'display_name':'Python 3','language':'python','name':'python3'}})
    nbf.validate(notebook)
    for cell in cells:
        if cell.cell_type == 'code': compile(cell.source, '<ask39 notebook>', 'exec')
    nbf.write(notebook, target)
    print(target)


if __name__ == '__main__':
    main()

