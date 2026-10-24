"""F4: separate DOM presence from title/body context without rejecting short topics."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import ask120
import ask120_gate as gate
from test_ask120_corpus_gate import small_page

FOLDER=ROOT/'tests/fixtures/120ask_f4'
MANIFEST=json.loads((FOLDER/'manifest.json').read_text(encoding='utf-8'))
URL='https://www.120ask.com/question/123.htm'
ANSWER='患者可能患有高血压，但此答案绝不能用来为缺失的患者问题补充病情和诊断。'


def make_page(title,question,answer=ANSWER):
    body=small_page(answer,question).decode().replace('<h1 id="d_askH1">患者问题</h1>',f'<h1 id="d_askH1">{title}</h1>').encode()
    page=gate.parse_source_response(body,dict(id=1,url=URL,raw_sha256=gate.sha(body),raw_path='raw/1.gz',
        parser_sha256=gate.sha(Path(gate.PARSER.__file__).read_bytes()),policy_sha256=gate.policy_hash(gate.POLICY),
        http_status=200,access_status='VAO_DUOC'))
    return body,page


class QuestionContextTests(unittest.TestCase):
    def test_real_cases_and_all_16_original_short_questions(self):
        self.assertEqual(sum(c['initial_short_cohort'] for c in MANIFEST['cases']),16)
        for case in MANIFEST['cases']:
            with self.subTest(source_id=case['source_id']):
                body=gzip.decompress((FOLDER/case['raw_file']).read_bytes())
                self.assertEqual(gate.sha(body),case['raw_sha256'])
                doc=ask120.extract(body,case['url'],case['content_type'])
                self.assertEqual(doc['question_context_status'],case['expected_status'])
                self.assertEqual(bool(doc['question_context']['review_reasons']),case['expected_F4_review'])
                self.assertEqual(doc['title'],case['expected_title'])
                self.assertEqual(doc['ask120_question'],case['expected_body'])

    def test_short_named_topics_are_kept_without_a_character_cutoff(self):
        for topic in ('什么是血性恶露','精神分裂能治愈吗','皮炎','痒','HIV阳性','TIA怎样治疗',
                      'BRCA1 < 2，EGFR阴性','尿频','头痛9年，没治过，能治好吗'):
            with self.subTest(topic=topic):
                _,page=make_page('请教专业人士',topic)
                self.assertEqual(page['question_context_status'],'context_present')
                self.assertEqual(page['question_context_source'],'body')
                self.assertEqual(gate.review_thread(page['ask120_threads'][0],page,gate.POLICY)['corpus_decision'],'INCLUDE')

    def test_generic_questions_durations_and_demographics_are_reviewed_even_if_long(self):
        for question in ('怎么治疗啊!','9年 没治过 能治好吗','谢谢','男25岁','今年','想治疗',
                         '请问已经很多年了，一直没治疗，能治好吗？',
                         '请问专家，怎么治疗啊，谢谢！'*100):
            with self.subTest(question=question[:45]):
                _,page=make_page('请问怎么治疗',question)
                self.assertTrue(page['question_valid'])
                self.assertIn(page['question_context_status'],('insufficient','unresolved'))
                self.assertEqual(gate.review_thread(page['ask120_threads'][0],page,gate.POLICY)['corpus_decision'],'REVIEW')

    def test_title_only_is_explicit_and_does_not_replace_the_body(self):
        for question in ('谢谢','时间了.','9年\n没治过\n能治好吗'):
            _,page=make_page('高血脂患者血脂下降以后还需要服药吗？',question)
            self.assertEqual(page['question_context_status'],'title_only')
            self.assertEqual(page['question_context_source'],'title')
            self.assertEqual(page['ask120_question'],question)
            thread=gate.review_thread(page['ask120_threads'][0],page,gate.POLICY)
            self.assertIn('QUESTION_TITLE_ONLY_REVIEW',thread['decision_reasons'])
            self.assertEqual(thread['corpus_decision'],'REVIEW')

    def test_answer_does_not_supply_context(self):
        _,first=make_page('请问','怎么治疗啊!',ANSWER)
        _,second=make_page('请问','怎么治疗啊!','本回答谈到精神分裂症与皮炎，这不能被推定为患者提出的问题。')
        self.assertEqual(first['question_context'],second['question_context'])
        self.assertEqual(first['question_context_status'],'insufficient')

    def test_unresolved_reference_is_held_but_named_exposure_is_preserved(self):
        doc=ask120.question_context('请问','别人就是被我吃下去了会不会感染我说的这些医生')
        self.assertEqual(doc['status'],'unresolved')
        self.assertEqual(doc['review_reasons'],['QUESTION_CONTEXT_UNRESOLVED_REVIEW'])
        doc=ask120.question_context('请问','吃到口水会不会感染艾滋病？')
        self.assertEqual(doc['status'],'context_present')
        doc=ask120.question_context('请帮帮我','报告')
        self.assertEqual(doc['status'],'unresolved')

    def test_referenced_report_requires_details_but_definitions_and_actual_findings_are_kept(self):
        for title,body in [('请问我叔叔的病理','医生给他开这样的药治疗效果可以吗？请问我叔叔的病理。'),
                           ('我的病理','我想了解我的病理，请医生帮忙看看报告')]:
            context=ask120.question_context(title,body)
            self.assertEqual(context['status'],'unresolved')
        for body in ('请问病理是什么？','什么是病理？','请帮我看报告：谷丙转氨酶91，HBeAg阴性。',
                     '我叔叔病理报告是腺癌，正在服用阿司匹林。'):
            self.assertEqual(ask120.question_context('请问',body)['status'],'context_present')

    def test_context_evidence_has_exact_title_and_body_offsets_and_hashes(self):
        body,page=make_page('高血脂患者怎么治疗','9年\n没治过\n能治好吗')
        tree,_,_=ask120._tree(body)
        for field in ('title','body'):
            proof=page['question_context'][field]
            self.assertEqual(proof['text_sha256'],gate.sha(proof['text']))
            self.assertEqual(len(tree.xpath(proof['dom_locator'])),1)
            for item in proof['generic_evidence']+proof['residual_spans']:
                self.assertEqual(item['text'],proof['text'][item['char_start']:item['char_end']])
        self.assertEqual(page['question_context']['body']['text'],page['ask120_question'])

    def test_dom_invalid_stays_excluded_even_if_title_has_context(self):
        _,page=make_page('皮炎怎么治','')
        self.assertFalse(page['question_valid'])
        thread=gate.review_thread(page['ask120_threads'][0],page,gate.POLICY)
        self.assertEqual(thread['corpus_decision'],'EXCLUDE')
        self.assertIn('QUESTION_MISSING_OR_AMBIGUOUS',thread['decision_reasons'])

    def test_context_applies_to_all_threads_and_audio_stays_excluded(self):
        body,page=make_page('请问','怎么治疗')
        first=page['ask120_threads'][0]
        second=deepcopy(first);second['thread_id']='second';second['turns'][0]['reply_id']='reply456'
        for thread in (first,second):
            self.assertEqual(gate.review_thread(thread,page,gate.POLICY)['corpus_decision'],'REVIEW')
        audio=deepcopy(first);audio['turns'][0].update(text='',answer_type='audio')
        decision=gate.review_thread(audio,page,gate.POLICY)
        self.assertEqual(decision['corpus_decision'],'EXCLUDE')
        self.assertIn('AUDIO_ONLY',decision['decision_reasons'])

    def test_candidate_preserves_context_metadata_and_raw_audit_detects_tampering(self):
        body,page=make_page('皮炎','皮炎')
        thread=gate.review_thread(page['ask120_threads'][0],page,gate.POLICY)
        page['thread_decisions']=[thread]
        candidate=gate.build_candidate_document(page,[thread])
        self.assertEqual(candidate['question_context_status'],'context_present')
        self.assertEqual(candidate['question_context_source'],'both')
        self.assertEqual(candidate['question_context'],page['question_context'])
        self.assertNotIn('question_context',gate.PRODUCTION_FIELDS)
        ask120.audit(body,URL,page)
        page['question_context']['body']['text_sha256']='bad'
        with self.assertRaisesRegex(ValueError,'question_context'):
            ask120.audit(body,URL,page)

    def test_manual_include_and_modified_checkpoint_cannot_bypass_context_review(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            directory=Path(directory);source=directory/'source';out=directory/'output'
            (source/'raw').mkdir(parents=True)
            body,_=make_page('皮炎怎么治','谢谢')
            (source/'raw/1.gz').write_bytes(gzip.compress(body,mtime=0))
            gate.write_json(source/'manifest.json',{'fixture':True})
            gate.jsonl(source/'sample.jsonl',[dict(id=1,url=URL)])
            gate.write_json(source/'records/1.json',dict(id=1,url=URL,http_status=200,status='extracted',
                content_type='text/html; charset=utf-8',raw_path='raw/1.gz',raw_sha256=gate.sha(body)))
            with patch('requests.sessions.Session.request',side_effect=AssertionError('offline')):
                gate.replay(source,out)
            saved=json.loads((out/'records/1.json').read_text(encoding='utf-8'))
            thread=saved['thread_decisions'][0]
            label=dict(source_id=1,thread_id=thread['thread_id'],reviewer_decision='INCLUDE',
                reviewer_notes='synthetic policy test, not human approval',reviewed_at='2026-10-23T00:00:00Z',
                **{k:saved[k] for k in ('raw_sha256','parser_sha256','policy_sha256')})
            gate.jsonl(directory/'manual.jsonl',[label])
            result=gate.build_outputs(out,manual_review_path=directory/'manual.jsonl')
            self.assertEqual(result['candidate_documents'],0)
            actual=gate.read_jsonl_bytes((out/'qa_threads_all.jsonl').read_bytes())[0]
            self.assertIn('manual_override_blocked',actual)
            saved['question_context']={};saved['question_context_status']='context_present'
            thread['corpus_decision']='INCLUDE';thread['decision_reasons']=[]
            gate.write_json(out/'records/1.json',saved)
            result=gate.build_outputs(out)
            self.assertEqual(result['candidate_invariant_violations'],[1])
            self.assertEqual(result['candidate_documents'],0)


if __name__=='__main__':unittest.main()
