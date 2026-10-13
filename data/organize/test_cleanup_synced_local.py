"""Offline tests for exact-match local cleanup and shared raw protection."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid

import pyarrow as pa
import pyarrow.parquet as pq

SPEC = importlib.util.spec_from_file_location('cleanup', Path(__file__).with_name('cleanup_synced_local.py'))
cleanup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup)


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.root = (cleanup.ROOT / 'work' / 'hf_cleanup_tests' / uuid.uuid4().hex).resolve()
        self.run = self.root / 'run'
        (self.run / 'records').mkdir(parents=True)
        (self.run / 'raw').mkdir()
        self.db = cleanup.sync.new_database(self.root / 'index.sqlite')

    def tearDown(self):
        self.db.close()
        assert self.root.is_relative_to((cleanup.ROOT / 'work').resolve())
        shutil.rmtree(self.root)

    def record(self, doc_id, raw='raw/shared.gz'):
        text = f'medical text {doc_id}'
        row = {'id': doc_id, 'url': f'https://example.org/{doc_id}', 'text': text,
               'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'raw_path': raw}
        (self.run / raw).write_bytes(b'raw')
        (self.run / 'records' / f'{doc_id}.json').write_text(json.dumps(row), encoding='utf-8')
        self.db.execute('INSERT INTO official VALUES (?,?)', (doc_id, row['url']))
        return row

    def remote(self, row):
        self.db.execute('INSERT INTO remote VALUES (?,?,?,?)',
                        (row['id'], row['url'], row['text_sha256'], 'corpus/shard.parquet'))

    def test_only_exact_remote_match_is_planned_and_shared_raw_survives(self):
        self.remote(self.record(1))
        self.record(2)
        self.db.commit()
        plan, counts = cleanup.collect_plan(self.db, [self.run])
        self.assertEqual([x['id'] for x in plan], [1])
        self.assertEqual(plan[0]['raw'], [])
        self.assertEqual(counts['not_exactly_on_hf_and_official'], 1)

    def test_apply_removes_per_id_files_and_aggregate_rows(self):
        row = self.record(1, 'raw/one.gz')
        self.remote(row)
        self.record(2, 'raw/two.gz')
        self.db.commit()
        (self.run / 'requests_records').mkdir()
        (self.run / 'requests_records' / '1.json').write_text(json.dumps({'raw_path': 'raw/one.gz'}))
        with (self.run / 'documents.jsonl').open('w', encoding='utf-8') as stream:
            for id_ in (1, 2):
                stream.write(json.dumps({'id': id_, 'text': 'test'}) + '\n')
        (self.run / 'duplicates.jsonl').write_text(
            json.dumps({'text_sha256': 'a' * 64, 'doc_ids': [1, 2]}) + '\n', encoding='utf-8')
        pq.write_table(pa.table({'id': [1, 2], 'text': ['one', 'two']}), self.run / 'corpus.parquet')
        plan, _ = cleanup.collect_plan(self.db, [self.run])
        api = SimpleNamespace(repo_info=lambda **kw: SimpleNamespace(sha='revision'))
        counts = cleanup.apply_plan(plan, 'revision', api, 'team/repo')
        self.assertEqual(counts['records_cleaned'], 1)
        self.assertFalse((self.run / 'records' / '1.json').exists())
        self.assertFalse((self.run / 'requests_records' / '1.json').exists())
        self.assertFalse((self.run / 'raw' / 'one.gz').exists())
        self.assertTrue((self.run / 'records' / '2.json').exists())
        self.assertEqual([json.loads(x)['id'] for x in (self.run / 'documents.jsonl').read_text().splitlines()], [2])
        self.assertEqual((self.run / 'duplicates.jsonl').read_text(), '')
        self.assertEqual(pq.read_table(self.run / 'corpus.parquet')['id'].to_pylist(), [2])

    def test_shared_raw_is_removed_once_only_when_all_owners_are_on_hf(self):
        for doc_id in (1, 2):
            self.remote(self.record(doc_id))
        self.db.commit()
        plan, counts = cleanup.collect_plan(self.db, [self.run])
        self.assertEqual(counts['unique_raw_files'], 1)
        api = SimpleNamespace(repo_info=lambda **kw: SimpleNamespace(sha='revision'))
        cleanup.apply_plan(plan, 'revision', api, 'team/repo')
        self.assertFalse((self.run / 'raw/shared.gz').exists())

    def test_changed_checkpoint_blocks_deletion_before_any_file_is_touched(self):
        self.remote(self.record(1, 'raw/one.gz'))
        self.db.commit()
        plan, _ = cleanup.collect_plan(self.db, [self.run])
        (self.run / 'records/1.json').write_text('{"id": 1}', encoding='utf-8')
        api = SimpleNamespace(repo_info=lambda **kw: SimpleNamespace(sha='revision'))
        with self.assertRaisesRegex(RuntimeError, 'changed since preview'):
            cleanup.apply_plan(plan, 'revision', api, 'team/repo')
        self.assertTrue((self.run / 'raw/one.gz').exists())


if __name__ == '__main__':
    unittest.main()
