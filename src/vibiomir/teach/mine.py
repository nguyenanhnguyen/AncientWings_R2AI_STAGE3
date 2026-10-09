"""T3: find hard negatives for every accepted synthetic query with the current retriever.

Runs Block B's indexes as they are (BM25 plus the dense index), fuses with RRF, and keeps:
    hard   the top candidates that are not the seed's own document: what the student must learn
           to push down, and also where false negatives hide, which is why T4 re-judges them
    tail   a few random candidates from deeper ranks, so the student also sees easy contrasts

Chunks of the seed's own document are left out entirely: overlapping chunks of the same article
often contain the same answer, and calling them negatives would teach the wrong thing.

The rank of the seed chunk in the fused list is recorded, so this step doubles as an offline
benchmark: recall@k of today's retriever on questions whose answer chunk is known.
"""
import argparse
import json
from pathlib import Path
import random

import numpy as np

from ..common import storage
from ..common.console import emit
from ..common.runtime import release_model
from ..index import embedding as dense
from ..index.bm25 import BM25, tokenize
from ..retrieval import hybrid
from .store import read_stage, shard_of


def accepted_queries(out):
    rows = [row for row in read_stage(out, 'generated') if row.get('error') is None]
    unique = {row['chunk_id']: row for row in rows}
    return [unique[key] for key in sorted(unique)]


def recall_report(ranks, cutoffs=(1, 10, 50, 100, 200)):
    total = max(1, len(ranks))
    report = {f'recall@{k}': round(sum(r is not None and r < k for r in ranks) / total, 4)
              for k in cutoffs}
    report['mrr@10'] = round(sum(1.0 / (r + 1) for r in ranks if r is not None and r < 10)
                             / total, 4)
    return report


def build(args):
    queries = accepted_queries(args.teach)
    if not queries:
        raise ValueError(f'No accepted queries under {args.teach}/generated; run T2 first.')
    chunks = storage.read_parquet(args.chunks, columns=['chunk_id', 'doc_id'])
    row_of = {chunk['chunk_id']: row for row, chunk in enumerate(chunks)}
    doc_ids = np.array([chunk['doc_id'] for chunk in chunks], dtype=np.int64)
    queries = [query for query in queries if query['chunk_id'] in row_of]
    emit(f'{len(queries)} query tổng hợp có chunk gốc trong {args.chunks}')

    rankings = [dict() for _ in queries]
    index = Path(args.index)
    if (index / 'bm25.npz').exists():
        bm25 = BM25.load(index / 'bm25.npz')
        for position, query in enumerate(queries):
            hit_rows, hit_scores = bm25.top_k(tokenize(query['query']), args.top_k)
            rankings[position]['bm25'] = (hit_rows, hit_scores)
        del bm25
    for dense_dir in [index, *map(Path, args.extra_index)]:
        if not (dense_dir / 'dense_manifest.json').exists():
            continue
        manifest = storage.read_json(dense_dir / 'dense_manifest.json')
        recorded = manifest.get('model', {})
        encoder = dense.load_encoder(manifest['encoder'], device=args.device,
                                     max_length=recorded.get('max_length'),
                                     revision=recorded.get('revision'))
        vectors = encoder.encode([query['query'] for query in queries], kind='query',
                                 batch_size=args.batch_size)
        release_model(encoder)
        rows, scores = dense.search(dense_dir / 'embeddings.npy', vectors, args.top_k,
                                    device=args.search_device)
        for position in range(len(queries)):
            rankings[position][f"dense:{manifest['encoder']}"] = (rows[position].tolist(),
                                                                  scores[position])
    if not any(rankings):
        raise ValueError(f'No bm25.npz or dense index under {index}.')

    rng = random.Random(args.seed)
    groups, ranks = [], []
    channel_ranks = {}
    for query, ranking in zip(queries, rankings):
        positive_row = row_of[query['chunk_id']]
        fused = hybrid.rrf_fuse(ranking, top_k=args.top_k)
        order = [row for row, _score, _channels in fused]
        ranks.append(order.index(positive_row) if positive_row in order else None)
        for name, (hit_rows, _scores) in ranking.items():
            hit_rows = list(hit_rows)
            channel_ranks.setdefault(name, []).append(
                hit_rows.index(positive_row) if positive_row in hit_rows else None)
        own_doc = int(doc_ids[positive_row])
        others = [row for row in order if int(doc_ids[row]) != own_doc]
        hard = others[:args.hard]
        deep = others[max(args.hard, args.tail_from):]
        tail = rng.sample(deep, min(args.tail, len(deep)))
        qid = f"q:{query['chunk_id']}"
        groups.append({'qid': qid, 'query': query['query'], 'query_en': query.get('query_en'),
                       'query_zh': query.get('query_zh'), 'evidence': query.get('evidence'),
                       'positive': query['chunk_id'], 'positive_rank': ranks[-1],
                       'negatives': [chunks[row]['chunk_id'] for row in hard + tail],
                       'split': query['split'], 'shard': shard_of(qid, args.shards)})
    out = Path(args.teach)
    target = out / 'groups.jsonl'
    storage.write_jsonl(target, groups)
    summary = {'groups': len(groups), 'shards': args.shards,
               'negatives_per_group': args.hard + args.tail,
               'retriever_on_synthetic_queries': {
                   'fused': recall_report(ranks),
                   **{name: recall_report(value) for name, value in channel_ranks.items()},
                   'dev_only_fused': recall_report(
                       [rank for rank, group in zip(ranks, groups) if group['split'] == 'dev'])},
               'chunks_sha256': storage.sha256_file(args.chunks),
               'options': {k: v for k, v in vars(args).items() if not callable(v)}}
    storage.write_manifest(out / 'groups_manifest.json', summary, files=[target])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.hub_repo:
        from .store import push_result

        push_result(args.hub_repo, [target, out / 'groups_manifest.json'], 'teach')
    return summary


def add_arguments(parser):
    parser.add_argument('--teach', default='work/teach', help='Holds generated/ from T2.')
    parser.add_argument('--chunks', required=True)
    parser.add_argument('--index', required=True, help='Directory with bm25.npz and/or a dense index.')
    parser.add_argument('--extra-index', nargs='*', default=[])
    parser.add_argument('--shards', type=int, default=4)
    parser.add_argument('--top-k', type=int, default=200)
    parser.add_argument('--hard', type=int, default=8)
    parser.add_argument('--tail', type=int, default=3)
    parser.add_argument('--tail-from', type=int, default=30)
    parser.add_argument('--device', default=None)
    parser.add_argument('--search-device', default='cpu', choices=['cpu', 'cuda'])
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--seed', type=int, default=13)
    parser.add_argument('--hub-repo', default=None, help='Push groups.jsonl back to teach/ when set.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    build(parser.parse_args(argv))
