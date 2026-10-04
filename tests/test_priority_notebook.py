"""Verify the notebook's exported access report, including browser recovery."""
import csv
import contextlib
import json
import io
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).parents[1]


class PriorityNotebookTests(unittest.TestCase):
    def test_report_counts_browser_recovery_and_orders_remaining_errors(self):
        nb = json.loads((ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        for i, cell in enumerate(nb['cells']):
            if cell['cell_type'] == 'code':
                compile(''.join(cell['source']), f'cell-{i}', 'exec')
        with tempfile.TemporaryDirectory() as tmp:
            ns = {'RUN_DIR': Path(tmp), 'DIRECT_PUBLIC_PROBE': True}
            with contextlib.redirect_stdout(io.StringIO()):
                exec(''.join(nb['cells'][3]['source']).split('OUTPUT_BASE =', 1)[0], ns)
                exec(''.join(nb['cells'][7]['source']), ns)
                exec(''.join(nb['cells'][9]['source']), ns)
            by_host = {s['domain']: s for s in ns['SAMPLES'] if s['sample_index'] == 0}
            self.assertEqual(len(ns['SAMPLES']), 97)
            self.assertEqual(set(by_host), set(ns['SOURCE_PROFILE']['host_counts']))
            core = ns['crawler']
            for host in ('www.cnkang.com', 'ask.39.net', 'zysjonline.com'):
                sample = by_host[host]
                failed = dict(sample, status='network_error', error='read timed out',
                              requests=[{'url': sample['url'], 'error': 'read timed out'}])
                if host == 'zysjonline.com':
                    failed.update(status='http_error', http_status=403, error_kind='http_403_challenge',
                                  challenge_detected=True, error='HTTP 403; security challenge page')
                core.write_json(Path(tmp) / 'records' / f"{sample['id']}.json", failed)
            recovered = by_host['www.cnkang.com']
            core.write_json(Path(tmp) / 'browser_records' / f"{recovered['id']}.json",
                            dict(recovered, status='rendered', http_status=200, char_count=500,
                                 quality_status='accepted', quality_flags=[]))
            rows, summary, archive = ns['save_outputs'](show=False)
            self.assertEqual(summary['vao_duoc'], 1)
            self.assertEqual(summary['requests_http_2xx'], 0)
            self.assertEqual(summary['browser_recovered'], 1)
            self.assertEqual(summary['khong_vao_duoc'], 2)
            self.assertEqual(summary['chua_chay'], len(ns['SAMPLES']) - 3)
            row = next(r for r in rows if r['sample_id'] == recovered['id'])
            self.assertEqual(row['effective_engine'], 'selenium')
            self.assertEqual(row['crawl_status'], 'network_error')
            self.assertEqual(row['error_detail'], 'read timed out')
            self.assertEqual(row['effective_quality_status'], 'accepted')
            with (Path(tmp) / 'khong_vao_duoc.csv').open(encoding='utf-8-sig', newline='') as stream:
                failures = list(csv.DictReader(stream))
            self.assertEqual([r['domain'] for r in failures], ['ask.39.net', 'zysjonline.com'])
            priorities = json.loads((Path(tmp) / 'uu_tien_fix_domain.json').read_text(encoding='utf-8'))
            self.assertEqual([r['domain'] for r in priorities], ['ask.39.net', 'zysjonline.com'])
            self.assertTrue(archive.exists())
            # save_outputs creates its ZIP beside the run directory.
            archive.unlink()

    def test_all_hosts_samples_keep_source_ids_urls_and_priority_baselines(self):
        import pyarrow.parquet as pq
        sample = json.loads((ROOT / 'data/domain_probe_all_hosts_samples.json').read_text(encoding='utf-8'))
        rows = sample['samples']
        self.assertEqual(len(rows), 97)
        self.assertEqual(len({r['id'] for r in rows}), 97)
        self.assertEqual(len({r['domain'] for r in rows}), 97)
        actual = pq.read_table(ROOT / 'data/links_corpus.parquet',
                              filters=[('id', 'in', [r['id'] for r in rows])]).to_pylist()
        self.assertEqual({r['id']: r['url'] for r in rows}, {r['id']: r['url'] for r in actual})
        expected = json.loads((ROOT / 'data/domain_probe_priority_samples.json').read_text(encoding='utf-8'))
        by_host = {r['domain']: r for r in rows}
        for r in expected['samples']:
            if r['sample_index'] == 0:
                self.assertEqual((r['id'], r['url']), (by_host[r['domain']]['id'], by_host[r['domain']]['url']))


if __name__ == '__main__':
    unittest.main()
