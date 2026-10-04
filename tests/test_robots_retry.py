"""Regression cases for robots failures shared by concurrent article requests."""
from concurrent.futures import ThreadPoolExecutor
import gzip
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('robots_crawler', Path(__file__).parents[1] / 'src/vibiomir/corpus/crawler.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
ALLOW = (200, {'Content-Type': 'text/plain'}, b'User-agent: *\nAllow: /\n')


class RobotsRetryTests(unittest.TestCase):
    def test_timeout_recovers_and_redirect_evidence_is_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp)
            replies = [c.requests.exceptions.ConnectTimeout('connect timeout'),
                       (302, {'Location': 'https://example.org/rules'}, b'redirect'), ALLOW]
            with patch.object(f, 'request_once', side_effect=replies) as request, patch.object(c.time, 'sleep'):
                _, evidence = f.robot_policy('https://example.org/article')
            self.assertEqual(request.call_count, 3)
            self.assertEqual(evidence['attempt_count'], 2)
            self.assertEqual([r['attempt'] for r in evidence['requests']], [1, 2, 2])
            self.assertEqual(evidence['requests'][0]['exception_class'], 'ConnectTimeout')
            self.assertEqual(evidence['final_url'], 'https://example.org/rules')
            self.assertNotIn('error', evidence)
            self.assertFalse(evidence['cache_hit'])
            self.assertEqual(gzip.decompress((Path(tmp) / evidence['requests'][1]['raw_path']).read_bytes()), b'redirect')

    def test_failed_cache_expires_and_success_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp, robots_failure_ttl=30)
            clock = [100.0]
            def advance(seconds):
                clock[0] += seconds
            failures = [c.requests.exceptions.ConnectTimeout('timeout') for _ in range(3)]
            with patch.object(c.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(c.time, 'sleep', side_effect=advance):
                with patch.object(f, 'request_once', side_effect=[*failures, ALLOW]) as request:
                    with self.assertRaises(c.CrawlError):
                        f.robot_policy('https://example.org/one')
                    first = f.local.robot_evidence
                    with self.assertRaises(c.CrawlError):
                        f.robot_policy('https://example.org/two')
                    self.assertEqual(request.call_count, 3)
                    self.assertTrue(f.local.robot_evidence['cache_hit'])
                    self.assertEqual(first['fetch_id'], f.local.robot_evidence['fetch_id'])
                    advance(31)
                    _, recovered = f.robot_policy('https://example.org/three')
                    _, cached = f.robot_policy('https://example.org/four')
                    self.assertEqual(request.call_count, 4)
                    self.assertNotEqual(first['fetch_id'], recovered['fetch_id'])
                    self.assertFalse(recovered['cache_hit'])
                    self.assertTrue(cached['cache_hit'])

    def test_permanent_errors_do_not_retry(self):
        cases = [(403, {}, b'forbidden'), (200, {}, b'<!doctype html><html>error</html>'),
                 c.requests.exceptions.SSLError('certificate verification failed')]
        for reply in cases:
            with self.subTest(reply=reply), tempfile.TemporaryDirectory() as tmp:
                f = c.Fetcher(tmp)
                with patch.object(f, 'request_once', side_effect=[reply]) as request:
                    with self.assertRaises(c.CrawlError):
                        f.robot_policy('https://example.org/one')
                    with self.assertRaises(c.CrawlError):
                        f.robot_policy('https://example.org/two')
                self.assertEqual(request.call_count, 1)
                self.assertFalse(f.local.robot_evidence['retryable'])
                self.assertTrue(f.local.robot_evidence['cache_hit'])

    def test_retryable_http_statuses_recover(self):
        for status in (408, 429, 500, 502, 503, 504, 521):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                f = c.Fetcher(tmp)
                with patch.object(f, 'request_once', side_effect=[(status, {}, b'wait'), ALLOW]) as request, patch.object(c.time, 'sleep'):
                    _, evidence = f.robot_policy('https://example.org/article')
                self.assertEqual(request.call_count, 2)
                self.assertEqual(evidence['attempt_count'], 2)
                self.assertEqual(evidence['requests'][0]['http_status'], status)

    def test_long_retry_after_defers_and_extends_failure_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp, delay=0, robots_retry_budget=10, robots_failure_ttl=30)
            response = MagicMock(status_code=503, headers={'Retry-After': '120'})
            response.__enter__.return_value = response
            response.iter_content.return_value = [b'wait']
            session = MagicMock()
            session.get.return_value = response
            with patch.object(c.time, 'monotonic', return_value=100.), patch.object(c.time, 'sleep'), patch.object(f, 'validate'), patch.object(f, 'session', return_value=session):
                with self.assertRaises(c.CrawlError):
                    f.robot_policy('https://example.org/article')
                self.assertEqual(session.get.call_count, 1)
                evidence = f.local.robot_evidence
                self.assertEqual(evidence['failure_cache_ttl_seconds'], 120)
                self.assertIn('retry_deferred', evidence)
                self.assertEqual(session.get.call_args.kwargs['timeout'], (5., 5.))

    def test_budget_prevents_request_during_domain_cooldown(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp)
            f.next_at['example.org'] = 200
            with patch.object(c.time, 'monotonic', return_value=100.), patch.object(f, 'validate'), patch.object(f, 'session') as session:
                with self.assertRaisesRegex(c.CrawlError, 'cooldown'):
                    f.request_once('https://example.org/robots.txt', 1024, deadline=110.)
                session.assert_not_called()
            self.assertFalse(f.locks['example.org'].locked())

    def test_concurrent_urls_share_one_origin_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp)
            started, release = threading.Event(), threading.Event()
            def reply(*args, **kwargs):
                started.set()
                if not release.wait(5):
                    raise AssertionError('Concurrent test did not release robots request')
                return ALLOW
            with patch.object(f, 'request_once', side_effect=reply) as request, ThreadPoolExecutor(max_workers=5) as pool:
                futures = [pool.submit(f.robot_policy, f'https://example.org/{i}') for i in range(5)]
                try:
                    self.assertTrue(started.wait(5))
                finally:
                    release.set()
                traces = [future.result(timeout=5)[1] for future in futures]
            self.assertEqual(request.call_count, 1)
            self.assertEqual(sum(not e['cache_hit'] for e in traces), 1)
            self.assertEqual(len({e['fetch_id'] for e in traces}), 1)

    def test_disallowed_page_stays_blocked_and_has_failure_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = c.Fetcher(tmp)
            robots = (200, {}, b'User-agent: *\nDisallow: /\n')
            with patch.object(f, 'request_once', return_value=robots) as request:
                for i in range(2):
                    trace = {'requests': []}
                    with self.assertRaises(c.CrawlError) as caught:
                        f.fetch(f'https://example.org/{i}', trace)
                    self.assertEqual(caught.exception.status, 'robots_disallowed')
                    self.assertEqual(trace['requests'], [])
                    self.assertEqual(trace['robots']['cache_hit'], bool(i))
                self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
