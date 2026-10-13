"""Sync accepted local crawl records into the HF notebook's corpus shard layout.

Preview: python data/organize/sync_local_corpus_to_hf.py
Upload:  python data/organize/sync_local_corpus_to_hf.py --push
See sync_local_corpus_to_hf.md for setup, conflict policy and archive scope.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
REPO = 'AncientWings/AncientWings_R2AI_STAGE3_ds'
SOURCE_REPO = 'AIGuruTinix/ViBioMIR'
# The organisers replaced links_corpus.parquet (4.394.718 rows) with this vi/en/zh list
# (1.220.598 rows) on 2026-10-13. Of the old ids, 980.598 are kept with exactly the same URL and
# 3.414.120 are gone; 240.000 ids are new. Only (id, url) pairs of THIS file may be uploaded,
# because the rules score nothing outside it.
SOURCE_FILE = 'links_corpus_vi_en_zh.parquet'
SOURCE_REVISION = '71be0e1239a19dfd7a717e2bc13e3bec21bd0334'
SOURCE_SHA256 = '87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7'
# A crawl run records the list it was planned against. Runs planned against a retired list stay
# usable: every record is checked against the current list, id and url, before it is uploaded.
RETIRED_SOURCE_SHA256 = {
    'dee1153f5b9d9010dea18e1b7724b4915ff847b711d036bec8b933486802a971': 'links_corpus.parquet',
}
FIELDS = ('id', 'url', 'final_url', 'title', 'text', 'domain', 'extractor',
          'published_at', 'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids')


def canonical_run_name(first_id, last_id):
    if type(first_id) is not int or type(last_id) is not int or first_id < 0 or last_id < first_id:
        raise ValueError('Invalid inclusive source ID range.')
    return f'ids_{first_id}_{last_id}_synced'


def sha_stream(stream):
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
    return digest.hexdigest()


def sha_file(path):
    with Path(path).open('rb') as stream:
        return sha_stream(stream)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def discover_runs(roots):
    """Stop at a run root; never walk millions of raw/record files to find runs."""
    found = set()
    for root in roots:
        root = Path(root).resolve()
        if not root.is_dir():
            raise ValueError(f'Source directory does not exist: {root}')
        if root.name == 'records':
            root = root.parent
        for folder, directories, _ in os.walk(root, followlinks=False):
            path = Path(folder)
            if 'records' in directories:
                if not (path / 'manifest.json').is_file():
                    raise ValueError(f'Missing manifest.json: {path}')
                found.add(path)
                directories[:] = []
            else:
                directories[:] = sorted(d for d in directories if d not in (
                    'raw', 'robots', 'requests_records', 'logs', '__pycache__', '.git', 'data'))
    if not found:
        raise ValueError('No crawl run with manifest.json and records/ found.')
    return sorted(found)


def fingerprint(row):
    doc_id = row.get('id')
    if type(doc_id) is not int or doc_id < 0 or not isinstance(row.get('url'), str) or not row['url']:
        raise ValueError('Record needs an integer source id and a nonempty url.')
    digest = row.get('text_sha256')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError(f'Invalid text_sha256 for id={doc_id}')
    return doc_id, row['url'], digest


def new_database(path):
    db = sqlite3.connect(path)
    # This is a plan rebuilt on every invocation, never the authority for remote state.
    db.executescript('''
        DROP TABLE IF EXISTS remote;
        DROP TABLE IF EXISTS pending;
        DROP TABLE IF EXISTS official;
        CREATE TABLE remote (id INTEGER PRIMARY KEY, url TEXT, digest TEXT, origin TEXT);
        CREATE TABLE pending (id INTEGER PRIMARY KEY, url TEXT, digest TEXT, run TEXT, record TEXT);
        CREATE TABLE official (id INTEGER PRIMARY KEY, url TEXT NOT NULL);
    ''')
    return db


def index_official(db, source):
    """Load the organisers' id/url list into `official`, after checking the file is that list.

    Kept in SQLite rather than a dict: the list has over a million rows, and every later check is
    a primary-key lookup.
    """
    import pyarrow.parquet as pq
    print(f'Read official ID/URL list: {source}', flush=True)
    digest = sha_file(source)
    if digest != SOURCE_SHA256:
        retired = RETIRED_SOURCE_SHA256.get(digest)
        detail = f' That file is the retired {retired}.' if retired else ''
        raise ValueError(f'{source} is not the pinned {SOURCE_FILE} (sha256 {digest}).{detail} '
                         f'Download {SOURCE_FILE} from {SOURCE_REPO} at {SOURCE_REVISION[:12]}.')
    parquet = pq.ParquetFile(source)
    if not {'id', 'url'}.issubset(parquet.schema_arrow.names):
        raise ValueError(f'{source} must hold id and url columns.')
    for batch in parquet.iter_batches(batch_size=65536, columns=['id', 'url']):
        db.executemany('INSERT OR REPLACE INTO official VALUES (?,?)',
                       zip(batch.column('id').to_pylist(), batch.column('url').to_pylist()))
    db.commit()
    total = db.execute('SELECT COUNT(*) FROM official').fetchone()[0]
    if total != parquet.metadata.num_rows:
        raise ValueError(f'Official list has duplicate ids: {parquet.metadata.num_rows} rows, '
                         f'{total} unique ids.')
    print(f'Official list: {total:,} ids.', flush=True)
    return total


def official_url(db, doc_id):
    """The organisers' URL for this id, or None when the id is not on their list."""
    row = db.execute('SELECT url FROM official WHERE id=?', (doc_id,)).fetchone()
    return row[0] if row else None


def index_remote(db, api, repo, revision, cache_dir, download):
    import pyarrow.parquet as pq
    paths = sorted(p for p in api.list_repo_files(repo_id=repo, repo_type='dataset', revision=revision)
                   if p.startswith('corpus/') and p.endswith('.parquet'))
    count = 0
    for i, name in enumerate(paths, 1):
        print(f'Read HF corpus {i}/{len(paths)}: {name}', flush=True)
        local = download(repo_id=repo, repo_type='dataset', filename=name, revision=revision,
                         token=api.token, cache_dir=str(cache_dir))
        parquet = pq.ParquetFile(local)
        names = parquet.schema_arrow.names
        if not {'id', 'url'}.issubset(names) or not {'text', 'text_sha256'}.intersection(names):
            raise ValueError(f'Unsupported HF corpus schema: {name}')
        columns = ['id', 'url', 'text_sha256' if 'text_sha256' in names else 'text']
        for batch in parquet.iter_batches(batch_size=8192, columns=columns):
            for row in batch.to_pylist():
                if 'text_sha256' not in row:
                    row['text_sha256'] = hashlib.sha256(row['text'].encode('utf-8')).hexdigest()
                doc_id, url, digest = fingerprint(row)
                prior = db.execute('SELECT url,digest,origin FROM remote WHERE id=?', (doc_id,)).fetchone()
                if prior and prior[:2] != (url, digest):
                    raise ValueError(f'HF already has conflicting id={doc_id}: {prior[2]} vs {name}')
                db.execute('INSERT OR IGNORE INTO remote VALUES (?,?,?,?)', (doc_id, url, digest, name))
                count += 1
        db.commit()
    print(f'HF: {len(paths)} corpus shards, {count:,} rows, '
          f'{db.execute("SELECT COUNT(*) FROM remote").fetchone()[0]:,} unique IDs.', flush=True)


def plan_local(db, runs, out, max_new=None, on_conflict='error'):
    counts = Counter()
    with (out / 'conflicts.jsonl').open('w', encoding='utf-8') as conflicts, \
            (out / 'deferred.jsonl').open('w', encoding='utf-8') as deferred, \
            (out / 'not_official.jsonl').open('w', encoding='utf-8') as unofficial:
        for run in runs:
            manifest = read_json(run / 'manifest.json')
            pinned = manifest.get('source_sha256')
            if pinned != SOURCE_SHA256 and pinned not in RETIRED_SOURCE_SHA256:
                raise ValueError(f'Run uses an unknown source dataset: {run}')
            print(f'Scan records: {run}', flush=True)
            for path in sorted((run / 'records').glob('*.json')):
                counts['scanned'] += 1
                if counts['scanned'] % 10000 == 0:
                    print(f'  scanned={counts["scanned"]:,}, new={counts["new"]:,}', flush=True)
                try:
                    before = signature(path)
                    row = read_json(path)
                    if before != signature(path):
                        raise ValueError('Record changed while being read')
                except (OSError, ValueError) as error:
                    deferred.write(json.dumps({'path': str(path), 'reason': str(error)}) + '\n')
                    counts['deferred'] += 1
                    continue
                if not isinstance(row, dict):
                    raise ValueError(f'Invalid record object: {path}')
                if row.get('quality_status') != 'accepted' or row.get('status') != 'extracted':
                    counts['not_accepted'] += 1
                    continue
                doc_id, url, digest = fingerprint(row)
                if path.stem != str(doc_id):
                    raise ValueError(f'Record filename/id mismatch: {path}')
                # Only ids and urls of the organisers' current list can ever be scored, so a
                # record outside it is dropped here instead of being uploaded.
                expected = official_url(db, doc_id)
                if expected is None or expected != url:
                    reason = 'id_not_in_official_list' if expected is None else 'url_differs'
                    unofficial.write(json.dumps({'id': doc_id, 'reason': reason, 'local_url': url,
                                                 'official_url': expected, 'path': str(path)},
                                                ensure_ascii=False) + '\n')
                    counts[reason] += 1
                    continue
                if not isinstance(row.get('text'), str) or not row['text'].strip():
                    raise ValueError(f'Empty accepted text: {path}')
                if hashlib.sha256(row['text'].encode('utf-8')).hexdigest() != digest:
                    raise ValueError(f'Text hash mismatch: {path}')
                prior = db.execute('SELECT url,digest,origin FROM remote WHERE id=?', (doc_id,)).fetchone()
                origin = 'remote'
                if not prior:
                    prior = db.execute('SELECT url,digest,run FROM pending WHERE id=?', (doc_id,)).fetchone()
                    origin = 'local'
                if prior:
                    if prior[:2] == (url, digest):
                        counts[f'duplicate_{origin}'] += 1
                    else:
                        keep_remote = on_conflict == 'keep-remote' and origin == 'remote' and prior[0] == url
                        conflicts.write(json.dumps({'id': doc_id, 'existing_origin': prior[2],
                            'local_path': str(path), 'existing_url': prior[0], 'local_url': url,
                            'existing_text_sha256': prior[1], 'local_text_sha256': digest,
                            'action': 'keep_remote' if keep_remote else 'blocked'},
                            ensure_ascii=False) + '\n')
                        counts['conflicts'] += 1
                        if keep_remote:
                            counts['conflicts_kept_remote'] += 1
                    continue
                # Store the captured record, so the live crawler cannot change this plan.
                db.execute('INSERT INTO pending VALUES (?,?,?,?,?)',
                           (doc_id, url, digest, str(run), json.dumps(row, ensure_ascii=False)))
                counts['new'] += 1
                if counts['new'] % 1000 == 0:
                    db.commit()
                if max_new and counts['new'] >= max_new:
                    break
            if max_new and counts['new'] >= max_new:
                break
    db.commit()
    return dict(counts)


def verify_source(db):
    """Last gate before upload: every planned record must be on the official list, id and url."""
    print('Check planned records against the official ID/URL list.', flush=True)
    bad = db.execute('''SELECT p.id, p.url, o.url FROM pending p LEFT JOIN official o ON p.id = o.id
                        WHERE o.url IS NULL OR o.url <> p.url LIMIT 5''').fetchall()
    if bad:
        raise ValueError(f'Planned records are not on the official list: {bad}')


def evidence_path(run, relative):
    relative = PurePosixPath(str(relative).replace('\\', '/'))
    if relative.is_absolute() or '..' in relative.parts or ':' in str(relative):
        raise ValueError(f'Raw evidence path must be relative to its run: {relative}')
    path = (run / str(relative)).resolve()
    if not path.is_relative_to(run.resolve()) or not path.is_file():
        raise ValueError(f'Missing/unsafe evidence path: {path}')
    return path, str(relative)


def raw_references(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in ('raw_path', 'requests_record_path') and item:
                yield item
            else:
                yield from raw_references(item)
    elif isinstance(value, list):
        for item in value:
            yield from raw_references(item)


def make_shard(entries, directory, name, repo, *, archive=False, jsonl=True):
    import pyarrow as pa
    import pyarrow.parquet as pq
    directory.mkdir(parents=True, exist_ok=True)
    rows, records, evidence = [], [], {}
    for doc_id, _url, _digest, run_name, record in entries:
        run, row = Path(run_name), json.loads(record)
        if not row.get('raw_path') or not row.get('raw_sha256'):
            raise ValueError(f'Missing raw evidence for id={doc_id}')
        raw, relative = evidence_path(run, row['raw_path'])
        before = signature(raw)
        with gzip.open(raw, 'rb') as stream:
            if sha_stream(stream) != row['raw_sha256']:
                raise ValueError(f'Raw SHA-256 mismatch: {raw}')
        if before != signature(raw):
            raise ValueError(f'Raw changed while being verified: {raw}')
        # Distinct local runs can use identical relative paths. Give each a namespace.
        namespace = hashlib.sha256(str(run).encode('utf-8')).hexdigest()[:16]
        prefix = f'sources/{namespace}'
        exported = {field: row.get(field) for field in FIELDS}
        exported['raw_path'] = f'{prefix}/{relative}'
        rows.append(exported)
        records.append((f'{prefix}/records/{doc_id}.json', record))
        for reference in raw_references(row):
            path, rel = evidence_path(run, reference)
            key = f'{prefix}/{rel}'
            evidence[key] = (path, signature(path))
        if evidence[f'{prefix}/{relative}'][1] != before:
            raise ValueError(f'Raw changed after validation: {raw}')
    schema = pa.schema([(key, pa.int64() if key == 'id' else
                         pa.list_(pa.int64()) if key == 'duplicate_doc_ids' else pa.string()) for key in FIELDS])
    parquet = directory / 'corpus.parquet'
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), parquet, compression='zstd')
    if pq.read_table(parquet).to_pylist() != rows:
        raise ValueError('Parquet round-trip mismatch')
    files = [(parquet, f'corpus/{name}.parquet')]
    if jsonl:
        path = directory / 'corpus.jsonl'
        with path.open('w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        files.append((path, f'corpus_jsonl/{name}.jsonl'))
    manifest = {'format_version': 1, 'generated_by': Path(__file__).name, 'run_name': name,
        'snapshot_scope': 'new_accepted_records_only', 'full_crawl_resume_supported': False,
        'id_from_inclusive': min(r['id'] for r in rows), 'id_to_inclusive': max(r['id'] for r in rows),
        'dataset_revision': SOURCE_REVISION, 'source_sha256': SOURCE_SHA256,
        'source_file': SOURCE_FILE, 'official_id_url_verified': True,
        'selected': len(rows), 'completed': len(rows), 'pending': 0, 'accepted': len(rows),
        'complete': True, 'audit_passed': True, 'export_passed': True,
        'audit_scope': 'source ID/URL, text SHA-256, decompressed raw SHA-256, Parquet round trip',
        'parent_runs': sorted({Path(e[3]).name for e in entries}),
        'exported_files': ['corpus.parquet'] + (['corpus.jsonl'] if jsonl else [])}
    manifest_path = directory / 'notebook_manifest.json'
    write_json(manifest_path, manifest)
    files.append((manifest_path, f'manifests/{name}/notebook_manifest.json'))
    if archive:
        path = directory / f'{name}.zip'
        # Gzip evidence is already compressed; ZIP_STORED avoids CPU recompression.
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
            for relative, record in records:
                bundle.writestr(f'{name}/{relative}', record.encode('utf-8'))
            for relative, (local, stat) in evidence.items():
                if signature(local) != stat:
                    raise ValueError(f'Evidence changed during packaging: {local}')
                bundle.write(local, f'{name}/{relative}')
                if signature(local) != stat:
                    raise ValueError(f'Evidence changed during packaging: {local}')
            for local, _remote in files:
                bundle.write(local, f'{name}/{local.name}')
        files.append((path, f'archives/{name}.zip'))
    proof = {'format_version': 1, 'source_notebook': 'crawl_corpus_kaggle_hf_upload.ipynb',
        'generated_by': Path(__file__).name, 'repo_id': repo, 'run_name': name,
        'dataset_revision': SOURCE_REVISION, 'source_sha256': SOURCE_SHA256,
        'source_file': SOURCE_FILE, 'official_id_url_verified': True,
        'id_from_inclusive': manifest['id_from_inclusive'], 'id_to_inclusive': manifest['id_to_inclusive'],
        'complete': True, 'corpus_policy': 'accepted_only', 'snapshot_scope': manifest['snapshot_scope'],
        'counts': {k: manifest[k] for k in ('selected', 'completed', 'pending', 'accepted')},
        'files': [{'path_in_repo': remote, 'bytes': local.stat().st_size, 'sha256': sha_file(local)}
                  for local, remote in files]}
    proof_path = directory / 'upload_manifest.json'
    write_json(proof_path, proof)
    files.append((proof_path, f'manifests/{name}/upload_manifest.json'))
    return files


def commit_shard(api, repo, parent, files, name, attempts, operation_add):
    """Pin the parent commit so another contributor cannot invalidate ID dedup silently."""
    for attempt in range(1, attempts + 1):
        try:
            commit = api.create_commit(repo_id=repo, repo_type='dataset', revision='main',
                parent_commit=parent, commit_message=f'Sync local crawl {name}',
                operations=[operation_add(path_in_repo=remote, path_or_fileobj=str(local))
                            for local, remote in files])
            return commit.oid, commit.commit_url
        except Exception as error:
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            if status in (409, 412):
                raise RuntimeError('HF changed during sync. Run again to refresh ID dedup; '
                                   'completed commits are preserved.') from None
            if status in (400, 401, 403, 404, 422) or attempt == attempts:
                raise
            # A timeout may occur after a successful commit. Never retry on a changed head.
            head = api.repo_info(repo_id=repo, repo_type='dataset', revision='main').sha
            if head != parent:
                raise RuntimeError('HF head changed after an upload error. Run again; remote '
                                   'corpus is rechecked, including any commit that succeeded.') from None
            print(f'Upload attempt {attempt} failed (HTTP {status or "?"}); retrying.', flush=True)
            time.sleep(min(2 ** attempt, 15))


@contextmanager
def workspace_lock(out):
    """OS lock is released after a crash; keep the tiny lock file for future runs."""
    with (out / '.sync.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another sync is using this --out directory.') from None
        yield


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', nargs='+', type=Path,
                        default=[ROOT / 'nguyen/output', ROOT / 'nguyen/shards'])
    parser.add_argument('--repo-id', default=REPO)
    parser.add_argument('--source-parquet', type=Path, default=ROOT / f'data/{SOURCE_FILE}',
                        help=f'The organisers\' current id/url list (default data/{SOURCE_FILE}).')
    parser.add_argument('--out', type=Path, default=ROOT / 'work/hf_local_sync')
    parser.add_argument('--batch-size', type=int, default=1000, help='Accepted records per HF commit.')
    parser.add_argument('--max-new', type=int, help='Limit new accepted records in this invocation.')
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--on-conflict', choices=['error', 'keep-remote'], default='error',
                        help='Keep existing HF text for same-ID/same-URL conflicts; '
                             'different URLs and local-only conflicts still block upload.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--push', action='store_true', help='Upload; default is preview only.')
    mode.add_argument('--local-only', action='store_true', help='Offline preview; no HF dedup or upload.')
    archive_mode = parser.add_mutually_exclusive_group()
    archive_mode.add_argument('--archive', dest='archive', action='store_true',
                              help='Opt in to packaging and uploading raw/records ZIPs (default: off).')
    archive_mode.add_argument('--no-archive', dest='archive', action='store_false',
                              help='Keep raw local; still verify raw hashes (the default).')
    parser.set_defaults(archive=False)
    parser.add_argument('--no-jsonl', action='store_true')
    args = parser.parse_args(argv)
    if args.batch_size < 1 or args.attempts < 1 or (args.max_new is not None and args.max_new < 1):
        parser.error('Batch size, attempts and max-new must be positive.')
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        raise RuntimeError('Install dependencies: python -m pip install pyarrow "huggingface_hub>=0.34,<3"') from None
    runs = discover_runs(args.sources)
    out = args.out.resolve()
    if any(out.is_relative_to(run) or run.is_relative_to(out) for run in runs):
        raise ValueError('--out must be separate from all crawl run directories.')
    out.mkdir(parents=True, exist_ok=True)
    with workspace_lock(out), new_database(out / 'plan.sqlite') as db:
        index_official(db, args.source_parquet)
        api, parent, operation_add = None, None, None
        if not args.local_only:
            try:
                from huggingface_hub import HfApi, CommitOperationAdd, hf_hub_download, get_token
            except ImportError:
                raise RuntimeError('Install: python -m pip install "huggingface_hub>=0.34,<3"') from None
            token = os.environ.get('HF_TOKEN') or get_token()
            if not token:
                raise RuntimeError('Set HF_TOKEN or run hf auth login. Never put a token in this script.')
            api = HfApi(token=token)
            parent = api.repo_info(repo_id=args.repo_id, repo_type='dataset', revision='main').sha
            operation_add = CommitOperationAdd
            index_remote(db, api, args.repo_id, parent, out / 'hf_cache', hf_hub_download)
        else:
            print('OFFLINE PREVIEW: remote IDs are unknown; counts are local only.', flush=True)
        counts = plan_local(db, runs, out, args.max_new, args.on_conflict)
        summary = {'mode': 'push' if args.push else 'local_only' if args.local_only else 'preview',
                   'repo_id': args.repo_id, 'remote_revision': parent, 'counts': counts,
                   'official_source': {'file': SOURCE_FILE, 'repo': SOURCE_REPO,
                                       'revision': SOURCE_REVISION, 'sha256': SOURCE_SHA256,
                                       'path': str(args.source_parquet)},
                   'on_conflict': args.on_conflict,
                   'created_at_utc': datetime.now(timezone.utc).isoformat(), 'commits': []}
        write_json(out / 'sync_result.json', summary)
        print(json.dumps(counts, indent=2), flush=True)
        if counts.get('conflicts', 0) > counts.get('conflicts_kept_remote', 0):
            raise RuntimeError(f'Conflicting IDs. Review {out / "conflicts.jsonl"}; no new commit was made.')
        if not counts.get('new'):
            print('No new accepted records to sync.')
            return 0
        verify_source(db)
        cursor = db.execute('SELECT id,url,digest,run,record FROM pending ORDER BY id')
        part = 0
        while entries := cursor.fetchmany(args.batch_size):
            part += 1
            name = canonical_run_name(entries[0][0], entries[-1][0])
            if api:
                # Never overwrite an existing run, even if someone left only a partial manifest.
                for remote in (f'corpus/{name}.parquet', f'corpus_jsonl/{name}.jsonl',
                               f'archives/{name}.zip', f'manifests/{name}/upload_manifest.json',
                               f'manifests/{name}/notebook_manifest.json'):
                    if api.file_exists(repo_id=args.repo_id, repo_type='dataset', revision=parent, filename=remote):
                        raise RuntimeError(f'Destination path already exists: {remote}. Inspect it before retrying.')
            directory = out / 'staging' / name
            print(f'Prepare shard {part}: {name} ({len(entries):,} records)', flush=True)
            files = make_shard(entries, directory, name, args.repo_id,
                               archive=args.archive, jsonl=not args.no_jsonl)
            print(f'  {sum(p.stat().st_size for p, _ in files) / 1024**2:.1f} MiB prepared.', flush=True)
            if args.push:
                parent, url = commit_shard(api, args.repo_id, parent, files, name, args.attempts, operation_add)
                summary['commits'].append({'run_name': name, 'commit_oid': parent, 'commit_url': url})
                write_json(out / 'sync_result.json', summary)
                print(f'Uploaded: {url}', flush=True)
        print(f'Done. Report: {out / "sync_result.json"}', flush=True)
        if not args.push:
            print('No upload performed. Use --push to sync after reviewing this preview.')
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as error:
        # SDK errors can contain credentials or signed URLs; do not echo them unfiltered.
        message = str(error)
        token = os.environ.get('HF_TOKEN')
        if token:
            message = message.replace(token, '[TOKEN]')
        message = re.sub(r'\bhf_[A-Za-z0-9]{8,}\b', '[TOKEN]', message)
        message = re.sub(r'(https?://[^\s?]+)\?\S+', r'\1?[QUERY]', message)
        print(f'ERROR: {type(error).__name__}: {message}', file=sys.stderr)
        raise SystemExit(130 if isinstance(error, KeyboardInterrupt) else 1)
