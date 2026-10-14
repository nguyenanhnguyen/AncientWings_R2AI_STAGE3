"""IP observations must not turn a generic denial, missing URL or parser failure into an IP ban."""
from contextlib import redirect_stdout
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_notebook_selenium_fallback import assignments, load_module
import test_notebook_pubmed_parser as fixtures

ROOT = Path(__file__).resolve().parents[1]


class DomainIpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PubMedParserTests.setUpClass.__func__(cls)
        cls.ip = load_module('domain_ip_test', ROOT / 'scripts/domain_ip_diagnostics.py')

    @classmethod
    def tearDownClass(cls):
        fixtures.PubMedParserTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixtures.PubMedParserTests.setUp(self)

    def classify(self, status, body, **extra):
        return self.ip.classify(dict(status='observed', http_status=status, **extra), body.encode())

    def test_plain_403_is_suspicion_and_not_an_ip_block_message(self):
        row = self.classify(403, '<title>Forbidden</title>Forbidden', quality_flags=['error_or_challenge'])
        self.assertFalse(row['ip_block_message'])
        self.assertEqual(row['category'], 'ACCESS_DENIED')
        self.assertEqual(self.ip.verdict([row])[0], 'ACCESS_BLOCK_SUSPECTED')

    def test_explicit_ip_message_is_kept_but_negation_and_article_mentions_are_not(self):
        row = self.classify(403, '<h1>Your IP address 8.8.8.8 has been blocked</h1>')
        # Servers also use the pronoun form without repeating the literal address.
        row2 = self.classify(403, '<h1>Your IP address has been blocked</h1>')
        self.assertTrue(row2['ip_block_message'])
        row3 = self.classify(403, '<h1>IP address 8.8.8.8 has been blocked</h1>')
        self.assertTrue(row3['ip_block_message'])
        self.assertFalse(self.classify(200, 'Your IP address is not blocked')['ip_block_message'])
        article = 'A medical research article. ' * 100 + 'Your IP address has been blocked is an example error message.'
        self.assertFalse(self.classify(200, article)['ip_block_message'])

    def test_cookie_gate_even_with_2xx_is_not_accessible(self):
        row = self.classify(203, fixtures.COOKIE_HEADING.decode())
        self.assertEqual(row['category'], 'CHALLENGE_OR_ERROR_PAGE')
        self.assertFalse(row['ip_block_message'])

    def test_rate_limit_missing_url_network_and_parser_review_are_separate(self):
        self.assertEqual(self.classify(429, 'Too many requests')['category'], 'RATE_LIMITED')
        self.assertEqual(self.classify(404, 'Not found')['category'], 'URL_NOT_FOUND')
        self.assertEqual(self.ip.classify({'status': 'network_error', 'error': 'DNS failed'})['category'], 'NETWORK_OR_BROWSER_ERROR')
        self.assertEqual(self.classify(200, 'A real article', quality_status='review',
                                      quality_flags=['domain_parser_fallback'])['category'], 'HTTP_ACCESS_OK')

    def test_requests_challenge_and_browser_success_do_not_mean_hostname_ip_ban(self):
        rows = [self.classify(203, fixtures.COOKIE_HEADING.decode()), self.classify(200, 'A real article')]
        self.assertEqual(self.ip.verdict(rows)[0], 'SOME_URL_ACCESSIBLE')
        self.assertEqual(self.ip.verdict([self.ip.classify({})])[0], 'NOT_TESTED')

    def test_ip_parser_rejects_html_fake_private_and_invalid_addresses(self):
        self.assertEqual(self.ip.parse_ip('{"ip":"8.8.8.8"}'), '8.8.8.8')
        self.assertEqual(self.ip.parse_ip('2606:4700:4700::1111'), '2606:4700:4700::1111')
        for value in ('<html>Access denied</html>', '{"ip":"192.168.1.1"}', 'not an IP'):
            self.assertIsNone(self.ip.parse_ip(value))

    def make_evidence(self, status, body):
        sample = {'id': 1, 'url': 'https://example.org/article', 'domain': 'example.org'}
        raw = body.encode()
        self.crawler.atomic_bytes(self.out / 'raw/article.gz', gzip.compress(raw, mtime=0))
        record = dict(sample, status='extracted', http_status=status, raw_path='raw/article.gz',
                      raw_sha256=self.crawler.digest(raw), quality_status='rejected')
        self.crawler.write_json(self.out / 'records/1.json', record)
        return sample

    def test_report_preserves_raw_evidence_and_does_not_confuse_homepage_with_articles(self):
        sample = self.make_evidence(403, 'Forbidden')
        key = self.ip.hashlib.sha256(b'example.org').hexdigest()
        self.crawler.write_json(self.out / 'network_controls' / (key + '.json'), {
            'http_status': 200, 'category': 'HTTP_ACCESS_OK', 'final_hostname': 'example.org'})
        self.ip.build_report(self.crawler, self.out, [sample], {'host_counts': {'example.org': 20}})
        report = self.crawler.load_json(self.out / 'ip_block_report.json')
        self.assertEqual(report['hosts'][0]['verdict'], 'ARTICLES_DENIED_HOMEPAGE_OK')
        self.assertEqual(report['hosts'][0]['ip_block_messages'], 0)
        evidence = [json.loads(line) for line in (self.out / 'ip_url_evidence.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(evidence[0]['raw_path'], 'raw/article.gz')
        self.assertTrue((self.out / 'ip_block_report.html').exists())

    def test_corrupt_or_external_raw_is_not_used_as_ip_block_proof(self):
        sample = self.make_evidence(403, 'Your IP address has been blocked')
        path = self.out / 'records/1.json'
        record = self.crawler.load_json(path)
        for raw_path in ('raw/article.gz', '../outside.gz'):
            record.update(raw_sha256='wrong', raw_path=raw_path)
            self.crawler.write_json(path, record)
            self.ip.build_report(self.crawler, self.out, [sample], {'host_counts': {'example.org': 20}})
            self.assertEqual(self.crawler.load_json(self.out / 'ip_block_report.json')['hosts'][0]['ip_block_messages'], 0)

    def test_ip_provider_and_browser_setup_failures_do_not_stop_host_diagnostics(self):
        with patch.object(self.crawler.Fetcher, 'request_once', side_effect=OSError('network unavailable')), \
                patch.object(self.probe, 'create_browser', side_effect=RuntimeError('Chrome unavailable')), \
                patch.object(self.ip.socket, 'getaddrinfo', return_value=[]), redirect_stdout(io.StringIO()):
            result = self.ip.collect_network(self.crawler, self.probe, self.out, ['example.org'], user_agent='Test')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['requests_ips'], [])
        self.assertEqual(result['selenium_ips'], [])
        self.assertIn('Chrome unavailable', result['browser_ip_error'])

    def test_resume_remeasures_ip_and_keeps_previous_measurement(self):
        address = ['8.8.8.8']
        def response(url, *args, **kwargs):
            body = json.dumps({'ip': address[0]}).encode() if 'ipify.org' in url else b'<html>Home page</html>'
            return 200, {'Content-Type': 'text/html'}, body
        with patch.object(self.crawler.Fetcher, 'request_once', side_effect=response), \
                patch.object(self.ip.socket, 'getaddrinfo', return_value=[]), redirect_stdout(io.StringIO()):
            first = self.ip.collect_network(self.crawler, self.probe, self.out, ['example.org'], user_agent='Test', browser_ip=False)
            address[0] = '1.1.1.1'
            second = self.ip.collect_network(self.crawler, self.probe, self.out, ['example.org'], user_agent='Test', browser_ip=False)
        self.assertEqual(first['requests_ips'], ['8.8.8.8'])
        self.assertEqual(second['requests_ips'], ['1.1.1.1'])
        self.assertTrue((self.out / 'network_history' / first['measurement_id'] / 'network_check.json').exists())


if __name__ == '__main__':
    unittest.main()
