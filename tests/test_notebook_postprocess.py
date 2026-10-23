"""Recover an old run offline, exercising real report/audit/export and rescue ZIPs."""
import ast
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import Mock, patch
import zipfile
import zlib

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]


class NotebookPostprocessTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.run = self.work / 'runs/ids_1_4_synced'
        self.run.mkdir(parents=True)
        self.nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        values = {}
        for node in ast.parse(''.join(self.nb['cells'][6]['source'])).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('EMBEDDED_FILES', 'EMBEDDED_SHA256'):
                    values[node.targets[0].id] = ast.literal_eval(node.value)
        for name, payload in values['EMBEDDED_FILES'].items():
            data = zlib.decompress(base64.b85decode(payload))
            self.assertEqual(hashlib.sha256(data).hexdigest(), values['EMBEDDED_SHA256'][name])
            (self.run / name).write_bytes(data)
        self.assertEqual((self.run / 'postprocess_snapshot.py').read_text(encoding='utf-8'),
                         (ROOT / 'scripts/notebook_postprocess.py').read_text(encoding='utf-8'))
        (self.run / 'audit_snapshot.py').write_text("raise RuntimeError('old audit: Document is empty')\n")
        (self.run / 'export_snapshot.py').write_text("raise RuntimeError('old exporter')\n")
        samples = [{'id': i, 'url': f'https://example.org/article/{i}', 'domain': 'example.org'}
                   for i in range(1, 5)]
        self.source = self.work / 'input.parquet'
        pq.write_table(pa.Table.from_pylist(samples), self.source)
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        sample_bytes = ''.join(json.dumps(r) + '\n' for r in samples).encode()
        (self.run / 'sample.jsonl').write_bytes(sample_bytes)
        self.write('manifest.json', {
            'source': '/previous/kaggle/session/links.parquet', 'source_sha256': self.source_hash,
            'sample_sha256': hashlib.sha256(sample_bytes).hexdigest(), 'selected': 4,
            'sampling': 'offline regression fixture', 'id_start_inclusive': 1, 'id_stop_exclusive': 5,
        })
        self.write('source_profile.json', {'rows': 4, 'host_counts': {'example.org': 4},
                                           'sample_host_counts': {'example.org': 4}})
        self.write('corpus_config.json', {'version': 'saved-version', 'settings': {'delay': 17}})
        self.write('corpus_settings.json', {'delay': 17, 'browser_mode': 'off'})
        self.write('crawl_config.json', {
            'script_sha256': hashlib.sha256((self.run / 'crawler_snapshot.py').read_bytes()).hexdigest()})
        (self.run / 'notebook_requirements.txt').write_text('preserved dependencies\n')
        (self.run / 'records').mkdir()
        (self.run / 'raw').mkdir()
        text = 'An intact health article with original source information. ' * 20
        bodies = [b'', b' \r\n\t ', b'<!-- comment without document -->',
                  f'<html><body><div class="content-editor-post"><p>{text}</p></div></body></html>'.encode()]
        for sample, body in zip(samples, bodies):
            raw_path = f'raw/{sample["id"]}.gz'
            (self.run / raw_path).write_bytes(gzip.compress(body, mtime=0))
            record = dict(sample, status='http_error', http_status=500, quality_flags=[],
                          raw_path=raw_path, raw_sha256=hashlib.sha256(body).hexdigest())
            if sample['id'] == 4:
                record.update(status='extracted', http_status=200, quality_status='accepted', title='Article',
                              text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                              char_count=len(text), language_hint='latin_or_unknown', final_url=sample['url'],
                              content_type='text/html', extractor='fixture')
            self.write(f'records/{sample["id"]}.json', record)
        self.protected = {p.relative_to(self.run).as_posix(): p.read_bytes()
                          for p in self.run.rglob('*') if p.is_file() and (
                              p.parent.name in ('raw', 'records') or p.name in (
                                  'crawler_snapshot.py', 'priority_probe_snapshot.py', 'corpus_runner_snapshot.py',
                                  'manifest.json', 'sample.jsonl', 'corpus_config.json', 'corpus_settings.json',
                                  'crawl_config.json', 'notebook_requirements.txt'))}
        self.output = io.StringIO()
        display_module = ModuleType('IPython.display')
        display_module.display = Mock()
        display_module.FileLink = lambda value: value
        ipython = ModuleType('IPython')
        ipython.display = display_module
        self.module_patch = patch.dict(sys.modules, {'IPython': ipython, 'IPython.display': display_module})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.env = {'subprocess': subprocess, 'sys': sys}
        config = ''.join(self.nb['cells'][2]['source']).replace('ID_FROM = 583', 'ID_FROM = 1')
        config = config.replace('ID_TO = 1582', 'ID_TO = 4')
        config = config.replace('POSTPROCESS_ONLY = False', 'POSTPROCESS_ONLY = True')
        config = config.replace("WORKDIR = Path('/kaggle/working')", f'WORKDIR = Path({str(self.work)!r})')
        with redirect_stdout(self.output):
            exec(compile(config, 'config-cell', 'exec'), self.env)
        self.env.update(SOURCE_PARQUET=str(self.source), SOURCE_SHA256=self.source_hash,
                        versions={'pyarrow': 'fixture'}, requirements_path=self.run / 'notebook_requirements.txt')
        self.execute(6)

    def write(self, name, value):
        (self.run / name).write_text(json.dumps(value), encoding='utf-8')

    def read(self, name):
        return json.loads((self.run / name).read_text(encoding='utf-8'))

    def execute(self, index):
        with redirect_stdout(self.output):
            exec(compile(''.join(self.nb['cells'][index]['source']), f'cell-{index}', 'exec'), self.env)

    def prepare(self):
        with patch('requests.get', side_effect=AssertionError('Hậu xử lý không tải URL')) as request:
            self.execute(8)
            self.execute(10)
            self.execute(12)
            request.assert_not_called()

    def assert_rescue(self):
        archive = self.work / f'{self.run.name}.zip'
        diagnostics = self.work / f'{self.run.name}_diagnostics.zip'
        self.assertTrue(archive.is_file())
        self.assertTrue(diagnostics.is_file())
        with zipfile.ZipFile(archive) as bundle:
            manifest = json.loads(bundle.read(f'{self.run.name}/notebook_manifest.json'))
            self.assertFalse(manifest['complete'])
            for name, data in self.protected.items():
                self.assertEqual(bundle.read(f'{self.run.name}/{name}'), data)
        with zipfile.ZipFile(diagnostics) as bundle:
            self.assertFalse(json.loads(bundle.read('metadata/notebook_manifest.json'))['complete'])
            self.assertEqual(json.loads(bundle.read('metadata/postprocess_status.json'))['status'], 'failed')
        self.assertFalse(self.read('notebook_manifest.json')['complete'])
        with self.assertRaises(RuntimeError):
            self.env['POSTPROCESS'].require_ready(self.run, self.read('notebook_manifest.json'))

    def test_old_auditor_is_refreshed_and_full_postprocess_keeps_crawl_bytes(self):
        self.assertIn('empty_raw_document', (self.run / 'audit_snapshot.py').read_text(encoding='utf-8'))
        self.assertNotIn('old exporter', (self.run / 'export_snapshot.py').read_text(encoding='utf-8'))
        self.prepare()
        self.execute(14)
        self.execute(18)
        for name, data in self.protected.items():
            self.assertEqual((self.run / name).read_bytes(), data, name)
        self.assertEqual(self.read('audit_summary.json')['diagnostic_flags'],
                         {'empty_raw_document': 2, 'unparseable_raw_document': 1})
        self.assertTrue(self.read('notebook_manifest.json')['complete'])
        self.env['POSTPROCESS'].require_ready(self.run, self.read('notebook_manifest.json'))
        self.assertEqual([r['id'] for r in pq.read_table(self.run / 'corpus.parquet').to_pylist()], [4])
        events = [json.loads(line) for line in (self.run / 'logs/invocations.jsonl').read_text().splitlines()]
        self.assertEqual([r['operation'] for r in events if r['event'] == 'start'],
                         ['report', 'audit_snapshot', 'export_snapshot'])
        with zipfile.ZipFile(self.work / f'{self.run.name}.zip') as bundle:
            self.assertTrue(json.loads(bundle.read(f'{self.run.name}/notebook_manifest.json'))['complete'])

    def test_bad_raw_hash_stays_fatal_and_automatically_creates_both_archives(self):
        self.prepare()
        record = self.read('records/1.json')
        record['raw_sha256'] = 'wrong-hash'
        self.write('records/1.json', record)
        self.protected['records/1.json'] = (self.run / 'records/1.json').read_bytes()
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(14)
        self.assert_rescue()
        self.assertIn('Corrupt raw', (self.run / 'logs/storage_snapshot.log').read_text())

    def test_unexpected_record_id_is_fatal_at_audit_and_does_not_export(self):
        self.prepare()
        self.write('records/999.json', {'id': 999, 'url': 'https://example.org/unexpected', 'status': 'network_error'})
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(14)
        self.assert_rescue()
        self.assertFalse((self.run / 'corpus.parquet').exists())
        self.assertEqual(self.read('postprocess_status.json')['failed_step'], 'audit')

    def test_export_failure_cannot_reuse_an_old_success_marker(self):
        self.prepare()
        self.write('notebook_manifest.json', {'complete': True, 'pending': 0})
        self.write('postprocess_status.json', {'status': 'complete', 'audit_passed': True, 'export_passed': True})
        (self.run / 'export_snapshot.py').write_text("raise RuntimeError('export failed')\n")
        (self.run / 'corpus.parquet').write_bytes(b'stale corpus')
        with self.assertRaises(subprocess.CalledProcessError):
            self.execute(14)
        self.assert_rescue()
        self.assertEqual(self.read('postprocess_status.json')['failed_step'], 'export')

    def test_pending_run_is_packaged_without_audit_export_or_success(self):
        (self.run / 'records/4.json').unlink()
        self.prepare()
        self.execute(14)
        self.execute(18)
        self.assertEqual(self.read('postprocess_status.json')['status'], 'incomplete')
        self.assertFalse(self.read('notebook_manifest.json')['complete'])
        self.assertFalse((self.run / 'audit_summary.json').exists())
        self.assertFalse((self.run / 'corpus.parquet').exists())
        self.assertTrue((self.work / f'{self.run.name}.zip').is_file())

    def test_diagnostic_packaging_error_keeps_full_zip_and_original_exception(self):
        self.env['refresh_diagnostics'] = Mock(side_effect=OSError('diagnostics unavailable'))
        with self.assertRaisesRegex(ValueError, 'original processing error'):
            with redirect_stdout(self.output), self.env['diagnostic_step']('test_failure'):
                raise ValueError('original processing error')
        self.assertTrue((self.work / f'{self.run.name}.zip').is_file())
        self.assertFalse(self.read('notebook_manifest.json')['complete'])
        self.assertIn('diagnostics unavailable', self.output.getvalue())


if __name__ == '__main__':
    unittest.main()
