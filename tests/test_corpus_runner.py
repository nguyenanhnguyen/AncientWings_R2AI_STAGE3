"""Exercise shared HTTP/browser engines through corpus audit, export and recovery."""
import argparse
from contextlib import redirect_stdout
import gzip
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).parents[1]
MODULES = ROOT / 'src/vibiomir/crawl'


def load(name):
    spec = importlib.util.spec_from_file_location('corpus_test_' + name, MODULES / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


c, p, runner, diagnostics = (load(name) for name in ('crawler', 'priority_probe', 'corpus_runner', 'diagnostics'))
BODY = b'<html><head><title>Clinical study</title></head><body><article><p>' + b'Medical source evidence and treatment findings. ' * 40 + b'</p></article></body></html>'


class CorpusRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.stdout = redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def prepare(self, name='run', hosts=('example.org',)):
        source = self.root / 'source.parquet'
        pq.write_table(pa.table({'id': list(range(1, len(hosts) + 1)),
                                'url': [f'https://{host}/{i}' for i, host in enumerate(hosts, 1)]}), source)
        out = self.root / name
        c.prepare(argparse.Namespace(source=source, out=out, size=len(hosts), seed=42))
        return out

    def browser(self, core, out, samples, **options):
        for sample in samples:
            raw = f"raw/selenium/{sample['id']}.gz"
            core.atomic_bytes(out / raw, gzip.compress(BODY))
            doc = core.extract(BODY, 'text/html; charset=utf-8', sample['url'])
            record = dict(sample, engine='selenium', status='rendered', http_status=200,
                          final_url=sample['url'], raw_path=raw, raw_sha256=core.digest(BODY),
                          **doc, **core.quality(doc))
            core.write_json(out / 'browser_records' / f"{sample['id']}.json", record)
            options['on_record'](record)

    def test_browser_recovery_is_audited_exported_and_retains_request_error(self):
        out = self.prepare()
        with patch.object(c.Fetcher, 'request_once', return_value=(403, {'Content-Type': 'text/html'}, b'<html>Forbidden</html>')), patch.object(p, 'crawl_browser', side_effect=self.browser):
            summary = runner.run(c, p, out, {})
        self.assertEqual((summary['accessible'], summary['browser_recovered']), (1, 1))
        record = c.load_json(out / 'records/1.json')
        self.assertEqual((record['status'], record['quality_status'], record['engine']), ('extracted', 'accepted', 'selenium'))
        self.assertEqual(record['requests_http_status'], 403)
        self.assertEqual(c.load_json(out / record['requests_record_path'])['status'], 'http_error')
        self.assertEqual(gzip.decompress((out / record['requests'][0]['raw_path']).read_bytes()), b'<html>Forbidden</html>')
        for script in ('audit.py', 'export.py'):
            subprocess.run([sys.executable, str(MODULES / script), '--out', str(out)], check=True, capture_output=True)
        self.assertEqual(pq.read_table(out / 'corpus.parquet')['id'].to_pylist(), [1])
        archive = self.root / 'diagnostics.zip'
        diagnostics.build_archive(out, archive)
        with zipfile.ZipFile(archive) as bundle:
            self.assertIsNone(bundle.testzip())
            self.assertIn('samples/requests_records/1.json', bundle.namelist())
            self.assertIn('samples/browser_records/1.json', bundle.namelist())
            self.assertIn('metadata/requests_vs_selenium.csv', bundle.namelist())
        before = (out / 'records/1.json').read_bytes()
        with patch.object(c.Fetcher, 'request_once', side_effect=AssertionError('Unexpected network')):
            runner.run(c, p, out, {})
        self.assertEqual((out / 'records/1.json').read_bytes(), before)

    def test_recovery_reuses_browser_raw_and_retries_only_failed_ids(self):
        source = self.prepare('source_run', ('example.org', 'other.org'))
        def one_browser(core, out, samples, **options):
            self.browser(core, out, [s for s in samples if s['id'] == 1], **options)
        with patch.object(c.Fetcher, 'request_once', return_value=(403, {}, b'<html>Forbidden</html>')), patch.object(p, 'crawl_browser', side_effect=one_browser):
            runner.run(c, p, source, {})
        before = (source / 'records/1.json').read_bytes()
        out = self.prepare('recovered', ('example.org', 'other.org'))
        with patch.object(c.Fetcher, 'request_once', return_value=(200, {'Content-Type': 'text/html'}, BODY)) as request:
            summary = runner.run(c, p, out, {'browser_mode': 'off'}, recovery_source=source)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], 'https://other.org/2')
        self.assertEqual(summary['accessible'], 2)
        self.assertEqual(c.load_json(out / 'recovery_manifest.json')['reused_ids'], [1])
        self.assertEqual((source / 'records/1.json').read_bytes(), before)
        record = c.load_json(out / 'records/1.json')
        self.assertTrue((out / record['requests'][0]['raw_path']).is_file())
        with patch.object(c.Fetcher, 'request_once', side_effect=AssertionError('Unexpected network')):
            runner.run(c, p, out, {'browser_mode': 'off'}, recovery_source=source)
        subprocess.run([sys.executable, str(MODULES / 'audit.py'), '--out', str(out)], check=True, capture_output=True)

    def test_robots_failure_never_falls_through_to_page_or_browser(self):
        out = self.prepare()
        with patch.object(c.Fetcher, 'robot_policy', side_effect=c.CrawlError('robots_denied')), patch.object(c.Fetcher, 'request_once') as request, patch.object(p, 'crawl_browser') as browser:
            runner.run(c, p, out, {'respect_robots': True})
        request.assert_not_called()
        browser.assert_not_called()
        self.assertEqual(c.load_json(out / 'records/1.json')['status'], 'robots_denied')

    def test_shared_page_fetch_checks_robots_again_after_redirect(self):
        out = self.prepare()
        with patch.object(c.Fetcher, 'robot_policy', side_effect=[(2., {}), c.CrawlError('robots_disallowed')]) as robots, patch.object(c.Fetcher, 'request_once', return_value=(302, {'Location': 'https://other.org/new'}, b'')) as request:
            runner.run(c, p, out, {'respect_robots': True, 'browser_mode': 'off'})
        self.assertEqual(robots.call_count, 2)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs['delay'], 2.)
        self.assertEqual(c.load_json(out / 'records/1.json')['status'], 'robots_disallowed')

    def test_retry_settings_and_original_error_survive_corpus_pipeline(self):
        out = self.prepare()
        with patch.object(c.Fetcher, 'request_once', side_effect=[c.requests.exceptions.ReadTimeout('timed out'), (200, {'Content-Type': 'text/html'}, BODY)]) as request, patch.object(p.time, 'sleep'):
            runner.run(c, p, out, {'browser_mode': 'off'})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args.kwargs['timeout'], [20., 45.])
        record = c.load_json(out / 'records/1.json')
        self.assertEqual(record['requests'][0]['error_kind'], 'read_timeout')
        self.assertTrue(record['requests'][0]['session_reset_for_retry'])
        self.assertEqual(record['quality_status'], 'accepted')
        with self.assertRaisesRegex(ValueError, 'code/config changed'):
            runner.run(c, p, out, {'browser_mode': 'off', 'budget': 200.})

    def test_failed_domains_are_ordered_by_dataset_population(self):
        out = self.prepare(hosts=('small.org', 'large.org', 'large.org'))
        with patch.object(c.Fetcher, 'request_once', return_value=(403, {}, b'<html>Forbidden</html>')):
            runner.run(c, p, out, {'browser_mode': 'off'})
        priorities = c.load_json(out / 'uu_tien_fix_domain.json')
        self.assertEqual([r['domain'] for r in priorities], ['large.org', 'small.org'])
        self.assertEqual(priorities[0]['dataset_url_count'], 2)
        self.assertEqual(priorities[0]['failed_urls_in_run'], 2)

    def test_partial_run_resumes_without_refetching_completed_ids(self):
        out = self.prepare(hosts=('example.org', 'other.org'))
        with patch.object(c.Fetcher, 'request_once', return_value=(200, {'Content-Type': 'text/html'}, BODY)) as request:
            first = runner.run(c, p, out, {'browser_mode': 'off'}, max_new=1)
            second = runner.run(c, p, out, {'browser_mode': 'off'}, max_new=1)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(first['pending'], 1)
        self.assertEqual(second['pending'], 0)

    def test_browser_setup_failure_preserves_http_results_and_can_resume(self):
        out = self.prepare()
        def unavailable(core, directory, samples, **options):
            core.write_json(directory / 'browser_setup_error.json', {'error': 'Chrome download failed'})
        with patch.object(c.Fetcher, 'request_once', return_value=(403, {}, b'<html>Forbidden</html>')), patch.object(p, 'crawl_browser', side_effect=unavailable):
            result = runner.run(c, p, out, {})
        self.assertEqual(result['failed'], 1)
        self.assertIn('Chrome download failed', (out / 'khong_vao_duoc.csv').read_text(encoding='utf-8-sig'))
        with patch.object(c.Fetcher, 'request_once', side_effect=AssertionError('Unexpected network')), patch.object(p, 'crawl_browser', side_effect=self.browser):
            result = runner.run(c, p, out, {})
        self.assertEqual(result['browser_recovered'], 1)


if __name__ == '__main__':
    unittest.main()
