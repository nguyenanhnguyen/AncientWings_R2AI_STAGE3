"""Regression coverage for Long Chau cleanup, shared backups, progress and recovery cooldown."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import zipfile

import test_notebook_longchau as base
import test_notebook_pubmed_efetch as pubmed
import test_notebook_pubmed_parser as pubmed_html
from test_notebook_selenium_fallback import load_module


class LongChauPipelineFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.LongChauTests.setUpClass.__func__(cls)
        cls.backup=load_module('pipeline_backup_test',cls.root/'checkpoint_snapshot.py')
        cls.diagnostics=load_module('pipeline_diagnostics_test',cls.root/'diagnostics_snapshot.py')
    @classmethod
    def tearDownClass(cls): base.LongChauTests.tearDownClass.__func__(cls)
    def setUp(self): base.LongChauTests.setUp(self)
    transport=base.LongChauTests.transport
    make_run=base.LongChauTests.make_run

    def config(self,efetch=True,**checkpoint):
        return {'browser_mode':'off','pubmed_use_efetch':efetch,
            'pubmed_efetch':{'checkpoint':{'enabled':True,'upload':False,
                'every_urls':10000,'archive_dir':str(self.out.parent),**checkpoint}}}

    def samples(self,count=3):
        return [dict(self.sample,id=self.sample['id']+i) for i in range(count)]

    def state(self): return self.crawler.load_json(self.out/'checkpoint_upload_state.json')

    def test_related_paragraph_group_is_removed_without_cutting_medical_links_or_prose(self):
        content=('<h2>Điều trị</h2><p><a href="/benh/clinical.html">'+base.PROSE+'</a></p>'
            '<p>Xem thêm:&nbsp;</p><p><a href="/bai-viet/related.html">Bài liên quan A</a></p>'
            '<p><a href="/bai-viet/related-2.html">Bài liên quan B</a><a> </a></p>'
            '<h2>Cảnh báo tiếp theo</h2><p>'+base.PROSE*5+'</p>')
        doc=self.lc.extract(base.article(content),base.URL)
        self.assertNotIn('Xem thêm',doc['text'])
        self.assertNotIn('Bài liên quan',doc['text'])
        self.assertIn(base.PROSE.strip(),doc['text'])
        self.assertIn('Cảnh báo tiếp theo',doc['text'])
        self.assertEqual(doc['longchau_removed_count'],3)
        self.assertEqual(doc['missing_blocks'],0)
        self.assertEqual(doc['longchau_review_reasons'],[])

    def test_mixed_link_list_keeps_clinical_prose(self):
        content=('<h2>Điều trị</h2><p>'+base.PROSE*5+'</p><p>Xem thêm:</p>'
            '<ul><li><a href="/bai-viet/ref.html">Tài liệu</a></li><li>'+base.PROSE+'</li></ul>')
        doc=self.lc.extract(base.article(content),base.URL)
        self.assertIn('Tài liệu',doc['text'])
        self.assertEqual(doc['longchau_removed_count'],0)
        self.assertEqual(doc['text'].count(base.PROSE.strip()),6)

    def test_longchau_only_has_no_empty_efetch_backup_and_final_zip_has_current_records(self):
        self.make_run(self.samples(2))
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},base.article())]*2)
        output=io.StringIO()
        with redirect_stdout(output):
            self.runner.run(self.crawler,self.probe,self.out,self.config(every_urls=1),workers=1)
        backups=[json.loads(l) for l in output.getvalue().splitlines() if l.startswith('{')
                 and json.loads(l).get('event')=='periodic_checkpoint']
        self.assertTrue(backups)
        self.assertTrue(all(r['completed']>0 for r in backups))
        self.assertEqual([r['completed'] for r in backups],[1,2,2])
        self.assertEqual((self.state()['completed'],self.state()['pending']),(2,0))
        self.assertEqual(len(session.calls),2)
        with zipfile.ZipFile(self.state()['local_archive']) as z:
            self.assertIsNone(z.testzip())
            self.assertIn(self.out.name+'/records/778.json',z.namelist())

    def test_checkpoint_also_works_with_efetch_disabled(self):
        self.make_run(self.samples(1))
        self.transport([(200,{'Content-Type':'text/html'},base.article())])
        self.runner.run(self.crawler,self.probe,self.out,self.config(efetch=False),workers=1)
        self.assertEqual(self.state()['completed'],1)

    def website_run(self,count=1):
        samples=[{'id':777+i,'url':f'https://pubmed.ncbi.nlm.nih.gov/{28382721+i}/',
            'domain':'pubmed.ncbi.nlm.nih.gov'} for i in range(count)]
        self.make_run(samples)
        self.crawler.write_json(self.out/'source_profile.json',{'rows':count,
            'host_counts':{'pubmed.ncbi.nlm.nih.gov':count},
            'sample_host_counts':{'pubmed.ncbi.nlm.nih.gov':count}})
        return samples

    def test_requests_website_publishes_shared_checkpoint(self):
        self.website_run()
        config=dict(self.config(efetch=False),longchau_use_curl=False,pubmed_selenium_first=False)
        with patch.object(self.crawler.Fetcher,'request_once',
                return_value=(200,{'Content-Type':'text/html'},pubmed_html.article())),redirect_stdout(io.StringIO()):
            self.runner.run(self.crawler,self.probe,self.out,config,workers=1)
        self.assertEqual(self.state()['completed'],1)
        self.assertEqual(self.crawler.load_json(self.out/'records/777.json')['engine'],'requests')

    def test_selenium_interruption_still_backs_up_finished_browser_result(self):
        self.website_run(2)
        config=dict(self.config(efetch=False),longchau_use_curl=False,browser_mode='failed_only')
        def rendered(crawler,driver,sample,out,**options):
            if sample['id']==778:raise KeyboardInterrupt()
            raw=pubmed_html.article(pmid='28382721')
            path='raw/selenium/777.gz';crawler.atomic_bytes(out/path,gzip.compress(raw,mtime=0))
            doc=crawler.extract(raw,'text/html',sample['url'])
            return dict(sample,**doc,**crawler.quality(doc),engine='selenium',status='rendered',
                http_status=200,final_url=sample['url'],raw_path=path,raw_sha256=crawler.digest(raw),elapsed_seconds=0)
        with patch.object(self.probe,'browser_preflight'),patch.object(self.probe,'create_browser',return_value=Mock()),\
                patch.object(self.probe,'browser_attempt',side_effect=rendered),redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                self.runner.run(self.crawler,self.probe,self.out,config,workers=1)
        self.assertEqual((self.state()['completed'],self.state()['pending']),(1,1))
        with zipfile.ZipFile(self.state()['local_archive']) as z:
            self.assertIn(self.out.name+'/browser_records/777.json',z.namelist())

    def test_time_cadence_saves_mid_crawl_even_without_url_threshold(self):
        self.make_run(self.samples(2))
        self.transport([(200,{'Content-Type':'text/html'},base.article())]*2)
        output=io.StringIO()
        with redirect_stdout(output):
            self.runner.run(self.crawler,self.probe,self.out,self.config(every_seconds=.05),workers=1)
        backups=[json.loads(l) for l in output.getvalue().splitlines() if l.startswith('{')
                 and json.loads(l).get('event')=='periodic_checkpoint']
        self.assertEqual(backups[0]['completed'],1,'Time checkpoint must happen before the whole crawl finishes')
        self.assertEqual(backups[-1]['completed'],2)

    def test_notebook_rejects_old_longchau_resume_before_overwriting_runtime_or_data(self):
        nb=json.loads((base.ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        self.make_run(self.samples(1))
        self.crawler.write_json(self.out/'corpus_config.json',{'longchau_sha256':'old-parser',
            'runner_sha256':'old-runner','probe_sha256':'old-probe'})
        (self.out/'longchau_snapshot.py').write_bytes(b'# saved legacy runtime\n')
        before={p.name:p.read_bytes() for p in self.out.iterdir() if p.is_file()}
        with self.assertRaisesRegex(ValueError,'RECOVERY_RUN_PATH'):
            exec(compile(''.join(nb['cells'][6]['source']),'snapshot-cell','exec'),
                {'RUN_DIR':self.out,'POSTPROCESS_ONLY':False,'json':json})
        for name,body in before.items():self.assertEqual((self.out/name).read_bytes(),body,name)

    def test_24_hour_429_forces_latest_backup_and_stops_before_next_url(self):
        self.make_run(self.samples())
        session,clock,_=self.transport([(200,{'Content-Type':'text/html'},base.article()),
            (429,{'Content-Type':'text/html','Retry-After':'86400'},b'<h1>Error 1015</h1>')])
        summary=self.runner.run(self.crawler,self.probe,self.out,self.config(),workers=1)
        self.assertEqual(len(session.calls),2)
        self.assertEqual((summary['completed'],summary['pending']),(2,1))
        self.assertEqual((self.state()['completed'],self.state()['pending']),(2,1))
        gate=self.crawler.load_json(self.out/'longchau_request_gate.json')['not_before']
        self.assertGreater(gate-clock.time(),86300)
        self.assertFalse((self.out/'records/779.json').exists())

    def test_interruption_backs_up_committed_record_and_resume_does_not_fetch_it_again(self):
        self.make_run(self.samples())
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},base.article()),KeyboardInterrupt()])
        config=self.config()
        with self.assertRaises(KeyboardInterrupt):
            self.runner.run(self.crawler,self.probe,self.out,config,workers=1)
        self.assertEqual(self.state()['completed'],1)
        previous=(self.out/'records/777.json').read_bytes()
        session,_,_=self.transport([(200,{'Content-Type':'text/html'},base.article())]*2)
        self.runner.run(self.crawler,self.probe,self.out,config,workers=1)
        self.assertEqual(len(session.calls),2)
        self.assertEqual(self.state()['completed'],3)
        self.assertEqual((self.out/'records/777.json').read_bytes(),previous)

    def test_mixed_pubmed_longchau_progress_and_checkpoint_count_ids_once(self):
        samples=self.samples(1)+[{'id':778,'url':'https://pubmed.ncbi.nlm.nih.gov/28000000/',
            'domain':'pubmed.ncbi.nlm.nih.gov'}]
        self.make_run(samples)
        self.crawler.write_json(self.out/'source_profile.json',{'rows':2,
            'host_counts':{'nhathuoclongchau.com.vn':1,'pubmed.ncbi.nlm.nih.gov':1},
            'sample_host_counts':{'nhathuoclongchau.com.vn':1,'pubmed.ncbi.nlm.nih.gov':1}})
        self.transport([(200,{'Content-Type':'text/html'},base.article())])
        api_session=Mock();api_session.headers={}
        api_session.get.return_value=pubmed.Response(pubmed.xml([pubmed.article('28000000')]))
        output=io.StringIO()
        with patch('requests.Session',return_value=api_session),redirect_stdout(output):
            self.runner.run(self.crawler,self.probe,self.out,self.config(every_urls=1),workers=1)
        rows=[json.loads(line) for line in output.getvalue().splitlines() if line.startswith('{')]
        totals=[r for r in rows if r.get('progress_scope')=='invocation']
        engines=[r for r in rows if r.get('engine')=='curl_cffi' and 'completed_this_invocation' in r]
        self.assertEqual(totals[-1]['completed_this_invocation'],2)
        self.assertEqual(totals[-1]['scheduled'],2)
        self.assertEqual(engines[-1]['completed_this_invocation'],1)
        self.assertEqual(self.state()['completed'],2)

    def test_recovery_preserves_server_cooldown_and_reuses_success_without_network(self):
        samples=self.samples(2)
        self.make_run(samples)
        session,clock,_=self.transport([(200,{'Content-Type':'text/html'},base.article()),
            (429,{'Content-Type':'text/html','Retry-After':'86400'},b'<h1>Error 1015</h1>')])
        config=self.config()
        self.runner.run(self.crawler,self.probe,self.out,config,workers=1)
        source=self.out
        original=(source/'records/777.json').read_bytes()
        self.out=source.parent/'recovery'
        self.make_run(samples)
        session,clock,_=self.transport([])
        self.runner.run(self.crawler,self.probe,self.out,config,recovery_source=source,workers=1)
        self.assertEqual(session.calls,[],'Recovery must respect the 24-hour gate before GET')
        self.assertEqual((source/'records/777.json').read_bytes(),original)
        self.assertEqual(self.crawler.load_json(self.out/'records/777.json')['status'],'extracted')
        self.assertEqual(self.crawler.load_json(self.out/'recovery_manifest.json')['reused_ids'],[777])
        self.assertGreater(self.crawler.load_json(self.out/'longchau_request_gate.json')['not_before']-clock.time(),86300)

    def test_diagnostics_prefers_source_id_progress_over_last_engine_and_suppresses_cooldown_eta(self):
        logs=self.out/'logs';logs.mkdir(exist_ok=True)
        self.crawler.jsonl(logs/'invocations.jsonl',[{'event':'start','operation':'crawl',
            'invocation_id':'one','at':'2026-10-15T00:00:00+00:00'},
            {'event':'end','invocation_id':'one','elapsed_seconds':100.}])
        self.crawler.jsonl(logs/'progress.jsonl',[
            {'invocation_id':'one','progress_scope':'invocation','completed_this_invocation':555,'scheduled':1001},
            {'invocation_id':'one','progress_scope':'engine','completed_this_invocation':1,'scheduled':1}])
        data=self.diagnostics.timing_summary(self.out,datetime.now(timezone.utc),[])
        self.assertEqual(data['completed_at_last_progress'],555)
        self.assertEqual(data['urls_per_minute'],333.)
        self.assertIsNotNone(data['eta_seconds'])
        with (logs/'progress.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps({'invocation_id':'one','progress_scope':'invocation',
                'completed_this_invocation':555,'scheduled':1001,'deferred':True})+'\n')
        data=self.diagnostics.timing_summary(self.out,datetime.now(timezone.utc),[])
        self.assertIsNone(data['eta_seconds'])
        self.assertTrue(data['deferred'])
