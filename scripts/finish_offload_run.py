"""Resume the completed English 4B embedding run through retrieval and submission."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['HF_HOME'] = str(ROOT / 'nguyen/hf_pipeline/hf_home')
os.environ['HF_HUB_CACHE'] = str(ROOT / 'nguyen/hf_pipeline/hf_home/hub')

import numpy as np
import pyarrow.parquet as pq
from vibiomir.common import storage
from vibiomir.index.embedding import ENCODERS
from vibiomir.pipeline import Runner, run_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, default=ROOT/'nguyen/pipeline_runs/en_batches_01_08')
    parser.add_argument('--rerank-k', type=int, default=100)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    if not 50 <= args.rerank_k <= 200:
        parser.error('--rerank-k must be between 50 and 200')
    run = args.run.resolve()
    chunks = run/'chunks/chunks.parquet'
    corpus = run/'corpus/corpus.parquet'
    index = run/'qwen4b_cpu_offload'
    state = storage.read_json(index/'checkpoint.json')
    key = state['key']
    count = pq.ParquetFile(chunks).metadata.num_rows
    if state['done'] != count or key['rows'] != count:
        raise ValueError('Embedding is not complete for this corpus')
    if (Path(key['chunks']).resolve() != chunks or key['chunks_size'] != chunks.stat().st_size
            or key['model'] != 'Qwen/Qwen3-Embedding-4B' or key['dtype'] != 'float16'):
        raise ValueError('Embedding checkpoint does not match this run')
    digest = storage.sha256_file(chunks)
    original = storage.read_json(run/'stages/chunk.json')['outputs']
    if original.get(str(chunks)) != digest:
        raise ValueError('Chunks changed since the original chunk stage')
    matrix = np.load(index/'embeddings.npy', mmap_mode='r')
    if matrix.shape != (count, 2560) or matrix.dtype != np.float16:
        raise ValueError(f'Unexpected embedding matrix: {matrix.shape}, {matrix.dtype}')
    for start in range(0, count, 1024):
        block = np.asarray(matrix[start:start+1024], dtype=np.float32)
        if not np.isfinite(block).all() or not np.allclose(np.linalg.norm(block, axis=1), 1, atol=.01):
            raise ValueError(f'Invalid embeddings near row {start}')
    del matrix
    snapshot = storage.read_json(run/'stages/hf_snapshot.json')['outputs']
    queries = next(Path(p) for p in snapshot if Path(p).name == 'query.parquet')
    links = next(Path(p) for p in snapshot if Path(p).name == 'links_corpus_vi_en_zh.parquet')
    for path in (queries, links):
        if storage.sha256_file(path) != snapshot[str(path)]:
            raise ValueError(f'Snapshot changed: {path}')
    cache = Path(os.environ['HF_HUB_CACHE'])/'models--Qwen--Qwen3-Embedding-4B'
    revision = '5cf2132abc99cad020ac570b19d031efec650f2b'
    if not (cache/'snapshots'/revision/'config.json').exists():
        raise FileNotFoundError('The original embedding model revision is not cached')
    print(f'Validated {count:,} normalized vectors; query rows: {pq.ParquetFile(queries).metadata.num_rows}', flush=True)
    if args.check_only:
        return
    out = run/f'finish_4b_rerank06b_k{args.rerank_k}'
    out.mkdir(parents=True, exist_ok=True)
    with run_lock(out/'pipeline.lock'):
        config = dict(ENCODERS['qwen3-embedding-4b'], max_length=key['max_length'],
                      quantize='none', cpu_offload=True)
        storage.write_manifest(index/'dense_manifest.json', {
            'stage': 'dense', 'encoder': 'qwen3-embedding-4b', 'dim': 2560,
            'vectors': count, 'pooling': 'last', 'document_text': 'raw chunk text',
            'chunks_sha256': digest, 'chunks_file': str(chunks),
            'model': {'revision': revision, 'max_length': key['max_length'], 'config': config},
        }, files=[index/'embeddings.npy'])
        runner = Runner(out)
        runner.step('bm25', ['index', 'bm25', '--chunks', chunks, '--out', index],
                    [chunks], [index/'bm25.npz', index/'bm25_manifest.json'])
        candidates = out/'retrieval/candidates.jsonl'
        runner.step('retrieve', ['retrieve', '--chunks', chunks, '--index', index,
                    '--queries', queries, '--out', candidates.parent, '--device', 'cuda',
                    '--search-device', 'cpu', '--batch-size', '1',
                    '--reranker', 'qwen3-reranker-0.6b', '--reranker-quantize', 'none',
                    '--rerank-batch', '1', '--rerank-max-length', '512',
                    '--top-k', '200', '--fuse-k', '200', '--rerank-k', args.rerank_k,
                    '--keep', '50', '--candidate-per-doc', '2', '--keyword-variant'],
                    [chunks, queries, index/'dense_manifest.json', index/'bm25.npz'],
                    [candidates, candidates.with_name('retrieval_manifest.json')])
        for profile in ('recall', 'balanced'):
            target = out/f'submission_{profile}'
            runner.step('submit_'+profile, ['submit', '--candidates', candidates,
                        '--chunks', chunks, '--corpus', corpus, '--queries', queries,
                        '--links', links, '--profile', profile, '--require-complete', '--out', target],
                        [candidates, chunks, corpus, queries, links],
                        [target/'submission.zip', target/'submission_manifest.json'])
        print(f'Submissions: {out}', flush=True)


if __name__ == '__main__':
    main()
