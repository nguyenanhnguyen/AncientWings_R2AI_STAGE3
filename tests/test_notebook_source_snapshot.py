"""Source upgrades must preserve resume provenance and avoid poisoning the cache."""
import ast
from contextlib import nullcontext, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def literals(source):
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                pass
    return values


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        self.sample_nb = json.loads((ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        self.config_source = ''.join(self.nb['cells'][2]['source'])

    def configure(self, *, postprocess=False, resume=None):
        source = self.config_source.replace("WORKDIR = Path('/kaggle/working')", f'WORKDIR = Path({str(self.work)!r})')
        if postprocess:
            source = source.replace('POSTPROCESS_ONLY = False', 'POSTPROCESS_ONLY = True')
        if resume:
            source = source.replace('RESUME_RUN_PATH = None', f'RESUME_RUN_PATH = {str(resume)!r}')
        env = {'__name__': '__main__', 'hashlib': hashlib}
        with redirect_stdout(io.StringIO()):
            exec(compile(source, 'config', 'exec'), env)
        return env

    def checkpoint(self, path, source_hash):
        path.mkdir(parents=True)
        (path / 'manifest.json').write_text(json.dumps({
            'source_sha256': source_hash, 'id_start_inclusive': 583, 'id_stop_exclusive': 1583}), encoding='utf-8')
        (path / 'sample.jsonl').write_text('', encoding='utf-8')
        (path / 'crawler_snapshot.py').write_text('', encoding='utf-8')
        (path / 'records').mkdir()

    def test_default_download_uses_same_snapshot_as_domain_samples(self):
        env = self.configure()
        sample = literals(''.join(self.sample_nb['cells'][7]['source']))
        self.assertEqual(env['SOURCE_SHA256'], sample['SOURCE_SHA256'])
        self.assertEqual(env['DATASET_REVISION'], sample['SOURCE_REVISION'])
        self.assertEqual(env['SOURCE_PATH'].name, sample['SOURCE_FILE'])
        body = b'new source download fixture'
        env['SOURCE_SHA256'] = hashlib.sha256(body).hexdigest()
        env['diagnostic_step'] = lambda name: nullcontext()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.iter_content.return_value = [body]
        with patch('requests.get', return_value=response) as request, redirect_stdout(io.StringIO()):
            exec(compile(''.join(self.nb['cells'][8]['source']), 'source', 'exec'), env)
        request.assert_called_once_with(
            f"https://huggingface.co/datasets/AIGuruTinix/ViBioMIR/resolve/{sample['SOURCE_REVISION']}/{sample['SOURCE_FILE']}",
            stream=True, timeout=(15, 90))
        self.assertEqual(env['SOURCE_PATH'].read_bytes(), body)
        self.assertFalse(env['SOURCE_PATH'].with_suffix('.download').exists())

    def test_legacy_resume_is_rejected_before_copying_checkpoint(self):
        legacy = literals(self.config_source)['LEGACY_SOURCE']
        previous = self.work / 'input/old_run'
        self.checkpoint(previous, legacy['sha256'])
        with patch('shutil.copytree') as copy, self.assertRaisesRegex(ValueError, 'RECOVERY_RUN_PATH'):
            self.configure(resume=previous)
        copy.assert_not_called()

    def test_new_run_does_not_reuse_legacy_default_directory(self):
        legacy = literals(self.config_source)['LEGACY_SOURCE']
        previous = self.work / 'runs/ids_583_1582_synced'
        self.checkpoint(previous, legacy['sha256'])
        original = (previous / 'manifest.json').read_bytes()
        env = self.configure()
        self.assertNotEqual(env['RUN_DIR'], previous)
        self.assertEqual((previous / 'manifest.json').read_bytes(), original)

    def test_postprocess_keeps_legacy_source_and_selects_new_run_when_present(self):
        legacy = literals(self.config_source)['LEGACY_SOURCE']
        old = self.work / 'runs/ids_583_1582_synced'
        self.checkpoint(old, legacy['sha256'])
        env = self.configure(postprocess=True)
        self.assertEqual(env['RUN_DIR'], old)
        self.assertEqual(env['SOURCE_SHA256'], legacy['sha256'])
        self.assertEqual(env['DATASET_REVISION'], legacy['revision'])
        self.assertEqual(env['SOURCE_PATH'].name, legacy['filename'])
        new = self.configure()
        self.checkpoint(new['RUN_DIR'], new['SOURCE_SHA256'])
        processed = self.configure(postprocess=True)
        self.assertEqual(processed['RUN_DIR'], new['RUN_DIR'])
        self.assertEqual(processed['SOURCE_SHA256'], new['SOURCE_SHA256'])

    def test_explicit_postprocess_resume_preserves_legacy_run_provenance(self):
        legacy = literals(self.config_source)['LEGACY_SOURCE']
        previous = self.work / 'input/custom_legacy_run'
        self.checkpoint(previous, legacy['sha256'])
        original = (previous / 'manifest.json').read_bytes()
        env = self.configure(postprocess=True, resume=previous)
        self.assertEqual(env['RUN_DIR'].name, previous.name)
        self.assertEqual((env['RUN_DIR'] / 'manifest.json').read_bytes(), original)
        self.assertEqual(env['SOURCE_SHA256'], legacy['sha256'])
        self.assertEqual(env['DATASET_REVISION'], legacy['revision'])
        self.assertTrue(env['SOURCE_URL'].endswith('/' + legacy['filename']))

    def test_wrong_input_does_not_overwrite_verified_cached_source(self):
        env = self.configure()
        source = env['SOURCE_PATH']
        source.parent.mkdir(parents=True)
        source.write_bytes(b'verified new source')
        wrong = self.work / 'legacy.parquet'
        wrong.write_bytes(b'old source')
        env.update(SOURCE_PARQUET=str(wrong), SOURCE_SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
                   diagnostic_step=lambda name: nullcontext())
        with patch('requests.get') as request, self.assertRaisesRegex(ValueError, 'cache'):
            exec(compile(''.join(self.nb['cells'][8]['source']), 'source', 'exec'), env)
        request.assert_not_called()
        self.assertEqual(source.read_bytes(), b'verified new source')


if __name__ == '__main__':
    unittest.main()
