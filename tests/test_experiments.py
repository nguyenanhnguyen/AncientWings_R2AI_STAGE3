"""CPU integration: feedback, validated ZIPs, snapshot isolation and resume."""
import argparse
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from vibiomir.common import storage
from vibiomir.index.bm25 import BM25, tokenize
from vibiomir.retrieval.feedback import expand
from vibiomir.pipeline import Runner
from vibiomir.experiments import run


class ExperimentsTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / 'work/experiment_tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        assert self.root.resolve().is_relative_to((ROOT / 'work/experiment_tests').resolve())
        shutil.rmtree(self.root)

    def test_feedback_uses_distinct_documents_and_excludes_original_terms(self):
        texts = ['fever marker unique', 'fever marker', *['unrelated'] * 10]
        bm = BM25.build([tokenize(t) for t in texts])
        chunks = {str(i): {'doc_id': i, 'text': t} for i, t in enumerate(texts)}
        chunks['duplicate'] = {'doc_id': 0, 'text': texts[0]}
        terms, trace = expand([{'chunk_id': i} for i in ['0', 'duplicate', '1']],
                              chunks, bm, ['fever'])
        self.assertEqual(terms, ['marker'])
        self.assertEqual(trace['seed_doc_ids'], [0, 1])

    def test_end_to_end_and_resume(self):
        base, out = self.root / 'base', self.root / 'experiments'
        index = base / 'index'
        index.mkdir(parents=True)
        docs, chunks = [], []
        for i in range(12):
            text = 'fever marker information' if i < 2 else f'unrelated content number {i}'
            docs.append({'id': i, 'text': text, 'title': '', 'url': f'https://example.org/{i}'})
            chunks.append({'chunk_id': f'{i}:0', 'doc_id': i, 'chunk_order': 0,
                           'char_start': 0, 'char_end': len(text), 'text': text,
                           'title': '', 'lang': 'en', 'n_tokens': len(tokenize(text)), 'domain': ''})
        cp, qp, dp = base / 'chunks.parquet', base / 'queries.parquet', base / 'corpus.parquet'
        storage.write_parquet(cp, chunks)
        storage.write_parquet(qp, [{'id': 1, 'query': 'fever'}])
        storage.write_parquet(dp, docs)
        BM25.build([tokenize(c['text']) for c in chunks]).save(index / 'bm25.npz')
        retrieval = base / 'retrieval'
        submission = base / 'submission'
        r = Runner(base)
        r.step('retrieve', ['retrieve', '--chunks', cp, '--queries', qp, '--index', index,
                           '--no-dense', '--reranker', 'identity', '--shards', '1',
                           '--fuse-k', '400', '--rerank-k', '50', '--keep', '50', '--out', retrieval],
               [cp, qp], [retrieval / 'candidates.jsonl', retrieval / 'retrieval_manifest.json'])
        r.step('submit', ['submit', '--chunks', cp, '--queries', qp, '--corpus', dp,
                         '--candidates', retrieval / 'candidates.jsonl', '--profile', 'f2',
                         '--window-tokens', '768', '--require-complete', '--out', submission],
               [cp, qp, dp], [submission / 'submission.json', submission / 'submission.zip',
                             submission / 'submission_manifest.json'])
        before = storage.sha256_file(submission / 'submission.json')
        args = argparse.Namespace(base=str(base), out=str(out), suite='overnight',
                                  labels=None, dry_run=False)
        run(args)
        self.assertEqual(len(storage.read_json(out / 'summary.json')), 9)
        trace = storage.read_jsonl(out / 'feedback1/retrieval/feedback_trace.jsonl')[0]
        self.assertIn('marker', trace['terms'])
        self.assertEqual(storage.sha256_file(out / 'baseline/submission/submission.json'), before)
        self.assertEqual(storage.sha256_file(submission / 'submission.json'), before)
        with patch('vibiomir.pipeline.subprocess.Popen', side_effect=AssertionError('Must resume')):
            run(args)
        storage.write_parquet(qp, [{'id': 1, 'query': 'different'}])
        with self.assertRaisesRegex(ValueError, 'changed'):
            run(args)


if __name__ == '__main__':
    unittest.main()
