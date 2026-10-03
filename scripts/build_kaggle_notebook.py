"""Build a standalone Kaggle notebook from the current crawl implementation."""
from pathlib import Path
import base64
import hashlib
import json
import pprint
import textwrap
import zlib


ROOT = Path(__file__).resolve().parents[1]


def build():
    cells = []

    def add(kind, source, hidden=False, step=None):
        source = textwrap.dedent(source).strip() + '\n'
        if kind == 'code' and step:
            source = f'with diagnostic_step({step!r}):\n' + textwrap.indent(source, '    ')
        cell = {
            'cell_type': kind,
            'id': f'crawl-{len(cells):02d}',
            'metadata': {'jupyter': {'source_hidden': True}} if hidden else {},
            'source': source,
        }
        if kind == 'code':
            cell.update(execution_count=None, outputs=[])
        cells.append(cell)

    add('markdown', '''
        # Crawl corpus ViBioMIR trên Kaggle

        Notebook tự chứa code crawl, không cần clone repo hoặc upload file Python.
        Phần chẩn đoán đã tích hợp: Output tự tạo `<run>_diagnostics.zip` để debug.
        Bật **Internet** trong cài đặt notebook; dùng CPU, không cần GPU.
        Chỉnh ô **1. Cấu hình**, rồi chạy các ô theo thứ tự.

        ID bắt đầu và kết thúc đều được tính vào khoảng chọn. Đây là **ID gốc**,
        không phải số thứ tự dòng. Giữ nguyên ID/URL nguồn, không dịch hoặc sinh lại text.
        Trích HTML/PDF có text; chưa có OCR hoặc browser render JavaScript.
        Tài liệu nguồn: [ViBioMIR](https://huggingface.co/datasets/AIGuruTinix/ViBioMIR).
    ''')
    add('markdown', '''
        ## 1. Cấu hình — chỉnh ID tại đây

        Mặc định chọn ID **583–1582**. Để thử trước, đặt `MAX_NEW = 10`;
        sau đó đổi thành `None` và chạy lại ô crawl để làm tiếp.
        Giữ nguyên `DELAY`, `ATTEMPTS` và phiên bản code khi resume cùng run.
        Với khoảng lớn, chia thành nhiều run nhỏ: crawler hiện tại nạp danh sách công việc vào RAM.

        `SOURCE_PARQUET` để trống sẽ tải nguồn đã chốt từ Hugging Face.
        Nếu đã thêm Parquet vào Kaggle Input, điền đường dẫn `/kaggle/input/.../links_corpus.parquet`.
        `RESUME_RUN_PATH` tùy chọn trỏ tới **thư mục run đã giải nén** từ notebook này trong Kaggle Input.
    ''')
    add('code', '''
        # ===== CHỈNH CẤU HÌNH TẠI ĐÂY =====
        ID_FROM = 583
        ID_TO = 1582              # Bao gồm ID này
        WORKERS = 4
        DELAY = 1.0
        ATTEMPTS = 3
        MAX_NEW = None            # None: toàn bộ còn lại; 10: thêm tối đa 10 URL

        SOURCE_PARQUET = None     # None: tự tải; hoặc '/kaggle/input/.../links_corpus.parquet'
        RESUME_RUN_PATH = None    # None: mới/tiếp tục session; hoặc thư mục run trong Kaggle Input
        RUN_TAG = None            # None: tự đặt ids_<ID_FROM>_<ID_TO>; đổi khi muốn run mới

        from pathlib import Path
        import json
        import shutil
        import sys

        if sys.version_info < (3, 11):
            raise RuntimeError('Code crawl yêu cầu Python 3.11 trở lên.')
        WORKDIR = Path('/kaggle/working')
        DATASET_REVISION = '0148f6f80ffafed5c005af6d506ccfd9d3fb47a7'
        SOURCE_SHA256 = 'dee1153f5b9d9010dea18e1b7724b4915ff847b711d036bec8b933486802a971'
        SOURCE_URL = f'https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/resolve/{DATASET_REVISION}/links_corpus.parquet'

        if type(ID_FROM) is not int or type(ID_TO) is not int or ID_FROM < 0 or ID_TO < ID_FROM:
            raise ValueError('ID_FROM và ID_TO phải là số nguyên; ID_TO >= ID_FROM >= 0.')
        if type(WORKERS) is not int or WORKERS < 1 or type(ATTEMPTS) is not int or ATTEMPTS < 1:
            raise ValueError('WORKERS và ATTEMPTS phải là số nguyên dương.')
        if not isinstance(DELAY, (int, float)) or not 0 <= DELAY < float('inf'):
            raise ValueError('DELAY phải hữu hạn và không âm.')
        if MAX_NEW is not None and (type(MAX_NEW) is not int or MAX_NEW < 1):
            raise ValueError('MAX_NEW phải là None hoặc số nguyên dương.')
        tag = RUN_TAG or f'ids_{ID_FROM}_{ID_TO}'
        if not isinstance(tag, str) or tag in ('.', '..') or any(separator in tag for separator in ('/', chr(92))):
            raise ValueError('RUN_TAG chỉ là tên thư mục, không phải đường dẫn.')
        RUN_DIR = WORKDIR / 'runs' / tag
        SOURCE_PATH = WORKDIR / 'data' / 'links_corpus.parquet'
        RUN_DIR.parent.mkdir(parents=True, exist_ok=True)
        if RESUME_RUN_PATH:
            previous = Path(RESUME_RUN_PATH)
            if not (previous / 'manifest.json').is_file():
                raise ValueError('RESUME_RUN_PATH phải chứa manifest.json, records/ và raw/.')
            if not RUN_DIR.exists():
                shutil.copytree(previous, RUN_DIR)
            else:
                print('Đã có output trong session; dùng run hiện tại, không copy đè.')
        if (RUN_DIR / 'manifest.json').exists():
            saved = json.loads((RUN_DIR / 'manifest.json').read_text(encoding='utf-8'))
            if saved.get('id_start_inclusive') != ID_FROM or saved.get('id_stop_exclusive') != ID_TO + 1:
                raise ValueError('Khoảng ID không khớp run đã có. Chọn RUN_TAG mới.')
        print(f'ID: {ID_FROM} đến {ID_TO}, bao gồm cả hai đầu')
        print(f'Output: {RUN_DIR}')
    ''')
    add('markdown', '''
        ## 2. Cài dependencies

        Lượt mới dùng phiên bản tương thích mà pip chọn trong môi trường Kaggle,
        không ép bản lock Windows của repo. Phiên bản thực tế được lưu cùng run.
        Khi khôi phục run, notebook cài lại dependencies trực tiếp đã ghi nhận.
    ''')
    add('code', '''
        import subprocess
        import importlib.metadata

        package_names = ['pyarrow', 'requests', 'trafilatura', 'pymupdf', 'tld']
        requirements_path = RUN_DIR / 'notebook_requirements.txt'
        if requirements_path.exists():
            install_args = ['-r', str(requirements_path)]
        else:
            install_args = package_names
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / 'logs').mkdir(exist_ok=True)
        installation = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--quiet', *install_args],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
        )
        with (RUN_DIR / 'logs' / 'pip_install.log').open('a', encoding='utf-8') as log:
            log.write(installation.stdout or '')
        if installation.stdout:
            print(installation.stdout)
        if installation.returncode:
            raise subprocess.CalledProcessError(installation.returncode, installation.args, output=installation.stdout)
        versions = {name: importlib.metadata.version(name) for name in package_names}
        print(json.dumps(versions, indent=2))
    ''')
    add('markdown', '''
        ## 3. Chuẩn bị code crawl

        Ô dưới giải nén snapshot của code trong repo vào output; không tải code từ mạng.
        Các file `.py` sinh ra có thể mở để xem. Snapshot có sẵn của run được giữ nguyên khi resume.
        Muốn cập nhật snapshot sau khi sửa code repo, chạy `scripts/build_kaggle_notebook.py` để dựng lại notebook.
    ''')
    embedded = {}
    hashes = {}
    for name, module in [('crawler_snapshot.py', 'crawler.py'),
                         ('audit_snapshot.py', 'audit.py'),
                         ('export_snapshot.py', 'export.py'),
                         ('diagnostics_snapshot.py', 'diagnostics.py')]:
        raw = (ROOT / 'src/vibiomir/crawl' / module).read_bytes()
        embedded[name] = base64.b85encode(zlib.compress(raw, level=9)).decode('ascii')
        hashes[name] = hashlib.sha256(raw).hexdigest()
    add('code', 'import base64\nimport hashlib\nimport zlib\n\n'
        + 'EMBEDDED_FILES = ' + pprint.pformat(embedded, width=100) + '\n'
        + 'EMBEDDED_SHA256 = ' + pprint.pformat(hashes, width=100) + '\n\n'
        + textwrap.dedent('''
            RUN_DIR.mkdir(parents=True, exist_ok=True)
            for name, encoded in EMBEDDED_FILES.items():
                target = RUN_DIR / name
                if not target.exists():
                    body = zlib.decompress(base64.b85decode(encoded))
                    if hashlib.sha256(body).hexdigest() != EMBEDDED_SHA256[name]:
                        raise ValueError(f'Snapshot bị hỏng: {name}')
                    target.write_bytes(body)
            CRAWLER = RUN_DIR / 'crawler_snapshot.py'
            AUDITOR = RUN_DIR / 'audit_snapshot.py'
            EXPORTER = RUN_DIR / 'export_snapshot.py'
            # Diagnostics chỉ đọc output, có thể cập nhật riêng mà không đổi crawler/hash resume.
            diagnostic_body = zlib.decompress(base64.b85decode(EMBEDDED_FILES['diagnostics_snapshot.py']))
            if hashlib.sha256(diagnostic_body).hexdigest() != EMBEDDED_SHA256['diagnostics_snapshot.py']:
                raise ValueError('Snapshot diagnostics bị hỏng.')
            DIAGNOSTICS = RUN_DIR / 'diagnostics_snapshot.py'
            DIAGNOSTICS.write_bytes(diagnostic_body)
            diagnostics_archive = WORKDIR / f'{RUN_DIR.name}_diagnostics.zip'
            from contextlib import contextmanager
            import traceback
            LOG_DIR = RUN_DIR / 'logs'
            LOG_DIR.mkdir(exist_ok=True)

            def refresh_diagnostics(strict=False):
                try:
                    result = subprocess.run(
                        [sys.executable, '-u', str(DIAGNOSTICS), '--out', str(RUN_DIR), '--archive', str(diagnostics_archive)],
                        check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding='utf-8', errors='replace',
                    )
                    with (LOG_DIR / 'diagnostics.log').open('a', encoding='utf-8') as stream:
                        stream.write(result.stdout)
                except (OSError, subprocess.CalledProcessError) as exc:
                    with (LOG_DIR / 'diagnostics.log').open('a', encoding='utf-8') as stream:
                        stream.write(str(exc) + '\\n' + str(getattr(exc, 'output', '') or '') + '\\n')
                    if strict:
                        raise
                    print(f'Tạo ZIP chẩn đoán thất bại: {exc}', flush=True)

            @contextmanager
            def diagnostic_step(name):
                try:
                    yield
                except BaseException:
                    with (LOG_DIR / 'notebook_errors.log').open('a', encoding='utf-8') as stream:
                        stream.write(f'Bước: {name}\\n' + traceback.format_exc() + '\\n')
                    raise
                finally:
                    refresh_diagnostics()
            if (RUN_DIR / 'crawl_config.json').exists():
                saved_config = json.loads((RUN_DIR / 'crawl_config.json').read_text(encoding='utf-8'))
                if hashlib.sha256(CRAWLER.read_bytes()).hexdigest() != saved_config['script_sha256']:
                    raise ValueError('Snapshot không khớp hash của run cũ; không được ép resume.')
            if not requirements_path.exists():
                requirements_path.write_text(''.join(f'{k}=={v}\\n' for k, v in versions.items()), encoding='utf-8')
            print('Đã chuẩn bị snapshot và ghi phiên bản dependencies.')
            refresh_diagnostics()
        '''), hidden=True)
    add('markdown', '''
        ## 4. Tải hoặc đọc danh sách URL

        Nguồn được cố định theo revision và kiểm tra SHA-256. Chỉ đọc corpus URL;
        không dùng query làm nội dung hay nhãn. File Input có thể ở vị trí khác nhưng
        được copy vào đường dẫn ổn định trong `/kaggle/working` để dùng lại khi resume.
    ''')
    add('code', '''
        import requests

        def sha256_file(path):
            digest = hashlib.sha256()
            with Path(path).open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(block)
            return digest.hexdigest()

        SOURCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SOURCE_PARQUET:
            supplied = Path(SOURCE_PARQUET)
            if not supplied.is_file():
                raise FileNotFoundError(supplied)
            if supplied.resolve() != SOURCE_PATH.resolve():
                shutil.copyfile(supplied, SOURCE_PATH)
        elif not SOURCE_PATH.exists():
            temporary = SOURCE_PATH.with_suffix('.download')
            try:
                with requests.get(SOURCE_URL, stream=True, timeout=(15, 90)) as response:
                    response.raise_for_status()
                    with temporary.open('wb') as stream:
                        for block in response.iter_content(1024 * 1024):
                            if block:
                                stream.write(block)
                if sha256_file(temporary) != SOURCE_SHA256:
                    raise ValueError('Hash file tải về không khớp nguồn đã chốt.')
                temporary.replace(SOURCE_PATH)
            finally:
                temporary.unlink(missing_ok=True)
        if sha256_file(SOURCE_PATH) != SOURCE_SHA256:
            raise ValueError('Parquet không khớp nguồn đã chốt. Kiểm tra file Input.')
        print(f'Nguồn hợp lệ: {SOURCE_PATH} ({SOURCE_PATH.stat().st_size:,} byte)')
    ''', step='source')
    add('markdown', '''
        ## 5. Chọn ID và tạo manifest

        Nếu khoảng chọn có ID không tồn tại trong nguồn, notebook báo số lượng thiếu,
        rồi lấy đúng các hàng thực sự có trong khoảng; không tạo ID hoặc URL thay thế.
        Bước chuẩn bị hiện quét toàn file để kiểm tra nguồn và thống kê hostname, nên có thể mất một lúc.
    ''')
    add('code', '''
        import pyarrow.parquet as pq
        from collections import Counter
        from urllib.parse import urlsplit
        from IPython.display import display
        from datetime import datetime, timezone
        import time
        import uuid

        selected = pq.read_table(SOURCE_PATH, filters=[('id', '>=', ID_FROM), ('id', '<=', ID_TO)]).to_pylist()
        selected.sort(key=lambda row: row['id'])
        if not selected:
            raise ValueError('Không có URL nào trong khoảng ID đã chọn.')
        if len({row['id'] for row in selected}) != len(selected):
            raise ValueError('Nguồn có ID trùng trong khoảng chọn.')
        missing_count = ID_TO - ID_FROM + 1 - len(selected)
        print(f'Chọn {len(selected):,} URL; có {missing_count:,} ID không tồn tại trong khoảng.')
        print('Phân bố hostname:', dict(Counter(urlsplit(row['url']).hostname for row in selected)))
        display(selected[:5])

        LOG_DIR = RUN_DIR / 'logs'
        LOG_DIR.mkdir(exist_ok=True)

        def log_event(name, event):
            with (LOG_DIR / name).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\\n')

        def run_script(script, *arguments):
            # Output hiển thị trực tiếp để theo dõi tiến độ; không dùng shell.
            invocation_id = uuid.uuid4().hex
            started = time.monotonic()
            operation = str(arguments[0]) if script == CRAWLER else Path(script).stem
            log_event('invocations.jsonl', {
                'event': 'start', 'invocation_id': invocation_id, 'operation': operation,
                'at': datetime.now(timezone.utc).isoformat(), 'arguments': list(map(str, arguments)),
            })
            process = subprocess.Popen(
                [sys.executable, '-u', str(script), *map(str, arguments)],
                cwd=str(WORKDIR), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
            )
            returncode = None
            try:
                with (LOG_DIR / (Path(script).stem + '.log')).open('a', encoding='utf-8') as log:
                    for line in process.stdout:
                        print(line, end='', flush=True)
                        log.write(line)
                        log.flush()
                        if operation == 'crawl':
                            try:
                                progress = json.loads(line)
                            except ValueError:
                                progress = {}
                            if isinstance(progress, dict) and 'completed_this_invocation' in progress:
                                log_event('progress.jsonl', {
                                    **progress, 'invocation_id': invocation_id,
                                    'at': datetime.now(timezone.utc).isoformat(),
                                    'elapsed_seconds': time.monotonic() - started,
                                })
                                refresh_diagnostics()
                returncode = process.wait()
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
            finally:
                process.stdout.close()
                log_event('invocations.jsonl', {
                    'event': 'end', 'invocation_id': invocation_id, 'operation': operation,
                    'at': datetime.now(timezone.utc).isoformat(),
                    'elapsed_seconds': time.monotonic() - started,
                    'returncode': process.returncode,
                })
                refresh_diagnostics()
            if returncode:
                raise subprocess.CalledProcessError(returncode, process.args)

        manifest_path = RUN_DIR / 'manifest.json'
        if not manifest_path.exists():
            run_script(CRAWLER, 'prepare', '--source', SOURCE_PATH, '--out', RUN_DIR,
                       '--size', len(selected), '--id-start', ID_FROM, '--id-stop', ID_TO + 1)
        else:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if manifest['source_sha256'] != SOURCE_SHA256 or manifest['selected'] != len(selected):
                raise ValueError('Manifest không khớp nguồn hoặc số URL đã chọn.')
            if Path(manifest['source']).resolve() != SOURCE_PATH.resolve():
                raise ValueError('Đường dẫn nguồn của run cũ khác notebook này; dùng run mới.')
            sample_bytes = (RUN_DIR / 'sample.jsonl').read_bytes()
            if hashlib.sha256(sample_bytes).hexdigest() != manifest['sample_sha256']:
                raise ValueError('Hash sample của run cũ đã thay đổi.')
            with (RUN_DIR / 'sample.jsonl').open(encoding='utf-8') as stream:
                sample = [json.loads(line) for line in stream if line.strip()]
            if {r['id']: r['url'] for r in sample} != {r['id']: r['url'] for r in selected} or len(sample) != len(selected):
                raise ValueError('ID/URL của run cũ không khớp khoảng chọn.')
            print('Manifest hợp lệ; giữ checkpoint để resume.')
    ''', step='prepare')
    add('markdown', '''
        ## 6. Crawl — chạy lại ô này để tiếp tục

        Tiến độ in mỗi 25 URL hoàn tất hoặc khi hết lượt. Crawler tuân thủ robots,
        giới hạn một request cùng registered domain, có retry và checkpoint theo ID.
        `WORKERS = 4` không có nghĩa bốn request đồng thời đến cùng website.
        ID đã có checkpoint, kể cả thất bại, sẽ được bỏ qua khi resume.
        ZIP `<run>_diagnostics.zip` được cập nhật sau mỗi log tiến độ và khi lệnh kết thúc,
        kể cả ngắt ô crawl. File có một số mẫu record/raw để debug, không nén lại toàn bộ raw.
    ''')
    add('code', '''
        arguments = ['crawl', '--out', RUN_DIR, '--workers', WORKERS,
                     '--delay', DELAY, '--attempts', ATTEMPTS]
        if MAX_NEW is not None:
            arguments += ['--max-new', MAX_NEW]
        print('ZIP chẩn đoán tự cập nhật:', diagnostics_archive)
        run_script(CRAWLER, *arguments)
    ''', step='crawl')
    add('markdown', '''
        ## 7. Báo cáo, kiểm tra và xuất corpus

        Corpus accepted chỉ gồm tài liệu qua heuristic; chưa chứng minh chất lượng bằng chấm thủ công.
        Audit chỉ chạy khi đủ checkpoint. Nếu đang crawl thử, vẫn xuất phần accepted hiện có;
        manifest notebook ghi rõ đây là corpus chưa hoàn tất.
    ''')
    add('code', '''
        run_script(CRAWLER, 'report', '--out', RUN_DIR)
        summary = json.loads((RUN_DIR / 'quality_report.json').read_text(encoding='utf-8'))
        display({k: summary[k] for k in ['selected', 'completed', 'pending', 'accepted', 'review', 'rejected', 'status_counts']})
        if summary['pending'] == 0:
            run_script(AUDITOR, '--out', RUN_DIR)
        else:
            print('Run chưa hoàn tất; bỏ qua audit toàn mẫu. Chạy lại ô crawl để tiếp tục.')
        if summary['accepted'] > 0:
            run_script(EXPORTER, '--out', RUN_DIR)
            corpus = pq.read_table(RUN_DIR / 'corpus.parquet')
            print(corpus.schema)
            display(corpus.select(['id', 'url', 'title']).slice(0, 5).to_pylist())
        else:
            print('Chưa có tài liệu accepted; xem quarantine.jsonl và QUALITY_REPORT.md.')
    ''', step='report_audit_export')
    add('markdown', '''
        ## 8. ZIP chẩn đoán — tích hợp trong Output

        Chạy ô này để tạo lại gói debug từ checkpoint hiện có, kể cả khi crawl chưa xong.
        Không cần file Python riêng, không tải lại URL. ZIP chứa:
        - `overview.html`, `summary.json`: tiến độ, tốc độ/ETA, trạng thái HTTP và QC.
        - CSV từng ID, lỗi/pending, request/retry và redirect.
        - Log pip/crawl, traceback notebook, manifest/cấu hình và phiên bản môi trường.
        - Snapshot code, bằng chứng robots và tối đa 10 mẫu record/raw để kiểm tra parser.

        Raw mẫu có ngân sách 10 MiB; các mẫu bị bỏ qua được ghi trong `sample_manifest.json`.
        Giải nén ZIP và mở `overview.html`. Có thể gửi nguyên ZIP này để chẩn đoán lỗi.
    ''')
    add('code', '''
        from IPython.display import FileLink
        import zipfile

        refresh_diagnostics(strict=True)
        with zipfile.ZipFile(diagnostics_archive) as diagnostic_bundle:
            diagnostic_summary = json.loads(diagnostic_bundle.read('summary.json'))
        display({key: diagnostic_summary[key] for key in ['selected', 'completed', 'pending', 'quality_status_counts', 'timing']})
        print('ZIP chẩn đoán trong Output:', diagnostics_archive)
        display(FileLink(str(diagnostics_archive.relative_to(WORKDIR))))
    ''')
    add('markdown', '''
        ## 9. Đóng gói corpus đầy đủ để tải về

        ZIP chứa cả raw, records, snapshot code và corpus để truy vết/resume; có thể khá lớn.
        ZIP riêng `<run>_diagnostics.zip` nhỏ hơn: giải nén và mở `overview.html` để xem
        tiến độ, tốc độ/ETA, HTTP status, lỗi và cờ chất lượng. Có CSV từng ID và log cài dependencies.
        Tải file trong Output hoặc qua link bên dưới. Khi đổi session, cần giữ output hoặc
        thêm run đã giải nén làm Kaggle Input và đặt `RESUME_RUN_PATH` trước khi chạy lại.
        Resume không tự thử lại ID lỗi đã có checkpoint.
    ''')
    add('code', '''
        from IPython.display import FileLink

        notebook_manifest = {
            'id_from_inclusive': ID_FROM, 'id_to_inclusive': ID_TO,
            'dataset_revision': DATASET_REVISION, 'source_sha256': SOURCE_SHA256,
            'selected': summary['selected'], 'completed': summary['completed'],
            'pending': summary['pending'], 'accepted': summary['accepted'],
            'complete': summary['pending'] == 0,
            'packages': versions,
            'exported_files': [name for name in ['corpus.parquet', 'corpus.jsonl'] if (RUN_DIR / name).exists()],
        }
        (RUN_DIR / 'notebook_manifest.json').write_text(json.dumps(notebook_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        refresh_diagnostics(strict=True)
        archive = shutil.make_archive(str(WORKDIR / RUN_DIR.name), 'zip', root_dir=RUN_DIR.parent, base_dir=RUN_DIR.name)
        print('ZIP:', archive)
        print('Corpus:', RUN_DIR / 'corpus.parquet')
        display(FileLink(str(Path(archive).relative_to(WORKDIR))))
        print('ZIP chẩn đoán:', diagnostics_archive)
        display(FileLink(str(diagnostics_archive.relative_to(WORKDIR))))
        if (RUN_DIR / 'corpus.parquet').exists():
            display(FileLink(str((RUN_DIR / 'corpus.parquet').relative_to(WORKDIR))))
            display(FileLink(str((RUN_DIR / 'corpus.jsonl').relative_to(WORKDIR))))
    ''')
    notebook = {
        'cells': cells,
        'metadata': {
            'kernelspec': {'display_name': 'Python 3', 'language': 'python', 'name': 'python3'},
            'language_info': {'name': 'python'},
        },
        'nbformat': 4,
        'nbformat_minor': 5,
    }
    output = ROOT / 'notebooks/crawl_corpus_kaggle.ipynb'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    build()
