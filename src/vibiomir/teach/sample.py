"""T1: pick the chunks the teacher writes questions for.

One chunk per document at most, so the questions cover many topics instead of many angles on one
article. Domains are capped by the square root of their size: thanhnien.vn alone is a third of the
current corpus and would otherwise dominate the training questions. Chunks are assigned to Kaggle
shards and to train/dev by a stable hash, so re-running with more chunks never moves a seed.
"""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import zlib

from ..common import storage
from ..common.console import emit
from ..corpus.chunk import retrieval_text
from .models import STYLES
from .store import shard_of


def _letters_ratio(text):
    return sum(ch.isalpha() for ch in text) / max(1, len(text))


def select(chunks, target, min_tokens=120, languages=None, seed=13):
    """-> seed rows. Deterministic for the same chunks, target and seed."""
    eligible = defaultdict(list)
    for chunk in chunks:
        if chunk['n_tokens'] < min_tokens or _letters_ratio(chunk['text']) < 0.6:
            continue
        if languages and chunk['lang'] not in languages:
            continue
        eligible[chunk['doc_id']].append(chunk)
    rng = random.Random(seed)
    per_doc = []
    for doc_id in sorted(eligible):
        options = eligible[doc_id]
        per_doc.append(options[rng.randrange(len(options))])
    by_domain = defaultdict(list)
    for chunk in per_doc:
        by_domain[chunk.get('domain') or ''].append(chunk)
    weights = {domain: math.sqrt(len(items)) for domain, items in by_domain.items()}
    total = sum(weights.values()) or 1.0
    picked = []
    for domain in sorted(by_domain):
        items = by_domain[domain]
        rng.shuffle(items)
        picked.extend(items[:max(1, round(target * weights[domain] / total))])
    if len(picked) < target:
        # Small domains could not fill their share; top up from the leftovers.
        chosen = {chunk['chunk_id'] for chunk in picked}
        rest = [chunk for chunk in per_doc if chunk['chunk_id'] not in chosen]
        rng.shuffle(rest)
        picked.extend(rest[:target - len(picked)])
    picked.sort(key=lambda chunk: chunk['chunk_id'])
    return picked[:target]


def build(args):
    chunks = storage.read_parquet(args.chunks, columns=['chunk_id', 'doc_id', 'text', 'title',
                                                        'lang', 'n_tokens', 'domain'])
    picked = select(chunks, args.target, args.min_tokens, args.languages, args.seed)
    rows = []
    for chunk in picked:
        bucket = zlib.crc32(chunk['chunk_id'].encode('utf-8')) % 1000
        rows.append({'chunk_id': chunk['chunk_id'], 'doc_id': int(chunk['doc_id']),
                     'domain': chunk.get('domain'), 'lang': chunk['lang'],
                     'passage': retrieval_text(chunk),
                     'style': STYLES[zlib.crc32(chunk['chunk_id'].encode()) % len(STYLES)],
                     'split': 'dev' if bucket < args.dev_permille else 'train',
                     'shard': shard_of(chunk['chunk_id'], args.shards)})
    out = Path(args.out)
    target = out / 'seeds.jsonl'
    storage.write_jsonl(target, rows)
    domains = defaultdict(int)
    for row in rows:
        domains[row['domain']] += 1
    summary = {'seeds': len(rows), 'shards': args.shards,
               'per_shard': [sum(row['shard'] == k for row in rows) for k in range(args.shards)],
               'dev': sum(row['split'] == 'dev' for row in rows), 'domains': dict(domains),
               'chunks_sha256': storage.sha256_file(args.chunks),
               'options': {k: v for k, v in vars(args).items() if not callable(v)}}
    storage.write_manifest(out / 'seeds_manifest.json', summary, files=[target])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.hub_repo:
        from .store import push_result

        push_result(args.hub_repo, [target, out / 'seeds_manifest.json'], 'inputs')
    return summary


def add_arguments(parser):
    parser.add_argument('--chunks', required=True)
    parser.add_argument('--out', default='work/teach')
    parser.add_argument('--target', type=int, default=30000)
    parser.add_argument('--shards', type=int, default=4, help='One per Kaggle account.')
    parser.add_argument('--min-tokens', type=int, default=120)
    parser.add_argument('--languages', nargs='*', default=None)
    parser.add_argument('--dev-permille', type=int, default=50, help='50 = 5%% held out.')
    parser.add_argument('--seed', type=int, default=13)
    parser.add_argument('--hub-repo', default=None, help='Push seeds.jsonl back to inputs/ when set.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    build(parser.parse_args(argv))
