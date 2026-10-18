"""Embed the 120ask V3 parser in the production and domain-sample notebooks."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import zlib

from build_longchau_notebooks import (
    encode, literals, main as build_shared_notebooks, replace_literals, write,
)
from build_domain_samples_notebook import replace


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb'
DOMAIN = ROOT / 'notebooks/crawl_domain_samples.ipynb'


def core_upgrade(body):
    source = body.decode('utf-8')
    source = source.replace("VERSION = 'v10'", "VERSION = 'v11'")
    if 'TRUST_ENV = True' not in source:
        source = source.replace("ROBOT_AGENT = 'ViBioMIRResearchCrawler'\n",
                                "ROBOT_AGENT = 'ViBioMIRResearchCrawler'\nTRUST_ENV = True\n", 1)
        session_marker = "            self.local.session = requests.Session()\n"
        if session_marker not in source:
            raise ValueError('Crawler Requests session marker not found.')
        source = source.replace(session_marker, session_marker +
                                "            self.local.session.trust_env = TRUST_ENV\n", 1)
    if 'def ask120_module():' not in source:
        marker = '\ndef extract(body, content_type, url):'
        loader = '''
def ask120_module():
    import importlib.util
    name = 'crawler_ask120_' + str(digest(str(Path(__file__).resolve()).encode())[:8])
    if name not in sys.modules:
        path = Path(__file__).parent / 'ask120_snapshot.py'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]

'''
        if marker not in source:
            raise ValueError('Crawler extract() marker not found.')
        source = source.replace(marker, loader + marker, 1)
        route = "    if host(url) in ('nhathuoclongchau.com.vn', 'www.nhathuoclongchau.com.vn'):\n"
        replacement = (
            "    if (host(url) in ('120ask.com', 'www.120ask.com')\n"
            "            and re.fullmatch(r'/question/[0-9]+\\.htm', urlsplit(url).path)):\n"
            "        return ask120_module().extract(body, url, content_type)\n"
            + route
        )
        if route not in source:
            raise ValueError('Crawler Long Chau route marker not found.')
        source = source.replace(route, replacement, 1)
        short_marker = "    if (language == 'zh_hint' and doc.get('extractor') == '120ask_qa_dom_v1'\n"
        short_rule = (
            "    if doc.get('extractor') == '120ask_qa_dom_v2' and doc.get('ask120_access_pass'):\n"
            "        # Structural checks, rather than a generic 300-character threshold, validate short Q&A pages.\n"
            "        minimum_chars = 1\n"
        )
        if short_marker not in source:
            raise ValueError('Crawler 120ask V1 short-text marker not found.')
        source = source.replace(short_marker, short_rule + short_marker, 1)
        flag_marker = "    flags.extend(doc.get('longchau_review_reasons') or [])\n"
        if flag_marker not in source:
            raise ValueError('Crawler review-reason marker not found.')
        source = source.replace(
            flag_marker,
            flag_marker + "    flags.extend(doc.get('ask120_review_reasons') or [])\n",
            1,
        )
        source = source.replace(
            "if doc.get('extractor') == '120ask_qa_dom_v1' and not doc.get('source_answer_count'):",
            "if doc.get('extractor') in ('120ask_qa_dom_v1', '120ask_qa_dom_v2') and not doc.get('source_answer_count'):",
            1,
        )
    if 'ask120_canonical_redirect' not in source:
        old_redirect = '''def flag_redirect(record):
    if host(record['url']) != host(record['final_url']) or (urlsplit(record['final_url']).path in ('', '/') and urlsplit(record['url']).path not in ('', '/')):
        record['quality_flags'].append('redirect_review')
        if record['quality_status'] == 'accepted':
            record['quality_status'] = 'review'
'''
        new_redirect = '''def flag_redirect(record):
    source, target = urlsplit(record['url']), urlsplit(record['final_url'])
    ask120_source = ((source.hostname or '').lower() in ('120ask.com', 'www.120ask.com')
                     and re.fullmatch(r'/question/[0-9]+\\.htm', source.path))
    ask120_canonical_redirect = (ask120_source
        and (target.hostname or '').lower() in ('120ask.com', 'www.120ask.com')
        and target.path == source.path)
    redirect_review = ((ask120_source and not ask120_canonical_redirect)
        or (not ask120_source and (host(record['url']) != host(record['final_url'])
            or (target.path in ('', '/') and source.path not in ('', '/')))))
    if redirect_review:
        record['quality_flags'].append('redirect_review')
        if record['quality_status'] == 'accepted':
            record['quality_status'] = 'review'
'''
        if old_redirect not in source:
            raise ValueError('Crawler redirect marker not found.')
        source = source.replace(old_redirect, new_redirect, 1)
    source = source.replace("'120ask_qa_dom_v2'", "'120ask_qa_dom_v3'")
    source = source.replace("VERSION = 'v11'", "VERSION = 'v12'")
    compile(source, 'crawler_snapshot.py', 'exec')
    return source.encode('utf-8')


def _update_main(ask120_body):
    notebook = json.loads(MAIN.read_text(encoding='utf-8'))
    get = lambda index: ''.join(notebook['cells'][index]['source'])
    put = lambda index, text: notebook['cells'][index].update(source=text.splitlines(keepends=True))
    pack = literals(get(6))
    core = core_upgrade(zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['crawler_snapshot.py'])))
    pack['EMBEDDED_FILES']['crawler_snapshot.py'] = encode(core)
    pack['EMBEDDED_SHA256']['crawler_snapshot.py'] = hashlib.sha256(core).hexdigest()
    pack['EMBEDDED_FILES']['ask120_snapshot.py'] = encode(ask120_body)
    pack['EMBEDDED_SHA256']['ask120_snapshot.py'] = hashlib.sha256(ask120_body).hexdigest()
    diagnostic = zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['diagnostics_snapshot.py'])).decode('utf-8')
    if "'ask120_snapshot.py'" not in diagnostic:
        diagnostic = diagnostic.replace("'longchau_snapshot.py'):", "'longchau_snapshot.py', 'ask120_snapshot.py'):")
    pack['EMBEDDED_FILES']['diagnostics_snapshot.py'] = encode(diagnostic.encode('utf-8'))
    pack['EMBEDDED_SHA256']['diagnostics_snapshot.py'] = hashlib.sha256(diagnostic.encode('utf-8')).hexdigest()
    put(6, replace_literals(get(6), {key: pack[key] for key in ('EMBEDDED_FILES', 'EMBEDDED_SHA256')}))

    setup = get(6)
    if 'HAS_ASK120_SAMPLE =' not in setup:
        guard = '''HAS_ASK120_SAMPLE = False
if (RUN_DIR / 'sample.jsonl').exists():
    from urllib.parse import urlsplit
    with (RUN_DIR / 'sample.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            if not line.strip():
                continue
            ask120_url = urlsplit(json.loads(line)['url'])
            ask120_id = ask120_url.path[len('/question/'):-len('.htm')]
            if ((ask120_url.hostname or '').lower() in ('120ask.com', 'www.120ask.com')
                    and ask120_url.path.startswith('/question/') and ask120_url.path.endswith('.htm')
                    and ask120_id.isdigit()):
                HAS_ASK120_SAMPLE = True
                break
if not POSTPROCESS_ONLY and HAS_ASK120_SAMPLE and (RUN_DIR / 'corpus_config.json').exists():
    saved_ask120_runtime = json.loads((RUN_DIR / 'corpus_config.json').read_text(encoding='utf-8'))
    for name, key in (('ask120_snapshot.py', 'ask120_sha256'),
                      ('crawler_snapshot.py', 'crawler_sha256'),
                      ('corpus_runner_snapshot.py', 'runner_sha256')):
        if saved_ask120_runtime.get(key) != EMBEDDED_SHA256[name]:
            raise ValueError('Run 120ask cũ cần RUN_TAG mới + RECOVERY_RUN_PATH; '
                             'không tự thay text/checkpoint đã trích bằng parser cũ.')

'''
        setup = setup.replace('HAS_VOV_SAMPLE = False', guard + 'HAS_VOV_SAMPLE = False', 1)
        setup = setup.replace(
            "(name == 'longchau_snapshot.py' and POSTPROCESS_ONLY and HAS_LONGCHAU_SAMPLE)",
            "(name == 'ask120_snapshot.py' and POSTPROCESS_ONLY and HAS_ASK120_SAMPLE) or "
            "(name == 'longchau_snapshot.py' and POSTPROCESS_ONLY and HAS_LONGCHAU_SAMPLE)",
            1,
        )
    put(6, setup)
    config = get(2)
    if 'REQUESTS_TRUST_ENV =' not in config:
        config = config.replace("USER_AGENT = 'Mozilla/5.0", "REQUESTS_TRUST_ENV = False  # False như lượt thử Kaggle; True nếu môi trường bắt buộc proxy\nUSER_AGENT = 'Mozilla/5.0", 1)
        config = config.replace("if type(POSTPROCESS_ONLY) is not bool:\n",
                                "if type(REQUESTS_TRUST_ENV) is not bool:\n    raise ValueError('REQUESTS_TRUST_ENV phải là bool.')\nif type(POSTPROCESS_ONLY) is not bool:\n", 1)
    put(2, config)
    crawl = get(12)
    if "'requests_trust_env':" not in crawl:
        crawl = crawl.replace("'user_agent': USER_AGENT, 'delay': DELAY, 'attempts': ATTEMPTS,",
                              "'user_agent': USER_AGENT, 'requests_trust_env': REQUESTS_TRUST_ENV, "
                              "'delay': DELAY, 'attempts': ATTEMPTS,", 1)
    put(12, crawl)
    put(11, get(11).replace('120ask V2', '120ask V3'))
    note = (
        '\n\n120ask V3 chỉ định tuyến `/question/<id>.htm`; `text` giữ câu hỏi và từng lượt theo thread. '
        '`ask120_threads`, `ask120_text_raw` và `ask120_qc` nằm trong record checkpoint; Parquet corpus không thêm cột. '
        'Run parser cũ phải dùng RUN_TAG mới + RECOVERY_RUN_PATH để tái trích raw, không resume ghi đè.\n'
    )
    if '120ask V3 chỉ định tuyến' not in get(11):
        put(11, get(11).rstrip() + note)
    write(notebook, MAIN)


def _update_domain(ask120_body):
    notebook = json.loads(DOMAIN.read_text(encoding='utf-8'))
    get = lambda index: ''.join(notebook['cells'][index]['source'])
    put = lambda index, text: notebook['cells'][index].update(source=text.splitlines(keepends=True))
    pack = literals(get(7))
    core = core_upgrade(zlib.decompress(base64.b85decode(pack['CRAWLER_PAYLOAD'])))
    values = {
        'CRAWLER_PAYLOAD': encode(core),
        'CRAWLER_SHA256': hashlib.sha256(core).hexdigest(),
        'ASK120_PAYLOAD': encode(ask120_body),
        'ASK120_SHA256': hashlib.sha256(ask120_body).hexdigest(),
    }
    setup = replace(get(7), values)
    if 'ask120_path = RUN_DIR' not in setup:
        helper = '''
ask120_body = zlib.decompress(base64.b85decode(ASK120_PAYLOAD))
if hashlib.sha256(ask120_body).hexdigest() != ASK120_SHA256:
    raise ValueError('120ask snapshot hash mismatch')
ask120_path = RUN_DIR / 'ask120_snapshot.py'
if ask120_path.exists() and ask120_path.read_bytes() != ask120_body:
    raise ValueError('120ask parser changed; use a new run and RECOVERY_RUN_DIR')
ask120_path.write_bytes(ask120_body)
'''
        setup += helper
    put(7, setup)
    config = get(3)
    if 'REQUESTS_TRUST_ENV =' not in config:
        config = config.replace("USER_AGENT = 'Mozilla/5.0", "REQUESTS_TRUST_ENV = False  # True nếu môi trường bắt buộc HTTP(S)_PROXY\nUSER_AGENT = 'Mozilla/5.0", 1)
        config = config.replace("if type(WORKERS) is not int or WORKERS < 1:\n",
                                "if type(REQUESTS_TRUST_ENV) is not bool:\n    raise ValueError('REQUESTS_TRUST_ENV phải là bool.')\nif type(WORKERS) is not int or WORKERS < 1:\n", 1)
    put(3, config)
    setup = get(7)
    if 'crawler.TRUST_ENV = REQUESTS_TRUST_ENV' not in setup:
        setup = setup.replace("crawler.ROBOT_AGENT = USER_AGENT.split('/', 1)[0]",
                              "crawler.ROBOT_AGENT = USER_AGENT.split('/', 1)[0]\n"
                              "crawler.TRUST_ENV = REQUESTS_TRUST_ENV", 1)
    put(7, setup)
    put(10, get(10).replace('120ask V2', '120ask V3'))
    note = (
        '\n\n120ask V3 chỉ áp dụng cho `/question/<id>.htm`, giữ thứ tự thread và ghi QC chi tiết '
        'trong record JSON. URL khác trên domain dùng route hiện có. Parser đổi thì tạo run mới và recovery raw.\n'
    )
    if '120ask V3 chỉ áp dụng' not in get(10):
        put(10, get(10).rstrip() + note)
    write(notebook, DOMAIN)


def main():
    # Update only the established 120ask routes/snapshots; do not rebuild unrelated engines.
    ask120_body = (ROOT / 'scripts/ask120.py').read_bytes()
    compile(ask120_body, 'ask120_snapshot.py', 'exec')
    _update_main(ask120_body)
    _update_domain(ask120_body)
    from build_120ask_gate_notebook import main as build_check
    build_check()
    print(json.dumps({'parser': '120ask_qa_dom_v3',
                      'sha256': hashlib.sha256(ask120_body).hexdigest()}, indent=2))


if __name__ == '__main__':
    main()
