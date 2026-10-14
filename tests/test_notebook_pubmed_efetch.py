"""Exercise production EFetch routing, durable resume, XML fidelity and audit/export."""
from contextlib import redirect_stdout
import csv
import gzip
import io
import json
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import Mock, patch

import pyarrow as pa
import pyarrow.parquet as pq

import test_notebook_pubmed_parser as fixtures
from test_notebook_selenium_fallback import load_module, assignments


ABSTRACT = ('A prospective clinical study evaluated patient outcomes and treatment response. '
            'All numbers and source text should be retained in full. ') * 4


def article(pmid, *, title=None, body=None, extra=''):
    title = title if title is not None else f'Clinical study {pmid}'
    body = body if body is not None else f'<AbstractText Label="RESULTS" NlmCategory="RESULTS">{ABSTRACT}</AbstractText>'
    return (f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>'
            f'<ArticleTitle>{title}</ArticleTitle><Abstract>{body}</Abstract></Article>'
            f'{extra}</MedlineCitation></PubmedArticle>')


def xml(items):
    return ('<PubmedArticleSet>' + ''.join(items) + '</PubmedArticleSet>').encode('utf-8')


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code = payload, status
        self.headers = headers or {'Content-Type': 'application/xml'}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def iter_content(self, size):
        yield self.payload


class PubMedEFetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PubMedParserTests.setUpClass.__func__(cls)
        cls.api = load_module('efetch_test_api', cls.root / 'pubmed_efetch_snapshot.py')
        cls.audit = load_module('efetch_test_audit', cls.root / 'audit_snapshot.py')
        cls.exporter = load_module('efetch_test_exporter', cls.root / 'export_snapshot.py')

    @classmethod
    def tearDownClass(cls):
        fixtures.PubMedParserTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixtures.PubMedParserTests.setUp(self)
        self.api_calls, self.events = [], []
        self.session = Mock()
        self.session.headers = {}
        self.session.get.side_effect = self.get
        self.reply = None

    def make_run(self, count=2, mixed=False):
        samples = [{'id': i + 10, 'url': f'https://pubmed.ncbi.nlm.nih.gov/{28000000+i}/',
                    'domain': 'pubmed.ncbi.nlm.nih.gov'} for i in range(count)]
        if mixed:
            samples.append({'id': 1, 'url': 'https://vov.vn/article', 'domain': 'vov.vn'})
            samples.reverse()
        samples.sort(key=lambda r: r['id'])
        self.samples = samples
        self.crawler.jsonl(self.out / 'sample.jsonl', samples)
        source = self.out / 'source.parquet'
        pq.write_table(pa.Table.from_pylist([{k: r[k] for k in ('id', 'url')} for r in samples]), source)
        self.crawler.write_json(self.out / 'manifest.json', {
            'source': str(source), 'source_sha256': self.crawler.file_hash(source), 'selected': len(samples),
            'sample_sha256': self.crawler.file_hash(self.out / 'sample.jsonl'), 'sampling': 'fixture'})
        counts = {domain: sum(s['domain'] == domain for s in samples) for domain in {s['domain'] for s in samples}}
        self.crawler.write_json(self.out / 'source_profile.json', {
            'rows': len(samples), 'host_counts': counts, 'sample_host_counts': counts})
        return samples

    def get(self, endpoint, **kwargs):
        self.events.append(('efetch', endpoint))
        self.api_calls.append(kwargs)
        if callable(self.reply): return self.reply(endpoint, **kwargs)
        if self.reply is not None: return self.reply
        pmids = kwargs['params']['id'].split(',')
        return Response(xml([article(pmid) for pmid in reversed(pmids)]))

    def page(self, url, *args, **kwargs):
        self.events.append(('requests', url))
        self.assertNotIn('pubmed.ncbi.nlm.nih.gov', url)
        payload = ('<html><head><title>Public health research</title></head><body><article><h1>Public health research</h1>'
                   f'<p>{ABSTRACT * 5}</p></article></body></html>').encode()
        return 200, {'Content-Type': 'text/html'}, payload

    def execute(self, config=None, max_new=None):
        with patch('requests.Session', return_value=self.session), \
                patch.object(self.crawler.Fetcher, 'request_once', side_effect=self.page) as page, \
                patch.object(self.probe, 'browser_preflight') as preflight, \
                patch.object(self.probe, 'crawl_browser') as browser, redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out,
                                      {'attempts': 1, 'delay': 0, 'pubmed_efetch': {'attempts': 1}, **(config or {})},
                                      workers=4, max_new=max_new)
        return summary, page, preflight, browser

    def rows(self):
        return [self.crawler.load_json(self.out / 'records' / f"{s['id']}.json") for s in self.samples]

    def test_default_all_pubmed_uses_one_get_no_chrome_even_browser_off(self):
        self.make_run(100)
        summary, page, preflight, browser = self.execute({'browser_mode': 'off'})
        self.assertEqual(len(self.api_calls), 1)
        page.assert_not_called()
        preflight.assert_not_called()
        browser.assert_not_called()
        self.assertEqual(summary['pubmed_efetch'], 100)
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['accepted'], 100)
        self.assertEqual(len(self.api_calls[0]['params']['id'].split(',')), 100)
        self.assertFalse(self.api_calls[0]['allow_redirects'])
        self.assertEqual(self.api_calls[0]['params']['retmode'], 'xml')
        for sample, record in zip(self.samples, self.rows()):
            pmid = sample['url'].rstrip('/').rsplit('/', 1)[-1]
            self.assertEqual((record['id'], record['url'], record['pubmed_pmid']), (sample['id'], sample['url'], pmid))
            self.assertEqual(record['title'], f'Clinical study {pmid}')
            self.assertTrue(record['text'].endswith(ABSTRACT.strip()))
            self.assertEqual(record['engine'], 'efetch')

    def test_mixed_run_keeps_other_domain_http_and_api_before_it(self):
        self.make_run(2, mixed=True)
        summary, page, preflight, browser = self.execute()
        self.assertEqual(self.events, [('efetch', self.api.ENDPOINT), ('requests', 'https://vov.vn/article')])
        self.assertEqual(page.call_count, 1)
        browser.assert_not_called()
        self.assertEqual(summary['accessible'], 3)

    def test_max_new_counts_corpus_urls_and_batches_100_then_one(self):
        self.make_run(105)
        summary, _, _, _ = self.execute(max_new=101)
        self.assertEqual([len(c['params']['id'].split(',')) for c in self.api_calls], [100, 1])
        self.assertEqual(summary['pending'], 4)
        saved = (self.out / 'pubmed_records/10.json').read_bytes()
        self.api_calls.clear()
        summary, _, _, _ = self.execute(max_new=4)
        self.assertEqual(len(self.api_calls[0]['params']['id'].split(',')), 4)
        self.assertEqual(summary['pending'], 0)
        self.assertEqual((self.out / 'pubmed_records/10.json').read_bytes(), saved)

    def test_duplicate_corpus_pmid_preserves_both_ids(self):
        samples = self.make_run(2)
        samples[1]['url'] = samples[0]['url']
        self.crawler.jsonl(self.out / 'sample.jsonl', samples)
        manifest = self.crawler.load_json(self.out / 'manifest.json')
        manifest['sample_sha256'] = self.crawler.file_hash(self.out / 'sample.jsonl')
        self.crawler.write_json(self.out / 'manifest.json', manifest)
        summary, _, _, _ = self.execute()
        self.assertEqual(self.api_calls[0]['params']['id'], '28000000')
        self.assertEqual(summary['completed'], 2)
        self.assertEqual([r['id'] for r in self.rows()], [10, 11])

    def test_missing_and_no_abstract_retained_separately_and_audited(self):
        self.make_run(3)
        self.reply = Response(xml([article('28000000'), article('28000001', body='')]))
        summary, _, _, browser = self.execute()
        browser.assert_not_called()
        self.assertEqual(summary['completed'], 3)
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['accepted'], 1)
        self.assertEqual([r['pubmed_api_status'] for r in self.rows()], ['accepted', 'no_abstract', 'missing_pmid'])
        for name, pmid in [('pubmed_missing_pmids.csv', '28000002'), ('pubmed_no_abstract.csv', '28000001')]:
            with (self.out / name).open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual([r['pubmed_pmid'] for r in csv.DictReader(stream)], [pmid])
        self.run_audit()
        self.assertEqual(self.crawler.load_json(self.out / 'audit_summary.json')['pubmed_xml_records_verified'], 2)

    def test_interrupted_per_id_fanout_replays_batch_without_get(self):
        self.make_run(4)
        original = self.crawler.write_json
        interrupted = False
        def write(path, data):
            nonlocal interrupted
            if Path(path).parent.name == 'pubmed_records' and Path(path).stem == '11' and not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return original(path, data)
        with patch.object(self.crawler, 'write_json', side_effect=write):
            with self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual(len(self.api_calls), 1)
        self.assertTrue(list((self.out / 'pubmed_batches').glob('*.json')))
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['pending'], 3)
        self.api_calls.clear()
        summary, _, _, _ = self.execute()
        self.assertEqual(len(self.api_calls), 0)
        self.assertEqual(summary['completed'], 4)

    def test_network_failure_keeps_pending_and_resume_retries(self):
        self.make_run(3)
        self.reply = Response(b'Access denied', status=403)
        with self.assertRaisesRegex(RuntimeError, 'URLs remain pending'): self.execute()
        self.assertEqual(list((self.out / 'records').glob('*.json')), [])
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['pending'], 3)
        self.assertTrue(list((self.out / 'pubmed_batch_failures').glob('*.json')))
        with (self.out / 'pubmed_review.csv').open(encoding='utf-8-sig', newline='') as stream:
            review = list(csv.DictReader(stream))
        self.assertEqual(len(review), 3)
        self.assertTrue(all(r['http_status'] == '403' and (self.out / r['raw_path']).is_file() for r in review))
        self.reply = None
        summary, _, _, _ = self.execute()
        self.assertEqual(summary['completed'], 3)
        self.assertEqual(len(self.api_calls), 2)

    def test_interrupt_in_request_has_no_fake_completed_rows(self):
        self.make_run(3)
        self.session.get.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['pending'], 3)
        self.assertEqual(list((self.out / 'records').glob('*.json')), [])

    def test_html_http_200_stays_pending_and_has_saved_raw_evidence(self):
        self.make_run(2)
        self.reply = Response(b'<html><title>Access denied</title></html>')
        with self.assertRaisesRegex(RuntimeError, 'URLs remain pending'): self.execute()
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['pending'], 2)
        self.assertEqual(list((self.out / 'pubmed_records').glob('*.json')), [])
        request = json.loads((self.out / 'pubmed_requests.jsonl').read_text(encoding='utf-8'))
        self.assertEqual(request['http_status'], 200)
        self.assertIn('XML root', request['error'])
        self.assertTrue((self.out / request['raw_path']).is_file())

    def test_config_cannot_raise_get_batch_size_workers_or_request_rate(self):
        for cfg in [{'batch_size': 101}, {'workers': 2}, {'gap_seconds': .49}, {'gap_seconds': float('nan')}]:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError): self.api.validate_config(cfg)

    def test_labels_inline_other_abstract_and_export_roundtrip(self):
        self.make_run(1)
        body = ('<AbstractText Label="BACKGROUND">Water H<sub>2</sub>O and <i>DNA</i> molecules. '
                + ABSTRACT + '</AbstractText><AbstractText NlmCategory="METHODS"><p>Paragraph 1.</p><p>Paragraph 2.</p></AbstractText>'
                '<AbstractText Label="RESULTS">Numbers 1.5 &amp; 2.7.</AbstractText>')
        other = '<OtherAbstract Type="Publisher" Language="fre"><AbstractText Label="CONCLUSION">Résultat final.</AbstractText></OtherAbstract>'
        self.reply = Response(xml([article('28000000', title='Study of H<sub>2</sub>O', body=body, extra=other)]))
        self.execute()
        row = self.rows()[0]
        self.assertIn('BACKGROUND: Water H2O and DNA', row['text'])
        self.assertIn('METHODS: Paragraph 1.\n\nParagraph 2.', row['text'])
        self.assertIn('RESULTS: Numbers 1.5 & 2.7.', row['text'])
        self.assertTrue(row['text'].endswith('CONCLUSION: Résultat final.'))
        self.run_audit()
        with patch.object(sys, 'argv', ['export', '--out', str(self.out)]), redirect_stdout(io.StringIO()):
            self.exporter.main()
        exported = pq.read_table(self.out / 'corpus.parquet').to_pylist()
        self.assertEqual(exported[0]['text'], row['text'])
        self.assertTrue(self.crawler.load_json(self.out / 'export_manifest.json')['accepted_source_ids_preserved'])

    def run_audit(self):
        with patch.object(sys, 'argv', ['audit', '--out', str(self.out)]), redirect_stdout(io.StringIO()):
            self.audit.main()

    def test_audit_rejects_truncation_even_with_recomputed_text_hash(self):
        self.make_run(1)
        self.execute()
        row = self.rows()[0]
        row['text'] = row['title'] + '\n\n' + row['abstract_sections'][0]['text'][:100]
        row['text_sha256'] = self.crawler.digest(row['text'].encode())
        self.crawler.write_json(self.out / 'records/10.json', row)
        with self.assertRaisesRegex(ValueError, 'PubMed abstract text/XML mismatch'): self.run_audit()

    def test_changed_route_requires_new_run_before_any_network(self):
        self.make_run(1)
        self.execute()
        self.api_calls.clear()
        with self.assertRaisesRegex(ValueError, 'code/config changed'): self.execute({'pubmed_use_efetch': False})
        self.assertFalse(self.api_calls)

    def test_recovery_reuses_xml_for_matching_ids_without_api(self):
        self.make_run(2)
        self.execute()
        previous = self.out
        self.out = previous / 'new_run'
        self.out.mkdir()
        self.make_run(2)
        self.api_calls.clear()
        with patch('requests.Session', return_value=self.session), redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out, {}, recovery_source=previous)
        self.assertFalse(self.api_calls)
        self.assertEqual(summary['completed'], 2)
        self.run_audit()

    def test_pacing_and_retry_after_persist_between_clients(self):
        samples = self.make_run(1)
        timer = {'now': 1000.}
        starts = []
        replies = iter([Response(b'Rate limited', 429, {'Retry-After': '3'}), Response(xml([article('28000000')])),
                        Response(xml([article('28000000')]))])
        def get(*args, **kwargs):
            starts.append(timer['now'])
            timer['now'] += .2
            return next(replies)
        self.session.get.side_effect = get
        cfg = self.api.validate_config({})
        with patch.object(time, 'time', side_effect=lambda: timer['now']), \
                patch.object(time, 'monotonic', side_effect=lambda: timer['now']), \
                patch.object(time, 'sleep', side_effect=lambda duration: timer.update(now=timer['now'] + duration)), \
                redirect_stdout(io.StringIO()):
            client = self.api.EFetchClient(self.crawler, self.out, cfg, self.session)
            client.fetch(samples)
            client.close()
            client = self.api.EFetchClient(self.crawler, self.out, cfg, self.session)
            client.fetch(samples)
        self.assertGreaterEqual(starts[1] - starts[0] - .2, 3.)
        self.assertGreaterEqual(starts[2] - starts[1] - .2 + 1e-9, .5)

    def test_secret_values_do_not_enter_settings_records_or_logs(self):
        self.make_run(1)
        with patch.dict('os.environ', {'NCBI_API_KEY': 'private+key', 'NCBI_EMAIL': 'person@example.com'}):
            self.execute()
        for path in self.out.rglob('*.json*'):
            data = path.read_text(encoding='utf-8')
            self.assertNotIn('private+key', data, str(path))
            self.assertNotIn('person@example.com', data, str(path))

    def test_notebook_default_efetch_configuration_and_embedded_source_match(self):
        nb = json.loads((fixtures.ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        config = assignments(''.join(nb['cells'][2]['source']))
        self.assertTrue(config['PUBMED_USE_EFETCH'])
        self.assertEqual(config['PUBMED_EFETCH_BATCH_SIZE'], 100)
        self.assertEqual(config['PUBMED_EFETCH_WORKERS'], 1)
        self.assertGreaterEqual(config['PUBMED_EFETCH_GAP_SECONDS'], .5)
        self.assertEqual(Path(self.api.__file__).read_bytes(), (fixtures.ROOT / 'scripts/pubmed_efetch.py').read_bytes())

    def test_duplicate_response_and_wrong_pmid_cannot_enter_corpus(self):
        self.make_run(2)
        self.reply = Response(xml([article('28000000'), article('28000000'), article('99999999')]))
        self.execute()
        self.assertEqual(self.crawler.load_json(self.out / 'quality_report.json')['accepted'], 0)
        self.assertEqual([r['pubmed_api_status'] for r in self.rows()], ['duplicate_api_pmid', 'missing_pmid'])
        self.run_audit()
        anomalies = [json.loads(line) for line in (self.out / 'pubmed_api_anomalies.jsonl').read_text().splitlines()]
        self.assertEqual({a['kind'] for a in anomalies}, {'duplicate_api_pmid', 'unexpected_pmid'})


if __name__ == '__main__':
    unittest.main()
