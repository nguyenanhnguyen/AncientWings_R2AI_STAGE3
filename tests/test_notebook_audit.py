"""Empty HTTP error bodies must not stop the notebook audit/export boundary."""
import ast
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]


class NotebookAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        values = {}
        for node in ast.parse(''.join(nb['cells'][6]['source'])).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('EMBEDDED_FILES', 'EMBEDDED_SHA256'):
                    values[node.targets[0].id] = ast.literal_eval(node.value)
        data = zlib.decompress(base64.b85decode(values['EMBEDDED_FILES']['audit_snapshot.py']))
        self.assertEqual(hashlib.sha256(data).hexdigest(), values['EMBEDDED_SHA256']['audit_snapshot.py'])
        script = self.run / 'audit.py'
        script.write_bytes(data)
        spec = importlib.util.spec_from_file_location('audit_regression_fixture', script)
        self.audit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.audit)

        samples = [{'id': i, 'url': f'https://example.org/article/{i}'} for i in range(1, 5)]
        source = self.run / 'source.parquet'
        pq.write_table(pa.Table.from_pylist(samples), source)
        sample_bytes = ''.join(json.dumps(r) + '\n' for r in samples).encode('utf-8')
        (self.run / 'sample.jsonl').write_bytes(sample_bytes)
        (self.run / 'manifest.json').write_text(json.dumps({
            'source': str(source), 'sample_sha256': hashlib.sha256(sample_bytes).hexdigest(),
        }), encoding='utf-8')
        text = 'An intact article with health information. ' * 20
        bodies = [b'', b' \r\n\t ', b'<!-- response comment only -->',
                  f'<html><body><div class="content-editor-post"><p>{text}</p></div></body></html>'.encode()]
        (self.run / 'records').mkdir()
        (self.run / 'raw').mkdir()
        for row, body in zip(samples, bodies):
            raw_path = f'raw/{row["id"]}.gz'
            (self.run / raw_path).write_bytes(gzip.compress(body, mtime=0))
            record = dict(row, raw_path=raw_path, raw_sha256=hashlib.sha256(body).hexdigest(),
                          status='http_error', http_status=521, quality_flags=[])
            if row['id'] == 4:
                record.update(status='extracted', http_status=200, quality_status='accepted',
                              title='Article', text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest())
            (self.run / 'records' / f'{row["id"]}.json').write_text(json.dumps(record), encoding='utf-8')

    def run_audit(self):
        with patch.object(sys, 'argv', ['audit.py', '--out', str(self.run)]), redirect_stdout(io.StringIO()):
            self.audit.main()

    def test_empty_and_unparseable_responses_are_reported_without_stopping_audit(self):
        self.run_audit()
        summary = json.loads((self.run / 'audit_summary.json').read_text(encoding='utf-8'))
        self.assertEqual(summary['completed'], 4)
        self.assertTrue(summary['source_mapping_verified'])
        self.assertTrue(summary['raw_and_text_hashes_verified'])
        self.assertEqual(summary['diagnostic_flags'], {'empty_raw_document': 2, 'unparseable_raw_document': 1})
        cases = [json.loads(line) for line in (self.run / 'audit_cases.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(cases[-1]['quality_status'], 'accepted')
        self.assertEqual(cases[-1]['flags'], [])
        review = [json.loads(line) for line in (self.run / 'review_100.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['id'] for r in review], [4])
        self.assertIn('An intact article', (self.run / 'review_100.html').read_text(encoding='utf-8'))

    def test_empty_body_does_not_bypass_raw_hash_validation(self):
        path = self.run / 'records/1.json'
        record = json.loads(path.read_text(encoding='utf-8'))
        record['raw_sha256'] = 'wrong-hash'
        path.write_text(json.dumps(record), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'Raw hash mismatch: 1'):
            self.run_audit()


if __name__ == '__main__':
    unittest.main()
