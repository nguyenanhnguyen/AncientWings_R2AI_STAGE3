"""Freeze a Vietnamese corpus snapshot from the team's HF dataset for Kaggle."""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
from pathlib import Path

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


def _valid(row, official):
    try:
        doc_id = int(row['id'])
    except (KeyError, TypeError, ValueError):
        return None
    if official.get(doc_id) != row.get('url'):
        return None
    record, reason = normalise_row(row, 'hf_corpus')
    if reason or record['lang'] != 'vi':
        return None
    return record


def build(args):
    from huggingface_hub import HfApi, hf_hub_download

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = out / 'hf_cache'
    token = os.environ.get('HF_TOKEN')
    if not token:
        raise RuntimeError('HF_TOKEN is required to read the private team dataset.')
    api = HfApi(token=token)
    manifest_path = out / 'source_manifest.json'
    previous = storage.read_json(manifest_path) if manifest_path.exists() else None
    requested = (previous['config']['revision'] if previous and args.revision == 'main'
                 else args.revision)
    pinned = api.dataset_info(args.repo, revision=requested).sha
    config = {'repo': args.repo, 'revision': pinned, 'limit': args.limit, 'seed': args.seed,
              'official_revision': OFFICIAL_REVISION,
              'official_links_sha256': LINKS_SHA256, 'official_queries_sha256': QUERIES_SHA256}
    target = out / 'input_vi.parquet'
    if manifest_path.exists():
        old = storage.read_json(manifest_path)
        if old['config'] != config:
            raise ValueError('HF snapshot configuration changed. Choose a new output directory.')
        if target.exists() and storage.sha256_file(target) == old['input_sha256']:
            for name, digest in ((LINKS_NAME, LINKS_SHA256),
                                 (QUERIES_NAME, QUERIES_SHA256)):
                local = out / name
                if not local.exists() or storage.sha256_file(local) != digest:
                    import shutil
                    downloaded = hf_hub_download(repo_id=OFFICIAL_REPO, repo_type='dataset',
                                                 filename=name, revision=OFFICIAL_REVISION,
                                                 token=token, cache_dir=str(cache))
                    shutil.copyfile(downloaded, local)
                    if storage.sha256_file(local) != digest:
                        raise ValueError(f'Official file failed checksum: {name}')
            return old
        raise ValueError('HF snapshot is incomplete or changed. Choose a new output directory.')

    def download(repo, filename, revision):
        return hf_hub_download(repo_id=repo, repo_type='dataset', filename=filename,
                               revision=revision, token=token, cache_dir=str(cache))

    links = Path(download(OFFICIAL_REPO, LINKS_NAME, OFFICIAL_REVISION))
    queries = Path(download(OFFICIAL_REPO, QUERIES_NAME, OFFICIAL_REVISION))
    if storage.sha256_file(links) != LINKS_SHA256 or storage.sha256_file(queries) != QUERIES_SHA256:
        raise ValueError('Official links/query checksum differs from the pinned competition files.')
    official = {int(row['id']): row['url'] for row in _rows(links)}
    files = sorted(f for f in api.list_repo_files(repo_id=args.repo, repo_type='dataset',
                                                   revision=pinned)
                   if f.startswith('corpus/') and f.endswith('.parquet'))
    if not files:
        raise ValueError('The team dataset contains no corpus/*.parquet shards.')

    # A stable hash sample spreads 500k IDs across all shards and does not favor low ID ranges.
    heap, seen = [], set()
    counts = {'files': len(files), 'rows_scanned': 0, 'vi_valid_unique': 0}
    for position, remote in enumerate(files):
        path = download(args.repo, remote, pinned)
        for row in _rows(path):
            counts['rows_scanned'] += 1
            record = _valid(row, official)
            if record is None or record['id'] in seen:
                continue
            doc_id = record['id']
            seen.add(doc_id)
            counts['vi_valid_unique'] += 1
            rank = _rank(doc_id, args.seed)
            item = (-rank, doc_id, position)
            if len(heap) < args.limit:
                heapq.heappush(heap, item)
            elif item > heap[0]:
                heapq.heapreplace(heap, item)
        print(f'Scan HF {position + 1}/{len(files)}: {remote}; '
              f'valid vi={counts["vi_valid_unique"]:,}', flush=True)
    if len(heap) < args.limit:
        raise ValueError(f'HF contains only {len(heap):,} valid Vietnamese documents; '
                         f'requested {args.limit:,}. Lower LIMIT explicitly.')
    selected = {doc_id: position for _, doc_id, position in heap}
    by_file = {}
    for doc_id, position in selected.items():
        by_file.setdefault(position, set()).add(doc_id)

    temporary = target.with_suffix('.partial.parquet')
    written = set()
    with pq.ParquetWriter(temporary, CORPUS_SCHEMA, compression='zstd') as writer:
        for position in sorted(by_file):
            remote = files[position]
            path = download(args.repo, remote, pinned)
            wanted = by_file[position]
            batch = []
            for row in _rows(path):
                doc_id = row.get('id')
                if doc_id not in wanted or doc_id in written:
                    continue
                record = _valid(row, official)
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
    if len(written) != args.limit:
        temporary.unlink(missing_ok=True)
        raise ValueError(f'Only {len(written):,}/{args.limit:,} selected documents were written.')
    os.replace(temporary, target)
    # Keep exact official files next to the frozen input for submit validation.
    for source, destination in ((links, out / LINKS_NAME), (queries, out / QUERIES_NAME)):
        if not destination.exists():
            import shutil
            shutil.copyfile(source, destination)
    report = {'config': config, 'counts': counts, 'selected': len(written),
              'input_sha256': storage.sha256_file(target), 'input': str(target),
              'links': str(out / LINKS_NAME), 'queries': str(out / QUERIES_NAME)}
    storage.write_json(manifest_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', default='AncientWings/AncientWings_R2AI_STAGE3_ds')
    parser.add_argument('--revision', default='main')
    parser.add_argument('--limit', type=int, default=500000)
    parser.add_argument('--seed', type=int, default=13)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    build(args)


if __name__ == '__main__':
    main()
