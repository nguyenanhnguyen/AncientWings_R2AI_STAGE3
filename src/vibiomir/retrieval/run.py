"""Block C CLI: retrieve and rerank candidates for every query.

The same command serves both cascade stages: over document cards (identity reranker, the output
is each query's ranked documents) and over the chunks of those documents (`--doc-candidates` adds
the card ranking as a fusion channel, one reranker scores the fused list). With
`--match-language` the reranker reads a Chinese chunk next to the Chinese translation of the
question, turning the costliest step into a same-language judgement. `--shard i --shards n` splits
the queries so two GPUs can work at once; Block D accepts the shard files together.

All query variants are encoded and searched in one pass. The vector matrix is read from disk, so
searching per query would re-read the whole file 1.200 times; searching once for every query reads
it once. BM25 is per query because it only touches the postings of the query's own terms.

By default the chunk table is loaded whole, so chunk text sits in RAM
for the length of the run. The embeddings are memmapped and the BM25 postings are flat arrays, but
roughly a kilobyte of Python object per chunk means a few million chunks will not fit on a 16GB
machine. Shard the corpus and merge the candidate files, or move the chunk table to a column read,
before pointing this at the full crawl.

--disk-text loads metadata only and fetches candidate texts from a derived SQLite sidecar.
BM25 postings and FAISS IVFFlat vectors still consume RAM; this is not a fully disk-based index.
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


def _card_rankings(path, doc_ids, chunk_orders, top_k):
    """{query id: (rows, scores)}: chunks of each query's card-ranked documents, in that order.

    The document ranking from the card stage becomes one more RRF channel at chunk level, so a
    document the cards placed first lifts all of its chunks, the way a strong title match should.
    """
    order = np.lexsort((chunk_orders, doc_ids))
    rows_by_doc = {}
    for row in order.tolist():
        rows_by_doc.setdefault(int(doc_ids[row]), []).append(row)
    rankings = {}
    for record in storage.iter_jsonl(path):
        rows = []
        for doc_id in record['doc_ids']:
            rows.extend(rows_by_doc.get(int(doc_id), ()))
            if len(rows) >= top_k:
                break
        rows = rows[:top_k]
        rankings[int(record['query_id'])] = (rows, np.linspace(1.0, 0.0, num=len(rows),
                                                               dtype=np.float32))
    return rankings


def _shard(queries, args):
    shards, shard = getattr(args, 'shards', 1) or 1, getattr(args, 'shard', 0) or 0
    if not 0 <= shard < shards:
        raise ValueError('--shard must be in [0, --shards).')
    return [query for position, query in enumerate(queries) if position % shards == shard]


def _rerank_query(query, table, language, match):
    """The wording the reranker reads for a chunk: the translation in the chunk's language when
    one exists and matching is on, else the original Vietnamese question."""
    if match and language in ('zh', 'en'):
        return table.get(f'translated_{language}') or query['query']
    return query['query']


def run(args):
    started_all = time.monotonic()
    match = getattr(args, 'match_language', False)
    disk_text = getattr(args, 'disk_text', False)
    if disk_text and getattr(args, 'feedback_candidates', None):
        raise ValueError('--disk-text currently cannot be combined with feedback.')
    chunks = storage.read_parquet(args.chunks, columns=['chunk_id', 'doc_id', 'chunk_order', 'lang']
                                  if disk_text else None)
    if not chunks:
        raise ValueError(f'No chunks in {args.chunks}')
    index_dir = Path(args.index)
    _check_pair(args.chunks, index_dir)
    all_queries = load_queries(args.queries)
    queries = _shard(all_queries, args)
    translations = load_translations(args.translations, all_queries) if args.translations else None
    doc_ids = np.array([chunk['doc_id'] for chunk in chunks], dtype=np.int64)
    if disk_text:
        from .passages import PassageStore
        texts = PassageStore(args.chunks, index_dir / 'passages.sqlite',
                             storage.sha256_file(args.chunks))
    else:
        texts = [retrieval_text(chunk) for chunk in chunks]
    languages = [chunk.get('lang') or 'unknown' for chunk in chunks]
    card_hits = {}
    if getattr(args, 'doc_candidates', None):
        card_hits = _card_rankings(args.doc_candidates, doc_ids,
                                   np.array([chunk['chunk_order'] for chunk in chunks]),
                                   args.top_k)

    bm25 = None
    if not args.no_bm25:
        bm25_path = index_dir / 'bm25.npz'
        if not bm25_path.exists():
            raise FileNotFoundError(f'{bm25_path} missing; run `vibiomir.py index bm25` first.')
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
    search_reports = []
    dense_models = []
    dense_dirs = [] if args.no_dense else [index_dir] + [Path(p) for p in getattr(args, 'extra_index', [])]
    if len({p.resolve() for p in dense_dirs}) != len(dense_dirs):
        raise ValueError('Dense index directories must be unique.')
    for dense_dir in dense_dirs:
        _check_pair(args.chunks, dense_dir, names=('dense_manifest.json',))
        embeddings = dense_dir / 'embeddings.npy'
        if not embeddings.exists():
            raise FileNotFoundError(f'{embeddings} missing; run `vibiomir.py index dense` first.')
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
                                     revision=recorded.get('revision'))
        dense_models.append(model_info(encoder))
        started = time.monotonic()
        vectors = encoder.encode(variant_rows, kind='query', batch_size=args.batch_size)
        release_model(encoder)
        del encoder
        faiss_index = dense_dir / 'faiss.index'
        search_started = time.monotonic()
        audit = None
        if args.faiss:
            ann_manifest = dense_dir / 'ann_manifest.json'
            if not faiss_index.exists() or not ann_manifest.exists():
                raise FileNotFoundError(f'Run `vibiomir.py ann --index {dense_dir}` first.')
            ann = storage.read_json(ann_manifest)
            if (ann['chunks_sha256'] != storage.sha256_file(args.chunks)
                    or ann['embeddings_sha256'] != storage.sha256_file(embeddings)
                    or ann['files']['faiss.index']['sha256'] != storage.sha256_file(faiss_index)):
                raise ValueError('ANN index does not match embeddings/chunks; rebuild ANN.')
            search = hybrid.make_dense_search(embeddings, faiss_index,
                                               nprobe=getattr(args, 'nprobe', 32))
            rows, scores = search(vectors, args.top_k)
        else:
            rows, scores = dense.search(embeddings, vectors, args.top_k,
                                        device=getattr(args, 'search_device', 'cpu'),
                                        block=getattr(args, 'search_block', 16384),
                                        query_block=getattr(args, 'query_block', 128))
        search_seconds = time.monotonic() - search_started
        sample_count = min(getattr(args, 'ann_audit', 0), len(vectors)) if args.faiss else 0
        if sample_count:
            sample = np.linspace(0, len(vectors) - 1, sample_count, dtype=int)
            exact_rows, _ = dense.search(embeddings, vectors[sample], args.top_k,
                                         device=getattr(args, 'search_device', 'cpu'))
            audit = float(np.mean([len(set(rows[i]) & set(gold)) / max(len(gold), 1)
                                   for i, gold in zip(sample, exact_rows)]))
        search_reports.append({'encoder': manifest['encoder'], 'backend': 'faiss' if args.faiss else 'exact',
                               'search_seconds': search_seconds, 'audit_variants': sample_count,
                               'overlap_with_exact_at_k': audit,
                               'nprobe': min(getattr(args, 'nprobe', 32), ann['lists']) if args.faiss else None})
        if args.faiss:
            del search  # release FAISS index before another encoder/reranker loads
        emit(f'dense: {len(variant_rows)} query vectors trong '
             f'{time.monotonic() - started:.1f}s')
        for position, (query_id, name) in enumerate(variant_names):
            # Grouped by query id so the per-query loop below is a lookup, not a scan of
            # every variant of every query.
            channel = f"{manifest['encoder']}:{name}" if len(dense_dirs) > 1 else name
            dense_hits.setdefault(query_id, {})[channel] = (
                np.asarray(rows[position]).tolist(), np.asarray(scores[position]))

    weights = json.loads(args.weights) if args.weights else {}
    feedback = {}
    feedback_path = getattr(args, 'feedback_candidates', None)
    if feedback_path:
        if bm25 is None:
            raise ValueError('Lexical feedback requires BM25.')
        manifest = storage.read_json(Path(feedback_path).with_name('retrieval_manifest.json'))
        if (manifest.get('chunks_sha256') != storage.sha256_file(args.chunks)
                or manifest.get('queries_sha256') != storage.sha256_file(args.queries)):
            raise ValueError('Feedback must use the same chunks and queries.')
        feedback = {int(r['query_id']): r for r in storage.iter_jsonl(feedback_path)}
        if any(q['id'] not in feedback for q in queries):
            raise ValueError('Feedback candidates are missing queries.')
    chunks_by_id = {str(c['chunk_id']): c for c in chunks} if feedback else {}
    feedback_trace = []
    fused_queries = []
    candidate_trace = []
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
        if card_hits.get(query['id']) and card_hits[query['id']][0]:
            rankings['card'] = card_hits[query['id']]
        if feedback:
            from .feedback import expand
            original = tokenize(query['query'])
            for name, text in variant_tables[query['id']].items():
                if name.startswith('translated_'):
                    original.extend(tokenize(text))
            added, trace = expand(feedback[query['id']]['candidates'], chunks_by_id,
                                  bm25, original, args.feedback_docs, args.feedback_terms)
            trace['query_id'] = query['id']
            feedback_trace.append(trace)
            if added:
                rankings['feedback'] = bm25.top_k(original + added, args.top_k)
                weights['feedback'] = args.feedback_weight
        fused = hybrid.rrf_fuse(rankings, weights=weights, top_k=args.fuse_k)
        before_cap = len(fused)
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
        candidate_trace.append({'query_id': query['id'], 'fused_count': before_cap,
                                'after_doc_cap': len(fused),
                                'rerank_count': len(fused[:args.rerank_k]),
                                'rerank_doc_ids': sorted({int(doc_ids[c[0]]) for c in fused[:args.rerank_k]})})

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    names = [args.reranker] + getattr(args, 'extra_reranker', [])
    if len(set(names)) != len(names) or ('identity' in names and len(names) > 1):
        raise ValueError('Rerankers must be unique; identity cannot be ensembled.')
    all_scores = [[] for _ in queries]
    reranker_models = []
    cache_hits, cache_misses = 0, 0
    with Cache(getattr(args, 'score_cache', None) or out / 'scores.sqlite') as cache:
        for name in names:
            scorer = load_reranker(name, device=args.device, fp16=not args.fp32,
                                   max_length=getattr(args, 'rerank_max_length', None))
            info = model_info(scorer)
            reranker_models.append(info)
            progress = Progress(f'rerank {name}')
            try:
                for qi, (query, fused) in enumerate(zip(queries, fused_queries)):
                    passages = [texts[row] for row, _, _ in fused]
                    asked = [_rerank_query(query, variant_tables[query['id']], languages[row],
                                           match) for row, _, _ in fused]
                    keys = [cache_key({'model': info, 'version': 3,
                                       'query': question, 'text': text,
                                       'instruction': INSTRUCTION})
                            for question, text in zip(asked, passages)]
                    values = [cache.get(key) for key in keys] if name != 'identity' else [None]*len(keys)
                    missing = [i for i, value in enumerate(values) if value is None]
                    cache_hits += len(values) - len(missing)
                    cache_misses += len(missing)
                    # One call per query wording: Chinese chunks with the Chinese question, etc.
                    for question in dict.fromkeys(asked[i] for i in missing):
                        group = [i for i in missing if asked[i] == question]
                        fresh = scorer.score(question, [passages[i] for i in group],
                                             batch_size=args.rerank_batch)
                        if name == 'identity':
                            # Identity keeps the fused order across the whole list.
                            fresh = np.linspace(1.0, 0.0, num=len(passages))[group]
                        for i, value in zip(group, fresh):
                            values[i] = float(value)
                    if missing and name != 'identity':
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
                            'chunk_order': chunks[row]['chunk_order'], 'lang': languages[row],
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
    storage.write_jsonl(out / 'candidate_trace.jsonl', candidate_trace)
    if disk_text:
        texts.close()
    if feedback_path:
        storage.write_jsonl(out / 'feedback_trace.jsonl', feedback_trace)
    summary = {
        'queries': len(results),
        'disk_text': disk_text, 'dense_search': search_reports,
        'cache_hits': cache_hits, 'cache_misses': cache_misses,
        'feedback': {'source': feedback_path,
                     'sha256': storage.sha256_file(feedback_path) if feedback_path else None,
                     'docs': getattr(args, 'feedback_docs', 5),
                     'terms': getattr(args, 'feedback_terms', 8),
                     'weight': getattr(args, 'feedback_weight', .3),
                     'queries_expanded': sum(bool(t['terms']) for t in feedback_trace)},
        'chunks_searched': len(chunks),
        'channels': sorted({name.split(':')[0] for row in results
                            for item in row['candidates'] for name in item['channels']}),
        'encoder': None if args.no_dense else (args.encoder or
                                               storage.read_json(index_dir / 'dense_manifest.json')['encoder']),
        'reranker': args.reranker,
        'dense_models': dense_models, 'reranker_models': reranker_models,
        'score_method': 'mean sigmoid/yes-no scores; uncalibrated',
        'environment': environment(), 'retrieval_seconds': time.monotonic() - started_all,
        'translations_sha256': storage.sha256_file(args.translations) if args.translations else None,
        'queries_sha256': storage.sha256_file(args.queries),
        'candidate_per_doc': getattr(args, 'candidate_per_doc', 0),
        'match_language': match,
        'doc_candidates': str(args.doc_candidates) if getattr(args, 'doc_candidates', None) else None,
        'shard': [getattr(args, 'shard', 0) or 0, getattr(args, 'shards', 1) or 1],
        'queries_total': len(all_queries),
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
    parser.add_argument('--score-cache', help='Shared content-addressed reranker SQLite cache.')
    parser.add_argument('--feedback-candidates', help='Previous reranked candidates, same chunks/queries.')
    parser.add_argument('--feedback-docs', type=int, default=5)
    parser.add_argument('--feedback-terms', type=int, default=8)
    parser.add_argument('--feedback-weight', type=float, default=.3)
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
    parser.add_argument('--doc-candidates', default=None,
                        help='doc_candidates.jsonl from `cards.py subset`: adds the "card" channel.')
    parser.add_argument('--match-language', action='store_true',
                        help='Rerank Chinese/English chunks with the translated question.')
    parser.add_argument('--shard', type=int, default=0, help='Process queries i, i+n, ...')
    parser.add_argument('--shards', type=int, default=1, help='...out of n (one per GPU).')
    parser.add_argument('--no-bm25', action='store_true')
    parser.add_argument('--no-dense', action='store_true')
    parser.add_argument('--faiss', action='store_true', help='Require verified index from `vibiomir.py ann`.')
    parser.add_argument('--nprobe', type=int, default=32, help='IVF cells searched; speed/recall tradeoff.')
    parser.add_argument('--ann-audit', type=int, default=0, help='Compare this many query variants with exact search.')
    parser.add_argument('--disk-text', action='store_true', help='Read candidate text from a derived SQLite sidecar.')
    parser.add_argument('--device', default=None)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--rerank-batch', type=int, default=16)
    parser.add_argument('--fp32', action='store_true')
    args = parser.parse_args()
    if args.nprobe < 1 or args.ann_audit < 0:
        parser.error('Require nprobe >= 1 and ann-audit >= 0.')
    if args.feedback_docs < 2 or args.feedback_terms < 1 or not 0 < args.feedback_weight <= 1:
        parser.error('Feedback requires docs >= 2, terms >= 1, and weight in (0, 1].')
    if min(args.top_k, args.fuse_k, args.rerank_k, args.keep, args.batch_size,
           args.rerank_batch, args.search_block, args.query_block, args.doc_chunks) < 1:
        parser.error('Counts, batches and search blocks must be positive.')
    if args.candidate_per_doc < 0:
        parser.error('--candidate-per-doc must be nonnegative.')
    if not 0 <= args.shard < args.shards:
        parser.error('Require 0 <= --shard < --shards.')
    if args.no_bm25 and args.no_dense:
        parser.error('At least one of BM25 or dense retrieval must stay enabled.')
    if args.keep > args.rerank_k:
        # Candidates past rerank_k have no reranker score; mixing them with scored ones would
        # compare a probability against an RRF score in Block D.
        parser.error('--keep cannot exceed --rerank-k')
    if args.rerank_k > args.fuse_k:
        parser.error('--rerank-k cannot exceed --fuse-k')
    run(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
