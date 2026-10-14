"""Embed EFetch, runner and XML audit into the main corpus notebook. No sample notebook changes."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import pprint
import re
import zlib

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb'


def literals(source):
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values


def replace_literals(source, values):
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in values:
            start = offsets[node.value.lineno - 1] + node.value.col_offset
            stop = offsets[node.value.end_lineno - 1] + node.value.end_col_offset
            edits.append((start, stop, pprint.pformat(values[node.targets[0].id], width=120, sort_dicts=True)))
    for start, stop, value in sorted(edits, reverse=True):
        source = source[:start] + value + source[stop:]
    return source


def upgrade_core(body):
    source = body.decode('utf-8')
    source = source.replace("VERSION = 'v8'", "VERSION = 'v9'")
    source = source.replace("doc.get('extractor') == 'pubmed_abstract_dom_v1'",
                            "doc.get('extractor') in ('pubmed_abstract_dom_v1', 'pubmed_efetch_xml_v1')")
    # One EFetch response is raw evidence for up to 100 IDs. Verify each distinct raw/hash once.
    if 'verified_raw = set()' not in source:
        source = source.replace("    rows = []\n    for item in sample:\n", "    rows = []\n    verified_raw = set()\n    for item in sample:\n", 1)
        source = source.replace("""            if r.get('raw_path'):
                if digest(gzip.decompress((out / r['raw_path']).read_bytes())) != r['raw_sha256']:
                    raise ValueError(f"Corrupt raw: {r['id']}")
""", """            if r.get('raw_path'):
                raw_key = (r['raw_path'], r['raw_sha256'])
                if raw_key not in verified_raw:
                    if digest(gzip.decompress((out / r['raw_path']).read_bytes())) != r['raw_sha256']:
                        raise ValueError(f"Corrupt raw: {r['id']}")
                    verified_raw.add(raw_key)
""", 1)
    return source.encode('utf-8')


def main():
    nb = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
    def get(index): return ''.join(nb['cells'][index]['source'])
    def put(index, source): nb['cells'][index]['source'] = source.splitlines(keepends=True)
    config = get(2)
    if 'PUBMED_USE_EFETCH =' not in config:
        config = config.replace("PUBMED_SELENIUM_FIRST = True  # PubMed chạy Selenium trước, bỏ Requests bài viết",
                                "PUBMED_USE_EFETCH = True  # Mặc định: PubMed đi EFetch GET, ghép theo PMID\n"
                                "PUBMED_EFETCH_BATCH_SIZE = 100\nPUBMED_EFETCH_WORKERS = 1\n"
                                "PUBMED_EFETCH_GAP_SECONDS = 0.5\nPUBMED_EFETCH_ATTEMPTS = 3\n"
                                "PUBMED_EFETCH_CONNECT_TIMEOUT = 10.0\nPUBMED_EFETCH_READ_TIMEOUT = 60.0\n"
                                "PUBMED_EFETCH_BUDGET = 180.0\n"
                                "PUBMED_SELENIUM_FIRST = True  # Chỉ dùng khi PUBMED_USE_EFETCH = False")
        config = config.replace('import json\n', 'import json\nimport os\n', 1)
        config = config.replace('import sys\n', "import sys\n\n"
                                "NCBI_EMAIL = os.environ.get('NCBI_EMAIL', '')  # Email liên hệ; có thể điền ở đây\n"
                                "NCBI_API_KEY = os.environ.get('NCBI_API_KEY', '')  # Tùy chọn; không ghi vào settings/log\n", 1)
        config = config.replace("default_tag = f'ids_{ID_FROM}_{ID_TO}_synced_vi_en_zh'",
                                "source_tag = f'ids_{ID_FROM}_{ID_TO}_synced_vi_en_zh'\n"
                                "default_tag = source_tag + ('_efetch' if PUBMED_USE_EFETCH else '')")
        config = config.replace("        default_tag = f'ids_{ID_FROM}_{ID_TO}_synced'",
                                "        default_tag = source_tag if (WORKDIR / 'runs' / source_tag).exists() else f'ids_{ID_FROM}_{ID_TO}_synced'")
        marker = "    if not RUN_DIR.exists():\n"
        config = config.replace(marker,
                                "    if not POSTPROCESS_ONLY and PUBMED_USE_EFETCH and (previous / 'corpus_config.json').exists():\n"
                                "        old_settings = json.loads((previous / 'corpus_config.json').read_text(encoding='utf-8')).get('settings', {})\n"
                                "        if old_settings.get('pubmed_use_efetch') is not True:\n"
                                "            raise ValueError('Run cũ chưa dùng EFetch. Chọn RUN_TAG mới và RECOVERY_RUN_PATH.')\n" + marker, 1)
    config = replace_literals(config, {'PUBMED_EFETCH_ATTEMPTS':5,'PUBMED_EFETCH_READ_TIMEOUT':90.0,'PUBMED_EFETCH_BUDGET':300.0})
    if 'PUBMED_UPGRADE_EFETCH_SNAPSHOT =' not in config:
        config = config.replace('POSTPROCESS_ONLY =', '''PUBMED_UPGRADE_EFETCH_SNAPSHOT = True  # Upgrade transport compatible with existing XML; keep saved runner/core/data
PUBMED_MIN_BATCH_SIZE = 1
PUBMED_MAX_SPLIT_REQUESTS = 50
PUBMED_FALLBACK_BUDGET = 900.0
PUBMED_PENDING_RETRY_PASSES = 1
PUBMED_MAX_FAILED_BATCHES = 3
CHECKPOINT_ENABLED = True
CHECKPOINT_UPLOAD_ENABLED = True
CHECKPOINT_EVERY_URLS = 10000
CHECKPOINT_EVERY_SECONDS = 900.0
CHECKPOINT_HF_REPO_ID = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
CHECKPOINT_HF_SECRET_NAME = 'HF_TOKEN'

POSTPROCESS_ONLY =''', 1)
    put(2, config)
    if 'Khôi phục checkpoint PubMed 6.000' not in get(1):
        put(1,get(1).rstrip()+'''

Khôi phục checkpoint PubMed 6.000/110.000: giải nén ZIP đầy đủ
`ids_5979207_7061937_synced_vi_en_zh_efetch.zip`, đặt `RESUME_RUN_PATH` tới thư mục chứa manifest,
`ID_FROM=5979207`, `ID_TO=7061937`, `POSTPROCESS_ONLY=False`, `PUBMED_USE_EFETCH=True`, `MAX_NEW=None`.
Giữ `PUBMED_UPGRADE_EFETCH_SNAPSHOT=True`: chỉ nâng cấp transport EFetch; XML parser/schema, core/runner/probe
và dữ liệu cũ giữ nguyên. Log sẽ ghi completed/pending thực tế. Không dùng ZIP diagnostics để resume.
Checkpoint full ZIP được tạo mỗi 10.000 URL mới hoặc 15 phút, và cuối lượt. Nếu có Secret HF_TOKEN quyền ghi,
upload ZIP/checksum vào `checkpoints/<run>/latest.zip` và `latest.json` trong cùng commit. Đây là backup;
run còn pending không upload corpus như hoàn tất. Có thể tắt upload, ZIP local vẫn được tạo.
''')
    crawl = get(12)
    if "'pubmed_use_efetch':" not in crawl:
        crawl = crawl.replace("            'pubmed_selenium_first': PUBMED_SELENIUM_FIRST,",
                              "            'pubmed_selenium_first': PUBMED_SELENIUM_FIRST,\n"
                              "            'pubmed_use_efetch': PUBMED_USE_EFETCH,\n"
                              "            'pubmed_efetch': {'batch_size': PUBMED_EFETCH_BATCH_SIZE, 'workers': PUBMED_EFETCH_WORKERS,\n"
                              "                               'gap_seconds': PUBMED_EFETCH_GAP_SECONDS, 'attempts': PUBMED_EFETCH_ATTEMPTS,\n"
                              "                               'timeout': [PUBMED_EFETCH_CONNECT_TIMEOUT, PUBMED_EFETCH_READ_TIMEOUT],\n"
                              "                               'budget': PUBMED_EFETCH_BUDGET},")
        crawl = crawl.replace("        POSTPROCESS.invalidate(RUN_DIR)",
                              "        # Pass credentials to the subprocess through its environment; settings/log contain none.\n"
                              "        for name, value in [('NCBI_EMAIL', NCBI_EMAIL), ('NCBI_API_KEY', NCBI_API_KEY)]:\n"
                              "            if value:\n                os.environ[name] = value\n"
                              "        POSTPROCESS.invalidate(RUN_DIR)", 1)
    put(12, crawl)
    transport_config = """{'batch_size': PUBMED_EFETCH_BATCH_SIZE, 'workers': PUBMED_EFETCH_WORKERS,
            'gap_seconds': PUBMED_EFETCH_GAP_SECONDS, 'attempts': PUBMED_EFETCH_ATTEMPTS,
            'timeout': [PUBMED_EFETCH_CONNECT_TIMEOUT, PUBMED_EFETCH_READ_TIMEOUT], 'budget': PUBMED_EFETCH_BUDGET,
            'min_batch_size': PUBMED_MIN_BATCH_SIZE, 'max_split_requests': PUBMED_MAX_SPLIT_REQUESTS,
            'fallback_budget': PUBMED_FALLBACK_BUDGET, 'pending_retry_passes': PUBMED_PENDING_RETRY_PASSES,
            'max_consecutive_failed_batches': PUBMED_MAX_FAILED_BATCHES,
            'checkpoint': {'enabled': CHECKPOINT_ENABLED, 'upload': CHECKPOINT_UPLOAD_ENABLED,
                           'repo_id': CHECKPOINT_HF_REPO_ID, 'every_urls': CHECKPOINT_EVERY_URLS,
                           'every_seconds': CHECKPOINT_EVERY_SECONDS, 'token_env': 'HF_TOKEN'}}"""
    crawl=get(12)
    if 'PUBMED_CONFIG_CURRENT =' not in crawl:
        crawl=crawl.replace("        settings_path = RUN_DIR / 'corpus_settings.json'",
            "        PUBMED_CONFIG_CURRENT = "+transport_config+"\n"
            "        corpus_settings['pubmed_efetch'] = PUBMED_CONFIG_CURRENT\n"
            "        if PUBMED_UPGRADE_EFETCH_SNAPSHOT:\n"
            "            corpus_settings = PUBMED_RESUME.runtime_settings(RUN_DIR, corpus_settings)\n"
            "        if CHECKPOINT_ENABLED and CHECKPOINT_UPLOAD_ENABLED and not os.environ.get('HF_TOKEN'):\n"
            "            try:\n"
            "                from kaggle_secrets import UserSecretsClient\n"
            "                os.environ['HF_TOKEN'] = UserSecretsClient().get_secret(CHECKPOINT_HF_SECRET_NAME)\n"
            "            except Exception:\n"
            "                print('Chưa có HF_TOKEN: checkpoint local vẫn lưu; backup HF chưa khả dụng.')\n"
            "        settings_path = RUN_DIR / 'corpus_settings.json'",1)
    put(12,crawl)
    deps=get(4)
    if "'huggingface_hub'" not in deps: deps=deps.replace("'tld',", "'tld', 'huggingface_hub',",1)
    deps=re.sub(r"if requirements_path.exists\(\):\n.*?\nelse:\n    install_args = package_names",
        "if requirements_path.exists():\n"
        "    pinned = {line.split('==',1)[0].strip().replace('_','-').lower() for line in requirements_path.read_text(encoding='utf-8').splitlines() if line.strip() and not line.startswith('#')}\n"
        "    install_args = ['-r', str(requirements_path)] + [p for p in package_names if p.replace('_','-').lower() not in pinned]\n"
        "else:\n    install_args = package_names",deps,count=1,flags=re.S)
    put(4,deps)
    pack = literals(get(6))
    files, hashes = pack['EMBEDDED_FILES'], pack['EMBEDDED_SHA256']
    for name in files:
        body = zlib.decompress(base64.b85decode(files[name]))
        if hashlib.sha256(body).hexdigest() != hashes[name]:
            raise ValueError(f'Existing embedded hash mismatch: {name}')
    updates = {name: (ROOT / 'scripts' / path).read_bytes() for name, path in [
        ('pubmed_efetch_snapshot.py', 'pubmed_efetch.py'), ('corpus_runner_snapshot.py', 'corpus_runner.py'),
        ('audit_snapshot.py', 'corpus_audit.py'), ('pubmed_resume_snapshot.py', 'pubmed_resume.py'),
        ('checkpoint_snapshot.py','corpus_checkpoint.py')]}
    updates['crawler_snapshot.py'] = upgrade_core(zlib.decompress(base64.b85decode(files['crawler_snapshot.py'])))
    diagnostics = zlib.decompress(base64.b85decode(files['diagnostics_snapshot.py'])).decode('utf-8')
    diagnostics = diagnostics.replace("'corpus_runner_snapshot.py', 'postprocess_snapshot.py'):",
                                      "'corpus_runner_snapshot.py', 'postprocess_snapshot.py', 'pubmed_efetch_snapshot.py'):")
    diagnostics = diagnostics.replace("'export_manifest.json', 'postprocess_status.json'):",
                                      "'export_manifest.json', 'postprocess_status.json', 'pubmed_efetch_summary.json'):")
    if "'pubmed_resume_snapshot.py'" not in diagnostics:
        diagnostics=diagnostics.replace("'pubmed_efetch_snapshot.py'", "'pubmed_efetch_snapshot.py', 'pubmed_resume_snapshot.py', 'checkpoint_snapshot.py'",1)
        diagnostics=diagnostics.replace("'corpus_config.json',", "'checkpoint_upload_state.json', 'checkpoint_progress.json', 'pubmed_upgrade_journal.json', 'corpus_config.json',",1)
    updates['diagnostics_snapshot.py'] = diagnostics.encode('utf-8')
    for name, body in updates.items():
        compile(body, name, 'exec')
        files[name] = base64.b85encode(zlib.compress(body, 9)).decode('ascii')
        hashes[name] = hashlib.sha256(body).hexdigest()
    put(6, replace_literals(get(6), {'EMBEDDED_FILES': files, 'EMBEDDED_SHA256': hashes}))
    setup=get(6)
    if 'PUBMED_RESUME =' not in setup:
        setup=setup.replace("POSTPROCESS_FILES = {", "POSTPROCESS_FILES = {'pubmed_resume_snapshot.py', 'checkpoint_snapshot.py', ",1)
        setup=setup.replace("CRAWLER = RUN_DIR / 'crawler_snapshot.py'",'''resume_spec = importlib.util.spec_from_file_location('pubmed_resume_upgrade', RUN_DIR / 'pubmed_resume_snapshot.py')
PUBMED_RESUME = importlib.util.module_from_spec(resume_spec)
resume_spec.loader.exec_module(PUBMED_RESUME)
if not POSTPROCESS_ONLY and PUBMED_USE_EFETCH and PUBMED_UPGRADE_EFETCH_SNAPSHOT:
    upgrade_status = PUBMED_RESUME.upgrade(RUN_DIR,
        zlib.decompress(base64.b85decode(EMBEDDED_FILES['pubmed_efetch_snapshot.py'])),
        '''+transport_config+''')
    print('EFetch snapshot:', json.dumps(upgrade_status, ensure_ascii=False), flush=True)

''' + "CRAWLER = RUN_DIR / 'crawler_snapshot.py'",1)
        # The upgrade loader runs before the previous importlib import.
        setup=setup.replace('import base64\n','import base64\nimport importlib.util\n',1)
    put(6,setup)
    put(11, '''## 6. Crawl — chạy lại ô này để tiếp tục

PubMed mặc định dùng **EFetch GET**, **100 PMID/batch**, **1 worker**, nghỉ ít nhất **0,5 giây giữa request**.
`PUBMED_USE_EFETCH = True` hoạt động cả khi `BROWSER_TEST_MODE = 'off'`; run chỉ có PubMed không khởi động Chrome.
Giữ ID/URL gốc, ghép theo PMID trong XML; `text` có title và toàn bộ abstract cùng nhãn.
Các domain khác dùng Requests rồi Selenium theo cấu hình browser; `RESPECT_ROBOTS` áp dụng lượt crawl website.

Checkpoint XML và batch được lưu trước các record ID. Resume sửa các record còn thiếu mà không GET lại batch đã lưu.
`MAX_NEW` tính số URL corpus mới đã lên lịch, gồm cả PubMed; retry không tính hai lần.
HTTP 400 chỉ retry khi body báo Timeout/Empty Response; HTTP 400 invalid UID/parameter không retry mù quáng.
5 attempts, read timeout 90 giây, budget 300 giây/request batch, backoff + jitter và Retry-After.
Batch còn lỗi chia 100 → 50 → 25 → … để cô lập, giới hạn tổng request/time; sau đó tiếp tục batch khác.
Cuối lượt thử pending thêm một vòng. Cooldown server dài hoặc 3 batch liên tiếp không lấy được bản ghi
thì hoãn để resume; không ném RuntimeError vì riêng một batch lỗi, không đánh dấu complete khi còn pending.
PMID không được API trả về hoặc không có abstract được ghi riêng, không đưa vào corpus accepted.
Xem `pubmed_results.csv`, `pubmed_missing_pmids.csv`, `pubmed_no_abstract.csv`, `pubmed_review.csv`,
`pubmed_pending.csv`, `pubmed_requests.jsonl`, `pubmed_efetch_summary.json` và `raw/efetch/` trong ZIP đầy đủ.

Run mới có hậu tố `_efetch`. Nâng cấp run Selenium cũ bằng `RUN_TAG` mới và `RECOVERY_RUN_PATH`:
reuse raw hợp lệ của domain khác; PubMed HTML cũ được lấy mới qua EFetch.
Muốn thử lại PMID thiếu/no abstract cần run mới; resume giữ những kết quả XML hợp lệ đã hoàn tất.
`POSTPROCESS_ONLY = True` vẫn audit/export run cũ mà không crawl lại.
Resume EFetch cũ tự nâng cấp transport tương thích, giữ nguyên XML/record/schema và các snapshot crawl khác.
Checkpoint full ZIP/HF chạy định kỳ trong lúc crawl, khác với upload corpus cuối cùng sau audit/export.

Tham khảo [NCBI EFetch](https://www.ncbi.nlm.nih.gov/books/NBK25499/).
''')
    intro = get(0)
    if 'PubMed dùng EFetch GET' not in intro:
        put(0, intro.rstrip() + '\n\nPubMed dùng EFetch GET theo PMID; các website khác dùng Requests/Selenium.\n')
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), 'notebook_cell', 'exec')
            cell['outputs'], cell['execution_count'] = [], None
    NOTEBOOK.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print('Updated:', NOTEBOOK.relative_to(ROOT))


if __name__ == '__main__':
    main()
