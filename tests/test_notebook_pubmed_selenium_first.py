"""Default PubMed browser routing, mixed batches, limits and durable resume."""
from contextlib import redirect_stdout
import gzip
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import test_notebook_pubmed_parser as fixtures
from test_notebook_selenium_fallback import assignments


class PubMedSeleniumFirstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PubMedParserTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixtures.PubMedParserTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixtures.PubMedParserTests.setUp(self)
        self.events = []

    def make_run(self, mixed=False):
        samples = [dict(self.sample, id=i, url=f'https://pubmed.ncbi.nlm.nih.gov/{28382721 + i}/')
                   for i in (1, 2)]
        if mixed:
            samples[1] = dict(samples[1], url='https://vov.vn/article', domain='vov.vn')
            samples.reverse()  # PubMed must still render before the first ordinary request.
        self.crawler.jsonl(self.out / 'sample.jsonl', samples)
        self.crawler.write_json(self.out / 'manifest.json', {
            'selected': 2, 'sample_sha256': self.crawler.file_hash(self.out / 'sample.jsonl'), 'sampling': 'fixture'})
        counts = {domain: sum(s['domain'] == domain for s in samples) for domain in {s['domain'] for s in samples}}
        self.crawler.write_json(self.out / 'source_profile.json', {
            'rows': 2, 'host_counts': counts, 'sample_host_counts': counts})
        return samples

    def render(self, crawler, driver, sample, out, **options):
        self.events.append(('selenium', sample['url']))
        body = fixtures.article(pmid=sample['url'].strip('/').rsplit('/', 1)[1])
        raw_path = f"raw/selenium/{sample['id']}.gz"
        crawler.atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
        doc = crawler.extract(body, 'text/html', sample['url'])
        return dict(sample, **doc, **crawler.quality(doc), engine='selenium', status='rendered',
                    http_status=200, final_url=sample['url'], raw_path=raw_path,
                    raw_sha256=crawler.digest(body), elapsed_seconds=0)

    def request(self, url, *args, **kwargs):
        self.events.append(('requests', url))
        body = (fixtures.article(pmid=url.rstrip('/').rsplit('/', 1)[1])
                if 'pubmed.ncbi.nlm.nih.gov' in url else
                ('<html><head><title>Public health article</title></head><body><article>'
                 '<h1>Public health article</h1><p>' +
                 'A detailed public health article describes research findings and practical outcomes. ' * 35 +
                 '</p></article></body></html>').encode('utf-8'))
        return 200, {'Content-Type': 'text/html'}, body

    def execute(self, config=None, max_new=None):
        with patch.object(self.crawler.Fetcher, 'request_once', side_effect=self.request) as transport, \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', return_value=Mock()), \
                patch.object(self.probe, 'browser_attempt', side_effect=self.render) as browser, \
                redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out,
                                      {'attempts': 1, 'delay': 0, **(config or {})}, workers=1, max_new=max_new)
        return summary, transport, browser

    def test_mixed_batch_uses_pubmed_selenium_before_other_domain_requests(self):
        self.make_run(mixed=True)
        summary, transport, browser = self.execute()
        self.assertEqual(self.events, [('selenium', 'https://pubmed.ncbi.nlm.nih.gov/28382722/'),
                                       ('requests', 'https://vov.vn/article')])
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(browser.call_count, 1)
        record = self.crawler.load_json(self.out / 'records/1.json')
        self.assertEqual(record['requests_status'], 'skipped_selenium_first')
        self.assertIsNone(record['requests_http_status'])
        self.assertEqual(record['requests'], [])
        self.assertEqual(record['browser_route'], 'selenium_first')
        self.assertEqual(record['quality_status'], 'accepted')
        self.assertEqual(record['engine'], 'selenium')
        self.assertEqual(summary['accessible'], 2)

    def test_limit_counts_pubmed_and_resume_only_renders_missing_url(self):
        self.make_run()
        summary, transport, browser = self.execute(max_new=1)
        transport.assert_not_called()
        self.assertEqual(browser.call_count, 1)
        self.assertEqual(summary['pending'], 1)
        saved = (self.out / 'browser_records/1.json').read_bytes()
        self.events.clear()
        summary, transport, browser = self.execute(max_new=1)
        transport.assert_not_called()
        self.assertEqual(browser.call_count, 1)
        self.assertEqual(browser.call_args.args[2]['id'], 2)
        self.assertEqual(summary['pending'], 0)
        self.assertEqual((self.out / 'browser_records/1.json').read_bytes(), saved)

    def test_interrupt_before_browser_commit_remains_pending_and_can_resume(self):
        self.make_run()
        with patch.object(self.crawler.Fetcher, 'request_once') as transport, \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', return_value=Mock()), \
                patch.object(self.probe, 'browser_attempt', side_effect=KeyboardInterrupt), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                self.runner.run(self.crawler, self.probe, self.out, {'attempts': 1, 'delay': 0}, workers=1)
        transport.assert_not_called()
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['pending'], 2)
        self.assertEqual(list((self.out / 'records').glob('*.json')), [])
        summary, transport, browser = self.execute()
        transport.assert_not_called()
        self.assertEqual(browser.call_count, 2)
        self.assertEqual(summary['accessible'], 2)

    def test_failed_primary_browser_keeps_actual_failure_and_no_accepted_text(self):
        self.make_run()
        def failure(crawler, driver, sample, out, **options):
            return dict(sample, engine='selenium', status='browser_error', http_status=None, error='Chrome failed')
        with patch.object(self, 'render', side_effect=failure):
            summary, transport, browser = self.execute()
        transport.assert_not_called()
        self.assertEqual(summary['failed'], 2)
        record = self.crawler.load_json(self.out / 'records/1.json')
        self.assertEqual(record['status'], 'browser_error')
        self.assertEqual(record['error'], 'Chrome failed')
        self.assertEqual((self.out / 'corpus.accepted.jsonl').read_text(), '')

    def test_primary_startup_failure_keeps_run_pending(self):
        self.make_run()
        with patch.object(self.crawler.Fetcher, 'request_once') as transport, \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', side_effect=RuntimeError('Chrome crashed')), \
                redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Selenium pass incomplete'):
                self.runner.run(self.crawler, self.probe, self.out, {'attempts': 1, 'delay': 0}, workers=1)
        transport.assert_not_called()
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['pending'], 2)
        self.assertEqual(list((self.out / 'records').glob('*.json')), [])
        self.assertIn('Chrome crashed', self.crawler.load_json(self.out / 'browser_setup_error.json')['error'])

    def test_robots_denial_is_not_bypassed_by_primary_selenium(self):
        self.make_run()
        with patch.object(self.crawler.Fetcher, 'robot_policy', side_effect=self.crawler.CrawlError('robots_disallowed')):
            summary, transport, browser = self.execute({'respect_robots': True})
        transport.assert_not_called()
        browser.assert_not_called()
        self.assertEqual(summary['failed'], 2)
        self.assertEqual(self.crawler.load_json(self.out / 'records/1.json')['status'], 'robots_disallowed')

    def test_domain_routing_change_requires_new_run_before_network(self):
        samples = self.make_run()
        self.probe.prepare_pubmed_selenium(self.crawler, self.out, samples)
        with patch.object(self.crawler.Fetcher, 'request_once') as request:
            with self.assertRaisesRegex(ValueError, 'config changed'):
                self.probe.prepare_pubmed_selenium(self.crawler, self.out, samples, enabled=False)
        request.assert_not_called()

    def test_explicit_off_or_false_restores_requests_first(self):
        for config in ({'browser_mode': 'off'}, {'pubmed_selenium_first': False}):
            with self.subTest(config=config):
                # A fresh isolated run is required when changing the routing configuration.
                original = self.out
                self.out = original / ('off' if config.get('browser_mode') else 'false')
                self.out.mkdir()
                self.make_run()
                _, transport, browser = self.execute(config)
                self.assertEqual(transport.call_count, 2)
                browser.assert_not_called()
                self.out = original

    def test_domain_notebook_executes_same_primary_route(self):
        samples = self.make_run(mixed=True)
        nb = json.loads((fixtures.ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        config = assignments(''.join(nb['cells'][3]['source']))
        self.assertTrue(config['PUBMED_SELENIUM_FIRST'])
        (self.out / 'network_check.json').write_text('{}')
        namespace = dict(config, RUN_DIR=self.out, crawler=self.crawler, priority_probe=self.probe,
                         IP_CHECK_ENABLED=False,
                         DIRECT_PUBLIC_PROBE=True, SAMPLES=samples, NETWORK_CHECK_DOMAINS=[],
                         save_outputs=lambda: ([], {}, self.out / 'test.zip'))
        with patch.object(self.crawler.Fetcher, 'request_once', side_effect=self.request), \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', return_value=Mock()), \
                patch.object(self.probe, 'browser_attempt', side_effect=self.render), \
                redirect_stdout(io.StringIO()):
            exec(compile(''.join(nb['cells'][11]['source']), '<domain-crawl>', 'exec'), namespace)
        self.assertEqual(self.events, [('selenium', samples[1]['url']), ('requests', samples[0]['url'])])


if __name__ == '__main__':
    unittest.main()
