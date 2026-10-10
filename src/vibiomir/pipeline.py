"""Run the whole cascade, crawl output to submission.zip, in isolated and resumable stages.

    fetch        (--source hf, the default) team corpus + BTC query/links from Hugging Face,
                 at a commit pinned for this run directory
    prepare      HF corpus parquet / local crawl runs -> corpus.parquet (frozen snapshot)
    chunk        every document -> chunks.parquet (CPU)
    cards        one card per document: title + opening (CPU)
    translate    1.200 queries -> Chinese (+English) translations and HyDE passages (one LLM)
    cards_*      BM25 + dense index over the cards
    doc_search   cards retrieval: top documents per query (no reranker)
    subset       chunks of those documents only
    subset_*     BM25 + dense index over the subset
    retrieve     chunk retrieval + the "card" channel + ONE reranker, language matched
    submit       F2-optimal selection, windows widened to the token budget, validated ZIP

Each stage runs as its own process and is skipped when its command, input hashes, code and
environment match a finished run (`stages/<name>.json`). With several GPUs the dense parts and the
query shards of the reranking run at the same time, one process per card.

Profiles set defaults only; every option can still be given:
    local    one 4 GB laptop GPU: bge-m3, bge-reranker-v2-m3, Qwen3-4B 4-bit translator.
    kaggle   two T4 16 GB: bge-m3, Qwen3-Reranker-4B, Qwen3-4B fp16 translator.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .common import storage
from .common.cache import cache_key
from .common.console import emit
from .common.runtime import environment
from .corpus import fetch

ROOT = Path(__file__).resolve().parents[2]

PROFILES = {
    'local': {'gpus': 1, 'encoder': 'bge-m3', 'reranker': 'bge-reranker-v2-m3',
              'translation_model': 'qwen3-4b', 'translation_quantize': '4bit',
              'translate_batch': 8, 'docs_per_query': 150, 'rerank_k': 60,
              'encoder_batch': None, 'rerank_batch': None, 'pilot': True},
    'kaggle': {'gpus': 2, 'encoder': 'bge-m3', 'reranker': 'qwen3-reranker-4b',
               'translation_model': 'qwen3-4b', 'translation_quantize': 'none',
               'translate_batch': 32, 'docs_per_query': 250, 'rerank_k': 80,
               'encoder_batch': 64, 'rerank_batch': 8, 'pilot': False},
}

# Original question strongest; the Chinese translation is near equal because most of the corpus
# is Chinese; HyDE passages broaden recall at lower weight; the card channel carries the
# document-level match into the chunk ranking.
WEIGHTS = {'bm25:keyword': 0.7, 'bm25:translated_zh': 1.0, 'bm25:translated_en': 0.5,
           'bm25:hyde_zh': 0.5, 'bm25:hyde_vi': 0.5, 'bm25:hyde_en': 0.5,
           'dense:translated_zh': 0.8, 'dense:translated_en': 0.5,
           'dense:hyde_zh': 0.7, 'dense:hyde_vi': 0.7, 'dense:hyde_en': 0.5, 'card': 1.0}


@contextmanager
def run_lock(path):
    """OS lock is released even on Ctrl+C; never two writers in the same run directory."""
    with Path(path).open('a+b') as stream:
        stream.write(b'0')
        stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Runner:
    def __init__(self, out, dry_run=False):
        self.out, self.dry_run = Path(out), dry_run
        self.code_key = cache_key({str(p.relative_to(ROOT)): storage.sha256_file(p)
                                  for base in ('src', 'scripts') for p in sorted((ROOT/base).rglob('*.py'))})
        self.env = environment()
        self._hashes = {}

    def _sha(self, path):
        """File hashes are reused within one run; a stage never edits a file it reads."""
        path = Path(path)
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self._hashes:
            self._hashes[key] = storage.sha256_file(path)
        return self._hashes[key]

    def _command(self, command):
        return [sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts'/command[0]),
                *map(str, command[1:])]

    def step(self, name, command, inputs, outputs, gpu=None):
        self.parallel([{'name': name, 'command': command, 'inputs': inputs,
                        'outputs': outputs, 'gpu': gpu}])

    def parallel(self, steps):
        """Run independent steps at once (each on its own GPU when `gpu` is set)."""
        todo = []
        for step in steps:
            cmd = self._command(step['command'])
            emit(f"\n[{step['name']}]" + (f" GPU {step['gpu']}" if step.get('gpu') is not None else '')
                 + f' {subprocess.list2cmdline(cmd)}')
            if self.dry_run:
                continue
            state_path = self.out / 'stages' / f"{step['name']}.json"
            key = cache_key({'command': cmd, 'inputs': {str(p): self._sha(p) for p in step['inputs']},
                             'code': self.code_key, 'environment': self.env})
            if state_path.exists():
                state = storage.read_json(state_path)
                if state['key'] == key and all(Path(p).exists() and self._sha(p) == digest
                                               for p, digest in state['outputs'].items()):
                    emit(f"[{step['name']}] Dùng lại kết quả đã kiểm tra SHA-256.")
                    continue
                if step['name'] == 'prepare':
                    # The source is live. Re-running prepare would change the population mid-run.
                    raise ValueError('Frozen corpus/config changed. Choose a new --out to take a '
                                     'new snapshot.')
            todo.append((step, cmd, state_path, key))
        if not todo:
            return
        logs = self.out / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        running = []
        try:
            for step, cmd, _state, _key in todo:
                env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'TOKENIZERS_PARALLELISM': 'false'}
                if step.get('gpu') is not None:
                    env['CUDA_VISIBLE_DEVICES'] = str(step['gpu'])
                process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                           errors='replace')
                prefix = f"[{step['name']}] " if len(todo) > 1 else ''
                reader = threading.Thread(target=_pump, args=(process, logs / f"{step['name']}.log",
                                                               prefix), daemon=True)
                reader.start()
                running.append((step, process, reader))
            failed = []
            for step, process, reader in running:
                if process.wait():
                    failed.append(step['name'])
                reader.join()
            if failed:
                raise RuntimeError(f"Stage(s) {', '.join(failed)} failed; see {logs}")
        except BaseException:
            for _step, process, _reader in running:
                if process.poll() is None:
                    process.terminate()
                    process.wait()
            raise
        for step, cmd, state_path, key in todo:
            storage.write_json(state_path, {'key': key, 'command': cmd,
                               'seconds': time.monotonic() - started,
                               'outputs': {str(p): self._sha(p) for p in step['outputs']}})


def _pump(process, log_path, prefix):
    with Path(log_path).open('a', encoding='utf-8') as log:
        for line in process.stdout:
            emit(prefix + line.rstrip())
            log.write(line)
            log.flush()
    process.stdout.close()


def _dense_steps(runner, name, chunks, index, encoder, gpus, batch, max_length, extra=()):
    """Encode `chunks` into `index`, split over the GPUs, then publish one embeddings.npy."""
    parts = max(1, len(gpus))
    devices = gpus or [None]
    common = ['--chunks', chunks, '--out', index, '--encoder', encoder,
              '--device', 'cuda' if gpus else 'cpu', '--max-length', max_length,
              '--batch-size', batch, '--shard', 2048, '--resume', *extra]
    if parts == 1:
        runner.step(name, ['index.py', 'dense', *common], [chunks],
                    [index/'embeddings.npy', index/'dense_manifest.json'], gpu=devices[0])
        return
    part_files = [index/'parts'/f'embeddings.part{i:02d}-of-{parts:02d}.npy' for i in range(parts)]
    runner.parallel([{'name': f'{name}_part{i}', 'gpu': gpu,
                      'command': ['index.py', 'dense', *common, '--part', i, '--parts', parts],
                      'inputs': [chunks], 'outputs': [part_files[i], part_files[i].with_suffix('.json')]}
                     for i, gpu in enumerate(devices)])
    runner.step(f'{name}_merge', ['index.py', 'dense-merge', '--chunks', chunks, '--out', index,
                                  '--parts', parts, '--encoder', encoder],
                [chunks, *part_files], [index/'embeddings.npy', index/'dense_manifest.json'])


def _fetch(r, args, out):
    """`--source hf`: download (or reuse) the pinned HF snapshot -> (corpus dir, queries, links)."""
    hf_dir = out/'hf'
    if args.dry_run:
        pinned = hf_dir/'pinned.json'
        revision = (storage.read_json(pinned)['revision'] if pinned.exists()
                    else args.hf_revision or 'LATEST_COMMIT_RESOLVED_AT_RUN')
    else:
        try:
            revision = fetch.resolve_revision(hf_dir, args.hf_repo, args.hf_revision)
        except Exception as error:
            raise fetch.explain_auth(error) from error
        fetch.pin(hf_dir, args.hf_repo, revision)
        emit(f'Corpus HF: {args.hf_repo}@{revision[:12]} (ghim cho run này)')
    paths = fetch.layout(hf_dir, revision)
    r.step('fetch', ['fetch_hf.py', '--out', hf_dir, '--repo', args.hf_repo, '--revision', revision],
           [], [paths['manifest'], paths['queries'], paths['links']])
    return paths['corpus'], paths['queries'], paths['links']


def run(args):
    out = Path(args.out).resolve()
    corpus = out/'corpus'/'corpus.parquet'
    chunks = out/'chunks'/'chunks.parquet'
    cards = out/'cards'/'cards.parquet'
    gpus = list(range(args.gpus))
    device = 'cuda' if gpus else 'cpu'
    r = Runner(out, args.dry_run)
    if args.source == ['hf']:
        corpus_dir, fetched_queries, fetched_links = _fetch(r, args, out)
        source = [str(corpus_dir)]
        queries = Path(args.queries).resolve() if args.queries else fetched_queries
        links = Path(args.links).resolve() if args.links else fetched_links
    else:
        source = [str(Path(p).resolve()) for p in args.source]
        queries = Path(args.queries or 'data/query.parquet').resolve()
        links = Path(args.links or 'data/links_corpus.parquet').resolve()
    if not args.dry_run and gpus:
        # CUDA probe runs in its own process so no parent CUDA context consumes VRAM later.
        probe = [sys.executable, str(ROOT/'scripts'/'benchmark.py'), '--check-only']
        if not args.skip_translation and args.translation_quantize == '4bit':
            probe.append('--quantized')
        subprocess.run(probe, cwd=ROOT, check=True)

    prepare = ['prepare.py', '--source', *source, '--out', corpus.parent]
    if args.limit:
        prepare += ['--limit', args.limit]
    r.step('prepare', prepare, [], [corpus, corpus.with_name('prepare_manifest.json')])
    report = {} if args.dry_run else storage.read_json(corpus.with_name('prepare_manifest.json'))
    if args.limit and report and report['rows_read'] < args.limit:
        raise ValueError(f"Only {report['rows_read']} input rows were available, requested "
                         f'{args.limit}. Use a new --out and the actual --limit.')

    r.parallel([
        {'name': 'chunk', 'command': ['chunk.py', '--corpus', corpus, '--out', chunks.parent,
                                      '--target-tokens', 320, '--overlap-tokens', 80,
                                      '--max-tokens', 768],
         'inputs': [corpus], 'outputs': [chunks, chunks.with_name('chunk_manifest.json')]},
        {'name': 'cards', 'command': ['cards.py', 'build', '--corpus', corpus, '--out', cards.parent,
                                     '--lead-tokens', args.lead_tokens],
         'inputs': [corpus], 'outputs': [cards, cards.with_name('cards_manifest.json')]},
    ])

    encoder_batch, rerank_batch = args.encoder_batch, args.rerank_batch
    revisions = {}
    if args.pilot and not args.dry_run:
        pilot = out/'pilot.json'
        r.step('pilot', ['benchmark.py', '--chunks', chunks, '--queries', queries, '--out', pilot,
                         '--device', device, '--encoders', args.encoder,
                         '--rerankers', args.reranker], [chunks, queries], [pilot], gpu=gpus[0] if gpus else None)
        found = storage.read_json(pilot)['models']
        batches = {(m['kind'], m['name']): m['batch_size'] for m in found}
        revisions = {(m['kind'], m['name']): m['model'].get('revision') for m in found}
        encoder_batch = encoder_batch or batches.get(('encoder', args.encoder))
        rerank_batch = rerank_batch or batches.get(('reranker', args.reranker))
    encoder_batch, rerank_batch = encoder_batch or 16, rerank_batch or 4
    revision = revisions.get(('encoder', args.encoder))
    extra = ['--revision', revision] if revision else []

    # Translate to the languages the corpus actually holds (>= 1% of documents).
    counts = report.get('languages', {'zh': 1, 'en': 1}) if report else {'zh': 1, 'en': 1}
    total = max(1, sum(counts.values()))
    languages = [lang for lang in ('zh', 'en') if counts.get(lang, 0) / total >= 0.01]
    translations = None
    if not args.skip_translation and (languages or args.hyde):
        translations = out/'translations'/'translations.jsonl'
        generate = {'name': 'translate', 'gpu': gpus[0] if gpus else None,
                    'command': ['translate.py', '--queries', queries, '--out', translations.parent,
                                '--device', device, '--model', args.translation_model,
                                '--quantize', args.translation_quantize,
                                '--batch-size', args.translate_batch,
                                '--languages', *languages, '--hyde', *args.hyde, '--allow-partial'],
                    'inputs': [queries],
                    'outputs': [translations, translations.with_name('translation_manifest.json')]}
    else:
        generate = None
        emit('Bỏ qua sinh truy vấn: cấu hình tắt hoặc corpus không có ngôn ngữ đích.')

    cards_index = out/'index'/'cards'
    cards_bm25 = {'name': 'cards_bm25', 'command': ['index.py', 'bm25', '--chunks', cards,
                                                    '--out', cards_index],
                  'inputs': [cards], 'outputs': [cards_index/'bm25.npz', cards_index/'bm25_manifest.json']}
    # The LLM and the card encoder do not fit one 4 GB card together: run them one after the
    # other there, side by side on two GPUs.
    if generate and len(gpus) > 1:
        generate['gpu'] = gpus[1]
        r.parallel([generate, cards_bm25])
    else:
        r.parallel([step for step in (generate, cards_bm25) if step])
    _dense_steps(r, 'cards_dense', cards, cards_index, args.encoder, gpus, encoder_batch, 512, extra)

    query_inputs = [queries] + ([translations] if translations else [])
    translation_args = ['--translations', translations] if translations else []
    weights = json.dumps(WEIGHTS)
    doc_dir = out/'doc_search'
    k = args.docs_per_query
    r.step('doc_search', ['retrieve.py', '--chunks', cards, '--index', cards_index,
                          '--queries', queries, '--out', doc_dir, '--reranker', 'identity',
                          '--device', device, '--search-device', device, '--keyword-variant',
                          '--top-k', k, '--fuse-k', k, '--rerank-k', k, '--keep', k,
                          '--batch-size', encoder_batch, '--weights', weights, *translation_args],
           [cards, cards_index/'bm25.npz', cards_index/'embeddings.npy', *query_inputs],
           [doc_dir/'candidates.jsonl', doc_dir/'retrieval_manifest.json'], gpu=gpus[0] if gpus else None)

    subset_dir = out/'subset'
    subset = subset_dir/'chunks.parquet'
    doc_candidates = subset_dir/'doc_candidates.jsonl'
    r.step('subset', ['cards.py', 'subset', '--candidates', doc_dir/'candidates.jsonl',
                      '--chunks', chunks, '--out', subset_dir, '--docs-per-query', k],
           [doc_dir/'candidates.jsonl', chunks], [subset, doc_candidates])

    subset_index = out/'index'/'subset'
    r.step('subset_bm25', ['index.py', 'bm25', '--chunks', subset, '--out', subset_index],
           [subset], [subset_index/'bm25.npz', subset_index/'bm25_manifest.json'])
    _dense_steps(r, 'subset_dense', subset, subset_index, args.encoder, gpus, encoder_batch, 1024, extra)

    shards = max(1, len(gpus))
    retrieval = out/'retrieval'
    shard_dirs = [retrieval if shards == 1 else retrieval/f'part{i}' for i in range(shards)]
    retrieve = ['retrieve.py', '--chunks', subset, '--index', subset_index, '--queries', queries,
                '--doc-candidates', doc_candidates, '--reranker', args.reranker,
                '--match-language', '--device', device, '--search-device', device,
                '--keyword-variant', '--top-k', 300, '--fuse-k', 400, '--rerank-k', args.rerank_k,
                '--keep', args.rerank_k, '--candidate-per-doc', 4, '--rerank-max-length', 1024,
                '--batch-size', encoder_batch, '--rerank-batch', rerank_batch,
                '--weights', weights, *translation_args]
    retrieve_inputs = [subset, doc_candidates, subset_index/'bm25.npz',
                       subset_index/'embeddings.npy', subset_index/'dense_manifest.json', *query_inputs]
    r.parallel([{'name': 'retrieve' if shards == 1 else f'retrieve_{i}',
                 'gpu': gpus[i] if gpus else None,
                 'command': [*retrieve, '--out', shard_dirs[i], '--shard', i, '--shards', shards],
                 'inputs': retrieve_inputs,
                 'outputs': [shard_dirs[i]/'candidates.jsonl', shard_dirs[i]/'retrieval_manifest.json']}
                for i in range(shards)])

    candidates = [d/'candidates.jsonl' for d in shard_dirs]
    calibration = ['--calibration', Path(args.calibration).resolve()] if args.calibration else []
    variants = [('submit', out/'submission', args.window_tokens)]
    if args.window_tokens:
        # The same selection without widening, for a one-change A/B on the leaderboard.
        variants.append(('submit_nowindow', out/'submission_nowindow', 0))
    for name, target, window in variants:
        r.step(name, ['submit.py', '--candidates', *candidates, '--chunks', subset,
                      '--corpus', corpus, '--queries', queries, '--links', links, '--profile', 'f2',
                      '--window-tokens', window, '--require-complete', '--out', target, *calibration],
               [*candidates, subset, corpus, queries, links],
               [target/'submission.zip', target/'submission.json', target/'submission_manifest.json'])
    emit(f'\nBài nộp: {out / "submission" / "submission.zip"}')
    return out / 'submission' / 'submission.zip'


def parse_args(argv=None):
    from .index.embedding import ENCODERS
    from .retrieval.rerank import RERANKERS
    from .retrieval.translate import MODELS
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--profile', choices=sorted(PROFILES), default='local')
    p.add_argument('--source', nargs='+', default=['hf'],
                   help="'hf' (default): download the team corpus and BTC files from Hugging Face "
                        'and pin the commit for this run. Or local crawl folders (nguyen, a run '
                        'directory) / parquet folders.')
    p.add_argument('--hf-repo', default=fetch.CORPUS_REPO, help='Dataset holding corpus/*.parquet.')
    p.add_argument('--hf-revision', default=None,
                   help='Corpus commit; default: pinned for this --out, else the latest.')
    p.add_argument('--out', default='work/run_hf')
    p.add_argument('--limit', type=int, default=None,
                   help='Input rows, before quality filtering. Default: everything.')
    p.add_argument('--queries', default=None,
                   help='Default: BTC query.parquet from HF with --source hf, else data/query.parquet.')
    p.add_argument('--links', default=None,
                   help='Default: BTC links_corpus.parquet from HF, else data/links_corpus.parquet.')
    p.add_argument('--gpus', type=int, default=None, help='GPUs to use; 0 runs on CPU.')
    p.add_argument('--encoder', choices=sorted(ENCODERS), default=None)
    p.add_argument('--reranker', choices=sorted(RERANKERS), default=None)
    p.add_argument('--translation-model', choices=sorted(MODELS), default=None)
    p.add_argument('--translation-quantize', choices=['4bit', 'none'], default=None)
    p.add_argument('--translate-batch', type=int, default=None)
    p.add_argument('--hyde', nargs='*', choices=['zh', 'vi', 'en'], default=['zh', 'vi'])
    p.add_argument('--skip-translation', action='store_true')
    p.add_argument('--skip-pilot', action='store_true')
    p.add_argument('--encoder-batch', type=int, default=None)
    p.add_argument('--rerank-batch', type=int, default=None)
    p.add_argument('--lead-tokens', type=int, default=160)
    p.add_argument('--docs-per-query', type=int, default=None)
    p.add_argument('--rerank-k', type=int, default=None)
    p.add_argument('--window-tokens', type=int, default=768,
                   help='Submitted chunk window; 0 keeps the indexed chunk.')
    p.add_argument('--calibration', default=None, help='calibration.json for the F2 cut.')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    for key, value in PROFILES[args.profile].items():
        if key == 'pilot':
            continue
        if getattr(args, key, None) is None:
            setattr(args, key, value)
    args.pilot = PROFILES[args.profile]['pilot'] and not args.skip_pilot and args.gpus > 0
    if args.limit is not None and args.limit < 1:
        p.error('--limit must be positive')
    if args.gpus < 0 or not 1 <= args.rerank_k <= 400 or not 1 <= args.docs_per_query <= 1000:
        p.error('Require --gpus >= 0, 1 <= --rerank-k <= 400, 1 <= --docs-per-query <= 1000.')
    if not 0 <= args.window_tokens <= 1024:
        p.error('--window-tokens must be in [0, 1024].')
    if args.reranker == 'identity':
        emit('Cảnh báo: reranker identity chỉ để chạy thử; điểm F2 sẽ không có ý nghĩa.')
    return args


def main(argv=None):
    args = parse_args(argv)
    if args.dry_run:
        run(args)
    else:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        with run_lock(Path(args.out)/'pipeline.lock'):
            run(args)


if __name__ == '__main__':
    main()
