import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('check_ask39', ROOT/'scripts/check_ask39.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class Ask39CheckTests(unittest.TestCase):
    def test_audit_detects_missing_followup_and_sidebar_contamination(self):
        audit_spec = importlib.util.spec_from_file_location('ask39_audit', ROOT/'scripts/ask39_audit.py')
        audit = importlib.util.module_from_spec(audit_spec)
        audit_spec.loader.exec_module(audit)
        sidebar = 'encyclopedia content outside question and answer ' * 2
        body = ('<html><p class="txt_ms">Question</p><p class="sele_txt">Main answer</p>'
                '<div class="doc_zw"><span class="zw2">Followup message</span>'
                '<div class="hfu_box">Submit</div></div><p class="jbk_txt">'+sidebar+'</p></html>').encode()
        record = dict(id=1, url='https://ask.39.net/question/1.html', quality_status='accepted',
                      text='Question Main answer '+sidebar+' 我要咨询')
        result = audit.audit_record(record, body)
        self.assertEqual(result['missing_answers'], 0)
        self.assertEqual(result['missing_followup_blocks'], 1)
        self.assertIn('encyclopedia_contamination', result['flags'])
        self.assertIn('ui_boilerplate', result['flags'])
        clean = audit.audit_record(dict(record, text='Question Main answer Followup message'), body)
        self.assertEqual(clean['flags'], [])
        malformed = b'<p class="txt_ms">Question</p><p class="sele_txt"><p>Part one</p><p>Part two</p></p><div class="doc_t_strip">Date</div>'
        repaired = audit.audit_record(dict(record, text='Question Part one Part two'), malformed)
        self.assertEqual(repaired['source_answers'], 1)
        self.assertEqual(repaired['repaired_nested_p_answers'], 1)
        self.assertEqual(repaired['flags'], [])

    def test_selection_preserves_source_and_is_deterministic(self):
        rows = [dict(id=i, url=f'https://ask.39.net/question/{i}.html') for i in range(20)]
        rows += [rows[0], dict(id=90, url='https://fake.ask.39.net/question/90.html'),
                 dict(id=91, url='https://ask.39.net.evil.test/question/91.html'),
                 dict(id=92, url='http://ask.39.net/other/92.html')]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source.parquet'
            pq.write_table(pa.Table.from_pylist(rows), source)
            samples, selection = check.select(source, 8)
            self.assertEqual(samples, check.select(source, 8)[0])
            self.assertEqual(len(samples), 8)
            self.assertEqual(selection['domain_rows'], 22)
            self.assertEqual(selection['unique_domain_urls'], 21)
            self.assertEqual(len({r['url'] for r in samples}), 8)
            self.assertTrue(any(r['id'] == 92 for r in samples))
            self.assertTrue(all(any(r['id'] == s['id'] and r['url'] == s['url'] for s in rows) for r in samples))

    def test_generated_notebook_payload_integrity_and_syntax(self):
        import ast
        import base64
        import hashlib
        import zlib
        nb = json.loads((ROOT/'notebooks/check_ask.39.net.ipynb').read_text(encoding='utf-8'))
        payloads = None
        for cell in nb['cells']:
            if cell['cell_type'] == 'code':
                source = ''.join(cell['source'])
                compile(source, '<notebook>', 'exec')
                for node in ast.parse(source).body:
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'PAYLOADS':
                        payloads = ast.literal_eval(node.value)
        self.assertIsNotNone(payloads)
        for name, (payload, expected) in payloads.items():
            body = zlib.decompress(base64.b85decode(payload))
            self.assertEqual(hashlib.sha256(body).hexdigest(), expected)
            if name == 'check_ask39.py':
                self.assertEqual(body, (ROOT/'scripts/check_ask39.py').read_bytes())


if __name__ == '__main__':
    unittest.main()
