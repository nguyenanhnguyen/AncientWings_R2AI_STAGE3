"""Regressions for disease-page extraction, quality logging, and raw recovery."""
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib

from test_notebook_selenium_fallback import assignments, load_module


ROOT = Path(__file__).resolve().parents[1]
URL = 'https://www.cnkang.com/dise/350/1123729.html'
PARAGRAPHS = [
    f'段落{i}：这是一段用于测试网页正文提取的示例文字，正文内容应当完整保留，不能混入导航链接。'
    for i in range(1, 6)
]
BODY = ''.join(f'<p>{text}</p>' for text in PARAGRAPHS)


def disease_page(article=None):
    article = article or (
        '<div class="detail">'
        '<h1 class="detaila">正文标题</h1>'
        '<ul class="detailb"><li>发布时间：2016-05-16</li></ul>'
        f'<div class="detailc">{BODY}</div>'
        '<div class="detaile">广告咨询</div>'
        '<ul class="detaild"><li>上一篇下一篇</li></ul>'
        '</div>'
    )
    return (
        '<html><head><meta charset="utf-8"><title>页面标题</title></head><body>'
        '<div class="dise_nav"><h1>疾病导航标题</h1></div>'
        f'{article}<aside><h1>相关文章标题</h1><p>热门文章导航</p></aside>'
        '</body></html>'
    ).encode('utf-8')


class CnkangParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        cls.root = Path(cls.temp.name)
        notebook = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        pack = assignments(''.join(notebook['cells'][6]['source']))
        for name, payload in pack['EMBEDDED_FILES'].items():
            body = zlib.decompress(base64.b85decode(payload))
            if hashlib.sha256(body).hexdigest() != pack['EMBEDDED_SHA256'][name]:
                raise AssertionError(f'Snapshot hash mismatch: {name}')
            (cls.root / name).write_bytes(body)
        domain = json.loads((ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        domain_pack = assignments(''.join(domain['cells'][7]['source']))
        body = zlib.decompress(base64.b85decode(domain_pack['CRAWLER_PAYLOAD']))
        if hashlib.sha256(body).hexdigest() != domain_pack['CRAWLER_SHA256']:
            raise AssertionError('Domain crawler hash mismatch')
        (cls.root / 'domain_crawler.py').write_bytes(body)
        cls.crawler = load_module('cnkang_test_crawler', cls.root / 'crawler_snapshot.py')
        cls.domain_crawler = load_module('cnkang_test_domain_crawler', cls.root / 'domain_crawler.py')
        cls.probe = load_module('cnkang_test_probe', cls.root / 'priority_probe_snapshot.py')
        cls.runner = load_module('cnkang_test_runner', cls.root / 'corpus_runner_snapshot.py')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.out = Path(self.case.name)
        self.sample = {'id': 1, 'url': URL, 'domain': 'www.cnkang.com'}

    def test_disease_body_and_its_heading_are_kept_without_navigation(self):
        for crawler in (self.crawler, self.domain_crawler):
            with self.subTest(crawler=crawler.__name__):
                doc = crawler.extract(disease_page(), 'text/html; charset=UTF-8', URL)
                self.assertEqual(doc['title'], '正文标题')
                self.assertEqual(doc['extractor'], 'cnkang_dise_dom_v1')
                for text in PARAGRAPHS:
                    self.assertIn(text, doc['text'])
                for text in ('疾病导航标题', '广告咨询', '上一篇下一篇', '热门文章导航'):
                    self.assertNotIn(text, doc['text'])
                self.assertEqual(crawler.quality(doc)['quality_status'], 'accepted')
                self.assertNotIn('domain_parser_fallback', doc)

    def test_ambiguous_or_unconfirmed_templates_stay_in_review(self):
        cases = [
            '<div class="detail"><h1 class="detaila">正文标题</h1>'
            f'<div class="detailc">{BODY}</div><div class="detailc">{BODY}</div></div>',
            '<div class="detail"><h1 class="detaila">正文标题</h1>'
            f'<div class="detailc">{BODY}</div></div>' * 2,
            f'<div class="detail"><div class="detailc">{BODY}</div></div>',
            '<div class="detail"><h1 class="detaila">正文标题</h1>'
            f'<div class="detailc-sidebar">{BODY}</div></div>',
        ]
        for crawler in (self.crawler, self.domain_crawler):
            for article in cases:
                with self.subTest(crawler=crawler.__name__, article=article[:80]):
                    doc = crawler.extract(disease_page(article), 'text/html; charset=UTF-8', URL)
                    self.assertTrue(doc['domain_parser_fallback'])
                    self.assertNotEqual(crawler.quality(doc)['quality_status'], 'accepted')

    def test_existing_endtext_template_still_excludes_related_widgets(self):
        article = (
            '<h1 id="h1title">旧版正文标题</h1><div id="endText">'
            f'{BODY}<div class="article_intro">推荐广告</div>'
            '<div id="jkpl">评论模块</div><p>相关文章：推荐文章</p></div>'
        )
        for crawler in (self.crawler, self.domain_crawler):
            with self.subTest(crawler=crawler.__name__):
                doc = crawler.extract(disease_page(article), 'text/html', 'https://www.cnkang.com/yyk/article/1.html')
                self.assertEqual(doc['title'], '旧版正文标题')
                self.assertEqual(doc['extractor'], 'cnkang_article_dom_v1')
                for text in ('推荐广告', '评论模块', '推荐文章'):
                    self.assertNotIn(text, doc['text'])
                self.assertEqual(crawler.quality(doc)['quality_status'], 'accepted')

    def test_recovery_reextracts_old_review_without_fetching_or_stale_fallback_flag(self):
        source, target = self.out / 'old', self.out / 'recovered'
        source.mkdir()
        target.mkdir()
        self.crawler.write_json(source / 'manifest.json', {'selected': 1})
        body = disease_page()
        self.crawler.atomic_bytes(source / 'raw/article.gz', gzip.compress(body, mtime=0))
        old = dict(self.sample, status='extracted', http_status=200, content_type='text/html',
                   raw_path='raw/article.gz', raw_sha256=self.crawler.digest(body),
                   quality_status='review', quality_flags=['domain_parser_fallback'],
                   domain_parser_fallback=True)
        self.crawler.write_json(source / 'records/1.json', old)
        with patch.object(self.crawler.Fetcher, 'request_once') as request:
            manifest = self.probe.seed_successful_requests(
                self.crawler, target, [self.sample], source, record_dir='requests_records')
        request.assert_not_called()
        self.assertEqual(manifest['reused_ids'], [1])
        record = self.crawler.load_json(target / 'requests_records/1.json')
        self.assertEqual(record['quality_status'], 'accepted')
        self.assertNotIn('domain_parser_fallback', record)
        self.assertEqual(self.probe.select_browser_samples([self.sample], [record], 'failed_only'), [])
        original = self.crawler.load_json(target / 'recovery_records/1.json')
        self.assertTrue(original['domain_parser_fallback'])

    def test_correct_disease_page_reaches_accepted_corpus_without_selenium(self):
        self.crawler.jsonl(self.out / 'sample.jsonl', [self.sample])
        self.crawler.write_json(self.out / 'manifest.json', {
            'sample_sha256': self.crawler.file_hash(self.out / 'sample.jsonl'), 'sampling': 'test fixture'})
        self.crawler.write_json(self.out / 'source_profile.json', {
            'rows': 1, 'host_counts': {'www.cnkang.com': 1}, 'sample_host_counts': {'www.cnkang.com': 1}})
        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(200, {'Content-Type': 'text/html; charset=UTF-8'}, disease_page())), \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser') as browser, redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out, {'attempts': 1, 'delay': 0}, workers=1)
        browser.assert_not_called()
        self.assertEqual(summary['accessible'], 1)
        accepted = [json.loads(line) for line in (self.out / 'corpus.accepted.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['title'], '正文标题')

    def test_quality_reviews_are_batched_and_not_counted_as_access_failures(self):
        samples = [dict(self.sample, id=i, url=URL + f'?test={i}') for i in range(1, 302)]

        def reviewed_record(crawler, fetcher, sample, out, *args, record_dir='records', **options):
            row = dict(sample, status='extracted', http_status=200, text='Readable article.',
                       quality_status='review', quality_flags=['domain_parser_fallback'])
            crawler.write_json(Path(out) / record_dir / f"{sample['id']}.json", row)
            return row

        console = io.StringIO()
        with patch.object(self.probe, 'request_record', side_effect=reviewed_record), redirect_stdout(console):
            self.probe.crawl_requests(self.crawler, self.out, samples, workers=2, delay=0, user_agent='Test/1')
        rows = [json.loads(line) for line in console.getvalue().splitlines()]
        self.assertEqual([row['completed'] for row in rows], [300, 301])
        self.assertTrue(all(row['failed'] == 0 for row in rows))
        self.assertEqual(rows[-1]['quality_statuses'], {'review': 301})
        self.assertEqual(rows[-1]['quality_flags'], {'domain_parser_fallback': 301})

    def test_http_error_prints_before_the_next_url_and_before_batch_progress(self):
        console = io.StringIO()
        samples = [dict(self.sample, id=i, url=URL + f'?test={i}') for i in (1, 2)]

        def request_record(crawler, fetcher, sample, out, *args, record_dir='records', **options):
            if sample['id'] == 2:
                already_printed = [json.loads(line) for line in console.getvalue().splitlines()]
                self.assertEqual(len(already_printed), 1)
                self.assertEqual(already_printed[0]['event'], 'url_error')
                self.assertEqual(already_printed[0]['http'], 503)
            row = dict(sample, status='http_error' if sample['id'] == 1 else 'extracted',
                       http_status=503 if sample['id'] == 1 else 200, text='Article body.',
                       quality_status='accepted', quality_flags=[], error='Server unavailable')
            crawler.write_json(Path(out) / record_dir / f"{sample['id']}.json", row)
            return row

        with patch.object(self.probe, 'request_record', side_effect=request_record), redirect_stdout(console):
            self.probe.crawl_requests(self.crawler, self.out, samples, workers=1, delay=0, user_agent='Test/1')
        rows = [json.loads(line) for line in console.getvalue().splitlines()]
        self.assertEqual(rows[-1]['failed'], 1)

    def test_selenium_reviews_are_batched_but_empty_document_prints_immediately(self):
        samples = [dict(self.sample, id=i, url=URL + f'?test={i}') for i in range(1, 4)]

        def browser_attempt(crawler, browser, sample, out, **options):
            return dict(sample, status='rendered', http_status=200,
                        text='' if sample['id'] == 1 else 'Article body.',
                        quality_status='review', quality_flags=['domain_parser_fallback'])

        console = io.StringIO()
        with patch.object(self.probe, 'create_browser', return_value=Mock()), \
                patch.object(self.probe, 'browser_attempt', side_effect=browser_attempt), redirect_stdout(console):
            self.probe.crawl_browser(self.crawler, self.out, samples, attempts=1, delay=0)
        rows = [json.loads(line) for line in console.getvalue().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['error_kind'], 'empty_text')
        self.assertEqual(rows[-1]['completed'], 3)
        self.assertEqual(rows[-1]['failed'], 1)
        self.assertEqual(rows[-1]['quality_statuses'], {'review': 3})


if __name__ == '__main__':
    unittest.main()
