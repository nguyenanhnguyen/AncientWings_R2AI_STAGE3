"""All-host samples retain source IDs, unique URLs, shortages and resume provenance."""
import ast
import base64
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

import pyarrow as pa
import pyarrow.parquet as pq

from test_notebook_selenium_fallback import assignments, load_module

ROOT = Path(__file__).resolve().parents[1]


class DomainInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.nb = json.loads((ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        self.pack = assignments(''.join(self.nb['cells'][7]['source']))

    def test_all_94_hosts_have_unique_fresh_source_urls_and_honest_quotas(self):
        samples, profile = self.pack['SAMPLES'], self.pack['SOURCE_PROFILE']
        self.assertEqual(len(samples), 1764)
        self.assertEqual(len({r['domain'] for r in samples}), 94)
        self.assertEqual(len({r['id'] for r in samples}), len(samples))
        self.assertEqual(len({r['url'] for r in samples}), len(samples))
        self.assertFalse({r['id'] for r in samples} & set(self.pack['EXCLUDED_SAMPLE_IDS']))
        self.assertFalse({r['url'] for r in samples} & set(self.pack['EXCLUDED_SAMPLE_URLS']))
        counts = Counter(r['domain'] for r in samples)
        for host, count in counts.items():
            self.assertEqual(count, min(20, profile['available_host_counts'][host]))
        self.assertEqual(sum(count < 20 for count in counts.values()), 7)
        actual = pq.read_table(ROOT / 'data/links_corpus_vi_en_zh.parquet', columns=['id', 'url'],
                               filters=[('id', 'in', [r['id'] for r in samples])]).to_pylist()
        self.assertEqual({r['id']: r['url'] for r in actual}, {r['id']: r['url'] for r in samples})

    def execute_setup(self, target=None):
        config = ''.join(self.nb['cells'][3]['source'])
        if target is not None:
            config = config.replace('TARGET_DOMAINS = None', f'TARGET_DOMAINS = {target!r}')
        lines = config.splitlines(keepends=True)
        node = next(n for n in ast.parse(config).body if isinstance(n, ast.Assign)
                    and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'RUN_DIR')
        lines[node.lineno - 1:node.end_lineno] = [f'RUN_DIR = Path({str(self.out)!r})\n']
        env = {'__name__': '__main__'}
        with redirect_stdout(io.StringIO()):
            exec(compile(''.join(lines), '<domain-config>', 'exec'), env)
            exec(compile(''.join(self.nb['cells'][7]['source']), '<domain-setup>', 'exec'), env)
        return env

    def test_standalone_setup_selects_all_hosts_and_embeds_exact_helper(self):
        env = self.execute_setup()
        self.assertEqual(len(env['SAMPLES']), 1764)
        self.assertEqual(len(env['NETWORK_CHECK_DOMAINS']), 94)
        expected = (ROOT / 'scripts/domain_ip_diagnostics.py').read_bytes()
        self.assertEqual(zlib.decompress(base64.b85decode(self.pack['IP_DIAGNOSTICS_PAYLOAD'])), expected)
        self.assertEqual(hashlib.sha256(expected).hexdigest(), self.pack['IP_DIAGNOSTICS_SHA256'])
        self.assertEqual((self.out / 'ip_diagnostics_snapshot.py').read_bytes(), expected)

    def test_runtime_subset_and_resume_keep_identical_sample_hash(self):
        env = self.execute_setup(('vov.vn', 'pubmed.ncbi.nlm.nih.gov'))
        self.assertEqual(len(env['SAMPLES']), 40)
        sample_file = [json.loads(line) for line in (self.out / 'sample.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(sample_file, env['SAMPLES'])
        saved = (self.out / 'manifest.json').read_bytes()
        second = self.execute_setup(('vov.vn', 'pubmed.ncbi.nlm.nih.gov'))
        self.assertEqual(env['SAMPLES'], second['SAMPLES'])
        self.assertEqual((self.out / 'manifest.json').read_bytes(), saved)
        with self.assertRaisesRegex(ValueError, 'khớp mẫu'):
            self.execute_setup(('vov.vn',))

    def test_reports_can_be_generated_before_network_for_all_hosts(self):
        env = self.execute_setup()
        with redirect_stdout(io.StringIO()):
            exec(compile(''.join(self.nb['cells'][9]['source']), '<domain-reports>', 'exec'), env)
        report = json.loads((self.out / 'ip_block_report.json').read_text(encoding='utf-8'))
        self.assertEqual(report['hostnames'], 94)
        self.assertEqual(report['verdict_counts'], {'NOT_TESTED': 94})
        self.assertEqual(env['summary']['chua_chay'], 1764)
        self.assertTrue(env['zip_path'].is_file())

    def test_cnkang_route_merges_pages_without_generic_requests_or_browser(self):
        from test_cnkang_pagination import synthetic, reply
        from urllib.parse import urlsplit
        env = self.execute_setup(('www.cnkang.com',))
        env.update(IP_CHECK_ENABLED=False, MAX_NEW=1, BROWSER_TEST_MODE='off')
        with redirect_stdout(io.StringIO()):
            exec(compile(''.join(self.nb['cells'][9]['source']), '<domain-reports>', 'exec'), env)
        runtime = env['CNKANG_TRANSPORT']
        sample = env['SAMPLES'][0]
        basename = urlsplit(sample['url']).path.rsplit('/', 1)[-1].removesuffix('.html')
        self.assertTrue(basename.isdigit())
        def response(url, *args, **kwargs):
            raw = (b'User-agent: *\nAllow: /\n' if url.endswith('/robots.txt') else
                   synthetic(2) if '_2.html' in url else synthetic(next_href='123_2.html'))
            result = reply(raw.replace(b'123', basename.encode()))
            result.network = {'worker_pid': 123, 'elapsed_seconds': 0.001}
            return result
        with patch.object(runtime.Transport, 'wait'), \
                patch.object(runtime.NETWORK.NetworkWorker, 'get', side_effect=response), \
                patch.object(env['priority_probe'], 'crawl_requests') as generic, \
                patch.object(env['priority_probe'], 'browser_preflight') as browser, \
                redirect_stdout(io.StringIO()):
            exec(compile(''.join(self.nb['cells'][11]['source']), '<domain-crawl>', 'exec'), env)
        generic.assert_not_called()
        browser.assert_not_called()
        records = list((self.out/'records').glob('*.json'))
        self.assertEqual(len(records), 1)
        record = json.loads(records[0].read_text(encoding='utf-8'))
        self.assertTrue(record['article_complete'])
        self.assertEqual(record['article_page_count'], 2)
        self.assertTrue(runtime.audit_saved(self.out, record)['cnkang_article_verified'])

    def test_sampler_excludes_old_urls_deduplicates_and_is_reproducible(self):
        builder = load_module('domain_sample_builder_test', ROOT / 'scripts/build_domain_samples_notebook.py')
        rows = [{'id': i, 'url': f'https://example.org/{i}'} for i in range(1, 31)]
        rows += [{'id': 31, 'url': 'https://example.org/1'}, {'id': 32, 'url': 'https://tiny.example.net/a'}]
        source = self.out / 'source.parquet'
        pq.write_table(pa.Table.from_pylist(rows), source)
        samples, profile = builder.select_samples(source, {2}, {'https://example.org/1'}, seed=42)
        repeated, _ = builder.select_samples(source, {2}, {'https://example.org/1'}, seed=42)
        self.assertEqual(samples, repeated)
        self.assertEqual(profile['available_host_counts']['example.org'], 28)
        self.assertEqual(profile['sample_host_counts'], {'example.org': 20, 'tiny.example.net': 1})
        self.assertFalse({r['id'] for r in samples} & {1, 2, 31})


if __name__ == '__main__':
    unittest.main()
