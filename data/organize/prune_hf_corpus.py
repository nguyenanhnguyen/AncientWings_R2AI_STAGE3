"""Remove from the HF dataset every corpus record outside the organisers' current id/url list.

The organisers replaced links_corpus.parquet with links_corpus_vi_en_zh.parquet, dropping
3.414.120 ids. Records of those ids can never be scored, so they are deleted here; a record whose
id is on the list but whose url differs is deleted too, because the pair is the identity of a
document.

Preview (downloads corpus shards, changes nothing):
    python data/organize/prune_hf_corpus.py

Apply:
    python data/organize/prune_hf_corpus.py --apply

What happens to each `corpus/<name>.parquet`:

    every row kept     left untouched, not even re-uploaded
    some rows removed  rewritten with the kept rows, same schema and row order; its
                       `corpus_jsonl/<name>.jsonl` is regenerated from those rows, and both
                       manifests under `manifests/<name>/` get fresh counts and hashes
    every row removed  the shard, its jsonl and its manifests are deleted

Shard file names keep their original `ids_<min>_<max>_synced` form even when pruning narrows the
range, so links in older reports stay valid; the manifest records the original and the new range.
`archives/<name>.zip` holds the raw evidence of a shard. It is left alone by default and reported,
because it is provenance, not corpus data, and rewriting a ZIP means downloading gigabytes;
`--archives delete` removes the archives of pruned shards instead.

Nothing else is touched: `code/`, `inputs/`, `diagnostics/` and `teach/` are left as they are.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
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


def shard_name(path_in_repo):
    return Path(path_in_repo).stem


def plan_shard(db, local_parquet):
    """-> (kept rows, [(id, reason, official url)]) for one downloaded corpus shard."""
    import pyarrow.parquet as pq
    table = pq.read_table(local_parquet)
    missing = [name for name in ('id', 'url') if name not in table.schema.names]
    if missing:
        raise ValueError(f'{local_parquet} has no {missing} column.')
    kept, removed = [], []
    for row in table.to_pylist():
        expected = sync.official_url(db, row['id'])
        if expected is None:
            removed.append((row['id'], 'id_not_in_official_list', None))
        elif expected != row['url']:
            removed.append((row['id'], 'url_differs', expected))
        else:
            kept.append(row)
    return kept, removed, table.schema


def write_shard(directory, name, kept, schema, *, jsonl=True):
    """Rewrite one shard from its kept rows. -> [(local path, path in repo)]."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    directory.mkdir(parents=True, exist_ok=True)
    parquet = directory / f'{name}.parquet'
    pq.write_table(pa.Table.from_pylist(kept, schema=schema), parquet, compression='zstd')
    if pq.read_table(parquet).to_pylist() != kept:
        raise ValueError(f'Parquet round-trip mismatch while pruning {name}')
    files = [(parquet, f'corpus/{name}.parquet')]
    if jsonl:
        # Regenerated from the kept rows, exactly as make_shard wrote it, so the 5 GiB of JSONL
        # on the Hub never has to be downloaded.
        path = directory / f'{name}.jsonl'
        with path.open('w', encoding='utf-8') as stream:
            for row in kept:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        files.append((path, f'corpus_jsonl/{name}.jsonl'))
    return files


def prune_manifests(directory, name, manifests, kept, files, removed_count):
    """Refresh the shard's manifests: new counts, id range, file hashes and a pruning note."""
    out = []
    ids = [row['id'] for row in kept]
    note = {'pruned_at_utc': datetime.now(timezone.utc).isoformat(),
            'pruned_by': Path(__file__).name,
            'records_removed': removed_count, 'records_kept': len(kept),
            'reason': f'id/url not in {sync.SOURCE_FILE}',
            'source_file': sync.SOURCE_FILE, 'source_sha256': sync.SOURCE_SHA256,
            'source_revision': sync.SOURCE_REVISION}
    for remote, body in manifests.items():
        body = dict(body)
        before = (body.get('id_from_inclusive'), body.get('id_to_inclusive'))
        for key in ('selected', 'completed', 'accepted'):
            if key in body:
                body[key] = len(kept)
        if 'counts' in body and isinstance(body['counts'], dict):
            body['counts'] = {k: (len(kept) if k in ('selected', 'completed', 'accepted') else v)
                              for k, v in body['counts'].items()}
        body['id_from_inclusive'], body['id_to_inclusive'] = min(ids), max(ids)
        body['official_id_url_verified'] = True
        body['source_file'] = sync.SOURCE_FILE
        body['source_sha256'] = sync.SOURCE_SHA256
        body['dataset_revision'] = sync.SOURCE_REVISION
        body['pruning'] = {**note, 'id_range_before': list(before),
                           'name_keeps_original_range': True}
        if 'files' in body and isinstance(body['files'], list):
            sizes = {remote_path: local for local, remote_path in files}
            body['files'] = [{'path_in_repo': item['path_in_repo'],
                              'bytes': sizes[item['path_in_repo']].stat().st_size,
                              'sha256': sync.sha_file(sizes[item['path_in_repo']])}
                             if item.get('path_in_repo') in sizes else item
                             for item in body['files']]
        path = directory / Path(remote).name
        sync.write_json(path, body)
        out.append((path, remote))
    return out


def commit(api, repo, parent, operations, message, attempts):
    """One commit with a pinned parent, so a concurrent push cannot be overwritten."""
    import time
    for attempt in range(1, attempts + 1):
        try:
            result = api.create_commit(repo_id=repo, repo_type='dataset', revision='main',
                                       parent_commit=parent, commit_message=message,
                                       operations=operations)
            return result.oid, result.commit_urlp
        except Exception as error:
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            if status in (409, 412):
                raise RuntimeError('The dataset changed while pruning. Run again: the plan is '
                                   'rebuilt from the new revision and finished commits are kept.') from None
            if status in (400, 401, 403, 404, 422) or attempt == attempts:
                raise
            head = api.repo_info(repo_id=repo, repo_type='dataset', revision='main').sha
            if head != parent:
                raise RuntimeError('The dataset head moved after an upload error. Run again to '
                                   'rebuild the plan.') from None
            print(f'Commit attempt {attempt} failed (HTTP {status or "?"}); retrying.', flush=True)
            time.sleep(min(2 ** attempt, 15))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repo-id', default=sync.REPO)
    parser.add_argument('--source-parquet', type=Path, default=ROOT / f'data/{sync.SOURCE_FILE}',
                        help=f"The organisers' current id/url list (default data/{sync.SOURCE_FILE}).")
    parser.add_argument('--out', type=Path, default=ROOT / 'work/hf_prune')
    parser.add_argument('--apply', action='store_true',
                        help='Commit the plan. Without it nothing on the Hub changes.')
    parser.add_argument('--shards-per-commit', type=int, default=20)
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--archives', choices=['keep', 'delete'], default='keep',
                        help="'keep' (default) leaves archives/<name>.zip and reports it; "
                             "'delete' removes the archive of every pruned shard.")
    parser.add_argument('--limit-shards', type=int, help='Inspect only the first N shards (testing).')
    args = parser.parse_args(argv)
    if args.shards_per_commit < 1 or args.attempts < 1:
        parser.error('--shards-per-commit and --attempts must be positive')

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    from huggingface_hub import HfApi, CommitOperationAdd, CommitOperationDelete, get_token, hf_hub_download
    token = os.environ.get('HF_TOKEN') or get_token()
    if not token:
        raise RuntimeError('Set HF_TOKEN or run hf auth login. Never put a token in this script.')
    api = HfApi(token=token)

    with sync.workspace_lock(out), sync.new_database(out / 'prune.sqlite') as db:
        sync.index_official(db, args.source_parquet)
        parent = api.repo_info(repo_id=args.repo_id, repo_type='dataset', revision='main').sha
        files = sorted(api.list_repo_files(repo_id=args.repo_id, repo_type='dataset', revision=parent))
        shards = [f for f in files if f.startswith('corpus/') and f.endswith('.parquet')]
        if args.limit_shards:
            shards = shards[:args.limit_shards]
        present = set(files)
        print(f'{args.repo_id}@{parent[:12]}: {len(shards)} corpus shards', flush=True)

        counts = Counter()
        plan = []
        report = out / 'removed_records.jsonl'
        with report.open('w', encoding='utf-8') as removed_log:
            for position, remote in enumerate(shards, 1):
                name = shard_name(remote)
                local = hf_hub_download(repo_id=args.repo_id, repo_type='dataset', filename=remote,
                                        revision=parent, token=token, cache_dir=str(out / 'hf_cache'))
                kept, removed, schema = plan_shard(db, local)
                counts['records'] += len(kept) + len(removed)
                counts['records_kept'] += len(kept)
                counts['records_removed'] += len(removed)
                for doc_id, reason, official in removed:
                    counts[reason] += 1
                    removed_log.write(json.dumps({'shard': remote, 'id': doc_id, 'reason': reason,
                                                  'official_url': official}, ensure_ascii=False) + '\n')
                if not removed:
                    counts['shards_unchanged'] += 1
                    action = 'unchanged'
                elif not kept:
                    counts['shards_deleted'] += 1
                    action = 'delete'
                else:
                    counts['shards_rewritten'] += 1
                    action = 'rewrite'
                plan.append({'shard': remote, 'name': name, 'action': action,
                             'kept': len(kept), 'removed': len(removed), 'local': local})
                del kept, removed, schema
                if position % 10 == 0 or position == len(shards):
                    print(f'  {position}/{len(shards)} shards read; '
                          f'{counts["records_removed"]:,} records to remove', flush=True)

        archives = [f'archives/{item["name"]}.zip' for item in plan
                    if item['action'] != 'unchanged' and f'archives/{item["name"]}.zip' in present]
        summary = {'mode': 'apply' if args.apply else 'preview', 'repo_id': args.repo_id,
                   'remote_revision': parent, 'counts': dict(counts),
                   'official_source': {'file': sync.SOURCE_FILE, 'repo': sync.SOURCE_REPO,
                                       'revision': sync.SOURCE_REVISION, 'sha256': sync.SOURCE_SHA256},
                   'archives_policy': args.archives, 'archives_of_pruned_shards': archives,
                   'created_at_utc': datetime.now(timezone.utc).isoformat(),
                   'plan': [{k: item[k] for k in ('shard', 'action', 'kept', 'removed')}
                            for item in plan], 'commits': []}
        sync.write_json(out / 'prune_result.json', summary)
        print(json.dumps({k: v for k, v in summary['counts'].items()}, indent=2), flush=True)
        if archives:
            verb = 'sẽ bị xóa' if args.archives == 'delete' else 'được giữ nguyên (dùng --archives delete để xóa)'
            print(f'{len(archives)} archive của shard bị sửa {verb}.', flush=True)
        print(f'Chi tiết từng bản ghi bị loại: {report}', flush=True)

        if not counts['records_removed']:
            print('Không có bản ghi nào ngoài danh sách chính thức; không cần sửa gì.')
            return 0
        if not args.apply:
            print(f'PREVIEW: chưa thay đổi gì trên Hub. Thêm --apply để áp dụng. '
                  f'Kế hoạch: {out / "prune_result.json"}')
            return 0

        work = out / 'staging'
        batch, operations, labels = [], [], []
        for item in plan:
            if item['action'] == 'unchanged':
                continue
            name = item['name']
            targets = [item['shard'], f'corpus_jsonl/{name}.jsonl',
                       f'manifests/{name}/notebook_manifest.json',
                       f'manifests/{name}/upload_manifest.json']
            if args.archives == 'delete':
                targets.append(f'archives/{name}.zip')
            if item['action'] == 'delete':
                operations += [CommitOperationDelete(path_in_repo=path) for path in targets
                               if path in present]
            else:
                directory = work / name
                # Read the shard again from the cached file: holding the kept rows of every
                # shard would need several GB of RAM.
                rows, dropped, schema = plan_shard(db, item['local'])
                if len(rows) != item['kept'] or len(dropped) != item['removed']:
                    raise ValueError(f'{item["shard"]} changed between planning and applying.')
                written = write_shard(directory, name, rows, schema,
                                      jsonl=f'corpus_jsonl/{name}.jsonl' in present)
                manifests = {}
                for remote in targets[2:4]:
                    if remote in present:
                        local = hf_hub_download(repo_id=args.repo_id, repo_type='dataset',
                                                filename=remote, revision=parent, token=token,
                                                cache_dir=str(out / 'hf_cache'))
                        manifests[remote] = sync.read_json(local)
                written += prune_manifests(directory, name, manifests, rows, written,
                                           item['removed'])
                operations += [CommitOperationAdd(path_in_repo=remote, path_or_fileobj=str(local))
                               for local, remote in written]
                if args.archives == 'delete' and f'archives/{name}.zip' in present:
                    operations.append(CommitOperationDelete(path_in_repo=f'archives/{name}.zip'))
            labels.append(f'{name}:{item["action"]}')
            batch.append(item)
            if len(batch) >= args.shards_per_commit:
                parent = _flush(api, args, parent, operations, labels, summary, out)
                batch, operations, labels = [], [], []
        if operations:
            parent = _flush(api, args, parent, operations, labels, summary, out)
        print(f'Xong. Báo cáo: {out / "prune_result.json"}')
    return 0


def _flush(api, args, parent, operations, labels, summary, out):
    message = (f'Prune {len(labels)} corpus shards to {sync.SOURCE_FILE} '
               f'({sync.SOURCE_REVISION[:12]})')
    oid, url = commit(api, args.repo_id, parent, operations, message, args.attempts)
    summary['commits'].append({'shards': labels, 'commit_oid': oid, 'commit_url': url})
    sync.write_json(out / 'prune_result.json', summary)
    print(f'Đã commit {len(labels)} shard: {url}', flush=True)
    return oid


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as error:
        message = str(error)
        token = os.environ.get('HF_TOKEN')
        if token:
            message = message.replace(token, '[TOKEN]')
        message = re.sub(r'\bhf_[A-Za-z0-9]{8,}\b', '[TOKEN]', message)
        print(f'{type(error).__name__}: {message}', file=sys.stderr)
        raise SystemExit(1) from None
