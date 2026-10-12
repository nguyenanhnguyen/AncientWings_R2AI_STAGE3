"""Range selection, one-pass orchestration, interrupted-run safety; no model downloads."""
import argparse
import ast
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.append(str(ROOT/'scripts'))
from vibiomir import pipeline
from vibiomir.common import storage
from vibiomir.corpus import fetch, prepare
from test_pipeline import write_fixture


class UnifiedTests(unittest.TestCase):
    def setUp(self):
        self.base = (ROOT/'work/unified_tests').resolve()
        self.out = self.base/uuid.uuid4().hex
        self.out.mkdir(parents=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        assert self.out.resolve().is_relative_to(self.base)
        shutil.rmtree(self.out)

    def test_filter_before_limit_for_parquet_and_live_records(self):
        rows = [{'id': i, 'text': f'Article {i}'} for i in (30, 2, 10, 21, 20, 40)]
        parquet = storage.write_parquet(self.out/'export.parquet', rows)
        records = self.out/'run'/'records'
        records.mkdir(parents=True)
        for row in rows:
            storage.write_json(records/f"{row['id']}.json", row)
        for source in (parquet, records.parent):
            self.assertEqual(prepare.source_size(source, 10, 21), 3)
            got = list(prepare.read_source(source, limit=2, id_start=10, id_end=21))
            self.assertEqual([row['id'] for row in got], [10, 20])
            self.assertEqual([row['id'] for row in prepare.read_source(source, id_start=21, id_end=21)], [21])

    def test_proportional_budget_ignores_sources_outside_range(self):
        sources = []
        for name, ids in (('a', [1, 2, 3]), ('b', [10, 11]), ('c', [20, 21])):
            sources.append(str(storage.write_parquet(self.out/f'{name}.parquet',
                                                     [{'id': i, 'text': f'body {i}'} for i in ids])))
        args = argparse.Namespace(source=sources, out=str(self.out/'prepared'), limit=2,
                                  id_start=10, id_end=21, split='proportional',
                                  max_duplicates=20, min_chars=0, drop_review=False, text_field=None)
        with contextlib.redirect_stdout(io.StringIO()):
            report = prepare.build(args)
        got = storage.read_parquet(self.out/'prepared/corpus.parquet')
        self.assertEqual([row['id'] for row in got], [10, 20])
        self.assertEqual(report['rows_read_per_source'][sources[0]], 0)

    def test_shard_overlap_and_selection_pin(self):
        names = ['corpus/ids_1_9_synced.parquet', 'corpus/ids_10_20_synced.parquet',
                 'corpus/ids_21_30_synced.parquet', 'corpus/legacy.parquet', 'raw/a.parquet']
        self.assertEqual(fetch.select_shards(names, 20, 21), names[1:4])
        fetch.pin_selection(self.out, 20, 21)
        fetch.pin_selection(self.out, 20, 21)
        with self.assertRaisesRegex(ValueError, 'pinned'):
            fetch.pin_selection(self.out, 20, 22)

    def test_one_pass_profiles_and_disjoint_shards(self):
        for profile in ('local', 'kaggle'):
            args = pipeline.parse_args(['--dry-run', '--profile', profile, '--out', str(self.out),
                                        '--id-start', '10', '--id-end', '20'])
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                pipeline.run(args)
            plan = stream.getvalue()
            self.assertTrue(args.skip_translation)
            self.assertEqual(args.architecture, 'full')
            for forbidden in ('[translate]', '[cards]', '[subset]', 'feedback', '--extra-reranker', '--quantized'):
                self.assertNotIn(forbidden, plan)
            self.assertIn('--id-start 10 --id-end 20', plan)
            self.assertIn('--keyword-variant --disk-text', plan)
            if profile == 'kaggle':
                self.assertIn('--shard 0 --shards 2', plan)
                self.assertIn('--shard 1 --shards 2', plan)
                self.assertEqual(plan.count('--reranker qwen3-reranker-4b'), 2)
                self.assertIn('--encoder qwen3-embedding-4b', plan)
            else:
                self.assertEqual(plan.count('--reranker bge-reranker-v2-m3'), 1)

    def test_timeout_records_finished_sibling_and_never_marks_unfinished_stage(self):
        runner = pipeline.Runner(self.out, max_hours=0.01)
        runner._command = lambda command: [sys.executable, '-c', command[0]]
        done = self.out/'done.txt'
        steps = [{'name': 'slow', 'command': ['import time; time.sleep(30)'], 'inputs': [],
                  'outputs': [self.out/'never.txt']},
                 {'name': 'fast', 'command': [f'open({str(done)!r}, "w").write("done")'],
                  'inputs': [], 'outputs': [done]}]
        runner.deadline = time.monotonic() + 2
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(pipeline.BudgetExceeded):
            runner.parallel(steps)
        self.assertTrue((self.out/'stages/fast.json').is_file())
        self.assertFalse((self.out/'stages/slow.json').exists())
        self.assertFalse((self.out/'submission/submission.zip').exists())
        # Even if a previous ZIP exists, this invocation is not labelled complete.
        with patch.object(pipeline, 'run', side_effect=pipeline.BudgetExceeded('budget')), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
            pipeline.main(['--out', str(self.out)])
        self.assertEqual(stop.exception.code, 124)
        self.assertEqual(storage.read_json(self.out/'pipeline_status.json')['status'], 'budget_exhausted')

    def test_full_pipeline_real_stages_to_zip_and_resume(self):
        fixture = write_fixture(self.out)
        out = self.out/'run'
        argv = ['--source', str(fixture['corpus']), '--queries', str(fixture['queries']),
                '--links', str(fixture['links']), '--out', str(out), '--gpus', '0',
                '--encoder', 'hash', '--reranker', 'identity', '--limit', '100',
                '--id-start', '1584', '--id-end', '1586']
        # Identity/hash are restricted to this offline plumbing test, never notebook defaults.
        with contextlib.redirect_stdout(io.StringIO()):
            pipeline.main(argv)
        corpus = storage.read_parquet(out/'corpus/corpus.parquet')
        self.assertEqual([r['id'] for r in corpus], [1584, 1585, 1586])
        status = storage.read_json(out/'pipeline_status.json')
        self.assertEqual(status['status'], 'complete')
        submission = storage.read_json(out/'submission/submission_manifest.json')
        self.assertEqual(submission['submission']['queries'], 3)
        before = {p.name: p.read_bytes() for p in (out/'stages').glob('*.json')}
        with contextlib.redirect_stdout(io.StringIO()), \
                patch('vibiomir.pipeline.subprocess.Popen', side_effect=AssertionError('Expected resume')):
            pipeline.main(argv)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (out/'stages').glob('*.json')})
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, 'verification failed'):
            pipeline.main([*argv[:-1], '1587'])

    def test_notebook_code_matches_source_and_compiles(self):
        import build_notebooks
        notebook = json.loads((ROOT/'notebooks/pipeline_for_kaggle.ipynb').read_text(encoding='utf-8'))
        cells = [''.join(cell['source']) for cell in notebook['cells'] if cell['cell_type'] == 'code']
        for i, code in enumerate(cells):
            compile(code, f'cell{i}', 'exec')
        self.assertIn('ID_START =', cells[0])
        self.assertIn('ID_END =', cells[0])
        embedded = next(code for code in cells if code.startswith(build_notebooks.CODE_MARKER))
        assignments = {node.targets[0].id: ast.literal_eval(node.value)
                       for node in ast.parse(embedded).body if isinstance(node, ast.Assign)
                       and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id in ('CODE_ZIP', 'CODE_SHA256')}
        data = base64.b64decode(assignments['CODE_ZIP'])
        self.assertEqual(hashlib.sha256(data).hexdigest(), assignments['CODE_SHA256'])
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for name in archive.namelist():
                self.assertEqual(archive.read(name), (ROOT/name).read_bytes(), name)


if __name__ == '__main__':
    unittest.main()
