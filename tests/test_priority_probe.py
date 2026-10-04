from concurrent.futures import ThreadPoolExecutor
import importlib.util
import gzip
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parents[1]
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
c = load('priority_test_core', ROOT / 'src/vibiomir/crawl/crawler.py')
p = load('priority_test_probe', ROOT / 'src/vibiomir/crawl/priority_probe.py')
UA = 'Mozilla/5.0 Chrome/130.0.0.0 Safari/537.36'


class PriorityProbeTests(unittest.TestCase):
    def test_network_retry_uses_fresh_session_and_preserves_cookies(self):
        body = b'<html><title>Article</title><article><p>' + b'Medical article content. ' * 40 + b'</p></article></html>'
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp, attempts=3)
            original = fetcher.session()
            original.cookies.set('language', 'zh')
            seen = []
            def request(*args, **kwargs):
                seen.append(fetcher.session())
                if len(seen) == 1:
                    raise c.requests.exceptions.ConnectionError('RemoteDisconnected: Remote end closed connection without response')
                return 200, {'content-type': 'text/html; charset=utf-8'}, body
            with patch.object(fetcher, 'request_once', side_effect=request), patch.object(p.time, 'sleep'):
                record = p.request_record(c, fetcher, {'id': 1, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), 180)
            self.assertEqual(record['status'], 'extracted')
            self.assertEqual(len(seen), 2)
            self.assertIsNot(seen[0], seen[1])
            self.assertEqual(seen[1].cookies.get('language'), 'zh')
            self.assertEqual(seen[1].headers['User-Agent'], UA)
            self.assertEqual(record['requests'][0]['error_kind'], 'connection_closed')
            self.assertTrue(record['requests'][0]['session_reset_for_retry'])
            self.assertGreaterEqual(record['requests'][0]['retry_wait_seconds'], 2)

    def test_ssl_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp, attempts=3)
            with patch.object(fetcher, 'request_once', side_effect=c.requests.exceptions.SSLError('certificate verify failed')) as request:
                record = p.request_record(c, fetcher, {'id': 2, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), 180)
            self.assertEqual(record['status'], 'network_error')
            self.assertEqual(record['error_kind'], 'ssl_error')
            self.assertFalse(record['retryable'])
            self.assertEqual(request.call_count, 1)

    def test_raw_write_failure_is_not_misreported_as_network_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp, attempts=3)
            atomic = c.atomic_bytes
            def save(path, data):
                if Path(path).suffix == '.gz':
                    raise OSError('Cannot save raw response')
                return atomic(path, data)
            with patch.object(fetcher, 'request_once', return_value=(200, {}, b'Article')) as request, patch.object(c, 'atomic_bytes', side_effect=save):
                record = p.request_record(c, fetcher, {'id': 12, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), 180)
            self.assertEqual(record['status'], 'unexpected_error')
            self.assertIn('Cannot save raw', record['error'])
            self.assertEqual(request.call_count, 1)

    def test_exhausted_budget_preserves_network_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp, attempts=3)
            with patch.object(fetcher, 'request_once', side_effect=c.requests.exceptions.ReadTimeout('read timed out')) as request, patch.object(p.time, 'sleep') as sleep:
                record = p.request_record(c, fetcher, {'id': 3, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), .1)
            self.assertEqual(record['error_kind'], 'read_timeout')
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()
            self.assertIn('budget', record['retry_deferred'])

    def test_retry_after_does_not_sleep_past_budget_or_lose_error_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp, attempts=3)
            def request(*args, **kwargs):
                fetcher.next_at['example.org'] = p.time.monotonic() + 120
                return 503, {'Content-Type': 'text/html', 'Retry-After': '120'}, b'<html>Service unavailable</html>'
            with patch.object(fetcher, 'request_once', side_effect=request) as mocked, patch.object(p.time, 'sleep') as sleep:
                record = p.request_record(c, fetcher, {'id': 4, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), 30)
            self.assertEqual(record['status'], 'http_error')
            self.assertEqual(record['http_status'], 503)
            self.assertEqual(mocked.call_count, 1)
            sleep.assert_not_called()
            self.assertTrue((Path(tmp) / record['raw_path']).is_file())
            self.assertIn('budget', record['retry_deferred'])

    def test_intermediate_http_error_body_is_kept_after_retry_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp, attempts=3)
            body = b'<html><title>Article</title><article>' + b'Medical article. ' * 50 + b'</article></html>'
            with patch.object(fetcher, 'request_once', side_effect=[(500, {}, b'Backend error'), (200, {'Content-Type': 'text/html'}, body)]), patch.object(p.time, 'sleep'):
                record = p.request_record(c, fetcher, {'id': 5, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), 180)
            self.assertEqual(record['status'], 'extracted')
            first = record['requests'][0]
            self.assertEqual(gzip.decompress((Path(tmp) / first['raw_path']).read_bytes()), b'Backend error')
            self.assertNotEqual(first['raw_sha256'], record['raw_sha256'])

    def test_http_200_challenge_is_not_a_successful_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp)
            with patch.object(fetcher, 'request_once', return_value=(200, {'cf-mitigated': 'challenge'}, b'<html><title>Just a moment...</title></html>')):
                record = p.request_record(c, fetcher, {'id': 6, 'url': 'https://example.org/a'}, tmp, UA, (20, 45), 180)
            self.assertEqual(record['status'], 'http_error')
            self.assertTrue(record['challenge_detected'])
            self.assertEqual(p.access_outcome(record)[0], 'KHONG_VAO_DUOC')

    def test_recovery_reuses_verified_success_and_leaves_failed_id_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / 'source', Path(tmp) / 'recovery'
            c.write_json(source / 'manifest.json', {})
            body = b'<html><title>Article</title><article>' + b'Medical source. ' * 50 + b'</article></html>'
            raw = Path('raw/example.gz')
            c.atomic_bytes(source / raw, gzip.compress(body))
            samples = [{'id': 7, 'url': 'https://example.org/a', 'domain': 'example.org'},
                       {'id': 8, 'url': 'https://example.org/b', 'domain': 'example.org'}]
            c.write_json(source / 'records/7.json', dict(samples[0], status='extracted', http_status=200,
                         content_type='text/html', raw_path=raw.as_posix(), raw_sha256=c.digest(body)))
            c.write_json(source / 'records/8.json', dict(samples[1], status='network_error', error='read timed out'))
            result = p.seed_successful_requests(c, out, samples, source)
            self.assertEqual(result['reused_ids'], [7])
            self.assertEqual(result['retry_ids'], [8])
            self.assertFalse((out / 'records/8.json').exists())
            record = c.load_json(out / 'records/7.json')
            self.assertEqual(record['text_sha256'], c.digest(record['text'].encode()))
            self.assertTrue((out / record['raw_path']).is_file())
            self.assertEqual(p.seed_successful_requests(c, out, samples, source), result)
            with self.assertRaisesRegex(ValueError, 'source changed'):
                p.seed_successful_requests(c, out, samples[:1], source)

    def test_recovery_rejects_corrupted_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / 'source', Path(tmp) / 'recovery'
            c.write_json(source / 'manifest.json', {})
            c.atomic_bytes(source / 'raw/a.gz', gzip.compress(b'changed raw'))
            sample = {'id': 9, 'url': 'https://example.org/a'}
            c.write_json(source / 'records/9.json', dict(sample, status='extracted', http_status=200,
                         content_type='text/html', raw_path='raw/a.gz', raw_sha256=c.digest(b'original raw')))
            with self.assertRaisesRegex(ValueError, 'hash/size mismatch'):
                p.seed_successful_requests(c, out, [sample], source)
            self.assertFalse((out / 'records/9.json').exists())

    def test_recovery_does_not_reuse_legacy_http_200_challenge(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, out = Path(tmp) / 'source', Path(tmp) / 'recovery'
            c.write_json(source / 'manifest.json', {})
            body = b'<html><title>Just a moment...</title></html>'
            c.atomic_bytes(source / 'raw/a.gz', gzip.compress(body))
            sample = {'id': 11, 'url': 'https://example.org/a'}
            c.write_json(source / 'records/11.json', dict(sample, status='extracted', http_status=200,
                         content_type='text/html', raw_path='raw/a.gz', raw_sha256=c.digest(body)))
            result = p.seed_successful_requests(c, out, [sample], source)
            self.assertEqual(result['retry_ids'], [11])
            self.assertEqual(result['reused_ids'], [])
            self.assertFalse((out / 'records/11.json').exists())

    def test_browser_fallback_changes_access_without_hiding_requests_error(self):
        record = {'status': 'network_error', 'error': 'read timed out'}
        browser = {'status': 'rendered', 'http_status': 200, 'quality_status': 'accepted'}
        self.assertEqual(p.access_outcome(record, browser), ('VAO_DUOC', 'selenium', browser))
        self.assertEqual(record['status'], 'network_error')
        self.assertTrue(p.retry_browser({'status': 'browser_navigation_timeout'}))
        self.assertFalse(p.retry_browser({'status': 'http_error', 'http_status': 403, 'challenge_detected': True}))
        self.assertEqual(p.access_outcome(record, dict(browser, challenge_detected=True))[0], 'KHONG_VAO_DUOC')

    def test_browser_retries_timeout_but_stops_when_article_is_loaded(self):
        from selenium import webdriver
        with tempfile.TemporaryDirectory() as tmp:
            sample = {'id': 10, 'url': 'https://example.org/a', 'domain': 'example.org'}
            driver = MagicMock()
            driver.capabilities = {'browserVersion': '154'}
            driver.execute_script.return_value = 'Mozilla/5.0 Chrome/154.0.0.0 Safari/537.36'
            first = dict(sample, status='browser_navigation_timeout', error='navigation timed out')
            second = dict(sample, status='rendered', http_status=200, char_count=500)
            with patch.object(webdriver, 'Chrome', return_value=driver), patch.object(p, 'browser_attempt', side_effect=[first, second]) as attempt, patch.object(p.time, 'sleep'):
                p.crawl_browser(c, tmp, [sample], attempts=2)
            result = c.load_json(Path(tmp) / 'browser_records/10.json')
            self.assertEqual(result['status'], 'rendered')
            self.assertEqual(result['attempt_count'], 2)
            self.assertEqual(result['browser_attempts'][0]['status'], 'browser_navigation_timeout')
            self.assertEqual(attempt.call_count, 2)
            driver.quit.assert_called_once()

    def test_public_page_probe_keeps_source_and_extracts_with_browser_headers(self):
        body = ('<html><head><title>Medical source</title></head><body><article><p>'
                + 'Detailed medical source material for extraction. ' * 30 + '</p></article></body></html>').encode()
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp)
            sample = {'id': 583, 'url': 'https://example.org/medical', 'domain': 'example.org'}
            with patch.object(fetcher, 'request_once', return_value=(200, {'Content-Type': 'text/html; charset=utf-8'}, body)), patch.object(fetcher, 'robot_policy', side_effect=AssertionError('Diagnostic must request the page')):
                record = p.request_record(c, fetcher, sample, tmp, UA, (15, 25), 75)
            self.assertEqual(record['status'], 'extracted')
            self.assertEqual(record['id'], 583)
            self.assertEqual(record['url'], sample['url'])
            self.assertEqual(record['quality_status'], 'accepted')
            self.assertEqual(record['text_sha256'], c.digest(record['text'].encode()))
            self.assertEqual(fetcher.session().headers['User-Agent'], UA)
            self.assertNotIn('Crawler', fetcher.session().headers['User-Agent'])

    def test_forbidden_page_is_reported_and_not_retried(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = c.Fetcher(tmp)
            sample = {'id': 584, 'url': 'https://example.org/article', 'domain': 'example.org'}
            with patch.object(fetcher, 'request_once', return_value=(403, {'Content-Type': 'text/html'}, b'<html><title>Just a moment...</title></html>')) as request:
                record = p.request_record(c, fetcher, sample, tmp, UA, (15, 25), 75)
            self.assertEqual(record['status'], 'http_error')
            self.assertEqual(record['http_status'], 403)
            self.assertEqual(request.call_count, 1)
            self.assertTrue((Path(tmp) / record['raw_path']).is_file())

    def test_domain_samples_do_not_compete_with_their_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            barrier, guard = threading.Barrier(2), threading.Lock()
            active, maximum = {}, {}
            samples = [{'id': i, 'url': f'https://{host}/{i}', 'domain': host} for i, host in
                       [(1, 'a.org'), (2, 'a.org'), (3, 'b.org'), (4, 'b.org')]]
            def fetch(core, fetcher, sample, out, *args, **kwargs):
                host = sample['domain']
                with guard:
                    active[host] = active.get(host, 0) + 1
                    maximum[host] = max(maximum.get(host, 0), active[host])
                barrier.wait(timeout=5)
                record = dict(sample, status='extracted', http_status=200)
                core.write_json(Path(out) / 'records' / f"{sample['id']}.json", record)
                with guard:
                    active[host] -= 1
                return record
            with patch.object(p, 'request_record', side_effect=fetch):
                records = p.crawl_requests(c, tmp, samples, workers=2, user_agent=UA)
            self.assertEqual(len(records), 4)
            self.assertEqual(maximum, {'a.org': 1, 'b.org': 1})

    def test_main_document_http_status_excludes_iframes_and_images(self):
        def event(kind, frame, url, status):
            return {'message': json.dumps({'message': {'method': 'Network.responseReceived',
                         'params': {'type': kind, 'frameId': frame, 'response': {'url': url, 'status': status}}}})}
        url = 'https://example.org/article'
        events = [event('Document', 'main', url, 403), event('Document', 'iframe', url, 200),
                  event('Image', 'main', url, 200)]
        self.assertEqual(p.main_document_status(events, url, 'main'), 403)
        self.assertIsNone(p.main_document_status(events[1:], url, 'main'))

    def test_empty_browser_page_is_not_reported_as_rendered(self):
        status, error = p.browser_outcome({'final_url': 'about:blank', 'char_count': 0,
                                         'navigation_warning': 'navigation timed out', 'http_status': None})
        self.assertEqual(status, 'browser_navigation_timeout')
        self.assertIn('timed out', error)

    def test_challenge_text_does_not_end_the_render_wait(self):
        driver = MagicMock()
        driver.execute_script.return_value = {'title': 'Just a moment...', 'text': 'Performing security verification. ' * 20}
        self.assertFalse(p.browser_page_ready(driver))
        driver.execute_script.return_value = {'title': 'Medical article', 'text': 'Detailed medical source material. ' * 20}
        self.assertTrue(p.browser_page_ready(driver))


if __name__ == '__main__':
    unittest.main()
