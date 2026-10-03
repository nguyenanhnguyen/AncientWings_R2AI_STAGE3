import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq

spec = importlib.util.spec_from_file_location('crawler', Path(__file__).parents[1] / 'src/vibiomir/crawl/crawler.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CrawlTests(unittest.TestCase):
    def test_preserve_medical_text(self):
        text = 'Liều 0,5 mg/kg; Na⁺ ≥ 135 mmol/L.\r\n\r\nKhông dùng quá 2 lần/ngày.'
        result = c.normalize(text)
        self.assertIn('0,5 mg/kg; Na⁺ ≥ 135 mmol/L.', result)
        self.assertIn('Không dùng quá 2 lần/ngày.', result)
        self.assertNotIn('\r', result)

    def test_chinese_not_filtered_as_short_by_word_count(self):
        doc = {'title': '医学资料', 'text': '这是一篇关于疾病诊断和治疗的医学资料。' * 15}
        self.assertEqual(c.quality(doc)['quality_status'], 'accepted')
        self.assertEqual(c.quality(doc)['language_hint'], 'zh_hint')

    def test_error_page_not_accepted(self):
        self.assertEqual(c.quality({'title': 'Just a moment...', 'text': 'Verify you are human'})['quality_status'], 'rejected')
        self.assertEqual(c.quality({'title': '404 Not Found', 'text': 'Some text ' * 100})['quality_status'], 'rejected')

    def test_duplicate_ids_fail(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'in.parquet'
            pq.write_table(pa.table({'id': [5, 5], 'url': ['https://a.org/1', 'https://a.org/2']}), src)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                c.prepare(Namespace(source=src, out=Path(tmp) / 'run', size=2, seed=42))

    def test_balanced_sample_preserves_ids_and_urls(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'in.parquet'
            urls = ['https://a.org/' + str(i) for i in range(30)] + ['https://b.org/one']
            pq.write_table(pa.table({'id': list(range(583, 614)), 'url': urls}), src)
            for name in ('one', 'two'):
                c.prepare(Namespace(source=src, out=Path(tmp) / name, size=10, seed=42))
            a = (Path(tmp) / 'one/sample.jsonl').read_bytes()
            self.assertEqual(a, (Path(tmp) / 'two/sample.jsonl').read_bytes())
            rows = [json.loads(x) for x in a.splitlines()]
            self.assertEqual(len(rows), 10)
            self.assertEqual(len({r['id'] for r in rows}), 10)
            self.assertTrue(any(r['url'] == 'https://b.org/one' for r in rows))
            for r in rows:
                self.assertEqual(r['url'], urls[r['id'] - 583])

    def test_gbk_html_extraction(self):
        body = '<html><head><meta charset="gbk"><title>医学资料</title></head><body><article><h1>医学资料</h1><p>' + '这是关于疾病诊断和治疗的详细医学资料。' * 40 + '</p></article></body></html>'
        doc = c.extract(body.encode('gbk'), 'text/html', 'https://example.org/article')
        self.assertIn('疾病诊断', doc['text'])
        self.assertNotIn('\ufffd', doc['text'])

    def test_private_redirect_target_rejected(self):
        with self.assertRaises(c.CrawlError):
            c.Fetcher.validate('http://127.0.0.1/test')

    def test_mojibake_without_replacement_character_flagged(self):
        doc = {'title': 'Title', 'text': 'ЖззХХХФђФмжЮЧАСаЯйбз' * 100}
        self.assertEqual(c.quality(doc)['quality_status'], 'review')

    def test_qa_advertising_template_flagged(self):
        doc = {'title': 'Q&A', 'text': '医学资料' * 100 + '涉嫌广告宣传 其他投诉理由 医生在线免费咨询'}
        self.assertIn('boilerplate_suspect', c.quality(doc)['quality_flags'])

    def test_redirect_is_checked_against_robots_before_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp)
            trace = {'requests': []}
            with patch.object(f, 'robot_policy', side_effect=[(0, {}), c.CrawlError('robots_disallowed')]) as robots:
                with patch.object(f, 'request_once', return_value=(302, {'Location': 'https://b.org/private'}, b'')) as fetch:
                    with self.assertRaisesRegex(c.CrawlError, 'robots_disallowed'):
                        f.fetch('https://a.org/start', trace)
                    self.assertEqual(fetch.call_count, 1)
                    self.assertEqual(robots.call_args.args[0], 'https://b.org/private')

    def test_transient_http_retries_but_forbidden_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp)
            with patch.object(f, 'robot_policy', return_value=(0, {})), patch.object(c.time, 'sleep'):
                with patch.object(f, 'request_once', side_effect=[(503, {}, b'wait'), (200, {}, b'ok')]) as request:
                    self.assertEqual(f.fetch('https://a.org/', {'requests': []}), b'ok')
                    self.assertEqual(request.call_count, 2)
                with patch.object(f, 'request_once', return_value=(403, {}, b'blocked')) as request:
                    self.assertEqual(f.fetch('https://a.org/', {'requests': []}), b'blocked')
                    self.assertEqual(request.call_count, 1)

    def test_id_interval_is_half_open_and_uses_ids_not_row_numbers(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'in.parquet'
            pq.write_table(pa.table({'id': [1583, 585, 583, 584, 10000],
                                     'url': [f'https://a.org/{i}' for i in [1583, 585, 583, 584, 10000]]}), src)
            out = Path(tmp) / 'run'
            c.prepare(Namespace(source=src, out=out, size=3, seed=42, id_start=583, id_stop=586))
            rows = [json.loads(x) for x in (out / 'sample.jsonl').read_text().splitlines()]
            self.assertEqual([r['id'] for r in rows], [583, 584, 585])
            self.assertEqual(c.load_json(out / 'manifest.json')['sampling'], 'id_interval')

    def test_bachmai_keeps_intro_inline_units_and_table(self):
        body = '''<html><head><meta charset="utf-8"><title>Tài liệu mẫu</title></head><body>
        <div class="content-excerpt">Phần mở đầu cần giữ nguyên.</div>
        <div class="content-editor content-editor-post"><p>Liều <b>0,5</b> mg/kg; Na⁺ ≥ 135 mmol/L.</p>
        <table><tr><th>Tuổi</th><th>Liều</th></tr><tr><td>12</td><td>5 mg</td></tr></table></div>
        <div class="post-detail__same-category-content">Tin liên quan không thuộc bài.</div></body></html>'''
        doc = c.extract(body.encode('utf-8'), 'text/html; charset=utf-8', 'https://bachmai.gov.vn/bai-viet/example')
        self.assertEqual(doc['extractor'], 'bachmai_dom_v1')
        self.assertTrue(doc['text'].startswith('Phần mở đầu cần giữ nguyên.'))
        self.assertIn('0,5 mg/kg; Na⁺ ≥ 135 mmol/L.', doc['text'])
        self.assertIn('12 | 5 mg |', doc['text'])
        self.assertNotIn('Tin liên quan', doc['text'])

    def test_office_conditional_comments_do_not_become_corpus_text(self):
        from lxml import html
        tree = html.fromstring('<div><!--[if mso]><style>mso-style; MicrosoftInternetExplorer4</style><![endif]--><p>Liều <b>0,5</b> mg/kg.</p></div>')
        self.assertEqual(c.dom_text(tree), 'Liều 0,5 mg/kg.')

    def test_run_lock_rejects_second_writer_and_releases_after_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            with c.run_lock(tmp):
                with self.assertRaisesRegex(RuntimeError, 'Another crawler'):
                    with c.run_lock(tmp):
                        self.fail('Second lock should fail')
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                with c.run_lock(tmp):
                    raise ValueError('interrupted')
            with c.run_lock(tmp):
                pass

    def test_jsonl_unicode_line_separators_do_not_split_records(self):
        spec = importlib.util.spec_from_file_location('exporter', Path(__file__).parents[1] / 'src/vibiomir/crawl/export.py')
        exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(exporter)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'rows.jsonl'
            rows = [{'id': 583, 'text': 'Đoạn A\u2028Đoạn B\u0085Đoạn C'}, {'id': 584, 'text': 'Tiếp theo'}]
            path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
            self.assertEqual(exporter.read_jsonl(path), rows)

    def test_duplicate_content_keeps_both_ids_and_resume_skips_completed(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'in.parquet'
            out = Path(tmp) / 'run'
            pq.write_table(pa.table({'id': [583, 584], 'url': ['https://a.org/1', 'https://a.org/2']}), src)
            c.prepare(Namespace(source=src, out=out, size=2, seed=42))
            sample = [json.loads(x) for x in (out / 'sample.jsonl').read_text().splitlines()]
            for item in sample:
                doc = {'title': 'Title', 'text': 'Meaningful medical source text. ' * 40}
                c.write_json(out / 'records' / f"{item['id']}.json", {**item, **doc, **c.quality(doc), 'status': 'extracted', 'http_status': 200})
            with patch.object(c.Fetcher, 'fetch', side_effect=AssertionError('Completed IDs must not be fetched')):
                c.crawl(Namespace(out=out, workers=1, delay=1, attempts=3, max_new=None))
            accepted = [json.loads(x) for x in (out / 'corpus.accepted.jsonl').read_text().splitlines()]
            self.assertEqual([r['id'] for r in accepted], [583, 584])
            self.assertEqual(accepted[0]['duplicate_doc_ids'], [583, 584])
            self.assertEqual(c.load_json(out / 'quality_report.json')['exact_duplicate_groups'], 1)


if __name__ == '__main__':
    unittest.main()
