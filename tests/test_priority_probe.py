from concurrent.futures import ThreadPoolExecutor
import importlib.util
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
c = load('priority_test_core', ROOT / 'src/vibiomir/corpus/crawler.py')
p = load('priority_test_probe', ROOT / 'src/vibiomir/corpus/priority_probe.py')
UA = 'Mozilla/5.0 Chrome/130.0.0.0 Safari/537.36'


class PriorityProbeTests(unittest.TestCase):
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
            def fetch(core, fetcher, sample, out, *args):
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
