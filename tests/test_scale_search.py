"""ANN correctness, disk passage equivalence and provenance checks, using CPU data."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from vibiomir.common import storage
from vibiomir.index import ann, build
from vibiomir.retrieval import run as retrieve
from vibiomir.retrieval.passages import PassageStore
from vibiomir.retrieval.hybrid import make_dense_search


class ScaleTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'work/scale_tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        assert self.root.resolve().is_relative_to((ROOT / 'work/scale_tests').resolve())
        shutil.rmtree(self.root)

    def test_passage_store_cache_and_replacement(self):
        path = self.root / 'chunks.parquet'
        storage.write_parquet(path, [{'title': 'heading', 'text': 'original'},
                                     {'title': '', 'text': 'second'}])
        db = self.root / 'passages.sqlite'
        s = PassageStore(path, db, storage.sha256_file(path), capacity=1)
        try:
            self.assertEqual(s[0], 'heading\noriginal')
            self.assertEqual(s[1], 'second')
            self.assertEqual(s[0], 'heading\noriginal')
        finally:
            s.close()
        storage.write_parquet(path, [{'title': '', 'text': 'changed'}])
        s = PassageStore(path, db, storage.sha256_file(path))
        try:
            self.assertEqual(s[0], 'changed')
        finally:
            s.close()

    @unittest.skipUnless(importlib.util.find_spec('faiss'), 'Install requirements/search.txt for ANN tests')
    def test_ann_full_probe_matches_exact_and_provenance(self):
        vectors = np.random.default_rng(7).normal(size=(200, 16)).astype('float32')
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        np.save(self.root / 'embeddings.npy', vectors)
        storage.write_json(self.root / 'dense_manifest.json', {'chunks_sha256': 'test'})
        report = ann.build(argparse.Namespace(index=self.root, lists=4, train_rows=200, batch=17))
        self.assertEqual(report['rows'], 200)
        search = make_dense_search(self.root / 'embeddings.npy', self.root / 'faiss.index', nprobe=4)
        rows, _ = search(vectors[:5], 10)
        exact = np.argsort(-(vectors[:5] @ vectors.T), axis=1)[:, :10]
        np.testing.assert_array_equal(np.array(rows), exact)
        del search

    def test_retrieve_disk_text_matches_memory(self):
        chunks = self.root / 'chunks.parquet'
        queries = self.root / 'query.parquet'
        index = self.root / 'index'
        rows = [{'chunk_id': f'{i}:0', 'doc_id': i, 'chunk_order': 0, 'lang': 'en',
                 'title': f'title {i}', 'text': f'fever treatment {i}' if i < 4 else 'unrelated news'}
                for i in range(12)]
        storage.write_parquet(chunks, rows)
        storage.write_parquet(queries, [{'id': 1, 'query': 'fever treatment'}])
        with patch.object(sys, 'argv', ['index', 'all', '--chunks', str(chunks),
                                       '--out', str(index), '--encoder', 'hash']):
            build.main()
        common = ['retrieve', '--chunks', str(chunks), '--queries', str(queries),
                  '--index', str(index), '--reranker', 'identity']
        for label, flags in [('memory', []), ('disk', ['--disk-text'])]:
            with patch.object(sys, 'argv', common + ['--out', str(self.root / label)] + flags):
                retrieve.main()
        self.assertEqual(storage.read_jsonl(self.root / 'memory/candidates.jsonl'),
                         storage.read_jsonl(self.root / 'disk/candidates.jsonl'))
        if importlib.util.find_spec('faiss'):
            ann.build(argparse.Namespace(index=index, lists=1, train_rows=12, batch=4))
            with patch.object(sys, 'argv', common + ['--out', str(self.root / 'ann'),
                                   '--disk-text', '--faiss', '--nprobe', '1', '--ann-audit', '1']):
                retrieve.main()
            report = storage.read_json(self.root / 'ann/retrieval_manifest.json')
            self.assertAlmostEqual(report['dense_search'][0]['overlap_with_exact_at_k'], 1.0)
            # A modified vector matrix must not be searched with the old ANN index.
            np.save(index / 'embeddings.npy', np.zeros((12, 256), dtype='float32'))
            with patch.object(sys, 'argv', common + ['--out', str(self.root / 'bad'), '--faiss']):
                with self.assertRaisesRegex(ValueError, 'does not match'):
                    retrieve.main()


if __name__ == '__main__':
    unittest.main()
