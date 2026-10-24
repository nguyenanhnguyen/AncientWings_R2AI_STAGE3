"""F5: normalize only proven question artifacts, preserve content and provenance."""
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

FIXTURE=ROOT/'tests/fixtures/120ask_f5'
MANIFEST=json.loads((FIXTURE/'manifest.json').read_text(encoding='utf-8'))
URL='https://www.120ask.com/question/123.htm'
ANSWER='这是足够完整的文字回答，包含需要的上下文，并保留来源内容与句子顺序。'


def page(body):
    return gate.parse_source_response(body,dict(id=1,url=URL,raw_path='raw/1.gz',raw_sha256=gate.sha(body),
        parser_sha256=gate.sha(Path(gate.PARSER.__file__).read_bytes()),
        policy_sha256=gate.policy_hash(gate.POLICY),http_status=200,access_status='VAO_DUOC'))


class QuestionNormalizationTests(unittest.TestCase):
    def assert_trace(self,doc,body):
        proof=doc['question_provenance']
        current=proof['raw_text']
        self.assertEqual(gate.sha(current),proof['raw_text_sha256'])
        self.assertEqual(gate.sha(proof['source_html']),proof['source_html_sha256'])
        tree,_,_=ask120._tree(body)
        self.assertEqual(len(tree.xpath(proof['dom_locator'])),1)
        self.assertEqual(proof['source_html'],ask120.html.tostring(tree.xpath(proof['dom_locator'])[0],encoding='unicode',with_tail=False))
        for action in proof['actions']:
            self.assertEqual(gate.sha(current),action['before_sha256'])
            stop=0
            for span in action['spans']:
                a,b=span['char_start'],span['char_end']
                self.assertTrue(stop<=a<=b<=len(current))
                self.assertEqual(current[a:b],span['text'])
                stop=b
            for span in reversed(action['spans']):
                current=current[:span['char_start']]+span['replacement']+current[span['char_end']:]
            self.assertEqual(gate.sha(current),action['after_sha256'])
            for key,value in action['evidence'].items():
                if key.endswith('dom_locator'):
                    self.assertEqual(len(tree.xpath(value)),1)
        self.assertEqual(current,doc['ask120_question'])
        self.assertEqual(gate.sha(current),proof['clean_text_sha256'])

    def test_all_51_real_pages_preserve_content_and_exact_trace(self):
        self.assertEqual(sum(c['initial_candidate'] for c in MANIFEST['cases'] if c['expected_rule'].endswith('br_fragment_v1')),31)
        for case in MANIFEST['cases']:
            with self.subTest(source_id=case['source_id']):
                body=gzip.decompress((FIXTURE/case['raw_file']).read_bytes())
                self.assertEqual(gate.sha(body),case['raw_sha256'])
                doc=ask120.extract(body,case['url'],case['content_type'])
                self.assertEqual(ask120.compact(doc['ask120_question']),case['expected_compact'])
                self.assertEqual(doc['ask120_question_raw'],case['legacy_question_raw'])
                self.assertFalse(doc['question_qc']['review_reasons'])
                self.assertIn(case['expected_rule'],[a['rule_id'] for a in doc['question_provenance']['actions']])
                self.assert_trace(doc,body)

    def test_true_br_and_paragraphs_survive_as_line_breaks(self):
        body=small_page(ANSWER,'第一段病情。<br>第二段检查。<p>第三段补充。</p>')
        doc=ask120.extract(body,URL)
        self.assertEqual(doc['ask120_question'],'第一段病情。\n第二段检查。\n第三段补充。')
        self.assert_trace(doc,body)

    def test_bounded_escaped_formatting_does_not_decode_unrelated_entities(self):
        body=small_page(ANSWER,'&amp;lt;P&amp;gt;BRCA1 &lt; 2 且数值 &gt; 1。&amp;lt;BR&amp;gt;'
            '符号 &amp;lt;GENE&amp;gt; 和 A&amp;amp;B 保留。&amp;lt;/P&amp;gt;')
        doc=ask120.extract(body,URL)
        self.assertEqual(doc['ask120_question'],'BRCA1 < 2 且数值 > 1。\n符号 &lt;GENE&gt; 和 A&amp;B 保留。')
        self.assertFalse(doc['question_qc']['review_reasons'])
        self.assert_trace(doc,body)

    def test_genes_inequalities_and_patient_complaint_are_not_removed_or_held(self):
        for question in ('BRCA1 < 2，BRCA2 > 1，EGFR阴性，需要复查吗？',
                         '符号 &lt;GENE&gt; 和数值 2 &lt; 3，5 &gt; 4 应该保留。',
                         '我想投诉医生，报告中的评价(0)是什么意思？',
                         '网页写着“点击查看大图”，我无法上传自己的检查图片。',
                         '我看到了“| 投诉 | 评价(0)”这几个字。',
                         '检查报告提到健康咨询描述：这些文字，请问如何理解？'):
            with self.subTest(question=question):
                doc=page(small_page(ANSWER,question))
                self.assertFalse(doc['question_qc']['review_reasons'])
                self.assertEqual(gate.review_thread(doc['ask120_threads'][0],doc,gate.POLICY)['corpus_decision'],'INCLUDE')
                self.assertNotIn('ask120_ui_marker_suspect',doc['ask120_review_reasons'])
                self.assertIn('投诉',doc['ask120_question']) if '投诉' in question else None

    def test_unknown_br_and_footer_stay_in_source_and_force_review(self):
        for question,reason in [('BR&gt;病情说明。','QUESTION_MARKUP_REVIEW'),
                                ('患者描述。<br>| 投诉 | 评价(0','QUESTION_UI_CONTAMINATION_REVIEW'),
                                ('患者描述。<br>医生在线免费咨询','QUESTION_UI_CONTAMINATION_REVIEW')]:
            with self.subTest(question=question):
                doc=page(small_page(ANSWER,question))
                self.assertIn(reason,doc['question_qc']['review_reasons'])
                decision=gate.review_thread(doc['ask120_threads'][0],doc,gate.POLICY)
                self.assertEqual(decision['corpus_decision'],'REVIEW')
                self.assertIn(reason,decision['decision_reasons'])
                self.assertNotIn('question_leading_br_fragment_v1',[a['rule_id'] for a in doc['question_provenance']['actions']])

    def test_only_proven_terminal_footer_is_removed(self):
        good='患者描述希望保留，我想投诉医院，应该怎么办？'
        question='<p class="crazy_new"><span>健康咨询描述：</span>'+good+'<br><br>| 投诉 | 评价(0</p>'
        body=small_page(ANSWER,question)
        doc=page(body)
        self.assertEqual(doc['ask120_question'],good)
        self.assertFalse(doc['question_qc']['review_reasons'])
        self.assert_trace(doc,body)
        self.assertEqual(gate.review_thread(doc['ask120_threads'][0],doc,gate.POLICY)['corpus_decision'],'INCLUDE')

    def test_header_in_later_paragraph_does_not_authorize_removing_an_unowned_prefix(self):
        question=('BR&gt;这是患者引用的原始字符。'
            '<p class="crazy_new"><span>健康咨询描述：</span>BR&gt;另一个段落。</p>')
        doc=page(small_page(ANSWER,question))
        self.assertTrue(doc['ask120_question'].startswith('BR>这是患者引用的原始字符。'))
        self.assertNotIn('question_leading_br_fragment_v1',[a['rule_id'] for a in doc['question_provenance']['actions']])
        self.assertIn('QUESTION_MARKUP_REVIEW',doc['question_qc']['review_reasons'])

    def test_question_flags_apply_to_every_good_thread_on_the_page(self):
        body=small_page(ANSWER,'BR&gt;患者问题').decode()
        card=body[body.index('<div class="b_answerli">'):body.rindex('</div></html>')]
        body=body.replace('1人回复','2人回复').replace('</div></html>',card.replace('reply123','reply456')+'</div></html>').encode()
        doc=page(body)
        self.assertEqual(len(doc['ask120_threads']),2)
        decisions=[gate.review_thread(t,doc,gate.POLICY) for t in doc['ask120_threads']]
        self.assertTrue(all(t['corpus_decision']=='REVIEW' and 'QUESTION_MARKUP_REVIEW' in t['decision_reasons'] for t in decisions))

    def test_candidate_keeps_question_evidence_without_changing_production_columns(self):
        doc=page(small_page(ANSWER,'第一段。<br>第二段。'))
        thread=gate.review_thread(doc['ask120_threads'][0],doc,gate.POLICY)
        doc['thread_decisions']=[thread]
        candidate=gate.build_candidate_document(doc,[thread])
        span=candidate['question_source_span']
        self.assertEqual(candidate['text'][span['char_start']:span['char_end']],doc['ask120_question'])
        self.assertEqual(candidate['question_provenance'],doc['question_provenance'])
        self.assertNotIn('question_provenance',gate.PRODUCTION_FIELDS)
        doc['title']=''
        candidate=gate.build_candidate_document(doc,[thread])
        span=candidate['question_source_span']
        self.assertEqual(candidate['text'][span['char_start']:span['char_end']],doc['ask120_question'])

    def test_raw_audit_rejects_changed_question_evidence(self):
        body=small_page(ANSWER)
        doc=ask120.extract(body,URL)
        ask120.audit(body,URL,doc)
        doc['question_provenance']['raw_text']='changed'
        with self.assertRaisesRegex(ValueError,'question_provenance'):
            ask120.audit(body,URL,doc)

    def test_manual_include_and_tampered_checkpoint_cannot_bypass_question_blockers(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            folder=Path(folder)
            source,out=folder/'input',folder/'output'
            (source/'raw').mkdir(parents=True)
            body=small_page(ANSWER,'BR&gt;这是有上下文的患者问题。')
            (source/'raw/1.gz').write_bytes(gzip.compress(body,mtime=0))
            gate.write_json(source/'manifest.json',{'fixture':True})
            gate.jsonl(source/'sample.jsonl',[dict(id=1,url=URL)])
            gate.write_json(source/'records/1.json',dict(id=1,url=URL,raw_path='raw/1.gz',raw_sha256=gate.sha(body),
                http_status=200,status='extracted',content_type='text/html; charset=utf-8'))
            with patch('requests.sessions.Session.request',side_effect=AssertionError('no network')):
                gate.replay(source,out)
            saved=json.loads((out/'records/1.json').read_text(encoding='utf-8'))
            thread=saved['thread_decisions'][0]
            label=dict(source_id=1,thread_id=thread['thread_id'],reviewer_decision='INCLUDE',
                reviewer_notes='synthetic behavioral test, not a human review',reviewed_at='2026-10-23T00:00:00Z',
                **{k:saved[k] for k in ('raw_sha256','parser_sha256','policy_sha256')})
            gate.jsonl(folder/'manual.jsonl',[label])
            summary=gate.build_outputs(out,manual_review_path=folder/'manual.jsonl')
            self.assertEqual(summary['candidate_documents'],0)
            evaluated=gate.read_jsonl_bytes((out/'qa_threads_all.jsonl').read_bytes())[0]
            self.assertIn('manual_override_blocked',evaluated)
            saved['question_qc']={}
            thread['corpus_decision']='INCLUDE'
            gate.write_json(out/'records/1.json',saved)
            summary=gate.build_outputs(out)
            self.assertEqual(summary['candidate_invariant_violations'],[1])
            self.assertEqual(summary['candidate_documents'],0)


if __name__=='__main__': unittest.main()
