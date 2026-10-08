"""Exercise the embedded notebook engines without external network or Chrome."""
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
from unittest.mock import Mock, patch
import uuid
import zlib


ROOT = Path(__file__).resolve().parents[1]


def assignments(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SeleniumFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scratch = ROOT / 'tmp'
        scratch.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=scratch)
        cls.root = Path(cls.temp.name)
        nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        pack = assignments(''.join(nb['cells'][6]['source']))
        for name, payload in pack['EMBEDDED_FILES'].items():
            data = zlib.decompress(base64.b85decode(payload))
            if hashlib.sha256(data).hexdigest() != pack['EMBEDDED_SHA256'][name]:
                raise AssertionError(f'Embedded snapshot hash mismatch: {name}')
            (cls.root / name).write_bytes(data)
        cls.crawler = load_module('fallback_test_crawler', cls.root / 'crawler_snapshot.py')
        cls.probe = load_module('fallback_test_probe', cls.root / 'priority_probe_snapshot.py')
        cls.runner = load_module('fallback_test_runner', cls.root / 'corpus_runner_snapshot.py')

    @classmethod
    def tearDownClass(cls):
        for name in ('fallback_test_crawler', 'fallback_test_probe', 'fallback_test_runner'):
            sys.modules.pop(name, None)
        cls.temp.cleanup()

    def good_record(self, **changes):
        record = {'id': 1, 'status': 'extracted', 'http_status': 200,
                  'content_type': 'text/html', 'text': 'Useful article. ' * 50,
                  'quality_status': 'accepted', 'quality_flags': []}
        record.update(changes)
        return record

    def test_every_request_or_quality_failure_selects_selenium(self):
        failures = [
            {'status': status} for status in (
                'http_error', 'network_error', 'response_deadline', 'unexpected_error',
                'redirect_limit', 'unsupported_content', 'oversized', 'rate_limited_deferred')
        ] + [
            {'http_status': status} for status in (None, 403, 404, 408, 429, 500, 503)
        ] + [
            {'challenge_detected': True}, {'text': ''}, {'text': ' \n\t '},
            {'quality_status': 'rejected'}, {'quality_status': 'review'}, {'quality_status': None},
            {'content_type': 'application/pdf', 'text': '', 'quality_status': 'rejected'},
        ] + [
            {'quality_flags': [flag]} for flag in (
                'short_text', 'missing_title', 'decode_suspect', 'encoding_or_script_review',
                'boilerplate_suspect', 'low_letter_ratio', 'repeated_lines', 'pdf_needs_ocr_review',
                'domain_parser_fallback', 'qa_without_answer', 'short_article_body',
                'office_or_markup_leak', 'error_or_challenge', 'redirect_review')
        ]
        sample = {'id': 1, 'url': 'https://example.org/article', 'domain': 'example.org'}
        for changes in failures:
            with self.subTest(changes=changes):
                record = self.good_record(**changes)
                self.assertTrue(self.probe.needs_browser(record))
                self.assertEqual(self.probe.select_browser_samples([sample], [record], 'failed_only'), [sample])

    def test_accepted_html_and_pdf_do_not_need_browser(self):
        for content_type in ('text/html', 'application/pdf'):
            self.assertFalse(self.probe.needs_browser(self.good_record(content_type=content_type)))

    def test_robots_and_invalid_addresses_remain_excluded(self):
        sample = {'id': 1, 'url': 'https://example.org/article'}
        for status in ('robots_unknown', 'robots_denied', 'robots_disallowed', 'invalid_url', 'unsafe_address'):
            with self.subTest(status=status):
                record = self.good_record(status=status)
                self.assertFalse(self.probe.needs_browser(record))
                self.assertEqual(self.probe.select_browser_samples([sample], [record], 'all'), [])

    def make_run(self):
        out = self.root / ('case_' + uuid.uuid4().hex)
        out.mkdir()
        sample = {'id': 1, 'url': 'https://example.org/article', 'domain': 'example.org'}
        self.crawler.jsonl(out / 'sample.jsonl', [sample])
        self.crawler.write_json(out / 'manifest.json', {
            'sample_sha256': self.crawler.file_hash(out / 'sample.jsonl'), 'sampling': 'test fixture',
        })
        self.crawler.write_json(out / 'source_profile.json', {
            'rows': 1, 'host_counts': {'example.org': 1}, 'sample_host_counts': {'example.org': 1},
        })
        return out

    def browser_result(self, crawler, driver, sample, out, **options):
        doc = {'title': 'Browser article', 'text': 'Useful article content with enough detail. ' * 30,
               'extractor': 'test-browser'}
        raw = ('<article>' + doc['text'] + '</article>').encode('utf-8')
        raw_path = 'raw/selenium/test.gz'
        crawler.atomic_bytes(out / raw_path, gzip.compress(raw, mtime=0))
        return {**sample, **doc, **crawler.quality(doc), 'engine': 'selenium', 'status': 'rendered',
                'http_status': 200, 'final_url': sample['url'], 'started_at': crawler.utc(),
                'raw_path': raw_path, 'raw_sha256': crawler.digest(raw)}

    def execute_failure(self, transport, *, parse_error=False, mode='failed_only', attempts=1):
        out = self.make_run()
        browser = Mock()
        console = io.StringIO()
        if isinstance(transport, BaseException):
            request_options = {'side_effect': transport}
        else:
            request_options = {'return_value': transport}
        with patch.object(self.crawler.Fetcher, 'request_once', **request_options) as request, \
                patch.object(self.probe, 'browser_preflight') as preflight, \
                patch.object(self.probe, 'create_browser', return_value=browser), \
                patch.object(self.probe, 'browser_attempt', side_effect=self.browser_result) as render, \
                patch.object(self.probe, 'wait_for_retry', return_value=True), \
                redirect_stdout(console):
            if parse_error:
                with patch.object(self.crawler, 'extract', side_effect=ValueError('parser failure')):
                    summary = self.runner.run(self.crawler, self.probe, out,
                                              {'browser_mode': mode, 'attempts': attempts, 'delay': 0}, workers=1)
            else:
                summary = self.runner.run(self.crawler, self.probe, out,
                                          {'browser_mode': mode, 'attempts': attempts, 'delay': 0}, workers=1)
        return out, summary, console.getvalue(), request.call_count, preflight, render

    def test_errors_reach_actual_browser_pass_and_accepted_corpus(self):
        cases = [
            (status, (status, {'Content-Type': 'text/html'}, b'<title>Server error</title>'), False)
            for status in (403, 404, 429, 500, 503)
        ] + [
            (type(error).__name__, error, False) for error in (
                self.crawler.requests.exceptions.ConnectTimeout('connect timed out'),
                self.crawler.requests.exceptions.ReadTimeout('read timed out'),
                self.crawler.requests.exceptions.SSLError('certificate failure'),
                self.crawler.requests.exceptions.ConnectionError('connection reset'),
            )
        ] + [
            ('challenge', (200, {'Content-Type': 'text/html'},
             b'<html><body><script>document.cookie="x=y";location.reload()</script></body></html>'), False),
            ('empty', (200, {'Content-Type': 'text/html'}, b'<html><body></body></html>'), False),
            ('parser', (200, {'Content-Type': 'text/html'}, b'<html><body>article</body></html>'), True),
        ]
        for name, transport, parse_error in cases:
            with self.subTest(name=name):
                out, summary, console, _, preflight, render = self.execute_failure(transport, parse_error=parse_error)
                preflight.assert_called_once()
                render.assert_called_once()
                self.assertEqual(summary['browser_recovered'], 1)
                self.assertIn('"selenium_fallback_scheduled": 1', console)
                canonical = self.crawler.load_json(out / 'records/1.json')
                original = self.crawler.load_json(out / 'requests_records/1.json')
                self.assertEqual(canonical['requests_status'], original['status'])
                self.assertEqual(canonical['selenium_fallback_reason'], self.probe.browser_fallback_reason(original))
                self.assertEqual((canonical['status'], canonical['engine'], canonical['quality_status']),
                                 ('extracted', 'selenium', 'accepted'))
                accepted = [json.loads(line) for line in (out / 'corpus.accepted.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertEqual(len(accepted), 1)
                self.assertEqual((accepted[0]['id'], accepted[0]['text']), (1, canonical['text']))

    def test_request_retries_finish_before_selenium(self):
        for transport in (
            self.crawler.requests.exceptions.ReadTimeout('read timed out'),
            (503, {'Content-Type': 'text/html'}, b'<title>Server error</title>'),
        ):
            with self.subTest(transport=transport):
                _, _, _, count, _, render = self.execute_failure(transport, attempts=3)
                self.assertEqual(count, 3)
                render.assert_called_once()

    def test_failed_browser_does_not_become_accepted(self):
        out = self.make_run()
        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(403, {'Content-Type': 'text/html'}, b'<title>Access denied</title>')), \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', return_value=Mock()), \
                patch.object(self.probe, 'browser_attempt', side_effect=lambda crawler, driver, sample, out, **kw:
                             {**sample, 'status': 'browser_error', 'engine': 'selenium',
                              'http_status': None, 'error': 'Browser could not load the page'}), \
                redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, out, {'attempts': 1, 'delay': 0}, workers=1)
        self.assertEqual(summary['failed'], 1)
        canonical = self.crawler.load_json(out / 'records/1.json')
        self.assertEqual(canonical['browser_status'], 'browser_error')
        self.assertEqual(canonical['browser_error'], 'Browser could not load the page')
        self.assertEqual((out / 'corpus.accepted.jsonl').read_text(encoding='utf-8'), '')

    def test_preflight_failure_stops_before_requests(self):
        out = self.make_run()
        with patch.object(self.probe, 'create_browser', side_effect=RuntimeError('Chrome unavailable')), \
                patch.object(self.crawler.Fetcher, 'request_once') as request, redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Chrome preflight failed'):
                self.runner.run(self.crawler, self.probe, out, {}, workers=1)
        request.assert_not_called()
        self.assertEqual(self.crawler.load_json(out / 'browser_preflight.json')['status'], 'failed')
        self.assertIn('Chrome unavailable', self.crawler.load_json(out / 'browser_setup_error.json')['error'])

    def test_failed_request_checkpoint_resumes_into_selenium(self):
        out, _, _, _, _, _ = self.execute_failure(
            (403, {'Content-Type': 'text/html'}, b'<title>Access denied</title>'), mode='off')
        # Simulate interruption after the Requests checkpoint, before the browser pass.
        (out / 'corpus_config.json').unlink()
        config = {'version': self.runner.VERSION, 'settings': dict(self.runner.DEFAULTS, attempts=1, delay=0),
                  'runner_sha256': self.crawler.file_hash(self.runner.__file__),
                  'crawler_sha256': self.crawler.file_hash(self.crawler.__file__),
                  'probe_sha256': self.crawler.file_hash(self.probe.__file__)}
        self.crawler.write_json(out / 'corpus_config.json', config)
        with patch.object(self.crawler.Fetcher, 'request_once') as request, \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', return_value=Mock()), \
                patch.object(self.probe, 'browser_attempt', side_effect=self.browser_result) as render, \
                redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, out, {'attempts': 1, 'delay': 0}, workers=1)
        request.assert_not_called()
        render.assert_called_once()
        self.assertEqual(summary['browser_recovered'], 1)

    def test_browser_startup_failure_keeps_failure_and_evidence(self):
        out = self.make_run()
        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(403, {'Content-Type': 'text/html'}, b'<title>Access denied</title>')), \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser', side_effect=RuntimeError('Chrome crashed')), \
                redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, out, {'attempts': 1, 'delay': 0}, workers=1)
        self.assertEqual(summary['failed'], 1)
        self.assertIn('Chrome crashed', self.crawler.load_json(out / 'browser_setup_error.json')['error'])
        self.assertEqual((out / 'corpus.accepted.jsonl').read_text(encoding='utf-8'), '')

    def test_manual_off_switch_is_explicit(self):
        _, summary, console, _, preflight, render = self.execute_failure(
            (403, {'Content-Type': 'text/html'}, b'<title>Access denied</title>'), mode='off')
        preflight.assert_not_called()
        render.assert_not_called()
        self.assertNotIn('selenium_fallback_scheduled', console)
        self.assertEqual(summary['failed'], 1)

    def test_notebooks_have_same_probe_and_enabled_fallback(self):
        expected = (self.root / 'priority_probe_snapshot.py').read_bytes()
        for name in ('crawl_corpus_kaggle_hf_upload', 'crawl_domain_samples'):
            nb = json.loads((ROOT / 'notebooks' / f'{name}.ipynb').read_text(encoding='utf-8'))
            config_index, snapshot_index = (3, 7) if name == 'crawl_domain_samples' else (2, 6)
            self.assertEqual(assignments(''.join(nb['cells'][config_index]['source']))['BROWSER_TEST_MODE'], 'failed_only')
            pack = assignments(''.join(nb['cells'][snapshot_index]['source']))
            if name == 'crawl_domain_samples':
                payload, expected_hash = pack['PRIORITY_PAYLOAD'], pack['PRIORITY_SHA256']
            else:
                payload = pack['EMBEDDED_FILES']['priority_probe_snapshot.py']
                expected_hash = pack['EMBEDDED_SHA256']['priority_probe_snapshot.py']
            data = zlib.decompress(base64.b85decode(payload))
            self.assertEqual(data, expected)
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected_hash)


if __name__ == '__main__':
    unittest.main()
