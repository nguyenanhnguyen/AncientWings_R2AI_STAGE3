"""Diagnostic ZIP replacement must survive brief locks and retain old evidence."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from test_notebook_selenium_fallback import assignments, load_module


ROOT = Path(__file__).resolve().parents[1]


class NotebookDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        cls.root = Path(cls.temp.name)
        nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        pack = assignments(''.join(nb['cells'][6]['source']))
        name = 'diagnostics_snapshot.py'
        body = zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES'][name]))
        if hashlib.sha256(body).hexdigest() != pack['EMBEDDED_SHA256'][name]:
            raise AssertionError('Diagnostics snapshot hash mismatch')
        (cls.root / name).write_bytes(body)
        cls.diagnostics = load_module('archive_retry_test_diagnostics', cls.root / name)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.work = Path(self.case.name)
        self.run = self.work / 'run'
        self.run.mkdir()
        (self.run / 'manifest.json').write_text('{"selected": 0}', encoding='utf-8')
        (self.run / 'notebook_manifest.json').write_text('{"complete": false}', encoding='utf-8')
        (self.run / 'postprocess_status.json').write_text('{"status": "failed"}', encoding='utf-8')
        self.archive = self.work / 'diagnostics.zip'
        with zipfile.ZipFile(self.archive, 'w') as bundle:
            bundle.writestr('metadata/notebook_manifest.json', '{"complete": true}')
        self.previous = self.archive.read_bytes()

    def locked_replace(self, winerror, failures):
        original = Path.replace
        self.replace_calls = 0

        def replace(path, target):
            if Path(target) == self.archive:
                self.replace_calls += 1
                if self.replace_calls <= failures:
                    self.assertEqual(self.archive.read_bytes(), self.previous)
                    error = PermissionError('ZIP is held by another process')
                    if winerror is not None:
                        error.winerror = winerror
                    raise error
            return original(path, target)

        return patch.object(Path, 'replace', replace)

    def test_brief_windows_lock_replaces_stale_manifest_atomically(self):
        for code in (5, 32, 33):
            with self.subTest(winerror=code):
                self.archive.write_bytes(self.previous)
                with self.locked_replace(code, 2), patch.object(self.diagnostics.time, 'sleep') as sleep:
                    self.diagnostics.build_archive(self.run, self.archive)
                self.assertEqual(self.replace_calls, 3)
                self.assertEqual(sleep.call_count, 2)
                with zipfile.ZipFile(self.archive) as bundle:
                    self.assertFalse(json.loads(bundle.read('metadata/notebook_manifest.json'))['complete'])
                    self.assertEqual(json.loads(bundle.read('metadata/postprocess_status.json'))['status'], 'failed')
                self.assertFalse(self.archive.with_name(self.archive.name + '.tmp').exists())

    def test_persistent_windows_lock_propagates_error_and_preserves_old_archive(self):
        with self.locked_replace(32, 100), patch.object(self.diagnostics.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                self.diagnostics.build_archive(self.run, self.archive)
        self.assertEqual(self.replace_calls, 8)
        self.assertEqual(sleep.call_count, 7)
        self.assertLess(sum(call.args[0] for call in sleep.call_args_list), 4)
        self.assertEqual(self.archive.read_bytes(), self.previous)
        self.assertFalse(self.archive.with_name(self.archive.name + '.tmp').exists())

    def test_other_permission_errors_are_not_retried(self):
        with self.locked_replace(None, 100), patch.object(self.diagnostics.time, 'sleep') as sleep:
            with self.assertRaises(PermissionError):
                self.diagnostics.build_archive(self.run, self.archive)
        self.assertEqual(self.replace_calls, 1)
        sleep.assert_not_called()
        self.assertEqual(self.archive.read_bytes(), self.previous)
        self.assertFalse(self.archive.with_name(self.archive.name + '.tmp').exists())


if __name__ == '__main__':
    unittest.main()
