"""Remove per-document local crawl artifacts only after exact HF corpus verification.

Preview: python data/organize/cleanup_synced_local.py
Apply:   python data/organize/cleanup_synced_local.py --apply

The remote Parquet corpus is the authority. A matching id, URL and text SHA-256 is
required, as is membership in the current organisers' id/URL list. This tool does
not remove shared run metadata, plain-text logs or the original URL sample.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack, contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

SPEC = importlib.util.spec_from_file_location('sync_local',
                                              Path(__file__).with_name('sync_local_corpus_to_hf.py'))
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)
ROOT = sync.ROOT


def safe_path(run: Path, relative: str) -> Path:
    path = (run / relative).resolve()
    if not path.is_relative_to(run.resolve()):
        raise ValueError(f'Path escapes crawl run: {relative}')
    return path


def record_assets(run: Path, record: dict) -> tuple[list[Path], set[Path]]:
    """Individual JSON checkpoints and raw evidence referenced by one record."""
    doc_id = int(record['id'])
    checkpoints = [run / 'records' / f'{doc_id}.json']
    for folder in ('requests_records', 'browser_records'):
        path = run / folder / f'{doc_id}.json'
        if path.is_file():
            checkpoints.append(path)
    raw = set()
    for source in [record, *(sync.read_json(p) for p in checkpoints[1:])]:
        for relative in sync.raw_references(source):
            path = safe_path(run, relative)
            if path.suffix == '.gz' and path.is_file():
                raw.add(path)
    return checkpoints, raw


def collect_plan(db, runs: list[Path]) -> tuple[list[dict], dict]:
    """Scan every local record so shared raw files are never removed prematurely."""
    planned = []
    refcounts = Counter()
    counts = Counter()
    for run in runs:
        for path in sorted((run / 'records').glob('*.json')):
            counts['scanned'] += 1
            try:
                data = path.read_bytes()
                row = json.loads(data)
                doc_id, url, digest = sync.fingerprint(row)
                if path.stem != str(doc_id):
                    raise ValueError('filename/id mismatch')
                checkpoints, raw = record_assets(run, row)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                counts['unreadable_or_invalid'] += 1
                continue
            for asset in raw:
                refcounts[asset] += 1
            official = sync.official_url(db, doc_id)
            remote = db.execute('SELECT url,digest FROM remote WHERE id=?', (doc_id,)).fetchone()
            if official != url or remote != (url, digest):
                counts['not_exactly_on_hf_and_official'] += 1
                continue
            planned.append({'run': str(run), 'id': doc_id, 'record_sha256': hashlib.sha256(data).hexdigest(),
                            'checkpoints': [str(p) for p in checkpoints],
                            'raw': [str(p) for p in sorted(raw)]})
            counts['verified_on_hf'] += 1
    selected_refs = Counter(Path(p) for item in planned for p in item['raw'])
    scheduled_raw = set()
    # Keep raw files used by any record not verified on HF. A raw file shared by
    # several verified records is scheduled just once.
    for item in planned:
        item['raw'] = [p for p in item['raw']
                       if refcounts[Path(p)] == selected_refs[Path(p)] and p not in scheduled_raw]
        scheduled_raw.update(item['raw'])
        counts['checkpoint_files'] += len(item['checkpoints'])
        counts['unique_raw_files'] += len(item['raw'])
    return planned, dict(counts)


@contextmanager
def lock_run(run: Path):
    lock = run / '.crawl.lock'
    with lock.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(f'Crawler still holds {run}') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def filter_jsonl(path: Path, ids: set[int]) -> int:
    """Remove only rows with an explicit top-level id; leave shared logs untouched."""
    if not path.is_file():
        return 0
    temp = path.with_name(path.name + '.cleanup-tmp')
    removed = 0
    try:
        with path.open('r', encoding='utf-8') as source, temp.open('w', encoding='utf-8') as target:
            for line in source:
                try:
                    row = json.loads(line)
                except ValueError:
                    raise ValueError(f'Cannot safely filter malformed JSONL: {path}') from None
                if isinstance(row, dict) and row.get('id') in ids:
                    removed += 1
                else:
                    target.write(line)
        if removed:
            temp.replace(path)
        else:
            temp.unlink()
    finally:
        if temp.exists():
            temp.unlink()
    return removed


def filter_duplicates(path: Path, ids: set[int]) -> int:
    """Remove deleted IDs from hash groups; groups with fewer than 2 IDs disappear."""
    if not path.is_file():
        return 0
    temp = path.with_name(path.name + '.cleanup-tmp')
    changed = 0
    try:
        with path.open('r', encoding='utf-8') as source, temp.open('w', encoding='utf-8') as target:
            for line in source:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get('doc_ids'), list):
                    raise ValueError(f'Unsupported duplicate group in {path}')
                kept = [value for value in row['doc_ids'] if value not in ids]
                changed += len(row['doc_ids']) - len(kept)
                if len(kept) >= 2:
                    row['doc_ids'] = kept
                    target.write(json.dumps(row, ensure_ascii=False) + '\n')
        if changed:
            temp.replace(path)
        else:
            temp.unlink()
    finally:
        if temp.exists():
            temp.unlink()
    return changed


def filter_parquet(path: Path, ids: set[int]) -> int:
    if not path.is_file():
        return 0
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    source = pq.ParquetFile(path)
    if 'id' not in source.schema_arrow.names:
        return 0
    temp = path.with_name(path.name + '.cleanup-tmp')
    removed = 0
    writer = None
    value_set = pa.array(sorted(ids), type=pa.int64())
    try:
        for batch in source.iter_batches(batch_size=8192):
            table = pa.Table.from_batches([batch])
            mask = pc.invert(pc.is_in(table['id'], value_set=value_set))
            kept = table.filter(mask)
            removed += table.num_rows - kept.num_rows
            if writer is None:
                writer = pq.ParquetWriter(temp, source.schema_arrow, compression='zstd')
            writer.write_table(kept)
        if writer is not None:
            writer.close()
            writer = None
        # Windows keeps the original Parquet file locked while ParquetFile is alive.
        del source
        if removed:
            temp.replace(path)
        elif temp.exists():
            temp.unlink()
    finally:
        if writer is not None:
            writer.close()
        if temp.exists():
            temp.unlink()
    return removed


def apply_plan(plan: list[dict], expected_revision: str, api, repo: str) -> dict:
    if api.repo_info(repo_id=repo, repo_type='dataset', revision='main').sha != expected_revision:
        raise RuntimeError('HF changed after the preview; run preview again.')
    grouped = defaultdict(list)
    for item in plan:
        grouped[Path(item['run'])].append(item)
    counts = Counter()
    with ExitStack() as stack:
        for run in sorted(grouped):
            stack.enter_context(lock_run(run))
        # Verify every remaining checkpoint before changing any file.
        for run, items in grouped.items():
            for item in items:
                path = safe_path(run, f"records/{item['id']}.json")
                if path.exists() and sync.sha_file(path) != item['record_sha256']:
                    raise RuntimeError(f'Record changed since preview: {path}')
        for run, items in grouped.items():
            ids = {item['id'] for item in items}
            for name in ('documents.jsonl', 'corpus.accepted.jsonl', 'corpus.jsonl',
                         'quarantine.jsonl', 'manual_review.jsonl'):
                counts['aggregate_jsonl_rows_removed'] += filter_jsonl(run / name, ids)
            counts['duplicate_group_ids_removed'] += filter_duplicates(run / 'duplicates.jsonl', ids)
            counts['aggregate_parquet_rows_removed'] += filter_parquet(run / 'corpus.parquet', ids)
            # Machine-readable logs with an explicit document ID are safe to filter.
            for log in (run / 'logs').glob('*.jsonl') if (run / 'logs').is_dir() else ():
                counts['log_jsonl_rows_removed'] += filter_jsonl(log, ids)
            # This crawler writes one JSON object per document to a .log file.
            counts['log_jsonl_rows_removed'] += filter_jsonl(
                run / 'logs' / 'corpus_runner_snapshot.log', ids)
            for item in items:
                for value in item['checkpoints'] + item['raw']:
                    path = Path(value)
                    if not path.is_relative_to(run.resolve()):
                        raise ValueError(f'Unsafe deletion path: {path}')
                    if path.is_file():
                        path.unlink()
                        counts['files_deleted'] += 1
                counts['records_cleaned'] += 1
            # Aggregate text logs and run-level reports contain multiple IDs and stay intact.
            counts['shared_logs_retained'] += len(list((run / 'logs').glob('*.log'))) if (run / 'logs').is_dir() else 0
    return dict(counts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--sources', nargs='+', type=Path,
                        default=[ROOT / 'nguyen/output', ROOT / 'nguyen/shards'])
    parser.add_argument('--repo-id', default=sync.REPO)
    parser.add_argument('--out', type=Path, default=ROOT / 'work/hf_local_cleanup')
    parser.add_argument('--apply', action='store_true', help='Delete planned local artifacts; default is preview.')
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import HfApi, hf_hub_download, get_token
    token = os.environ.get('HF_TOKEN') or get_token()
    if not token:
        raise RuntimeError('Run hf auth login or set HF_TOKEN.')
    api = HfApi(token=token)
    with sync.workspace_lock(out), sync.new_database(out / 'index.sqlite') as db:
        sync.index_official(db, ROOT / f'data/{sync.SOURCE_FILE}')
        revision = api.repo_info(repo_id=args.repo_id, repo_type='dataset', revision='main').sha
        sync.index_remote(db, api, args.repo_id, revision, out / 'hf_cache', hf_hub_download)
        runs = sync.discover_runs(args.sources)
        plan, counts = collect_plan(db, runs)
        summary = {'mode': 'apply' if args.apply else 'preview', 'repo_id': args.repo_id,
                   'remote_revision': revision, 'official_source_sha256': sync.SOURCE_SHA256,
                   'counts': counts, 'runs': [str(run) for run in runs],
                   'limitations': ['Raw may exist only locally if HF archives were not uploaded.',
                                   'Shared text logs, reports, URL sample and crawl metadata are retained.',
                                   'Run-level quality reports and artifact manifests become historical after cleanup.',
                                   'Deleted checkpoints cannot be used to resume the crawler.']}
        report_path = out / 'cleanup_result.json'
        plan_path = out / 'cleanup_plan.jsonl'
        next_plan = out / 'cleanup_plan.next.jsonl'
        with next_plan.open('w', encoding='utf-8') as stream:
            for item in plan:
                stream.write(json.dumps(item, ensure_ascii=False) + '\n')
        if args.apply:
            if not report_path.exists() or not plan_path.exists():
                raise RuntimeError('Run a preview first; there is no reviewed cleanup plan.')
            previous = sync.read_json(report_path)
            if (previous.get('mode') != 'preview' or previous.get('repo_id') != args.repo_id
                    or previous.get('remote_revision') != revision
                    or previous.get('official_source_sha256') != sync.SOURCE_SHA256
                    or sync.sha_file(plan_path) != sync.sha_file(next_plan)):
                raise RuntimeError('HF or local cleanup plan changed since preview; run preview again.')
        next_plan.replace(plan_path)
        sync.write_json(report_path, summary)
        print(json.dumps(summary['counts'], indent=2), flush=True)
        if not args.apply:
            print(f'PREVIEW only. Review {out / "cleanup_result.json"} and {plan_path}. '
                  'Use --apply to delete the listed local files.')
            return
        summary['deleted'] = apply_plan(plan, revision, api, args.repo_id)
        sync.write_json(out / 'cleanup_result.json', summary)
        print(json.dumps(summary['deleted'], indent=2), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        message = str(exc)
        if os.environ.get('HF_TOKEN'):
            message = message.replace(os.environ['HF_TOKEN'], '[TOKEN]')
        message = re.sub(r'\bhf_[A-Za-z0-9]{8,}\b', '[TOKEN]', message)
        print(f'{type(exc).__name__}: {message}', file=sys.stderr)
        raise SystemExit(1) from None
