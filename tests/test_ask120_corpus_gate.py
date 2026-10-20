"""Real-run regressions and behavioral coverage for the v3 parser/admission gate."""
import ast
import base64
import csv
import gzip
import hashlib
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

FIXTURES=ROOT/'tests/fixtures/120ask_v3'
MANIFEST=json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8'))


def raw(qid):
    return gzip.decompress((FIXTURES/(qid+'.html.gz')).read_bytes())


def small_page(main,question='这是一个真实且完整的患者问题，包含症状和病情。'):
    return ('<html><meta charset="utf-8"><h1 id="d_askH1">患者问题</h1>'
            f'<div id="d_msCon">健康咨询描述：{question}</div><span>1人回复</span><div class="b_answerbox">'
            '<div class="b_answerli"><div class="b_answertl"><span class="b_sp1"><a>医生甲</a></span></div>'
            f'<div class="b_anscont_cont"><p id="reply123">{main}</p></div></div></div></html>').encode()


def create_run(path,qids=None,missing=False,bad_hash=False):
    qids=list(qids or MANIFEST)
    samples=[{'id':MANIFEST[q]['id'],'url':MANIFEST[q]['url']} for q in qids]
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('manifest.json',json.dumps({'snapshot_sha256':{'ask120_snapshot.py':'old-parser-hash'}}))
        z.writestr('sample.jsonl',''.join(json.dumps(s)+'\n' for s in samples))
        for q in qids:
            r=dict(MANIFEST[q],http_status=200,status='extracted',quality_status='accepted',text='baseline',
                   raw_path='raw/'+q+'.gz')
            if bad_hash:r['raw_sha256']='0'*64
            z.writestr(f"records/{r['id']}.json",json.dumps(r))
            if not missing:z.writestr(r['raw_path'],gzip.compress(raw(q),mtime=0))
        # This is input data, never an importable runtime module.
        z.writestr('support/ask120_snapshot.py','raise RuntimeError("input code executed")')
    return samples


class ParserV3Tests(unittest.TestCase):
    def test_audio_real_word_mixed_and_inequalities(self):
        text='这是关于 audio 检查的真实回答。BRCA1 < 2 且数值 > 1，建议结合病史进行复查。'
        doc=ask120.extract(small_page(text),'https://www.120ask.com/question/123.htm')
        turn=doc['ask120_threads'][0]['turns'][0]
        self.assertEqual(turn['answer_type'],'text')
        self.assertIn('BRCA1 < 2',turn['text'])
        self.assertIn('> 1',turn['text'])
        doc=ask120.extract(small_page('完整的文字回答应保留原始内容，不可以因为附有语音而把文字内容也排除。'
            '<audio><source src="/voice.mp3">您的浏览器不支持 audio 元素。</audio>'),
            'https://www.120ask.com/question/123.htm')
        turn=doc['ask120_threads'][0]['turns'][0]
        self.assertEqual(turn['answer_type'],'mixed')
        self.assertEqual(turn['media_urls'],['https://www.120ask.com/voice.mp3'])
        self.assertNotIn('您的浏览器',turn['text'])
        self.assertIn('您的浏览器',turn['raw_text'])

    def test_thread_gate_preserves_good_text_beside_audio(self):
        good='这是足够完整的文字回答，包含患者需要的上下文，并且保留原始来源的段落与语义。'
        body=small_page(good).decode()
        extra=('<div class="b_answerli"><div class="b_answertl"><span class="b_sp1"><a>医生乙</a></span></div>'
               '<div class="b_anscont_cont"><p id="reply456"><audio src="/other.mp3">'
               '您的浏览器不支持 audio 元素。</audio></p></div></div>')
        body=body.replace('1人回复','2人回复').replace(
            '</div></div></div></html>','</div></div>'+extra+'</div></html>').encode()
        page=gate.parse_source_response(body,{'id':42,'url':'https://www.120ask.com/question/123.htm',
            'raw_sha256':gate.sha(body),'raw_path':'raw/test.gz','parser_sha256':'current-parser',
            'policy_sha256':'current-policy','access_status':'VAO_DUOC'})
        threads=[gate.review_thread(t,page,gate.POLICY) for t in page['ask120_threads']]
        self.assertEqual([t['corpus_decision'] for t in threads],['INCLUDE','EXCLUDE'])
        self.assertEqual(gate.decide_page(threads,page)['corpus_decision'],'INCLUDE_PARTIAL')
        page['thread_decisions']=threads
        doc=gate.build_candidate_document(page,[threads[0]])
        self.assertEqual(doc['id'],42)
        self.assertIn(good,doc['text'])
        self.assertNotIn('audio',doc['text'])
        self.assertNotIn('reply456',doc['included_thread_ids'])

    def test_same_identity_dom_copy_is_distinct_from_equal_different_replies(self):
        good='这是一段完整回答，内容必须保持，并且不能仅因为文字相同就静默删除来源。'
        body=small_page(good).decode()
        extra=('<div class="b_answerli"><div class="b_anscont_cont">'
               f'<p id="reply123">{good}</p></div></div>')
        body=body.replace('1人回复','2人回复').replace(
            '</div></div></div></html>','</div></div>'+extra+'</div></html>').encode()
        doc=ask120.extract(body,'https://www.120ask.com/question/123.htm')
        self.assertEqual(doc['main_answer_count'],2)
        self.assertEqual(doc['ask120_qc']['duplicates_by_role'][0]['kind'],'duplicate_dom_representation')
        self.assertEqual(doc['ask120_qc']['duplicate_dom_representation'][0]['action'],'preserved_for_review')

    def test_real_audio_ids_and_card_count_semantics(self):
        doc=ask120.extract(raw('1015858'),MANIFEST['1015858']['final_url'])
        self.assertEqual(doc['usable_text_main_answers'],0)
        self.assertEqual(doc['audio_main_answers'],2)
        self.assertFalse(ask120.AUDIO_FALLBACK.search(doc['text']))
        doc=ask120.extract(raw('3202910'),MANIFEST['3202910']['final_url'])
        mains=[t['turns'][0] for t in doc['ask120_threads']]
        self.assertTrue({'reply500933','reply505382'}<={t['reply_id'] for t in mains})
        self.assertEqual(doc['ask120_qc']['published_count_semantics'],'card_count_matches_template')
        self.assertGreater(doc['source_reply_count'],doc['source_card_count'])
        self.assertFalse(any(x['kind']=='duplicate_main_answer' and
            x['text_sha256']==ask120.sha(ask120.compact('您的浏览器不支持 audio 元素。'))
            for x in doc['ask120_qc']['duplicates_by_role']))

    def test_real_legacy_paragraphs_and_original_hashes(self):
        for qid in ('3530545','3256774','3434509'):
            doc=ask120.extract(raw(qid),MANIFEST[qid]['final_url'])
            self.assertFalse(ask120.LEGACY_MARKUP.search(doc['text']))
            turns=[turn for t in doc['ask120_threads'] for turn in t['turns']]
            self.assertTrue(any(t['normalization_actions'] for t in turns))
            for t in turns:self.assertEqual(t['raw_text_sha256'],ask120.sha(t['raw_text']))
        self.assertEqual(len(doc['ask120_threads']),1)
        self.assertIn('\n',doc['ask120_threads'][0]['turns'][0]['text'])

    def test_patient_repeats_and_13_owned_followups_survive(self):
        for qid,count in (('13753474',13),('77939582',10)):
            doc=ask120.extract(raw(qid),MANIFEST[qid]['final_url'])
            self.assertEqual(doc['followup_count'],count)
            self.assertFalse(doc['ask120_qc']['unresolved_blocks'])
            self.assertTrue(any(g['kind']=='repeated_patient_followup' for g in doc['ask120_qc']['duplicates_by_role']))
            for thread in doc['ask120_threads']:
                self.assertEqual([t['turn_index'] for t in thread['turns']],list(range(1,len(thread['turns'])+1)))
                self.assertTrue(all(t['reply_id']==thread['reply_id'] for t in thread['turns']))

    def test_markup_normalization_is_bounded_and_not_greedy(self):
        value='&lt;P&gt;BRCA1 < 2，数值 > 1。&lt;BR&gt;下一段&lt;/P&gt;'
        text,actions=ask120.normalize_legacy_markup(value)
        self.assertIn('BRCA1 < 2',text)
        self.assertIn('\n下一段',text)
        self.assertLessEqual(len(actions),2)
        text,_=ask120.normalize_legacy_markup('符号 <GENE> 不应被删除')
        self.assertIn('<GENE>',text)


class ReplayGateTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.input=self.root/'input.zip'
        self.out=self.root/'replayed'

    def replay(self,**options):
        with patch('requests.Session.request',side_effect=AssertionError('Replay sent network request')), \
             patch.object(gate.pq,'ParquetFile',side_effect=AssertionError('Replay reads corpus')):
            return gate.replay(self.input,self.out,**options)

    def test_full_real_regressions_candidate_mapping_and_idempotent_outputs(self):
        samples=create_run(self.input)
        self.replay()
        summary=gate.build_outputs(self.out)
        self.assertTrue(all(r['passed'] for r in summary['regression_checks'].values()),summary['regression_checks'])
        self.assertEqual(summary['candidate_audio_fallbacks'],0)
        self.assertEqual(summary['candidate_legacy_markup'],0)
        self.assertEqual(summary['manual_reviewed'],0)
        self.assertNotEqual(summary['readiness'],'READY_FOR_FILTERED_CORPUS')
        docs=[json.loads(line) for line in (self.out/'corpus_candidates.jsonl').read_text(encoding='utf-8').splitlines()]
        expected={s['id'] for s in samples}
        self.assertTrue(docs)
        self.assertTrue({d['id'] for d in docs}<=expected)
        pages={json.loads(line)['id']:json.loads(line) for line in (self.out/'results_reparsed.jsonl').read_text(encoding='utf-8').splitlines()}
        for doc in docs:
            included=[t for t in pages[doc['id']]['thread_decisions'] if t['corpus_decision']=='INCLUDE']
            self.assertEqual(doc['included_thread_ids'],[t['thread_id'] for t in included])
            for span in doc['source_spans']:
                self.assertIn('：\n',doc['text'][span['char_start']:span['char_end']])
        self.assertEqual(pq.read_table(self.out/'corpus_candidates.parquet').column_names,list(gate.PRODUCTION_FIELDS))
        before={name:(self.out/name).read_bytes() for name in ('report.md','summary.json','qa_threads_all.jsonl',
                'corpus_candidates.jsonl','corpus_candidates.parquet','manual_review_sheet.csv')}
        gate.build_outputs(self.out)
        self.assertEqual(before,{name:(self.out/name).read_bytes() for name in before})
        with patch.object(gate,'parse_source_response',side_effect=AssertionError('already parsed')):
            self.replay()

    def test_missing_raw_and_bad_hash_exclude_without_network(self):
        for missing,bad in ((True,False),(False,True)):
            with self.subTest(missing=missing,bad=bad):
                self.out=self.root/f'case_{missing}_{bad}'
                create_run(self.input,['1015858'],missing=missing,bad_hash=bad)
                self.replay()
                summary=gate.build_outputs(self.out)
                self.assertEqual(summary['raw_or_parse_errors'],1)
                self.assertEqual(summary['candidate_documents'],0)
                table=pq.read_table(self.out/'corpus_candidates.parquet')
                self.assertEqual(table.num_rows,0)
                self.assertEqual(table.schema,gate.CANDIDATE_SCHEMA)

    def test_empty_candidate_schema_and_version_mismatch(self):
        create_run(self.input)
        self.replay(policy={'min_answer_chars':100000})
        summary=gate.build_outputs(self.out)
        self.assertEqual(summary['candidate_documents'],0)
        self.assertTrue((self.out/'corpus_candidates.jsonl').is_file())
        with self.assertRaisesRegex(ValueError,'identity changed'):
            self.replay(policy={'min_answer_chars':20})

    def test_path_traversal_and_ambiguous_replay_inputs(self):
        create_run(self.input,['1015858'])
        with zipfile.ZipFile(self.input,'a') as z:z.writestr('../escape.py','raise RuntimeError()')
        with self.assertRaisesRegex(ValueError,'Unsafe input path'):gate.RunInput(self.input)
        with self.assertRaisesRegex(ValueError,'Choose INPUT'):gate.locate_input(self.input,self.root)

    def test_question_only_labels_are_not_corpus(self):
        for qid in ('378338','257785'):
            self.out=self.root/qid;create_run(self.input,[qid]);self.replay()
            summary=gate.build_outputs(self.out)
            self.assertEqual(summary['candidate_documents'],0)
            self.assertEqual(summary['page_decisions'],{'EXCLUDE':1})

    def test_source_claim_requires_explicit_provenance_bound_review(self):
        create_run(self.input)
        self.replay()
        first=gate.build_outputs(self.out)
        with (self.out/'manual_review_sheet.csv').open(encoding='utf-8-sig',newline='') as stream:
            rows=list(csv.DictReader(stream));fields=list(rows[0])
        row=next(r for r in rows if 'SOURCE_CLAIM_REVIEW' in r['decision_reasons'] and r['corpus_decision']=='REVIEW')
        row.update(reviewer_decision='INCLUDE',reviewer_notes='Source claim reviewed; extraction checked against raw.',
                   reviewed_at='2026-10-18T12:00:00+07:00')
        path=self.root/'reviewed.csv'
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        after=gate.build_outputs(self.out,manual_review_path=path)
        self.assertGreater(after['manual_reviewed'],0)
        self.assertGreater(after['candidate_threads'],first['candidate_threads'])
        self.assertNotEqual(after['readiness'],'READY_FOR_FILTERED_CORPUS')
        row['raw_sha256']='stale'
        with path.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
        with self.assertRaisesRegex(ValueError,'Stale manual'):
            gate.build_outputs(self.out,manual_review_path=path)

    def test_production_adapter_uses_existing_document_fields(self):
        sys.path.insert(0,str(ROOT/'src'))
        from vibiomir.common.schema import DOCUMENT_FIELDS
        self.assertEqual(gate.PRODUCTION_FIELDS,DOCUMENT_FIELDS)

    def test_crawl_new_excludes_canonical_history_preserves_ids_and_resumes(self):
        nb=json.loads((ROOT/'notebooks/check_120ask_50.ipynb').read_text(encoding='utf-8'))
        for cell in nb['cells']:
            if cell['cell_type']!='code':continue
            for n in ast.parse(''.join(cell['source'])).body:
                if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='PACK':
                    pack=ast.literal_eval(n.value)
        support=self.out/'support';support.mkdir(parents=True)
        for name,payload in pack['EMBEDDED_FILES'].items():
            (support/name).write_bytes(zlib.decompress(base64.b85decode(payload)))
        source=self.root/'source.parquet'
        pq.write_table(pa.Table.from_pylist([
            {'id':1000,'url':'http://www.120ask.com/question/1015858.htm'},
            {'id':2000,'url':'https://120ask.com/question/1015858.htm'},
            {'id':3000,'url':'https://www.120ask.com/question/3434509.htm'},
            {'id':4000,'url':'https://www.120ask.com/question/3256774.htm'}]),source)
        history=self.root/'history.jsonl'
        gate.jsonl(history,[{'id':1000,'url':'https://120ask.com/question/1015858.htm'}])
        def response(url,**kwargs):
            qid=url.split('/')[-1].split('.')[0]
            r=requests.Response();r.status_code=200;r._content=raw(qid);r._content_consumed=True
            r.headers['Content-Type']='text/html; charset=utf-8'
            return r
        with patch('requests.Session.get',side_effect=response) as get,patch('time.sleep'), \
             patch('socket.getaddrinfo',return_value=[(2,1,6,'',('93.184.216.34',443))]):
            samples=gate.crawl_new(source,self.out,limit=2,support_dir=support,history_paths=[history])
        self.assertEqual(get.call_count,2)
        self.assertEqual({s['id'] for s in samples},{3000,4000})
        self.assertEqual(json.loads((self.out/'manifest.json').read_text())['excluded_history'],1)
        with patch('requests.Session.get',side_effect=AssertionError('must not re-fetch completed URLs')):
            resumed=gate.crawl_new(source,self.out,limit=2,support_dir=support,history_paths=[history])
        self.assertEqual(samples,resumed)
        summary=gate.build_outputs(self.out)
        self.assertEqual(summary['raw_or_parse_errors'],0)

    def test_snapshot_matches_current_source(self):
        nb=json.loads((ROOT/'notebooks/check_120ask_50.ipynb').read_text(encoding='utf-8'))
        import nbformat
        nbformat.validate(nb)
        for c in nb['cells']:
            if c['cell_type']!='code':continue
            source=''.join(c['source']);compile(source,'cell','exec')
            for n in ast.parse(source).body:
                if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='PACK':
                    pack=ast.literal_eval(n.value)
        body=zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['ask120_snapshot.py']))
        self.assertEqual(body,(ROOT/'scripts/ask120.py').read_bytes())
        self.assertEqual(hashlib.sha256(body).hexdigest(),pack['EMBEDDED_SHA256']['ask120_snapshot.py'])
        gate_body=zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES']['ask120_gate.py']))
        self.assertEqual(gate_body,(ROOT/'scripts/ask120_gate.py').read_bytes())
        for name in ('ask120_experiments.py','ask120_experiment_baseline.json'):
            body=zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES'][name]))
            self.assertEqual(body,(ROOT/'scripts'/name).read_bytes())
            self.assertEqual(hashlib.sha256(body).hexdigest(),pack['EMBEDDED_SHA256'][name])


if __name__=='__main__':unittest.main()
