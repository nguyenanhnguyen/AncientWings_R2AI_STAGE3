"""Offline regression checks for the resumable local profile. No model downloads."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from vibiomir.common import storage
from vibiomir.index import embedding
from vibiomir.retrieval import run as retrieval
from vibiomir.retrieval.rerank import CrossEncoderReranker
from vibiomir.retrieval.translate import check_translation
from vibiomir.retrieval.query import load_translations
from vibiomir.submission import validate, choose


class ResumableTests(unittest.TestCase):
    def test_interrupted_embedding_resumes_only_unfinished_rows_and_refuses_changed_input(self):
        class Encoder:
            name, dim = 'fake', 2
            def __init__(self, fail=False):
                self.calls, self.fail = [], fail
            def encode(self, texts, **kwargs):
                self.calls.extend(texts)
                if self.fail and len(self.calls) > 2:
                    raise RuntimeError('interrupted')
                return np.asarray([[int(t), -int(t)] for t in texts], np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'embeddings.npy'
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                embedding.encode_to_memmap(Encoder(True), ['1','2','3','4'], p, shard=2, resume=True)
            self.assertFalse(p.exists())
            model = Encoder()
            embedding.encode_to_memmap(model, ['1','2','3','4'], p, shard=2, resume=True)
            self.assertEqual(model.calls, ['3','4'])
            np.testing.assert_array_equal(np.load(p), [[1,-1],[2,-2],[3,-3],[4,-4]])
            model.calls.clear()
            embedding.encode_to_memmap(model, ['1','2','3','4'], p, shard=2, resume=True)
            self.assertEqual(model.calls, [])
            with self.assertRaisesRegex(ValueError, 'differs'):
                embedding.encode_to_memmap(model, ['9','2','3','4'], p, shard=2, resume=True)

    def test_blocked_search_equals_brute_force_with_partial_blocks(self):
        rng = np.random.default_rng(42)
        docs, queries = rng.normal(size=(31,7)).astype('float16'), rng.normal(size=(9,7)).astype('float32')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'vectors.npy'
            np.save(p, docs)
            rows, scores = embedding.search(p, queries, 5, block=8, query_block=2)
            expected = queries @ docs.astype('float32').T
            order = np.argsort(-expected, axis=1)[:, :5]
            np.testing.assert_array_equal(rows, order)
            np.testing.assert_allclose(scores, np.take_along_axis(expected, order, 1), rtol=1e-5)

    def test_qwen_suffix_survives_truncation(self):
        class Tokenizer:
            def __call__(self, prompts, **kwargs):
                return {'input_ids': [[7]*kwargs['max_length'] for _ in prompts]}
            def pad(self, inputs, **kwargs):
                return inputs
        scorer = CrossEncoderReranker.__new__(CrossEncoderReranker)
        scorer.config = {'kind': 'causal-yes-no', 'max_length': 128}
        scorer.tokenizer, scorer.prefix_ids, scorer.suffix_ids = Tokenizer(), [1,2], [3,4,5]
        result = scorer._inputs('query', ['long '*1000])['input_ids'][0]
        self.assertEqual(len(result), 128)
        self.assertEqual(result[:2], [1,2])
        self.assertEqual(result[-3:], [3,4,5])

    def test_translations_reject_altered_numbers_and_stale_queries(self):
        self.assertEqual(check_translation('uống 5 mg', 'Take 50 mg', 'en'), 'numbers_changed')
        self.assertIsNone(check_translation('uống 5 mg', 'Take 5 mg', 'en'))
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/'translations.jsonl'
            storage.write_jsonl(p, [{'id': 1, 'lang': 'en', 'text': 'Take 5 mg',
                                     'query_sha256': storage.sha256_text('old query')}])
            with self.assertRaisesRegex(ValueError, 'different query'):
                load_translations(p, [{'id': 1, 'query': 'new query'}])

    def test_unofficial_document_cannot_leak_through_chunk_array(self):
        chunks = {'9:0': {'doc_id': 9, 'text': 'original', 'char_start': 0,
                          'char_end': 8, 'chunk_order': 0}}
        rows, report = validate.build_rows({1: ([9], [{'doc_id': 9, 'chunk_id': '9:0'}])},
                                           chunks, {9: 'original'}, [1], allowed_doc_ids={1})
        self.assertEqual(rows[0]['relevant_chunks'], [])
        self.assertEqual(report['dropped_chunks'], 1)

    def test_document_cap_does_not_admit_low_scoring_chunks_below_ratio(self):
        candidates = [{'doc_id': d, 'chunk_id': f'{d}:{i}', 'chunk_order': i,
                       'ce_score': score} for i, (d, score) in enumerate([(1, .9),(1,.8),(2,.01)])]
        _, chunks = choose.select_for_query({'candidates': candidates, 'documents': []},
                    choose.policy('balanced', chunk_min=1, chunk_per_doc=1))
        self.assertEqual([c['doc_id'] for c in chunks], [1])

    def test_full_cli_snapshot_resume_and_cached_sequential_ensemble(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-local-') as tmp:
            root = Path(tmp)
            corpus = root/'source.jsonl'
            storage.write_jsonl(corpus, [
                {'id': 1, 'text': ('Điều trị sỏi thận cần khám bác sĩ và uống nước. '*40)},
                {'id': 2, 'text': ('Viêm họng gây đau khi nuốt và cần được khám. '*40)}])
            queries, links = root/'queries.parquet', root/'links.parquet'
            storage.write_parquet(queries, [{'id': 1, 'query': 'Điều trị sỏi thận?'}])
            storage.write_parquet(links, [{'id': 1}, {'id': 2}])
            out = root/'run'
            command = [sys.executable, str(ROOT/'scripts/pipeline.py'), '--source', str(corpus),
                       '--out', str(out), '--queries', str(queries), '--links', str(links),
                       '--limit', '2', '--device', 'cpu', '--encoders', 'hash',
                       '--rerankers', 'identity', '--skip-pilot', '--skip-translation']
            first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(first.returncode, 0, first.stdout+first.stderr)
            digest = storage.sha256_file(out/'submission/submission.zip')
            # Simulate the live crawler adding a new document; the existing snapshot stays frozen.
            with corpus.open('a', encoding='utf-8') as f:
                f.write(json.dumps({'id': 3, 'text': 'new article'})+'\n')
            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(second.returncode, 0, second.stdout+second.stderr)
            self.assertIn('Dùng lại', second.stdout)
            self.assertEqual(digest, storage.sha256_file(out/'submission/submission.zip'))

            args = argparse.Namespace(chunks=str(out/'chunks/chunks.parquet'), index=str(out/'index/hash'),
                   queries=str(queries), out=str(out/'ensemble'), translations=None, no_bm25=False,
                   no_dense=False, encoder=None, keyword_variant=True, top_k=10, fuse_k=10,
                   rerank_k=10, keep=10, doc_chunks=3, weights=None, device='cpu', fp32=True,
                   faiss=False, batch_size=2, rerank_batch=2, reranker='fake-a', extra_reranker=['fake-b'])
            live, calls = [], []
            class Fake:
                def __init__(self, name):
                    if live:
                        raise AssertionError('Previous model was not released')
                    self.name = name
                    live.append(name)
                def score(self, query, passages, **kwargs):
                    calls.append(self.name)
                    return np.asarray([.9 if 'sỏi' in p else .1 for p in passages], dtype='float32')
            def release(model):
                if isinstance(model, Fake):
                    live.remove(model.name)
            with patch.object(retrieval, 'load_reranker', side_effect=lambda name, **kw: Fake(name)), \
                 patch.object(retrieval, 'release_model', side_effect=release), \
                 contextlib.redirect_stdout(io.StringIO()):
                retrieval.run(args)
                self.assertEqual(calls, ['fake-a','fake-b'])
                calls.clear()
                retrieval.run(args)
                self.assertEqual(calls, [])
                # Same query id but changed text invalidates the pair cache.
                storage.write_parquet(queries, [{'id': 1, 'query': 'Viêm họng?'}])
                retrieval.run(args)
                self.assertEqual(calls, ['fake-a','fake-b'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
