"""Transient 400s, bounded batch isolation, transport upgrades and durable checkpoint publication."""
from contextlib import ExitStack, redirect_stdout
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import zipfile

import test_notebook_pubmed_efetch as base_tests
from test_notebook_selenium_fallback import load_module

Response,article,xml=base_tests.Response,base_tests.article,base_tests.xml

TIMEOUT=b'<eFetchResult><ERROR>Error: External viewer error: Empty Response. Bytes read: 0 Status: Timeout</ERROR></eFetchResult>'


class Clock:
    def __init__(self): self.base=datetime.now(timezone.utc).timestamp(); self.elapsed=0.
    def time(self): return self.base+self.elapsed
    def monotonic(self): return self.elapsed
    def sleep(self,value): self.elapsed+=value


class EFetchResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base_tests.PubMedEFetchTests.setUpClass.__func__(cls)
        cls.resume=load_module('efetch_resume_test',cls.root/'pubmed_resume_snapshot.py')
        cls.backup=load_module('efetch_backup_test',cls.root/'checkpoint_snapshot.py')
    @classmethod
    def tearDownClass(cls): base_tests.PubMedEFetchTests.tearDownClass.__func__(cls)
    make_run=base_tests.PubMedEFetchTests.make_run
    get=base_tests.PubMedEFetchTests.get
    page=base_tests.PubMedEFetchTests.page
    rows=base_tests.PubMedEFetchTests.rows
    def setUp(self):
        base_tests.PubMedEFetchTests.setUp(self)
        self.clock=Clock()
        stack=ExitStack()
        for name in ('time','monotonic','sleep'):
            stack.enter_context(patch.object(self.api.time,name,getattr(self.clock,name)))
        stack.enter_context(patch.object(self.api.random,'uniform',return_value=.25))
        self.addCleanup(stack.close)
    def execute(self,config=None,max_new=None):
        settings={'attempts':1,'pending_retry_passes':0,**(config or {})}
        return base_tests.PubMedEFetchTests.execute(self,{'pubmed_efetch':settings},max_new)

    def test_400_timeout_body_retries_with_jitter_and_saved_evidence(self):
        self.make_run(3)
        replies=iter([Response(TIMEOUT,400),Response(xml([article('28000000'),article('28000001'),article('28000002')]))])
        self.reply=lambda *a,**kw:next(replies)
        summary,_,_,_=self.execute({'attempts':2})
        self.assertEqual(summary['completed'],3)
        events=[json.loads(l) for l in (self.out/'pubmed_requests.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([e['http_status'] for e in events],[400,200])
        self.assertEqual(events[0]['error_kind'],'transient_http_400')
        self.assertEqual(events[0]['retry_wait_seconds'],1.25)
        self.assertEqual(gzip.decompress((self.out/events[0]['raw_path']).read_bytes()),TIMEOUT)
        self.assertGreaterEqual(self.clock.elapsed,1.25)

    def test_real_checkpoint_error_body_is_transient_but_other_400s_are_not(self):
        fixture=Path(__file__).parent/'fixtures/pubmed/efetch_timeout_400.xml'
        self.assertTrue(self.api.transient_400(fixture.read_bytes()))
        for body in (b'Invalid UID',b'Invalid timeout parameter',b'Bad request',b'<ERROR>Unknown database</ERROR>'):
            self.assertFalse(self.api.transient_400(body))

    def test_ordinary_400_invalid_parameter_is_pending_without_retries(self):
        self.make_run(3)
        self.reply=Response(b'<ERROR>Invalid timeout parameter</ERROR>',400)
        result,_,_,_=self.execute({'attempts':5,'pending_retry_passes':1})
        self.assertEqual(len(self.api_calls),1)
        self.assertEqual(result['pending'],3)
        self.assertEqual(self.crawler.load_json(self.out/'pubmed_efetch_summary.json')['complete'],False)

    def test_failed_batch_does_not_stop_later_batch(self):
        self.make_run(200)
        def reply(endpoint,**kw):
            ids=kw['params']['id'].split(',')
            if ids[0]=='28000000': return Response(b'Invalid UID',400)
            return Response(xml([article(p) for p in ids]))
        self.reply=reply
        result,_,_,_=self.execute()
        self.assertEqual(result['completed'],100)
        self.assertEqual(result['pending'],100)
        self.assertTrue((self.out/'pubmed_records/110.json').exists())
        self.assertFalse((self.out/'pubmed_records/10.json').exists())

    def test_exhausted_batch_time_budget_does_not_defer_a_healthy_later_batch(self):
        self.make_run(200)
        def reply(endpoint,**kw):
            ids=kw['params']['id'].split(',')
            if ids[0]=='28000000': self.clock.sleep(2.)
            return Response(xml([article(p) for p in ids]))
        self.reply=reply
        result,_,_,_=self.execute({'budget':1.,'fallback_budget':1.})
        self.assertEqual(len(self.api_calls),2)
        self.assertEqual((result['completed'],result['pending']),(100,100))
        self.assertFalse((self.out/'pubmed_records/10.json').exists())
        self.assertTrue((self.out/'pubmed_records/110.json').exists())
        events=[json.loads(line) for line in (self.out/'pubmed_requests.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertFalse(events[0]['raw_complete'],'Partial XML must never mark URLs completed')

    def test_split_100_50_25_to_single_isolates_only_one_bad_pmid(self):
        self.make_run(100)
        bad='28000099'
        def reply(endpoint,**kw):
            ids=kw['params']['id'].split(',')
            return Response(TIMEOUT,400) if bad in ids else Response(xml([article(p) for p in reversed(ids)]))
        self.reply=reply
        result,_,_,_=self.execute()
        sizes=[len(c['params']['id'].split(',')) for c in self.api_calls]
        self.assertEqual(sizes[:3],[100,50,50])
        self.assertIn(25,sizes)
        self.assertIn(1,sizes)
        self.assertEqual(result['completed'],99)
        self.assertEqual(result['pending'],1)
        self.assertFalse((self.out/'pubmed_records/109.json').exists())
        self.assertTrue(all(self.crawler.load_json(p)['id']!=109 for p in (self.out/'pubmed_records').glob('*.json')))

    def test_final_pending_round_recovers_transient_single_pmid(self):
        self.make_run(1)
        calls=0
        def reply(endpoint,**kw):
            nonlocal calls
            calls+=1
            return Response(TIMEOUT,400) if calls==1 else Response(xml([article('28000000')]))
        self.reply=reply
        result,_,_,_=self.execute({'pending_retry_passes':1})
        self.assertEqual(result['completed'],1)
        self.assertEqual(calls,2)
        self.assertEqual(self.crawler.load_json(self.out/'pubmed_efetch_summary.json')['pending'],0)

    def test_fallback_request_budget_bounds_an_outage_and_does_not_fake_completion(self):
        self.make_run(100)
        self.reply=Response(TIMEOUT,400)
        result,_,_,_=self.execute({'max_split_requests':7})
        self.assertEqual(len(self.api_calls),7)
        self.assertEqual(result['pending'],100)
        self.assertFalse(list((self.out/'pubmed_records').glob('*.json')))

    def test_long_retry_after_defers_whole_pass_without_waiting_per_pending_batch(self):
        self.make_run(300)
        self.reply=Response(b'busy',429,{'Retry-After':'3600'})
        result,_,_,_=self.execute({'attempts':1,'pending_retry_passes':1})
        self.assertEqual(len(self.api_calls),1)
        self.assertEqual(result['pending'],300)
        self.assertLess(self.clock.elapsed,1)
        self.assertGreater(self.crawler.load_json(self.out/'pubmed_request_gate.json')['not_before']-self.clock.time(),3500)
        result,_,_,_=self.execute({'attempts':1,'pending_retry_passes':1})
        self.assertEqual(len(self.api_calls),1,'Resume must respect the persisted cooldown without GET')

    def test_retry_after_http_date_and_nonretryable_tls_error(self):
        future=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=600),usegmt=True)
        self.assertGreater(self.api.retry_after_seconds(future),590)
        self.make_run(1)
        self.session.get.side_effect=self.api.requests.exceptions.SSLError('certificate verify failed')
        result,_,_,_=self.execute({'attempts':5,'pending_retry_passes':1})
        self.assertEqual(self.session.get.call_count,1)
        self.assertEqual(result['pending'],1)

    def test_circuit_breaker_needs_multiple_failed_root_batches(self):
        self.make_run(400)
        self.reply=Response(b'Invalid UID',400)
        result,_,_,_=self.execute({'max_consecutive_failed_batches':3})
        self.assertEqual(len(self.api_calls),3)
        self.assertEqual(result['pending'],400)

    def test_max_new_failure_does_not_schedule_extra_domains(self):
        self.make_run(2,mixed=True)
        self.reply=Response(b'Invalid UID',400)
        _,pages,_,_=self.execute(max_new=2)
        pages.assert_not_called()
        self.assertEqual(len(self.api_calls),1)

    def prepared_upgrade(self):
        self.make_run(2)
        self.execute()
        protected={str(p.relative_to(self.out)):p.read_bytes() for p in self.out.rglob('*') if p.is_file()
                   and (p.parent.name in ('records','pubmed_records','pubmed_batches') or p.suffix=='.gz'
                        or p.name in ('manifest.json','sample.jsonl','quality_report.json'))}
        for name in ('pubmed_efetch_snapshot.py','checkpoint_snapshot.py','crawler_snapshot.py',
                     'corpus_runner_snapshot.py','priority_probe_snapshot.py'):
            (self.out/name).write_bytes((self.root/name).read_bytes())
        identity=self.crawler.load_json(self.out/'corpus_config.json')
        old=(self.out/'pubmed_efetch_snapshot.py').read_bytes()+b'\n# old transport marker\n'
        (self.out/'pubmed_efetch_snapshot.py').write_bytes(old)
        identity['pubmed_efetch_sha256']=hashlib.sha256(old).hexdigest()
        self.crawler.write_json(self.out/'corpus_config.json',identity)
        new=(self.root/'pubmed_efetch_snapshot.py').read_bytes()
        return new,protected

    def test_upgrade_refreshes_only_compatible_transport_and_is_idempotent(self):
        new,protected=self.prepared_upgrade()
        state=self.resume.upgrade(self.out,new,{'attempts':5,'timeout':[10.,90.],'budget':300.})
        self.assertEqual((state['completed'],state['pending']),(2,0))
        self.assertEqual((self.out/'pubmed_efetch_snapshot.py').read_bytes(),new)
        for name,body in protected.items(): self.assertEqual((self.out/name).read_bytes(),body,name)
        second=self.resume.upgrade(self.out,new,{'attempts':5,'timeout':[10.,90.],'budget':300.})
        self.assertEqual(second['status'],'current')

    def test_upgrade_rejects_parser_changes_and_corrupt_raw_before_modifying_data(self):
        new,protected=self.prepared_upgrade()
        original=(self.out/'pubmed_efetch_snapshot.py').read_bytes()
        changed=new.replace(b"blocks = {'p',",b"blocks = {'span', 'p',",1)
        with self.assertRaisesRegex(ValueError,'XML parser changed'):
            self.resume.upgrade(self.out,changed,{})
        self.assertEqual((self.out/'pubmed_efetch_snapshot.py').read_bytes(),original)
        row=self.rows()[0]
        self.crawler.atomic_bytes(self.out/row['raw_path'],gzip.compress(b'bad'))
        with self.assertRaises(ValueError): self.resume.upgrade(self.out,new,{})
        self.assertEqual((self.out/'pubmed_efetch_snapshot.py').read_bytes(),original)

    def test_interrupted_upgrade_repairs_snapshot_identity_transaction(self):
        new,_=self.prepared_upgrade()
        original=self.resume.write
        stopped=False
        def write(path,value):
            nonlocal stopped
            if Path(path).name=='corpus_config.json' and not stopped:
                stopped=True
                raise KeyboardInterrupt
            return original(path,value)
        with patch.object(self.resume,'write',side_effect=write),self.assertRaises(KeyboardInterrupt):
            self.resume.upgrade(self.out,new,{})
        self.assertEqual(self.crawler.load_json(self.out/'pubmed_upgrade_journal.json')['status'],'running')
        result=self.resume.upgrade(self.out,new,{})
        self.assertEqual(result['completed'],2)
        self.assertEqual(self.crawler.load_json(self.out/'pubmed_upgrade_journal.json')['status'],'complete')

    def checkpoint_fixture(self):
        self.make_run(2)
        self.execute(max_new=1)
        return self.backup.PeriodicCheckpoint(self.crawler,self.out,{'enabled':True,'upload':False,
            'every_urls':1,'archive_dir':str(self.out.parent)})

    def test_periodic_zip_is_full_valid_and_incomplete_not_corpus_ready(self):
        manager=self.checkpoint_fixture()
        state=manager.maybe_save(new_completed=1)
        self.assertEqual(state['pending'],1)
        self.assertFalse(state['complete'])
        archive=Path(state['local_archive'])
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),state['archive_sha256'])
        with zipfile.ZipFile(archive) as z:
            self.assertIsNone(z.testzip())
            self.assertIn(self.out.name+'/pubmed_records/10.json',z.namelist())
            self.assertIn(self.out.name+'/sample.jsonl',z.namelist())
            self.assertTrue(any('/raw/efetch/' in n for n in z.namelist()))

    def test_checkpoint_zip_and_checksum_are_published_in_one_commit(self):
        manager=self.checkpoint_fixture()
        archive,proof=manager.build()
        client=Mock()
        client.create_commit.return_value=type('Commit',(),{'oid':'remote-sha'})()
        with patch.dict('os.environ',{'HF_TOKEN':'hf_private_token_12345678'}), \
                patch('huggingface_hub.HfApi',return_value=client):
            self.assertEqual(manager.upload(archive,proof),'remote-sha')
        operation=client.create_commit.call_args.kwargs
        self.assertEqual(len(operation['operations']),2)
        self.assertEqual(operation['num_threads'],1)
        self.assertEqual(operation['repo_type'],'dataset')
        self.assertEqual([o.path_in_repo for o in operation['operations']],
                         [f'checkpoints/{self.out.name}/latest.zip',f'checkpoints/{self.out.name}/latest.json'])

    def test_upload_failure_keeps_local_zip_redacts_secret_and_does_not_raise(self):
        manager=self.checkpoint_fixture()
        manager.config['upload']=True
        token='hf_private_token_12345678'
        with patch.dict('os.environ',{'HF_TOKEN':token}),patch.object(manager,'upload',side_effect=RuntimeError('Bearer '+token)), \
                redirect_stdout(io.StringIO()):
            state=manager.maybe_save(force=True)
        self.assertEqual(state['upload_status'],'failed')
        self.assertTrue(Path(state['local_archive']).exists())
        self.assertNotIn(token,(self.out/'checkpoint_upload_state.json').read_text(encoding='utf-8'))

    def test_checkpoint_pack_failure_keeps_previous_good_zip(self):
        manager=self.checkpoint_fixture()
        state=manager.maybe_save(force=True)
        archive=Path(state['local_archive'])
        original=archive.read_bytes()
        with patch.object(self.backup.zipfile.ZipFile,'write',side_effect=OSError('disk error')),redirect_stdout(io.StringIO()):
            manager.maybe_save(force=True)
        self.assertEqual(archive.read_bytes(),original)

    def test_non_efetch_runtime_config_change_requires_recovery(self):
        new,_=self.prepared_upgrade()
        self.resume.upgrade(self.out,new,{})
        desired=self.crawler.load_json(self.out/'corpus_config.json')['settings']
        with self.assertRaisesRegex(ValueError,'Non-EFetch'):
            self.resume.runtime_settings(self.out,dict(desired,browser_mode='off'))


if __name__=='__main__': unittest.main()
