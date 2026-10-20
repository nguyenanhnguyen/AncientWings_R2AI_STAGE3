"""Regressions for review history, immutable resume evidence, and question media."""
import ast
import base64
import csv
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ask120
import ask120_gate as gate
from test_ask120_corpus_gate import create_run, small_page


def csv_rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:return list(csv.DictReader(stream))


class FixTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.source=self.root/'source'
        self.out=self.root/'output'

    def source_page(self,question='A real patient question with enough clinical context.',**metadata):
        body=small_page('A detailed original answer with enough clinical context to pass the length threshold.',question)
        sample={'id':1,'url':'https://www.120ask.com/question/123.htm'}
        gate.write_json(self.source/'manifest.json',{})
        gate.jsonl(self.source/'sample.jsonl',[sample])
        (self.source/'raw').mkdir(exist_ok=True)
        (self.source/'raw/1.gz').write_bytes(gzip.compress(body,mtime=0))
        record=dict(sample,http_status=200,content_type='text/html; charset=utf-8',raw_path='raw/1.gz',raw_sha256=gate.sha(body))
        record.update(metadata)
        gate.write_json(self.source/'records/1.json',record)
        return record

    def replay(self):
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected HTTP')):
            return gate.replay(self.source,self.out)

    def test_resume_source_changes_rejected_before_any_output_changes(self):
        record=self.source_page()
        self.replay()
        names=('manifest.json','sample.jsonl','records/1.json','results_baseline.jsonl')
        before={name:(self.out/name).read_bytes() for name in names}
        for field,value in [('raw_sha256','0'*64),('final_url','https://www.120ask.com/question/456.htm'),
                            ('content_type','text/html; charset=gb18030'),('http_status',403),('text','new baseline')]:
            with self.subTest(field=field):
                gate.write_json(self.source/'records/1.json',dict(record,**{field:value}))
                with self.assertRaisesRegex(ValueError,'Replay identity changed'):self.replay()
                self.assertEqual(before,{name:(self.out/name).read_bytes() for name in names})
        gate.write_json(self.source/'records/1.json',record)
        with patch.object(gate,'parse_source_response',side_effect=AssertionError('Unchanged input re-parsed')):
            self.replay()

    def test_resume_raw_and_matching_new_hash_rejected(self):
        record=self.source_page()
        self.replay()
        body=small_page('A replacement answer with enough text, not the original answer.')
        (self.source/'raw/1.gz').write_bytes(gzip.compress(body))
        record['raw_sha256']=gate.sha(body)
        gate.write_json(self.source/'records/1.json',record)
        with self.assertRaisesRegex(ValueError,'Replay identity changed'):self.replay()

    def test_replay_restores_missing_or_corrupt_output_raw_without_network(self):
        self.source_page()
        self.replay()
        record=json.loads((self.out/'records/1.json').read_text(encoding='utf-8'))
        for damage in ('missing','corrupt'):
            with self.subTest(damage=damage):
                path=self.out/record['raw_path']
                if damage=='missing':path.unlink()
                else:path.write_bytes(b'not a gzip stream')
                with patch.object(gate,'parse_source_response',wraps=gate.parse_source_response) as parse:
                    self.replay()
                self.assertEqual(parse.call_count,1)
                self.assertEqual(gate.sha(gate.safe_raw(gate.RunInput(self.out),record)),record['raw_sha256'])

    def test_changed_raw_without_new_source_hash_excludes_stale_candidate(self):
        self.source_page()
        self.replay()
        (self.source/'raw/1.gz').write_bytes(gzip.compress(b'changed bytes'))
        self.replay()
        record=json.loads((self.out/'records/1.json').read_text(encoding='utf-8'))
        self.assertEqual(record['corpus_decision'],'EXCLUDE')
        self.assertIn('Raw hash mismatch',record['replay_error'])

    def review_source(self):
        archive=self.root/'fixtures.zip'
        create_run(archive)
        with zipfile.ZipFile(archive) as z:z.extractall(self.source)
        samples=gate.read_jsonl_bytes((self.source/'sample.jsonl').read_bytes())
        for index in range(65):
            identifier=9000000+index
            sample={'id':identifier,'url':f'https://www.120ask.com/question/{900000000+index}.htm'}
            samples.append(sample)
            body=small_page('A complete ordinary answer long enough for automated inclusion.')
            path=f'raw/{identifier}.gz'
            (self.source/path).write_bytes(gzip.compress(body,mtime=0))
            gate.write_json(self.source/'records'/f'{identifier}.json',dict(sample,http_status=200,
                raw_path=path,raw_sha256=gate.sha(body)))
        gate.jsonl(self.source/'sample.jsonl',samples)
        self.replay()
        gate.build_outputs(self.out)

    def test_manual_parser_error_and_review_cohort_survive_repeated_exclusions(self):
        self.review_source()
        sheet=self.out/'manual_review_sheet.csv'
        initial=csv_rows(sheet)
        original_keys={(r['source_id'],r['thread_id']) for r in initial}
        ordinary=[r for r in initial if int(r['source_id'])>=9000000 and r['corpus_decision']=='INCLUDE'][:2]
        labels=self.root/'reviewed.csv'
        for count,row in enumerate(ordinary,1):
            row.update(reviewer_decision='EXCLUDE',reviewer_notes='PARSER_ERROR: synthetic label',reviewed_at='2026-10-20T12:00:00+07:00')
            gate.save_csv(labels,initial,list(initial[0]))
            result=gate.build_outputs(self.out,manual_review_path=labels)
            rows=csv_rows(sheet)
            self.assertTrue(original_keys<={(r['source_id'],r['thread_id']) for r in rows})
            self.assertEqual(result['manual_reviewed'],count)
            self.assertEqual(result['readiness'],'NEEDS_PARSER_FIX')
        before={name:(self.out/name).read_bytes() for name in ('manual_review_sheet.csv','manual_review_cohort.json','summary.json')}
        gate.build_outputs(self.out,manual_review_path=labels)
        self.assertEqual(before,{name:(self.out/name).read_bytes() for name in before})

    def test_manual_unknown_thread_stale_hash_and_cohort_identity_rejected(self):
        self.review_source()
        rows=csv_rows(self.out/'manual_review_sheet.csv')
        subject=rows[0]
        subject.update(reviewer_decision='EXCLUDE',reviewer_notes='Synthetic test',reviewed_at='2026-10-20')
        labels=self.root/'labels.csv'
        original=dict(subject)
        for key,value,reason in [('thread_id','unknown-thread','Unknown manual'),('raw_sha256','stale','Stale manual')]:
            with self.subTest(key=key):
                subject.update(original)
                subject[key]=value
                gate.save_csv(labels,rows,list(rows[0]))
                with self.assertRaisesRegex(ValueError,reason):gate.build_outputs(self.out,manual_review_path=labels)
        path=self.out/'manual_review_cohort.json'
        cohort=json.loads(path.read_text(encoding='utf-8'))
        cohort['identity']['parser_sha256']='stale'
        gate.write_json(path,cohort)
        with self.assertRaisesRegex(ValueError,'cohort identity changed'):gate.build_outputs(self.out)

    def test_manual_include_cannot_bypass_audio_hard_blocker(self):
        self.review_source()
        rows=csv_rows(self.out/'manual_review_sheet.csv')
        subject=next(r for r in rows if 'AUDIO_ONLY' in r['decision_reasons'])
        subject.update(reviewer_decision='INCLUDE',reviewer_notes='Synthetic label',reviewed_at='2026-10-20')
        labels=self.root/'labels.csv'
        gate.save_csv(labels,rows,list(rows[0]))
        gate.build_outputs(self.out,manual_review_path=labels)
        row=next(r for r in csv_rows(self.out/'manual_review_sheet.csv')
                 if r['source_id']==subject['source_id'] and r['thread_id']==subject['thread_id'])
        self.assertEqual(row['corpus_decision'],'EXCLUDE')

    def test_aggregation_rejects_runtime_and_checkpoint_identity_mismatch(self):
        self.source_page()
        self.replay()
        manifest_path=self.out/'manifest.json'
        original=manifest_path.read_bytes()
        manifest=json.loads(original)
        manifest['parser_sha256']='old-parser'
        gate.write_json(manifest_path,manifest)
        with self.assertRaisesRegex(ValueError,'Aggregation runtime identity changed'):gate.build_outputs(self.out)
        manifest_path.write_bytes(original)
        record_path=self.out/'records/1.json'
        record=json.loads(record_path.read_text(encoding='utf-8'))
        record['policy_sha256']='old-policy'
        gate.write_json(record_path,record)
        with self.assertRaisesRegex(ValueError,'Checkpoint identity differs'):gate.build_outputs(self.out)

    def test_candidate_sidecar_keeps_reviewed_question_media_without_schema_change(self):
        self.source_page(question='Please interpret the report: <img src="/lab.jpg">')
        self.replay()
        gate.build_outputs(self.out)
        rows=csv_rows(self.out/'manual_review_sheet.csv')
        rows[0].update(reviewer_decision='INCLUDE',reviewer_notes='Synthetic explicit media review',reviewed_at='2026-10-20')
        labels=self.root/'labels.csv'
        gate.save_csv(labels,rows,list(rows[0]))
        gate.build_outputs(self.out,manual_review_path=labels)
        candidate=gate.read_jsonl_bytes((self.out/'corpus_candidates.jsonl').read_bytes())[0]
        self.assertEqual(candidate['question_attachment_urls'],['https://www.120ask.com/lab.jpg'])
        self.assertTrue(candidate['question_media'][0]['dom_locator'])
        self.assertEqual(pq.read_table(self.out/'corpus_candidates.parquet').column_names,list(gate.PRODUCTION_FIELDS))

    def test_aggregation_does_not_export_when_verified_raw_was_lost(self):
        self.source_page()
        self.replay()
        page=json.loads((self.out/'records/1.json').read_text(encoding='utf-8'))
        (self.out/page['raw_path']).unlink()
        with self.assertRaisesRegex(ValueError,'Aggregation raw evidence missing or corrupt'):gate.build_outputs(self.out)
        self.assertFalse((self.out/'corpus_candidates.jsonl').exists())

    def test_question_media_provenance_gate_and_audit(self):
        variants=[('<img src="/lab.jpg" alt="Lab report">',['https://www.120ask.com/lab.jpg']),
                  ('<img data-src="/lazy.jpg">',['https://www.120ask.com/lazy.jpg']),
                  ('<picture><source srcset="/small.jpg 1x, /large.jpg 2x"></picture>',
                   ['https://www.120ask.com/small.jpg','https://www.120ask.com/large.jpg']),
                  ('<video poster="/poster.jpg"><source src="/clip.mp4"></video>',
                   ['https://www.120ask.com/poster.jpg','https://www.120ask.com/clip.mp4']),
                  ('<img alt="">',[])]
        for media,urls in variants:
            for fallback in (False,True):
                with self.subTest(media=media,fallback=fallback):
                    body=small_page('A complete answer long enough to be included without media.',
                                    'Please interpret the attached report: '+media)
                    if fallback:
                        body=body.replace(b'<div id="d_msCon">',b'<div class="b_askbox"><div class="b_askcont">')
                        body=body.replace(b'</div><span>',b'</div></div><span>')
                    page=gate.parse_source_response(body,dict(id=1,url='https://www.120ask.com/question/123.htm',
                        access_status='VAO_DUOC',raw_path='raw/test.gz',raw_sha256=gate.sha(body),
                        parser_sha256='parser',policy_sha256='policy'))
                    self.assertEqual(page['question_attachment_urls'],urls)
                    self.assertTrue(all(item['dom_locator'] for item in page['question_media']))
                    self.assertIn('ask120_question_media_review',page['ask120_review_reasons'])
                    thread=gate.review_thread(page['ask120_threads'][0],page,gate.POLICY)
                    self.assertEqual(thread['corpus_decision'],'REVIEW')
                    self.assertIn('ESSENTIAL_MEDIA_REVIEW',thread['decision_reasons'])
                    ask120.audit(body,page['url'],page)
                    page['question_media']=[]
                    with self.assertRaisesRegex(ValueError,'question_media'):ask120.audit(body,page['url'],page)


class CrawlResumeFixTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.out=self.root/'output'
        self.support=self.out/'support'
        self.support.mkdir(parents=True)
        notebook=json.loads((ROOT/'notebooks/check_120ask_50.ipynb').read_text(encoding='utf-8'))
        pack=next(ast.literal_eval(node.value) for c in notebook['cells'] if c['cell_type']=='code'
            for node in ast.parse(''.join(c['source'])).body
            if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='PACK')
        for name,payload in pack['EMBEDDED_FILES'].items():
            (self.support/name).write_bytes(zlib.decompress(base64.b85decode(payload)))
        self.parquet=self.root/'source.parquet'
        self.limit=1
        pq.write_table(pa.Table.from_pylist([{'id':1,'url':'https://www.120ask.com/question/123.htm'}]),self.parquet)

    def crawl(self):
        return gate.crawl_new(self.parquet,self.out,limit=self.limit,support_dir=self.support)

    def initial_crawl(self,question='A real patient question with enough context.',status=200):
        response=requests.Response()
        response.status_code=status
        response._content=small_page('A complete answer with enough detail for this test case.',question)
        response._content_consumed=True
        response.headers['Content-Type']='text/html; charset=utf-8'
        with patch('requests.Session.get',return_value=response),patch('time.sleep'), \
             patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]):
            self.crawl()

    def test_crawl_resume_and_interrupted_fetch_do_not_send_http(self):
        self.initial_crawl()
        record=self.out/'records/1.json'
        before=record.read_bytes()
        with patch('requests.sessions.Session.request',side_effect=AssertionError('HTTP on resume')):
            self.crawl()
            self.assertEqual(record.read_bytes(),before)
            record.unlink()
            self.crawl()
            self.assertEqual(record.read_bytes(),before)

    def test_crawl_changed_fetch_metadata_source_and_missing_evidence_rejected(self):
        self.initial_crawl()
        path=self.out/'fetch_records/1.json'
        original=path.read_bytes()
        with patch('requests.sessions.Session.request',side_effect=AssertionError('HTTP on invalid resume')):
            for field,value in [('content_type','text/html; charset=gbk'),('raw_sha256','0'*64),('raw_path','raw/changed.gz'),('id',2)]:
                with self.subTest(field=field):
                    data=json.loads(original)
                    data[field]=value
                    gate.write_json(path,data)
                    with self.assertRaisesRegex(ValueError,'source evidence changed|source mapping changed'):self.crawl()
                    path.write_bytes(original)
            parsed=json.loads((self.out/'records/1.json').read_text(encoding='utf-8'))
            raw_path=self.out/parsed['raw_path']
            raw_before=raw_path.read_bytes()
            for damage in ('missing','corrupt'):
                if damage=='missing':raw_path.unlink()
                else:raw_path.write_bytes(b'invalid gzip')
                with self.assertRaisesRegex(ValueError,'raw evidence missing or corrupt'):self.crawl()
                raw_path.write_bytes(raw_before)
            path.unlink()
            with self.assertRaisesRegex(ValueError,'Fetch checkpoint missing'):self.crawl()
            path.write_bytes(original)
            pq.write_table(pa.Table.from_pylist([{'id':2,'url':'https://www.120ask.com/question/456.htm'}]),self.parquet)
            with self.assertRaisesRegex(ValueError,'Crawl source changed'):self.crawl()

    def test_crawl_question_media_is_reviewed(self):
        self.initial_crawl('Please interpret the report <img data-src="/lab.jpg">')
        page=json.loads((self.out/'records/1.json').read_text(encoding='utf-8'))
        self.assertEqual(page['corpus_decision'],'REVIEW')
        self.assertEqual(page['question_attachment_urls'],['https://www.120ask.com/lab.jpg'])

    def test_crawl_resume_keeps_stop_after_rate_limit(self):
        self.limit=2
        pq.write_table(pa.Table.from_pylist([
            {'id':1,'url':'https://www.120ask.com/question/123.htm'},
            {'id':2,'url':'https://www.120ask.com/question/456.htm'}]),self.parquet)
        self.initial_crawl(status=429)
        self.assertEqual(len(list((self.out/'records').glob('*.json'))),1)
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Must stay stopped')):
            self.crawl()
        self.assertEqual(len(list((self.out/'records').glob('*.json'))),1)


if __name__=='__main__':unittest.main()
