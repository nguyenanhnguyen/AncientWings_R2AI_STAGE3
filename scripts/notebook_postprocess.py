"""Offline audit/export and rescue packaging, embedded in the HF upload crawl notebook."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

_storage_path = Path(__file__).with_name('storage_snapshot.py')
if not _storage_path.exists(): _storage_path = Path(__file__).with_name('corpus_storage.py')
_storage_spec = importlib.util.spec_from_file_location('postprocess_storage', _storage_path)
STORAGE = importlib.util.module_from_spec(_storage_spec)
_storage_spec.loader.exec_module(STORAGE)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def records_hash(out):
    digest = hashlib.sha256()
    for path in sorted((Path(out) / 'records').glob('*.json')):
        digest.update(path.name.encode('utf-8') + b'\0')
        digest.update(bytes.fromhex(file_hash(path)))
    return digest.hexdigest()


def verify_audit(out, counts):
    audit = read_json(Path(out) / 'audit_summary.json')
    if (audit.get('source_mapping_verified') is not True
            or audit.get('raw_and_text_hashes_verified') is not True
            or audit.get('selected') != counts['selected']
            or audit.get('completed') != counts['selected']):
        raise RuntimeError('Audit chưa xác minh đủ ID/URL và hash raw/text.')


def verify_export(out, counts):
    if counts['accepted'] == 0:
        return
    out = Path(out)
    exported = read_json(out / 'export_manifest.json')
    if (exported.get('documents') != counts['accepted']
            or any(exported.get(key) is not True for key in (
                'accepted_source_ids_preserved', 'parquet_round_trip_verified'))
            or ('corpus.jsonl' in exported.get('files', {}) and exported.get('jsonl_round_trip_verified') is not True)):
        raise RuntimeError('Export chưa xác minh đủ bản ghi accepted và round-trip.')
    for name in ('corpus.parquet', 'corpus.jsonl'):
        if name == 'corpus.jsonl' and name not in exported.get('files', {}):
            continue
        proof = exported.get('files', {}).get(name, {})
        target = out / name
        if (not target.is_file() or target.stat().st_size != proof.get('bytes')
                or file_hash(target) != proof.get('sha256')):
            raise RuntimeError(f'Hash/size corpus không khớp export: {name}')


def require_ready(out, manifest=None):
    """Reject legacy, failed or stale completion markers before obtaining credentials."""
    out = Path(out)
    try:
        state = read_json(out / 'postprocess_status.json')
        if not isinstance(state, dict):
            raise RuntimeError('Bằng chứng audit/export không hợp lệ; chạy lại mục 7–9.')
        if (state.get('status') != 'complete' or state.get('audit_passed') is not True
                or state.get('export_passed') is not True):
            raise RuntimeError('Audit/export chưa hoàn tất; chạy lại mục 7–9.')
        counts = state['counts']
        if (counts['pending'] != 0
                or counts['completed'] != counts['selected']):
            raise RuntimeError('Audit/export chưa hoàn tất; chạy lại mục 7–9.')
        if manifest is not None:
            if manifest.get('complete') is not True or any(
                    manifest.get(key) != counts[key] for key in ('selected', 'completed', 'pending', 'accepted')):
                raise RuntimeError('Manifest chưa khớp kết quả audit/export; chạy lại mục 7–9.')
        for name, key in (('manifest.json', 'source_manifest_sha256'), ('sample.jsonl', 'sample_sha256'),
                          ('audit_summary.json', 'audit_summary_sha256')):
            if file_hash(out / name) != state.get(key):
                raise RuntimeError(f'Bằng chứng audit đã thay đổi: {name}; chạy lại mục 7–9.')
        if records_hash(out) != state.get('records_sha256'):
            raise RuntimeError('Checkpoint đã thay đổi sau audit; chạy lại mục 7–9.')
        verify_audit(out, counts)
        if counts['accepted'] > 0 and file_hash(out / 'export_manifest.json') != state.get('export_manifest_sha256'):
            raise RuntimeError('Bằng chứng export đã thay đổi; chạy lại mục 7–9.')
        verify_export(out, counts)
        return state
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise RuntimeError('Thiếu hoặc hỏng bằng chứng audit/export; chạy lại mục 7–9.') from exc


def invalidate(out, *, status='pending', failed_step=None, error=None):
    state = {'status': status, 'audit_passed': False, 'export_passed': False}
    if failed_step:
        state.update(failed_step=failed_step, error=str(error))
    write_json(Path(out) / 'postprocess_status.json', state)
    return state


def run_postprocess(out, source, execute):
    """Use the saved crawler for report, then the refreshed auditor/exporter; never crawl."""
    out = Path(out)
    state = invalidate(out, status='running')
    step = 'report'
    try:
        STORAGE.prepare_reports(out)
        execute(out / 'storage_snapshot.py', 'report', '--out', out)
        counts = read_json(out / 'quality_report.json')
        state['counts'] = {key: counts[key] for key in ('selected', 'completed', 'pending', 'accepted')}
        if counts['pending']:
            state['status'] = 'incomplete'
            if counts['accepted'] > 0:
                # Useful output on a storage pause; never present unaudited data as final corpus.
                execute(out / 'export_snapshot.py', '--out', out, '--partial')
            return counts
        step = 'audit'
        execute(out / 'audit_snapshot.py', '--out', out, '--source', source)
        verify_audit(out, counts)
        state['audit_passed'] = True
        step = 'export'
        if counts['accepted'] > 0:
            execute(out / 'export_snapshot.py', '--out', out)
        verify_export(out, counts)
        state.update(status='complete', export_passed=True,
                     source_manifest_sha256=file_hash(out / 'manifest.json'),
                     sample_sha256=file_hash(out / 'sample.jsonl'), records_sha256=records_hash(out),
                     audit_summary_sha256=file_hash(out / 'audit_summary.json'))
        if counts['accepted'] > 0:
            state['export_manifest_sha256'] = file_hash(out / 'export_manifest.json')
        return counts
    except BaseException as exc:
        state.update(status='failed', failed_step=step, error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        write_json(out / 'postprocess_status.json', state)


def package_run(out, workdir, *, id_from, id_to, dataset_revision, source_sha256, packages,
                refresh_diagnostics, failed_step=None, error=None):
    """Attempt both archives even after a processing error; preserve raw/checkpoints."""
    out, workdir = Path(out), Path(workdir)
    if failed_step:
        try:
            saved = read_json(out / 'postprocess_status.json')
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict) or saved.get('status') != 'failed' or saved.get('error') != str(error):
            invalidate(out, status='failed', failed_step=failed_step, error=error)
    try:
        state = require_ready(out)
        complete = True
    except RuntimeError:
        state, complete = {}, False
    counts = state.get('counts', {})
    if not counts:
        # Rescue must also work when report was never written or a checkpoint is corrupt.
        try:
            selected = read_json(out / 'manifest.json').get('selected', 0)
        except (OSError, ValueError, AttributeError):
            selected = 0
        rows = []
        for path in (out / 'records').glob('*.json'):
            try:
                record = read_json(path)
                if isinstance(record, dict):
                    rows.append(record)
            except (OSError, ValueError):
                pass
        counts = {'selected': selected, 'completed': len(rows), 'pending': max(0, selected - len(rows)),
                  'accepted': sum(r.get('quality_status') == 'accepted' for r in rows)}
    manifest = {
        'id_from_inclusive': id_from, 'id_to_inclusive': id_to,
        'dataset_revision': dataset_revision, 'source_sha256': source_sha256,
        **counts, 'complete': complete, 'audit_passed': complete, 'export_passed': complete,
        'packages': packages,
        'exported_files': [name for name in ('corpus.parquet', 'corpus.jsonl') if (out/name).exists()]
                          if complete and counts['accepted'] > 0 else [],
    }
    if failed_step:
        manifest.update(failed_step=failed_step, error=str(error))
    write_json(out / 'notebook_manifest.json', manifest)
    diagnostic_error = None
    # Diagnostics replaces its archive atomically; failure blocks upload via the manifest.
    try:
        refresh_diagnostics(strict=True)
    except Exception as exc:
        diagnostic_error = exc
        manifest['complete'] = False
        write_json(out / 'notebook_manifest.json', manifest)
    archive = workdir / f'{out.name}.zip'
    temporary = archive.with_suffix('.zip.tmp')
    temporary.unlink(missing_ok=True)
    all_paths = [p for p in out.rglob('*') if p.is_file() and not p.is_symlink()
                 and p.suffix not in ('.tmp', '.lock') and '__pycache__' not in p.parts]
    # Successful runs need a results bundle, not another full raw/checkpoint copy.
    compact = complete or not STORAGE.archive_fits(all_paths, archive)
    manifest['archive_kind'] = 'results' if compact else 'resume_checkpoint'
    write_json(out / 'notebook_manifest.json', manifest)
    paths = [p for p in all_paths if p.parent == out and
             (p.suffix in ('.parquet', '.csv', '.md') or p.name in (
                 'notebook_manifest.json', 'export_manifest.json', 'audit_summary.json',
                 'postprocess_status.json', 'quality_report.json', 'audit_cases.jsonl',
                 'review_100.jsonl', 'review_100.html'))] if compact else all_paths
    try:
        if not STORAGE.archive_fits(paths, archive):
            # Parquet and diagnostics already exist independently; skip an optional duplicate ZIP.
            print('Skipping results ZIP: reserve disk for corpus.parquet and diagnostics.', flush=True)
            if diagnostic_error is not None: raise diagnostic_error
            return None
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as bundle:
            for path in sorted(paths):
                bundle.write(path, out.name + '/' + path.relative_to(out).as_posix())
        temporary.replace(archive)
    except BaseException:
        manifest['complete'] = False
        write_json(out / 'notebook_manifest.json', manifest)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    if diagnostic_error is not None:
        raise diagnostic_error
    return archive
