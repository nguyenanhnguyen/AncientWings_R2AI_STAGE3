"""Real HTML regressions plus offline tests for retries, raw recovery and interruption."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timezone
from email.utils import format_datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lxml import html
import pyarrow as pa
import pyarrow.parquet as pq

import test_notebook_pubmed_parser as fixtures
from test_notebook_selenium_fallback import assignments, load_module

ROOT = fixtures.ROOT
FIXTURES = ROOT / 'tests/fixtures/longchau'
URL = 'https://nhathuoclongchau.com.vn/bai-viet/clinical-test.html'
PROSE = ('Không được tự ý dùng thuốc. Ngày 14/10/2026, dược sĩ khuyến cáo liều 5 mg/kg; '
         'trẻ có dấu hiệu nặng cần đến cơ sở y tế ngay. ')


def article(content=None, slug=None, extra=''):
    content = content or '<h2>Cảnh báo y khoa</h2><p>' + PROSE * 5 + '</p>'
    data = {'id': 901, 'slug': slug or URL.split('.vn/')[1], 'name': 'Bài kiểm tra lâm sàng',
            'shortDescription': 'Sapo cần được giữ đầy đủ cùng toàn bộ nội dung bài viết.',
            'description': content, 'author': {'fullName': 'Nguyễn An'},
            'approver': {'fullName': 'Trần Bình'}, 'publishedAt': '2026-10-14T00:00:00Z',
            'updatedAt': '2026-10-14T01:00:00Z'}
    payload = json.dumps({'props': {'pageProps': {'detail': {'data': data}}}}, ensure_ascii=False)
    return (f'<html><head><meta charset="utf-8"><link rel="canonical" href="{URL}">'
            f'<script id="__NEXT_DATA__" type="application/json">{payload}</script></head><body>'
            '<nav>Menu và hotline không thuộc bài</nav><h1>Bài kiểm tra lâm sàng</h1>'
            f'<div data-theme-element="article" data-scale-font="true">{content}</div>{extra}'
            '<aside class="author-profile">Tiểu sử dược sĩ không thuộc bài</aside></body></html>').encode()


class FakeClock:
    def __init__(self): self.elapsed, self.epoch = 0., 1800000000.
    def monotonic(self): return self.elapsed
    def time(self): return self.epoch + self.elapsed
    def sleep(self, seconds): self.elapsed += max(0., seconds)


class FakeSession:
    def __init__(self, responses, clock):
        self.responses, self.clock = list(responses), clock
        self.calls, self.headers, self.closed = [], {}, False
    def get(self, url, **options):
        self.calls.append((url, options, self.clock.elapsed))
        self.clock.elapsed += .1
        result = self.responses.pop(0)
        if isinstance(result, BaseException): raise result
        status, headers, body = result
        options['content_callback'](body)
        return SimpleNamespace(status_code=status, headers=headers)
    def close(self): self.closed = True


class LongChauTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PubMedParserTests.setUpClass.__func__(cls)
        cls.lc = cls.crawler.longchau_module()
        cls.audit = load_module('longchau_test_audit', cls.root / 'audit_snapshot.py')
        cls.smoke = load_module('longchau_test_smoke', ROOT / 'scripts/check_longchau.py')
        cls.manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
    @classmethod
    def tearDownClass(cls): fixtures.PubMedParserTests.tearDownClass.__func__(cls)
    def setUp(self):
        fixtures.PubMedParserTests.setUp(self)
        self.sample = {'id': 777, 'url': URL, 'domain': 'nhathuoclongchau.com.vn'}
    def fixture(self, name):
        row = next(r for r in self.manifest if r['name'] == name)
        body = gzip.decompress((FIXTURES / row['file']).read_bytes())
        self.assertEqual(hashlib.sha256(body).hexdigest(), row['sha256'])
        return row, body
    def transport(self, responses, config=None):
        from curl_cffi import requests as curl_requests
        clock = FakeClock()
        session = FakeSession(responses, clock)
        stack = ExitStack()
        self.session_constructor = stack.enter_context(patch.object(curl_requests, 'Session', return_value=session))
        stack.enter_context(patch.object(self.crawler.Fetcher, 'validate'))
        for name in ('monotonic', 'time', 'sleep'):
            stack.enter_context(patch.object(self.lc.time, name, getattr(clock, name)))
        stack.enter_context(redirect_stdout(io.StringIO()))
        self.addCleanup(stack.close)
        return session, clock, self.lc.validate_config(config or {})
    def request(self, responses, config=None, respect_robots=False):
        session, clock, config = self.transport(responses, config)
        fetcher = self.lc.make_fetcher(self.crawler, self.out, config)
        self.addCleanup(fetcher.close)
        record = self.probe.request_record(self.crawler, fetcher, self.sample, self.out, 'TestCrawler',
            config['timeout'], config['budget'], respect_robots=respect_robots)
        return record, session, clock, fetcher
    def make_run(self, samples):
        self.crawler.jsonl(self.out / 'sample.jsonl', samples)
        self.crawler.write_json(self.out / 'manifest.json', {'selected': len(samples), 'sampling': 'fixture',
            'sample_sha256': self.crawler.file_hash(self.out / 'sample.jsonl')})
        self.crawler.write_json(self.out / 'source_profile.json', {'rows': len(samples),
            'host_counts': {'nhathuoclongchau.com.vn': len(samples)},
            'sample_host_counts': {'nhathuoclongchau.com.vn': len(samples)}})

    def test_three_real_article_fixtures_keep_intro_end_and_all_medical_blocks(self):
        expectations = {
            'dyslexia': ('Dyslexia là gì? Triệu chứng và nguyên nhân gây ra tình trạng này', 6,
                        'giảm thiểu những hậu quả tiêu cực của chứng khó đọc.'),
            'sot_xuat_huyet': ('Cách sơ cứu sốt xuất huyết hiệu quả, an toàn', 7,
                             'hy vọng bạn sẽ tiếp tục đồng hành cùng Nhà Thuốc Long Châu trong thời gian tới!'),
            'thieu_mau_cap': ('Thiếu máu cấp là gì? Nguyên nhân nào gây ra thiếu máu cấp?', 11,
                             'kiểm soát và điều trị thiếu máu cấp hiệu quả.'),
        }
        squash = lambda s: re.sub(r'\s+', '', s)
        for name, (title, headings, ending) in expectations.items():
            with self.subTest(name=name):
                row, body = self.fixture(name)
                doc = self.crawler.extract(body, 'text/html', row['url'])
                self.assertEqual(doc['title'], title)
                self.assertEqual(doc['text'].count(title), 1)
                self.assertIn(doc['longchau_sapo'], doc['text'])
                self.assertTrue(doc['text'].endswith(ending))
                self.assertEqual(doc['source_heading_count'], headings)
                self.assertEqual(doc['missing_blocks'], 0)
                self.assertEqual(doc['longchau_review_reasons'], [])
                self.assertEqual(self.crawler.quality(doc)['quality_status'], 'accepted')
                tree = html.fromstring(body.decode())
                raw_region = tree.xpath('//*[@data-theme-element="article" and @data-scale-font]')[0]
                removed = [squash(r['text']) for r in doc['longchau_removed_blocks']]
                # Independent text_content view of every medical p/list item/heading in raw DOM.
                medical_blocks = 0
                for node in raw_region.xpath('.//p|.//li|.//h2|.//h3|.//h4|.//tr|.//figcaption'):
                    text = squash(node.text_content())
                    if not text or any(text in junk for junk in removed): continue
                    self.assertIn(text, squash(doc['text']))
                    medical_blocks += 1
                self.assertGreater(medical_blocks, 20)
                for junk in ('Mặc định', 'Lớn hơn', 'Nguồn tham khảo: Tổng hợp',
                             'Thông tin và sản phẩm gợi ý trong bài viết chỉ mang tính chất tham khảo'):
                    self.assertNotIn(junk, doc['text'])
                self.assertTrue(doc['published_at'])
                self.assertTrue(doc['reviewed_by'])
                if name != 'thieu_mau_cap': self.assertTrue(doc['author'])
                else: self.assertIsNone(doc['author'], 'Source has no declared author; do not invent one')

    def test_disease_fixtures_keep_unrendered_treatment_prevention_and_faqs(self):
        for name in ('benh_a_vay_nen', 'benh_alzheimer'):
            row, body = self.fixture(name)
            doc = self.lc.extract(body, row['url'])
            tree = html.fromstring(body.decode())
            current, reasons = self.lc.current_data(tree, row['url'])
            self.assertEqual(reasons, [])
            self.assertEqual(doc['longchau_review_reasons'], [])
            self.assertTrue(set(self.lc.DISEASE_FIELDS).issubset(doc['longchau_section_keys']))
            for key in ('risk', 'diagnoseAndTreaty', 'livingAndPreventive'):
                self.assertFalse(tree.xpath(f'//*[@id="{key}"]//*[@data-theme-element="article"]'))
                for paragraph in html.fragment_fromstring(current[key], create_parent='div').xpath('.//p'):
                    text = paragraph.text_content().strip()
                    if any(re.sub(r'\s+','',text) in re.sub(r'\s+','',r['text']) for r in doc['longchau_removed_blocks']):
                        continue
                    if text: self.assertIn(re.sub(r'\s+','',text), re.sub(r'\s+','',doc['text']))
            for faq in current['faqs']: self.assertIn(faq['question'], doc['text'])

    def test_clinical_negation_dates_dosage_table_caption_and_pure_link_are_preserved(self):
        content = ('<h2>Cảnh báo</h2><h3>Chống chỉ định</h3><h4>Theo dõi</h4>'
                   '<p>' + PROSE * 3 + '</p><ul><li>Không uống aspirin.</li><li>Liều 5 mg/kg.</li></ul>'
                   '<table><tr><th>Chỉ số</th><th>Đơn vị</th></tr><tr><td>3.5</td><td>mg m<sup>−3</sup></td></tr></table>'
                   '<figure><img src="x"><figcaption>Ảnh biểu hiện bệnh cần giữ.</figcaption></figure>'
                   '<p><a href="/bai-viet/clinical.html">Dược sĩ hướng dẫn dùng thuốc</a></p>'
                   '<p style="text-align:right"><strong>Không uống aspirin</strong></p>'
                   '<p style="text-align:right"><strong>Không Uống Aspirin</strong></p>'
                   '<p style="text-align:right">Nguồn tham khảo: Tổng hợp</p>')
        doc = self.lc.extract(article(content), URL)
        for text in (PROSE.strip(), 'Không uống aspirin', '3.5', 'mg m−3',
                     'Ảnh biểu hiện bệnh cần giữ.', 'Dược sĩ hướng dẫn dùng thuốc', 'Không Uống Aspirin'):
            self.assertIn(text, doc['text'])
        self.assertEqual(doc['source_table_count'], 1)
        self.assertEqual(doc['source_heading_count'], 3)
        self.assertEqual(doc['longchau_review_reasons'], [])
        self.assertNotIn('Tiểu sử dược sĩ', doc['text'])

    def test_component_disclaimer_removed_but_clinical_warning_retained(self):
        doc = self.lc.extract(article('<h2>Cảnh báo</h2><p>'+PROSE*4+'</p>'
            '<aside data-component="site-disclaimer">Website disclaimer</aside>'
            '<div class="related-articles">Bài liên quan</div>'
            '<p>Thông tin và sản phẩm gợi ý trong bài viết chỉ mang tính chất tham khảo.</p>'), URL)
        self.assertIn(PROSE.strip(), doc['text'])
        for junk in ('Website disclaimer','Bài liên quan','Thông tin và sản phẩm gợi ý'):
            self.assertNotIn(junk, doc['text'])

    def test_json_identity_or_ambiguous_dom_never_falls_back_to_long_generic_text(self):
        for body, reason in ((article(slug='bai-viet/wrong.html'), 'longchau_identity_mismatch'),
                (article(extra='<div data-theme-element="article" data-scale-font="true">'+PROSE*5+'</div>'),
                 'longchau_article_boundary_ambiguous')):
            doc = self.crawler.extract(body, 'text/html', URL)
            self.assertIn(reason, doc['longchau_review_reasons'])
            self.assertNotEqual(self.crawler.quality(doc)['quality_status'], 'accepted')

    def test_dom_json_mismatch_and_unsupported_template_remain_review(self):
        body = article().replace(b'<p>', b'<p>DOM-only extra.', 1)
        doc = self.lc.extract(body, URL)
        self.assertIn('longchau_dom_cms_content_mismatch', doc['longchau_review_reasons'])
        doc = self.lc.extract(article(), URL.replace('/bai-viet/', '/unknown/'))
        self.assertIn('longchau_unsupported_path_template', doc['longchau_review_reasons'])

    def test_browser_session_preserves_profile_tls_headers_and_raw_bytes(self):
        record, session, clock, fetcher = self.request([(200, {'Content-Type':'text/html'}, article())])
        self.assertEqual(record['engine'], 'curl_cffi')
        self.assertEqual(record['quality_status'], 'accepted')
        self.assertEqual(session.headers, {}, 'Do not override Chrome profile with Requests headers')
        self.assertFalse(session.calls[0][1]['allow_redirects'])
        self.assertIs(fetcher.session(), session)
        self.session_constructor.assert_called_once_with(impersonate='chrome', verify=True)
        self.assertEqual(gzip.decompress((self.out / record['raw_path']).read_bytes()), article())
        self.assertEqual(record['id'], self.sample['id'])
        self.assertEqual(record['url'], self.sample['url'])

    def test_403_is_one_attempt_and_200_challenge_is_not_accepted(self):
        for status, title in ((403,'Attention Required! | Cloudflare'), (200,'Just a moment...'),
                              (200,'Access denied'), (200,'Checking your browser')):
            body = ('<title>'+title+'</title><h1>'+title+'</h1>').encode()
            # Direct fake route prevents a previous subtest's cooldown affecting the next case.
            fetcher = self.crawler.Fetcher(self.out, delay=0, attempts=3)
            fetcher.uses_browser_fingerprint = True
            with patch.object(fetcher, 'request_once', return_value=(status, {'Content-Type':'text/html'}, body)) as get:
                record = self.probe.request_record(self.crawler, fetcher, self.sample, self.out, 'UA', (1,1), 30)
            self.assertEqual(get.call_count, 1)
            self.assertTrue(record['challenge_detected'])
            self.assertEqual(record['status'], 'http_error')
            self.assertNotEqual(record.get('quality_status'), 'accepted')

    def test_retryable_http_retries_with_backoff_cookie_session_and_minimum_gap(self):
        record, session, clock, _ = self.request([(408, {}, b'wait'), (503, {}, b'wait'),
            (200, {'Content-Type':'text/html'}, article())])
        self.assertEqual(record['status'], 'extracted')
        self.assertEqual([e['http_status'] for e in record['requests']], [408,503,200])
        gaps = [session.calls[i][2]-session.calls[i-1][2] for i in (1,2)]
        self.assertGreaterEqual(gaps[0], 1.75)
        self.assertGreaterEqual(gaps[1], 4.)
        self.assertFalse(any(e.get('session_reset_for_retry') for e in record['requests']))

    def test_long_retry_after_seconds_is_persisted_and_deferred_across_resume(self):
        record, session, clock, _ = self.request([(429, {'Retry-After':'3600'}, b'rate limited')])
        self.assertIn('retry_deferred', record)
        self.assertEqual(len(session.calls), 1)
        gate = self.crawler.load_json(self.out / 'longchau_request_gate.json')
        self.assertGreater(gate['not_before'] - clock.time(), 3500)
        fetcher = self.lc.make_fetcher(self.crawler, self.out, self.lc.validate_config({}))
        with self.assertRaises(self.crawler.CrawlError) as error:
            fetcher.request_once(URL, 1000, deadline=clock.monotonic()+30)
        self.assertEqual(error.exception.status, 'response_deadline')
        self.assertEqual(len(session.calls), 1)

    def test_retry_after_http_date_is_respected(self):
        session, clock, config = self.transport([])
        date = format_datetime(datetime.fromtimestamp(clock.time()+10, timezone.utc), usegmt=True)
        session.responses = [(503, {'Retry-After': date}, b'busy'), (200, {'Content-Type':'text/html'}, article())]
        fetcher = self.lc.make_fetcher(self.crawler, self.out, config)
        record = self.probe.request_record(self.crawler, fetcher, self.sample, self.out, 'UA', config['timeout'], 30)
        self.assertEqual(record['status'], 'extracted')
        self.assertGreaterEqual(session.calls[1][2]-session.calls[0][2], 10)

    def test_timeout_retries_but_tls_validation_failure_does_not(self):
        from curl_cffi import requests as curl_requests
        record, session, _, _ = self.request([curl_requests.exceptions.Timeout('timed out'),
            (200, {'Content-Type':'text/html'}, article())])
        self.assertEqual(record['status'], 'extracted')
        self.assertEqual(len(session.calls), 2)
        session.responses = [curl_requests.exceptions.SSLError('certificate verify failed')]
        record = self.probe.request_record(self.crawler, self.lc.make_fetcher(self.crawler, self.out,
            self.lc.validate_config({})), dict(self.sample,id=778), self.out, 'UA', (10,45), 180)
        self.assertEqual(record['error_kind'], 'ssl_error')
        self.assertFalse(record['retryable'])
        self.assertEqual(len(session.calls), 3)

    def test_stream_size_limit_never_saves_oversized_as_article(self):
        session, clock, config = self.transport([(200, {}, b'X'*1001)])
        fetcher = self.lc.make_fetcher(self.crawler, self.out, config)
        with self.assertRaises(self.crawler.CrawlError) as error:
            fetcher.request_once(URL, 1000, deadline=clock.monotonic()+30)
        self.assertEqual(error.exception.status, 'oversized')

    def test_robots_deny_uses_curl_and_never_requests_article(self):
        record, session, _, _ = self.request([(403, {}, b'robots denied')], respect_robots=True)
        self.assertEqual(record['status'], 'robots_denied')
        self.assertEqual([c[0] for c in session.calls], ['https://nhathuoclongchau.com.vn/robots.txt'])
        self.assertEqual(record['robots']['status'], 403)

    def test_main_route_never_starts_chrome_for_longchau(self):
        self.make_run([self.sample])
        session, _, _ = self.transport([(200, {'Content-Type':'text/html'}, article())])
        with patch.object(self.probe, 'browser_preflight') as browser, \
                patch.object(self.probe, 'crawl_requests') as regular:
            result = self.runner.run(self.crawler,self.probe,self.out,{},workers=4)
        browser.assert_not_called()
        self.assertEqual(result['longchau_curl'], 1)
        # An empty ordinary route is harmless; no Long Chau sample may reach it.
        if regular.called: self.assertEqual(regular.call_args.args[2], [])

    def test_interrupt_resume_preserves_success_and_repairs_publication(self):
        samples = [self.sample, dict(self.sample,id=778)]
        self.make_run(samples)
        session, _, _ = self.transport([(200, {'Content-Type':'text/html'}, article()), KeyboardInterrupt('stop')])
        with self.assertRaises(KeyboardInterrupt):
            self.runner.run(self.crawler,self.probe,self.out,{},workers=4)
        saved = (self.out / 'requests_records/777.json').read_bytes()
        (self.out / 'records/777.json').unlink()
        session.responses = [(200, {'Content-Type':'text/html'}, article())]
        self.runner.run(self.crawler,self.probe,self.out,{},workers=4)
        self.assertEqual((self.out / 'requests_records/777.json').read_bytes(),saved)
        self.assertEqual(self.crawler.load_json(self.out / 'records/777.json')['engine'],'curl_cffi')
        self.assertEqual(len(session.calls), 3)

    def test_failed_403_is_retried_on_resume_and_success_is_cached(self):
        self.make_run([self.sample])
        session, _, _ = self.transport([(403, {}, b'<title>Access denied</title>'),
            (200, {'Content-Type':'text/html'}, article())])
        self.runner.run(self.crawler,self.probe,self.out,{},workers=1)
        self.runner.run(self.crawler,self.probe,self.out,{},workers=1)
        checkpoint = (self.out / 'records/777.json').read_bytes()
        self.runner.run(self.crawler,self.probe,self.out,{},workers=1)
        self.assertEqual(len(session.calls),2)
        self.assertEqual((self.out / 'records/777.json').read_bytes(),checkpoint)
        history=list((self.out/'longchau_previous_records').glob('777_*.json'))
        self.assertEqual(len(history),1)
        self.assertEqual(self.crawler.load_json(history[0])['http_status'],403)

    def test_resume_config_change_and_corrupt_success_are_rejected(self):
        self.make_run([self.sample])
        self.transport([(200, {'Content-Type':'text/html'}, article())])
        self.runner.run(self.crawler,self.probe,self.out,{},workers=1)
        with self.assertRaisesRegex(ValueError,'code/config changed'):
            self.runner.run(self.crawler,self.probe,self.out,{'longchau':{'delay':2.}},workers=1)
        record = self.crawler.load_json(self.out/'requests_records/777.json')
        self.crawler.atomic_bytes(self.out/record['raw_path'],gzip.compress(b'corrupted'))
        with self.assertRaisesRegex(ValueError,'hash mismatch|Corrupt raw'):
            self.runner.run(self.crawler,self.probe,self.out,{},workers=1)

    def test_recovery_reextracts_legacy_200_and_leaves_old_403_pending(self):
        old = self.out/'old'
        old.mkdir()
        samples = [self.sample,dict(self.sample,id=778)]
        self.crawler.write_json(old/'manifest.json',{'sample_sha256':'legacy'})
        self.crawler.atomic_bytes(old/'raw/777.gz',gzip.compress(article()))
        self.crawler.write_json(old/'records/777.json',dict(self.sample,status='extracted',http_status=200,
            final_url=URL,content_type='text/html',extractor='trafilatura',text='OLD INCOMPLETE TEXT',
            raw_path='raw/777.gz',raw_sha256=self.crawler.digest(article())))
        self.crawler.write_json(old/'records/778.json',dict(samples[1],status='http_error',http_status=403))
        manifest = self.probe.seed_successful_requests(self.crawler,self.out,samples,old,record_dir='requests_records')
        recovered = self.crawler.load_json(self.out/'requests_records/777.json')
        self.assertEqual(manifest['reused_ids'],[777])
        self.assertEqual(manifest['retry_ids'],[778])
        self.assertIn(PROSE.strip(),recovered['text'])
        self.assertNotIn('OLD INCOMPLETE',recovered['text'])
        self.assertEqual(recovered['longchau_parser_version'], self.lc.VERSION)

    def test_audit_detects_truncation_and_legacy_accepted_text(self):
        doc=self.lc.extract(article(),URL)
        record=dict(self.sample,**doc,status='extracted',quality_status='accepted',final_url=URL)
        _, details = self.audit.audit_longchau(record,article(),self.lc)
        self.assertTrue(details['longchau_raw_reextraction_verified'])
        with self.assertRaisesRegex(ValueError,'full text/raw mismatch'):
            self.audit.audit_longchau(dict(record,text=record['text'][:600]),article(),self.lc)
        with self.assertRaisesRegex(ValueError,'Legacy Long Chau'):
            self.audit.audit_longchau(dict(record,longchau_parser_version=None,extractor='trafilatura'),article(),self.lc)

    def test_report_previews_never_truncate_saved_corpus_text(self):
        record,_,_,_=self.request([(200,{'Content-Type':'text/html'},article())])
        self.lc.write_reports(self.crawler,self.out,[self.sample])
        row=json.loads((self.out/'longchau_results.jsonl').read_text(encoding='utf-8'))
        self.assertEqual(len(row['preview_start']),600)
        self.assertEqual(row['preview_end'],record['text'][-600:])
        self.assertEqual(self.crawler.load_json(self.out/'records/777.json')['text'],record['text'])

    def test_stratified_sampling_is_unique_deterministic_and_preserves_source_ids(self):
        rows=[{'id':i*37+5,'url':f'https://nhathuoclongchau.com.vn/{kind}/test-{i}{suffix}.html'}
              for i in range(30) for kind,suffix in [('bai-viet',''),('benh','-123')]]
        # Unique IDs per row are part of the source contract.
        for i,r in enumerate(rows): r['id']=100+i*37
        source=self.out/'source.parquet'
        pq.write_table(pa.Table.from_pylist(rows),source)
        selected,profile=self.smoke.select(source,50)
        self.assertEqual(selected,self.smoke.select(source,50)[0])
        self.assertEqual(len({r['url'] for r in selected}),50)
        expected={r['id']:r['url'] for r in rows}
        self.assertTrue(all(expected[r['id']]==r['url'] for r in selected))
        self.assertEqual(sorted(profile['selected_strata'].values()),[25,25])

    def test_longchau_snapshot_and_shared_probe_match_both_notebooks(self):
        main=json.loads((ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        domain=json.loads((ROOT/'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        import base64,zlib
        pack=assignments(''.join(domain['cells'][7]['source']))
        self.assertEqual(zlib.decompress(base64.b85decode(pack['LONGCHAU_PAYLOAD'])),(ROOT/'scripts/longchau.py').read_bytes())
        self.assertEqual(zlib.decompress(base64.b85decode(pack['PRIORITY_PAYLOAD'])),(ROOT/'scripts/priority_probe.py').read_bytes())
        main_pack=assignments(''.join(main['cells'][6]['source']))
        for name,source in [('longchau_snapshot.py','longchau.py'),('priority_probe_snapshot.py','priority_probe.py')]:
            self.assertEqual(zlib.decompress(base64.b85decode(main_pack['EMBEDDED_FILES'][name])),(ROOT/'scripts'/source).read_bytes())

    def test_domain_notebook_routes_longchau_without_requests_or_chrome(self):
        notebook=json.loads((ROOT/'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        config=assignments(''.join(notebook['cells'][3]['source']))
        self.make_run([self.sample])
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},article())])
        env=dict(config,RUN_DIR=self.out,crawler=self.crawler,priority_probe=self.probe,longchau=self.lc,
                 IP_CHECK_ENABLED=False,DIRECT_PUBLIC_PROBE=True,SAMPLES=[self.sample],NETWORK_CHECK_DOMAINS=[],
                 save_outputs=lambda **kw:([],{},self.out/'test.zip'))
        with patch.object(self.probe,'browser_preflight') as browser,patch.object(self.probe,'crawl_requests') as regular:
            exec(compile(''.join(notebook['cells'][11]['source']),'<domain-longchau>','exec'),env)
        browser.assert_not_called()
        if regular.called: self.assertEqual(regular.call_args.args[2],[])
        self.assertEqual(self.crawler.load_json(self.out/'records/777.json')['engine'],'curl_cffi')
        self.assertEqual(len(session.calls),1)

    def test_smoke_kaggle_notebook_runs_self_contained_with_local_source_offline(self):
        notebook=json.loads((ROOT/'notebooks/check_longchau_50.ipynb').read_text(encoding='utf-8'))
        source=self.out/'source.parquet'
        pq.write_table(pa.Table.from_pylist([{'id':777,'url':URL}]),source)
        self.transport([(200,{'Content-Type':'text/html'},article())])
        env={}
        # Execute the real notebook, skipping pip only; the transport is a documented offline mock.
        exec(compile(''.join(notebook['cells'][1]['source']),'<smoke-config>','exec'),env)
        env.update(WORKDIR=self.out,RUN_DIR=self.out/'smoke',SOURCE_PARQUET=str(source),LIMIT=1)
        for index in (3,4,5):
            exec(compile(''.join(notebook['cells'][index]['source']),f'<smoke-{index}>','exec'),env)
        exported=pq.read_table(env['RUN_DIR']/'corpus.parquet').to_pylist()
        self.assertEqual(exported[0]['id'],777)
        self.assertEqual(exported[0]['url'],URL)
        self.assertIn(PROSE.strip(),exported[0]['text'])
        self.assertEqual(exported[0]['author'],'Nguyễn An')
        self.assertEqual(exported[0]['reviewed_by'],'Trần Bình')
        self.assertEqual(exported[0]['updated_at'],'2026-10-14T01:00:00Z')


if __name__=='__main__': unittest.main()
