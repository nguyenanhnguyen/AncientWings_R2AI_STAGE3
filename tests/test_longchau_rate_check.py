"""Bounded access probe: pacing, first-block stop, durable cooldown and notebook wiring."""
import gzip
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

import test_notebook_longchau as base
from test_notebook_selenium_fallback import load_module


class RateCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base.LongChauTests.setUpClass.__func__(cls)
        cls.rate=load_module('test_longchau_rate',base.ROOT/'scripts/longchau_rate_check.py')

    @classmethod
    def tearDownClass(cls):base.LongChauTests.tearDownClass.__func__(cls)
    def setUp(self):base.LongChauTests.setUp(self)
    transport=base.LongChauTests.transport

    def samples(self,count):
        return [dict(self.sample,id=777+i,url=base.URL.replace('clinical-test',f'clinical-{i}')) for i in range(count)]

    def good(self,i,headers=None):
        return 200,{'Content-Type':'text/html',**(headers or {})},base.article().replace(b'clinical-test',f'clinical-{i}'.encode())

    def measure(self,samples,**options):
        options.setdefault('stages',[{'delay_seconds':5.,'urls':len(samples)}])
        return self.rate.measure(self.crawler,self.probe,self.lc,samples,self.out/'rate',**options)

    def test_staged_pacing_headers_raw_and_complete_resume(self):
        session,clock,_=self.transport([self.good(i,{'RateLimit-Limit':'100','X-RateLimit-Remaining':str(99-i)}) for i in range(6)])
        samples=self.samples(6)
        stages=[{'delay_seconds':d,'urls':2} for d in (10.,7.5,5.)]
        summary=self.measure(samples,stages=stages)
        self.assertEqual(summary['status'],'completed')
        self.assertEqual(summary['accessible'],6)
        self.assertFalse(summary['exact_quota_known'])
        self.assertEqual(len(summary['server_advertised_rate_headers']),6)
        self.assertEqual(len(session.calls),6)
        # Production pacing waits AFTER each response; changing stages cannot shorten a pending wait.
        for first,second in zip(session.calls,session.calls[1:]):
            self.assertGreaterEqual(second[2]-first[2],5.)
        for sample in samples:
            record=self.crawler.load_json(self.out/'rate/probe_records'/f"{sample['id']}.json")
            raw=gzip.decompress((self.out/'rate'/record['raw_path']).read_bytes())
            self.assertEqual(self.crawler.digest(raw),record['raw_sha256'])
            self.assertEqual((record['id'],record['url']),(sample['id'],sample['url']))
        with zipfile.ZipFile(str(self.out/'rate')+'.zip') as z:
            self.assertIsNone(z.testzip())
            self.assertIn('rate/rate_check_snapshot.py',z.namelist())
        # Completed resume needs neither a new session nor any HTTP requests.
        self.session_constructor.reset_mock()
        again=self.measure(samples,stages=stages)
        self.assertEqual(again['status'],'completed')
        self.assertEqual(again['http_attempts_this_invocation'],0)
        self.session_constructor.assert_not_called()

    def test_first_429_stops_and_shares_cooldown_without_overwriting_input(self):
        session,clock,_=self.transport([self.good(0),(429,{'Retry-After':'86400','Server':'cloudflare'},
            b'<title>Cloudflare Error 1015</title>You are being rate limited'),self.good(2)])
        source=self.out/'readonly-source';destination=self.out/'following-crawl'
        source.mkdir();gate=source/'longchau_request_gate.json'
        self.crawler.write_json(gate,{'not_before':clock.time()-10,'evidence':'keep'})
        before=gate.read_bytes()
        summary=self.measure(self.samples(3),cooldown_dirs=[source],share_cooldown_dir=destination)
        self.assertEqual(summary['status'],'rate_limited')
        self.assertEqual((summary['attempted_urls'],summary['accessible'],len(session.calls)),(2,1,2))
        self.assertGreater(self.crawler.load_json(destination/'longchau_request_gate.json')['not_before'],clock.time()+86390)
        self.assertEqual(gate.read_bytes(),before)
        again=self.measure(self.samples(3),cooldown_dirs=[source],share_cooldown_dir=destination)
        self.assertEqual(again['status'],'deferred_cooldown')
        self.assertEqual(again['http_attempts_this_invocation'],0)
        self.assertEqual(len(session.calls),2)

    def test_existing_cooldown_does_not_create_session(self):
        session,clock,_=self.transport([])
        source=self.out/'old-run';source.mkdir()
        self.crawler.write_json(source/'longchau_request_gate.json',{'not_before':clock.time()+86400})
        summary=self.measure(self.samples(1),cooldown_dirs=[source])
        self.assertEqual(summary['status'],'deferred_cooldown')
        self.session_constructor.assert_not_called()

    def test_200_challenge_is_not_accessible(self):
        session,_,_=self.transport([(200,{'CF-Mitigated':'challenge'},b'<title>Just a moment...</title>'),self.good(1)])
        summary=self.measure(self.samples(2))
        self.assertEqual(summary['status'],'blocked_or_challenge')
        self.assertEqual(summary['accessible'],0)
        self.assertEqual(len(session.calls),1)

    def test_network_failure_is_separate_from_rate_limit(self):
        session,_,_=self.transport([OSError('connection closed'),self.good(1)])
        summary=self.measure(self.samples(2))
        self.assertEqual(summary['status'],'request_error')
        self.assertFalse(summary['exact_quota_known'])
        self.assertEqual(len(session.calls),1)

    def test_interruption_archives_completed_records_then_resume_skips_them(self):
        session,_,_=self.transport([self.good(0),KeyboardInterrupt(),self.good(1)])
        samples=self.samples(2)
        with self.assertRaises(KeyboardInterrupt):self.measure(samples)
        summary=self.crawler.load_json(self.out/'rate/rate_check_summary.json')
        self.assertEqual((summary['status'],summary['accessible']),('interrupted',1))
        self.assertTrue(Path(str(self.out/'rate')+'.zip').is_file())
        summary=self.measure(samples)
        self.assertEqual(summary['accessible'],2)
        self.assertEqual([call[0] for call in session.calls],[samples[0]['url'],samples[1]['url'],samples[1]['url']])

    def test_resume_rejects_changed_selection_and_corrupt_raw(self):
        session,_,_=self.transport([self.good(0)])
        self.measure(self.samples(1))
        with self.assertRaisesRegex(ValueError,'selection/code/settings changed'):self.measure(self.samples(2))
        record=self.crawler.load_json(self.out/'rate/probe_records/777.json')
        (self.out/'rate'/record['raw_path']).write_bytes(gzip.compress(b'corrupt'))
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.measure(self.samples(1))
        self.assertEqual(len(session.calls),1)

    def test_validation_and_no_existing_crawl_overwrite(self):
        for stages in ([{'delay_seconds':0.5,'urls':20}], [{'delay_seconds':5.,'urls':501}],
                       [{'delay_seconds':5.,'urls':1},{'delay_seconds':10.,'urls':1}]):
            with self.subTest(stages=stages),self.assertRaises(ValueError):self.rate.validate_stages(stages)
        with self.assertRaisesRegex(ValueError,'unique'):self.measure(self.samples(1)*2)
        (self.out/'rate/records').mkdir()
        with self.assertRaisesRegex(ValueError,'separate fresh'):self.measure(self.samples(1))

    def test_windows_root_path_cannot_be_misidentified_as_kaggle(self):
        notebook_path=self.out/'check.ipynb'
        subprocess.run([sys.executable,str(base.ROOT/'scripts/build_longchau_smoke_notebook.py'),
                        '--out',str(notebook_path)],check=True)
        notebook=json.loads(notebook_path.read_text(encoding='utf-8'))
        env={}
        with patch.object(sys,'platform','win32'),patch.object(Path,'is_dir',return_value=True):
            exec(''.join(notebook['cells'][1]['source']),env)
        self.assertFalse(env['IS_KAGGLE'])
        self.assertEqual(env['WORKDIR'],Path.cwd())

    def test_actual_notebook_rate_cell_and_postponed_smoke(self):
        notebook_path=self.out/'check.ipynb'
        subprocess.run([sys.executable,str(base.ROOT/'scripts/build_longchau_smoke_notebook.py'),
                        '--out',str(notebook_path)],check=True)
        notebook=json.loads(notebook_path.read_text(encoding='utf-8'))
        source=self.out/'source.parquet'
        pq.write_table(pa.Table.from_pylist(self.samples(2)),source)
        session,_,_=self.transport([(429,{'Retry-After':'86400'},b'rate limited')])
        env={}
        exec(''.join(notebook['cells'][1]['source']),env)
        env.update(WORKDIR=self.out,RUN_DIR=self.out/'smoke',SOURCE_PARQUET=str(source),LIMIT=2,
                   RATE_CHECK_STAGES=[{'delay_seconds':5.,'urls':2}])
        # Fresh embedded runtime has a distinct Fetcher class; DNS remains a documented offline mock.
        with patch.object(socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]):
            for index in (3,4,6,7):
                exec(compile(''.join(notebook['cells'][index]['source']),f'<rate-notebook-{index}>','exec'),env)
        self.assertEqual(env['RATE_CHECK_SUMMARY']['status'],'rate_limited')
        self.assertEqual(len(session.calls),1)
        self.assertFalse((env['RUN_DIR']/'manifest.json').exists(),'Following main crawl must be postponed')
        self.assertTrue((env['RUN_DIR']/'longchau_request_gate.json').is_file())

    def test_successful_rate_check_allows_smoke_with_shared_pacing_gate(self):
        notebook_path=self.out/'check.ipynb'
        subprocess.run([sys.executable,str(base.ROOT/'scripts/build_longchau_smoke_notebook.py'),
                        '--out',str(notebook_path)],check=True)
        notebook=json.loads(notebook_path.read_text(encoding='utf-8'))
        source=self.out/'source.parquet'
        pq.write_table(pa.Table.from_pylist(self.samples(1)),source)
        session,_,_=self.transport([self.good(0),self.good(0)])
        env={}
        exec(''.join(notebook['cells'][1]['source']),env)
        env.update(WORKDIR=self.out,RUN_DIR=self.out/'smoke',SOURCE_PARQUET=str(source),LIMIT=1,
                   RATE_CHECK_STAGES=[{'delay_seconds':5.,'urls':1}])
        with patch.object(socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))]):
            for index in (3,4,6,7):
                exec(compile(''.join(notebook['cells'][index]['source']),f'<rate-and-smoke-{index}>','exec'),env)
        self.assertEqual(env['RATE_CHECK_SUMMARY']['status'],'completed')
        self.assertEqual(env['RATE_CHECK_SUMMARY']['environment'],'Kaggle' if env['IS_KAGGLE'] else 'local_'+sys.platform)
        self.assertEqual(pq.read_table(env['RUN_DIR']/'corpus.parquet').to_pylist()[0]['id'],777)
        self.assertEqual(len(session.calls),2)
        self.assertGreaterEqual(session.calls[1][2]-session.calls[0][2],5.)


if __name__=='__main__':unittest.main()
