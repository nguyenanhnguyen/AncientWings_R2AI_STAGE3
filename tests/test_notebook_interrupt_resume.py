"""Interruptions preserve checkpoints and resume only unfinished engine work."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import gzip
import io
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

import test_notebook_pubmed_parser as pubmed_fixtures

article = pubmed_fixtures.article
COOKIE_HEADING = pubmed_fixtures.COOKIE_HEADING


class InterruptResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pubmed_fixtures.PubMedParserTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        pubmed_fixtures.PubMedParserTests.tearDownClass.__func__(cls)

    def setUp(self):
        pubmed_fixtures.PubMedParserTests.setUp(self)

    def make_run(self, count=2):
        samples = [dict(self.sample, id=index, url=f'https://pubmed.ncbi.nlm.nih.gov/{28382721 + index}/')
                   for index in range(1, count + 1)]
        self.crawler.jsonl(self.out / 'sample.jsonl', samples)
        self.crawler.write_json(self.out / 'manifest.json', {
            'selected': count, 'sample_sha256': self.crawler.file_hash(self.out / 'sample.jsonl'), 'sampling': 'fixture'})
        self.crawler.write_json(self.out / 'source_profile.json', {
            'rows': count, 'host_counts': {'pubmed.ncbi.nlm.nih.gov': count},
            'sample_host_counts': {'pubmed.ncbi.nlm.nih.gov': count}})
        return samples

    def rendered(self, crawler, driver, sample, out, **options):
        pmid = sample['url'].rstrip('/').rsplit('/', 1)[1]
        body = article(pmid=pmid)
        raw_path = f"raw/selenium/{sample['id']}.gz"
        crawler.atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
        doc = crawler.extract(body, 'text/html', sample['url'])
        return dict(sample, **doc, **crawler.quality(doc), engine='selenium', status='rendered',
                    http_status=200, final_url=sample['url'], raw_path=raw_path,
                    raw_sha256=crawler.digest(body), elapsed_seconds=0)

    def test_requests_interrupt_stops_group_and_resume_skips_committed_url(self):
        samples = self.make_run(4)
        started, finish_current = threading.Event(), threading.Event()
        original_record = self.probe.request_record

        def record(*args, **kwargs):
            started.set()
            if not finish_current.wait(3):
                raise RuntimeError('Test coordination timed out')
            return original_record(*args, **kwargs)

        class ReleasingPool(ThreadPoolExecutor):
            def __exit__(self, *args):
                finish_current.set()
                return super().__exit__(*args)

        def interrupt(futures):
            self.assertTrue(started.wait(3))
            raise KeyboardInterrupt('user stopped cell')

        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(203, {'Content-Type': 'text/html'}, COOKIE_HEADING)), \
                patch.object(self.probe, 'request_record', side_effect=record) as request, \
                patch.object(self.probe, 'ThreadPoolExecutor', ReleasingPool), \
                patch.object(self.probe, 'as_completed', side_effect=interrupt), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                self.probe.crawl_requests(self.crawler, self.out, samples, workers=1, delay=0,
                                          attempts=1, user_agent='TestCrawler')
        self.assertEqual(request.call_count, 1, 'Stop must not drain the whole domain queue')
        checkpoint = (self.out / 'records/1.json').read_bytes()
        self.assertEqual(len(list((self.out / 'records').glob('*.json'))), 1)
        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(203, {'Content-Type': 'text/html'}, COOKIE_HEADING)) as transport, \
                redirect_stdout(io.StringIO()):
            records = self.probe.crawl_requests(self.crawler, self.out, samples, workers=1, delay=0,
                                                attempts=1, user_agent='TestCrawler')
        self.assertEqual(transport.call_count, 3)
        self.assertEqual(len(records), 4)
        self.assertEqual((self.out / 'records/1.json').read_bytes(), checkpoint)

    def test_browser_interrupt_keeps_completed_article_and_resumes_remaining_url(self):
        self.make_run()
        driver = Mock()
        attempted = []

        def render(*args, **kwargs):
            sample = args[2]
            attempted.append(sample['id'])
            if sample['id'] == 2:
                raise KeyboardInterrupt('user stopped browser pass')
            return self.rendered(*args, **kwargs)

        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(203, {'Content-Type': 'text/html'}, COOKIE_HEADING)), \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', return_value=driver), \
                patch.object(self.probe, 'browser_attempt', side_effect=render), \
                redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                self.runner.run(self.crawler, self.probe, self.out,
                                {'attempts': 1, 'delay': 0, 'pubmed_use_efetch': False}, workers=1)
        driver.quit.assert_called_once()
        self.assertEqual(attempted, [1, 2])
        checkpoint = (self.out / 'browser_records/1.json').read_bytes()
        self.assertFalse((self.out / 'browser_records/2.json').exists())
        self.assertEqual(self.crawler.load_json(self.out / 'records/1.json')['quality_status'], 'accepted')
        with patch.object(self.crawler.Fetcher, 'request_once') as transport, \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser'), \
                patch.object(self.probe, 'browser_attempt', side_effect=self.rendered) as render, \
                redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out,
                                      {'attempts': 1, 'delay': 0, 'pubmed_use_efetch': False}, workers=1)
        transport.assert_not_called()
        self.assertEqual(render.call_count, 1)
        self.assertEqual(render.call_args.args[2]['id'], 2)
        self.assertEqual((self.out / 'browser_records/1.json').read_bytes(), checkpoint)
        self.assertEqual(summary['accessible'], 2)
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['accepted'], 2)

    def test_interruption_between_browser_checkpoint_and_publication_is_repaired(self):
        samples = self.make_run(1)
        request = dict(samples[0], status='http_error', engine='requests', http_status=203,
                       challenge_detected=True, error_kind='http_203_challenge', requests=[])
        self.crawler.write_json(self.out / 'requests_records/1.json', request)
        browser = self.rendered(self.crawler, None, samples[0], self.out)
        self.crawler.write_json(self.out / 'browser_records/1.json', browser)
        # This is the durable state left by a process killed before on_record runs.
        self.assertFalse((self.out / 'records/1.json').exists())
        with patch.object(self.crawler.Fetcher, 'request_once') as transport, \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser') as driver, redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out,
                                      {'attempts': 1, 'delay': 0, 'pubmed_use_efetch': False}, workers=1)
        transport.assert_not_called()
        driver.assert_not_called()
        self.assertEqual(summary['accessible'], 1)
        self.assertEqual(self.crawler.load_json(self.out / 'records/1.json')['engine'], 'selenium')

    def test_interrupted_atomic_write_preserves_old_record_and_ignores_partial_file(self):
        target = self.out / 'records/1.json'
        self.crawler.write_json(target, {'id': 1, 'text': 'previous durable record'})
        original = target.read_bytes()
        with patch.object(Path, 'replace', side_effect=KeyboardInterrupt('stop before replace')):
            with self.assertRaises(KeyboardInterrupt):
                self.crawler.write_json(target, {'id': 1, 'text': 'new record'})
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual([p.name for p in target.parent.glob('*.json')], ['1.json'])
        self.crawler.write_json(target, {'id': 1, 'text': 'resumed write'})
        self.assertEqual(json.loads(target.read_text(encoding='utf-8'))['text'], 'resumed write')


if __name__ == '__main__':
    unittest.main()
