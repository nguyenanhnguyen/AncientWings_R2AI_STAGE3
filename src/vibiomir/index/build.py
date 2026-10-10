"""Block B CLI: build the BM25 and dense indexes over one chunks.parquet.

Both indexes are positional: row i of chunks.parquet is vector i and BM25 document i. The manifest
records the chunk file's hash, and Block C refuses to run against a chunk file that has changed,
because a shifted row would score the right text under the wrong document id.
"""
import argparse
import json
import os
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


def _part_range(total, part, parts):
    """Contiguous rows [start, end) of part `part` out of `parts`."""
    return total * part // parts, total * (part + 1) // parts


def _part_path(out, part, parts):
    return Path(out) / 'parts' / f'embeddings.part{part:02d}-of-{parts:02d}.npy'


def build_dense(args):
    """Encode every chunk, or one contiguous part of them when --parts > 1.

    Parts let two GPUs encode one matrix at once (Kaggle T4 x2): each process encodes its rows
    into its own file, and `dense-merge` concatenates them into the same embeddings.npy a single
    run would have written.
    """
    chunks = load_chunks(args.chunks)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    parts, part = getattr(args, 'parts', 1) or 1, getattr(args, 'part', 0) or 0
    if not 0 <= part < parts:
        raise ValueError('--part must be in [0, --parts).')
    if parts > len(chunks):
        raise ValueError('More parts than chunks; use fewer --parts.')
    start, end = _part_range(len(chunks), part, parts)
    encoder = dense.load_encoder(args.encoder, device=args.device, fp16=not args.fp32,
                                 max_length=getattr(args, 'max_length', None),
                                 revision=getattr(args, 'revision', None))
    info = model_info(encoder)
    texts = [retrieval_text(chunk) for chunk in chunks[start:end]]
    chunks_sha = storage.sha256_file(args.chunks)
    target = out / 'embeddings.npy' if parts == 1 else _part_path(out, part, parts)
    path = dense.encode_to_memmap(encoder, texts, target,
                                  batch_size=args.batch_size, shard=args.shard,
                                  progress=_progress(f'encode {part + 1}/{parts}'),
                                  resume=getattr(args, 'resume', False),
                                  # A whole-file run keeps the old key so existing checkpoints
                                  # still resume.
                                  fingerprint=chunks_sha if parts == 1
                                  else f'{chunks_sha}:{start}:{end}')
    release_model(encoder)
    report = dense.encoder_report(args.encoder, encoder, len(chunks))
    if parts > 1:
        storage.write_json(target.with_suffix('.json'), {
            'part': part, 'parts': parts, 'rows': [start, end], 'encoder': args.encoder,
            'report': report, 'model': info, 'chunks_sha256': chunks_sha,
            'sha256': storage.sha256_file(target)})
        emit(f'Đã encode phần {part + 1}/{parts}: hàng {start}..{end}')
        return {'stage': 'dense-part', 'part': part, 'parts': parts, 'rows': [start, end]}
    return _publish_dense(args, chunks, path, report, info, chunks_sha)


def _publish_dense(args, chunks, path, report, info, chunks_sha):
    out = Path(args.out)
    np.save(out / 'doc_ids.npy', np.array([chunk['doc_id'] for chunk in chunks], dtype=np.int64))
    storage.write_jsonl(out / 'chunk_ids.jsonl',
                        [{'row': position, 'chunk_id': chunk['chunk_id']}
                         for position, chunk in enumerate(chunks)])
    faiss_path = None
    if getattr(args, 'faiss', False):
        faiss_path = dense.try_faiss(path, out / 'faiss.index', n_list=args.faiss_lists)
        if faiss_path is None:
            emit('faiss không có trong môi trường; bỏ qua, retrieval dùng numpy.')
    summary = {'stage': 'dense', **report, 'model': info, 'environment': environment(),
               'embeddings': str(path), 'faiss_index': str(faiss_path) if faiss_path else None,
               'chunks_file': str(args.chunks), 'chunks_sha256': chunks_sha}
    storage.write_manifest(out / 'dense_manifest.json', summary, files=[path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def merge_dense(args):
    """Concatenate the parts written by `dense --part i --parts n` into embeddings.npy."""
    chunks = load_chunks(args.chunks)
    out = Path(args.out)
    chunks_sha = storage.sha256_file(args.chunks)
    parts = args.parts
    metas = []
    for part in range(parts):
        path = _part_path(out, part, parts)
        meta_path = path.with_suffix('.json')
        if not path.exists() or not meta_path.exists():
            raise FileNotFoundError(f'Missing embedding part {part + 1}/{parts}: {path}')
        meta = storage.read_json(meta_path)
        if meta['chunks_sha256'] != chunks_sha:
            raise ValueError(f'Part {part + 1} was encoded from a different chunks file.')
        if meta['rows'] != list(_part_range(len(chunks), part, parts)):
            raise ValueError(f'Part {part + 1} covers rows {meta["rows"]}, not its share.')
        if storage.sha256_file(path) != meta['sha256']:
            raise ValueError(f'Part {part + 1} failed its checksum.')
        metas.append((path, meta))
    names = {meta['encoder'] for _path, meta in metas}
    revisions = {meta['model'].get('revision') for _path, meta in metas}
    if len(names) != 1 or len(revisions) != 1:
        raise ValueError('Parts were encoded by different models; vectors would not be comparable.')
    first = np.load(metas[0][0], mmap_mode='r')
    target = out / 'embeddings.npy'
    temporary = out / 'embeddings.merging.npy'
    store = np.lib.format.open_memmap(temporary, mode='w+', dtype=first.dtype,
                                      shape=(len(chunks), first.shape[1]))
    try:
        for path, meta in metas:
            start, end = meta['rows']
            store[start:end] = np.load(path, mmap_mode='r')
        store.flush()
    finally:
        del store, first
    os.replace(temporary, target)
    _path, meta = metas[0]
    return _publish_dense(args, chunks, target, meta['report'], meta['model'], chunks_sha)


def build_all(args):
    return {'bm25': build_bm25(args), 'dense': build_dense(args)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    for name, function, help_text in (('bm25', build_bm25, 'Keyword index only.'),
                                      ('dense', build_dense, 'Vector index only.'),
                                      ('dense-merge', merge_dense, 'Join dense parts.'),
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
        step.add_argument('--faiss', action='store_true', help='Also write a faiss index if installed.')
        step.add_argument('--faiss-lists', type=int, default=4096)
        step.add_argument('--part', type=int, default=0, help='This process encodes part i...')
        step.add_argument('--parts', type=int, default=1, help='...of n contiguous row ranges.')
        step.set_defaults(func=function)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
