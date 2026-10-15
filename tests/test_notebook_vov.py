"""VOV curl routing, Chrome profile, cooldown, resume and both embedded notebooks."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
from email.utils import format_datetime
import gzip
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_notebook_longchau as base
from test_notebook_selenium_fallback import assignments


BODY=('<html><head><title>Health research news</title></head><body><main><article>'
      '<h1>Health research news</h1><p>'+base.PROSE*15+'</p></article></main></body></html>').encode()


class VOVTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):base.LongChauTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):base.LongChauTests.tearDownClass.__func__(cls)
    def setUp(self):base.LongChauTests.setUp(self)
    transport=base.LongChauTests.transport
    make_run=base.LongChauTests.make_run

    def samples(self,count=2):
        return [{'id':777+i,'url':f"https://{'vov.vn' if i%2==0 else 'vov2.vov.vn'}/suc-khoe/article-{i}.vov",
                 'domain':'vov.vn' if i%2==0 else 'vov2.vov.vn'} for i in range(count)]

    def run_probe(self,samples,**options):
        return self.probe.crawl_requests(self.crawler,self.out,samples,user_agent='TestCrawler',
            delay=1.,attempts=3,timeout=(10.,30.),budget=90.,**options)

    def test_host_boundary(self):
        for url in ('https://vov.vn/a','https://vov2.vov.vn/a','https://www.vov.vn/a'):
            self.assertTrue(self.probe.is_vov(url))
        for url in ('https://vov.vn.evil.example/a','https://fakevov.vn/a','https://example.com/vov.vn'):
            self.assertFalse(self.probe.is_vov(url))

    def test_shared_curl_session_profile_tls_pacing_raw_mapping_and_resume(self):
        session,clock,_=self.transport([(200,{'Content-Type':'text/html'},BODY)]*2)
        samples=self.samples()
        records=self.run_probe(samples,workers=4)
        self.session_constructor.assert_called_once_with(impersonate='chrome',verify=True)
        self.assertEqual(session.headers,{})
        self.assertTrue(session.closed)
        self.assertGreaterEqual(session.calls[1][2]-session.calls[0][2],1.)
        for sample,record in zip(samples,records):
            self.assertEqual((record['id'],record['url']),(sample['id'],sample['url']))
            self.assertEqual((record['engine'],record['impersonate'],record['status']),('curl_cffi','chrome','extracted'))
            self.assertFalse(session.calls[0][1]['allow_redirects'])
            self.assertEqual(gzip.decompress((self.out/record['raw_path']).read_bytes()),BODY)
        self.run_probe(samples,workers=4)
        self.assertEqual(len(session.calls),2)

    def test_429_is_one_request_and_pending_stays_pending_until_cooldown(self):
        session,clock,_=self.transport([(429,{'Retry-After':'86400'},b'rate limited'),(200,{'Content-Type':'text/html'},BODY)]*2)
        samples=self.samples()
        rows=self.run_probe(samples)
        self.assertEqual(len(session.calls),1)
        self.assertEqual(len(rows),1)
        self.assertTrue(rows[0]['retry_deferred'])
        self.assertFalse((self.out/'records/778.json').exists())
        self.run_probe(samples)
        self.assertEqual(len(session.calls),1,'A resumed active gate must not make a request')
        clock.sleep(86401)
        self.run_probe(samples,max_new=1)
        self.assertEqual(len(session.calls),2)
        self.assertEqual(self.crawler.load_json(self.out/'records/777.json')['status'],'extracted')
        self.assertTrue(list((self.out/'vov_previous_records').glob('777_*.json')))

    def test_http_date_retry_after_and_tls_failure(self):
        session,clock,_=self.transport([])
        retry=format_datetime(datetime.fromtimestamp(clock.time()+3600,timezone.utc),usegmt=True)
        session.responses=[(429,{'Retry-After':retry},b'limit')]
        self.run_probe(self.samples(1))
        self.assertGreater(self.crawler.load_json(self.out/'vov_request_gate.json')['not_before'],clock.time()+3590)
        # Fresh output for an unrelated TLS failure: no TLS bypass or retry.
        self.out=self.out/'tls';self.out.mkdir()
        from curl_cffi import requests as curl_requests
        session.responses=[curl_requests.exceptions.SSLError('certificate failed')]
        rows=self.run_probe(self.samples(1))
        self.assertEqual(rows[0]['status'],'network_error')
        self.assertFalse(rows[0]['retryable'])
        self.assertEqual(len(session.calls),2)

    def test_timeout_retry_keeps_chrome_session_and_redirect_keeps_source_id(self):
        from curl_cffi import requests as curl_requests
        session,_,_=self.transport([curl_requests.exceptions.Timeout('read timeout'),
            (301,{'Location':'https://vov2.vov.vn/moved'},b'redirect'),(200,{'Content-Type':'text/html'},BODY)])
        samples=self.samples(1)
        rows=self.run_probe(samples)
        self.assertEqual((rows[0]['id'],rows[0]['url']),(samples[0]['id'],samples[0]['url']))
        self.assertEqual(rows[0]['final_url'],'https://vov2.vov.vn/moved')
        self.assertEqual(len(rows[0]['redirects']),1)
        self.assertEqual(len(session.calls),3)
        self.assertEqual(self.session_constructor.call_count,1)
        self.assertEqual(rows[0]['status'],'extracted')

    def test_robots_disallow_uses_curl_without_requesting_article(self):
        session,_,_=self.transport([(200,{'Content-Type':'text/plain'},b'User-agent: *\nDisallow: /\n')])
        rows=self.run_probe(self.samples(1),respect_robots=True)
        self.assertEqual(rows[0]['status'],'robots_disallowed')
        self.assertEqual(len(session.calls),1)
        self.assertEqual(session.calls[0][0],'https://vov.vn/robots.txt')

    def test_curl_callback_enforces_body_limit(self):
        self.transport([(200,{'Content-Type':'text/html'},BODY)])
        fetcher=self.probe.make_vov_fetcher(self.crawler,self.out,delay=1.,attempts=1)
        self.addCleanup(fetcher.close)
        with self.assertRaises(self.crawler.CrawlError) as raised:
            fetcher.request_once(self.samples(1)[0]['url'],100,timeout=(10.,30.))
        self.assertEqual(raised.exception.status,'oversized')

    def test_no_browser_in_main_runner_and_shared_checkpoint_limit(self):
        samples=self.samples(2);self.make_run(samples)
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},BODY)]*2)
        with patch.object(self.probe,'browser_preflight') as preflight,patch.object(self.probe,'crawl_browser') as browser:
            config={'pubmed_use_efetch':False,'browser_mode':'all','delay':1.,
                    'checkpoint':{'enabled':True,'upload':False,'every_urls':1,'archive_dir':str(self.out.parent)}}
            first=self.runner.run(self.crawler,self.probe,self.out,config,workers=4,max_new=1)
            self.assertEqual((first['vov_curl'],first['longchau_curl'],first['pending']),(1,0,1))
            saved=(self.out/'records/777.json').read_bytes()
            second=self.runner.run(self.crawler,self.probe,self.out,config,workers=4,max_new=1)
        self.assertEqual((second['vov_curl'],second['pending']),(2,0))
        self.assertEqual((self.out/'records/777.json').read_bytes(),saved)
        preflight.assert_not_called();browser.assert_not_called()
        self.assertEqual(self.crawler.load_json(self.out/'checkpoint_upload_state.json')['completed'],2)
        self.assertEqual(len(session.calls),2)

    def test_other_domain_keeps_requests(self):
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},BODY)])
        samples=self.samples(1)+[{'id':9,'url':'https://example.org/news','domain':'example.org'}]
        # Patch the base Requests method only; VOV overrides it with its curl method.
        with patch.object(self.crawler.Fetcher,'request_once',return_value=(200,{'Content-Type':'text/html'},BODY)) as requests:
            rows=self.run_probe(samples,workers=1)
        self.assertEqual([r['engine'] for r in rows],['curl_cffi','requests'])
        self.assertEqual(requests.call_count,1)
        self.assertEqual(len(session.calls),1)

    def test_interrupt_preserves_success_and_closes_session(self):
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},BODY),KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt):self.run_probe(self.samples())
        self.assertTrue((self.out/'records/777.json').exists())
        self.assertFalse((self.out/'records/778.json').exists())
        self.assertTrue(session.closed)

    def test_recovery_keeps_future_vov_gate_and_raw_success(self):
        session,clock,_=self.transport([(200,{'Content-Type':'text/html'},BODY)])
        samples=self.samples(1);self.make_run(samples);self.run_probe(samples)
        self.crawler.write_json(self.out/'vov_request_gate.json',{'not_before':clock.time()+86400})
        target=self.out/'recovered';target.mkdir()
        result=self.probe.seed_successful_requests(self.crawler,target,samples,self.out)
        self.assertEqual(result['reused_ids'],[777])
        self.assertGreater(self.crawler.load_json(target/'vov_request_gate.json')['not_before'],clock.time()+86390)

    def test_old_vov_resume_is_rejected_before_any_runtime_or_record_is_overwritten(self):
        samples=self.samples(1);self.make_run(samples)
        self.crawler.write_json(self.out/'corpus_config.json',{'probe_sha256':'old','runner_sha256':'old'})
        (self.out/'priority_probe_snapshot.py').write_bytes(b'# old probe\n')
        before={p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        nb=json.loads((base.ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError,'RECOVERY_RUN_PATH'):
            exec(compile(''.join(nb['cells'][6]['source']),'<vov-resume-guard>','exec'),
                 {'RUN_DIR':self.out,'POSTPROCESS_ONLY':False,'VOV_USE_CURL':True,'json':json})
        for name,body in before.items():self.assertEqual((self.out/name).read_bytes(),body)

    def test_domain_cell_uses_curl_and_never_browser_even_mode_all(self):
        samples=self.samples(1);self.make_run(samples)
        self.transport([(200,{'Content-Type':'text/html'},BODY)])
        nb=json.loads((base.ROOT/'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        config=assignments(''.join(nb['cells'][3]['source']))
        env={**config,'RUN_DIR':self.out,'SAMPLES':samples,'crawler':self.crawler,'priority_probe':self.probe,
             'IP_CHECK_ENABLED':False,'DIRECT_PUBLIC_PROBE':True,'BROWSER_TEST_MODE':'all','VOV_USE_CURL':True,
             'longchau':self.lc,'RECOVERY_RUN_DIR':None,'save_outputs':lambda **kw:([],{},None)}
        with patch.object(self.probe,'browser_preflight') as preflight,patch.object(self.probe,'crawl_browser') as browser:
            exec(compile(''.join(nb['cells'][11]['source']),'<domain-vov>','exec'),env)
        preflight.assert_not_called();browser.assert_not_called()
        self.assertEqual(self.crawler.load_json(self.out/'records/777.json')['engine'],'curl_cffi')


if __name__=='__main__':unittest.main()
