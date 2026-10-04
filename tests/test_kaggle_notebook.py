"""Exercise notebook cells offline without installing packages or fetching websites."""
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/crawl_corpus_kaggle.ipynb'


class KaggleNotebookTests(unittest.TestCase):
    def setUp(self):
        self.notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
        self.code = [c['source'] for c in self.notebook['cells'] if c['cell_type'] == 'code']

    def test_structure_and_invalid_id_range(self):
        self.assertEqual(self.notebook['nbformat'], 4)
        self.assertEqual(len({c['id'] for c in self.notebook['cells']}), len(self.notebook['cells']))
        for i, source in enumerate(self.code):
            compile(source, f'notebook-cell-{i}', 'exec')
        with self.assertRaisesRegex(ValueError, 'ID_FROM'):
            exec(self.code[0].replace('ID_TO = 1582', 'ID_TO = 582'), {})

    def test_inclusive_selection_export_and_resume(self):
        display_module = types.ModuleType('IPython.display')
        display_module.display = lambda *args, **kwargs: None
        display_module.FileLink = lambda path: path
        with tempfile.TemporaryDirectory(prefix='vibiomir-notebook-') as temporary:
            workdir = Path(temporary).resolve()
            fixture = workdir / 'fixture.parquet'
            pq.write_table(pa.table({
                'id': [9000, 585, 583],
                'url': ['https://example.org/9000', 'https://example.org/585', 'https://example.org/583'],
            }), fixture)
            configuration = self.code[0].replace("Path('/kaggle/working')", f'Path({str(workdir)!r})')
            configuration = configuration.replace('ID_TO = 1582', 'ID_TO = 585')
            namespace = {}
            with patch.dict(sys.modules, {'IPython.display': display_module}), redirect_stdout(io.StringIO()):
                exec(configuration, namespace)
                with patch('subprocess.run') as install:
                    install.return_value = types.SimpleNamespace(stdout='Offline installer fixture\\n', returncode=0)
                    exec(self.code[1], namespace)
                    self.assertEqual(install.call_count, 1)
                exec(self.code[2], namespace)
                self.assertTrue(namespace['diagnostics_archive'].is_file())
                for snapshot, module in [('crawler_snapshot.py', 'crawler.py'),
                                         ('finalize_snapshot.py', 'finalize.py'),
                                         ('diagnostics_snapshot.py', 'diagnostics.py')]:
                    self.assertEqual((namespace['RUN_DIR'] / snapshot).read_bytes(),
                                     (ROOT / 'src/vibiomir/corpus' / module).read_bytes())
                namespace['SOURCE_SHA256'] = hashlib.sha256(fixture.read_bytes()).hexdigest()
                namespace['SOURCE_PARQUET'] = str(fixture)
                valid_hash = namespace['SOURCE_SHA256']
                namespace['SOURCE_SHA256'] = 'wrong_hash'
                with self.assertRaisesRegex(ValueError, 'Parquet'):
                    exec(self.code[3], namespace)
                with zipfile.ZipFile(namespace['diagnostics_archive']) as archive:
                    self.assertIn('logs/notebook_errors.log', archive.namelist())
                    self.assertIn(b'ValueError', archive.read('logs/notebook_errors.log'))
                namespace['SOURCE_SHA256'] = valid_hash
                exec(self.code[3], namespace)
                exec(self.code[4], namespace)
                self.assertEqual([r['id'] for r in namespace['selected']], [583, 585])
                self.assertEqual(namespace['missing_count'], 1)

                spec = importlib.util.spec_from_file_location('notebook_crawler', namespace['CRAWLER'])
                crawler = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(crawler)

                class OfflineFetcher:
                    def fetch(self, url, trace):
                        trace.update(http_status=200, final_url=url, redirects=[],
                                     content_type='text/html; charset=utf-8')
                        doc_id = url.rsplit('/', 1)[-1]
                        text = f'Clinical study source evidence for document {doc_id}. ' * 40
                        return f'<html><head><title>Document {doc_id}</title></head><body><article><p>{text}</p></article></body></html>'.encode()

                run = namespace['RUN_DIR']
                sample = [json.loads(line) for line in (run / 'sample.jsonl').read_text(encoding='utf-8').splitlines()]
                record = crawler.crawl_one(sample[0], OfflineFetcher(), run)
                self.assertEqual(record['quality_status'], 'accepted')
                exec(self.code[6], namespace)
                self.assertEqual(namespace['summary']['pending'], 1)
                self.assertFalse((run / 'audit_summary.json').exists())
                self.assertEqual(pq.read_table(run / 'corpus.parquet').num_rows, 1)
                exec(self.code[7], namespace)
                exec(self.code[8], namespace)
                self.assertFalse(json.loads((run / 'notebook_manifest.json').read_text())['complete'])
                with zipfile.ZipFile(namespace['diagnostics_archive']) as archive:
                    self.assertIsNone(archive.testzip())
                    diagnosis = json.loads(archive.read('summary.json'))
                    self.assertEqual(diagnosis['completed'], 1)
                    self.assertEqual(diagnosis['pending'], 1)
                    self.assertIn('overview.html', archive.namelist())
                    self.assertIn('logs/pip_install.log', archive.namelist())
                    self.assertIn('environment.json', archive.namelist())
                    self.assertIn('code/crawler_snapshot.py', archive.namelist())
                    self.assertIn('samples/records/583.json', archive.namelist())
                    self.assertTrue(any(name.startswith('samples/raw/') for name in archive.namelist()))
                    self.assertFalse(any(name.startswith('raw/') or name.endswith('corpus.parquet') for name in archive.namelist()))

                record = crawler.crawl_one(sample[1], OfflineFetcher(), run)
                self.assertEqual(record['quality_status'], 'accepted')
                exec(self.code[5], namespace)  # Both checkpoints exist: zero network requests.
                exec(self.code[6], namespace)
                exec(self.code[7], namespace)
                exec(self.code[8], namespace)
                self.assertEqual(namespace['summary']['pending'], 0)
                with zipfile.ZipFile(namespace['diagnostics_archive']) as archive:
                    self.assertEqual(json.loads(archive.read('summary.json'))['pending'], 0)
                self.assertTrue((run / 'audit_summary.json').exists())
                self.assertEqual(pq.read_table(run / 'corpus.parquet')['id'].to_pylist(), [583, 585])
                with zipfile.ZipFile(namespace['archive']) as archive:
                    self.assertIsNone(archive.testzip())
                    self.assertIn(f'{run.name}/crawler_snapshot.py', archive.namelist())
                    self.assertIn(f'{run.name}/records/583.json', archive.namelist())
                records_before = {p.name: p.read_bytes() for p in (run / 'records').glob('*.json')}
                self.assertEqual(namespace['diagnostic_summary']['completed'], 2)

                restore_config = configuration.replace('RUN_TAG = None', "RUN_TAG = 'restored'")
                restore_config = restore_config.replace('RESUME_RUN_PATH = None', f'RESUME_RUN_PATH = {str(run)!r}')
                restored = {}
                exec(restore_config, restored)
                with patch('subprocess.run') as install:
                    install.return_value = types.SimpleNamespace(stdout='', returncode=0)
                    exec(self.code[1], restored)
                    self.assertIn('-r', install.call_args.args[0])
                exec(self.code[2], restored)
                restored['SOURCE_SHA256'] = namespace['SOURCE_SHA256']
                exec(self.code[3], restored)
                exec(self.code[4], restored)
                exec(self.code[5], restored)
                exec(self.code[6], restored)
                records_after = {p.name: p.read_bytes() for p in (restored['RUN_DIR'] / 'records').glob('*.json')}
                self.assertEqual(records_after, records_before)
                self.assertEqual(restored['summary']['accepted'], 2)


if __name__ == '__main__':
    unittest.main()
