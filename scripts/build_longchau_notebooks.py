"""Embed the Long Chau route/parser in both crawler notebooks, preserving sample inventories."""
import ast
import base64
import hashlib
import json
from pathlib import Path
import pprint
import zlib

from build_pubmed_efetch_notebook import main as build_corpus, literals, replace_literals

ROOT = Path(__file__).resolve().parents[1]


def core_upgrade(body):
    source = body.decode('utf-8')
    for version in ('v8', 'v9'):
        source = source.replace(f"VERSION = '{version}'", "VERSION = 'v10'")
    if 'def longchau_module():' not in source:
        marker = '\ndef extract(body, content_type, url):'
        loader = '''
def longchau_module():
    import importlib.util
    name = 'crawler_longchau_' + str(digest(str(Path(__file__).resolve()).encode())[:8])
    if name not in sys.modules:
        path = Path(__file__).parent / 'longchau_snapshot.py'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]

'''
        source = source.replace(marker, loader + marker, 1)
        source = source.replace("    if host(url) == 'pubmed.ncbi.nlm.nih.gov':\n        from lxml import html",
                                "    if host(url) in ('nhathuoclongchau.com.vn', 'www.nhathuoclongchau.com.vn'):\n"
                                "        return longchau_module().extract(body, url)\n"
                                "    if host(url) == 'pubmed.ncbi.nlm.nih.gov':\n        from lxml import html", 1)
        source = source.replace("    if doc.get('domain_parser_fallback'):\n",
                                "    flags.extend(doc.get('longchau_review_reasons') or [])\n"
                                "    if doc.get('domain_parser_fallback'):\n", 1)
    return source.encode('utf-8')


def encode(body): return base64.b85encode(zlib.compress(body, 9)).decode('ascii')


def main():
    build_corpus()
    path = ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb'
    nb = json.loads(path.read_text(encoding='utf-8'))
    def get(i): return ''.join(nb['cells'][i]['source'])
    def put(i, text): nb['cells'][i]['source'] = text.splitlines(keepends=True)
    config = get(2)
    if 'LONGCHAU_USE_CURL =' not in config:
        config = config.replace('BROWSER_TEST_MODE =',
            "LONGCHAU_USE_CURL = True\nLONGCHAU_WORKERS = 1\nLONGCHAU_DELAY = 1.75\n"
            "LONGCHAU_ATTEMPTS = 3\nLONGCHAU_CONNECT_TIMEOUT = 10.0\nLONGCHAU_READ_TIMEOUT = 45.0\n"
            "LONGCHAU_REQUEST_BUDGET = 180.0\nLONGCHAU_RETRY_FAILED_ON_RESUME = True\n\nBROWSER_TEST_MODE =", 1)
        config = config.replace("default_tag = source_tag + ('_efetch' if PUBMED_USE_EFETCH else '')",
            "previous_tag = source_tag + ('_efetch' if PUBMED_USE_EFETCH else '')\n"
            "default_tag = previous_tag + ('_longchau' if LONGCHAU_USE_CURL else '')")
        config = config.replace("        default_tag = source_tag if (WORKDIR / 'runs' / source_tag).exists() else f'ids_{ID_FROM}_{ID_TO}_synced'",
            "        default_tag = previous_tag if (WORKDIR / 'runs' / previous_tag).exists() else (source_tag if (WORKDIR / 'runs' / source_tag).exists() else f'ids_{ID_FROM}_{ID_TO}_synced')")
    put(2, config)
    config = replace_literals(get(2), {'LONGCHAU_DELAY': 5.0})
    config = config.replace("('_longchau' if LONGCHAU_USE_CURL else '')", "('_longchau_v2' if LONGCHAU_USE_CURL else '')")
    put(2, config)
    crawl = get(12)
    if "'longchau_use_curl':" not in crawl:
        crawl = crawl.replace("            'pubmed_use_efetch': PUBMED_USE_EFETCH,",
            "            'pubmed_use_efetch': PUBMED_USE_EFETCH,\n"
            "            'longchau_use_curl': LONGCHAU_USE_CURL,\n"
            "            'longchau': {'workers': LONGCHAU_WORKERS, 'delay': LONGCHAU_DELAY, 'attempts': LONGCHAU_ATTEMPTS,\n"
            "                          'timeout': [LONGCHAU_CONNECT_TIMEOUT, LONGCHAU_READ_TIMEOUT],\n"
            "                          'budget': LONGCHAU_REQUEST_BUDGET, 'impersonate': 'chrome',\n"
            "                          'retry_failed_on_resume': LONGCHAU_RETRY_FAILED_ON_RESUME},")
    put(12, crawl)
    deps = get(4)
    if "'curl_cffi'" not in deps:
        deps = deps.replace("'pymupdf', 'tld']", "'pymupdf', 'tld', 'curl_cffi']")
    put(4, deps)
    pack = literals(get(6))
    updates = {'longchau_snapshot.py': (ROOT / 'scripts/longchau.py').read_bytes(),
               'priority_probe_snapshot.py': (ROOT / 'scripts/priority_probe.py').read_bytes()}
    updates['crawler_snapshot.py'] = core_upgrade(zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['crawler_snapshot.py'])))
    export = zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['export_snapshot.py'])).decode('utf-8')
    if "'reviewed_by'" not in export:
        export = export.replace("'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids')",
                                "'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids', 'author', 'reviewed_by', 'updated_at')")
    updates['export_snapshot.py'] = export.encode('utf-8')
    diagnostic = zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['diagnostics_snapshot.py'])).decode('utf-8')
    diagnostic = diagnostic.replace("'postprocess_snapshot.py', 'pubmed_efetch_snapshot.py'):",
                                    "'postprocess_snapshot.py', 'pubmed_efetch_snapshot.py', 'longchau_snapshot.py'):")
    diagnostic = diagnostic.replace("'postprocess_status.json', 'pubmed_efetch_summary.json'):",
                                    "'postprocess_status.json', 'pubmed_efetch_summary.json', 'longchau_summary.json'):")
    diagnostic = diagnostic.replace("('pyarrow', 'requests', 'trafilatura', 'pymupdf', 'tld'):",
                                    "('pyarrow', 'requests', 'trafilatura', 'pymupdf', 'tld', 'curl_cffi', 'lxml', 'selenium'):")
    diagnostic = diagnostic.replace("'pubmed_efetch_summary.json', 'longchau_summary.json'):",
        "'pubmed_efetch_summary.json', 'longchau_summary.json', 'longchau_results.csv', 'longchau_results.jsonl', "
        "'longchau_config.json', 'longchau_request_gate.json', 'longchau_selection.json'):")
    updates['diagnostics_snapshot.py'] = diagnostic.encode('utf-8')
    for name, body in updates.items():
        compile(body, name, 'exec')
        pack['EMBEDDED_FILES'][name] = encode(body)
        pack['EMBEDDED_SHA256'][name] = hashlib.sha256(body).hexdigest()
    put(6, replace_literals(get(6), {k: pack[k] for k in ('EMBEDDED_FILES', 'EMBEDDED_SHA256')}))
    # Preserve saved runtime snapshots. Parser/config changes require recovery in a new run;
    # postprocess-only uses the fresh auditor/parser to reject unreprocessed legacy text.
    setup = get(6).replace(", 'longchau_snapshot.py'}", "}")
    if 'HAS_LONGCHAU_SAMPLE =' not in setup:
        setup = setup.replace('for name, encoded in EMBEDDED_FILES.items():', '''HAS_LONGCHAU_SAMPLE = False
if (RUN_DIR / 'sample.jsonl').exists():
    from urllib.parse import urlsplit
    with (RUN_DIR / 'sample.jsonl').open(encoding='utf-8') as stream:
        HAS_LONGCHAU_SAMPLE = any(urlsplit(json.loads(line)['url']).hostname in
            ('nhathuoclongchau.com.vn', 'www.nhathuoclongchau.com.vn') for line in stream if line.strip())
if not POSTPROCESS_ONLY and HAS_LONGCHAU_SAMPLE and (RUN_DIR / 'corpus_config.json').exists():
    saved_runtime = json.loads((RUN_DIR / 'corpus_config.json').read_text(encoding='utf-8'))
    for name, key in (('longchau_snapshot.py', 'longchau_sha256'),
                      ('corpus_runner_snapshot.py', 'runner_sha256'), ('priority_probe_snapshot.py', 'probe_sha256')):
        if saved_runtime.get(key) != EMBEDDED_SHA256[name]:
            raise ValueError('Run Long Châu cũ cần recovery: dùng ZIP đầy đủ, RECOVERY_RUN_PATH + RUN_TAG mới; '
                             'không ép RESUME vì parser/runner đã đổi. Raw và records cũ được giữ nguyên.')

for name, encoded in EMBEDDED_FILES.items():''', 1)
        setup = setup.replace('if name in POSTPROCESS_FILES or (not target.exists() and not POSTPROCESS_ONLY):',
            "if name in POSTPROCESS_FILES or (name == 'longchau_snapshot.py' and POSTPROCESS_ONLY and HAS_LONGCHAU_SAMPLE) or (not target.exists() and not POSTPROCESS_ONLY):",1)
    put(6,setup)
    note = '\n\nLong Châu mặc định dùng `curl_cffi`/Chrome, 1 worker, delay 5 giây; không chạy Selenium cho domain này. '
    note += 'Parser giữ sapo/nội dung chính; `/benh/` lấy đầy đủ các trường HTML y khoa từ JSON đã xác minh slug/canonical. '
    note += 'Xem `longchau_results.csv`, `longchau_summary.json`; parser v2 loại nhóm liên kết “Xem thêm”. '
    note += 'Run mới có hậu tố `_longchau_v2`; dùng recovery từ ZIP đầy đủ để tái trích HTML 200 cũ, giữ cooldown. '
    note += 'Checkpoint thuộc runner chung: lưu theo cadence cho mọi engine và khi dừng/ngắt; log có tiến độ chung theo ID.\n'
    if 'Long Châu mặc định dùng' not in get(11): put(11, get(11).rstrip() + note)
    # build_corpus rewrites cell 11, so this note is always derived from the current parser.
    write(nb, path)
    update_domain(updates)
    from build_longchau_smoke_notebook import main as build_smoke
    build_smoke()


def write(nb, path):
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), str(path), 'exec')
            cell['execution_count'], cell['outputs'] = None, []
    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')


def update_domain(updates):
    path = ROOT / 'notebooks/crawl_domain_samples.ipynb'
    nb = json.loads(path.read_text(encoding='utf-8'))
    get = lambda i: ''.join(nb['cells'][i]['source'])
    def put(i, text): nb['cells'][i]['source'] = text.splitlines(keepends=True)
    pack = literals(get(7))
    values = {'CRAWLER_PAYLOAD': encode(core_upgrade(zlib.decompress(base64.b85decode(pack['CRAWLER_PAYLOAD'])))),
              'PRIORITY_PAYLOAD': encode(updates['priority_probe_snapshot.py']),
              'LONGCHAU_PAYLOAD': encode(updates['longchau_snapshot.py']),
              'IP_DIAGNOSTICS_PAYLOAD': encode((ROOT / 'scripts/domain_ip_diagnostics.py').read_bytes())}
    for key, payload in list(values.items()):
        values[key.replace('PAYLOAD','SHA256')] = hashlib.sha256(zlib.decompress(base64.b85decode(payload))).hexdigest()
    # Domain builder's replacement helper can add new top-level assignments.
    from build_domain_samples_notebook import replace
    put(7, replace(get(7), values))
    # Clean unused assignments from a pre-release builder invocation.
    source = get(7)
    lines = source.splitlines(keepends=True)
    for node in reversed(ast.parse(source).body):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('PROBE_PAYLOAD', 'PROBE_SHA256'):
            del lines[node.lineno - 1:node.end_lineno]
    put(7, ''.join(lines))
    if 'LONGCHAU_PAYLOAD' not in get(7).split('RUN_DIR.mkdir')[0]:
        raise ValueError('Long Chau payload not embedded')
    source = get(7)
    if "'longchau_snapshot.py':" not in source:
        source = source.replace("'priority_probe_snapshot.py':", "'longchau_snapshot.py': (LONGCHAU_PAYLOAD, LONGCHAU_SHA256),\n        'priority_probe_snapshot.py':", 1)
    put(7, source)
    config = get(3)
    if 'LONGCHAU_USE_CURL =' not in config:
        config += "\nLONGCHAU_USE_CURL = True\nLONGCHAU_CONFIG = {'workers': 1, 'delay': 1.75, 'attempts': 3, 'timeout': [10., 45.], 'budget': 180., 'impersonate': 'chrome', 'retry_failed_on_resume': True}\n"
    put(3, config)
    domain_config = literals(get(3))['LONGCHAU_CONFIG']
    put(3, replace_literals(get(3), {'LONGCHAU_CONFIG': dict(domain_config,delay=5.0)}))
    deps = get(5)
    if "'curl_cffi'" not in deps: deps = deps.replace("'ipython']", "'ipython', 'curl_cffi']")
    put(5, deps)
    # Domain snapshot setup differs from the corpus loader; inject a verified standalone helper explicitly.
    setup = get(7)
    if 'longchau_spec =' not in setup:
        setup += '''
longchau_body = zlib.decompress(base64.b85decode(LONGCHAU_PAYLOAD))
if hashlib.sha256(longchau_body).hexdigest() != LONGCHAU_SHA256:
    raise ValueError('Long Chau snapshot hash mismatch')
(RUN_DIR / 'longchau_snapshot.py').write_bytes(longchau_body)
longchau_spec = importlib.util.spec_from_file_location('domain_longchau', RUN_DIR / 'longchau_snapshot.py')
longchau = importlib.util.module_from_spec(longchau_spec)
longchau_spec.loader.exec_module(longchau)
'''
    put(7, setup)
    put(7, get(7).replace("(RUN_DIR / 'longchau_snapshot.py').write_bytes(longchau_body)",
        "longchau_path = RUN_DIR / 'longchau_snapshot.py'\n"
        "if longchau_path.exists() and longchau_path.read_bytes() != longchau_body:\n"
        "    raise ValueError('Long Chau code changed; use a new run and RECOVERY_RUN_DIR')\n"
        "longchau_path.write_bytes(longchau_body)"))
    rows = get(9)
    if "effective_engine = effective.get('engine', effective_engine)" not in rows:
        rows = rows.replace("        flags = record.get('quality_flags', [])",
                            "        effective_engine = effective.get('engine', effective_engine)\n"
                            "        flags = record.get('quality_flags', [])", 1)
    put(9, rows)
    note = '\n\nLong Châu dùng `curl_cffi`, 1 worker, delay 5 giây, cùng parser v2 với corpus chính. '
    note += 'Mặc định retry checkpoint lỗi Long Châu khi resume; kết quả trích hợp lệ giữ nguyên. '
    note += 'Báo cáo engine ghi `curl_cffi`; IP đo qua Requests/Chrome là phép đo riêng, chưa xác nhận IP curl.\n'
    if 'Long Châu dùng `curl_cffi`' not in get(10): put(10, get(10).rstrip() + note)
    put(10,get(10).replace('delay 1,75 giây, cùng parser với corpus chính', 'delay 5 giây, cùng parser v2 với corpus chính'))
    put(11, '''import argparse
import os
import socket
import time

robots_options = {'robots_attempts': ROBOTS_ATTEMPTS, 'robots_connect_timeout': ROBOTS_CONNECT_TIMEOUT,
                  'robots_read_timeout': ROBOTS_READ_TIMEOUT, 'robots_retry_budget': ROBOTS_RETRY_BUDGET,
                  'robots_failure_ttl': ROBOTS_FAILURE_TTL}
try:
    if IP_CHECK_ENABLED:
        network = IP_DIAGNOSTICS.collect_network(
            crawler, priority_probe, RUN_DIR, NETWORK_CHECK_DOMAINS, user_agent=USER_AGENT,
            browser_user_agent=BROWSER_USER_AGENT, chrome_binary=CHROME_BINARY,
            browser_ip=IP_BROWSER_EGRESS_CHECK and BROWSER_TEST_MODE != 'off', homepage=IP_HOMEPAGE_CHECK,
            workers=WORKERS, timeout=IP_CHECK_TIMEOUT, budget=IP_CHECK_BUDGET, force=IP_RECHECK_ON_RESUME)
        print('IP Requests:', network.get('requests_ips', []), '; IP Selenium:', network.get('selenium_ips', []))
        rows, summary, zip_path = save_outputs(show=False)
    with crawler.run_lock(RUN_DIR):
        if RECOVERY_RUN_DIR:
            recovery = priority_probe.seed_successful_requests(crawler, RUN_DIR, SAMPLES, RECOVERY_RUN_DIR)
            print('Recovery:', len(recovery['reused_ids']), 'URL reuse raw;', len(recovery['retry_ids']), 'URL thử lại.')
        longchau_samples = [s for s in SAMPLES if LONGCHAU_USE_CURL and longchau.is_host(s['url'])]
        remaining_samples = [s for s in SAMPLES if s not in longchau_samples]
        longchau_new = longchau.crawl(crawler, priority_probe, RUN_DIR, longchau_samples, LONGCHAU_CONFIG,
            user_agent=USER_AGENT, respect_robots=not DIRECT_PUBLIC_PROBE, record_dir='records',
            robots_options=robots_options, max_new=MAX_NEW, log_every=LOG_EVERY) if longchau_samples else 0
        remaining_limit = None if MAX_NEW is None else MAX_NEW - longchau_new
        if DIRECT_PUBLIC_PROBE and BROWSER_TEST_MODE != 'off' and remaining_samples:
            priority_probe.browser_preflight(crawler, RUN_DIR, user_agent=BROWSER_USER_AGENT,
                                             chrome_binary=CHROME_BINARY, load_timeout=BROWSER_LOAD_TIMEOUT)
        primary_enabled = DIRECT_PUBLIC_PROBE and PUBMED_SELENIUM_FIRST and BROWSER_TEST_MODE != 'off'
        primary, primary_new = [], 0
        if remaining_limit != 0:
            primary, primary_new = priority_probe.prepare_pubmed_selenium(
                crawler, RUN_DIR, remaining_samples, enabled=primary_enabled, max_new=remaining_limit,
                respect_robots=not DIRECT_PUBLIC_PROBE, robots_options=robots_options)
        if primary:
            priority_probe.crawl_browser(
                crawler, RUN_DIR, primary, user_agent=BROWSER_USER_AGENT, chrome_binary=CHROME_BINARY,
                delay=DELAY, load_timeout=BROWSER_LOAD_TIMEOUT, attempts=BROWSER_ATTEMPTS, log_every=LOG_EVERY)
            if any(not (RUN_DIR / 'browser_records' / f"{s['id']}.json").exists() for s in primary):
                raise RuntimeError('PubMed Selenium chưa hoàn tất; xem browser_setup_error.json và resume.')
        request_samples = [s for s in remaining_samples if not primary_enabled
                           or crawler.host(s['url']) != 'pubmed.ncbi.nlm.nih.gov']
        request_limit = None if remaining_limit is None else remaining_limit - primary_new
        if request_limit != 0:
            priority_probe.crawl_requests(
                crawler, RUN_DIR, request_samples, workers=WORKERS, delay=DELAY,
                attempts=PAGE_ATTEMPTS, user_agent=USER_AGENT, respect_robots=not DIRECT_PUBLIC_PROBE,
                robots_options=robots_options, record_dir='records', lock_run=False,
                timeout=(PAGE_CONNECT_TIMEOUT, PAGE_READ_TIMEOUT), budget=PAGE_REQUEST_BUDGET,
                max_new=request_limit, log_every=LOG_EVERY)
        records = [crawler.load_json(RUN_DIR / 'records' / f"{s['id']}.json") for s in request_samples
                   if (RUN_DIR / 'records' / f"{s['id']}.json").exists()]
        browser_samples = priority_probe.select_browser_samples(request_samples, records, BROWSER_TEST_MODE) if DIRECT_PUBLIC_PROBE else []
        if not DIRECT_PUBLIC_PROBE:
            allowed = {r['id'] for r in records if not r.get('status','').startswith('robots_')
                       and r.get('status') not in ('invalid_url','unsafe_address')}
            browser_samples = [s for s in browser_samples if s['id'] in allowed]
        if browser_samples:
            priority_probe.crawl_browser(crawler, RUN_DIR, browser_samples,
                                        user_agent=BROWSER_USER_AGENT, chrome_binary=CHROME_BINARY, delay=DELAY,
                                        load_timeout=BROWSER_LOAD_TIMEOUT, attempts=BROWSER_ATTEMPTS, log_every=LOG_EVERY)
        crawler.report(argparse.Namespace(out=str(RUN_DIR)))
finally:
    longchau.write_reports(crawler, RUN_DIR, [s for s in SAMPLES if longchau.is_host(s['url'])], 'records')
    rows, summary, zip_path = save_outputs()
''')
    write(nb, path)


if __name__ == '__main__':
    main()
