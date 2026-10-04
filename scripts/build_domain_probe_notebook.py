"""Build a standalone notebook for the fixed 97-host ViBioMIR sample."""
from pathlib import Path
import base64
import hashlib
import json
import pprint
import textwrap
import zlib
from collections import Counter
import argparse
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BROWSER_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36'


def select_followup(baseline_zip):
    import pyarrow.parquet as pq
    with zipfile.ZipFile(baseline_zip) as archive:
        names = [n for n in archive.namelist() if n.endswith('/ket_qua.json')]
        if len(names) != 1:
            raise ValueError('Expected exactly one baseline result.')
        prefix = names[0].rsplit('/', 1)[0] + '/'
        rows = json.loads(archive.read(names[0]))
        profile = json.loads(archive.read(prefix + 'source_profile.json'))
        manifest = json.loads(archive.read(prefix + 'manifest.json'))
    source = ROOT / 'data/links_corpus.parquet'
    with source.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['source_sha256']:
            raise ValueError('Source hash differs from baseline.')
    bad = {r['domain']: r for r in rows if r['access_result'] == 'KHONG_VAO_DUOC'
           or (r['access_result'] == 'VAO_DUOC' and r['quality_status'] != 'accepted')}
    exclude = {r['sample_url'] for r in rows}
    old_ids = {r['sample_id'] for r in rows}
    source_pairs = {}
    pools = {h: {} for h in bad}
    counts = Counter()
    for batch in pq.ParquetFile(source).iter_batches(columns=['id', 'url']):
        for doc_id, url in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist()):
            host = url.split('/', 3)[2].lower()
            counts[host] += 1
            if doc_id in old_ids:
                source_pairs[doc_id] = url
            if host not in pools or url in exclude:
                continue
            pool = pools[host]
            if url in pool:
                score, saved_id = pool[url]
                pool[url] = (score, min(saved_id, doc_id))
                continue
            score = hashlib.blake2b(('42\0' + url).encode(), digest_size=16).digest()
            if len(pool) < 4:
                pool[url] = (score, doc_id)
            else:
                worst = max(pool, key=lambda u: (pool[u][0], u))
                if (score, url) < (pool[worst][0], worst):
                    del pool[worst]
                    pool[url] = (score, doc_id)
    if dict(counts) != profile['host_counts'] or source_pairs != {r['sample_id']: r['sample_url'] for r in rows}:
        raise ValueError('Baseline URL/count mismatch with source.')
    samples, baseline = [], {}
    for domain in sorted(bad, key=lambda h: (-counts[h], h)):
        old = bad[domain]
        extra = sorted(pools[domain].items(), key=lambda item: (item[1][0], item[0]))
        baseline[domain] = dict(old, requested_additional=4, selected_additional=len(extra), shortfall=4-len(extra))
        samples.append({'id': old['sample_id'], 'url': old['sample_url'], 'domain': domain, 'sample_role': 'original', 'sample_index': 0})
        samples.extend({'id': doc_id, 'url': url, 'domain': domain, 'sample_role': 'additional', 'sample_index': i}
                       for i, (url, (_, doc_id)) in enumerate(extra, 1))
    profile['sample_host_counts'] = {h: 0 for h in counts}
    profile['sample_host_counts'].update(Counter(r['domain'] for r in samples))
    with Path(baseline_zip).open('rb') as stream:
        archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    manifest.update(baseline_archive=Path(baseline_zip).name, baseline_archive_sha256=archive_hash)
    probe = {'samples': samples, 'source_profile': profile, 'manifest': manifest, 'baseline': baseline}
    (ROOT / 'data/domain_probe_followup_samples.json').write_text(json.dumps(probe, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return probe


def build(probe=None, priority_five=False):
    if probe is None:
        probe = json.loads((ROOT / 'data/domain_probe_followup_samples.json').read_text(encoding='utf-8'))
    samples, profile, manifest = probe['samples'], probe['source_profile'], probe['manifest']
    if len({r['id'] for r in samples}) != len(samples) or len({r['url'] for r in samples}) != len(samples):
        raise ValueError('Duplicate sample ID or URL.')
    raw = (ROOT / 'src/vibiomir/corpus/crawler.py').read_bytes()
    # This notebook uses its own browser-style HTTP UA; other crawl entry points are unchanged.
    raw = raw.replace(b"UA = 'ViBioMIRResearchCrawler/0.1'", ('UA = ' + repr(BROWSER_UA)).encode())
    raw = raw.replace(b"ROBOT_AGENT = 'ViBioMIRResearchCrawler'", b"ROBOT_AGENT = 'Mozilla'")
    priority_raw = (ROOT / 'src/vibiomir/corpus/priority_probe.py').read_bytes()
    cells = []

    def add(kind, source, hidden=False):
        cell = {'cell_type': kind, 'id': f'domain-probe-{len(cells):02d}',
                'metadata': {'jupyter': {'source_hidden': True}} if hidden else {},
                'source': textwrap.dedent(source).strip() + '\n'}
        if kind == 'code':
            cell.update(execution_count=None, outputs=[])
            compile(cell['source'], cell['id'], 'exec')
        cells.append(cell)

    add('markdown', f'''
        # Test domain samples — {len(samples)} URL / {len(probe['baseline'])} hostname

        Chạy các ô từ trên xuống (**Run All**). Kaggle cần bật **Internet**; chỉ dùng CPU.
        Notebook giữ 1 URL cũ và thêm tối đa 4 URL khác nhau cho mỗi hostname,
        lấy từ `links_corpus.parquet` (4.394.718 dòng; seed 42).
        Có {sum(r['sample_role'] == 'original' for r in samples)} mẫu cũ và {sum(r['sample_role'] == 'additional' for r in samples)} mẫu bổ sung.
        Không cần clone repo, tải Parquet hay upload code Python.

        Dùng snapshot crawler hiện tại trong repo: kiểm tra robots.txt, retry,
        giới hạn tốc độ, tải HTML/PDF, trích xuất và kiểm tra chất lượng (QC).
        Kết quả sẽ khác theo thời điểm và môi trường mạng.
        HTTP User-Agent là chuỗi trình duyệt Mozilla/Chrome, có thể chỉnh ở ô cấu hình.
        User-Agent không đảm bảo hết 403; kết quả thực tế được giữ nguyên.
        Bảng ưu tiên domain lỗi xếp theo số URL hostname trong toàn dataset giảm dần,
        không xếp theo số lỗi mẫu. Giữ riêng subdomain, số dòng nguồn chưa loại URL trùng.

        - **VAO_DUOC**: URL cuối trả HTTP 2xx, kể cả khi trích xuất/QC thất bại.
        - **KHONG_VAO_DUOC**: đã chạy nhưng không lấy được HTTP 2xx của trang đích.
        - **CHUA_CHAY**: chưa có checkpoint, không tính là lỗi.

        `robots_http_status` là HTTP của robots.txt; `http_status` là HTTP của trang.
        Dừng do robots là kết quả của chính sách crawler, không chứng minh website
        không mở được bằng trình duyệt. Nhóm ưu tiên có thêm đối chiếu Selenium.
        Vài mẫu mỗi hostname chưa đại diện cho toàn bộ URL trên website.
    ''')
    if priority_five:
        add('markdown', '''
            Nhóm ưu tiên: **cnkang, 120ask, familydoctor.com.cn, ask.39.net, zysjonline**,
            tổng 2.910.092 dòng URL (66,22% dataset), 5 URL mỗi hostname.
            Chế độ này tải trực tiếp URL mẫu công khai bằng Requests với header trình duyệt;
            robots không chặn bước kiểm tra truy cập. Kết quả Requests và Selenium được giữ riêng.
            `BROWSER_TEST_MODE` mặc định thử Selenium cho URL Requests lỗi;
            `first_each_domain_and_failures` dùng khi muốn đối chiếu thêm mẫu đầu mỗi hostname.
            HTTP 2xx vẫn cần QC: trang lỗi trả 200 hoặc nội dung quảng cáo không phải bài sạch.
        ''')
    add('markdown', '''
        ## 1. Cấu hình

        Mặc định chạy toàn bộ URL đã nhúng. Có thể đặt `MAX_NEW = 10` để thử trước, rồi đổi
        thành `None` và chỉ chạy lại ô crawl để làm tiếp. Checkpoint đã có, kể cả
        lỗi, được bỏ qua. Muốn thử lại tất cả URL từ đầu, chạy lại ô cấu hình để
        tạo thư mục mới. `RESUME_RUN_DIR` dùng để tiếp tục thư mục output đã có.
    ''')
    add('code', 'USER_AGENT = ' + repr(BROWSER_UA) + '\n' + textwrap.dedent('''
        WORKERS = 8
        DELAY = 1.0
        ATTEMPTS = 3
        ROBOTS_ATTEMPTS = 3
        ROBOTS_CONNECT_TIMEOUT = 15.0
        ROBOTS_READ_TIMEOUT = 30.0
        ROBOTS_RETRY_BUDGET = 90.0
        ROBOTS_FAILURE_TTL = 30.0
        NETWORK_CHECK_DOMAINS = ('www.120ask.com', 'bingli.iiyi.com', 'article.iiyi.com')
        BROWSER_TEST_MODE = 'failed_only'  # off / first_each_domain_and_failures / all
        CHROME_BINARY = None       # None: Selenium Manager tìm hoặc tải Chrome phù hợp
        PAGE_CONNECT_TIMEOUT = 15.0
        PAGE_READ_TIMEOUT = 25.0
        PAGE_REQUEST_BUDGET = 75.0
        PAGE_ATTEMPTS = 2
        MAX_NEW = None           # None: toàn bộ; 10: thêm tối đa 10 URL
        RESUME_RUN_DIR = None    # Hoặc đường dẫn thư mục run đã có

        from pathlib import Path
        from datetime import datetime, timezone
        import json
        import sys
        import uuid

        if sys.version_info < (3, 11):
            raise RuntimeError('Cần Python 3.11 trở lên.')
        if type(WORKERS) is not int or WORKERS < 1:
            raise ValueError('WORKERS phải là số nguyên dương.')
        if type(ATTEMPTS) is not int or ATTEMPTS < 1:
            raise ValueError('ATTEMPTS phải là số nguyên dương.')
        if isinstance(DELAY, bool) or not isinstance(DELAY, (int, float)) or not 0 <= DELAY < float('inf'):
            raise ValueError('DELAY phải hữu hạn và không âm.')
        if MAX_NEW is not None and (type(MAX_NEW) is not int or MAX_NEW < 1):
            raise ValueError('MAX_NEW phải là None hoặc số nguyên dương.')
        OUTPUT_BASE = (Path('/kaggle/working') if Path('/kaggle/working').is_dir()
                       else Path('/content') if Path('/content').is_dir()
                       else Path.cwd() / 'runs')
        RUN_DIR = (Path(RESUME_RUN_DIR).expanduser().resolve() if RESUME_RUN_DIR else
                   OUTPUT_BASE / ('domain_probe_' + datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
                                  + '_' + uuid.uuid4().hex[:6]))
        if RESUME_RUN_DIR and not (RUN_DIR / 'manifest.json').is_file():
            raise ValueError('RESUME_RUN_DIR phải chứa manifest.json của notebook này.')
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        print('Output:', RUN_DIR)
    ''') + f'\nPRIORITY_FIVE = {priority_five!r}\n'
        + ('NETWORK_CHECK_DOMAINS = ' + repr(tuple(probe['baseline'])) + '\n' if priority_five else '')
        + ('BROWSER_TEST_MODE = "off"\n' if not priority_five else ''))
    add('markdown', f'''
        ## 2. Cài dependencies

        Cài các package crawler cần trong môi trường hiện tại. Phiên bản thực tế
        và log pip được lưu trong output. Khi resume, dùng phiên bản đã lưu.
    ''')
    add('code', '''
        import subprocess
        import importlib.metadata

        packages = ['pyarrow', 'requests', 'trafilatura', 'pymupdf', 'tld', 'ipython']
        if PRIORITY_FIVE and BROWSER_TEST_MODE != 'off':
            packages.append('selenium')
        requirement_file = RUN_DIR / 'notebook_requirements.txt'
        install_args = ['-r', str(requirement_file)] if requirement_file.exists() else packages
        installation = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--quiet', *install_args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding='utf-8', errors='replace',
        )
        (RUN_DIR / 'pip_install.log').write_text(installation.stdout or '', encoding='utf-8')
        if installation.returncode:
            print(installation.stdout)
            raise RuntimeError('Cài dependencies thất bại; xem pip_install.log.')
        versions = {name: importlib.metadata.version(name) for name in packages}
        if not requirement_file.exists():
            requirement_file.write_text(''.join(f'{p}=={v}\\n' for p, v in versions.items()), encoding='utf-8')
        print(json.dumps(versions, indent=2))
    ''')
    add('markdown', f'''
        ## 3. Danh sách mẫu và snapshot crawler

        {len(samples)} mẫu giữ nguyên ID/URL nguồn. Ô code có thể mở để kiểm tra danh sách
        và snapshot. Crawler được kiểm tra SHA-256 trước khi import.
    ''')
    add('code',
        'SAMPLES = ' + pprint.pformat(samples, width=110, sort_dicts=False) + '\n\n'
        + 'SOURCE_PROFILE = ' + pprint.pformat(profile, width=110, sort_dicts=False) + '\n\n'
        + 'BASELINE_DOMAINS = ' + pprint.pformat(probe['baseline'], width=110, sort_dicts=False) + '\n\n'
        + f'EXPECTED_URL_COUNT = {len(samples)}\nEXPECTED_DOMAIN_COUNT = {len(probe["baseline"])}\n'
        + 'BASELINE_ARCHIVE = ' + repr(manifest['baseline_archive']) + '\n'
        + 'BASELINE_ARCHIVE_SHA256 = ' + repr(manifest['baseline_archive_sha256']) + '\n'
        + f"SOURCE_SHA256 = {manifest['source_sha256']!r}\n"
        + f"CRAWLER_SHA256 = {hashlib.sha256(raw).hexdigest()!r}\n"
        + f"CRAWLER_PAYLOAD = {base64.b85encode(zlib.compress(raw, 9)).decode('ascii')!r}\n\n"
        + f"PROBE_KIND = {'priority_five_public_pages' if priority_five else 'expanded_failed_domains_browser_ua'!r}\n"
        + f"PRIORITY_SHA256 = {hashlib.sha256(priority_raw).hexdigest()!r}\n"
        + f"PRIORITY_PAYLOAD = {base64.b85encode(zlib.compress(priority_raw, 9)).decode('ascii')!r}\n\n"
        + textwrap.dedent('''
            import base64
            import hashlib
            import importlib.util
            import zlib

            def sha256(body):
                return hashlib.sha256(body).hexdigest()

            sample_bytes = ''.join(json.dumps(r, ensure_ascii=False) + '\\n' for r in SAMPLES).encode('utf-8')
            crawler_bytes = zlib.decompress(base64.b85decode(CRAWLER_PAYLOAD))
            if sha256(crawler_bytes) != CRAWLER_SHA256:
                raise ValueError('Snapshot crawler bị hỏng.')
            if (len(SAMPLES) != EXPECTED_URL_COUNT or len({r['domain'] for r in SAMPLES}) != EXPECTED_DOMAIN_COUNT
                    or len({r['url'] for r in SAMPLES}) != len(SAMPLES) or len({r['id'] for r in SAMPLES}) != len(SAMPLES)):
                raise ValueError('Danh sách mẫu thiếu hoặc trùng ID/URL.')
            manifest_path = RUN_DIR / 'manifest.json'
            sample_path = RUN_DIR / 'sample.jsonl'
            crawler_path = RUN_DIR / 'crawler_snapshot.py'
            if manifest_path.exists():
                saved = json.loads(manifest_path.read_text(encoding='utf-8'))
                if (saved.get('probe_kind') != PROBE_KIND
                        or saved.get('sample_sha256') != sha256(sample_bytes)
                        or saved.get('source_sha256') != SOURCE_SHA256):
                    raise ValueError('Run cũ không khớp mẫu của notebook này.')
                if not sample_path.exists() or sample_path.read_bytes() != sample_bytes:
                    raise ValueError('Danh sách mẫu của run cũ đã thay đổi.')
                if not crawler_path.exists() or sha256(crawler_path.read_bytes()) != CRAWLER_SHA256:
                    raise ValueError('Snapshot khác run cũ; hãy tạo run mới.')
                if json.loads((RUN_DIR / 'source_profile.json').read_text(encoding='utf-8')) != SOURCE_PROFILE:
                    raise ValueError('Source profile của run cũ đã thay đổi.')
            else:
                sample_path.write_bytes(sample_bytes)
                crawler_path.write_bytes(crawler_bytes)
                (RUN_DIR / 'source_profile.json').write_text(
                    json.dumps(SOURCE_PROFILE, ensure_ascii=False, indent=2), encoding='utf-8')
                manifest_path.write_text(json.dumps({
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'probe_kind': PROBE_KIND, 'dataset': 'AIGuruTinix/ViBioMIR',
                    'source': 'embedded samples from data/links_corpus.parquet',
                    'source_sha256': SOURCE_SHA256, 'source_rows': SOURCE_PROFILE['rows'],
                    'sampling': 'distinct_url_hash_sample', 'seed': 42, 'selected': len(SAMPLES),
                    'selected_domains': EXPECTED_DOMAIN_COUNT,
                    'baseline_archive': BASELINE_ARCHIVE, 'baseline_archive_sha256': BASELINE_ARCHIVE_SHA256,
                    'sample_sha256': sha256(sample_bytes),
                }, ensure_ascii=False, indent=2), encoding='utf-8')

            spec = importlib.util.spec_from_file_location('domain_probe_crawler', crawler_path)
            crawler = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = crawler
            spec.loader.exec_module(crawler)
            priority_path = RUN_DIR / 'priority_probe_snapshot.py'
            priority_bytes = zlib.decompress(base64.b85decode(PRIORITY_PAYLOAD))
            if sha256(priority_bytes) != PRIORITY_SHA256:
                raise ValueError('Priority probe snapshot bị hỏng.')
            if priority_path.exists() and sha256(priority_path.read_bytes()) != PRIORITY_SHA256:
                raise ValueError('Priority probe khác run cũ; tạo run mới.')
            priority_path.write_bytes(priority_bytes)
            priority_spec = importlib.util.spec_from_file_location('domain_priority_probe', priority_path)
            priority_probe = importlib.util.module_from_spec(priority_spec)
            sys.modules[priority_spec.name] = priority_probe
            priority_spec.loader.exec_module(priority_probe)
            if not isinstance(USER_AGENT, str) or not USER_AGENT.strip() or any(c in USER_AGENT for c in ('\\r', '\\n')):
                raise ValueError('USER_AGENT phải là chuỗi header hợp lệ.')
            crawler.UA = USER_AGENT
            crawler.ROBOT_AGENT = USER_AGENT.split('/', 1)[0]
            (RUN_DIR / 'baseline_domains.json').write_text(json.dumps(BASELINE_DOMAINS, ensure_ascii=False, indent=2), encoding='utf-8')
            print(f'Đã nạp {len(SAMPLES)} URL mẫu và crawler {crawler.VERSION}.')
        '''), hidden=True)
    add('markdown', '''
        ## 4. Chuẩn bị bảng kết quả và phân loại lỗi

        Output riêng: `vao_duoc.csv`, `khong_vao_duoc.csv`, `chua_chay.csv`,
        `loi_theo_loai.csv`, `can_xem_noi_dung.csv`; bảng tổng là `ket_qua.csv`.
        Các CSV dùng UTF-8 BOM để mở được tiếng Việt trong Excel.
        `error_detail` giữ nguyên lỗi kỹ thuật; `reason` diễn giải tiếng Việt.
        Mở `ket_qua.html` để lọc theo domain hoặc trạng thái.
        `uu_tien_fix_domain.csv/html` xếp hostname còn lỗi theo số URL dataset giảm dần.
        `tong_hop_domain.csv` gồm cả hostname đã phục hồi; `WEB_ERRORS.md` là báo cáo lỗi chi tiết.
    ''')
    add('code', r'''
        import csv
        import html
        import shutil
        from collections import Counter
        from IPython.display import HTML, FileLink, display

        STATUS_REASONS = {
            'robots_unknown': 'Không xác định được chính sách robots.txt; crawler dừng trước khi tải trang.',
            'robots_denied': 'robots.txt trả HTTP 401/403; crawler dừng theo chính sách robots.',
            'robots_disallowed': 'robots.txt không cho phép crawler tải URL này.',
            'http_error': 'Trang đích trả HTTP ngoài khoảng 200–299.',
            'network_error': 'Không tải được trang do lỗi kết nối sau retry.',
            'unsafe_address': 'Địa chỉ đích không phải IP public được crawler cho phép.',
            'invalid_url': 'URL không hợp lệ hoặc dùng cổng ngoài 80/443.',
            'oversized': 'Phản hồi vượt giới hạn kích thước của crawler.',
            'response_deadline': 'Tải phản hồi vượt giới hạn thời gian tổng.',
            'rate_limited_deferred': 'Server yêu cầu chờ Retry-After quá lâu; crawler hoãn URL.',
            'redirect_limit': 'Vượt số lần redirect cho phép.',
            'unsupported_content_type': 'Đã tải phản hồi nhưng định dạng không được hỗ trợ.',
            'unexpected_error': 'Lỗi ngoài dự kiến; xem error_detail.',
        }

        def classify_error(status, detail, http_status):
            lower = detail.lower()
            if status == 'http_error':
                return f'page_http_{http_status}'
            if status == 'robots_disallowed':
                return 'robots_disallowed'
            if status.startswith('robots_') and 'robots http ' in lower:
                return 'robots_http_' + lower.split('robots http ', 1)[1].split()[0]
            if 'html instead of robots.txt' in lower:
                return 'robots_html_instead_of_txt'
            prefix = 'robots_' if status.startswith('robots_') else ''
            if 'waiting for domain lock' in lower:
                return prefix + 'domain_lock_budget'
            if 'request budget exhausted' in lower or 'retry budget exhausted' in lower:
                return prefix + 'budget_exhausted'
            if 'winerror 10013' in lower or 'network is unreachable' in lower:
                return prefix + 'environment_network_blocked'
            if any(s in lower for s in ('timed out', 'timeout')):
                return prefix + 'timeout'
            if any(s in lower for s in ('sslerror', 'certificate verify failed', 'ssl:')):
                return prefix + 'ssl_error'
            if any(s in lower for s in ('nameresolutionerror', 'getaddrinfo failed', 'name or service not known', 'failed to resolve')):
                return prefix + 'dns_error'
            if any(s in lower for s in ('connection refused', 'failed to establish a new connection', 'connection reset')):
                return prefix + 'connection_error'
            return status

        def result_rows():
            rows = []
            for sample in sorted(SAMPLES, key=lambda s: (-SOURCE_PROFILE['host_counts'][s['domain']], s['domain'], s['sample_index'])):
                record_path = RUN_DIR / 'records' / f"{sample['id']}.json"
                record = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else {}
                if record and (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
                    raise ValueError('Checkpoint không khớp ID/URL nguồn.')
                status = record.get('status', 'pending')
                page_http = record.get('http_status')
                robots = record.get('robots', {})
                # Robots failure may happen before fetch() attaches its evidence to the record.
                if status.startswith('robots_') and not robots:
                    from urllib.parse import urlsplit
                    target = record.get('requests', [{}])[-1].get('url', sample['url']) if record.get('requests') else sample['url']
                    if record.get('redirects'):
                        target = record['redirects'][-1]['to']
                    p = urlsplit(target)
                    robot_file = RUN_DIR / 'robots' / (sha256(f'{p.scheme}://{p.netloc}'.encode()) + '.json')
                    if robot_file.exists():
                        robots = json.loads(robot_file.read_text(encoding='utf-8'))
                detail = record.get('error', '')
                browser_file = RUN_DIR / 'browser_records' / f"{sample['id']}.json"
                browser = json.loads(browser_file.read_text(encoding='utf-8')) if browser_file.exists() else {}
                if browser and (browser.get('id'), browser.get('url')) != (sample['id'], sample['url']):
                    raise ValueError('Browser checkpoint không khớp ID/URL.')
                access = ('CHUA_CHAY' if status == 'pending' else
                          'VAO_DUOC' if page_http is not None and 200 <= page_http < 300 else 'KHONG_VAO_DUOC')
                flags = record.get('quality_flags', [])
                if status == 'pending':
                    reason, error_type, stage = 'Chưa chạy URL này.', '', 'pending'
                elif status == 'extracted':
                    stage = 'done'
                    error_type = ('qc_' + record['quality_status'] if record.get('quality_status') in ('review', 'rejected') else '')
                    reason = ('Tải được và nội dung đạt QC tự động.' if record.get('quality_status') == 'accepted'
                              else 'Tải được, nhưng nội dung cần xem lại hoặc bị QC loại: ' + ', '.join(flags))
                else:
                    stage = ('robots' if status.startswith('robots_') else 'extraction' if access == 'VAO_DUOC' else 'fetch')
                    error_type = classify_error(status, detail, page_http)
                    reason = STATUS_REASONS.get(status, status)
                rows.append({
                    'domain': sample['domain'], 'dataset_url_count': SOURCE_PROFILE['host_counts'][sample['domain']],
                    'sample_id': sample['id'], 'sample_url': sample['url'], 'access_result': access,
                    'http_status': page_http, 'robots_http_status': robots.get('status'),
                    'robots_attempt_count': robots.get('attempt_count'),
                    'robots_cache_hit': robots.get('cache_hit'),
                    'robots_fetch_id': robots.get('fetch_id', ''),
                    'robots_error_kind': robots.get('error_kind', ''),
                    'robots_elapsed_seconds': robots.get('elapsed_seconds'),
                    'robots_lock_wait_seconds': robots.get('lock_wait_seconds'),
                    'crawl_status': status, 'failure_stage': stage, 'error_type': error_type,
                    'reason': reason, 'error_detail': detail, 'quality_status': record.get('quality_status', ''),
                    'quality_flags': '; '.join(flags), 'char_count': record.get('char_count'),
                    'title': record.get('title', ''), 'final_url': record.get('final_url', ''),
                    'elapsed_seconds': record.get('elapsed_seconds'),
                    'page_attempted': bool(record.get('requests')),
                    'browser_status': browser.get('status', ''),
                    'browser_http_status': browser.get('http_status'),
                    'browser_quality_status': browser.get('quality_status', ''),
                    'browser_char_count': browser.get('char_count'),
                    'browser_final_url': browser.get('final_url', ''),
                    'browser_error': browser.get('error', ''),
                    'sample_role': sample['sample_role'], 'sample_index': sample['sample_index'],
                })
            return rows

        def domain_rows(rows):
            result = []
            for domain in sorted(BASELINE_DOMAINS, key=lambda h: (-SOURCE_PROFILE['host_counts'][h], h)):
                selected = [r for r in rows if r['domain'] == domain]
                failed = [r for r in selected if r['access_result'] == 'KHONG_VAO_DUOC']
                content = [r for r in selected if r['access_result'] == 'VAO_DUOC' and r['quality_status'] != 'accepted']
                pending = sum(r['access_result'] == 'CHUA_CHAY' for r in selected)
                errors = Counter(r['error_type'] for r in failed + content)
                result.append({
                    'domain': domain, 'dataset_url_count': SOURCE_PROFILE['host_counts'][domain],
                    'baseline_error_type': BASELINE_DOMAINS[domain]['error_type'],
                    'selected_urls': len(selected), 'additional_urls': sum(r['sample_role'] == 'additional' for r in selected),
                    'missing_additional_urls': BASELINE_DOMAINS[domain]['shortfall'],
                    'completed_urls': len(selected) - pending, 'pending_urls': pending,
                    'page_not_attempted': sum(not r['page_attempted'] and r['access_result'] != 'CHUA_CHAY' for r in selected),
                    'accessible_urls': sum(r['access_result'] == 'VAO_DUOC' for r in selected),
                    'access_failures': len(failed), 'content_issues': len(content),
                    'total_problem_urls': len(failed) + len(content),
                    'additional_problem_urls': sum(r['sample_role'] == 'additional' for r in failed + content),
                    'error_types': '; '.join(f'{kind}: {n}' for kind, n in sorted(errors.items())),
                    'test_status': 'CHUA_CHAY' if pending == len(selected) else 'CHUA_HOAN_TAT' if pending else 'CON_LOI' if failed or content else 'DA_PHUC_HOI',
                })
            return result

        def write_csv(name, rows, fields):
            temporary = RUN_DIR / (name + '.tmp')
            with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            temporary.replace(RUN_DIR / name)

        def save_outputs(show=True):
            rows = result_rows()
            fields = list(rows[0])
            counts = Counter(r['access_result'] for r in rows)
            summary = {'selected': len(rows), 'vao_duoc': counts['VAO_DUOC'],
                       'khong_vao_duoc': counts['KHONG_VAO_DUOC'], 'chua_chay': counts['CHUA_CHAY'],
                       'crawl_status_counts': dict(Counter(r['crawl_status'] for r in rows)),
                       'quality_status_counts': dict(Counter(r['quality_status'] for r in rows if r['quality_status'])),
                       'created_at': datetime.now(timezone.utc).isoformat()}
            domains = domain_rows(rows)
            priority = [dict(priority_rank=i, **r) for i, r in enumerate((r for r in domains if r['total_problem_urls']), 1)]
            summary.update(hostnames=len(domains), domains_with_errors=len(priority),
                           priority_order='dataset_url_count descending', user_agent=USER_AGENT,
                           page_not_attempted=sum(not r['page_attempted'] and r['access_result'] != 'CHUA_CHAY' for r in rows),
                           additional_urls=sum(r['sample_role'] == 'additional' for r in rows))
            summary.update(request_mode='direct_public_page_probe' if PRIORITY_FIVE else 'robots_enforced',
                           browser_tested=sum(bool(r['browser_status']) for r in rows),
                           browser_http_2xx=sum(r['browser_http_status'] is not None and 200 <= r['browser_http_status'] < 300 for r in rows))
            write_csv('tong_hop_domain.csv', domains, list(domains[0]))
            write_csv('uu_tien_fix_domain.csv', priority, ['priority_rank', *domains[0]])
            (RUN_DIR / 'uu_tien_fix_domain.json').write_text(json.dumps(priority, ensure_ascii=False, indent=2), encoding='utf-8')
            write_csv('ket_qua.csv', rows, fields)
            write_csv('requests_vs_selenium.csv', rows, fields)
            for value, filename in [('VAO_DUOC', 'vao_duoc.csv'), ('KHONG_VAO_DUOC', 'khong_vao_duoc.csv'), ('CHUA_CHAY', 'chua_chay.csv')]:
                write_csv(filename, [r for r in rows if r['access_result'] == value], fields)
            write_csv('can_xem_noi_dung.csv', [r for r in rows if r['access_result'] == 'VAO_DUOC' and r['quality_status'] != 'accepted'], fields)
            failures = Counter(r['error_type'] for r in rows if r['access_result'] == 'KHONG_VAO_DUOC')
            errors = [{'error_type': kind, 'domain_count': len({r['domain'] for r in rows if r['access_result'] == 'KHONG_VAO_DUOC' and r['error_type'] == kind}),
                       'url_count': n,
                       'domains': '; '.join(sorted({r['domain'] for r in rows if r['access_result'] == 'KHONG_VAO_DUOC' and r['error_type'] == kind}))}
                      for kind, n in failures.most_common()]
            write_csv('loi_theo_loai.csv', errors, ['error_type', 'domain_count', 'url_count', 'domains'])
            (RUN_DIR / 'ket_qua.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            (RUN_DIR / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            md = ['# Các website còn lỗi sau lượt test bổ sung', '',
                  f"Thời điểm UTC: {summary['created_at']}. Run: `{RUN_DIR.name}`.", '',
                  f"Đã chạy {len(rows)-counts['CHUA_CHAY']}/{len(rows)} URL thuộc {len(domains)} hostname. "
                  f"HTTP 2xx: {counts['VAO_DUOC']}; không có HTTP 2xx: {counts['KHONG_VAO_DUOC']}; chưa chạy: {counts['CHUA_CHAY']}.", '',
                  f"{summary['page_not_attempted']} URL đã xử lý nhưng chưa request bài viết vì dừng trước bước tải bài. "
                  'Các trường hợp này được phân biệt với bài viết thực sự trả HTTP lỗi.', '',
                  f'HTTP User-Agent: `{USER_AGENT}`.', '',
                  'Giữ 1 mẫu cũ và lấy tối đa 4 URL mới mỗi hostname từ dataset, không trùng URL. '
                  'Gồm lỗi truy cập và lỗi nội dung/QC. Số URL dataset là số dòng của hostname, chưa loại URL trùng.', '',
                  'Ưu tiên theo số URL dataset giảm dần; không suy ra toàn bộ URL của domain đều bị lỗi. '
                  'Dừng ở robots là chưa request bài viết, không đồng nghĩa website không mở được trong trình duyệt.', '',
                  '| Ưu tiên | Hostname | Số URL dataset | Mẫu đã chạy | Lỗi truy cập | Lỗi nội dung | Loại lỗi |',
                  '|---:|---|---:|---:|---:|---:|---|']
            for item in priority:
                md.append(f"| {item['priority_rank']} | {item['domain']} | {item['dataset_url_count']:,} | {item['completed_urls']}/{item['selected_urls']} | {item['access_failures']} | {item['content_issues']} | {item['error_types']} |")
            md += ['', '## Domain đã phục hồi trong các mẫu', '']
            md += [f"- {r['domain']}: {r['accessible_urls']}/{r['selected_urls']} URL tải được và đạt QC." for r in domains if r['test_status'] == 'DA_PHUC_HOI'] or ['Chưa xác định domain phục hồi hoàn toàn.']
            md += ['', '## Domain thiếu URL bổ sung', '']
            md += [f"- {r['domain']}: lấy được {r['additional_urls']}/4 URL mới; dataset có {r['dataset_url_count']} dòng." for r in domains if r['missing_additional_urls']]
            md += ['', '## Chi tiết lỗi theo domain', '']
            for item in priority:
                md += [f"### {item['priority_rank']}. {item['domain']}", '',
                       f"{item['dataset_url_count']:,} URL nguồn; {item['page_not_attempted']} mẫu đã xử lý nhưng chưa request bài viết. "
                       f"Lỗi baseline: `{item['baseline_error_type']}`.", '']
                for row in rows:
                    if row['domain'] != item['domain'] or row['access_result'] == 'CHUA_CHAY' or (row['access_result'] == 'VAO_DUOC' and row['quality_status'] == 'accepted'):
                        continue
                    detail = (row['error_detail'] or row['quality_flags']).replace('\n', ' ').replace('`', "'")
                    md += [f"- ID {row['sample_id']} ({row['sample_role']}): [URL](<{row['sample_url']}>) — `{row['error_type']}`. "
                           f"HTTP trang: {row['http_status']}; HTTP robots: {row['robots_http_status']}. {row['reason']} Lỗi gốc: `{detail}`."]
                md.append('')
            (RUN_DIR / 'WEB_ERRORS.md').write_text('\n'.join(md), encoding='utf-8')

            visible_fields = ['domain', 'dataset_url_count', 'sample_id', 'sample_url', 'sample_role', 'access_result',
                              'http_status', 'robots_http_status', 'robots_attempt_count', 'robots_cache_hit', 'error_type', 'reason', 'error_detail',
                              'quality_status', 'quality_flags', 'char_count']
            labels = ['Domain', 'Số URL nguồn', 'ID mẫu', 'URL mẫu', 'Mẫu cũ/mới', 'Vào được?', 'HTTP trang',
                      'HTTP robots', 'Lần thử robots', 'Cache hit robots', 'Loại lỗi', 'Lý do', 'Lỗi gốc', 'QC', 'Cờ QC', 'Số ký tự']
            if PRIORITY_FIVE:
                visible_fields = ['domain', 'dataset_url_count', 'sample_id', 'sample_url', 'http_status',
                                  'error_type', 'error_detail', 'quality_status', 'char_count',
                                  'browser_status', 'browser_http_status', 'browser_quality_status', 'browser_char_count', 'browser_error']
                labels = ['Domain', 'Số URL nguồn', 'ID', 'URL', 'HTTP Requests', 'Lỗi Requests', 'Chi tiết',
                          'QC Requests', 'Ký tự Requests', 'Selenium', 'HTTP Selenium', 'QC Selenium', 'Ký tự Selenium', 'Lỗi Selenium']
            def esc(value):
                return html.escape(str(value if value is not None else ''), quote=True)
            body = []
            for row in rows:
                cells = []
                for field in visible_fields:
                    value = row[field]
                    text = (f'<a href="{esc(value)}" target="_blank" rel="noopener noreferrer">{esc(value)}</a>'
                            if field == 'sample_url' else esc(value))
                    cells.append('<td>' + text + '</td>')
                body.append(f'<tr data-access="{row["access_result"]}">' + ''.join(cells) + '</tr>')
            style = """<style>body{font:14px/1.5 system-ui,sans-serif;margin:20px;color:#172b4d}
            .table-wrap{overflow:auto;max-height:70vh;border:1px solid #ccd4df}table{border-collapse:collapse;width:100%}
            th,td{padding:9px;border-bottom:1px solid #dce2e9;text-align:left;vertical-align:top}th{background:#e8eef6;position:sticky;top:0}
            td{min-width:95px;max-width:330px;overflow-wrap:anywhere}td:nth-child(4),td:nth-child(9),td:nth-child(10){min-width:260px}
            input,select{padding:8px;margin:0 10px 14px 0}a{color:#1654a0}</style>"""
            table = '<div class="table-wrap"><table><thead><tr>' + ''.join('<th>' + esc(label) + '</th>' for label in labels)
            table += '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>'
            heading = f'<h1>Kết quả thử crawl {len(rows)} URL / {len(domains)} hostname</h1><p>Vào được: {counts["VAO_DUOC"]} · Không vào được: {counts["KHONG_VAO_DUOC"]} · Chưa chạy: {counts["CHUA_CHAY"]}</p>'
            heading += '<p>Vào được = HTTP trang cuối 2xx; QC là kết quả riêng. Dừng do robots là chính sách crawler. Kết quả chỉ áp dụng cho các URL mẫu.</p>'
            controls = '<input id="search" placeholder="Tìm domain, URL hoặc lỗi" aria-label="Tìm kiếm"><select id="access" aria-label="Kết quả"><option value="">Tất cả</option><option>VAO_DUOC</option><option>KHONG_VAO_DUOC</option><option>CHUA_CHAY</option></select><span id="count"></span>'
            priority_fields = ['priority_rank', 'domain', 'dataset_url_count', 'selected_urls', 'completed_urls', 'pending_urls', 'access_failures', 'content_issues', 'error_types']
            priority_labels = ['Ưu tiên', 'Domain', 'Số URL dataset', 'Mẫu', 'Đã chạy', 'Chưa chạy', 'Lỗi truy cập', 'Lỗi nội dung', 'Loại lỗi']
            priority_heading = '<h2>Domain còn lỗi — số URL dataset giảm dần</h2><p>Gồm lỗi truy cập và lỗi nội dung/QC. Số URL nguồn không phải số URL đã xác minh lỗi.</p>'
            priority_table = '<div class="table-wrap"><table id="priority"><thead><tr>' + ''.join('<th>'+esc(label)+'</th>' for label in priority_labels)
            priority_table += '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>'+esc(r[f])+'</td>' for f in priority_fields) + '</tr>' for r in priority) + '</tbody></table></div>'
            (RUN_DIR / 'uu_tien_fix_domain.html').write_text('<!doctype html><html lang="vi"><meta charset="utf-8"><title>Ưu tiên domain lỗi</title>'+style+priority_heading+priority_table+'</html>', encoding='utf-8')
            javascript = """<script>const rs=[...document.querySelectorAll('tbody tr')],s=document.getElementById('search'),a=document.getElementById('access');
            function filter(){let n=0;for(const r of rs){const ok=r.textContent.toLowerCase().includes(s.value.toLowerCase())&&(!a.value||r.dataset.access===a.value);r.hidden=!ok;n+=ok?1:0}document.getElementById('count').textContent=n+' hostname'}
            s.addEventListener('input',filter);a.addEventListener('change',filter);filter();</script>"""
            javascript = javascript.replace("document.querySelectorAll('tbody tr')", "document.querySelectorAll('tr[data-access]')").replace("n+' hostname'", "n+' URL'")
            (RUN_DIR / 'ket_qua.html').write_text('<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kết quả crawl domain</title>' + style + heading + priority_heading + priority_table + '<h2>Từng URL mẫu</h2>' + controls + table + javascript + '</html>', encoding='utf-8')
            # Archive outside the run directory to avoid including the archive itself.
            zip_path = Path(shutil.make_archive(str(RUN_DIR), 'zip', root_dir=RUN_DIR.parent, base_dir=RUN_DIR.name))
            if show:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                display(HTML(style + priority_heading + priority_table))
                display(HTML(style + heading + table))
                print('File kết quả:', RUN_DIR)
                print('ZIP:', zip_path)
            return rows, summary, zip_path

        # Create reports before networking, so partial runs have explicit CHUA_CHAY rows.
        rows, summary, zip_path = save_outputs(show=False)
        print('Đã chuẩn bị báo cáo và phân loại lỗi.')
    ''')
    add('markdown', '''
        ## 5. Crawl — chạy lại ô này để tiếp tục

        Tiến độ in mỗi 25 URL hoặc khi hết lượt. Cùng domain gốc được giới hạn
        tốc độ; robots.txt được kiểm tra trước mỗi origin. Lỗi của một URL không
        dừng các URL khác. Báo cáo và ZIP cập nhật khi ô kết thúc, kể cả khi có lỗi.
        Nếu dùng `MAX_NEW`, phần chưa chạy vẫn được ghi riêng, không tính là thất bại.

        Robots thử tối đa `ROBOTS_ATTEMPTS` lần khi timeout, lỗi kết nối hoặc HTTP
        408/429/5xx; chờ tăng dần và tôn trọng Retry-After. Timeout connect/read riêng
        và ngân sách retry nằm trong cấu hình. Lỗi tạm thời chỉ cache
        `ROBOTS_FAILURE_TTL` giây (hoặc lâu hơn nếu server yêu cầu chờ), sau đó
        URL kế tiếp có thể tải lại robots. Kết quả checkpoint cũ vẫn được bỏ qua;
        để so sánh bản sửa trên Kaggle/local, giữ `RESUME_RUN_DIR = None` và Run All.
        Ngân sách là giới hạn kiểm tra giữa các bước; DNS/socket có thể làm thời gian thực vượt mức đó.
    ''')
    add('code', '''
        import argparse
        import os
        import socket
        import time

        # DNS check is diagnostic only; failure here does not stop the crawl.
        network_path = RUN_DIR / 'network_check.json'
        if not network_path.exists():
            network = {
                'checked_at': datetime.now(timezone.utc).isoformat(),
                'environment': 'kaggle' if Path('/kaggle/working').is_dir() else 'colab' if Path('/content').is_dir() else 'local',
                'python': sys.version, 'platform': sys.platform,
                'proxy_environment_present': {key: bool(os.environ.get(key)) for key in
                                              ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')},
                'dns': [],
            }
            for domain in NETWORK_CHECK_DOMAINS:
                start = time.monotonic()
                entry = {'domain': domain}
                try:
                    entry['addresses'] = sorted({r[4][0] for r in socket.getaddrinfo(domain, 443)})
                except OSError as exc:
                    entry.update(exception_class=type(exc).__name__, error=str(exc))
                entry['elapsed_seconds'] = round(time.monotonic() - start, 3)
                network['dns'].append(entry)
            network_path.write_text(json.dumps(network, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Network check:', network_path)

        try:
            if PRIORITY_FIVE:
                records = priority_probe.crawl_requests(
                    crawler, RUN_DIR, SAMPLES, workers=min(WORKERS, 5), delay=DELAY,
                    attempts=PAGE_ATTEMPTS, user_agent=USER_AGENT,
                    timeout=(PAGE_CONNECT_TIMEOUT, PAGE_READ_TIMEOUT), budget=PAGE_REQUEST_BUDGET, max_new=MAX_NEW)
                browser_samples = priority_probe.select_browser_samples(SAMPLES, records, BROWSER_TEST_MODE)
                if browser_samples:
                    priority_probe.crawl_browser(crawler, RUN_DIR, browser_samples,
                                                user_agent=USER_AGENT, chrome_binary=CHROME_BINARY, delay=DELAY)
                crawler.report(argparse.Namespace(out=str(RUN_DIR)))
            else:
                crawler.locked_crawl(argparse.Namespace(
                    out=str(RUN_DIR), workers=WORKERS, delay=DELAY, attempts=ATTEMPTS, max_new=MAX_NEW,
                    robots_attempts=ROBOTS_ATTEMPTS, robots_connect_timeout=ROBOTS_CONNECT_TIMEOUT,
                    robots_read_timeout=ROBOTS_READ_TIMEOUT, robots_retry_budget=ROBOTS_RETRY_BUDGET,
                    robots_failure_ttl=ROBOTS_FAILURE_TTL,
                ))
        finally:
            rows, summary, zip_path = save_outputs()
    ''')
    add('markdown', '''
        ## 6. Xem lỗi riêng và tải output

        `khong_vao_duoc.csv` chứa domain, URL, loại lỗi, lý do tiếng Việt và lỗi gốc.
        `loi_theo_loai.csv` gom số hostname và số URL theo từng lỗi (HTTP 403, timeout,
        robots trả HTML, robots cấm crawl, DNS, SSL…). File JSON trong `records/`
        giữ trace request/redirect; `robots/` giữ bằng chứng robots.txt.
        `network_check.json` ghi DNS và môi trường của ba hostname timeout để đối chiếu
        Kaggle/local; `crawl_config.json` ghi timeout/retry và phiên bản package.
        `requests_vs_selenium.csv` và `browser_records/` giữ kết quả trình duyệt riêng;
        `browser_setup_error.json` được ghi nếu Chrome/driver không khởi động được.
        ZIP gồm kết quả, raw, ảnh chụp và snapshot để kiểm tra riêng.

        Kaggle: tải ZIP trong **Output**. Colab: ô dưới hiện nút tải ZIP.
        Jupyter local: dùng các liên kết file hoặc mở đường dẫn output được in ra.
    ''')
    add('code', '''
        # Có thể chạy lại ô này để xuất báo cáo từ checkpoint mà không crawl thêm.
        rows, summary, zip_path = save_outputs(show=False)
        failed_rows = [r for r in rows if r['access_result'] == 'KHONG_VAO_DUOC']
        print(f'Không vào được: {len(failed_rows)}/{len(rows)} URL, thuộc {len({r["domain"] for r in failed_rows})} hostname')
        for row in failed_rows:
            print(f"{row['domain']} | {row['error_type']} | {row['error_detail']}")
        print('\\nOutput:', RUN_DIR)
        for name in ['WEB_ERRORS.md', 'uu_tien_fix_domain.html', 'uu_tien_fix_domain.csv', 'tong_hop_domain.csv',
                     'requests_vs_selenium.csv',
                     'ket_qua.html', 'ket_qua.csv', 'vao_duoc.csv', 'khong_vao_duoc.csv',
                     'loi_theo_loai.csv', 'can_xem_noi_dung.csv', 'chua_chay.csv']:
            display(FileLink(str(RUN_DIR / name)))
        display(FileLink(str(zip_path)))

        if 'google.colab' in sys.modules:
            import ipywidgets as widgets
            from google.colab import files
            button = widgets.Button(description='Tải ZIP kết quả')
            button.on_click(lambda _: files.download(str(zip_path)))
            display(button)
    ''')
    if priority_five:
        for cell in cells:
            if cell['cell_type'] == 'markdown':
                cell['source'] = cell['source'].replace(
                    'Dùng snapshot crawler hiện tại trong repo: kiểm tra robots.txt, retry,',
                    'Dùng snapshot crawler và probe hiện tại: tải trực tiếp URL mẫu, retry,')
                cell['source'] = cell['source'].replace(
                    'HTTP User-Agent là chuỗi trình duyệt Mozilla/Chrome, có thể chỉnh ở ô cấu hình.',
                    'HTTP User-Agent là Mozilla/Chrome; Accept và Accept-Language được đặt theo trình duyệt.')
                if '## 5. Crawl' in cell['source']:
                    cell['source'] = '''## 5. Tải trang và đối chiếu Selenium

Chạy Requests trước, từng URL tuần tự trong một domain; các domain chạy song song.
Mỗi URL có timeout connect/read và ngân sách riêng, không tiêu hao ngân sách vì các mẫu cùng domain chờ nhau.
Ngân sách được kiểm tra giữa các bước; DNS và thử nhiều IP có thể làm thời gian thực vượt mức đặt.
Requests lỗi mới được thử Selenium theo `BROWSER_TEST_MODE`; có thể đặt `off` để chỉ chạy Requests.
Selenium Manager tìm/tải Chrome và driver. Nếu khởi động thất bại, lý do nằm trong `browser_setup_error.json`.
Requests và Selenium có kết quả riêng; DOM trống/challenge không được ghi thành tải được bài.
Để chạy lại toàn bộ bằng cấu hình mới, giữ `RESUME_RUN_DIR = None` và Run All.
'''
                cell['source'] = cell['source'].replace(
                    '`network_check.json` ghi DNS và môi trường của ba hostname timeout để đối chiếu\nKaggle/local; `crawl_config.json` ghi timeout/retry và phiên bản package.',
                    '`network_check.json` ghi DNS của 5 hostname để đối chiếu Kaggle/local;\n`priority_probe_config.json` ghi User-Agent/header, timeout và chế độ tải trang.')
    notebook = {'cells': cells, 'metadata': {
        'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python'},
        'kaggle': {'isInternetEnabled': True, 'accelerator': 'none'},
    }, 'nbformat': 4, 'nbformat_minor': 5}
    path = ROOT / 'notebooks/crawl_domain_samples.ipynb'
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'Created {path}: {len(cells)} cells, {len(samples)} samples')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-zip', type=Path)
    parser.add_argument('--failed-followup', action='store_true', help='Build the previous 227-URL failed-host cohort')
    args = parser.parse_args()
    if args.baseline_zip or args.failed_followup:
        build(select_followup(args.baseline_zip) if args.baseline_zip else None)
    else:
        priority_file = ROOT / 'data/domain_probe_priority_samples.json'
        build(json.loads(priority_file.read_text(encoding='utf-8')) if priority_file.exists() else None,
              priority_five=priority_file.exists())
