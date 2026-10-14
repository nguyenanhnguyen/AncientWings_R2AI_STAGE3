"""Generate a self-contained Kaggle smoke notebook from the main production snapshots."""
import base64
import argparse
import hashlib
import json
from pathlib import Path
import pprint
import zlib

import nbformat as nbf
from build_pubmed_efetch_notebook import literals

ROOT = Path(__file__).resolve().parents[1]


def main(output=None):
    main_nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
    pack = literals(''.join(main_nb['cells'][6]['source']))
    minimal = {'cells': [{'source': []} for _ in range(7)]}
    minimal['cells'][6]['source'] = [key + ' = ' + pprint.pformat(pack[key]) + '\n'
                                   for key in ('EMBEDDED_FILES', 'EMBEDDED_SHA256')]
    packed = json.dumps(minimal).encode()
    helper = (ROOT / 'scripts/check_longchau.py').read_bytes()
    encode = lambda body: base64.b85encode(zlib.compress(body, 9)).decode()
    cells = [nbf.v4.new_markdown_cell('''# Long Châu — thử 50 URL thật từ corpus

Bật **Internet**, không cần GPU hoặc Chrome. Run All để chọn **50 URL duy nhất**, seed `20261014`,
phân tầng `/bai-viet/`, `/benh/`, đuôi ID số/còn lại; loại 3 bài fixture. Giữ ID/URL nguồn.
Notebook nhúng đúng fetcher/parser/runner/auditor/exporter của corpus chính. Không upload Hugging Face.

`LIMIT = 100` để thử 100 URL; `MAX_NEW` giới hạn lượt mới. `SOURCE_PARQUET` có thể trỏ đến nguồn
`missing_links.parquet` hoặc `links_corpus_vi_en_zh.parquet` có cột `id`, `url`.
Mặc định tải nguồn ViBioMIR 1.220.598 URL đã ghim revision/hash. Hậu tố số URL không chứng minh tuổi bài.
Ngày xuất bản/cập nhật được lấy từ metadata đúng bài và ghi trong báo cáo.

`RESUME_RUN_DIR` tiếp tục cùng code/cấu hình/mẫu; lỗi Long Châu được thử lại, success hợp lệ giữ nguyên.
Đổi code/cấu hình: dùng `RUN_TAG` mới và `RECOVERY_RUN_DIR` để tái trích raw HTTP 200 đã xác minh hash.
Giữ thư mục run đầy đủ hoặc ZIP đầy đủ; ZIP diagnostics chỉ chứa một số raw mẫu.
'''), nbf.v4.new_code_cell('''from pathlib import Path
import os
import sys

SOURCE_PARQUET = None       # Hoặc '/kaggle/input/.../missing_links.parquet'
LIMIT = 50
SEED = 20261014
ID_FROM = None              # Hai đầu inclusive; None không lọc ID
ID_TO = None
MAX_NEW = None
DELAY = 5.0                 # 1 worker cố định; vẫn tôn trọng Retry-After/cooldown
ATTEMPTS = 3
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 45.0
REQUEST_BUDGET = 180.0
RESPECT_ROBOTS = False      # Giống cấu hình corpus chính; True giữ cơ chế robots
RUN_TAG = 'longchau_50_seed20261014_v1'
RESUME_RUN_DIR = None
RECOVERY_RUN_DIR = None
WORKDIR = Path('/kaggle/working') if Path('/kaggle/working').exists() else Path.cwd()

if sys.version_info < (3, 11): raise RuntimeError('Yêu cầu Python 3.11 trở lên')
if RESUME_RUN_DIR and RECOVERY_RUN_DIR: raise ValueError('Chỉ chọn resume hoặc recovery')
if not RUN_TAG or RUN_TAG in ('.','..') or any(s in RUN_TAG for s in ('/',chr(92))):
    raise ValueError('RUN_TAG phải là tên thư mục')
if type(LIMIT) is not int or LIMIT < 1: raise ValueError('LIMIT phải là số nguyên dương')
RUN_DIR = WORKDIR / 'runs' / RUN_TAG
RUN_DIR.parent.mkdir(parents=True,exist_ok=True)
'''), nbf.v4.new_code_cell('''import subprocess
subprocess.run([sys.executable,'-m','pip','install','--quiet','pyarrow','requests','trafilatura',
                'pymupdf','tld','lxml','curl_cffi','huggingface_hub','ipython'],check=True)
''')]
    setup = '\n'.join([f"PACK_PAYLOAD = {encode(packed)!r}", f"PACK_SHA256 = {hashlib.sha256(packed).hexdigest()!r}",
                       f"HELPER_PAYLOAD = {encode(helper)!r}", f"HELPER_SHA256 = {hashlib.sha256(helper).hexdigest()!r}"])
    setup += '''
import base64
import hashlib
import importlib.util
import shutil
import zlib

SUPPORT_DIR = WORKDIR / '_longchau_smoke_support' / PACK_SHA256[:12]
SUPPORT_DIR.mkdir(parents=True,exist_ok=True)
for name,payload,expected in [('smoke_pack.ipynb',PACK_PAYLOAD,PACK_SHA256),
                              ('check_longchau.py',HELPER_PAYLOAD,HELPER_SHA256)]:
    body=zlib.decompress(base64.b85decode(payload))
    if hashlib.sha256(body).hexdigest()!=expected: raise ValueError('Snapshot hash mismatch: '+name)
    (SUPPORT_DIR/name).write_bytes(body)
spec=importlib.util.spec_from_file_location('longchau_smoke',SUPPORT_DIR/'check_longchau.py')
smoke=importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
if RESUME_RUN_DIR and Path(RESUME_RUN_DIR).resolve()!=RUN_DIR.resolve():
    if not RUN_DIR.exists(): shutil.copytree(RESUME_RUN_DIR,RUN_DIR)
    else: print('Dùng checkpoint đã có trong output; không ghi đè từ Input.')
print('Output:',RUN_DIR)
'''
    cells.append(nbf.v4.new_code_cell(setup))
    cells.append(nbf.v4.new_code_cell('''if SOURCE_PARQUET:
    SOURCE_PATH=Path(SOURCE_PARQUET)
    if not SOURCE_PATH.is_file(): raise FileNotFoundError(SOURCE_PATH)
else:
    from huggingface_hub import hf_hub_download
    token=os.environ.get('HF_TOKEN')
    if not token:
        try:
            from kaggle_secrets import UserSecretsClient
            token=UserSecretsClient().get_secret('HF_TOKEN')
        except Exception: token=None
    SOURCE_PATH=Path(hf_hub_download(repo_id='AIGuruTinix/ViBioMIR',repo_type='dataset',
        filename='links_corpus_vi_en_zh.parquet',revision='71be0e1239a19dfd7a717e2bc13e3bec21bd0334',token=token))
    with SOURCE_PATH.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!='87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7':
        raise ValueError('Nguồn tải về khác hash đã ghim')
samples,selection=smoke.select(SOURCE_PATH,LIMIT,SEED,ID_FROM,ID_TO)
print('Nguồn:',SOURCE_PATH,'; số URL nguồn:',selection['source_rows'])
print('Phân tầng:',selection['selected_strata'],'; chọn:',len(samples))
print(selection['date_note'])
'''))
    cells.append(nbf.v4.new_code_cell('''from IPython.display import FileLink, display
try:
    smoke.run(SOURCE_PATH,SUPPORT_DIR/'smoke_pack.ipynb',RUN_DIR,limit=LIMIT,seed=SEED,
        id_from=ID_FROM,id_to=ID_TO,max_new=MAX_NEW,delay=DELAY,attempts=ATTEMPTS,
        timeout=(CONNECT_TIMEOUT,READ_TIMEOUT),budget=REQUEST_BUDGET,
        respect_robots=RESPECT_ROBOTS,recovery_source=RECOVERY_RUN_DIR)
finally:
    for path in (Path(str(RUN_DIR)+'.zip'),Path(str(RUN_DIR)+'_diagnostics.zip')):
        if path.is_file(): display(FileLink(str(path)))
'''))
    cells.append(nbf.v4.new_markdown_cell('''`longchau_results.csv/jsonl` ghi HTTP, QC, parser/selector, tác giả/ngày,
số heading/block, lý do review và 600 ký tự đầu/cuối. `records/` giữ **text đầy đủ**, raw gốc ở `raw/`;
`corpus.parquet/jsonl` chỉ xuất accepted. `review_100.html` đặt tham chiếu raw cạnh corpus để đọc kiểm tra.
`longchau_summary.json`, `source_profile.json`, `longchau_selection.json` ghi thống kê/mẫu.
ZIP đầy đủ chứa cả review/error/raw, tách riêng corpus chính. Nếu ngắt hoặc dùng `MAX_NEW`, resume để đủ mẫu
trước audit/export. PASS tự động chưa phải đánh giá chuyên gia hay bằng chứng IP Kaggle không bị chặn.
'''))
    nb = nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}})
    for cell in cells:
        if cell.cell_type=='code': compile(cell.source,'check_longchau_50.ipynb','exec')
    for index,cell in enumerate(cells): cell.id=f'longchau-smoke-{index}'
    output = Path(output) if output is not None else ROOT/'notebooks/check_longchau_50.ipynb'
    output.parent.mkdir(parents=True, exist_ok=True)
    nbf.write(nb,output)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, help='Output notebook; default is ignored notebooks/check_longchau_50.ipynb')
    main(parser.parse_args().out)
