"""Q1: scoped numbering and contextual repetition without rewriting content."""
import copy
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cnkang
import cnkang_article
TARGET={'DESCENDING_NUMBERING_REVIEW','REPEATED_PARAGRAPH_REVIEW'}
FIXTURES=ROOT/'tests/fixtures/cnkang_q1'
URL='https://www.cnkang.com/myjk/202001/123.html'
REPEAT='这是一个完整的重复测试段落，保留医学数字50mg及原始文字，不能自动删除。'

def extract(body):
    raw=('<html><meta charset="utf-8"><title>测试</title><div class="detail">'
         '<h1 class="detaila">测试</h1><div class="detailb">2020-01-02</div>'
         '<div class="detailc">'+body+'</div></div></html>').encode()
    return raw,cnkang.extract(raw,URL)

class StructureTests(unittest.TestCase):
    def test_real_contexts_have_pinned_text_and_explicit_expected_flags(self):
        for case in json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8')):
            with self.subTest(id=case['id']):
                raw=(FIXTURES/case['file']).read_bytes()
                self.assertEqual(cnkang.sha(raw),case['raw_sha256'])
                doc=cnkang.extract(raw,case['url'],case['content_type'])
                if case['id']==1690503:
                    # Q2 now verifies the legacy body/title/date and its pager.
                    # Content/boundary regression is pinned in normalization tests.
                    self.assertEqual(doc['template'],'legacy_table')
                    self.assertFalse(set(doc['parser_flags']) & TARGET)
                else:
                    self.assertEqual(doc['text_sha256'],case['text_sha256'])
                    self.assertEqual(set(doc['parser_flags']) & TARGET,set(case['expected_target_flags']))
                cnkang.audit(raw,case['url'],doc,case['content_type'])
                if case['id'] in (1759215,1669081):
                    self.assertIn('CONTEXTUAL_REPETITION_REVIEW',doc['source_flags'])

    def test_nested_markers_and_decimal_outline_are_not_flat_numbers(self):
        for body in (
            '<p>一、第一组</p><p>1.甲。</p><p>2.乙。</p><p>二、第二组</p><p>1.丙。</p>',
            '<p>1）第一组</p><p>1.甲。</p><p>2.乙。</p><p>2）第二组</p><p>1.丙。</p>',
            '<p>6.2.4.液体复苏的速度</p><p>（1）第一项。</p><p>(2)第二项。</p><p>6.3输血治疗</p>',
            '<ol><li>1.甲。<ol><li>1.子项。</li><li>2.子项。</li></ol></li><li>2.乙。</li></ol>'):
            raw,doc=extract(body)
            self.assertNotIn('DESCENDING_NUMBERING_REVIEW',doc['parser_flags'])
            self.assertEqual(doc['qc_structure']['state'],'verified')

    def test_real_descending_survives_bold_punctuation_variation_and_parent_return(self):
        for body in (
            '<p>3.甲</p><p>2.乙</p><p>1.丙</p>',
            '<p>3.甲</p><p>1、乙</p>',
            '<p><b>3.甲</b></p><p><b>2.乙</b></p><p><b>1.丙</b></p>',
            '<p>３．甲。</p><p>２.乙。</p><p>１．丙。</p>',
            '<p>二、第二组</p><p>1.子项。</p><p>一、第一组</p>',
            '<p>3.这是很长的连续正文。没有父列表或分组证据。</p><p>1、另一条连续正文。</p>',
            '<p>6.3.甲</p><p>6.2.乙</p>',
            '<ol><li>3.甲</li><li>2.乙</li></ol>'):
            with self.subTest(body=body):
                raw,doc=extract(body)
                self.assertIn('DESCENDING_NUMBERING_REVIEW',doc['parser_flags'])

    def test_heading_turn_and_separate_dom_lists_define_scopes(self):
        for body in (
            '<h2>第一组</h2><p>1.甲。</p><p>2.乙。</p><h2>第二组</h2><p>1.丙。</p>',
            '<p><strong>患者</strong>：提问。</p><p><b>医院医生</b>：</p><p>1.甲。</p><p>2.乙。</p>'
            '<p><b>患者</b>：追问。</p><p><b>医院医生</b>：</p><p>1.丙。</p>',
            '<ol><li>1.甲。</li><li>2.乙。</li></ol><ol><li>1.丙。</li></ol>',
            '<ol reversed><li>3.甲。</li><li>2.乙。</li></ol>'):
            raw,doc=extract(body)
            self.assertNotIn('DESCENDING_NUMBERING_REVIEW',doc['parser_flags'])

    def test_table_measurements_and_dosages_are_not_ordinal_transitions(self):
        raw,doc=extract('<p>1.检查项目。</p><p>2.注意事项。</p><table><tr><td>92.5%</td>'
                        '<td>33.4±10.1</td></tr></table><p>0.5mg每日。</p>'
                        '<p>0.5克每日。</p><p>2.5μg每日。</p><p>3.5毫克每日。</p>')
        self.assertNotIn('DESCENDING_NUMBERING_REVIEW',doc['parser_flags'])
        self.assertIn('0.5mg',doc['text'])

    def test_partial_inline_emphasis_and_plain_short_line_do_not_reset_order(self):
        for middle in ('<p>这是<b>重点</b>的说明。</p>','<p>处理方法</p>','<p><b>这是普通的完整句子。</b></p>'):
            raw,doc=extract('<p>3.正文。</p>'+middle+'<p>1.正文。</p>')
            self.assertIn('DESCENDING_NUMBERING_REVIEW',doc['parser_flags'])

    def test_repetition_in_distinct_sections_is_source_review_and_not_removed(self):
        raw,doc=extract('<p>1.第一类型</p><p>'+REPEAT+'</p><p>2.第二类型</p><p>'+REPEAT+'</p>')
        self.assertNotIn('REPEATED_PARAGRAPH_REVIEW',doc['parser_flags'])
        self.assertIn('CONTEXTUAL_REPETITION_REVIEW',doc['source_flags'])
        self.assertEqual(doc['text'].count(REPEAT),2)
        self.assertEqual(doc['cleaning_actions'],[])

    def test_identical_sections_same_scope_and_repeated_blocks_stay_review(self):
        for body in (
            '<p>'+REPEAT+'</p><p>'+REPEAT+'</p>',
            ('<h2>同一标题</h2><p>'+REPEAT+'</p>')*2,
            '<h2>甲</h2><p>'+REPEAT+'</p><p>第二个完整测试段落也被重复，不能借助不同的标题逃过检测。</p>'
            '<h2>乙</h2><p>'+REPEAT+'</p><p>第二个完整测试段落也被重复，不能借助不同的标题逃过检测。</p>'):
            raw,doc=extract(body)
            self.assertIn('REPEATED_PARAGRAPH_REVIEW',doc['parser_flags'])

    def test_punctuation_separators_are_preserved_without_prose_repeat_flag(self):
        raw,doc=extract('<p>'+'.'*60+'</p><p>正文。</p><p>'+'.'*60+'</p>')
        self.assertNotIn('REPEATED_PARAGRAPH_REVIEW',doc['parser_flags'])
        self.assertEqual(doc['text'].count('.'*60),2)

    def test_unknown_or_unaligned_structure_keeps_conservative_numbering(self):
        for context in (None,{'state':'unverified','paragraphs':[]}):
            proof=cnkang.structural_qc('3.正文。\n1.正文。',context)
            self.assertIn('DESCENDING_NUMBERING_REVIEW',proof['parser_flags'])
        with self.assertRaises(ValueError):
            cnkang.structural_qc('正文',{'state':'verified','paragraphs':[{'text_sha256':'tampered'}]})

    def test_removed_synopsis_cannot_reassign_identical_text_to_another_dom_scope(self):
        from lxml import html
        body=html.fromstring('<div><h2>甲</h2><p>'+REPEAT+'</p><h2>乙</h2><p>'+REPEAT+'</p></div>')
        context=cnkang.text_context(body,REPEAT)
        self.assertEqual(context['state'],'unverified')
        self.assertFalse(any(item.get('path') for item in context['paragraphs']))

    def test_audit_rejects_changed_structure_scope_and_decisions(self):
        raw,doc=extract('<h2>甲</h2><p>2.正文。</p><h2>乙</h2><p>1.正文。</p>')
        for field in ('paragraphs','decisions','numbering'):
            changed=copy.deepcopy(doc)
            changed['qc_structure'][field]=[]
            with self.subTest(field=field),self.assertRaises(ValueError):
                cnkang.audit(raw,URL,changed)

    def test_article_rechecks_across_page_boundary_without_invented_scope(self):
        _,first=extract('<p>1.正文。</p><p>3.正文。</p>')
        _,second=extract('<p>2.正文。</p><p>4.正文。</p>')
        result=cnkang_article.assemble(cnkang._parser_api(),[first,second],True,'complete')
        self.assertIn('DESCENDING_NUMBERING_REVIEW',result['parser_flags'])
        self.assertEqual(result['text'],first['text']+'\n'+second['text'])

if __name__=='__main__':unittest.main()
