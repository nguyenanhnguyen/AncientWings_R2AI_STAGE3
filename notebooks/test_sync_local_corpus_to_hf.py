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

import normalize_hf_corpus_names as naming

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

    def test_canonical_name_and_collision_checks(self):
        self.assertEqual(sync.canonical_run_name(12, 40), 'ids_12_40_synced')
        old = 'local-nguyen_12_40_' + 'a' * 20
        paths = naming.artifact_paths(old)
        self.assertEqual(naming.rename_plan([old], paths)[0][1], 'ids_12_40_synced')
        with self.assertRaisesRegex(ValueError, 'Destination already exists'):
            naming.rename_plan([old], paths + ['corpus/ids_12_40_synced.parquet'])
        second = 'other_12_40_' + 'b' * 20
        with self.assertRaisesRegex(ValueError, 'Two old runs'):
            naming.rename_plan([old, second], paths + naming.artifact_paths(second))
        self.assertEqual(naming.rename_plan(['ids_12_40_synced'], []), [])

    def test_rename_updates_zip_and_hashes_without_rewriting_corpus(self):
        row = self.record()
        sync.plan_local(self.db, [self.run], self.root)
        old = 'local-nguyen_1_1_' + 'a' * 20
        files = dict((remote, local) for local, remote in sync.make_shard(
            self.entries(), self.root / 'legacy', old, sync.REPO))
        old_parquet_hash = sync.sha_file(files[f'corpus/{old}.parquet'])
        _, new, mapping = naming.rename_plan([old], files)[0]
        changes = naming.prepare_rename(old, new, mapping, files.__getitem__, self.root / 'renamed')
        self.assertNotIn(f'corpus/{new}.parquet', changes)
        self.assertEqual(old_parquet_hash, sync.sha_file(files[f'corpus/{old}.parquet']))
        proof = sync.read_json(changes[f'manifests/{new}/upload_manifest.json'])
        self.assertEqual(proof['run_name'], new)
        for item in proof['files']:
            self.assertNotIn(old, item['path_in_repo'])
            if item['path_in_repo'] in changes:
                self.assertEqual(item['sha256'], sync.sha_file(changes[item['path_in_repo']]))
        with zipfile.ZipFile(changes[f'archives/{new}.zip']) as bundle:
            self.assertTrue(all(p.startswith(new + '/') for p in bundle.namelist()))
            record = next(p for p in bundle.namelist() if '/records/' in p)
            self.assertEqual(json.loads(bundle.read(record)), row)
            self.assertEqual(json.loads(bundle.read(new + '/notebook_manifest.json'))['run_name'], new)

    def test_rename_rejects_tampered_manifest(self):
        self.record()
        sync.plan_local(self.db, [self.run], self.root)
        old = 'local-nguyen_1_1_' + 'a' * 20
        files = dict((remote, local) for local, remote in sync.make_shard(
            self.entries(), self.root / 'legacy', old, sync.REPO))
        path = files[f'manifests/{old}/notebook_manifest.json']
        manifest = sync.read_json(path)
        manifest['accepted'] = 999
        sync.write_json(path, manifest)
        _, new, mapping = naming.rename_plan([old], files)[0]
        with self.assertRaisesRegex(ValueError, 'hash/size mismatch'):
            naming.prepare_rename(old, new, mapping, files.__getitem__, self.root / 'renamed')


if __name__ == '__main__':
    unittest.main()
