"""Run the 4B retrieval pipeline in isolated processes with a frozen corpus snapshot."""
import argparse
from contextlib import contextmanager
import json
import math
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
        # Crawler and notebook builders have separate lifecycles. Their edits must not
        # invalidate a frozen retrieval run or force corpus preparation to repeat.
        sources = [ROOT/'scripts'/'vibiomir.py', ROOT/'src'/'vibiomir'/'pipeline.py']
        sources += [p for part in ('common', 'corpus', 'index', 'retrieval', 'submission')
                    for p in sorted((ROOT/'src'/'vibiomir'/part).rglob('*.py'))]
        self.code_key = cache_key({str(p.relative_to(ROOT)): storage.sha256_file(p)
                                  for p in sources})
        self.env = environment()

    def step(self, name, command, inputs, outputs):
        # One entry point, one stage name: scripts/ stays a single file instead of ten wrappers.
        cmd = [sys.executable, '-X', 'utf8', '-u', str(ROOT/'scripts'/'vibiomir.py'),
               *map(str, command)]
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


def adopt_embeddings(index, chunks, encoder_name):
    """Register a completed external matrix without recomputing corpus vectors."""
    import numpy as np
    import pyarrow.parquet as pq
    from .index.embedding import ENCODERS

    checkpoint = storage.read_json(index/'checkpoint.json')
    key = checkpoint['key']
    count = pq.ParquetFile(chunks).metadata.num_rows
    expected = ENCODERS[encoder_name]
    if (checkpoint['done'] != count or key['rows'] != count
            or Path(key['chunks']).resolve() != chunks.resolve()
            or key['chunks_size'] != chunks.stat().st_size
            or key['model'] != expected['hf_id']
            or key['dim'] != expected['dim'] or key['dtype'] != 'float16'):
        raise ValueError('Precomputed embeddings do not match this frozen chunks file/model.')
    matrix_path = index/'embeddings.npy'
    matrix = np.load(matrix_path, mmap_mode='r')
    if matrix.shape != (count, expected['dim']) or matrix.dtype != np.float16:
        raise ValueError('Precomputed embedding matrix has the wrong shape or dtype.')
    for start in range(0, count, 1024):
        vectors = np.asarray(matrix[start:start+1024], dtype=np.float32)
        if not np.isfinite(vectors).all() or not np.allclose(
                np.linalg.norm(vectors, axis=1), 1, atol=.01):
            raise ValueError(f'Invalid embedding vectors near row {start}.')
    del matrix
    recorded_manifest = index/'dense_manifest.json'
    digest = storage.sha256_file(chunks)
    if recorded_manifest.exists():
        record = storage.read_json(recorded_manifest)
        expected_file = record.get('files', {}).get('embeddings.npy', {})
        if (record.get('chunks_sha256') != digest or record.get('encoder') != encoder_name
                or expected_file.get('sha256') != storage.sha256_file(matrix_path)):
            raise ValueError('Existing dense manifest belongs to different chunks/model.')
        return
    snapshots = sorted((ROOT/'nguyen'/'hf_pipeline'/'hf_home'/'hub'/
                        ('models--'+expected['hf_id'].replace('/', '--'))/'snapshots').glob('*/config.json'))
    if len(snapshots) != 1:
        raise ValueError('Cannot identify one cached model revision for the precomputed vectors.')
    revision = snapshots[0].parent.name
    config = dict(expected, max_length=key['max_length'], quantize='none', cpu_offload=True)
    storage.write_manifest(recorded_manifest, {
        'stage': 'dense', 'encoder': encoder_name, 'dim': expected['dim'],
        'vectors': count, 'pooling': expected['pooling'],
        'document_text': 'raw chunk text', 'chunks_file': str(chunks),
        'chunks_sha256': digest,
        'model': {'revision': revision, 'max_length': key['max_length'], 'config': config},
    }, files=[matrix_path])


def run(args):
    out = Path(args.out).resolve()
    if args.source == ['hf'] or args.reuse_run:
        if not os.environ.get('HF_TOKEN'):
            # Read the credential from the user's existing login before relocating HF_HOME.
            from huggingface_hub import get_token
            saved_token = get_token()
            if saved_token:
                os.environ['HF_TOKEN'] = saved_token
    # Model downloads from every source belong to the ignored project data tree.
    hf_home = ROOT / 'nguyen' / 'hf_pipeline' / 'hf_home'
    os.environ['HF_HOME'] = str(hf_home)
    os.environ['HF_HUB_CACHE'] = str(hf_home / 'hub')
    source = [str(Path(p).resolve()) for p in args.source if p != 'hf']
    corpus = out/'corpus'/'corpus.parquet'
    chunks = out/'chunks'/'chunks.parquet'
    queries, links = Path(args.queries).resolve(), Path(args.links).resolve()
    r = Runner(out, args.dry_run)
    if args.reuse_run:
        previous = Path(args.reuse_run).resolve()
        if previous == out:
            raise ValueError('--reuse-run requires a different --out directory.')
        corpus, chunks = previous/'corpus'/'corpus.parquet', previous/'chunks'/'chunks.parquet'
        if not corpus.is_file() or not chunks.is_file():
            raise FileNotFoundError('The reused run must have completed corpus and chunks files.')
        previous_chunk = storage.read_json(previous/'chunks'/'chunk_manifest.json')
        if previous_chunk['files']['chunks.parquet']['sha256'] != storage.sha256_file(chunks):
            raise ValueError('The reused chunk file differs from its manifest.')
        snapshot = previous/'stages'/'hf_snapshot.json'
        if snapshot.exists():
            recorded = storage.read_json(snapshot)['outputs']
            queries = next((Path(p) for p in recorded if Path(p).name == 'query.parquet'), queries)
            links = next((Path(p) for p in recorded
                          if Path(p).name == 'links_corpus_vi_en_zh.parquet'), links)
            for path in (queries, links):
                if str(path) in recorded and storage.sha256_file(path) != recorded[str(path)]:
                    raise ValueError(f'Reused snapshot file changed: {path}')
        emit(f'Dùng corpus và chunks đã chốt từ {previous}')
    elif args.source == ['hf']:
        hf_key = cache_key({'repo': args.hf_repo, 'revision': args.hf_revision,
                            'limit': args.limit, 'seed': args.hf_seed,
                            'mode': args.hf_sample_mode,
                            'max_shards': args.hf_max_shards,
                            'language': args.language, 'id_ranges': args.id_range})[:16]
        hf_dir = ROOT / 'nguyen' / 'hf_pipeline' / 'snapshots' / hf_key
        r.step('hf_snapshot', ['hf-snapshot', '--repo', args.hf_repo,
               '--revision', args.hf_revision, '--limit', args.limit,
               '--seed', args.hf_seed, '--sample-mode', args.hf_sample_mode,
               '--max-shards', args.hf_max_shards, '--language', args.language,
               *[item for a, b in args.id_range for item in ('--id-range', f'{a}:{b}')],
               '--out', hf_dir], [], [hf_dir/f'input_{args.language}.parquet',
               hf_dir/'source_manifest.json', hf_dir/'query.parquet',
               hf_dir/'links_corpus_vi_en_zh.parquet'])
        source = [str(hf_dir/f'input_{args.language}.parquet')]
        queries = hf_dir/'query.parquet'
        links = hf_dir/'links_corpus_vi_en_zh.parquet'
    if not args.dry_run and args.device == 'cuda':
        # CUDA probe runs in its own process so no parent CUDA context consumes VRAM later.
        probe = [sys.executable, str(ROOT/'scripts'/'vibiomir.py'), 'benchmark', '--check-only']
        if ((not args.skip_translation and args.translation_quantize == '4bit')
                or args.quantize == '4bit'):
            probe.append('--quantized')
        subprocess.run(probe,
                       cwd=ROOT, check=True)
    if not args.reuse_run:
        r.step('prepare', ['prepare', '--source', *source,
                       *(['--limit', args.limit] if args.limit else []),
                       '--out', corpus.parent], [], [corpus, corpus.with_name('prepare_manifest.json')])
    if not args.dry_run:
        report = storage.read_json(corpus.with_name('prepare_manifest.json'))
        if not args.reuse_run and args.limit and report['rows_read'] < args.limit:
            raise ValueError(f"Only {report['rows_read']} input rows were available, requested {args.limit}. "
                             'Use a new --out and the actual --limit, or wait for more crawl records.')
    if not args.reuse_run:
        r.step('chunk', ['chunk', '--corpus', corpus, '--out', chunks.parent,
                     '--target-tokens', args.chunk_target, '--overlap-tokens', args.chunk_overlap,
                     '--max-tokens', args.model_max_length,
                     '--tokenizer', args.chunk_tokenizer],
           [corpus], [chunks, chunks.with_name('chunk_manifest.json')])

    languages = ([args.language] if args.source == ['hf'] and not args.reuse_run and args.language in ('en', 'zh')
                 else [] if args.source == ['hf'] and args.language == 'vi' else ['en', 'zh'])
    if args.reuse_run:
        languages = ['en', 'zh']
    if not args.dry_run:
        counts = storage.read_json(corpus.with_name('prepare_manifest.json'))['languages']
        languages = [lang for lang in languages if counts.get(lang, 0)]
    if args.zh_corpus:
        # A Chinese corpus only needs the Chinese query; translating to English would cost time for nothing.
        languages = ['zh']
    translations = None
    if args.translations:
        translations = Path(args.translations).resolve()
        if not args.dry_run and not translations.exists():
            raise FileNotFoundError(f'Không thấy file dịch {translations}')
        emit(f'Dùng lại bản dịch câu hỏi: {translations}')
    elif args.stop_after != 'dense' and not args.skip_translation and languages:
        translations = out/'translations'/'translations.jsonl'
        r.step('translate', ['translate', '--queries', queries, '--out', translations.parent,
                             '--device', args.device, '--model', args.translation_model,
                             '--quantize', args.translation_quantize,
                             *(['--cpu-offload'] if args.cpu_offload else []),
                             '--languages', *languages,
                             '--allow-partial'], [queries],
               [translations, translations.with_name('translation_manifest.json')])
    else:
        emit('Bỏ qua dịch: cấu hình tắt dịch hoặc corpus hiện tại không có en/zh.')

    indices = [out/'index'/name for name in args.encoders]
    bm25_index = out/'index'/'bm25'
    if args.precomputed_embeddings:
        indices = [Path(args.precomputed_embeddings).resolve()]
        if len(args.encoders) != 1:
            raise ValueError('A precomputed embedding matrix requires exactly one encoder.')
        if not args.dry_run:
            adopt_embeddings(indices[0], chunks, args.encoders[0])
    if args.stop_after != 'dense':
        r.step('bm25', ['index', 'bm25', '--chunks', chunks, '--out', bm25_index], [chunks],
               [bm25_index/'bm25.npz', bm25_index/'bm25_manifest.json'])
    for name, index in ([] if args.precomputed_embeddings else zip(args.encoders, indices)):
        r.step('dense_'+name, ['index', 'dense', '--chunks', chunks, '--out', index,
                '--encoder', name, '--device', args.device, '--max-length', args.model_max_length,
                '--quantize', args.quantize,
                *(['--cpu-offload'] if args.cpu_offload else []),
                '--batch-size', 1 if args.cpu_offload or args.quantize == '4bit' else 4,
                '--shard', 512, '--resume'], [chunks],
               [index/'embeddings.npy', index/'dense_manifest.json'])

    if args.stop_after == 'dense':
        emit(f'Embedding completed: {indices[0] / "embeddings.npy"}')
        return

    retrieval = out/'retrieval'
    inputs = [chunks, queries, bm25_index/'bm25.npz']
    inputs.extend(p for index in indices for p in (index/'dense_manifest.json', index/'embeddings.npy'))
    if translations:
        inputs.append(translations)
    # Keep the original query strongest; translation channels broaden recall at lower weight.
    weights = {'bm25:keyword': 0.7, 'bm25:translated_en': 0.5, 'bm25:translated_zh': 0.5}
    for name in args.encoders:
        for lang in ('en', 'zh'):
            channel = f'dense:{name}:translated_{lang}' if len(indices)>1 else f'dense:translated_{lang}'
            weights[channel] = 0.5
    if args.zh_corpus:
        # Vietnamese words never occur in Chinese text: Vietnamese BM25 only matches stray Latin tokens
        # and digits, and that noise takes rerank slots. The translated query is the real lexical signal.
        weights.update({'bm25:original': 0, 'bm25:keyword': 0, 'bm25:translated_zh': 1.0})
        for name in args.encoders:
            weights[f'dense:{name}:translated_zh' if len(indices) > 1 else 'dense:translated_zh'] = 1.0
    if args.weights:
        weights.update(json.loads(args.weights))
    r.step('retrieve', ['retrieve', '--chunks', chunks, '--index', indices[0],
           '--bm25-index', bm25_index,
           '--extra-index', *indices[1:], '--queries', queries, '--out', retrieval,
           '--reranker', args.rerankers[0], '--extra-reranker', *args.rerankers[1:],
           '--device', args.device, '--search-device', args.device, '--keyword-variant',
           '--top-k', args.top_k, '--fuse-k', args.fuse_k,
           '--rerank-k', args.rerank_k, '--keep', args.keep,
           '--candidate-per-doc', args.candidate_per_doc,
           '--rerank-max-length', args.model_max_length,
           '--reranker-quantize', args.quantize,
           *(['--reranker-cpu-offload'] if args.cpu_offload else []),
           '--batch-size', 1 if args.precomputed_embeddings or args.cpu_offload or args.quantize == '4bit' else 4,
           '--rerank-batch', 1 if args.cpu_offload or args.quantize == '4bit' else 2,
           '--weights', json.dumps(weights),
           *(['--rerank-query', args.rerank_query] if args.rerank_query != 'original' else []),
           *(['--translations', translations] if translations else [])], inputs,
           [retrieval/'candidates.jsonl', retrieval/'retrieval_manifest.json'])
    for profile in ('recall', 'balanced'):
        target = out/('submission' if profile == 'recall' else 'submission_balanced')
        r.step('submit_'+profile, ['submit', '--candidates', retrieval/'candidates.jsonl',
               '--chunks', chunks, '--corpus', corpus, '--queries', queries, '--links', links,
               '--profile', profile, '--require-complete', '--out', target,
               *(['--adaptive'] if args.adaptive_submit else [])],
               [retrieval/'candidates.jsonl', retrieval/'retrieval_manifest.json', chunks, corpus, queries, links],
               [target/'submission.zip', target/'submission.json', target/'submission_manifest.json'])
    emit(f'\nBài nộp: {out / "submission" / "submission.zip"}')


def main():
    from .index.embedding import ENCODERS
    from .retrieval.rerank import RERANKERS
    from .retrieval.translate import MODELS
    from .corpus.hf_snapshot import parse_id_range
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', nargs='+', default=['hf'],
                   help='hf for the private team dataset, or local run/parquet paths.')
    p.add_argument('--reuse-run', default=None,
                   help='Reuse a completed corpus/chunks run; requires a fresh --out.')
    p.add_argument('--precomputed-embeddings', default=None,
                   help='Completed offload matrix directory with checkpoint.json and embeddings.npy.')
    p.add_argument('--out', default=None,
                   help='Run directory; default is an ignored nguyen/pipeline_runs path keyed by size/source.')
    p.add_argument('--stop-after', choices=['dense'], default=None,
                   help='Stop after corpus, chunks and dense embeddings; resume with the same command without this flag.')
    p.add_argument('--hf-repo', default='AncientWings/AncientWings_R2AI_STAGE3_ds')
    p.add_argument('--hf-revision', default='main')
    p.add_argument('--language', choices=['vi', 'en', 'zh', 'all'], default='all')
    p.add_argument('--id-range', type=parse_id_range, action='append', default=[],
                   help='HF source ID range START:END, inclusive; repeat for multiple ranges.')
    p.add_argument('--hf-seed', type=int, default=13)
    p.add_argument('--hf-sample-mode', choices=['bounded', 'hash'], default='bounded',
                   help='bounded reads shards until the requested limit; hash samples across all shards.')
    p.add_argument('--hf-max-shards', type=int, default=0,
                   help='0 reads every relevant shard; positive values cap the scan.')
    p.add_argument('--limit', type=int, default=0,
                   help='0 selects all matching HF records; positive values build a smaller run.')
    p.add_argument('--queries', default='data/query.parquet')
    p.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    p.add_argument('--device', choices=['cuda', 'cpu'], default='cuda')
    p.add_argument('--encoders', nargs='+', choices=sorted(ENCODERS), default=['qwen3-embedding-4b'])
    p.add_argument('--rerankers', nargs='+', choices=sorted(RERANKERS), default=['qwen3-reranker-4b'])
    p.add_argument('--quantize', choices=['none', '4bit'], default='none',
                   help='FP16 by default; 4bit is an optional lower-memory mode.')
    p.add_argument('--cpu-offload', action='store_true',
                   help='Split FP16 4B weights between GPU and CPU for a small GPU; much slower.')
    p.add_argument('--model-max-length', type=int, default=512)
    p.add_argument('--chunk-tokenizer', default='Qwen/Qwen3-Embedding-4B')
    p.add_argument('--chunk-target', type=int, default=320)
    p.add_argument('--chunk-overlap', type=int, default=80)
    p.add_argument('--top-k', type=int, default=300)
    p.add_argument('--fuse-k', type=int, default=600)
    p.add_argument('--candidate-per-doc', type=int, default=4)
    p.add_argument('--weights', default=None, help='JSON overrides for RRF channel weights; tune on labelled dev.')
    p.add_argument('--adaptive-submit', action='store_true', help='Adaptive evidence selection; validate on dev first.')
    p.add_argument('--translation-model', choices=sorted(MODELS), default='qwen3-4b')
    p.add_argument('--translation-quantize', choices=['4bit', 'none'], default='none')
    p.add_argument('--skip-translation', action='store_true')
    p.add_argument('--translations', default=None,
                   help='translations.jsonl đã có (vd. work/run_zh1/translations/translations.jsonl); bỏ bước dịch.')
    p.add_argument('--zh-corpus', action='store_true',
                   help='Corpus tiếng Trung: tắt BM25 câu tiếng Việt, dùng câu đã dịch sang tiếng Trung.')
    p.add_argument('--rerank-query', choices=['original', 'translated_zh'], default='original',
                   help='Câu hỏi đưa vào reranker: câu gốc tiếng Việt hoặc bản dịch tiếng Trung.')
    p.add_argument('--rerank-k', type=int, default=100)
    p.add_argument('--keep', type=int, default=50)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    if args.reuse_run and args.out is None:
        p.error('--reuse-run requires an explicit new --out.')
    if args.precomputed_embeddings and not args.reuse_run:
        p.error('--precomputed-embeddings requires --reuse-run.')
    if args.cpu_offload and args.quantize != 'none':
        p.error('--cpu-offload requires --quantize none (FP16).')
    if args.cpu_offload and args.translation_quantize != 'none':
        p.error('--cpu-offload requires --translation-quantize none (FP16).')
    if args.cpu_offload and args.device != 'cuda':
        p.error('--cpu-offload requires CUDA.')
    if args.out is None:
        size = ('full' if args.limit == 0 else
                f'{args.limit // 1000}k' if args.limit % 1000 == 0 else str(args.limit))
        source_tag = ('' if args.source == ['hf'] and args.hf_sample_mode == 'bounded'
                      else '_hash' if args.source == ['hf'] else '_local')
        range_tag = '_' + cache_key(args.id_range)[:8] if args.id_range else ''
        args.out = f'nguyen/pipeline_runs/qwen4b_{size}{source_tag}_{args.language}{range_tag}'
    if len(set(args.encoders)) != len(args.encoders) or len(set(args.rerankers)) != len(args.rerankers):
        p.error('Model names must be unique.')
    if not args.reuse_run and 'hf' in args.source and args.source != ['hf']:
        p.error('Use --source hf alone, or list only local paths.')
    if 'identity' in args.rerankers and len(args.rerankers) > 1:
        p.error('identity cannot be ensembled with a real reranker.')
    if (args.zh_corpus or args.rerank_query != 'original') and args.skip_translation and not args.translations:
        p.error('--zh-corpus/--rerank-query translated_zh cần câu hỏi đã dịch: bỏ --skip-translation '
                'hoặc truyền --translations.')
    if args.limit < 0 or not 1 <= args.keep <= args.rerank_k <= 600:
        p.error('Require nonnegative limit and 1 <= keep <= rerank-k <= 600')
    if not args.reuse_run and (args.id_range or args.language != 'all') and args.source != ['hf']:
        p.error('Language/ID filtering is supported for --source hf only.')
    if not args.reuse_run and args.limit == 0 and args.source == ['hf'] and (
            args.hf_sample_mode != 'bounded' or args.hf_max_shards):
        p.error('--limit 0 with HF requires --hf-sample-mode bounded --hf-max-shards 0')
    if args.hf_max_shards < 0:
        p.error('--hf-max-shards must be nonnegative.')
    if args.rerank_k > args.fuse_k or args.top_k < 1 or args.candidate_per_doc < 0:
        p.error('Require positive top-k, nonnegative candidate-per-doc, and rerank-k <= fuse-k.')
    if args.model_max_length < 128 or args.chunk_target < 1 or not 0 <= args.chunk_overlap < args.chunk_target:
        p.error('Invalid model length or chunk size/overlap.')
    if args.quantize == '4bit' and args.device != 'cuda':
        p.error('4-bit local profile requires CUDA.')
    if args.weights:
        try:
            values = json.loads(args.weights)
            if not isinstance(values, dict) or any(not isinstance(v, (int, float))
                                                    or not math.isfinite(v) or v < 0
                                                    for v in values.values()):
                raise ValueError
        except (ValueError, TypeError):
            p.error('--weights must be a JSON object with nonnegative numeric values.')
    if args.dry_run:
        run(args)
    else:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        with run_lock(Path(args.out)/'pipeline.lock'):
            run(args)


if __name__ == '__main__':
    main()
