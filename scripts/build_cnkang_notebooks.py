"""Build standalone cnkang check; synchronize parser/transport with corpus."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

from build_pubmed_efetch_notebook import literals, replace_literals
from build_domain_samples_notebook import replace

ROOT = Path(__file__).resolve().parents[1]


def encode(body):
    return base64.b85encode(zlib.compress(body, 9)).decode('ascii')


def write(nb, path):
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), str(path), 'exec')
            cell.update(execution_count=None, outputs=[])
    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def core_upgrade(body):
    text = body.decode('utf-8')
    if 'def cnkang_module():' not in text:
        loader = '''
def cnkang_module():
    name = 'crawler_cnkang_' + digest(str(Path(__file__).resolve()).encode())[:8]
    if name not in sys.modules:
        path = Path(__file__).with_name('cnkang_snapshot.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]

'''
        text = text.replace('\ndef extract(body, content_type, url):',
                            loader + '\ndef extract(body, content_type, url):', 1)
        text = text.replace('def extract(body, content_type, url):\n',
            "def extract(body, content_type, url):\n"
            "    if host(url) == 'cnkang.com' or host(url).endswith('.cnkang.com'):\n"
            "        return cnkang_module().extract(body, url, content_type)\n", 1)
        text = text.replace('def quality(doc):\n',
            "def quality(doc):\n"
            "    if doc.get('extractor') == 'cnkang_v6_spec_dom':\n"
            "        return {key: doc[key] for key in ('quality_status', 'quality_flags', 'char_count', 'text_sha256')}\n", 1)
    return text.encode('utf-8')


def synchronize():
    path = ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb'
    nb = json.loads(path.read_text(encoding='utf-8'))
    get = lambda i: ''.join(nb['cells'][i]['source'])
    def put(i, source): nb['cells'][i]['source'] = source.splitlines(keepends=True)
    pack = literals(get(6))
    updates = {
        'crawler_snapshot.py': core_upgrade(zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['crawler_snapshot.py']))),
        'cnkang_snapshot.py': (ROOT / 'scripts/cnkang.py').read_bytes(),
        'cnkang_transport_snapshot.py': (ROOT / 'scripts/cnkang_transport.py').read_bytes(),
        'corpus_runner_snapshot.py': (ROOT / 'scripts/corpus_runner.py').read_bytes(),
        'audit_snapshot.py': (ROOT / 'scripts/corpus_audit.py').read_bytes(),
    }
    for name, body in updates.items():
        pack['EMBEDDED_FILES'][name] = encode(body)
        pack['EMBEDDED_SHA256'][name] = hashlib.sha256(body).hexdigest()
    setup = replace_literals(get(6), {k:pack[k] for k in ('EMBEDDED_FILES','EMBEDDED_SHA256')})
    if 'HAS_CNKANG_SAMPLE =' not in setup:
        guard = '''
HAS_CNKANG_SAMPLE = False
if (RUN_DIR / 'sample.jsonl').exists():
    from urllib.parse import urlsplit
    with (RUN_DIR / 'sample.jsonl').open(encoding='utf-8') as stream:
        HAS_CNKANG_SAMPLE = any(
            (urlsplit(json.loads(line)['url']).hostname or '').lower() == 'cnkang.com'
            or (urlsplit(json.loads(line)['url']).hostname or '').lower().endswith('.cnkang.com')
            for line in stream if line.strip())
if not POSTPROCESS_ONLY and HAS_CNKANG_SAMPLE and (RUN_DIR / 'corpus_config.json').exists():
    saved_cnkang = json.loads((RUN_DIR / 'corpus_config.json').read_text(encoding='utf-8'))
    for name, key in (('cnkang_snapshot.py','cnkang_sha256'),
                      ('cnkang_transport_snapshot.py','cnkang_transport_sha256'),
                      ('crawler_snapshot.py','crawler_sha256'), ('corpus_runner_snapshot.py','runner_sha256')):
        if saved_cnkang.get(key) != EMBEDDED_SHA256[name]:
            raise ValueError('Run cnkang cũ cần RUN_TAG mới + RECOVERY_RUN_PATH; giữ nguyên raw/checkpoint cũ.')

'''
        setup = setup.replace('HAS_ASK120_SAMPLE = False', guard + 'HAS_ASK120_SAMPLE = False', 1)
    put(6, setup)
    config = get(2)
    if 'CNKANG_REQUEST_GAP =' not in config:
        config = config.replace('BROWSER_TEST_MODE =',
            "CNKANG_REQUEST_GAP = 1.5  # 1 worker, robots luôn bật, không chạy Selenium\n"
            "CNKANG_ATTEMPTS = 2\nCNKANG_CONNECT_TIMEOUT = 10.0\nCNKANG_READ_TIMEOUT = 30.0\n"
            "CNKANG_USER_AGENT = 'ViBioMIR-CnkangCheck/1.0'\n\nBROWSER_TEST_MODE =", 1)
    put(2, config)
    crawl = get(12)
    if "'cnkang':" not in crawl:
        crawl = crawl.replace("'longchau_use_curl': LONGCHAU_USE_CURL,",
            "'longchau_use_curl': LONGCHAU_USE_CURL,\n"
            "            'cnkang': {'gap': CNKANG_REQUEST_GAP, 'attempts': CNKANG_ATTEMPTS,\n"
            "                       'timeout': [CNKANG_CONNECT_TIMEOUT, CNKANG_READ_TIMEOUT],\n"
            "                       'user_agent': CNKANG_USER_AGENT, 'trust_env': REQUESTS_TRUST_ENV},", 1)
    put(12, crawl)
    note = ('\n\nCnkang dùng chung parser và Requests transport với check_cnkang.com.ipynb: '
            'một worker, gap tối thiểu 1,5 giây, HTTPS trước, robots từng origin, retry/cooldown hữu hạn; '
            'không chạy Selenium. Giữ encoding/body candidates, bảng, text trước/sau và '
            'parser_flags/source_flags riêng. Mã v6 gốc đã lưu trong docs/references/cnkang; '
            'chưa có raw 120 trang để chứng minh tương đương baseline cũ. '
            'Run cũ dùng RUN_TAG mới + RECOVERY_RUN_PATH để tái trích raw, không ép resume.\n')
    if 'Cnkang dùng chung parser' not in get(11): put(11, get(11).rstrip() + note)
    write(nb, path)
    path = ROOT / 'notebooks/crawl_domain_samples.ipynb'
    nb = json.loads(path.read_text(encoding='utf-8'))
    setup = ''.join(nb['cells'][7]['source'])
    values = literals(setup)
    core = core_upgrade(zlib.decompress(base64.b85decode(values['CRAWLER_PAYLOAD'])))
    setup = replace(setup, {
        'CRAWLER_PAYLOAD':encode(core), 'CRAWLER_SHA256':hashlib.sha256(core).hexdigest(),
        'CNKANG_PAYLOAD':encode(updates['cnkang_snapshot.py']),
        'CNKANG_SHA256':hashlib.sha256(updates['cnkang_snapshot.py']).hexdigest()})
    if 'cnkang_path = RUN_DIR' not in setup:
        setup += '''
cnkang_body = zlib.decompress(base64.b85decode(CNKANG_PAYLOAD))
if hashlib.sha256(cnkang_body).hexdigest() != CNKANG_SHA256:
    raise ValueError('cnkang parser hash mismatch')
cnkang_path = RUN_DIR / 'cnkang_snapshot.py'
if cnkang_path.exists() and cnkang_path.read_bytes() != cnkang_body:
    raise ValueError('cnkang parser changed; use a new run and RECOVERY_RUN_DIR')
cnkang_path.write_bytes(cnkang_body)
'''
    nb['cells'][7]['source'] = setup.splitlines(keepends=True)
    write(nb, path)


def build_check():
    cells = []
    def add(kind, text):
        c = {'cell_type':kind,'id':f'cnkang-{len(cells):02d}','metadata':{},
             'source':(text.strip()+'\n').splitlines(keepends=True)}
        if kind == 'code': c.update(execution_count=None,outputs=[])
        cells.append(c)
    add('markdown', '''
# Kiểm tra 500 URL cnkang.com sau khi loại URL đã biết

Kaggle: gắn dataset lighth/r2ai-stage3, bật **Internet**, không cần GPU/Playwright.
Notebook độc lập, nhúng parser và transport dùng chung với crawl chính; output mặc định
/kaggle/working/check_cnkang_com/. Không crawl toàn corpus.

**Mặc định chạy với lịch sử chưa đầy đủ:** loại 60 URL đã biết được nhúng sẵn, cùng
URL trong HISTORY_PATHS hoặc lịch sử tự tìm thấy (nếu có), rồi chọn 500 URL duy nhất.
**Không bảo đảm toàn bộ 500 URL chưa từng được kiểm tra.** Giới hạn này được ghi vào
manifest, history_summary.json, summary.json và review_report.md.
Không cần file Downloads hoặc manifest các session cũ để bắt đầu.
Nếu có thêm lịch sử, gắn output cũ vào Input và đặt HISTORY_PATHS.
Chỉ đặt HISTORY_COMPLETE=True khi đã đủ mọi lượt cũ. Muốn buộc kiểm tra lịch sử đầy đủ,
đặt ALLOW_INCOMPLETE_HISTORY=False.

Chọn tối đa 10 URL mỗi nhánh trước, chia phần còn lại theo dung lượng và phần dư lớn nhất.
Giữ ID gốc, các ID/URL trùng canonical, query/path và manifest bất biến khi resume.
Muốn resume, giữ/gắn **toàn bộ** thư mục output rồi đặt RESUME_FROM hoặc OUTPUT_DIR.
RESUME_FROM copy output gắn dưới Kaggle Input sang Working khi OUTPUT_DIR chưa tồn tại.

Parser port từ v6 được cung cấp, bổ sung QC theo đặc tả. Chưa có raw 120 HTML cũ để
đo tương đương baseline. Các cờ nguồn tách khỏi cờ parser; không đánh giá độ đúng y khoa.
''')
    add('code', '''
# Chỉ cài package thiếu, không nâng cấp rộng môi trường Kaggle.
import importlib.util
import subprocess
import sys
from pathlib import Path
if sys.version_info < (3, 11): raise RuntimeError('Cần Python 3.11+')
required = {'requests':'requests', 'lxml':'lxml', 'pyarrow':'pyarrow',
            'trafilatura':'trafilatura', 'IPython':'ipython'}
missing = [package for name, package in required.items() if importlib.util.find_spec(name) is None]
if missing:
    subprocess.run([sys.executable,'-m','pip','install','--quiet',*missing],check=True)
''')
    add('code', '''
PARQUET_PATH = None  # Tự tìm đúng file theo đặc tả; local: đặt đường dẫn rõ ràng.
HISTORY_PATHS = []  # Ví dụ ['/kaggle/input/my-old-output/cnkang_review_v6']
HISTORY_COMPLETE = False  # True sau khi gắn đủ review/samples manifests các lượt cũ.
ALLOW_INCOMPLETE_HISTORY = True  # Chạy sau khi loại URL đã biết; không bảo đảm chưa từng test.
TARGET_URLS = 500
RANDOM_SEED = 20261020
REQUEST_GAP_SECONDS = 1.5
CONNECT_TIMEOUT = 10.0
READ_TIMEOUT = 30.0
MAX_ATTEMPTS_PER_URL = 2
REQUESTS_TRUST_ENV = False
OUTPUT_DIR = Path('/kaggle/working/check_cnkang_com')
RESUME_FROM = None  # Thư mục run đầy đủ dưới Kaggle Input, copy khi OUTPUT_DIR chưa có.
''')
    files = {name:(ROOT/'scripts'/source).read_bytes() for name,source in (
        ('cnkang_snapshot.py','cnkang.py'),('cnkang_transport_snapshot.py','cnkang_transport.py'),
        ('cnkang_check_snapshot.py','cnkang_check.py'))}
    payloads = {name:encode(body) for name,body in files.items()}
    hashes = {name:hashlib.sha256(body).hexdigest() for name,body in files.items()}
    history = (ROOT/'docs/references/cnkang/known_history_partial.jsonl').read_text(encoding='utf-8')
    add('code', "import base64\nimport hashlib\nimport json\nimport shutil\nimport zlib\n\nPAYLOADS = " +
        repr(payloads) + '\nHASHES = ' + repr(hashes) + '\nBUNDLED_HISTORY = ' + repr(history) + '''

if RESUME_FROM and not OUTPUT_DIR.exists():
    shutil.copytree(Path(RESUME_FROM), OUTPUT_DIR)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
support = OUTPUT_DIR / 'support'
support.mkdir(exist_ok=True)
for name, encoded in PAYLOADS.items():
    body = zlib.decompress(base64.b85decode(encoded))
    if hashlib.sha256(body).hexdigest() != HASHES[name]: raise ValueError('Snapshot corrupted: '+name)
    path = support / name
    manifest = OUTPUT_DIR / 'sample_manifest.jsonl'
    has_saved_sample = manifest.exists() and manifest.stat().st_size > 0
    has_saved_records = any((OUTPUT_DIR/'records').glob('*.json'))
    journal = OUTPUT_DIR / 'crawl_journal.jsonl'
    has_saved_journal = journal.exists() and journal.stat().st_size > 0
    if path.exists() and path.read_bytes() != body and (has_saved_sample or has_saved_records or has_saved_journal):
        raise ValueError('Code changed; use a new OUTPUT_DIR instead of overwriting a saved run.')
    path.write_bytes(body)
history_path = support / 'known_history_partial.jsonl'
history_path.write_text(BUNDLED_HISTORY,encoding='utf-8')
spec = importlib.util.spec_from_file_location('cnkang_check_runtime',support/'cnkang_check_snapshot.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)
CONFIG = {'parquet_path':str(PARQUET_PATH) if PARQUET_PATH else None,
    'history_paths':[str(p) for p in HISTORY_PATHS], 'history_complete':HISTORY_COMPLETE,
    'allow_incomplete_history':ALLOW_INCOMPLETE_HISTORY,
    'target':TARGET_URLS, 'seed':RANDOM_SEED}
NETWORK = {'gap':REQUEST_GAP_SECONDS,'timeout':[CONNECT_TIMEOUT,READ_TIMEOUT],
    'attempts':MAX_ATTEMPTS_PER_URL,'trust_env':REQUESTS_TRUST_ENV,
    'user_agent':'ViBioMIR-CnkangCheck/1.0'}
CONFIG['network'] = NETWORK
''')
    add('code', '''
samples, history_summary = check.prepare(CONFIG, OUTPUT_DIR, history_path)
print('Trạng thái:', history_summary['state'])
print('Lịch sử:', history_summary['history_files'])
print('URL đã biết:', history_summary['history_unique_urls'])
print('Mẫu thực chọn:', len(samples))
if history_summary.get('history_warning'):
    print('LƯU Ý:', history_summary['history_warning'])
if not samples:
    print(history_summary.get('reason'))
from IPython.display import display, FileLink
if (OUTPUT_DIR/'sampling_summary.csv').exists():
    print((OUTPUT_DIR/'sampling_summary.csv').read_text(encoding='utf-8-sig'))
''')
    add('markdown', '''
## Tải tuần tự, checkpoint từng URL

Đọc robots theo origin, HTTPS trước; không đổi giao thức để né 403/429.
Retry timeout/5xx có giới hạn; Retry-After dài lưu cooldown và dừng để resume sau.
Nếu robots không xác minh được, lưu trạng thái và không giả định được phép.
fetched, parsed, needs_review, fetch_failed nằm trong crawl_status;
status giữ hợp đồng engine production. Cờ thiếu ngày không biến thành lỗi fetch.
Ngắt kernel: chạy lại ô tổng hợp/ZIP bên dưới để lấy kết quả một phần.
''')
    add('code', '''
try:
    if samples:
        check.run(OUTPUT_DIR, samples, NETWORK)
    else:
        print('Chưa có mẫu hợp lệ; xem history_summary để biết nguyên nhân.')
finally:
    summary = check.export(OUTPUT_DIR, samples, history_summary)
''')
    add('code', '''
# Tổng hợp lại không gửi request, kể cả sau interrupt.
summary = check.export(OUTPUT_DIR, samples, history_summary)
display(summary)
report = OUTPUT_DIR/'review_report.md'
print(report.read_text(encoding='utf-8')[:18000])
''')
    add('code', '''
archive = Path(shutil.make_archive(str(OUTPUT_DIR)+'_outputs','zip',root_dir=OUTPUT_DIR))
for path in [OUTPUT_DIR/'review_report.md', OUTPUT_DIR/'review.csv',
             OUTPUT_DIR/'summary_by_branch.csv', OUTPUT_DIR/'results.parquet', archive]:
    display(FileLink(str(path)))
print('ZIP đầy đủ:',archive)
''')
    nb = {'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
         'language_info':{'name':'python','version':'3.11'}},'nbformat':4,'nbformat_minor':5}
    write(nb, ROOT/'notebooks/check_cnkang.com.ipynb')


def main():
    synchronize()
    build_check()


if __name__ == '__main__':
    main()
