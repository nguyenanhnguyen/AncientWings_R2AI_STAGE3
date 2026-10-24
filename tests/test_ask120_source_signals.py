"""F3: evidence-backed source signals, local negation and speaker attribution."""
import gzip
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'scripts'))
import ask120_gate as gate
from test_ask120_corpus_gate import small_page

FIXTURES = ROOT / 'tests/fixtures/120ask_f3'
GOOD = '建议您结合病史和检查结果复诊，根据具体情况决定是否进一步治疗，注意记录症状变化。'
URL = 'https://www.120ask.com/question/123.htm'


def parse(body,metadata=None):
    data = dict(metadata or {})
    data.setdefault('id',1)
    data.setdefault('url',URL)
    data.update(access_status='VAO_DUOC',raw_path='raw/test.gz',raw_sha256=gate.sha(body),
                parser_sha256='test-parser',policy_sha256='test-policy')
    page = gate.parse_source_response(body,data)
    page['thread_decisions'] = [gate.review_thread(t,page,gate.POLICY) for t in page['ask120_threads']]
    return page


class SourceSignalTests(unittest.TestCase):
    def test_real_false_negative_positive_and_clinical_negative_fixtures(self):
        cases = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))['cases']
        self.assertEqual(len(cases),20)
        for case in cases:
            with self.subTest(source_id=case['source_id'],thread_id=case['thread_id']):
                raw = gzip.decompress((FIXTURES / case['raw_file']).read_bytes())
                self.assertEqual(gate.sha(raw),case['raw_sha256'])
                page = parse(raw,dict(case,id=case['source_id']))
                thread = next(t for t in page['thread_decisions'] if t['thread_id']==case['thread_id'])
                self.assertEqual(bool(thread['source_flags']),case['expected_flagged'])
                self.assertEqual(thread['corpus_decision'],case['expected_decision'])
                self.assertEqual('SOURCE_CLAIM_REVIEW' in thread['decision_reasons'],case['expected_flagged'])

    def test_observed_signal_families(self):
        cases = [
            ('您可以点击我的名字就可以看到我的联系方式。','SOURCE_CONTACT_CTA_REVIEW'),
            ('如果需要可以点击我的相片联系我们。','SOURCE_CONTACT_CTA_REVIEW'),
            ('需要帮助可以直接和我联系。','SOURCE_CONTACT_CTA_REVIEW'),
            ('我院免费提供的放松训练CD，可以了解具体内容。','SOURCE_SELF_PROMOTION_REVIEW'),
            ('我院采用国际最先进的疗法，一般1到3个月都能治愈。','SOURCE_SELF_PROMOTION_REVIEW'),
            ('某某中医眼科研制出治疗眼底出血的特效系列方剂。','SOURCE_SELF_PROMOTION_REVIEW'),
            ('我院保证一个月包治百病。','PROMOTIONAL_CLAIM_REVIEW'),
            ('本疗法100%治愈，治愈后永不复发。','PROMOTIONAL_CLAIM_REVIEW'),
            ('本疗法百分之百治愈。','PROMOTIONAL_CLAIM_REVIEW'),
            ('本药无任何的毒副作用。','PROMOTIONAL_CLAIM_REVIEW'),
            ('中草药热敷治疗乳腺癌有特效。','PROMOTIONAL_CLAIM_REVIEW'),
            ('这些药物配合使用，可以快速治愈。','PROMOTIONAL_CLAIM_REVIEW'),
            ('PH基因递进增强疗法，疗效极佳，复发率极低。','PROMOTIONAL_CLAIM_REVIEW'),
            ('康泰安口服液和圣夜口服液，服用方便，可以杀死癌细胞。','PROMOTIONAL_CLAIM_REVIEW'),
        ]
        for text,expected in cases:
            with self.subTest(text=text):
                self.assertIn(expected,{f['flag'] for f in gate.source_flags(text)})

    def test_clinical_terms_and_noncommercial_hospital_context_are_not_promotion(self):
        for text in (
            '您很可能是慢性泌尿系感染，未彻底根治。建议复查。',
            '药物无效的部分患者可做射频消融，部分病人可获根治。',
            '必要时行根治性手术，具体方案需结合检查结果。',
            '目前没有特效药，主要是对症治疗。',
            '我院建议您到当地医院复查，不能仅凭文字确定诊断。',
            '建议出现严重症状时联系当地急诊或拨打120。',
            '如果症状加重，请联系我们医院急诊或当地急救中心。',
            '点击我的名字可以查看科普文章和检查准备资料。',
            '初步治疗后病情好转，预计一个月后复查。',
            '如还有疑问，请随时和我们联系，按时复查。',
            '请将患儿的详细病历传真于我们，及时与我们联系。',
            '相关药物可能影响癌细胞，但用药需由医生评估。',
            '外用疗法较安全，一般无痛苦、无副作用，具体需医生评估。',
            '没有一种肿瘤标记能兼顾百分之百的特异性及敏感度。',
            '也确定不了百分之百，注意按时复查。',
        ):
            with self.subTest(text=text):
                self.assertEqual(gate.source_flags(text),[])

    def test_negation_warnings_and_questions_are_local_nonassertions(self):
        for text in (
            '不能保证治愈，需要结合病情判断。',
            '没有人能保证治愈，仍需结合情况判断。',
            '目前没有办法保证治愈，仍需复查。',
            '不能说本药没有任何副作用。',
            '并非百分之百有效，效果因人而异。',
            '没有无副作用的药物，使用前需要了解风险。',
            '不存在没有任何副作用的药物。',
            '不要相信“包治百病”的宣传。',
            '广告所谓“无任何副作用”的说法不可信。',
            '不要点击我的照片联系我，请联系当地急诊。',
            '请不要通过点击我的照片来联系我，请联系当地急诊。',
            '本药真的没有任何副作用吗？',
            '请问点击我的名字可以看到联系方式吗？',
            '不要相信快速治愈的广告，仍需正规检查。',
            '无法确定是否能百分之百治愈，需要结合检查。',
            '没有任何药物可以100%治愈。',
        ):
            with self.subTest(text=text):
                self.assertEqual(gate.source_flags(text),[])

    def test_negation_in_another_clause_does_not_hide_an_actual_promise(self):
        text = '一般治疗不能保证疗效，但我院独家疗法100%治愈。'
        flags = gate.source_flags(text)
        self.assertIn('PROMOTIONAL_CLAIM_REVIEW',{f['flag'] for f in flags})
        self.assertTrue(any('100%' in e['text'] for f in flags for e in f['evidence']))
        self.assertTrue(gate.source_flags('一般治疗不能保证疗效但我院独家疗法100%治愈。'))

    def test_multiple_flags_keep_exact_offsets_hash_and_dom_provenance(self):
        text = '我院免费提供训练资料。点击我的照片可以看到联系方式。本疗法100%治愈。'
        page = parse(small_page(text))
        thread = page['thread_decisions'][0]
        turn = thread['turns'][0]
        self.assertGreaterEqual(len(thread['source_flags']),3)
        for flag in thread['source_flags']:
            self.assertTrue(flag['rule_id'])
            self.assertEqual(flag['turn_index'],1)
            self.assertEqual(flag['reply_id'],turn['reply_id'])
            self.assertEqual(flag['dom_locator'],turn['dom_locator'])
            self.assertEqual(flag['text_sha256'],gate.sha(turn['text']))
            self.assertEqual(flag['excerpt'],turn['text'][flag['excerpt_start']:flag['excerpt_end']])
            self.assertTrue(flag['evidence'])
            for span in flag['evidence']:
                self.assertEqual(span['text'],turn['text'][span['char_start']:span['char_end']])
                self.assertLessEqual(flag['excerpt_start'],span['char_start'])
                self.assertGreaterEqual(flag['excerpt_end'],span['char_end'])

    def test_patient_question_and_followup_do_not_get_attributed_to_responder(self):
        ad = '我院采用独家疗法100%治愈，点击我的照片联系我们。'
        body = small_page(GOOD,ad).decode()
        followup = '<div class="b_ansaddli"><span class="b_ansaddti">追问</span><p>' + ad + '</p></div>'
        body = body.replace('</div></div></div></html>','</div>' + followup + '</div></div></html>')
        thread = parse(body.encode())['thread_decisions'][0]
        self.assertEqual(thread['source_flags'],[])
        self.assertEqual(thread['corpus_decision'],'INCLUDE')

    def test_responder_followup_is_scanned_with_its_own_evidence(self):
        body = small_page(GOOD).decode()
        followup = ('<div class="b_ansaddli"><span class="b_docaddti">补充回答</span>'
                    '<p>您可以点击我的名字查看我的联系方式。</p></div>')
        body = body.replace('</div></div></div></html>','</div>' + followup + '</div></div></html>')
        thread = parse(body.encode())['thread_decisions'][0]
        self.assertEqual(thread['corpus_decision'],'REVIEW')
        self.assertTrue(thread['source_flags'])
        self.assertTrue(all(f['turn_index']==2 for f in thread['source_flags']))

    def test_self_reference_and_claim_are_not_combined_across_unrelated_sentences(self):
        text = '我院建议复查。' + '请记录症状变化和检查结果。' * 30 + '相关研究讨论特效系列方剂的概念。'
        self.assertEqual(gate.source_flags(text),[])

    def test_flagging_preserves_source_text_and_policy_off_keeps_evidence(self):
        text = '我院免费提供训练资料，需要帮助可以点击我的照片联系我们。'
        page = parse(small_page(text))
        thread = page['thread_decisions'][0]
        self.assertEqual(thread['turns'][0]['text'],text)
        self.assertEqual(thread['corpus_decision'],'REVIEW')
        unheld = gate.review_thread(page['ask120_threads'][0],page,dict(gate.POLICY,promotional_claims_require_review=False))
        self.assertEqual(unheld['corpus_decision'],'INCLUDE')
        self.assertEqual(unheld['source_flags'],thread['source_flags'])
        doc = gate.build_candidate_document(dict(page,thread_decisions=[unheld]),[unheld])
        self.assertEqual(len(doc['source_claim_flags']),len(unheld['source_flags']))
        self.assertEqual(doc['source_claim_flags'][0]['thread_id'],unheld['thread_id'])
        self.assertNotIn('source_claim_flags',gate.PRODUCTION_FIELDS)

    def test_aggregation_blocks_unreviewed_claim_even_if_checkpoint_decision_is_changed(self):
        import tempfile
        from unittest.mock import patch
        (ROOT / 'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            root=Path(directory)
            source,output=root/'source',root/'output'
            (source/'raw').mkdir(parents=True)
            raw=small_page('我院采用独家疗法，保证100%治愈。')
            gate.write_json(source/'manifest.json',{})
            gate.jsonl(source/'sample.jsonl',[dict(id=1,url=URL)])
            (source/'raw/1.gz').write_bytes(gzip.compress(raw,mtime=0))
            gate.write_json(source/'records/1.json',dict(id=1,url=URL,http_status=200,
                content_type='text/html; charset=utf-8',raw_path='raw/1.gz',raw_sha256=gate.sha(raw)))
            with patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected HTTP')):
                gate.replay(source,output)
            path=output/'records/1.json'
            page=json.loads(path.read_text(encoding='utf-8'))
            page['thread_decisions'][0]['corpus_decision']='INCLUDE'
            gate.write_json(path,page)
            summary=gate.build_outputs(output)
            self.assertEqual(summary['candidate_invariant_violations'],[1])
            self.assertEqual(summary['candidate_documents'],0)


if __name__=='__main__':
    unittest.main()
