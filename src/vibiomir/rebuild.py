"""Rebuild from the frozen corpus and add retrieval techniques progressively.

No LLM query generation/rewriting, no implicit fine-tuning, no old subset/index
or reranker cache. Later experiments share the newly built full-corpus index.
"""
import argparse
import json
from pathlib import Path

from .common import storage
from .experiments import change, comparison
from .pipeline import Runner, run_lock


def variants(args):
    common = ['retrieve', '--chunks', args.out / 'chunks/chunks.parquet',
              '--index', args.out / 'index', '--queries', args.queries,
              '--reranker', args.reranker, '--device', args.device,
              '--search-device', 'cpu', '--batch-size', args.encoder_batch,
              '--rerank-batch', args.rerank_batch, '--rerank-max-length', '1024',
              '--top-k', '300', '--fuse-k', '400', '--rerank-k', '50', '--keep', '50',
              '--candidate-per-doc', '4', '--score-cache', args.out / 'scores.sqlite']
    common = list(map(str, common))
    scale = getattr(args, 'suite', 'progressive') == 'scale'
    if scale:
        common.append('--disk-text')
    if args.translations:
        common += ['--translations', str(args.translations), '--match-language']
    keyword = common + ['--keyword-variant', '--weights', '{"bm25:keyword":0.7}']
    deeper = change(keyword, '--rerank-k', '100')
    rows = [('01_full_hybrid', None, 'Full corpus, BM25 + dense + primary reranker', common),
            ('02_keyword', '01_full_hybrid', 'Add lexical keyword channel', keyword),
            ('03_rerank100', '02_keyword', 'Score 100 candidates, retain top 50', deeper)]
    if args.extra_reranker:
        rows.append(('04_ensemble', '03_rerank100', 'Add second reranker, mean scores',
                     deeper + ['--extra-reranker', args.extra_reranker]))
    if scale:
        audit = str(getattr(args, 'ann_audit', 16))
        rows += [('05_ann16', '03_rerank100', 'IVF search, nprobe16, same rerank budget',
                  deeper + ['--faiss', '--nprobe', '16', '--ann-audit', audit]),
                 ('06_ann64', '05_ann16', 'IVF search, nprobe64',
                  deeper + ['--faiss', '--nprobe', '64', '--ann-audit', audit])]
        if getattr(args, 'extra_encoder', None):
            dual = deeper + ['--extra-index', str(args.out / 'index_extra')]
            rows.append(('07_dual_dense', '03_rerank100', 'Add another dense encoder via RRF', dual))
            if args.extra_reranker:
                rows.append(('08_dual_ensemble', '07_dual_dense', 'Add second reranker to dual retrieval',
                             dual + ['--extra-reranker', args.extra_reranker]))
    return rows


def run(args):
    scale = getattr(args, 'suite', 'progressive') == 'scale'
    if scale and not args.dry_run:
        import importlib.util
        if importlib.util.find_spec('faiss') is None:
            raise RuntimeError('Scale suite requires faiss-cpu. Install requirements/search.txt first.')
    args.base, args.out = Path(args.base).resolve(), Path(args.out).resolve()
    args.queries = Path(args.queries).resolve()
    if args.out.is_relative_to(args.base) or args.base.is_relative_to(args.out):
        raise ValueError('Choose --out outside the baseline directory.')
    corpus = args.base / 'corpus/corpus.parquet'
    prepare = storage.read_json(args.base / 'stages/prepare.json')
    recorded = prepare['outputs'].get(str(corpus))
    if not recorded or storage.sha256_file(corpus) != recorded:
        raise ValueError('Frozen corpus does not match prepare checkpoint; do not resample live crawl.')
    sources = [corpus, args.queries]
    if args.links:
        args.links = Path(args.links).resolve()
        sources.append(args.links)
    if args.labels:
        args.labels = Path(args.labels).resolve()
        sources.append(args.labels)
    if args.translations:
        args.translations = Path(args.translations).resolve()
        from .retrieval.query import load_queries, load_translations
        load_translations(args.translations, load_queries(args.queries))
        if any((r.get('kind') or 'translate') != 'translate'
               for r in storage.iter_jsonl(args.translations)):
            raise ValueError('Only existing translations allowed; HyDE is disabled in rebuild.')
        sources.append(args.translations)
    plan = {'options': {k: str(v) if isinstance(v, Path) else v
                        for k, v in vars(args).items() if k != 'dry_run'},
            'inputs': {str(p): storage.sha256_file(p) for p in sources},
            'training': False, 'query_generation': False}
    args.out.mkdir(parents=True, exist_ok=True)
    with run_lock(args.out / 'rebuild.lock'):
        plan_path = args.out / 'plan.json'
        if plan_path.exists() and storage.read_json(plan_path) != plan:
            raise ValueError('Rebuild inputs/options changed. Choose another --out.')
        if not args.dry_run:
            storage.write_json(plan_path, plan)
        r = Runner(args.out, dry_run=args.dry_run)
        chunks, index = args.out / 'chunks/chunks.parquet', args.out / 'index'
        r.step('chunk_full', ['chunk', '--corpus', corpus, '--out', chunks.parent,
                             '--target-tokens', args.chunk_tokens, '--overlap-tokens', '32',
                             '--max-tokens', '768'], sources,
               [chunks, chunks.with_name('chunk_manifest.json')])
        r.step('bm25_full', ['index', 'bm25', '--chunks', chunks, '--out', index], [chunks],
               [index / 'bm25.npz', index / 'bm25_manifest.json'])
        r.step('dense_full', ['index', 'dense', '--chunks', chunks, '--out', index,
                             '--encoder', args.encoder, '--batch-size', args.encoder_batch,
                             '--device', args.device, '--resume'], [chunks],
               [index / 'embeddings.npy', index / 'dense_manifest.json'])
        if scale:
            r.step('ann_full', ['ann', '--index', index, '--lists', '1024'],
                   [index / 'embeddings.npy', index / 'dense_manifest.json'],
                   [index / 'faiss.index', index / 'ann_manifest.json'])
        if scale and getattr(args, 'extra_encoder', None):
            # Respect the encoder's model-card context limit (E5: 512).
            r.step('dense_extra', ['index', 'dense', '--chunks', chunks, '--out', args.out / 'index_extra',
                   '--encoder', args.extra_encoder, '--batch-size', args.encoder_batch,
                   '--device', args.device, '--resume'], [chunks],
                   [args.out / 'index_extra/embeddings.npy', args.out / 'index_extra/dense_manifest.json'])
        dependencies = sources + [chunks, index / 'bm25.npz', index / 'embeddings.npy',
                                  index / 'bm25_manifest.json', index / 'dense_manifest.json']
        report = []
        for name, parent, description, command in variants(args):
            directory = args.out / name
            candidates = directory / 'retrieval/candidates.jsonl'
            current_inputs = list(dependencies)
            if '--faiss' in command:
                current_inputs += [index / 'faiss.index', index / 'ann_manifest.json']
            if '--extra-index' in command:
                current_inputs += [args.out / 'index_extra/embeddings.npy',
                                   args.out / 'index_extra/dense_manifest.json']
            r.step(name + '_retrieve', command + ['--out', candidates.parent], current_inputs,
                   [candidates, candidates.with_name('retrieval_manifest.json'),
                    candidates.with_name('candidate_trace.jsonl')])
            submission = directory / 'submission'
            cmd = ['submit', '--candidates', candidates, '--chunks', chunks, '--corpus', corpus,
                   '--queries', args.queries, '--out', submission, '--profile', 'f2',
                   '--window-tokens', '768', '--require-complete']
            if args.links:
                cmd += ['--links', args.links]
            r.step(name + '_submit', cmd, sources + [chunks, candidates],
                   [submission / 'submission.json', submission / 'submission.zip',
                    submission / 'submission_manifest.json'])
            if args.labels:
                r.step(name + '_evaluate', ['evaluate', 'score', '--submission',
                       submission / 'submission.json', '--candidates', candidates, '--labels',
                       args.labels, '--corpus', corpus, '--out', directory / 'evaluation'],
                       sources + [candidates, submission / 'submission.json'],
                       [directory / 'evaluation/metrics.json'])
            if args.dry_run:
                continue
            detail = storage.read_json(candidates.with_name('retrieval_manifest.json'))
            item = {'name': name, 'parent': parent, 'change': description,
                    'zip': str(submission / 'submission.zip'),
                    'models': detail['reranker_models'], 'encoder': detail['encoder'],
                    'retrieval_seconds': detail['retrieval_seconds'],
                    'cache_hits': detail['cache_hits'], 'cache_misses': detail['cache_misses'],
                    'dense_search': detail.get('dense_search'),
                    'submission': storage.read_json(submission / 'submission_manifest.json')['submission']}
            if parent:
                parent_rows = {int(row['query_id']): row for row in storage.iter_jsonl(
                    args.out / parent / 'retrieval/candidates.jsonl')}
                delta = comparison(candidates, parent_rows)
                item['vs_parent'] = {k.replace('_vs_baseline', ''): v for k, v in delta.items()}
            if args.labels:
                item['evaluation'] = storage.read_json(directory / 'evaluation/metrics.json')
            report.append(item)
            storage.write_json(args.out / 'summary.json', report)
            lines = ['# Progressive full-corpus rebuild', '',
                     'No quality improvement is established without evaluation labels or leaderboard scores.', '',
                     '| Experiment | Parent | Retrieval seconds | ZIP |', '|---|---|---:|---|']
            for row in report:
                lines.append(f"| {row['name']} | {row['parent'] or '-'} | "
                             f"{row['retrieval_seconds']:.1f} | "
                             f"[ZIP]({row['name']}/submission/submission.zip) |")
            (args.out / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Rebuild {"previewed" if args.dry_run else "completed"}: {args.out}')


def main():
    from .index.embedding import ENCODERS
    from .retrieval.rerank import RERANKERS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='work/run_local_100k')
    parser.add_argument('--out', default='work/rebuild_100k')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--links', default='data/links_corpus.parquet')
    parser.add_argument('--labels')
    parser.add_argument('--suite', choices=['progressive', 'scale'], default='progressive',
                        help='Scale adds exact/IVF comparisons and another dense encoder.')
    parser.add_argument('--extra-encoder', choices=sorted(ENCODERS) + ['none'], default=None)
    parser.add_argument('--ann-audit', type=int, default=16)
    parser.add_argument('--translations', help='Optional existing translation-only JSONL. No generation.')
    parser.add_argument('--encoder', default='bge-m3', choices=sorted(ENCODERS))
    parser.add_argument('--reranker', default='bge-reranker-v2-m3', choices=sorted(RERANKERS))
    parser.add_argument('--extra-reranker', default='qwen3-reranker-0.6b',
                        choices=sorted(RERANKERS) + ['none'],
                        help='Second scorer, loaded sequentially. Use none to omit.')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--encoder-batch', type=int, default=8)
    parser.add_argument('--rerank-batch', type=int, default=2)
    parser.add_argument('--chunk-tokens', type=int, default=384)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.extra_encoder is None and args.suite == 'scale':
        args.extra_encoder = 'multilingual-e5-base'
    if args.extra_encoder == 'none':
        args.extra_encoder = None
    if args.extra_encoder == args.encoder:
        parser.error('Additional encoder must differ from the primary encoder.')
    if args.ann_audit < 0:
        parser.error('ann-audit must be nonnegative.')
    if args.extra_reranker == 'none':
        args.extra_reranker = None
    if min(args.encoder_batch, args.rerank_batch) < 1 or not 32 < args.chunk_tokens <= 768:
        parser.error('Positive batches and 32 < chunk-tokens <= 768 required.')
    if args.extra_reranker and args.extra_reranker == args.reranker:
        parser.error('The second reranker must differ from the first.')
    if args.extra_reranker and 'identity' in (args.reranker, args.extra_reranker):
        parser.error('identity cannot be ensembled with a model.')
    run(args)
