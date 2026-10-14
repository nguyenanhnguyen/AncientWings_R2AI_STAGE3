"""PubMed abstract fidelity, cookie gates, and canonical engine selection."""
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

from test_notebook_selenium_fallback import assignments, load_module


ROOT = Path(__file__).resolve().parents[1]
URL = 'https://pubmed.ncbi.nlm.nih.gov/28382722/'
TITLE = 'Postnatal growth and later clinical outcomes'
ABSTRACT = (
    '<p><strong>Background:</strong> Growth in term infants was assessed over time.</p>'
    '<p><strong>Results:</strong> The study included 125 infants; concentrations were '
    '3.5 mg m<sup>−3</sup> and the adjusted estimate was 1.25 (95% CI 1.01–1.54).</p>'
    '<ul><li>Neurocognitive outcomes improved in the first group.</li>'
    '<li>Metabolic outcomes differed in the second group.</li></ul>'
    '<p><strong>Conclusion:</strong> Follow-up measurements support further research.</p>'
)
COOKIE = b'<html><head><title>Cookies must be enabled</title></head><body>Please enable cookies.</body></html>'
COOKIE_HEADING = (
    b'<html><head><title>pubmed.ncbi.nlm.nih.gov</title></head><body>'
    b'<div id="cookie-required" hidden><h1 class="message">Cookies must be enabled</h1>'
    b'<p>Enable cookies and reload this page to continue.</p></div>'
    b'<footer>HHS Vulnerability Disclosure</footer></body></html>'
)


def article(abstract=ABSTRACT, pmid='28382722', extra_meta='', title_meta=True):
    return (
        '<html><head><meta charset="utf-8">'
        f'<meta name="citation_pmid" content="{pmid}">'
        + (f'<meta name="citation_title" content="{TITLE}">' if title_meta else '')
        + '<meta name="citation_doi" content="10.1000/pubmed-test">'
        '<meta name="citation_date" content="2020 Apr 01">'
        '<meta name="citation_authors" content="Author A; Author B">'
        f'{extra_meta}<title>{TITLE} - PubMed</title></head><body>'
        '<header>An official website of the United States government</header>'
        '<nav>Search history and navigation</nav>'
        f'<h1 class="heading-title">{TITLE}</h1><h1 class="heading-title">{TITLE}</h1>'
        f'<div id="eng-abstract">{abstract}</div>'
        '<section id="figures">Figures and captions unrelated to the abstract.</section>'
        '<section id="references">References and related publications.</section>'
        '</body></html>'
    ).encode('utf-8')


class PubMedParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        cls.root = Path(cls.temp.name)
        nb = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        pack = assignments(''.join(nb['cells'][6]['source']))
        for name, payload in pack['EMBEDDED_FILES'].items():
            body = zlib.decompress(base64.b85decode(payload))
            if hashlib.sha256(body).hexdigest() != pack['EMBEDDED_SHA256'][name]:
                raise AssertionError(f'Invalid embedded hash: {name}')
            (cls.root / name).write_bytes(body)
        nb = json.loads((ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        cls.domain_pack = assignments(''.join(nb['cells'][7]['source']))
        body = zlib.decompress(base64.b85decode(cls.domain_pack['CRAWLER_PAYLOAD']))
        if hashlib.sha256(body).hexdigest() != cls.domain_pack['CRAWLER_SHA256']:
            raise AssertionError('Invalid domain crawler hash')
        (cls.root / 'domain_crawler.py').write_bytes(body)
        cls.crawler = load_module('pubmed_test_crawler', cls.root / 'crawler_snapshot.py')
        cls.domain_crawler = load_module('pubmed_test_domain_crawler', cls.root / 'domain_crawler.py')
        cls.probe = load_module('pubmed_test_probe', cls.root / 'priority_probe_snapshot.py')
        cls.runner = load_module('pubmed_test_runner', cls.root / 'corpus_runner_snapshot.py')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.out = Path(self.case.name)
        self.sample = {'id': 6331460, 'url': URL, 'domain': 'pubmed.ncbi.nlm.nih.gov'}

    def test_both_notebooks_preserve_abstract_and_exclude_page_furniture(self):
        expected_abstract = (
            'Background: Growth in term infants was assessed over time.\n\n'
            'Results: The study included 125 infants; concentrations were 3.5 mg m−3 '
            'and the adjusted estimate was 1.25 (95% CI 1.01–1.54).\n\n'
            'Neurocognitive outcomes improved in the first group.\n\n'
            'Metabolic outcomes differed in the second group.\n\n'
            'Conclusion: Follow-up measurements support further research.'
        )
        for crawler in (self.crawler, self.domain_crawler):
            with self.subTest(crawler=crawler.__name__):
                doc = crawler.extract(article(), 'text/html; charset=UTF-8', URL)
                self.assertEqual(doc['extractor'], 'pubmed_abstract_dom_v1')
                self.assertEqual(doc['pubmed_pmid'], '28382722')
                self.assertTrue(doc['pubmed_pmid_verified'])
                self.assertEqual(doc['title'], TITLE)
                self.assertEqual(doc['text'].count(TITLE), 1)
                self.assertIn(expected_abstract, doc['text'])
                self.assertEqual(doc['source_abstract_chars'], len(expected_abstract))
                self.assertIn('PMID: 28382722', doc['text'])
                self.assertIn('DOI: 10.1000/pubmed-test', doc['text'])
                self.assertEqual(doc['author'], 'Author A; Author B')
                self.assertEqual(doc['published_at'], '2020 Apr 01')
                for junk in ('official website', 'Search history', 'Figures and captions', 'References and related'):
                    self.assertNotIn(junk, doc['text'])
                self.assertEqual(crawler.quality(doc)['quality_status'], 'accepted')

    def test_confirmed_short_abstract_keeps_link_and_is_accepted(self):
        abstract = ('<p><b>There was no association of transmission with temperature or UV radiation '
                    'in the cities examined.</b> <a href="https://example.org/study">Study details</a></p>')
        for crawler in (self.crawler, self.domain_crawler):
            doc = crawler.extract(article(abstract), 'text/html', URL)
            self.assertGreaterEqual(doc['source_abstract_chars'], 80)
            self.assertLess(len(doc['text']), 300)
            self.assertIn('Study details', doc['text'])
            self.assertEqual(crawler.quality(doc)['quality_status'], 'accepted')
            generic = dict(doc, extractor='trafilatura', pubmed_pmid_verified=False)
            self.assertIn('short_text', crawler.quality(generic)['quality_flags'])

    def test_tiny_abstract_cannot_be_padded_by_title_or_metadata(self):
        doc = self.crawler.extract(article('<p>Only a tiny source abstract.</p>'), 'text/html', URL)
        self.assertEqual(self.crawler.quality(doc)['quality_status'], 'review')
        self.assertIn('short_abstract', self.crawler.quality(doc)['quality_flags'])

    def test_h1_fallback_tolerates_identical_duplicate_headings(self):
        doc = self.crawler.extract(article(title_meta=False), 'text/html', URL)
        self.assertEqual(doc['title'], TITLE)
        self.assertEqual(self.crawler.quality(doc)['quality_status'], 'accepted')

    def test_unconfirmed_or_ambiguous_pages_require_review(self):
        cases = [
            (article(pmid='99999999'), URL),
            (article(extra_meta='<meta name="citation_pmid" content="99999999">'), URL),
            (article().replace(b'id="eng-abstract"', b'id="other-abstract"'), URL),
            (article(abstract=''), URL),
            (article(abstract=ABSTRACT + f'</div><div id="eng-abstract">{ABSTRACT}'), URL),
            (article(), 'https://pubmed.ncbi.nlm.nih.gov/?term=test'),
        ]
        for crawler in (self.crawler, self.domain_crawler):
            for body, url in cases:
                with self.subTest(crawler=crawler.__name__, url=url, body=body[:130]):
                    doc = crawler.extract(body, 'text/html', url)
                    self.assertTrue(doc['domain_parser_fallback'])
                    self.assertNotEqual(crawler.quality(doc)['quality_status'], 'accepted')

    def test_cookie_gate_is_rejected_and_scheduled_for_browser_even_with_2xx(self):
        self.assertTrue(self.probe.challenge_page({}, COOKIE))
        self.assertTrue(self.probe.challenge_page({}, COOKIE_HEADING))
        self.assertFalse(self.probe.challenge_page({}, article()))
        doc = self.crawler.extract(COOKIE, 'text/html', URL)
        self.assertEqual(self.crawler.quality(doc)['quality_status'], 'rejected')
        for status in (200, 203):
            with self.subTest(status=status), patch.object(
                    self.crawler.Fetcher, 'request_once', return_value=(status, {'Content-Type': 'text/html'}, COOKIE_HEADING)):
                fetcher = self.crawler.Fetcher(self.out, 0, 1)
                record = self.probe.request_record(self.crawler, fetcher, self.sample, self.out,
                                                   'TestCrawler', (1, 1), 10)
                self.assertEqual(record['status'], 'http_error')
                self.assertEqual(record['error_kind'], f'http_{status}_challenge')
                self.assertTrue(record['challenge_detected'])
                self.assertTrue(self.probe.needs_browser(record))
                self.assertNotEqual(self.probe.access_outcome(record)[0], 'VAO_DUOC')

    def test_old_cookie_checkpoint_never_beats_real_browser_content(self):
        old = dict(self.sample, status='extracted', http_status=203, title='Cookies must be enabled',
                   text='Please enable cookies.', quality_status='review', quality_flags=['short_text'])
        browser = dict(self.sample, status='rendered', http_status=200, title=TITLE,
                       text='Real article body. ' * 40, quality_status='review', quality_flags=['repeated_lines'])
        self.assertEqual(self.probe.access_outcome(old, browser)[1], 'selenium')
        self.assertNotEqual(self.probe.access_outcome(old)[0], 'VAO_DUOC')
        for change in ({'title': '', 'browser_title': 'Cookies must be enabled'},
                       {'title': TITLE, 'quality_flags': ['error_or_challenge']},
                       {'title': TITLE, 'challenge_detected': True}):
            gate = dict(browser, **change)
            self.assertNotEqual(self.probe.access_outcome(old, gate)[0], 'VAO_DUOC')

    def test_review_tie_prefers_full_text_but_equal_clean_content_keeps_requests(self):
        request = dict(self.sample, status='extracted', http_status=200, title=TITLE,
                       text='Short article.', quality_status='review', quality_flags=['short_text'])
        browser = dict(request, status='rendered', text='Article content. ' * 40,
                       quality_flags=['repeated_lines'])
        self.assertEqual(self.probe.access_outcome(request, browser)[1], 'selenium')
        request.update(quality_status='accepted', quality_flags=[])
        browser.update(quality_status='accepted', quality_flags=[])
        self.assertEqual(self.probe.access_outcome(request, browser)[1], 'requests')

    def test_cookie_fallback_publishes_clean_abstract_and_preserves_request_error(self):
        self.crawler.jsonl(self.out / 'sample.jsonl', [self.sample])
        self.crawler.write_json(self.out / 'manifest.json', {
            'sample_sha256': self.crawler.file_hash(self.out / 'sample.jsonl'), 'sampling': 'fixture'})
        self.crawler.write_json(self.out / 'source_profile.json', {
            'rows': 1, 'host_counts': {'pubmed.ncbi.nlm.nih.gov': 1},
            'sample_host_counts': {'pubmed.ncbi.nlm.nih.gov': 1}})

        def rendered(crawler, driver, sample, out, **options):
            body = article()
            raw_path = 'raw/selenium/article.gz'
            crawler.atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
            doc = crawler.extract(body, 'text/html', sample['url'])
            return dict(sample, **doc, **crawler.quality(doc), engine='selenium', status='rendered',
                        http_status=200, final_url=sample['url'], raw_path=raw_path,
                        raw_sha256=crawler.digest(body), elapsed_seconds=0)

        with patch.object(self.crawler.Fetcher, 'request_once',
                          return_value=(203, {'Content-Type': 'text/html'}, COOKIE)), \
                patch.object(self.probe, 'browser_preflight'), \
                patch.object(self.probe, 'create_browser'), \
                patch.object(self.probe, 'browser_attempt', side_effect=rendered), \
                redirect_stdout(io.StringIO()):
            summary = self.runner.run(self.crawler, self.probe, self.out,
                                      {'attempts': 1, 'delay': 0, 'pubmed_selenium_first': False,
                                       'pubmed_use_efetch': False}, workers=1)
        self.assertEqual(summary['browser_recovered'], 1)
        canonical = self.crawler.load_json(self.out / 'records/6331460.json')
        self.assertEqual(canonical['requests_error_kind'], 'http_203_challenge')
        self.assertEqual(canonical['quality_status'], 'accepted')
        self.assertEqual(canonical['extractor'], 'pubmed_abstract_dom_v1')
        accepted = [json.loads(line) for line in (self.out / 'corpus.accepted.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0]['id'], 6331460)
        self.assertIn('PMID: 28382722', accepted[0]['text'])

    def test_recovery_skips_legacy_cookie_gate_instead_of_reusing_it(self):
        source = self.out / 'old'
        target = self.out / 'new'
        source.mkdir()
        target.mkdir()
        self.crawler.write_json(source / 'manifest.json', {'selected': 1})
        self.crawler.atomic_bytes(source / 'raw/cookie.gz', gzip.compress(COOKIE, mtime=0))
        self.crawler.write_json(source / 'records/6331460.json', dict(
            self.sample, status='extracted', http_status=203, content_type='text/html',
            final_url=URL, raw_path='raw/cookie.gz', raw_sha256=self.crawler.digest(COOKIE)))
        with patch.object(self.crawler.Fetcher, 'request_once') as request:
            recovery = self.probe.seed_successful_requests(self.crawler, target, [self.sample], source)
        request.assert_not_called()
        self.assertEqual(recovery['reused_ids'], [])
        self.assertFalse((target / 'records/6331460.json').exists())

    def test_domain_and_corpus_use_identical_probe(self):
        probe = zlib.decompress(base64.b85decode(self.domain_pack['PRIORITY_PAYLOAD']))
        self.assertEqual(probe, (self.root / 'priority_probe_snapshot.py').read_bytes())
        self.assertEqual(hashlib.sha256(probe).hexdigest(), self.domain_pack['PRIORITY_SHA256'])


if __name__ == '__main__':
    unittest.main()
