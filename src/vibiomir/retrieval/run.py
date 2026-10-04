"""Block C CLI: retrieve and rerank candidates for every query.

All query variants are encoded and searched in one pass. The vector matrix is read from disk, so
searching per query would re-read the whole file 1.200 times; searching once for every query reads
it once. BM25 is per query because it only touches the postings of the query's own terms.

Scale limit, measured by nothing yet: the chunk table is loaded whole, so chunk text sits in RAM
for the length of the run. The embeddings are memmapped and the BM25 postings are flat arrays, but
roughly a kilobyte of Python object per chunk means a few million chunks will not fit on a 16GB
machine. Shard the corpus and merge the candidate files, or move the chunk table to a column read,
before pointing this at the full crawl.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from ..common import storage
from ..common.console import emit
from ..corpus.chunk import retrieval_text
from ..index import embedding as dense
from ..index.bm25 import BM25, tokenize
from . import hybrid
from .query import load_queries, load_translations, variants
from .rerank import load_reranker, rerank


def _check_pair(chunks_path, index_dir, names=('bm25_manifest.json', 'dense_manifest.json')):
    """Refuse an index built from a different chunk file: row i would mean a different chunk."""
    digest = storage.sha256_file(chunks_path)
    for name in names:
        path = Path(index_dir) / name
        if path.exists():
            recorded = storage.read_json(path).get('chunks_sha256')
            if recorded and recorded != digest:
                raise ValueError(f'{name} was built from a different chunks file; rebuild Block B.')


def run(args):
    chunks = storage.read_parquet(args.chunks)
    if not chunks:
        raise ValueError(f'No chunks in {args.chunks}')
    index_dir = Path(args.index)
    _check_pair(args.chunks, index_dir)
    queries = load_queries(args.queries)
    translations = load_translations(args.translations) if args.translations else None
    doc_ids = np.array([chunk['doc_id'] for chunk in chunks], dtype=np.int64)
    texts = [retrieval_text(chunk) for chunk in chunks]

    bm25 = None
    if not args.no_bm25:
        bm25_path = index_dir / 'bm25.npz'
        if not bm25_path.exists():
            raise FileNotFoundError(f'{bm25_path} missing; run scripts/index.py bm25 first.')
        bm25 = BM25.load(bm25_path)
        if bm25.n_docs != len(chunks):
            raise ValueError('BM25 index size does not match the chunks file.')

    variant_tables = {query['id']: variants(query, use_keyword=args.keyword_variant,
                                            translations=translations) for query in queries}
    variant_names, variant_rows = [], []
    for query in queries:
        for name, text in variant_tables[query['id']].items():
            variant_names.append((query['id'], name))
            variant_rows.append(text)

    dense_hits = {}
    if not args.no_dense:
        embeddings = index_dir / 'embeddings.npy'
        if not embeddings.exists():
            raise FileNotFoundError(f'{embeddings} missing; run scripts/index.py dense first.')
        manifest = storage.read_json(index_dir / 'dense_manifest.json')
        encoder = dense.load_encoder(args.encoder or manifest['encoder'], device=args.device,
                                     fp16=not args.fp32)
        started = time.monotonic()
        vectors = encoder.encode(variant_rows, kind='query', batch_size=args.batch_size)
        faiss_index = index_dir / 'faiss.index'
        search = hybrid.make_dense_search(embeddings,
                                          faiss_index if (args.faiss and faiss_index.exists())
                                          else None)
        rows, scores = search(vectors, args.top_k)
        emit(f'dense: {len(variant_rows)} query vectors trong '
             f'{time.monotonic() - started:.1f}s')
        for position, (query_id, name) in enumerate(variant_names):
            # Grouped by query id so the per-query loop below is a lookup, not a scan of
            # every variant of every query.
            dense_hits.setdefault(query_id, {})[name] = (
                np.asarray(rows[position]).tolist(), np.asarray(scores[position]))

    reranker = load_reranker(args.reranker, device=args.device, fp16=not args.fp32)
    weights = json.loads(args.weights) if args.weights else {}
    results = []
    started = time.monotonic()
    for position, query in enumerate(queries, start=1):
        rankings = {}
        if bm25 is not None:
            for name, text in variant_tables[query['id']].items():
                hit_rows, hit_scores = bm25.top_k(tokenize(text), args.top_k)
                if hit_rows:
                    rankings[f'bm25:{name}'] = (hit_rows, hit_scores)
        for name, hit in dense_hits.get(query['id'], {}).items():
            rankings[f'dense:{name}'] = hit
        fused = hybrid.rrf_fuse(rankings, weights=weights, top_k=args.fuse_k)
        scored = rerank(query['query'], fused, reranker, lambda row: texts[row],
                        batch_size=args.rerank_batch, limit=args.rerank_k)
        kept = scored[:args.keep]
        documents = hybrid.aggregate_documents(
            [(row, fused_score, channels) for row, fused_score, channels, _ce in kept],
            doc_ids, top_chunks_per_doc=args.doc_chunks)
        results.append({
            'query_id': query['id'],
            'query': query['query'],
            'candidates': [{'chunk_id': chunks[row]['chunk_id'], 'doc_id': int(doc_ids[row]),
                            'chunk_order': chunks[row]['chunk_order'],
                            'rrf_score': round(float(fused_score), 6),
                            'ce_score': None if ce is None else round(float(ce), 6),
                            'channels': channels}
                           for row, fused_score, channels, ce in kept],
            'documents': [{'doc_id': doc_id, 'score': round(score, 6)}
                          for doc_id, score, _rows in documents],
        })
        if position % 100 == 0 or position == len(queries):
            elapsed = time.monotonic() - started
            emit(f'rerank {position}/{len(queries)}  {elapsed / position:.2f}s/query')

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'candidates.jsonl'
    storage.write_jsonl(path, results)
    summary = {
        'queries': len(results),
        'chunks_searched': len(chunks),
        'channels': sorted({name.split(':')[0] for row in results
                            for item in row['candidates'] for name in item['channels']}),
        'encoder': None if args.no_dense else (args.encoder or
                                               storage.read_json(index_dir / 'dense_manifest.json')['encoder']),
        'reranker': args.reranker,
        'top_k': args.top_k, 'fuse_k': args.fuse_k, 'rerank_k': args.rerank_k, 'keep': args.keep,
        'weights': weights,
        'candidates_median': int(np.median([len(row['candidates']) for row in results])),
        'chunks_file': str(args.chunks), 'chunks_sha256': storage.sha256_file(args.chunks),
    }
    storage.write_manifest(out / 'retrieval_manifest.json', summary, files=[path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--chunks', default='work/chunks/chunks.parquet')
    parser.add_argument('--index', default='work/index')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--out', default='work/retrieval')
    parser.add_argument('--top-k', type=int, default=200, help='Per channel, before fusion.')
    parser.add_argument('--fuse-k', type=int, default=200, help='Kept after RRF.')
    parser.add_argument('--rerank-k', type=int, default=100, help='Scored by the cross-encoder.')
    parser.add_argument('--keep', type=int, default=50, help='Written per query.')
    parser.add_argument('--doc-chunks', type=int, default=3,
                        help='Chunks summed into a document score.')
    parser.add_argument('--encoder', default=None, help='Default: the one recorded in the index.')
    parser.add_argument('--reranker', default='bge-reranker-v2-m3')
    parser.add_argument('--weights', default=None,
                        help='JSON of RRF weights, by channel or family, e.g. \'{"bm25":0.7}\'')
    parser.add_argument('--keyword-variant', action='store_true',
                        help='Also search a filler-stripped query with BM25.')
    parser.add_argument('--translations', default=None, help='JSONL of prepared query translations.')
    parser.add_argument('--no-bm25', action='store_true')
    parser.add_argument('--no-dense', action='store_true')
    parser.add_argument('--faiss', action='store_true', help='Use faiss.index when present.')
    parser.add_argument('--device', default=None)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--rerank-batch', type=int, default=16)
    parser.add_argument('--fp32', action='store_true')
    args = parser.parse_args()
    if args.no_bm25 and args.no_dense:
        parser.error('At least one of BM25 or dense retrieval must stay enabled.')
    run(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
