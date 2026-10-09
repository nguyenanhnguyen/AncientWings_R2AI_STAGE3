"""Offline checks: python -m unittest discover -s notebooks -p test_sync_local_corpus_to_hf.py"""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
import uuid
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

SPEC = importlib.util.spec_from_file_location('sync_local', Path(__file__).with_name('sync_local_corpus_to_hf.py'))
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        test_root = (sync.ROOT / 'work/hf_sync_tests').resolve()
        self.root = test_root / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        def cleanup():
            if not self.root.resolve().is_relative_to(test_root):
                raise ValueError('Test cleanup escaped its workspace')
            shutil.rmtree(self.root)
        self.addCleanup(cleanup)
        self.run = self.root / 'run'
        (self.run / 'records').mkdir(parents=True)
        (self.run / 'raw').mkdir()
        sync.write_json(self.run / 'manifest.json', {'source_sha256': sync.SOURCE_SHA256})
        self.db = sync.new_database(self.root / 'plan.sqlite')
        self.addCleanup(self.db.close)

    def record(self, doc_id=1, text='Medical source text.', quality='accepted'):
        body = f'<p>{text}</p>'.encode()
        relative = f'raw/{doc_id}.gz'
        (self.run / relative).write_bytes(gzip.compress(body))
        row = {'id': doc_id, 'url': f'https://example.org/{doc_id}', 'text': text,
               'title': 'Title', 'status': 'extracted', 'quality_status': quality,
               'raw_path': relative, 'raw_sha256': hashlib.sha256(body).hexdigest(),
               'text_sha256': hashlib.sha256(text.encode()).hexdigest()}
        sync.write_json(self.run / f'records/{doc_id}.json', row)
        return row

    def entries(self):
        return self.db.execute('SELECT id,url,digest,run,record FROM pending ORDER BY id').fetchall()

    def test_dedup_preserves_different_source_ids_and_excludes_review(self):
        row = self.record(1)
        self.record(2)  # Same text, different official ID must be kept.
        self.record(3, quality='review')
        self.db.execute('INSERT INTO remote VALUES (?,?,?,?)', (*sync.fingerprint(row), 'corpus/old.parquet'))
        counts = sync.plan_local(self.db, [self.run], self.root)
        self.assertEqual(counts, {'scanned': 3, 'duplicate_remote': 1, 'new': 1, 'not_accepted': 1})
        self.assertEqual(self.entries()[0][0], 2)

    def test_conflicting_id_is_reported_and_not_planned(self):
        row = self.record()
        self.db.execute('INSERT INTO remote VALUES (?,?,?,?)', (1, row['url'], 'a' * 64, 'corpus/old.parquet'))
        counts = sync.plan_local(self.db, [self.run], self.root)
        self.assertEqual(counts['conflicts'], 1)
        self.assertEqual(self.entries(), [])
        self.assertEqual(json.loads((self.root / 'conflicts.jsonl').read_text())['id'], 1)

    def test_unfinished_json_is_deferred(self):
        (self.run / 'records/2.json').write_text('{')
        self.assertEqual(sync.plan_local(self.db, [self.run], self.root)['deferred'], 1)

    def test_keep_remote_skips_content_conflicts_but_retains_new_ids(self):
        row = self.record(1)
        self.record(2)
        self.db.execute('INSERT INTO remote VALUES (?,?,?,?)', (1, row['url'], 'a' * 64, 'corpus/old.parquet'))
        counts = sync.plan_local(self.db, [self.run], self.root, on_conflict='keep-remote')
        self.assertEqual(counts['conflicts_kept_remote'], 1)
        self.assertEqual([entry[0] for entry in self.entries()], [2])
        self.assertEqual(json.loads((self.root / 'conflicts.jsonl').read_text())['action'], 'keep_remote')

    def test_keep_remote_still_blocks_url_mismatch(self):
        row = self.record()
        self.db.execute('INSERT INTO remote VALUES (?,?,?,?)', (1, 'https://other.org/1', row['text_sha256'], 'old'))
        counts = sync.plan_local(self.db, [self.run], self.root, on_conflict='keep-remote')
        self.assertEqual(counts['conflicts'], 1)
        self.assertEqual(counts.get('conflicts_kept_remote', 0), 0)
        self.assertEqual(json.loads((self.root / 'conflicts.jsonl').read_text())['action'], 'blocked')

    def test_archive_resolves_corpus_raw_and_preserves_original_record(self):
        row = self.record()
        sync.plan_local(self.db, [self.run], self.root)
        files = sync.make_shard(self.entries(), self.root / 'stage', 'batch', sync.REPO)
        exported = pq.read_table(self.root / 'stage/corpus.parquet').to_pylist()[0]
        with zipfile.ZipFile(self.root / 'stage/batch.zip') as bundle:
            self.assertEqual(hashlib.sha256(gzip.decompress(bundle.read('batch/' + exported['raw_path']))).hexdigest(),
                             row['raw_sha256'])
            record_name = next(n for n in bundle.namelist() if '/records/' in n)
            self.assertEqual(json.loads(bundle.read(record_name)), row)
        self.assertEqual(tuple(exported), sync.FIELDS)
        self.assertEqual(len(files), 5)
        for entry in sync.read_json(self.root / 'stage/upload_manifest.json')['files']:
            local = next(p for p, remote in files if remote == entry['path_in_repo'])
            self.assertEqual(sync.sha_file(local), entry['sha256'])

    def test_tampered_raw_rejected_even_without_archive(self):
        self.record()
        sync.plan_local(self.db, [self.run], self.root)
        (self.run / 'raw/1.gz').write_bytes(gzip.compress(b'changed'))
        with self.assertRaisesRegex(ValueError, 'Raw SHA-256 mismatch'):
            sync.make_shard(self.entries(), self.root / 'stage', 'batch', sync.REPO, archive=False)

    def test_evidence_path_cannot_escape_run(self):
        with self.assertRaises(ValueError):
            sync.evidence_path(self.run, '../outside.gz')

    def test_remote_index_accepts_notebook_schema_and_detects_conflicts(self):
        row = self.record()
        path = self.root / 'remote.parquet'
        pq.write_table(pa.Table.from_pylist([{k: row[k] for k in ('id', 'url', 'text_sha256')}]), path)
        api = SimpleNamespace(token='test', list_repo_files=lambda **kw: ['corpus/run.parquet', 'archives/run.zip'])
        sync.index_remote(self.db, api, sync.REPO, 'revision', self.root, lambda **kw: str(path))
        self.assertEqual(self.db.execute('SELECT id FROM remote').fetchone()[0], 1)
        row['text_sha256'] = 'b' * 64
        pq.write_table(pa.Table.from_pylist([{k: row[k] for k in ('id', 'url', 'text_sha256')}]), path)
        with self.assertRaisesRegex(ValueError, 'conflicting id=1'):
            sync.index_remote(self.db, api, sync.REPO, 'revision', self.root, lambda **kw: str(path))

    def test_upload_passes_parent_and_never_deletes(self):
        calls = []
        api = SimpleNamespace(create_commit=lambda **kw: calls.append(kw) or SimpleNamespace(oid='new', commit_url='url'))
        result = sync.commit_shard(api, sync.REPO, 'old', [(self.root / 'a', 'corpus/a.parquet')],
                                   'a', 1, lambda **kw: ('add', kw))
        self.assertEqual(result, ('new', 'url'))
        self.assertEqual(calls[0]['parent_commit'], 'old')
        self.assertEqual(calls[0]['operations'][0][0], 'add')

    def test_concurrent_upload_aborts_for_fresh_dedup(self):
        class Conflict(Exception):
            response = SimpleNamespace(status_code=409)
        def fail(**kwargs):
            raise Conflict()
        api = SimpleNamespace(create_commit=fail)
        with self.assertRaisesRegex(RuntimeError, 'HF changed'):
            sync.commit_shard(api, sync.REPO, 'old', [], 'batch', 3, lambda **kw: kw)


if __name__ == '__main__':
    unittest.main()
