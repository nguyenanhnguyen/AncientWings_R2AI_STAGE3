"""Run a frozen corpus through full chunk retrieval to a validated submission.

Default on local and Kaggle: prepare -> structure-aware source chunks -> BM25 and
dense -> keyword/original query RRF -> document diversity -> ONE reranker ->
source-span validation and ZIP. No teacher, training, query LLM, feedback or ensemble.
Each query belongs to one GPU shard; a shard scores each uncached pair once.

Local uses BGE and scores 120 candidates/query; Kaggle uses Qwen3 4B and scores 60. Full chunk encoding
costs more than the legacy card gate, but searches evidence anywhere in the article.
Optional FAISS IVF speeds dense search with approximate recall; exact is the default.
Checkpoints, embedding shards and rerank pair caches are reused. --max-hours is a
wall-clock guard per invocation, not a promise about completion or weekly GPU quota.
--architecture cascade retains the older document-card path for explicit comparisons.
"""
import argparse
from contextlib import contextmanager
import importlib.util
import json
import math
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
    'local': {'source': ['nguyen'], 'limit': 100000, 'out': 'work/run_quality_local',
              'gpus': 1, 'encoder': 'bge-m3', 'reranker': 'bge-reranker-v2-m3',
              'translation_model': 'qwen3-4b', 'translation_quantize': '4bit',
              'translate_batch': 8, 'docs_per_query': 100, 'rerank_k': 120,
              'encoder_batch': 8, 'rerank_batch': 2, 'max_hours': 0},
    'kaggle': {'source': ['hf'], 'limit': 100000, 'out': 'work/run_quality_qwen4b_hf',
               'gpus': 2, 'encoder': 'qwen3-embedding-4b', 'reranker': 'qwen3-reranker-4b',
               'translation_model': 'qwen3-4b', 'translation_quantize': 'none',
               'translate_batch': 32, 'docs_per_query': 200, 'rerank_k': 60,
               'encoder_batch': 16, 'rerank_batch': 8, 'max_hours': 9},
}

# Original question strongest; the Chinese translation is near equal because most of the corpus
# is Chinese; HyDE passages broaden recall at lower weight; the card channel carries the
# document-level match into the chunk ranking.
WEIGHTS = {'bm25:keyword': 0.7, 'bm25:translated_zh': 1.0, 'bm25:translated_en': 0.5,
           'bm25:hyde_zh': 0.5, 'bm25:hyde_vi': 0.5, 'bm25:hyde_en': 0.5,
           'dense:translated_zh': 0.8, 'dense:translated_en': 0.5,
           'dense:hyde_zh': 0.7, 'dense:hyde_vi': 0.7, 'dense:hyde_en': 0.5, 'card': 1.0}
FULL_WEIGHTS = {'bm25:original': 1.0, 'dense:original': 1.0, 'bm25:keyword': 0.7,
                'bm25:translated_zh': 1.0, 'dense:translated_zh': 0.8,
                'bm25:translated_en': 0.5, 'dense:translated_en': 0.5}


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


class BudgetExceeded(RuntimeError):
    """Wall-clock budget reached: keep checkpoints, never declare a finished submission."""


class Runner:
    def __init__(self, out, dry_run=False, max_hours=0):
        self.out, self.dry_run = Path(out), dry_run
        self.deadline = time.monotonic() + max_hours * 3600 if max_hours else None
        self.code_key = cache_key({str(p.relative_to(ROOT)): storage.sha256_file(p)
                                  for base in ('src', 'scripts') for p in sorted((ROOT/base).rglob('*.py'))})
        self.env = environment()
        self._hashes = {}

    def remaining(self):
        if self.deadline is None:
            return None
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise BudgetExceeded('Time budget reached; retain this run directory to resume.')
        return left

    def _sha(self, path):
        """File hashes are reused within one run; a stage never edits a file it reads."""
        path = Path(path)
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self._hashes:
            self._hashes[key] = storage.sha256_file(path)
        return self._hashes[key]

    def _command(self, command):
        # Every stage goes through the one dispatcher: scripts/vibiomir.py <stage> ...
        return [sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts'/'vibiomir.py'),
                *map(str, command)]

    def _reuse_frozen_corpus(self, state, step):
        # A completed corpus is an immutable input snapshot for this run. Changes to
        # downstream code/environment do not invalidate its verified bytes.
        if step['name'] != 'prepare':
            return False
        old = state.get('command', [])
        if len(old) > 4 and Path(old[4]).name == 'prepare.py':
            old_options = old[5:]
        elif len(old) > 5 and Path(old[4]).name == 'vibiomir.py' and old[5] == 'prepare':
            old_options = old[6:]
        else:
            return False
        if old_options != list(map(str, step['command'][1:])):
            return False
        recorded = state.get('outputs', {})
        return (set(recorded) == {str(p) for p in step['outputs']}
                and all(Path(p).is_file() and self._sha(p) == digest for p, digest in recorded.items()))

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
                if step['name'] == 'prepare':
                    if self._reuse_frozen_corpus(state, step):
                        emit('[prepare] Reusing frozen corpus: source/options and output SHA-256 '
                             'verified. Use a new --out to prepare with new code or new crawl data.')
                        continue
                    # The source is live. Re-running prepare would change the population mid-run.
                    raise ValueError('Frozen corpus verification failed: prepare options differ, '
                                     'checkpoint is unsupported, or output files are missing/modified. '
                                     'Keep this run intact; use a new --out for a new snapshot.')
                if state['key'] == key and all(Path(p).exists() and self._sha(p) == digest
                                               for p, digest in state['outputs'].items()):
                    emit(f"[{step['name']}] Dùng lại kết quả đã kiểm tra SHA-256.")
                    continue
            todo.append((step, cmd, state_path, key))
        if not todo:
            return
        logs = self.out / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        running = []
        try:
            for step, cmd, _state, _key in todo:
                self.remaining()
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
                try:
                    code = process.wait(timeout=self.remaining())
                except subprocess.TimeoutExpired as error:
                    raise BudgetExceeded(f"Time budget reached during {step['name']}; "
                                         'completed stages and caches are retained.') from error
                reader.join()
                if code:
                    failed.append(step['name'])
                else:
                    # Record each step as soon as it succeeds. Waiting for the whole group would
                    # throw away hours of finished GPU work when a sibling fails or is stopped.
                    self._record(todo, step, started)
            if failed:
                raise RuntimeError(f"Stage(s) {', '.join(failed)} failed; see {logs}")
        except BaseException:
            for step, process, _reader in running:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                elif process.returncode == 0:
                    self._record(todo, step, started)
                _reader.join(timeout=10)
            raise

    def _record(self, todo, step, started):
        """Write <out>/stages/<name>.json, so a rerun reuses this step instead of repeating it."""
        for candidate, cmd, state_path, key in todo:
            if candidate is not step:
                continue
            if not all(Path(p).exists() for p in step['outputs']):
                emit(f"[{step['name']}] Thoát với mã 0 nhưng thiếu output; sẽ chạy lại lần sau.")
                return
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
    from .index.embedding import ENCODERS
    max_length = min(max_length, ENCODERS[encoder].get('context_limit', max_length))
    parts = max(1, len(gpus))
    devices = gpus or [None]
    common = ['--chunks', chunks, '--out', index, '--encoder', encoder,
              '--device', 'cuda' if gpus else 'cpu', '--max-length', max_length,
              '--batch-size', batch, '--shard', 2048, '--resume', *extra]
    if parts == 1:
        runner.step(name, ['index', 'dense', *common], [chunks],
                    [index/'embeddings.npy', index/'dense_manifest.json'], gpu=devices[0])
        return
    part_files = [index/'parts'/f'embeddings.part{i:02d}-of-{parts:02d}.npy' for i in range(parts)]
    runner.parallel([{'name': f'{name}_part{i}', 'gpu': gpu,
                      'command': ['index', 'dense', *common, '--part', i, '--parts', parts],
                      'inputs': [chunks], 'outputs': [part_files[i], part_files[i].with_suffix('.json')]}
                     for i, gpu in enumerate(devices)])
    runner.step(f'{name}_merge', ['index', 'dense-merge', '--chunks', chunks, '--out', index,
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
        fetch.pin_selection(hf_dir, args.id_start, args.id_end)
        emit(f'Corpus HF: {args.hf_repo}@{revision[:12]} (ghim cho run này)')
    paths = fetch.layout(hf_dir, revision)
    r.step('fetch', ['fetch', '--out', hf_dir, '--repo', args.hf_repo, '--revision', revision,
                     *_id_options(args)],
           [], [paths['manifest'], paths['queries'], paths['links']])
    return paths['corpus'], paths['queries'], paths['links']


def _id_options(args):
    return [value for flag, bound in (('--id-start', args.id_start), ('--id-end', args.id_end))
            if bound is not None for value in (flag, bound)]


def _run_full(r, args, out, corpus, queries, links, gpus):
    """One full-corpus retrieval pass and one multilingual reranker, no model ensemble."""
    device = 'cuda' if gpus else 'cpu'
    chunks = out/'chunks'/'chunks.parquet'
    index = out/'index'/'full'
    r.step('chunk', ['chunk', '--corpus', corpus, '--out', chunks.parent,
                     '--target-tokens', args.chunk_tokens, '--overlap-tokens', args.overlap_tokens,
                     '--max-tokens', 768], [corpus], [chunks, chunks.with_name('chunk_manifest.json')])
    r.step('bm25', ['index', 'bm25', '--chunks', chunks, '--out', index], [chunks],
           [index/'bm25.npz', index/'bm25_manifest.json'])
    _dense_steps(r, 'dense', chunks, index, args.encoder, gpus, args.encoder_batch, 1024)
    ann_options, ann_inputs = [], []
    if args.ann:
        r.step('ann', ['ann', '--index', index], [index/'embeddings.npy', index/'dense_manifest.json'],
               [index/'faiss.index', index/'ann_manifest.json'])
        ann_options = ['--faiss', '--nprobe', args.nprobe, '--ann-audit', 5]
        ann_inputs = [index/'faiss.index', index/'ann_manifest.json']
    translations = Path(args.translations).resolve() if args.translations else None
    if translations and not translations.is_file():
        raise FileNotFoundError(f'--translations {translations} does not exist.')
    # Build once before query shards start, avoiding two writers to the same SQLite sidecar.
    r.step('passages', ['passages', '--chunks', chunks, '--out', index/'passages.sqlite'],
           [chunks], [index/'passages.sqlite'])
    shards = max(1, len(gpus))
    folders = [out/'retrieval' if shards == 1 else out/'retrieval'/f'part{i}' for i in range(shards)]
    common = ['retrieve', '--chunks', chunks, '--index', index, '--queries', queries,
              '--reranker', args.reranker, '--device', device, '--search-device', device,
              '--keyword-variant', '--disk-text', '--top-k', 300, '--fuse-k', 400,
              '--rerank-k', args.rerank_k, '--keep', args.rerank_k,
              '--candidate-per-doc', 3, '--rerank-max-length', 1024,
              '--batch-size', args.encoder_batch, '--rerank-batch', args.rerank_batch,
              '--weights', json.dumps(FULL_WEIGHTS), *ann_options]
    inputs = [chunks, index/'bm25.npz', index/'bm25_manifest.json', index/'embeddings.npy',
              index/'dense_manifest.json', queries, *ann_inputs]
    if translations:
        common += ['--translations', translations, '--match-language']
        inputs.append(translations)
    r.parallel([{'name': 'retrieve' if shards == 1 else f'retrieve_{i}',
                 'gpu': gpus[i] if gpus else None,
                 'command': [*common, '--out', folder, '--shard', i, '--shards', shards],
                 'inputs': inputs,
                 'outputs': [folder/'candidates.jsonl', folder/'retrieval_manifest.json']}
                for i, folder in enumerate(folders)])
    candidates = [folder/'candidates.jsonl' for folder in folders]
    calibration = Path(args.calibration).resolve() if args.calibration else None
    target = out/'submission'
    r.step('submit', ['submit', '--candidates', *candidates, '--chunks', chunks,
                      '--corpus', corpus, '--queries', queries, '--links', links, '--profile', 'f2',
                      '--window-tokens', args.window_tokens, '--require-complete', '--out', target,
                      *(['--calibration', calibration] if calibration else [])],
           [*candidates, chunks, corpus, queries, links, *([calibration] if calibration else [])],
           [target/'submission.zip', target/'submission.json', target/'submission_manifest.json'])
    emit(f'Submission: {target / "submission.zip"}')
    return target/'submission.zip'


def run(args):
    out = Path(args.out).resolve()
    corpus = out/'corpus'/'corpus.parquet'
    cards = out/'cards'/'cards.parquet'
    gpus = list(range(args.gpus))
    device = 'cuda' if gpus else 'cpu'
    r = Runner(out, args.dry_run, args.max_hours)
    for name in ('translations', 'calibration'):
        value = getattr(args, name)
        if value and not Path(value).is_file():
            raise FileNotFoundError(f'--{name} {value} does not exist.')
    if args.ann and not args.dry_run and importlib.util.find_spec('faiss') is None:
        raise RuntimeError('--ann requires faiss-cpu. Install requirements/search.txt before running.')
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
        probe = [sys.executable, str(ROOT/'scripts'/'vibiomir.py'), 'benchmark', '--check-only']
        if not args.skip_translation and args.translation_quantize == '4bit':
            probe.append('--quantized')
        try:
            subprocess.run(probe, cwd=ROOT, check=True, timeout=r.remaining())
        except subprocess.TimeoutExpired as error:
            raise BudgetExceeded('Time budget reached during GPU check.') from error

    prepare = ['prepare', '--source', *source, '--out', corpus.parent, *_id_options(args)]
    if args.limit:
        prepare += ['--limit', args.limit]
    r.step('prepare', prepare, [], [corpus, corpus.with_name('prepare_manifest.json')])
    report = {} if args.dry_run else storage.read_json(corpus.with_name('prepare_manifest.json'))
    if args.limit and report and report['rows_read'] < args.limit:
        emit(f"prepare: read {report['rows_read']} rows; --limit {args.limit} is an upper bound.")

    if args.architecture == 'full':
        return _run_full(r, args, out, corpus, queries, links, gpus)

    r.step('cards', ['cards', 'build', '--corpus', corpus, '--out', cards.parent,
                     '--lead-tokens', args.lead_tokens],
           [corpus], [cards, cards.with_name('cards_manifest.json')])
    encoder_batch, rerank_batch, extra = args.encoder_batch, args.rerank_batch, []

    # Translate to the languages the corpus actually holds (>= 1% of documents).
    counts = report.get('languages', {'zh': 1, 'en': 1}) if report else {'zh': 1, 'en': 1}
    total = max(1, sum(counts.values()))
    languages = [lang for lang in ('zh', 'en') if counts.get(lang, 0) / total >= 0.01]
    translations = None
    if args.translations:
        # A file prepared elsewhere (a Kaggle run, a teammate): no translator model is loaded, so
        # a laptop on a slow line does not have to download several GB of weights.
        translations = Path(args.translations).resolve()
        if not translations.is_file():
            raise FileNotFoundError(f'--translations {translations} không tồn tại.')
        generate = None
        emit(f'Dùng bản dịch có sẵn: {translations} (bỏ qua khâu translate)')
    elif not args.skip_translation and (languages or args.hyde):
        translations = out/'translations'/'translations.jsonl'
        generate = {'name': 'translate', 'gpu': gpus[0] if gpus else None,
                    'command': ['translate', '--queries', queries, '--out', translations.parent,
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
    cards_bm25 = {'name': 'cards_bm25', 'command': ['index', 'bm25', '--chunks', cards,
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
    r.step('doc_search', ['retrieve', '--chunks', cards, '--index', cards_index,
                          '--queries', queries, '--out', doc_dir, '--reranker', 'identity',
                          '--device', device, '--search-device', device, '--keyword-variant',
                          '--top-k', k, '--fuse-k', k, '--rerank-k', k, '--keep', k,
                          '--batch-size', encoder_batch, '--weights', weights, *translation_args],
           [cards, cards_index/'bm25.npz', cards_index/'embeddings.npy', *query_inputs],
           [doc_dir/'candidates.jsonl', doc_dir/'retrieval_manifest.json'], gpu=gpus[0] if gpus else None)

    subset_dir = out/'subset'
    subset = subset_dir/'chunks.parquet'
    doc_candidates = subset_dir/'doc_candidates.jsonl'
    r.step('subset', ['cards', 'subset', '--candidates', doc_dir/'candidates.jsonl',
                      '--corpus', corpus, '--out', subset_dir, '--docs-per-query', k,
                      '--target-tokens', 384, '--overlap-tokens', 32, '--max-tokens', 768],
           [doc_dir/'candidates.jsonl', corpus], [subset, doc_candidates])

    subset_index = out/'index'/'subset'
    r.step('subset_bm25', ['index', 'bm25', '--chunks', subset, '--out', subset_index],
           [subset], [subset_index/'bm25.npz', subset_index/'bm25_manifest.json'])
    _dense_steps(r, 'subset_dense', subset, subset_index, args.encoder, gpus, encoder_batch, 1024, extra)

    shards = max(1, len(gpus))
    retrieval = out/'retrieval'
    shard_dirs = [retrieval if shards == 1 else retrieval/f'part{i}' for i in range(shards)]
    retrieve = ['retrieve', '--chunks', subset, '--index', subset_index, '--queries', queries,
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
    target = out/'submission'
    r.step('submit', ['submit', '--candidates', *candidates, '--chunks', subset,
                      '--corpus', corpus, '--queries', queries, '--links', links, '--profile', 'f2',
                      '--window-tokens', args.window_tokens, '--require-complete', '--out', target,
                      *calibration],
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
    p.add_argument('--architecture', choices=['full', 'cascade'], default='full',
                   help='Full corpus chunk search (default); cascade retains the older card gate.')
    from .corpus.prepare import add_id_arguments, validate_id_range
    add_id_arguments(p)
    p.add_argument('--max-hours', type=float, default=None,
                   help='Wall time per invocation, including downloads; 0 disables. Not GPU quota.')
    p.add_argument('--ann', action='store_true', help='Use FAISS IVF for full-corpus search; requires faiss-cpu.')
    p.add_argument('--nprobe', type=int, default=64)
    p.add_argument('--chunk-tokens', type=int, default=384)
    p.add_argument('--overlap-tokens', type=int, default=64)
    p.add_argument('--reuse-corpus', action='store_true',
                   help='Compatibility flag: verified frozen corpus reuse is now automatic. '
                        'Source/options and all recorded output hashes must still match.')
    p.add_argument('--source', nargs='+', default=None,
                   help="Local crawl folders (nguyen, a run directory) or parquet folders; or 'hf' "
                        'to download the team corpus and BTC files from Hugging Face and pin the '
                        'commit for this run. Default: nguyen (local), hf (kaggle).')
    p.add_argument('--hf-repo', default=fetch.CORPUS_REPO, help='Dataset holding corpus/*.parquet.')
    p.add_argument('--hf-revision', default=None,
                   help='Corpus commit; default: pinned for this --out, else the latest.')
    p.add_argument('--out', default=None,
                   help='New run directory; never change the input population of a frozen run.')
    p.add_argument('--limit', type=int, default=None,
                   help='Input rows before quality filtering, shared over the sources by size; '
                        '0 reads everything in the ID range. Default: 100000 on both profiles.')
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
    p.add_argument('--hyde', nargs='*', choices=['zh', 'vi', 'en'], default=[],
                   help='Also generate HyDE passages in these languages (slower; off by default).')
    translation = p.add_mutually_exclusive_group()
    translation.add_argument('--skip-translation', dest='skip_translation', action='store_true')
    translation.add_argument('--enable-translation', dest='skip_translation', action='store_false',
                             help='Legacy cascade only; loads a separate generative model.')
    p.set_defaults(skip_translation=True)
    p.add_argument('--translations', default=None,
                   help='Use this prepared translations.jsonl and skip the translate stage, so no '
                        'translator model is downloaded (e.g. a file generated on Kaggle).')
    p.add_argument('--encoder-batch', type=int, default=None)
    p.add_argument('--rerank-batch', type=int, default=None)
    p.add_argument('--lead-tokens', type=int, default=160)
    p.add_argument('--docs-per-query', type=int, default=None)
    p.add_argument('--rerank-k', type=int, default=None)
    p.add_argument('--window-tokens', type=int, default=0,
                   help='Submitted chunk window; 0 keeps the indexed chunk.')
    p.add_argument('--calibration', default=None, help='calibration.json for the F2 cut.')
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args(argv)
    for key, value in PROFILES[args.profile].items():
        if getattr(args, key, None) is None:
            setattr(args, key, value)
    if args.limit < 0:
        p.error('--limit must be >= 0 (0 reads everything)')
    try:
        validate_id_range(args.id_start, args.id_end)
    except ValueError as error:
        p.error(str(error))
    if args.max_hours < 0 or not math.isfinite(args.max_hours):
        p.error('--max-hours must be finite and >= 0.')
    if not 1 <= args.chunk_tokens <= 768 or not 0 <= args.overlap_tokens < args.chunk_tokens:
        p.error('Require 0 <= overlap < chunk tokens <= 768.')
    if args.nprobe < 1 or min(args.encoder_batch, args.rerank_batch) < 1:
        p.error('nprobe and batch sizes must be positive.')
    if args.architecture == 'full' and (not args.skip_translation or args.hyde):
        p.error('Full pipeline uses original queries: no LLM/HyDE. Cached --translations are optional.')
    if args.architecture == 'cascade' and args.ann:
        p.error('--ann is supported by --architecture full only.')
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
            status = Path(args.out)/'pipeline_status.json'
            storage.write_json(Path(args.out)/'pipeline_config.json', vars(args))
            storage.write_json(status, {'status': 'running', 'config': vars(args)})
            try:
                target = run(args)
            except BudgetExceeded as error:
                storage.write_json(status, {'status': 'budget_exhausted', 'reason': str(error)})
                emit(str(error))
                raise SystemExit(124) from error
            except BaseException as error:
                storage.write_json(status, {'status': 'failed', 'reason': str(error)})
                raise
            storage.write_json(status, {'status': 'complete', 'submission': str(target),
                                       'submission_sha256': storage.sha256_file(target)})


if __name__ == '__main__':
    main()
