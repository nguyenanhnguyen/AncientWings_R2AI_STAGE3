"""Build a reusable FAISS IVF index from existing vectors, without encoding again."""
import argparse
from pathlib import Path
import time

import numpy as np

from ..common import storage


def build(args):
    import faiss
    directory = Path(args.index)
    path = directory / 'embeddings.npy'
    matrix = np.load(path, mmap_mode='r')
    n, dim = matrix.shape
    if n == 0 or min(args.lists, args.train_rows, args.batch) < 1:
        raise ValueError('Nonempty embeddings and positive ANN parameters required.')
    # Keep >= 40 training samples per centroid; sampling is deterministic.
    train_rows = min(n, args.train_rows)
    lists = min(args.lists, max(1, train_rows // 40))
    index = faiss.IndexIVFFlat(faiss.IndexFlatIP(dim), dim, lists, faiss.METRIC_INNER_PRODUCT)
    started = time.monotonic()
    ids = np.sort(np.random.default_rng(13).choice(n, train_rows, replace=False))
    index.train(np.ascontiguousarray(matrix[ids], dtype=np.float32))
    for start in range(0, n, args.batch):
        index.add(np.ascontiguousarray(matrix[start:start + args.batch], dtype=np.float32))
    target = directory / 'faiss.index'
    temporary = directory / 'faiss.building.index'
    faiss.write_index(index, str(temporary))
    temporary.replace(target)
    dense = storage.read_json(directory / 'dense_manifest.json')
    report = {'kind': 'IVFFlat', 'rows': n, 'dim': dim, 'lists': lists,
              'train_rows': train_rows, 'seed': 13, 'seconds': time.monotonic() - started,
              'embeddings_sha256': storage.sha256_file(path),
              'chunks_sha256': dense['chunks_sha256']}
    storage.write_manifest(directory / 'ann_manifest.json', report, files=[target])
    print(report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--index', required=True)
    p.add_argument('--lists', type=int, default=1024)
    p.add_argument('--train-rows', type=int, default=50000)
    p.add_argument('--batch', type=int, default=8192)
    build(p.parse_args())
