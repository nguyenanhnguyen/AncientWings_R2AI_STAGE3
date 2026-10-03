"""Check diagnostic bundles and timing across interrupted/resumed crawl runs."""
import csv
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


spec = importlib.util.spec_from_file_location(
    'diagnostics', Path(__file__).parents[1] / 'src/vibiomir/crawl/diagnostics.py',
)
diagnostics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostics)


class DiagnosticsTests(unittest.TestCase):
    def test_partial_run_errors_and_latest_invocation_timing(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-diagnostics-') as temporary:
            root = Path(temporary)
            run = root / 'run'
            (run / 'records').mkdir(parents=True)
            (run / 'logs').mkdir()
            sample = [{'id': i, 'url': f'https://example.org/{i}', 'domain': 'example.org'} for i in [10, 11, 12]]
            (run / 'sample.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in sample), encoding='utf-8')
            (run / 'manifest.json').write_text(json.dumps({'id_start_inclusive': 10, 'id_stop_exclusive': 13}), encoding='utf-8')
            record_a = {**sample[0], 'status': 'extracted', 'quality_status': 'accepted', 'quality_flags': [],
                        'raw_path': 'raw/missing.gz', 'text': 'FULL_TEXT_MUST_NOT_BE_IN_DIAGNOSTICS' * 100,
                        'requests': [{'url': sample[0]['url'], 'attempt': 1, 'http_status': 200}]}
            record_b = {**sample[1], 'status': 'network_error', 'quality_status': 'rejected',
                        'error': '<script>timeout</script>', 'requests': [{'url': sample[1]['url'], 'attempt': 3, 'error': 'timeout'}]}
            for record in [record_a, record_b, {'id': 99, 'url': 'https://example.org/99'}]:
                (run / 'records' / f"{record['id']}.json").write_text(json.dumps(record), encoding='utf-8')
            events = [
                {'event': 'start', 'operation': 'crawl', 'invocation_id': 'old', 'at': '2026-10-04T01:00:00+00:00'},
                {'event': 'end', 'operation': 'crawl', 'invocation_id': 'old', 'elapsed_seconds': 1000},
                {'event': 'start', 'operation': 'crawl', 'invocation_id': 'new', 'at': '2026-10-04T02:00:00+00:00'},
                {'event': 'end', 'operation': 'crawl', 'invocation_id': 'new', 'elapsed_seconds': 30},
                {'event': 'start', 'operation': 'report', 'invocation_id': 'report', 'at': '2026-10-04T03:00:00+00:00'},
            ]
            (run / 'logs' / 'invocations.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events), encoding='utf-8')
            progress = [
                {'invocation_id': 'old', 'completed_this_invocation': 1000, 'scheduled': 1000},
                {'invocation_id': 'new', 'completed_this_invocation': 1, 'scheduled': 2},
            ]
            (run / 'logs' / 'progress.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in progress), encoding='utf-8')
            before = {p.name: p.read_bytes() for p in (run / 'records').glob('*.json')}
            archive = root / 'diagnostics.zip'
            summary = diagnostics.build_archive(run, archive)
            self.assertEqual((summary['selected'], summary['completed'], summary['pending']), (3, 2, 1))
            self.assertEqual(summary['missing_raw_files'], 1)
            self.assertEqual(summary['flagged_documents'], 2)
            self.assertEqual(summary['timing']['invocation_id'], 'new')
            self.assertEqual(summary['timing']['seconds_per_url'], 30)
            self.assertEqual(summary['timing']['urls_per_minute'], 2)
            self.assertEqual(summary['timing']['eta_seconds'], 30)
            self.assertTrue(summary['read_warnings'])
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                html = bundle.read('overview.html').decode('utf-8')
                self.assertIn('&lt;script&gt;timeout&lt;/script&gt;', html)
                rows = list(csv.DictReader(io.StringIO(bundle.read('pending.csv').decode('utf-8-sig'))))
                self.assertEqual([row['id'] for row in rows], ['12'])
                for name in ('overview.html', 'records.csv', 'summary.json'):
                    self.assertNotIn(b'FULL_TEXT_MUST_NOT_BE_IN_DIAGNOSTICS', bundle.read(name))
                self.assertIn('samples/records/10.json', bundle.namelist())
                cases = json.loads(bundle.read('sample_manifest.json'))
                self.assertEqual(len(cases), 2)
                self.assertFalse(cases[0]['raw_included'])
                self.assertIn('environment.json', bundle.namelist())
            self.assertEqual(before, {p.name: p.read_bytes() for p in (run / 'records').glob('*.json')})

    def test_active_invocation_eta(self):
        with tempfile.TemporaryDirectory(prefix='vibiomir-diagnostics-') as temporary:
            run = Path(temporary)
            (run / 'logs').mkdir()
            (run / 'logs' / 'invocations.jsonl').write_text(json.dumps({
                'event': 'start', 'operation': 'crawl', 'invocation_id': 'active',
                'at': '2026-10-04T00:00:00+00:00',
            }) + '\n', encoding='utf-8')
            (run / 'logs' / 'progress.jsonl').write_text(json.dumps({
                'invocation_id': 'active', 'completed_this_invocation': 25, 'scheduled': 100,
            }) + '\n', encoding='utf-8')
            now = datetime(2026, 10, 4, 0, 1, 15, tzinfo=timezone.utc)
            timing = diagnostics.timing_summary(run, now, [])
            self.assertFalse(timing['finished'])
            self.assertEqual(timing['seconds_per_url'], 3)
            self.assertEqual(timing['eta_seconds'], 225)


if __name__ == '__main__':
    unittest.main()
