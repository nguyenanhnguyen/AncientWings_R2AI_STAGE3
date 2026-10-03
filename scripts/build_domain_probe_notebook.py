"""Build a standalone notebook for the fixed 97-host ViBioMIR sample."""
from pathlib import Path
import base64
import hashlib
import json
import pprint
import textwrap
import zlib

ROOT = Path(__file__).resolve().parents[1]


def build():
    run = ROOT / 'runs/domain_coverage_20261004'
    samples = [json.loads(line) for line in (run / 'sample.jsonl').read_text(encoding='utf-8').splitlines()]
    profile = json.loads((run / 'source_profile.json').read_text(encoding='utf-8'))
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    if len(samples) != 97 or len({r['domain'] for r in samples}) != 97:
        raise ValueError('Expected the original 97-domain sample.')
    raw = (ROOT / 'src/vibiomir/crawl/crawler.py').read_bytes()
    cells = []

    def add(kind, source, hidden=False):
        cell = {'cell_type': kind, 'id': f'domain-probe-{len(cells):02d}',
                'metadata': {'jupyter': {'source_hidden': True}} if hidden else {},
                'source': textwrap.dedent(source).strip() + '\n'}
        if kind == 'code':
            cell.update(execution_count=None, outputs=[])
            compile(cell['source'], cell['id'], 'exec')
        cells.append(cell)

    add('markdown', '''
        # Thử crawl 97 hostname trong ViBioMIR

        Chạy các ô từ trên xuống (**Run All**). Kaggle cần bật **Internet**; chỉ dùng CPU.
        Notebook tự chứa **đúng 97 URL mẫu đã chọn**, mỗi hostname 1 URL từ
        `links_corpus.parquet` (4.394.718 dòng; 97 hostname; 65 domain gốc; seed 42).
        Không cần clone repo, tải Parquet hay upload code Python.

        Dùng snapshot crawler hiện tại trong repo: kiểm tra robots.txt, retry,
        giới hạn tốc độ, tải HTML/PDF, trích xuất và kiểm tra chất lượng (QC).
        Kết quả sẽ khác theo thời điểm và môi trường mạng.

        - **VAO_DUOC**: URL cuối trả HTTP 2xx, kể cả khi trích xuất/QC thất bại.
        - **KHONG_VAO_DUOC**: đã chạy nhưng không lấy được HTTP 2xx của trang đích.
        - **CHUA_CHAY**: chưa có checkpoint, không tính là lỗi.

        `robots_http_status` là HTTP của robots.txt; `http_status` là HTTP của trang.
        Dừng do robots là kết quả của chính sách crawler, không chứng minh website
        không mở được bằng trình duyệt. Notebook chưa render JavaScript hay OCR.
        Một mẫu mỗi hostname chưa đại diện cho toàn bộ URL trên website.
    ''')
    add('markdown', '''
        ## 1. Cấu hình

        Mặc định chạy cả 97 URL. Có thể đặt `MAX_NEW = 10` để thử trước, rồi đổi
        thành `None` và chỉ chạy lại ô crawl để làm tiếp. Checkpoint đã có, kể cả
        lỗi, được bỏ qua. Muốn thử lại tất cả URL từ đầu, chạy lại ô cấu hình để
        tạo thư mục mới. `RESUME_RUN_DIR` dùng để tiếp tục thư mục output đã có.
    ''')
    add('code', '''
        WORKERS = 8
        DELAY = 1.0
        ATTEMPTS = 3
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
    ''')
    add('markdown', '''
        ## 2. Cài dependencies

        Cài các package crawler cần trong môi trường hiện tại. Phiên bản thực tế
        và log pip được lưu trong output. Khi resume, dùng phiên bản đã lưu.
    ''')
    add('code', '''
        import subprocess
        import importlib.metadata

        packages = ['pyarrow', 'requests', 'trafilatura', 'pymupdf', 'tld', 'ipython']
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
    add('markdown', '''
        ## 3. Danh sách mẫu và snapshot crawler

        97 mẫu giữ nguyên ID/URL nguồn. Ô code có thể mở để kiểm tra danh sách
        và snapshot. Crawler được kiểm tra SHA-256 trước khi import.
    ''')
    add('code',
        'SAMPLES = ' + pprint.pformat(samples, width=110, sort_dicts=False) + '\n\n'
        + 'SOURCE_PROFILE = ' + pprint.pformat(profile, width=110, sort_dicts=False) + '\n\n'
        + f"SOURCE_SHA256 = {manifest['source_sha256']!r}\n"
        + f"CRAWLER_SHA256 = {hashlib.sha256(raw).hexdigest()!r}\n"
        + f"CRAWLER_PAYLOAD = {base64.b85encode(zlib.compress(raw, 9)).decode('ascii')!r}\n\n"
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
            if len(SAMPLES) != 97 or len({r['domain'] for r in SAMPLES}) != 97:
                raise ValueError('Phải có đúng 1 mẫu cho mỗi hostname.')
            manifest_path = RUN_DIR / 'manifest.json'
            sample_path = RUN_DIR / 'sample.jsonl'
            crawler_path = RUN_DIR / 'crawler_snapshot.py'
            if manifest_path.exists():
                saved = json.loads(manifest_path.read_text(encoding='utf-8'))
                if (saved.get('probe_kind') != 'fixed_97_hostnames'
                        or saved.get('sample_sha256') != sha256(sample_bytes)
                        or saved.get('source_sha256') != SOURCE_SHA256):
                    raise ValueError('Run cũ không khớp 97 mẫu của notebook này.')
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
                    'probe_kind': 'fixed_97_hostnames', 'dataset': 'AIGuruTinix/ViBioMIR',
                    'source': 'embedded samples from data/links_corpus.parquet',
                    'source_sha256': SOURCE_SHA256, 'source_rows': SOURCE_PROFILE['rows'],
                    'sampling': 'equal_host_reservoir', 'seed': 42, 'selected': len(SAMPLES),
                    'sample_sha256': sha256(sample_bytes),
                }, ensure_ascii=False, indent=2), encoding='utf-8')

            spec = importlib.util.spec_from_file_location('domain_probe_crawler', crawler_path)
            crawler = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = crawler
            spec.loader.exec_module(crawler)
            print(f'Đã nạp {len(SAMPLES)} URL mẫu và crawler {crawler.VERSION}.')
        '''), hidden=True)
    add('markdown', '''
        ## 4. Chuẩn bị bảng kết quả và phân loại lỗi

        Output riêng: `vao_duoc.csv`, `khong_vao_duoc.csv`, `chua_chay.csv`,
        `loi_theo_loai.csv`, `can_xem_noi_dung.csv`; bảng tổng là `ket_qua.csv`.
        Các CSV dùng UTF-8 BOM để mở được tiếng Việt trong Excel.
        `error_detail` giữ nguyên lỗi kỹ thuật; `reason` diễn giải tiếng Việt.
        Mở `ket_qua.html` để lọc theo domain hoặc trạng thái.
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
            for sample in sorted(SAMPLES, key=lambda s: s['domain']):
                record_path = RUN_DIR / 'records' / f"{sample['id']}.json"
                record = json.loads(record_path.read_text(encoding='utf-8')) if record_path.exists() else {}
                if record and (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
                    raise ValueError('Checkpoint không khớp ID/URL nguồn.')
                status = record.get('status', 'pending')
                page_http = record.get('http_status')
                robots = record.get('robots', {})
                # Robots failure may happen before fetch() attaches its evidence to the record.
                if status.startswith('robots_'):
                    from urllib.parse import urlsplit
                    target = record.get('requests', [{}])[-1].get('url', sample['url']) if record.get('requests') else sample['url']
                    if record.get('redirects'):
                        target = record['redirects'][-1]['to']
                    p = urlsplit(target)
                    robot_file = RUN_DIR / 'robots' / (sha256(f'{p.scheme}://{p.netloc}'.encode()) + '.json')
                    if robot_file.exists():
                        robots = json.loads(robot_file.read_text(encoding='utf-8'))
                detail = record.get('error', '')
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
                    'crawl_status': status, 'failure_stage': stage, 'error_type': error_type,
                    'reason': reason, 'error_detail': detail, 'quality_status': record.get('quality_status', ''),
                    'quality_flags': '; '.join(flags), 'char_count': record.get('char_count'),
                    'title': record.get('title', ''), 'final_url': record.get('final_url', ''),
                    'elapsed_seconds': record.get('elapsed_seconds'),
                })
            return rows

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
            write_csv('ket_qua.csv', rows, fields)
            for value, filename in [('VAO_DUOC', 'vao_duoc.csv'), ('KHONG_VAO_DUOC', 'khong_vao_duoc.csv'), ('CHUA_CHAY', 'chua_chay.csv')]:
                write_csv(filename, [r for r in rows if r['access_result'] == value], fields)
            write_csv('can_xem_noi_dung.csv', [r for r in rows if r['access_result'] == 'VAO_DUOC' and r['quality_status'] != 'accepted'], fields)
            failures = Counter(r['error_type'] for r in rows if r['access_result'] == 'KHONG_VAO_DUOC')
            errors = [{'error_type': kind, 'domain_count': n,
                       'domains': '; '.join(r['domain'] for r in rows if r['access_result'] == 'KHONG_VAO_DUOC' and r['error_type'] == kind)}
                      for kind, n in failures.most_common()]
            write_csv('loi_theo_loai.csv', errors, ['error_type', 'domain_count', 'domains'])
            (RUN_DIR / 'ket_qua.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            (RUN_DIR / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

            visible_fields = ['domain', 'dataset_url_count', 'sample_id', 'sample_url', 'access_result',
                              'http_status', 'robots_http_status', 'error_type', 'reason', 'error_detail',
                              'quality_status', 'quality_flags', 'char_count']
            labels = ['Domain', 'Số URL nguồn', 'ID mẫu', 'URL mẫu', 'Vào được?', 'HTTP trang',
                      'HTTP robots', 'Loại lỗi', 'Lý do', 'Lỗi gốc', 'QC', 'Cờ QC', 'Số ký tự']
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
            heading = f'<h1>Kết quả thử crawl {len(rows)} hostname</h1><p>Vào được: {counts["VAO_DUOC"]} · Không vào được: {counts["KHONG_VAO_DUOC"]} · Chưa chạy: {counts["CHUA_CHAY"]}</p>'
            heading += '<p>Vào được = HTTP trang cuối 2xx; QC là kết quả riêng. Dừng do robots là chính sách crawler. Kết quả chỉ áp dụng cho các URL mẫu.</p>'
            controls = '<input id="search" placeholder="Tìm domain, URL hoặc lỗi" aria-label="Tìm kiếm"><select id="access" aria-label="Kết quả"><option value="">Tất cả</option><option>VAO_DUOC</option><option>KHONG_VAO_DUOC</option><option>CHUA_CHAY</option></select><span id="count"></span>'
            javascript = """<script>const rs=[...document.querySelectorAll('tbody tr')],s=document.getElementById('search'),a=document.getElementById('access');
            function filter(){let n=0;for(const r of rs){const ok=r.textContent.toLowerCase().includes(s.value.toLowerCase())&&(!a.value||r.dataset.access===a.value);r.hidden=!ok;n+=ok?1:0}document.getElementById('count').textContent=n+' hostname'}
            s.addEventListener('input',filter);a.addEventListener('change',filter);filter();</script>"""
            (RUN_DIR / 'ket_qua.html').write_text('<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kết quả crawl domain</title>' + style + heading + controls + table + javascript + '</html>', encoding='utf-8')
            # Archive outside the run directory to avoid including the archive itself.
            zip_path = Path(shutil.make_archive(str(RUN_DIR), 'zip', root_dir=RUN_DIR.parent, base_dir=RUN_DIR.name))
            if show:
                print(json.dumps(summary, ensure_ascii=False, indent=2))
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
    ''')
    add('code', '''
        import argparse

        try:
            crawler.locked_crawl(argparse.Namespace(
                out=str(RUN_DIR), workers=WORKERS, delay=DELAY, attempts=ATTEMPTS, max_new=MAX_NEW,
            ))
        finally:
            rows, summary, zip_path = save_outputs()
    ''')
    add('markdown', '''
        ## 6. Xem lỗi riêng và tải output

        `khong_vao_duoc.csv` chứa domain, URL, loại lỗi, lý do tiếng Việt và lỗi gốc.
        `loi_theo_loai.csv` gom số hostname theo từng lỗi (HTTP 403, timeout,
        robots trả HTML, robots cấm crawl, DNS, SSL…). File JSON trong `records/`
        giữ trace request/redirect; `robots/` giữ bằng chứng robots.txt.
        ZIP gồm toàn bộ kết quả, raw và snapshot để kiểm tra riêng.

        Kaggle: tải ZIP trong **Output**. Colab: ô dưới hiện nút tải ZIP.
        Jupyter local: dùng các liên kết file hoặc mở đường dẫn output được in ra.
    ''')
    add('code', '''
        # Có thể chạy lại ô này để xuất báo cáo từ checkpoint mà không crawl thêm.
        rows, summary, zip_path = save_outputs(show=False)
        failed_rows = [r for r in rows if r['access_result'] == 'KHONG_VAO_DUOC']
        print(f'Không vào được: {len(failed_rows)}/{len(rows)} hostname')
        for row in failed_rows:
            print(f"{row['domain']} | {row['error_type']} | {row['error_detail']}")
        print('\\nOutput:', RUN_DIR)
        for name in ['ket_qua.html', 'ket_qua.csv', 'vao_duoc.csv', 'khong_vao_duoc.csv',
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
    notebook = {'cells': cells, 'metadata': {
        'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
        'language_info': {'name': 'python'},
        'kaggle': {'isInternetEnabled': True, 'accelerator': 'none'},
    }, 'nbformat': 4, 'nbformat_minor': 5}
    path = ROOT / 'notebooks/crawl_domain_samples.ipynb'
    path.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'Created {path}: {len(cells)} cells, {len(samples)} samples')


if __name__ == '__main__':
    build()
