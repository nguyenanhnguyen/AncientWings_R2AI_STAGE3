"""Block B CLI: build the BM25 and dense indexes over one chunks.parquet.

Both indexes are positional: row i of chunks.parquet is vector i and BM25 document i. The manifest
records the chunk file's hash, and Block C refuses to run against a chunk file that has changed,
because a shifted row would score the right text under the wrong document id.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from ..common import storage
from ..common.console import emit
from ..common.runtime import model_info, release_model, environment
from ..corpus.chunk import retrieval_text
from . import embedding as dense
from .bm25 import BM25, tokenize


def load_chunks(path):
    rows = storage.read_parquet(path)
    if not rows:
        raise ValueError(f'No chunks in {path}')
    return rows


def _progress(label):
    start = time.monotonic()

    def report(done, total):
        elapsed = time.monotonic() - start
        rate = done / elapsed if elapsed > 0 else 0
        remaining = (total - done) / rate if rate > 0 else float('nan')
        emit(f'{label}: {done}/{total}  {rate:.0f}/s  còn ~{remaining / 60:.1f} phút')

    return report


def build_bm25(args):
    chunks = load_chunks(args.chunks)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tokenized = [tokenize(retrieval_text(chunk)) for chunk in chunks]
    index = BM25.build(tokenized, k1=args.k1, b=args.b)
    path = out / 'bm25.npz'
    index.save(path)
    summary = {'stage': 'bm25', 'chunks': len(chunks), 'terms': len(index.terms),
               'k1': index.k1, 'b': index.b, 'avg_tokens': round(float(index.avgdl), 1),
               'chunks_file': str(args.chunks), 'chunks_sha256': storage.sha256_file(args.chunks)}
    storage.write_manifest(out / 'bm25_manifest.json', summary, files=[path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def build_dense(args):
    chunks = load_chunks(args.chunks)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    encoder = dense.load_encoder(args.encoder, device=args.device, fp16=not args.fp32,
                                 max_length=getattr(args, 'max_length', None),
                                 revision=getattr(args, 'revision', None),
                                 quantize=getattr(args, 'quantize', 'none'))
    info = model_info(encoder)
    texts = [retrieval_text(chunk) for chunk in chunks]
    path = dense.encode_to_memmap(encoder, texts, out / 'embeddings.npy',
                                  batch_size=args.batch_size, shard=args.shard,
                                  progress=_progress('encode'),
                                  resume=getattr(args, 'resume', False),
                                  fingerprint=storage.sha256_file(args.chunks))
    release_model(encoder)
    np.save(out / 'doc_ids.npy', np.array([chunk['doc_id'] for chunk in chunks], dtype=np.int64))
    storage.write_jsonl(out / 'chunk_ids.jsonl',
                        [{'row': position, 'chunk_id': chunk['chunk_id']}
                         for position, chunk in enumerate(chunks)])
    faiss_path = None
    if args.faiss:
        faiss_path = dense.try_faiss(path, out / 'faiss.index', n_list=args.faiss_lists)
        if faiss_path is None:
            emit('faiss không có trong môi trường; bỏ qua, retrieval dùng numpy.')
    summary = {'stage': 'dense', **dense.encoder_report(args.encoder, encoder, len(chunks)),
               'model': info, 'environment': environment(),
               'embeddings': str(path), 'faiss_index': str(faiss_path) if faiss_path else None,
               'chunks_file': str(args.chunks), 'chunks_sha256': storage.sha256_file(args.chunks)}
    storage.write_manifest(out / 'dense_manifest.json', summary, files=[path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def build_all(args):
    return {'bm25': build_bm25(args), 'dense': build_dense(args)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name, function, help_text in (('bm25', build_bm25, 'Keyword index only.'),
                                      ('dense', build_dense, 'Vector index only.'),
                                      ('all', build_all, 'Both indexes.')):
        step = sub.add_parser(name, help=help_text)
        step.add_argument('--chunks', default='work/chunks/chunks.parquet')
        step.add_argument('--out', default='work/index')
        step.add_argument('--k1', type=float, default=1.5)
        step.add_argument('--b', type=float, default=0.75)
        step.add_argument('--encoder', default='bge-m3', choices=sorted(dense.ENCODERS))
        step.add_argument('--device', default=None, help='cuda, cpu; default picks cuda if present')
        step.add_argument('--batch-size', type=int, default=16)
        step.add_argument('--shard', type=int, default=20000)
        step.add_argument('--resume', action='store_true', help='Resume flushed embedding shards.')
        step.add_argument('--max-length', type=int, default=None)
        step.add_argument('--revision', default=None, help='Hugging Face commit or tag.')
        step.add_argument('--fp32', action='store_true', help='Disable fp16 on GPU.')
        step.add_argument('--quantize', choices=['none', '4bit'], default='none')
        step.add_argument('--faiss', action='store_true', help='Also write a faiss index if installed.')
        step.add_argument('--faiss-lists', type=int, default=4096)
        step.set_defaults(func=function)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
