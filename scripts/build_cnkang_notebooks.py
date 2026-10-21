"""Build standalone cnkang check; synchronize parser/transport with corpus."""
import base64
import argparse
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
            if 'cnkang-local-experiments' not in cell.get('metadata', {}).get('tags', []):
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
    if '# cnkang full article audit' not in text:
        start = text.index('def report(')
        before, report = text[:start], text[start:]
        report = report.replace('            rows.append(r)',
            "            # cnkang full article audit, including POSTPROCESS_ONLY exports.\n"
            "            if (host(r['url']) == 'cnkang.com' or host(r['url']).endswith('.cnkang.com')) and r.get('status') == 'extracted':\n"
            "                if r.get('article_complete') is False and r.get('quality_status') == 'accepted':\n"
            "                    raise ValueError('Incomplete cnkang article cannot be accepted')\n"
            "                cnkang_module().audit(gzip.decompress((out/r['raw_path']).read_bytes()),\n"
            "                    r.get('final_url') or r['url'], r, r.get('content_type') or 'text/html', base_dir=out)\n"
            "            rows.append(r)", 1)
        text = before + report
    if '# cnkang source gate' not in text:
        helper = '''
def corpus_eligible(record, out):
    # cnkang source gate: report_only preserves provisional parser acceptance.
    if host(record['url']) == 'cnkang.com' or host(record['url']).endswith('.cnkang.com'):
        return cnkang_module().SOURCE.export_eligible(record, cnkang_module().SOURCE.mode_for_run(out))
    return record.get('quality_status') == 'accepted'

'''
        text = text.replace('\ndef report(args):', '\n' + helper + '\ndef report(args):',1)
        start = text.index('def report(args):')
        before, report = text[:start], text[start:]
        report = report.replace("r.get('quality_status') == 'accepted'", 'corpus_eligible(r, out)')
        report = report.replace("r.get('quality_status') != 'accepted'", 'not corpus_eligible(r, out)')
        report = report.replace('base_dir=out)\n',
            "base_dir=out)\n"
            "                r = cnkang_module().SOURCE.publish(r, cnkang_module().SOURCE.mode_for_run(out))\n",1)
        report = report.replace("    jsonl(out / 'documents.jsonl', extracted)",
            "    jsonl(out / 'source_decisions.jsonl', [r for r in extracted if r.get('source_policy_version')])\n"
            "    jsonl(out / 'documents.jsonl', extracted)",1)
        report = report.replace("'extracted': len(extracted), 'accepted': len(accepted),",
            "'extracted': len(extracted), 'accepted': len(accepted),\n"
            "               'cnkang_source_policy_mode': cnkang_module().SOURCE.mode_for_run(out) if any(host(r['url']).endswith('cnkang.com') for r in rows) else None,\n"
            "               'cnkang_source_decisions': dict(Counter(r['source_decision'] for r in rows if r.get('source_policy_version'))),\n"
            "               'cnkang_corpus_decisions': dict(Counter(r['corpus_decision'] for r in rows if r.get('source_policy_version'))),",1)
        text = before + report
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
        'cnkang_network_snapshot.py': (ROOT / 'scripts/cnkang_network.py').read_bytes(),
        'cnkang_request_worker_snapshot.py': (ROOT / 'scripts/cnkang_request_worker.py').read_bytes(),
        'cnkang_checkpoint_snapshot.py': (ROOT / 'scripts/cnkang_checkpoint.py').read_bytes(),
        'cnkang_article_snapshot.py': (ROOT / 'scripts/cnkang_article.py').read_bytes(),
        'cnkang_source_gate_snapshot.py': (ROOT / 'scripts/cnkang_source_gate.py').read_bytes(),
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
    if "('cnkang_network_snapshot.py','cnkang_network_sha256')" not in setup:
        setup = setup.replace("('cnkang_transport_snapshot.py','cnkang_transport_sha256'),",
            "('cnkang_transport_snapshot.py','cnkang_transport_sha256'),\n"
            "                      ('cnkang_network_snapshot.py','cnkang_network_sha256'),\n"
            "                      ('cnkang_request_worker_snapshot.py','cnkang_network_worker_sha256'),")
    if "('cnkang_checkpoint_snapshot.py','cnkang_checkpoint_sha256')" not in setup:
        setup = setup.replace("('cnkang_transport_snapshot.py','cnkang_transport_sha256'),",
            "('cnkang_transport_snapshot.py','cnkang_transport_sha256'),\n"
            "                      ('cnkang_checkpoint_snapshot.py','cnkang_checkpoint_sha256'),", 1)
    if "('cnkang_article_snapshot.py','cnkang_article_sha256')" not in setup:
        setup = setup.replace("('cnkang_transport_snapshot.py','cnkang_transport_sha256'),",
            "('cnkang_transport_snapshot.py','cnkang_transport_sha256'),\n"
            "                      ('cnkang_article_snapshot.py','cnkang_article_sha256'),", 1)
    if "('cnkang_source_gate_snapshot.py','cnkang_source_policy_sha256')" not in setup:
        setup = setup.replace("('cnkang_transport_snapshot.py','cnkang_transport_sha256'),",
            "('cnkang_transport_snapshot.py','cnkang_transport_sha256'),\n"
            "                      ('cnkang_source_gate_snapshot.py','cnkang_source_policy_sha256'),",1)
    put(6, setup)
    config = get(2)
    if 'CNKANG_REQUEST_GAP =' not in config:
        config = config.replace('BROWSER_TEST_MODE =',
            "CNKANG_REQUEST_GAP = 1.5  # 1 worker, robots luôn bật, không chạy Selenium\n"
            "CNKANG_ATTEMPTS = 2\nCNKANG_CONNECT_TIMEOUT = 10.0\nCNKANG_READ_TIMEOUT = 30.0\n"
            "CNKANG_USER_AGENT = 'ViBioMIR-CnkangCheck/1.0'\n\nBROWSER_TEST_MODE =", 1)
    if 'CNKANG_REQUEST_DEADLINE =' not in config:
        config = config.replace('CNKANG_ATTEMPTS =',
            'CNKANG_REQUEST_DEADLINE = 45.0  # DNS + connect + headers + body\n'
            'CNKANG_URL_DEADLINE = 120.0  # robots + gap + redirects + retries\nCNKANG_ATTEMPTS =', 1)
    if 'CNKANG_MAX_PAGES =' not in config:
        config = config.replace('CNKANG_ATTEMPTS =',
            'CNKANG_MAX_PAGES = 6\nCNKANG_ARTICLE_DEADLINE = 360.0\nCNKANG_ATTEMPTS =', 1)
    put(2, config)
    if 'CNKANG_SOURCE_POLICY_MODE =' not in config:
        config += "\nCNKANG_SOURCE_POLICY_MODE = 'report_only'  # independent labelled evaluation pending\n"
        put(2, config)
    crawl = get(12)
    if "'cnkang':" not in crawl:
        crawl = crawl.replace("'longchau_use_curl': LONGCHAU_USE_CURL,",
            "'longchau_use_curl': LONGCHAU_USE_CURL,\n"
            "            'cnkang': {'gap': CNKANG_REQUEST_GAP, 'attempts': CNKANG_ATTEMPTS,\n"
            "                       'timeout': [CNKANG_CONNECT_TIMEOUT, CNKANG_READ_TIMEOUT],\n"
            "                       'user_agent': CNKANG_USER_AGENT, 'trust_env': REQUESTS_TRUST_ENV},", 1)
    if "'request_deadline': CNKANG_REQUEST_DEADLINE" not in crawl:
        crawl = crawl.replace("'timeout': [CNKANG_CONNECT_TIMEOUT, CNKANG_READ_TIMEOUT],",
            "'timeout': [CNKANG_CONNECT_TIMEOUT, CNKANG_READ_TIMEOUT],\n"
            "                       'request_deadline': CNKANG_REQUEST_DEADLINE,\n"
            "                       'url_deadline': CNKANG_URL_DEADLINE,", 1)
    if "'max_pages': CNKANG_MAX_PAGES" not in crawl:
        crawl = crawl.replace("'url_deadline': CNKANG_URL_DEADLINE,",
            "'url_deadline': CNKANG_URL_DEADLINE,\n"
            "                       'max_pages': CNKANG_MAX_PAGES, 'article_deadline': CNKANG_ARTICLE_DEADLINE,", 1)
    if "'source_policy_mode': CNKANG_SOURCE_POLICY_MODE" not in crawl:
        crawl = crawl.replace("'user_agent': CNKANG_USER_AGENT,",
            "'source_policy_mode': CNKANG_SOURCE_POLICY_MODE, 'user_agent': CNKANG_USER_AGENT,",1)
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
    domain_config = ''.join(nb['cells'][3]['source'])
    if 'CNKANG_SOURCE_POLICY_MODE =' not in domain_config:
        domain_config += "\nCNKANG_SOURCE_POLICY_MODE = 'report_only'  # source labels not independently validated\n"
        nb['cells'][3]['source'] = domain_config.splitlines(keepends=True)
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
    if 'CNKANG_ARTICLE_PAYLOAD =' not in setup:
        setup += "\nCNKANG_ARTICLE_PAYLOAD = " + repr(encode(updates['cnkang_article_snapshot.py'])) + "\n"
    else:
        setup = replace(setup, {'CNKANG_ARTICLE_PAYLOAD': encode(updates['cnkang_article_snapshot.py'])})
    if 'cnkang_article_body =' not in setup:
        setup += '''
cnkang_article_body = zlib.decompress(base64.b85decode(CNKANG_ARTICLE_PAYLOAD))
cnkang_article_path = RUN_DIR / 'cnkang_article_snapshot.py'
if cnkang_article_path.exists() and cnkang_article_path.read_bytes() != cnkang_article_body:
    raise ValueError('cnkang article code changed; use a new run')
cnkang_article_path.write_bytes(cnkang_article_body)
'''
    runtime_files = {name: encode(body) for name, body in updates.items()
                     if name.startswith('cnkang_') and name != 'cnkang_snapshot.py'}
    if 'CNKANG_RUNTIME_PAYLOADS =' not in setup:
        setup += '\nCNKANG_RUNTIME_PAYLOADS = ' + repr(runtime_files) + '\n'
        setup += '''
import importlib.util
for cnkang_name, cnkang_payload in CNKANG_RUNTIME_PAYLOADS.items():
    cnkang_code = zlib.decompress(base64.b85decode(cnkang_payload))
    cnkang_target = RUN_DIR / cnkang_name
    if cnkang_target.exists() and cnkang_target.read_bytes() != cnkang_code:
        raise ValueError('cnkang runtime changed; use a new run and recovery')
    cnkang_target.write_bytes(cnkang_code)
cnkang_spec = importlib.util.spec_from_file_location('domain_cnkang_transport', RUN_DIR/'cnkang_transport_snapshot.py')
CNKANG_TRANSPORT = importlib.util.module_from_spec(cnkang_spec)
cnkang_spec.loader.exec_module(CNKANG_TRANSPORT)
'''
    else:
        setup = replace(setup, {'CNKANG_RUNTIME_PAYLOADS': runtime_files})
    nb['cells'][7]['source'] = setup.splitlines(keepends=True)
    domain_crawl = ''.join(nb['cells'][11]['source'])
    if 'cnkang_samples = ' not in domain_crawl:
        domain_crawl = domain_crawl.replace(
            'recovery = priority_probe.seed_successful_requests(crawler, RUN_DIR, SAMPLES, RECOVERY_RUN_DIR)',
            "recovery = priority_probe.seed_successful_requests(crawler, RUN_DIR,\n"
            "                [s for s in SAMPLES if not CNKANG_TRANSPORT.PARSER.is_host(s['url'])], RECOVERY_RUN_DIR)\n"
            "            CNKANG_TRANSPORT.seed_recovery(RUN_DIR,\n"
            "                [s for s in SAMPLES if CNKANG_TRANSPORT.PARSER.is_host(s['url'])], RECOVERY_RUN_DIR,\n"
            "                record_dir='records')")
        domain_crawl = domain_crawl.replace(
            '        if DIRECT_PUBLIC_PROBE and BROWSER_TEST_MODE',
            "        cnkang_samples = [s for s in remaining_samples if CNKANG_TRANSPORT.PARSER.is_host(s['url'])]\n"
            "        if cnkang_samples and remaining_limit != 0:\n"
            "            cnkang_new = CNKANG_TRANSPORT.crawl(crawler, priority_probe, RUN_DIR, cnkang_samples,\n"
            "                {'trust_env': REQUESTS_TRUST_ENV}, max_new=remaining_limit, log_every=LOG_EVERY,\n"
            "                record_dir='records')\n"
            "            if remaining_limit is not None: remaining_limit -= cnkang_new\n"
            "        remaining_samples = [s for s in remaining_samples if not CNKANG_TRANSPORT.PARSER.is_host(s['url'])]\n"
            "        if DIRECT_PUBLIC_PROBE and BROWSER_TEST_MODE", 1)
    if "'source_policy_mode': CNKANG_SOURCE_POLICY_MODE" not in domain_crawl:
        domain_crawl = domain_crawl.replace("{'trust_env': REQUESTS_TRUST_ENV}, max_new=remaining_limit",
            "{'trust_env': REQUESTS_TRUST_ENV, 'source_policy_mode': CNKANG_SOURCE_POLICY_MODE}, max_new=remaining_limit")
    nb['cells'][11]['source'] = domain_crawl.splitlines(keepends=True)
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
REQUEST_DEADLINE = 45.0
URL_DEADLINE = 120.0
MAX_ARTICLE_PAGES = 6
ARTICLE_DEADLINE = 360.0
MAX_ATTEMPTS_PER_URL = 2
SOURCE_POLICY_MODE = 'report_only'  # enforce only after independent labelled evaluation
REQUESTS_TRUST_ENV = False
OUTPUT_DIR = Path('/kaggle/working/check_cnkang_com')
RESUME_FROM = None  # Thư mục run đầy đủ dưới Kaggle Input, copy khi OUTPUT_DIR chưa có.
''')
    files = {name:(ROOT/'scripts'/source).read_bytes() for name,source in (
        ('cnkang_snapshot.py','cnkang.py'),('cnkang_transport_snapshot.py','cnkang_transport.py'),
        ('cnkang_network_snapshot.py','cnkang_network.py'),
        ('cnkang_request_worker_snapshot.py','cnkang_request_worker.py'),
        ('cnkang_checkpoint_snapshot.py','cnkang_checkpoint.py'),
        ('cnkang_article_snapshot.py','cnkang_article.py'),
        ('cnkang_source_gate_snapshot.py','cnkang_source_gate.py'),
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
    'source_policy_mode':SOURCE_POLICY_MODE,
    'request_deadline':REQUEST_DEADLINE,'url_deadline':URL_DEADLINE,
    'max_pages':MAX_ARTICLE_PAGES,'article_deadline':ARTICLE_DEADLINE,
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
    # Keep optional experiments local to the ignored check, including saved outputs.
    local_path = ROOT/'notebooks/check_cnkang.com.ipynb'
    if local_path.exists():
        previous = json.loads(local_path.read_text(encoding='utf-8'))
        cells.extend(c for c in previous['cells']
                     if 'cnkang-local-experiments' in c.get('metadata', {}).get('tags', []))
    nb = {'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
         'language_info':{'name':'python','version':'3.11'}},'nbformat':4,'nbformat_minor':5}
    write(nb, ROOT/'notebooks/check_cnkang.com.ipynb')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check-only', action='store_true', help='Build the single local check without changing crawl notebooks')
    args = ap.parse_args()
    if not args.check_only: synchronize()
    build_check()


if __name__ == '__main__':
    main()
