"""Disk-pressure regressions: protect originals and prioritize small verified exports."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)/'runs'/'run'
        self.out.mkdir(parents=True)
        self.storage = load('corpus_storage')

    def test_compact_report_keeps_export_text_and_protects_originals(self):
        row = {'id': 1, 'text': 'content', 'requests': [{'body': 'large'}], 'quality_status': 'accepted'}
        for name in ('documents.jsonl', 'corpus.accepted.jsonl'):
            self.storage.write_jsonl(self.out/name, [row])
        self.assertNotIn('text', json.loads((self.out/'documents.jsonl').read_text()))
        self.assertEqual(json.loads((self.out/'corpus.accepted.jsonl').read_text())['text'], 'content')
        protected = ['raw/1.gz', 'records/1.json', 'corpus.parquet', 'audit_summary.json', 'manual_review.jsonl']
        for name in protected:
            path = self.out/name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'keep')
        self.storage.prepare_reports(self.out)
        for name in protected: self.assertEqual((self.out/name).read_bytes(), b'keep')
        self.assertFalse((self.out/'documents.jsonl').exists())

    def checkpoint(self, *, upload=False):
        mod = load('corpus_checkpoint')
        sample = b'{"id":1,"url":"https://example.org/1"}\n'
        (self.out/'sample.jsonl').write_bytes(sample)
        (self.out/'manifest.json').write_text(json.dumps({'selected': 1, 'sample_sha256': hashlib.sha256(sample).hexdigest()}))
        (self.out/'records').mkdir(exist_ok=True)
        (self.out/'records/1.json').write_text('{"id":1,"url":"https://example.org/1"}')
        crawler = SimpleNamespace(load_json=lambda p: json.loads(p.read_text()),
            write_json=lambda p, v: p.write_text(json.dumps(v)), utc=lambda: 'now')
        return mod, mod.PeriodicCheckpoint(crawler, self.out, {'enabled': True, 'upload': upload})

    def test_checkpoint_skips_duplicate_reports_but_retains_resume_records(self):
        mod, backup = self.checkpoint()
        (self.out/'documents.jsonl').write_bytes(b'large duplicate')
        (self.out/'corpus.parquet').write_bytes(b'export')
        archive, proof = backup.build()
        with zipfile.ZipFile(archive) as z:
            self.assertIn('run/records/1.json', z.namelist())
            self.assertIn('run/checkpoint_progress.json', z.namelist())
            self.assertNotIn('run/documents.jsonl', z.namelist())
            self.assertNotIn('run/corpus.parquet', z.namelist())

    def test_insufficient_disk_skips_zip_and_preserves_previous_backup(self):
        mod, backup = self.checkpoint()
        previous = self.out.parent.parent/'run_checkpoint.zip'
        previous.write_bytes(b'previous backup')
        with patch.object(mod.STORAGE, 'free_bytes', return_value=10):
            result = backup.maybe_save(force=True)
        self.assertEqual(result['local_status'], 'failed')
        self.assertEqual(previous.read_bytes(), b'previous backup')
        self.assertTrue((self.out/'records/1.json').exists())

    def test_upload_success_reclaims_local_zip_but_upload_failure_keeps_it(self):
        mod, backup = self.checkpoint(upload=True)
        with patch.object(backup, 'upload', return_value='commit'):
            result = backup.maybe_save(force=True)
        self.assertEqual(result['upload_status'], 'uploaded')
        self.assertFalse(Path(result['local_archive']).exists())
        with patch.object(backup, 'upload', side_effect=RuntimeError('offline')):
            result = backup.maybe_save(force=True)
        self.assertEqual(result['upload_status'], 'failed')
        self.assertTrue(Path(result['local_archive']).exists())

    def test_partial_parquet_is_verified_and_not_marked_final(self):
        import pyarrow.parquet as pq
        row = {'id': 1, 'url': 'https://example.org/1', 'text': 'content', 'quality_status': 'accepted',
               'text_sha256': hashlib.sha256(b'content').hexdigest()}
        (self.out/'corpus.accepted.jsonl').write_text(json.dumps(row)+'\n')
        result = subprocess.run([sys.executable, str(ROOT/'scripts/corpus_export.py'), '--out', str(self.out), '--partial'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(pq.read_table(self.out/'corpus.partial.parquet')['id'].to_pylist(), [1])
        proof = json.loads((self.out/'partial_export_manifest.json').read_text())
        self.assertTrue(proof['provisional'])
        self.assertFalse((self.out/'corpus.parquet').exists())
        self.assertFalse((self.out/'corpus.jsonl').exists())

    def test_optional_results_zip_is_skipped_without_losing_parquet_or_diagnostics(self):
        mod = load('notebook_postprocess')
        parquet = self.out/'corpus.parquet'
        parquet.write_bytes(b'verified parquet')
        diagnostics = self.out.parent.parent/'run_diagnostics.zip'
        def refresh(**kwargs): diagnostics.write_bytes(b'diagnostics')
        with patch.object(mod, 'require_ready', return_value={'counts': {
                'selected': 1, 'completed': 1, 'pending': 0, 'accepted': 1}}), \
                patch.object(mod.STORAGE, 'free_bytes', return_value=10):
            result = mod.package_run(self.out, self.out.parent.parent, id_from=1, id_to=1,
                dataset_revision='rev', source_sha256='sha', packages={}, refresh_diagnostics=refresh)
        self.assertIsNone(result)
        self.assertEqual(parquet.read_bytes(), b'verified parquet')
        self.assertEqual(diagnostics.read_bytes(), b'diagnostics')
        self.assertTrue(json.loads((self.out/'notebook_manifest.json').read_text())['complete'])


if __name__ == '__main__': unittest.main()
