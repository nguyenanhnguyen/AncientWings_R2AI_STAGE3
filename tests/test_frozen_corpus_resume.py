"""Regression: an unrelated code/CLI change must not invalidate a frozen corpus."""
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from vibiomir.pipeline import Runner
from vibiomir.common import storage


class FrozenCorpusResumeTests(unittest.TestCase):
    def setUp(self):
        self.base = (ROOT / 'work/frozen_resume_tests').resolve()
        self.out = self.base / uuid.uuid4().hex
        self.out.mkdir(parents=True)
        self.addCleanup(self.cleanup)
        self.files = [self.out / 'corpus.parquet', self.out / 'prepare_manifest.json']
        for path in self.files:
            path.write_bytes(b'unchanged frozen output')
        self.options = ['--source', str(ROOT / 'nguyen'), '--out', str(self.out), '--limit', '100000']
        self.state = {'key': 'old-code-and-environment',
                      'command': [sys.executable, '-X', 'utf8', '-u', str(ROOT / 'scripts/prepare.py'),
                                  *self.options],
                      'outputs': {str(p): storage.sha256_file(p) for p in self.files}}
        self.state_path = self.out / 'stages/prepare.json'
        storage.write_json(self.state_path, self.state)

    def cleanup(self):
        assert self.out.resolve().is_relative_to(self.base)
        shutil.rmtree(self.out)

    def run_prepare(self, options=None):
        with patch('vibiomir.pipeline.subprocess.Popen', side_effect=AssertionError('Must not read live crawl')):
            Runner(self.out).step('prepare', ['prepare', *(options or self.options)], [], self.files)

    def test_legacy_wrapper_reuses_without_flag_and_preserves_provenance(self):
        self.run_prepare()
        self.assertEqual(json.loads(self.state_path.read_text()), self.state)

    def test_dispatcher_reuses_after_code_and_environment_changes(self):
        self.state['command'] = [sys.executable, '-X', 'utf8', '-u',
                                 str(ROOT / 'scripts/vibiomir.py'), 'prepare', *self.options]
        storage.write_json(self.state_path, self.state)
        self.run_prepare()

    def test_changed_limit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_prepare([*self.options[:-1], '200000'])

    def test_changed_source_is_rejected(self):
        options = self.options.copy()
        options[1] = str(ROOT / 'other-source')
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_prepare(options)

    def test_changed_output_is_rejected(self):
        self.files[0].write_bytes(b'modified')
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_prepare()

    def test_missing_output_is_rejected(self):
        self.files[1].unlink()
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_prepare()

    def test_incomplete_checkpoint_is_rejected(self):
        self.state['outputs'] = {}
        storage.write_json(self.state_path, self.state)
        with self.assertRaisesRegex(ValueError, 'verification failed'):
            self.run_prepare()


if __name__ == '__main__':
    unittest.main()
