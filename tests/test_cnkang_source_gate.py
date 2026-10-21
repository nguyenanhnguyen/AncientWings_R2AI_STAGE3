"""Q3 source policy: evidence/negation, whole articles, audit and export boundaries."""
import ast
import base64
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cnkang
import cnkang_article as article
import cnkang_check as check
import cnkang_transport as transport
from test_cnkang_metadata import page, URL

gate=cnkang.SOURCE
FIXTURES=ROOT/'tests/fixtures/cnkang_q3'
CASES=json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8'))['cases']


def document(body, title='湿疹的治疗', complete=True):
    raw=page(body).replace('湿疹的治疗'.encode(),title.encode())
    doc=cnkang.extract(raw,URL)
    doc.update(article_complete=complete,article_page_count=1,status='extracted')
    return gate.apply(doc)


class SourceGateTests(unittest.TestCase):
    def test_real_raw_fixtures_keep_text_and_explicit_source_oracles(self):
        for case in CASES:
            with self.subTest(id=case['id']):
                raw=(FIXTURES/case['file']).read_bytes()
                self.assertEqual(cnkang.sha(raw),case['raw_sha256'])
                doc=cnkang.extract(raw,case['url'],case['content_type'])
                self.assertEqual(doc['text_sha256'],case['text_sha256'])
                expected=case['expected']; signals=doc['source_signals']
                for field in ('stance','kind'):
                    if 'claim_'+field in expected:
                        self.assertIn(expected['claim_'+field],[s.get(field) for s in signals])
                if 'short_state' in expected:self.assertEqual(doc['short_text_assessment']['state'],expected['short_state'])
                if 'alignment' in expected:self.assertEqual(doc['title_body_alignment']['state'],expected['alignment'])
                if 'decision' in expected:self.assertEqual(doc['source_decision'],expected['decision'])
                if 'flag' in expected:self.assertIn(expected['flag'],doc['source_flags'])
                if expected.get('not_exclude'):self.assertNotEqual(doc['source_decision'],'EXCLUDE')
                for signal in signals:
                    a,b=signal['span'];self.assertEqual(doc['text'][a:b],signal['quote'])
                cnkang.audit(raw,case['url'],doc,case['content_type'])

    def test_negation_scope_does_not_hide_an_assertion_in_next_clause(self):
        doc=document('<p>不能保证百分之百治愈，但是本品无副作用，请立即购买。</p>')
        claims=[s for s in doc['source_signals'] if s['code']=='CLAIM_CONTEXT']
        self.assertEqual([s['stance'] for s in claims],['negated','asserted'])
        self.assertEqual(doc['source_decision'],'EXCLUDE')

    def test_quotes_rebuttal_endorsement_and_uncertainty_are_distinct(self):
        expected=[('广告声称“包治”，但本文反对这一说法。','quoted_rebutted'),
                  ('广告声称“包治”，对此我们赞同。','quoted_endorsed'),
                  ('有人声称“包治”，尚待核查。','quoted_uncertain')]
        for text,stance in expected:
            with self.subTest(stance=stance):
                doc=document('<p>'+text+'</p>')
                self.assertEqual(doc['source_signals'][0]['stance'],stance)
                self.assertNotEqual(doc['source_decision'],'EXCLUDE')
        rebuttal=document('<p>不能保证100%治愈，包治百病的广告不可信。</p>')
        self.assertNotEqual(rebuttal['source_decision'],'EXCLUDE')
        self.assertEqual([s['stance'] for s in rebuttal['source_signals']],['negated','rebutted'])

    def test_condition_percentage_herb_and_procedure_are_not_automatic_ads(self):
        samples=[('部分患者可以达到根治的效果。','conditional'),('葛根治之。','not_a_claim'),
                 ('根治性手术存在风险。','not_a_claim'),('问卷100%回收。','uncertain')]
        for text,stance in samples:
            with self.subTest(text=text):
                doc=document('<p>'+text+'</p>')
                self.assertEqual(doc['source_signals'][0]['stance'],stance)
                self.assertNotIn('PROMOTIONAL_CLAIM_REVIEW',doc['source_flags'])

    def test_warning_not_to_buy_and_quoted_DOM_do_not_trigger_commercial_exclusion(self):
        doc=document('<p>这种药声称包治；千万不要立即购买。</p>')
        self.assertNotEqual(doc['source_decision'],'EXCLUDE')
        self.assertEqual([s['stance'] for s in doc['source_signals']],['quoted_rebutted','negated'])
        doc=document('<p>患者：如何治疗？</p><blockquote><p>张三：本品包治，请立即购买。</p></blockquote>')
        self.assertNotEqual(doc['source_decision'],'EXCLUDE')
        self.assertEqual(doc['source_signals'][0]['stance'],'quoted_uncertain')

    def test_patient_question_is_not_an_article_endorsement_or_testimonial(self):
        doc=document('<p>患者：我儿子能根治吗？</p><p>答：需要检查。</p>')
        self.assertEqual(doc['source_signals'][0]['stance'],'question')
        self.assertNotIn('PERSONAL_EXPERIENCE_REVIEW',doc['source_flags'])
        self.assertIn('qa',doc['source_type'])

    def test_title_body_wrong_topic_same_topic_wrong_intent_and_generic_title(self):
        self.assertEqual(gate.alignment('湿疹是怎样形成的？','湿疹由过敏因素引起。')['state'],'related_lexical')
        self.assertEqual(gate.alignment('湿疹治疗方法','湿疹是一种皮肤病，原因有很多。')['state'],'topic_only')
        self.assertEqual(gate.alignment('湿疹治疗方法','心律失常需要消融治疗。')['state'],'mismatch_candidate')
        self.assertEqual(gate.alignment('如何治疗？','治疗需要个体化。')['state'],'insufficient_title_terms')
        self.assertEqual(gate.alignment('','湿疹。')['state'],'missing_heading')

    def test_short_and_incomplete_never_bypass_parser_or_get_padded(self):
        doc=document('<p>改善血液微循环</p>')
        self.assertEqual(doc['text'],'改善血液微循环')
        self.assertIn('SHORT_TEXT_REVIEW',doc['parser_flags'])
        self.assertEqual(gate.decision(doc),'REVIEW')
        doc=document('<p>'+('湿疹需要个体化治疗。'*30)+'</p>',complete=False)
        self.assertEqual(doc['short_text_assessment']['state'],'article_incomplete')
        self.assertEqual(gate.decision(doc),'REVIEW')

    def test_long_patient_question_without_answer_is_source_review(self):
        doc=document('<p>患者：'+('湿疹需要治疗吗？'*40)+'</p>')
        self.assertNotIn('SHORT_TEXT_REVIEW',doc['parser_flags'])
        self.assertIn('QA_ANSWER_UNVERIFIED_REVIEW',doc['source_reason_codes'])
        self.assertEqual(gate.decision(doc),'REVIEW')

    def test_article_recomputes_title_claims_and_shortness_after_merge(self):
        first=cnkang.extract(page('<p>前言。</p>'),URL)
        second=cnkang.extract(page('<p>湿疹需要个体化治疗。</p><p>本品百分之百有效，请立即购买。</p>'),URL)
        merged=article.assemble(cnkang._parser_api(),[first,second],True,'complete')
        self.assertEqual(merged['title_body_alignment']['state'],'related_lexical')
        self.assertEqual(merged['source_decision'],'EXCLUDE')
        self.assertTrue(any(s['article_page']==2 for s in merged['source_signals'] if s['code']=='CLAIM_CONTEXT'))
        self.assertEqual(len(merged['article_source_evidence']),2)

    def test_first_page_author_is_preserved_and_later_conflict_is_review(self):
        raw1=page('<p>'+'湿疹需要治疗。'*50+'</p>',meta='<meta name="author" content="张三">')
        raw2=page('<p>湿疹还需要护理。</p>',meta='<meta name="author" content="李四">')
        merged=article.assemble(cnkang._parser_api(),[cnkang.extract(raw1,URL),cnkang.extract(raw2,URL)],True,'complete')
        self.assertEqual(merged['author'],'张三')
        self.assertEqual(merged['metadata_conflicts'][0]['article_page'],2)
        self.assertIn('CONFLICTING_PAGE_METADATA',merged['source_reason_codes'])
        self.assertNotEqual(gate.decision(merged),'KEEP')

    def test_source_and_publication_tampering_is_rejected(self):
        doc=document('<p>'+'湿疹需要个体化治疗。'*40+'</p>')
        published=gate.publish(doc)
        self.assertEqual(gate.decision(doc),'KEEP')
        for field,value in [('source_decision','EXCLUDE'),('source_input_sha256','0'*64),
                            ('source_policy_sha256','0'*64),('source_signals',[{'fake':True}])]:
            bad=copy.deepcopy(doc);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):gate.audit(bad)
        bad=dict(published,corpus_decision='EXCLUDE')
        with self.assertRaises(ValueError):gate.audit_publication(bad)

    def test_report_only_enforce_missing_and_stale_policy_decisions(self):
        doc=document('<p>'+'湿疹需要个体化治疗。'*40+'</p><p>本品百分之百有效，请立即购买。</p>')
        self.assertEqual(doc['quality_status'],'accepted')
        self.assertTrue(gate.export_eligible(doc,'report_only'))
        self.assertFalse(gate.export_eligible(doc,'enforce'))
        self.assertEqual(gate.decision({'quality_status':'accepted','article_complete':True}),'REVIEW')
        bad=dict(doc,source_policy_sha256='0'*64)
        self.assertEqual(gate.decision(bad),'REVIEW')
        with self.assertRaises(ValueError):gate.export_eligible(bad,'enforce')
        with self.assertRaises(ValueError):gate.publish(doc,'typo')

    def test_check_export_enforces_source_policy_and_retains_all_diagnostic_records(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            root=Path(folder);(root/'records').mkdir()
            doc=document('<p>'+'湿疹需要个体化治疗。'*40+'</p><p>本品百分之百有效，请立即购买。</p>')
            doc.update(id=1,url=URL,source_url=URL,canonical_url='cnkang.com/jibing/test/123.html',branch='jibing',crawl_status='parsed')
            sample={k:doc[k] for k in ('id','url','canonical_url','branch')}
            (root/'records/1.json').write_text(json.dumps(doc),encoding='utf-8')
            policy={'mode':'enforce','policy_version':gate.VERSION,'policy_sha256':gate.POLICY_SHA256}
            (root/'cnkang_source_policy.json').write_text(json.dumps(policy),encoding='utf-8')
            with patch.object(check.transport_module,'audit_saved') as audited:
                summary=check.export(root,[sample])
            audited.assert_called_once()
            self.assertTrue(summary['source_gate_enforced'])
            self.assertFalse((root/'corpus.accepted.jsonl').read_text().strip())
            self.assertEqual(len((root/'results.jsonl').read_text().splitlines()),1)

    def test_policy_mode_conflict_is_not_silently_downgraded(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            root=Path(folder)
            (root/'config.json').write_text(json.dumps({'network':{'source_policy_mode':'enforce'}}))
            (root/'cnkang_source_policy.json').write_text(json.dumps({'mode':'report_only','policy_version':gate.VERSION,'policy_sha256':gate.POLICY_SHA256}))
            with self.assertRaises(ValueError):gate.mode_for_run(root)

    def test_transport_mode_change_cannot_reuse_a_cached_report_only_run(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            root=Path(folder)
            (root/'cnkang_source_policy.json').write_text(json.dumps({'mode':'report_only','policy_version':gate.VERSION,'policy_sha256':gate.POLICY_SHA256}))
            with patch.object(transport.NETWORK.NetworkWorker,'get') as get:
                with self.assertRaisesRegex(ValueError,'mode changed'):
                    transport.Transport(root,{'source_policy_mode':'enforce'})
            get.assert_not_called()

    def test_all_three_notebooks_embed_production_source_policy(self):
        for name in ('crawl_corpus_kaggle_hf_upload.ipynb','crawl_domain_samples.ipynb','check_cnkang.com.ipynb'):
            nb=json.loads((ROOT/'notebooks'/name).read_text(encoding='utf-8'));packs={}
            for cell in nb['cells']:
                if cell['cell_type']!='code':continue
                for node in ast.parse(''.join(cell['source'])).body:
                    if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('EMBEDDED_FILES','PAYLOADS','CNKANG_RUNTIME_PAYLOADS'):
                        packs.update(ast.literal_eval(node.value))
            body=zlib.decompress(base64.b85decode(packs['cnkang_source_gate_snapshot.py']))
            self.assertEqual(body,(ROOT/'scripts/cnkang_source_gate.py').read_bytes())


if __name__=='__main__': unittest.main()
