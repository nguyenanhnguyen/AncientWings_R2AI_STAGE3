"""Full-corpus rebuild smoke test, offline models only."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from vibiomir.common import storage
from vibiomir.rebuild import run, variants


class RebuildTests(unittest.TestCase):
    def test_full_coverage_and_resume_without_old_artifacts(self):
        root = ROOT / 'work/rebuild_tests' / uuid.uuid4().hex
        root.mkdir(parents=True)
        def cleanup():
            assert root.resolve().is_relative_to((ROOT / 'work/rebuild_tests').resolve())
            shutil.rmtree(root)
        self.addCleanup(cleanup)
        base, out = root / 'base', root / 'new'
        corpus = base / 'corpus/corpus.parquet'
        docs = [{'id': i, 'title': 'fever', 'text': 'fever symptoms treatment prevention ' * 30,
                 'status': 'ok'} for i in range(12)]
        corpus.parent.mkdir(parents=True)
        storage.write_parquet(corpus, docs)
        storage.write_json(base / 'stages/prepare.json', {'outputs': {str(corpus): storage.sha256_file(corpus)}})
        queries = root / 'queries.parquet'
        storage.write_parquet(queries, [{'id': 1, 'query': 'fever symptoms'}])
        args = argparse.Namespace(base=base, out=out, queries=queries, links=None,
                                  labels=None, translations=None, encoder='hash', reranker='identity',
                                  extra_reranker=None, device='cpu', encoder_batch=2, rerank_batch=2,
                                  chunk_tokens=384, dry_run=False)
        run(args)
        self.assertEqual(storage.read_json(out / 'chunks/chunk_manifest.json')['documents_with_chunks'], 12)
        self.assertEqual(len(storage.read_json(out / 'summary.json')), 3)
        self.assertFalse((base / 'subset').exists())
        with patch('vibiomir.pipeline.subprocess.Popen', side_effect=AssertionError('Should resume')):
            run(args)
        args.extra_reranker = 'qwen3-reranker-0.6b'
        plan = variants(args)
        self.assertEqual(len(plan), 4)
        self.assertEqual(plan[-1][1], '03_rerank100')
        for _, _, _, command in plan:
            self.assertNotIn('--feedback-candidates', command)
            self.assertNotIn('--translations', command)
            self.assertNotIn('--doc-candidates', command)
        with self.assertRaisesRegex(ValueError, 'changed'):
            run(args)
        if importlib.util.find_spec('faiss'):
            args.out = root / 'scale'
            args.suite = 'scale'
            args.extra_reranker = None
            args.extra_encoder = None
            args.ann_audit = 1
            run(args)
            summary = storage.read_json(args.out / 'summary.json')
            self.assertEqual(len(summary), 5)
            self.assertEqual(summary[-2]['parent'], '03_rerank100')
            self.assertEqual(summary[-1]['parent'], '05_ann16')
            self.assertEqual(summary[-1]['dense_search'][0]['overlap_with_exact_at_k'], 1.0)


if __name__ == '__main__':
    unittest.main()
