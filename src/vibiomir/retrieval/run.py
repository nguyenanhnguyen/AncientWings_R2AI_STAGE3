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
from ..common.cache import Cache, cache_key
from ..common.runtime import model_info, release_model, Progress, environment
from ..corpus.chunk import retrieval_text
from ..index import embedding as dense
from ..index.bm25 import BM25, tokenize
from . import hybrid
from .query import load_queries, load_translations, variants
from .rerank import load_reranker, INSTRUCTION


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
    started_all = time.monotonic()
    chunks = storage.read_parquet(args.chunks)
    if not chunks:
        raise ValueError(f'No chunks in {args.chunks}')
    index_dir = Path(args.index)
    _check_pair(args.chunks, index_dir)
    queries = load_queries(args.queries)
    translations = load_translations(args.translations, queries) if args.translations else None
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
            if name == 'keyword':
                continue  # The keyword variant is lexical-only.
            variant_names.append((query['id'], name))
            variant_rows.append(text)

    dense_hits = {}
    dense_models = []
    dense_dirs = [] if args.no_dense else [index_dir] + [Path(p) for p in getattr(args, 'extra_index', [])]
    if len({p.resolve() for p in dense_dirs}) != len(dense_dirs):
        raise ValueError('Dense index directories must be unique.')
    for dense_dir in dense_dirs:
        _check_pair(args.chunks, dense_dir, names=('dense_manifest.json',))
        embeddings = dense_dir / 'embeddings.npy'
        if not embeddings.exists():
            raise FileNotFoundError(f'{embeddings} missing; run scripts/index.py dense first.')
        manifest = storage.read_json(dense_dir / 'dense_manifest.json')
        matrix = np.load(embeddings, mmap_mode='r')
        if matrix.shape[0] != len(chunks):
            raise ValueError('Dense index size does not match the chunks file.')
        del matrix
        if args.encoder and dense_dir == index_dir and args.encoder != manifest['encoder']:
            # Query and chunk vectors from different models live in different spaces; the
            # similarity would be noise, not a weaker signal.
            raise ValueError(f"The index was encoded with {manifest['encoder']!r}, not "
                             f'{args.encoder!r}; rebuild it or drop --encoder.')
        recorded = manifest.get('model', {})
        encoder = dense.load_encoder(manifest['encoder'], device=args.device, fp16=not args.fp32,
                                     max_length=recorded.get('max_length'),
                                     revision=recorded.get('revision'),
                                     quantize=recorded.get('config', {}).get('quantize', 'none'))
        dense_models.append(model_info(encoder))
        started = time.monotonic()
        vectors = encoder.encode(variant_rows, kind='query', batch_size=args.batch_size)
        release_model(encoder)
        del encoder
        faiss_index = dense_dir / 'faiss.index'
        if args.faiss and faiss_index.exists():
            search = hybrid.make_dense_search(embeddings, faiss_index)
            rows, scores = search(vectors, args.top_k)
        else:
            rows, scores = dense.search(embeddings, vectors, args.top_k,
                                        device=getattr(args, 'search_device', 'cpu'),
                                        block=getattr(args, 'search_block', 16384),
                                        query_block=getattr(args, 'query_block', 128))
        emit(f'dense: {len(variant_rows)} query vectors trong '
             f'{time.monotonic() - started:.1f}s')
        for position, (query_id, name) in enumerate(variant_names):
            # Grouped by query id so the per-query loop below is a lookup, not a scan of
            # every variant of every query.
            channel = f"{manifest['encoder']}:{name}" if len(dense_dirs) > 1 else name
            dense_hits.setdefault(query_id, {})[channel] = (
                np.asarray(rows[position]).tolist(), np.asarray(scores[position]))

    weights = json.loads(args.weights) if args.weights else {}
    fused_queries = []
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
        cap = getattr(args, 'candidate_per_doc', 0)
        if cap:
            counts, diversified = {}, []
            for candidate in fused:
                doc = int(doc_ids[candidate[0]])
                if counts.get(doc, 0) < cap:
                    diversified.append(candidate)
                    counts[doc] = counts.get(doc, 0) + 1
            fused = diversified
        fused_queries.append(fused[:args.rerank_k])

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = [args.reranker] + getattr(args, 'extra_reranker', [])
    rerank_query = getattr(args, 'rerank_query', 'original')
    if len(set(names)) != len(names) or ('identity' in names and len(names) > 1):
        raise ValueError('Rerankers must be unique; identity cannot be ensembled.')
    all_scores = [[] for _ in queries]
    reranker_models = []
    with Cache(out / 'scores.sqlite') as cache:
        for name in names:
            scorer = load_reranker(name, device=args.device, fp16=not args.fp32,
                                   max_length=getattr(args, 'rerank_max_length', None),
                                   revision=(getattr(args, 'reranker_revision', None)
                                             if name == args.reranker else None),
                                   quantize=getattr(args, 'reranker_quantize', 'none'))
            info = model_info(scorer)
            reranker_models.append(info)
            progress = Progress(f'rerank {name}')
            try:
                for qi, (query, fused) in enumerate(zip(queries, fused_queries)):
                    passages = [texts[row] for row, _, _ in fused]
                    rerank_text = query['query']
                    if rerank_query != 'original':
                        rerank_text = variant_tables[query['id']].get(rerank_query) or query['query']
                    keys = [cache_key({'model': info, 'version': 3,
                                       'query': rerank_text, 'text': text,
                                       'instruction': INSTRUCTION}) for text in passages]
                    values = [cache.get(key) for key in keys] if name != 'identity' else [None]*len(keys)
                    missing = [i for i, value in enumerate(values) if value is None]
                    if missing:
                        fresh = scorer.score(rerank_text, [passages[i] for i in missing],
                                             batch_size=args.rerank_batch)
                        for i, value in zip(missing, fresh):
                            values[i] = float(value)
                        if name != 'identity':
                            cache.put_many([(keys[i], values[i]) for i in missing])
                    all_scores[qi].append(values)
                    progress(qi+1, len(queries))
            finally:
                release_model(scorer)
                del scorer

    results = []
    for qi, (query, fused) in enumerate(zip(queries, fused_queries)):
        # A heuristic ensemble, not a calibrated probability; keep component scores for ablation.
        mean_scores = np.mean(np.asarray(all_scores[qi], dtype=np.float32), axis=0)
        order = np.argsort(-mean_scores, kind='stable')
        scored = [(*fused[i], float(mean_scores[i])) for i in order]
        kept = scored[:args.keep]
        documents = hybrid.aggregate_documents(
            [(row, fused_score if ce is None else ce) for row, fused_score, _channels, ce in kept],
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
        score_lookup = {int(fused[i][0]): {name: float(all_scores[qi][j][i])
                                           for j, name in enumerate(names)} for i in order}
        for candidate, (row, *_rest) in zip(results[-1]['candidates'], kept):
            candidate['model_scores'] = score_lookup[row]

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
        'rerank_query': rerank_query,
        'dense_models': dense_models, 'reranker_models': reranker_models,
        'score_method': 'mean sigmoid/yes-no scores; uncalibrated',
        'environment': environment(), 'retrieval_seconds': time.monotonic() - started_all,
        'translations_sha256': storage.sha256_file(args.translations) if args.translations else None,
        'queries_sha256': storage.sha256_file(args.queries),
        'candidate_per_doc': getattr(args, 'candidate_per_doc', 0),
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
    parser.add_argument('--extra-index', nargs='*', default=[], help='Additional dense index directories.')
    parser.add_argument('--extra-reranker', nargs='*', default=[], help='Sequential score ensemble.')
    parser.add_argument('--candidate-per-doc', type=int, default=0,
                        help='Cap chunks per document before reranking; 0 disables.')
    parser.add_argument('--rerank-max-length', type=int, default=None)
    parser.add_argument('--search-device', default='cpu', choices=['cpu', 'cuda'])
    parser.add_argument('--search-block', type=int, default=16384)
    parser.add_argument('--query-block', type=int, default=128)
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
    parser.add_argument('--reranker-revision', default=None,
                        help='Pinned Hugging Face commit for the primary reranker.')
    parser.add_argument('--reranker-quantize', choices=['none', '4bit'], default='none')
    parser.add_argument('--weights', default=None,
                        help='JSON of RRF weights, by channel or family, e.g. \'{"bm25":0.7}\'')
    parser.add_argument('--keyword-variant', action='store_true',
                        help='Also search a filler-stripped query with BM25.')
    parser.add_argument('--translations', default=None, help='JSONL of prepared query translations.')
    parser.add_argument('--rerank-query', default='original', choices=['original', 'translated_zh', 'translated_en'],
                        help='Query text given to the reranker; a translated one needs --translations.')
    parser.add_argument('--no-bm25', action='store_true')
    parser.add_argument('--no-dense', action='store_true')
    parser.add_argument('--faiss', action='store_true', help='Use faiss.index when present.')
    parser.add_argument('--device', default=None)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--rerank-batch', type=int, default=16)
    parser.add_argument('--fp32', action='store_true')
    args = parser.parse_args()
    if min(args.top_k, args.fuse_k, args.rerank_k, args.keep, args.batch_size,
           args.rerank_batch, args.search_block, args.query_block, args.doc_chunks) < 1:
        parser.error('Counts, batches and search blocks must be positive.')
    if args.candidate_per_doc < 0:
        parser.error('--candidate-per-doc must be nonnegative.')
    if args.no_bm25 and args.no_dense:
        parser.error('At least one of BM25 or dense retrieval must stay enabled.')
    if args.keep > args.rerank_k:
        # Candidates past rerank_k have no reranker score; mixing them with scored ones would
        # compare a probability against an RRF score in Block D.
        parser.error('--keep cannot exceed --rerank-k')
    if args.rerank_query != 'original' and not args.translations:
        parser.error('--rerank-query with a translation needs --translations.')
    if args.rerank_k > args.fuse_k:
        parser.error('--rerank-k cannot exceed --fuse-k')
    run(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
