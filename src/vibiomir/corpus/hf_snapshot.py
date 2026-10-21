"""Freeze a pinned corpus subset selected by language and source ID from the team's HF dataset.

Parquet shards are read through the Hub filesystem with seekable ranged reads. Only the selected
rows and, when missing locally, the two official files are materialised in the output directory.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
from pathlib import Path
import shutil

import pyarrow as pa
import pyarrow.parquet as pq

from .prepare import CORPUS_SCHEMA, normalise_row
from ..common import storage

OFFICIAL_REPO = 'AIGuruTinix/ViBioMIR'
OFFICIAL_REVISION = '71be0e1239a19dfd7a717e2bc13e3bec21bd0334'
LINKS_NAME = 'links_corpus_vi_en_zh.parquet'
LINKS_SHA256 = '87e44a792d7a99fb0fde5dff7f09f1a38a0a1fdf02ddd1ac93a005736e00b0a7'
QUERIES_NAME = 'query.parquet'
QUERIES_SHA256 = 'ce13508b893bbd6b9169679d540630bc37eb5950cad08b4d5e0e5d7063670c08'


def _rank(doc_id, seed):
    return int.from_bytes(hashlib.blake2b(f'{seed}:{doc_id}'.encode(), digest_size=8).digest(),
                          'big')


def _rows(path):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=2048):
        yield from batch.to_pylist()


def _remote_rows(fs, repo, revision, filename, ranges=()):
    path = f'hf://datasets/{repo}@{revision}/{filename}'
    with fs.open(path, 'rb', block_size=4 * 1024 * 1024) as stream:
        parquet = pq.ParquetFile(stream)
        groups = None
        if ranges and 'id' in parquet.schema.names:
            column = parquet.schema.names.index('id')
            groups = []
            for index in range(parquet.num_row_groups):
                stats = parquet.metadata.row_group(index).column(column).statistics
                # Only numeric ID statistics can safely exclude a whole row group.
                if stats and stats.has_min_max and isinstance(stats.min, int) and isinstance(stats.max, int):
                    if not any(start <= stats.max and end >= stats.min for start, end in ranges):
                        continue
                groups.append(index)
        for batch in parquet.iter_batches(batch_size=2048, row_groups=groups):
            yield from batch.to_pylist()


def _spread_files(files, seed):
    """Visit shards across ID ranges instead of taking the lowest IDs first."""
    return sorted(files, key=lambda name: (_rank(name, seed), name))


def _official_file(out, name, digest, cache, token):
    local = out / name
    if local.exists():
        if storage.sha256_file(local) != digest:
            raise ValueError(f'Official file failed checksum: {local}')
        return local
    project_file = Path(__file__).resolve().parents[3] / 'data' / name
    if project_file.exists() and storage.sha256_file(project_file) == digest:
        shutil.copyfile(project_file, local)
    else:
        from huggingface_hub import hf_hub_download
        downloaded = hf_hub_download(repo_id=OFFICIAL_REPO, repo_type='dataset',
                                     filename=name, revision=OFFICIAL_REVISION,
                                     token=token, cache_dir=str(cache))
        shutil.copyfile(downloaded, local)
    if storage.sha256_file(local) != digest:
        local.unlink(missing_ok=True)
        raise ValueError(f'Official file failed checksum: {name}')
    return local


def _discard_download_cache(cache, out):
    if cache.exists():
        if cache.resolve().parent != out.resolve():
            raise RuntimeError('Refusing to remove a cache outside the snapshot directory')
        shutil.rmtree(cache)


def parse_id_range(value):
    try:
        start, end = map(int, value.split(':'))
        if not 0 <= start <= end:
            raise ValueError
        return start, end
    except ValueError as error:
        raise argparse.ArgumentTypeError('Expected inclusive START:END with 0 <= START <= END') from error


def _valid(row, official, language='vi'):
    try:
        doc_id = int(row['id'])
    except (KeyError, TypeError, ValueError):
        return None
    if doc_id not in official or official[doc_id] != row.get('url'):
        return None
    record, reason = normalise_row(row, 'hf_corpus')
    if reason or (language != 'all' and record['lang'] != language):
        return None
    return record


def build(args):
    from huggingface_hub import HfApi, HfFileSystem, get_token

    language = getattr(args, 'language', 'vi')
    ranges = getattr(args, 'id_range', [])
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = out / 'hf_cache'
    token = os.environ.get('HF_TOKEN') or get_token()
    if not token:
        raise RuntimeError('Authenticate with `hf auth login` or set HF_TOKEN to read the private dataset.')
    api = HfApi(token=token)
    manifest_path = out / 'source_manifest.json'
    previous = storage.read_json(manifest_path) if manifest_path.exists() else None
    requested = (previous['config']['revision'] if previous and args.revision == 'main'
                 else args.revision)
    pinned = api.dataset_info(args.repo, revision=requested).sha
    config = {'repo': args.repo, 'revision': pinned, 'limit': args.limit, 'seed': args.seed,
              'sample_mode': args.sample_mode, 'reader': 'hf_filesystem_ranges_v1',
              'max_shards': getattr(args, 'max_shards', 0),
              'language': language, 'id_ranges': [list(pair) for pair in ranges],
              'official_revision': OFFICIAL_REVISION,
              'official_links_sha256': LINKS_SHA256, 'official_queries_sha256': QUERIES_SHA256}
    target = out / f'input_{language}.parquet'
    if manifest_path.exists():
        old = storage.read_json(manifest_path)
        if old['config'] != config:
            raise ValueError('HF snapshot configuration changed. Choose a new output directory.')
        if target.exists() and storage.sha256_file(target) == old['input_sha256']:
            for name, digest in ((LINKS_NAME, LINKS_SHA256),
                                 (QUERIES_NAME, QUERIES_SHA256)):
                _official_file(out, name, digest, cache, token)
            _discard_download_cache(cache, out)
            return old
        raise ValueError('HF snapshot is incomplete or changed. Choose a new output directory.')
    links = _official_file(out, LINKS_NAME, LINKS_SHA256, cache, token)
    queries = _official_file(out, QUERIES_NAME, QUERIES_SHA256, cache, token)
    official = {int(row['id']): row['url'] for row in _rows(links)}
    if ranges:
        official = {doc_id: url for doc_id, url in official.items()
                    if any(start <= doc_id <= end for start, end in ranges)}
    if not official:
        raise ValueError('No official IDs match the requested intervals.')
    files = _spread_files([f for f in api.list_repo_files(repo_id=args.repo,
                           repo_type='dataset', revision=pinned)
                           if f.startswith('corpus/') and f.endswith('.parquet')], args.seed)
    if not files:
        raise ValueError('The team dataset contains no corpus/*.parquet shards.')
    fs = HfFileSystem(token=token)

    temporary = target.with_suffix('.partial.parquet')
    if args.sample_mode == 'bounded':
        shard_limit = getattr(args, 'max_shards', 0)
        selected_files = files[:shard_limit] if shard_limit else files
        seen = set()
        counts = {'files_available': len(files), 'files_read': 0,
                  'rows_scanned': 0, 'valid_unique': 0}
        try:
            with pq.ParquetWriter(temporary, CORPUS_SCHEMA, compression='zstd') as writer:
                batch = []
                for remote in selected_files:
                    counts['files_read'] += 1
                    for row in _remote_rows(fs, args.repo, pinned, remote, ranges):
                        counts['rows_scanned'] += 1
                        record = _valid(row, official, language)
                        if record is None or record['id'] in seen:
                            continue
                        seen.add(record['id'])
                        record['raw_path'] = ''
                        batch.append(record)
                        counts['valid_unique'] += 1
                        if len(batch) == 1024:
                            writer.write_table(pa.Table.from_pylist(batch, schema=CORPUS_SCHEMA))
                            batch.clear()
                        if args.limit and counts['valid_unique'] == args.limit:
                            break
                    print(f'Scan HF {counts["files_read"]}/{len(selected_files)}: {remote}; '
                          f'valid selected language={counts["valid_unique"]:,}', flush=True)
                    if args.limit and counts['valid_unique'] == args.limit:
                        break
                if batch:
                    writer.write_table(pa.Table.from_pylist(batch, schema=CORPUS_SCHEMA))
            if args.limit and counts['valid_unique'] < args.limit:
                raise ValueError(f'Only {counts["valid_unique"]:,} valid documents in the selected language/ranges '
                                 f'in {len(selected_files)} scanned shards; requested {args.limit:,}. '
                                 'Increase --max-shards or lower --limit.')
            if not seen:
                raise ValueError('No matching documents on HF; check language, ID ranges and crawl uploads.')
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        report = {'config': config, 'counts': counts, 'selected': len(seen),
                  'id_min': min(seen), 'id_max': max(seen),
                  'selected_per_range': {f'{a}:{b}': sum(a <= i <= b for i in seen) for a, b in ranges},
                  'input_sha256': storage.sha256_file(target), 'input': str(target),
                  'links': str(links), 'queries': str(queries)}
        storage.write_json(manifest_path, report)
        _discard_download_cache(cache, out)
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        return report

    # A stable hash sample spreads 500k IDs across all shards and does not favor low ID ranges.
    heap, seen = [], set()
    counts = {'files': len(files), 'rows_scanned': 0, 'valid_unique': 0}
    for position, remote in enumerate(files):
        for row in _remote_rows(fs, args.repo, pinned, remote, ranges):
            counts['rows_scanned'] += 1
            record = _valid(row, official, language)
            if record is None or record['id'] in seen:
                continue
            doc_id = record['id']
            seen.add(doc_id)
            counts['valid_unique'] += 1
            rank = _rank(doc_id, args.seed)
            item = (-rank, doc_id, position)
            if len(heap) < args.limit:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
        print(f'Scan HF {position + 1}/{len(files)}: {remote}; '
              f'valid selected language={counts["valid_unique"]:,}', flush=True)
    if len(heap) < args.limit:
        raise ValueError(f'HF contains only {len(heap):,} valid documents in the selected language/ranges; '
                         f'requested {args.limit:,}. Lower LIMIT explicitly.')
    selected = {doc_id: position for _, doc_id, position in heap}
    by_file = {}
    for doc_id, position in selected.items():
        by_file.setdefault(position, set()).add(doc_id)

    written = set()
    try:
        with pq.ParquetWriter(temporary, CORPUS_SCHEMA, compression='zstd') as writer:
            for position in sorted(by_file):
                remote = files[position]
                wanted = by_file[position]
                batch = []
                for row in _remote_rows(fs, args.repo, pinned, remote, ranges):
                    try:
                        doc_id = int(row.get('id'))
                    except (TypeError, ValueError):
                        continue
                    if doc_id not in wanted or doc_id in written:
                        continue
                    record = _valid(row, official, language)
                    if record is None:
                        raise ValueError(f'ID {doc_id} changed between HF passes at pinned revision.')
                    record['raw_path'] = ''  # HF corpus has no local raw checkpoint.
                    batch.append(record)
                    written.add(doc_id)
                    if len(batch) == 1024:
                        writer.write_table(pa.Table.from_pylist(batch, schema=CORPUS_SCHEMA))
                        batch.clear()
                if batch:
                    writer.write_table(pa.Table.from_pylist(batch, schema=CORPUS_SCHEMA))
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if len(written) != args.limit:
        temporary.unlink(missing_ok=True)
        raise ValueError(f'Only {len(written):,}/{args.limit:,} selected documents were written.')
    os.replace(temporary, target)
    report = {'config': config, 'counts': counts, 'selected': len(written),
              'input_sha256': storage.sha256_file(target), 'input': str(target),
              'links': str(out / LINKS_NAME), 'queries': str(out / QUERIES_NAME)}
    storage.write_json(manifest_path, report)
    _discard_download_cache(cache, out)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='AncientWings/AncientWings_R2AI_STAGE3_ds')
    parser.add_argument('--revision', default='main')
    parser.add_argument('--limit', type=int, default=500000)
    parser.add_argument('--seed', type=int, default=13)
    parser.add_argument('--language', choices=['vi', 'en', 'zh', 'all'], default='vi')
    parser.add_argument('--id-range', type=parse_id_range, action='append', default=[],
                        help='Inclusive START:END; repeat for multiple intervals.')
    parser.add_argument('--sample-mode', choices=['hash', 'bounded'], default='hash',
                        help='hash scans all shards twice; bounded stops after enough valid rows.')
    parser.add_argument('--max-shards', type=int, default=0,
                        help='Bounded mode cap on remote corpus shards; 0 allows all.')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.limit < 0 or (args.limit == 0 and args.sample_mode != 'bounded'):
        parser.error('--limit 0 (all matching records) requires bounded mode')
    if args.limit == 0 and args.max_shards:
        parser.error('--limit 0 requires --max-shards 0 to scan all shards')
    if args.max_shards < 0:
        parser.error('--max-shards must be nonnegative')
    build(args)


if __name__ == '__main__':
    main()
