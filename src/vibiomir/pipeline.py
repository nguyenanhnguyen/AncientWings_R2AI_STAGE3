"""Run the local 4 GB profile in isolated processes, with an immutable corpus snapshot."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .common import storage
from .common.cache import cache_key
from .common.console import emit
from .common.runtime import environment

ROOT = Path(__file__).resolve().parents[2]


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

    def step(self, name, command, inputs, outputs):
        cmd = [sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts'/command[0]), *map(str, command[1:])]
        emit(f'\n[{name}] {subprocess.list2cmdline(cmd)}')
        if self.dry_run:
            return
        state_path = self.out / 'stages' / f'{name}.json'
        key = cache_key({'command': cmd, 'inputs': {str(p): storage.sha256_file(p) for p in inputs},
                         'code': self.code_key, 'environment': self.env})
        if state_path.exists():
            state = storage.read_json(state_path)
            if state['key'] == key and all(Path(p).exists() and storage.sha256_file(p) == digest
                                           for p, digest in state['outputs'].items()):
                emit('Dùng lại kết quả đã kiểm tra SHA-256.')
                return
            if name == 'prepare':
                # The source is live. Re-running prepare would change the population mid-run.
                raise ValueError('Frozen corpus/config changed. Choose a new --out to take a new snapshot.')
        logs = self.out / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'TOKENIZERS_PARALLELISM': 'false'}
        with (logs / f'{name}.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            try:
                for line in process.stdout:
                    emit(line.rstrip())
                    log.write(line)
                    log.flush()
                if process.wait():
                    raise RuntimeError(f'Stage {name} failed; see {logs / (name + ".log")}')
            except BaseException:
                process.terminate()
                process.wait()
                raise
            finally:
                process.stdout.close()
        storage.write_json(state_path, {'key': key, 'command': cmd,
                           'seconds': time.monotonic()-started,
                           'outputs': {str(p): storage.sha256_file(p) for p in outputs}})


def run(args):
    out = Path(args.out).resolve()
    source = [str(Path(p).resolve()) for p in args.source]
    corpus = out/'corpus'/'corpus.parquet'
    chunks = out/'chunks'/'chunks.parquet'
    queries, links = Path(args.queries).resolve(), Path(args.links).resolve()
    r = Runner(out, args.dry_run)
    if not args.dry_run and args.device == 'cuda':
        # CUDA probe runs in its own process so no parent CUDA context consumes VRAM later.
        probe = [sys.executable, str(ROOT/'scripts'/'benchmark.py'), '--check-only']
        if not args.skip_translation and args.translation_quantize == '4bit':
            probe.append('--quantized')
        subprocess.run(probe,
                       cwd=ROOT, check=True)
    r.step('prepare', ['prepare.py', '--source', *source, '--limit', args.limit,
                       '--out', corpus.parent], [], [corpus, corpus.with_name('prepare_manifest.json')])
    if not args.dry_run:
        report = storage.read_json(corpus.with_name('prepare_manifest.json'))
        if report['rows_read'] < args.limit:
            raise ValueError(f"Only {report['rows_read']} input rows were available, requested {args.limit}. "
                             'Use a new --out and the actual --limit, or wait for more crawl records.')
    r.step('chunk', ['chunk.py', '--corpus', corpus, '--out', chunks.parent,
                     '--target-tokens', 320, '--overlap-tokens', 80, '--max-tokens', 768],
           [corpus], [chunks, chunks.with_name('chunk_manifest.json')])

    pilot = out/'pilot.json'
    if not args.skip_pilot:
        r.step('pilot', ['benchmark.py', '--chunks', chunks, '--queries', queries, '--out', pilot,
                         '--device', args.device, '--encoders', *args.encoders,
                         '--rerankers', *args.rerankers], [chunks, queries], [pilot])
    report = storage.read_json(pilot) if not args.dry_run and not args.skip_pilot else {'models': []}
    batches = {(m['kind'], m['name']): m['batch_size'] for m in report['models']}
    revisions = {(m['kind'], m['name']): m['model'].get('revision') for m in report['models']}

    languages = ['en', 'zh']
    if not args.dry_run:
        counts = storage.read_json(corpus.with_name('prepare_manifest.json'))['languages']
        languages = [lang for lang in languages if counts.get(lang, 0)]
    corpus_lang = 'zh' if args.zh_corpus else 'en' if args.en_corpus else None
    if corpus_lang:
        # A one-language corpus only needs the query in that language; the other translation costs time for nothing.
        languages = [corpus_lang]
    translations = None
    if args.translations:
        translations = Path(args.translations).resolve()
        if not args.dry_run and not translations.exists():
            raise FileNotFoundError(f'Không thấy file dịch {translations}')
        if not args.dry_run and corpus_lang:
            have = {row.get('lang') for row in storage.iter_jsonl(translations)}
            if corpus_lang not in have:
                raise ValueError(f'{translations} không có bản dịch "{corpus_lang}" (chỉ có {sorted(have)}). '
                                 'Bỏ --translations để pipeline tự dịch.')
        emit(f'Dùng lại bản dịch câu hỏi: {translations}')
    elif not args.skip_translation and languages:
        translations = out/'translations'/'translations.jsonl'
        r.step('translate', ['translate.py', '--queries', queries, '--out', translations.parent,
                             '--device', args.device, '--model', args.translation_model,
                             '--quantize', args.translation_quantize, '--languages', *languages,
                             '--allow-partial'], [queries],
               [translations, translations.with_name('translation_manifest.json')])
    else:
        emit('Bỏ qua dịch: cấu hình tắt dịch hoặc corpus hiện tại không có en/zh.')

    indices = [out/'index'/name for name in args.encoders]
    r.step('bm25', ['index.py', 'bm25', '--chunks', chunks, '--out', indices[0]], [chunks],
           [indices[0]/'bm25.npz', indices[0]/'bm25_manifest.json'])
    for name, index in zip(args.encoders, indices):
        revision = revisions.get(('encoder', name))
        r.step('dense_'+name, ['index.py', 'dense', '--chunks', chunks, '--out', index,
                '--encoder', name, '--device', args.device, '--max-length', 1024,
                '--batch-size', batches.get(('encoder', name), 8), '--shard', 512, '--resume',
                *(['--revision', revision] if revision else [])], [chunks],
               [index/'embeddings.npy', index/'dense_manifest.json'])

    retrieval = out/'retrieval'
    inputs = [chunks, queries, indices[0]/'bm25.npz']
    inputs.extend(p for index in indices for p in (index/'dense_manifest.json', index/'embeddings.npy'))
    if translations:
        inputs.append(translations)
    # Keep the original query strongest; translation channels broaden recall at lower weight.
    weights = {'bm25:keyword': 0.7, 'bm25:translated_en': 0.5, 'bm25:translated_zh': 0.5}
    for name in args.encoders:
        for lang in ('en', 'zh'):
            channel = f'dense:{name}:translated_{lang}' if len(indices)>1 else f'dense:translated_{lang}'
            weights[channel] = 0.5
    if corpus_lang:
        # Vietnamese words do not occur in Chinese or English text: Vietnamese BM25 only matches stray
        # tokens (digits, or Vietnamese syllables that happen to be English words once accents are
        # stripped), and that noise takes rerank slots. The translated query is the real lexical signal.
        weights.update({'bm25:original': 0, 'bm25:keyword': 0, f'bm25:translated_{corpus_lang}': 1.0})
        for name in args.encoders:
            weights[f'dense:{name}:translated_{corpus_lang}' if len(indices) > 1
                    else f'dense:translated_{corpus_lang}'] = 1.0
    r.step('retrieve', ['retrieve.py', '--chunks', chunks, '--index', indices[0],
           '--extra-index', *indices[1:], '--queries', queries, '--out', retrieval,
           '--reranker', args.rerankers[0], '--extra-reranker', *args.rerankers[1:],
           '--device', args.device, '--search-device', args.device, '--keyword-variant',
           '--top-k', 300, '--fuse-k', 600, '--rerank-k', args.rerank_k, '--keep', args.keep,
           '--candidate-per-doc', 4, '--rerank-max-length', 1024,
           '--batch-size', min((batches.get(('encoder', n), 8) for n in args.encoders)),
           '--rerank-batch', min((batches.get(('reranker', n), 4) for n in args.rerankers)),
           '--weights', json.dumps(weights),
           *(['--rerank-query', args.rerank_query] if args.rerank_query != 'original' else []),
           *(['--translations', translations] if translations else [])], inputs,
           [retrieval/'candidates.jsonl', retrieval/'retrieval_manifest.json'])
    for profile in ('recall', 'balanced'):
        target = out/('submission' if profile == 'recall' else 'submission_balanced')
        r.step('submit_'+profile, ['submit.py', '--candidates', retrieval/'candidates.jsonl',
               '--chunks', chunks, '--corpus', corpus, '--queries', queries, '--links', links,
               '--profile', profile, '--require-complete', '--out', target],
               [retrieval/'candidates.jsonl', retrieval/'retrieval_manifest.json', chunks, corpus, queries, links],
               [target/'submission.zip', target/'submission.json', target/'submission_manifest.json'])
    emit(f'\nBài nộp: {out / "submission" / "submission.zip"}')


def main():
    from .index.embedding import ENCODERS
    from .retrieval.rerank import RERANKERS
    from .retrieval.translate import MODELS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', nargs='+', required=True)
    p.add_argument('--out', default='work/rtx2050_60k')
    p.add_argument('--limit', type=int, default=60000, help='Input rows, before quality filtering.')
    p.add_argument('--queries', default='data/query.parquet')
    p.add_argument('--links', default='data/links_corpus.parquet')
    p.add_argument('--device', choices=['cuda', 'cpu'], default='cuda')
    p.add_argument('--encoders', nargs='+', choices=sorted(ENCODERS), default=['bge-m3', 'qwen3-embedding-0.6b'])
    p.add_argument('--rerankers', nargs='+', choices=sorted(RERANKERS), default=['bge-reranker-v2-m3', 'qwen3-reranker-0.6b'])
    p.add_argument('--translation-model', choices=sorted(MODELS), default='qwen3-4b')
    p.add_argument('--translation-quantize', choices=['4bit', 'none'], default='4bit')
    p.add_argument('--skip-translation', action='store_true')
    p.add_argument('--translations', default=None,
                   help='translations.jsonl đã có (vd. work/run_zh1/translations/translations.jsonl); bỏ bước dịch.')
    p.add_argument('--zh-corpus', action='store_true',
                   help='Corpus tiếng Trung: tắt BM25 câu tiếng Việt, dùng câu đã dịch sang tiếng Trung.')
    p.add_argument('--en-corpus', action='store_true',
                   help='Corpus tiếng Anh (PubMed): tắt BM25 câu tiếng Việt, dùng câu đã dịch sang tiếng Anh.')
    p.add_argument('--rerank-query', choices=['original', 'translated_zh', 'translated_en'], default='original',
                   help='Câu hỏi đưa vào reranker: câu gốc tiếng Việt hoặc bản dịch.')
    p.add_argument('--skip-pilot', action='store_true')
    p.add_argument('--rerank-k', type=int, default=200)
    p.add_argument('--keep', type=int, default=100)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if len(set(args.encoders)) != len(args.encoders) or len(set(args.rerankers)) != len(args.rerankers):
        p.error('Model names must be unique.')
    if 'identity' in args.rerankers and len(args.rerankers) > 1:
        p.error('identity cannot be ensembled with a real reranker.')
    if args.zh_corpus and args.en_corpus:
        p.error('Chỉ chọn một trong --zh-corpus và --en-corpus.')
    if (args.zh_corpus or args.en_corpus or args.rerank_query != 'original') and args.skip_translation \
            and not args.translations:
        p.error('--zh-corpus/--en-corpus/--rerank-query translated_* cần câu hỏi đã dịch: bỏ --skip-translation '
                'hoặc truyền --translations.')
    if args.limit < 1 or not 1 <= args.keep <= args.rerank_k <= 600:
        p.error('Require positive limit and 1 <= keep <= rerank-k <= 600')
    if args.dry_run:
        run(args)
    else:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        with run_lock(Path(args.out)/'pipeline.lock'):
            run(args)


if __name__ == '__main__':
    main()
