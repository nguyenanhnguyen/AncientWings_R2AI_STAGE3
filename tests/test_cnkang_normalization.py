"""Q2: contextual glyph normalization, charset provenance and anchored legacy layout."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cnkang
import cnkang_article
FIXTURES=ROOT/'tests/fixtures/cnkang_q2'
CASES=json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8'))
URL='https://www.cnkang.com/myjk/202001/123.html'

def page(text,encoding='gb18030',declared='gb2312'):
    return (f'<html><meta charset="{declared}"><title>测试正文</title>'
        '<h1 id="h1title">测试正文</h1><div id="endText">'+text+'</div></html>').encode(encoding)

def legacy(body='<p>1.甲。</p><p>2.乙。</p>',extra='',heading='测试正文'):
    return ('<html><meta charset="utf-8"><title>测试正文，额外关键词_大众健康_中华康网</title>'
       '<nav>导航文字</nav><table><tr><td><table><tr><th><span class="style8">'+heading+
       '</span></th></tr><tr><td class="style4"><a href="https://www.cnkang.com/">本站</a>'
       '2020-01-02 12:00:00</td></tr></table><table><tr><td class="style3 123">'+body+
       '</td></tr></table></td></tr></table>'+extra+'<aside>侧栏广告文字</aside></html>').encode()

class NormalizationTests(unittest.TestCase):
    def real(self,case):
        raw=(FIXTURES/case['file']).read_bytes()
        self.assertEqual(cnkang.sha(raw),case['raw_sha256'])
        return raw,cnkang.extract(raw,case['url'],case['content_type'])

    def test_nine_real_pages_match_explicit_normalization_and_charset_expectations(self):
        for case in CASES:
            with self.subTest(id=case['id']):
                raw,doc=self.real(case)
                glyph=doc['glyph_normalization']
                self.assertEqual(doc['template'],case['expected_template'])
                self.assertEqual(len(glyph['actions']),case['expected_actions'])
                self.assertEqual(len(glyph['unresolved']),case['expected_unresolved'])
                self.assertEqual(doc['encoding_uncertain'],case['expected_encoding_uncertain'])
                self.assertEqual(doc['selected_encoding'],case['selected_encoding'])
                self.assertEqual(doc['encoding_candidates'],case['encoding_candidates'])
                if case['id']!=1690503:
                    self.assertEqual(doc['text_before'],case['previous_text_before'])
                    # Independent text oracle: normalize only the documented
                    # number of E5E5 indents/separators or three F06C bullets.
                    old=case['previous_text']
                    if case['id'] in (1708607,1722395,1723595,1728042):
                        expected=old.replace('\ue5e5',' ')
                    elif case['id']==1772904:
                        import re
                        expected=re.sub(r'(?m)^[\s\ue5e5]+',
                            lambda m:m[0].replace('\ue5e5',' '),old)
                    elif case['id']==1844705: expected=old.replace('\uf06c','• ')
                    else: expected=old
                    expected='\n'.join(' '.join(line.split()) for line in expected.splitlines() if line.strip())
                    self.assertEqual(doc['text'],expected)
                else:
                    self.assertEqual(cnkang.compact(doc['text']),
                        cnkang.compact(case['previous_text']).removesuffix('[1][2][3]下一页'))
                cnkang.audit(raw,case['url'],doc,case['content_type'])

    def test_unknown_pair_and_legacy_suffix_glyphs_stay_review(self):
        for id_ in (1772904,1850128,1906646):
            case=next(c for c in CASES if c['id']==id_)
            _,doc=self.real(case)
            self.assertIn('PUA_FORMATTING_REVIEW',doc['parser_flags'])
            self.assertTrue(doc['glyph_normalization']['unresolved'])
        _,doc=self.real(next(c for c in CASES if c['id']==1772904))
        self.assertIn('\ue5e4比如限制生育\ue5e5',doc['text'])
        self.assertIn('ENCODING_UNCERTAIN_REVIEW',doc['parser_flags'])

    def test_indent_resolution_keeps_original_uncertainty_and_candidates(self):
        case=next(c for c in CASES if c['id']==1708607)
        _,doc=self.real(case)
        self.assertTrue(doc['encoding_uncertain_before_q2'])
        self.assertFalse(doc['encoding_uncertain'])
        self.assertEqual(doc['encoding_resolution']['state'],'verified_body_formatting')
        self.assertEqual(doc['encoding_uncertainty_reasons'],['pua_ratio'])
        self.assertGreater(next(c for c in doc['encoding_candidates'] if c.get('encoding')=='gb18030')['pua_ratio'],.002)

    def test_scientific_glyphs_unknown_codes_inline_pua_and_utf8_pua_are_unchanged(self):
        for body,encoding,declared in (
            ('<p>BRCA1\ue5e5 50mg 3.5mmol/L α β ≥ ≤ 10⁹</p>','gb18030','gb2312'),
            ('<p>\ue5e5BRCA1 c.123A&gt;G</p>','gb18030','gb2312'),
            ('<p>\ue5e5\ue5e5BRCA1 p.Val600Glu</p>','utf-8','utf-8'),
            ('<p>正文\ue111基因。</p>','gb18030','gb2312'),
            ('<table><tr><td><p>\ue5e5\ue5e5BRCA1 50mg</p></td></tr></table>','gb18030','gb2312'),
            ('<p>\uf06c50mg</p><p>\uf06c100mg</p>','gb18030','gb2312'),
            ('<p>\uf06c只有一个条目。</p>','gb18030','gb2312')):
            raw=page(body,encoding,declared)
            doc=cnkang.extract(raw,URL)
            with self.subTest(body=body):
                self.assertFalse(doc['glyph_normalization']['actions'])
                self.assertEqual(doc['text'],doc['text_before'])
                self.assertIn('PUA_FORMATTING_REVIEW',doc['parser_flags'])

    def test_verified_bullet_keeps_numbers_units_and_inline_links(self):
        raw=page('<p>\uf06c第一项50mg与<a>BRCA1</a>。</p><p>\uf06c第二项3.5mmol/L。</p>')
        doc=cnkang.extract(raw,URL)
        self.assertEqual(doc['text'],'• 第一项50mg与BRCA1。\n• 第二项3.5mmol/L。')
        self.assertEqual(len(doc['glyph_normalization']['actions']),2)

    def test_pua_penalty_cannot_silently_switch_to_unrelated_cjk_decode(self):
        raw=page('<p>正文\ue111基因。</p>')
        doc=cnkang.extract(raw,URL)
        self.assertEqual(doc['selected_encoding'],'gb18030')
        self.assertEqual(doc['encoding_selection']['ranking_best'],'big5')
        self.assertEqual(doc['text'],'正文\ue111基因。')
        self.assertIn('declared_pua_candidate_conflict',doc['encoding_uncertainty_reasons'])
        self.assertIn('ENCODING_UNCERTAIN_REVIEW',doc['parser_flags'])

    def test_non_pua_decode_uncertainty_never_clears_from_glyph_actions(self):
        glyphs={'actions':[{'x':1}],'unresolved':[]}
        for reasons in (['ambiguous_decode'],['pua_ratio','mojibake'],['no_strict_decode']):
            encoding={'encoding_uncertain':True,'encoding_uncertainty_reasons':reasons,
                      'declared_encoding':'gb2312','selected_encoding':'gb18030'}
            self.assertTrue(cnkang.resolve_encoding(encoding,glyphs)['encoding_uncertain'])

    def test_wrong_declared_charset_can_still_select_valid_utf8(self):
        text='正文医学符号BRCA1 50mg α β ≥ 这是完整中文内容。'*10
        doc=cnkang.extract(page('<p>'+text+'</p>',encoding='utf-8',declared='gb2312'),URL)
        self.assertEqual(doc['selected_encoding'],'utf-8')
        self.assertEqual(doc['text'],text)

    def test_saved_legacy_page_recovery_stays_incomplete_without_network(self):
        import gzip
        import cnkang_transport as transport
        case=next(c for c in CASES if c['id']==1690503)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as folder:
            source,target=Path(folder)/'source',Path(folder)/'recovered'
            raw=(FIXTURES/case['file']).read_bytes()
            transport.STORAGE.write_bytes(source/'raw/first.gz',gzip.compress(raw,mtime=0))
            sample={'id':1690503,'url':case['url'],'source_url':case['url'],
                    'canonical_url':cnkang_article.key(case['url'])}
            old=dict(sample,status='extracted',http_status=200,final_url=case['url'],
                raw_path='raw/first.gz',raw_sha256=cnkang.sha(raw),content_type=case['content_type'])
            transport.STORAGE.write_json(source/'records/1690503.json',old)
            with patch.object(transport.NETWORK.NetworkWorker,'get',
                              side_effect=AssertionError('network forbidden')):
                transport.seed_recovery(target,[sample],source,record_dir='records')
            saved=json.loads((target/'records/1690503.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['template'],'legacy_table')
            self.assertFalse(saved['article_complete'])
            self.assertEqual(saved['article_reason'],'offline_missing_page')
            self.assertEqual(saved['quality_status'],'review')
            self.assertTrue(transport.audit_saved(target,saved)['cnkang_article_verified'])

    def test_whole_article_keeps_every_page_glyph_and_encoding_proof(self):
        first=cnkang.extract(page('<p>\ue5e5\ue5e5第一部分正文。</p>'),URL)
        second=cnkang.extract(page('<p>正文\ue111基因。</p>'),URL.replace('.html','_2.html'))
        result=cnkang_article.assemble(cnkang._parser_api(),[first,second],True,'complete')
        self.assertEqual(len(result['article_glyph_normalizations']),2)
        self.assertEqual(len(result['article_glyph_normalizations'][0]['actions']),2)
        self.assertEqual(len(result['article_glyph_normalizations'][1]['unresolved']),1)
        self.assertEqual(result['article_encoding_resolutions'][1]['state'],'unresolved')
        self.assertIn('PUA_FORMATTING_REVIEW',result['parser_flags'])

    def test_legacy_body_title_metadata_and_pager_are_bound_to_source(self):
        case=next(c for c in CASES if c['id']==1690503)
        _,doc=self.real(case)
        self.assertEqual(doc['heading_title'],'去痘印的十三个不外传绝招')
        self.assertEqual(doc['date_candidates'],['2008-4-26 10:36:43'])
        self.assertEqual(doc['layout_evidence']['article_id'],'107572')
        self.assertEqual(doc['parser_flags'],['PAGINATION_REVIEW'])
        next_url,total=cnkang_article.next_page(doc,case['url'],case['url'])
        self.assertTrue(next_url.endswith('/107572_2.html'))
        self.assertEqual(total,3)
        for noise in ('站内搜索','今日导读','相关文章','www.cnkang.com','下一页'):
            self.assertNotIn(noise,doc['text'])

    def test_style_or_id_alone_wrong_title_missing_meta_and_duplicate_body_stay_review(self):
        valid=legacy()
        for raw in (
            valid.replace(b'style3 123',b'style3 999'),
            valid.replace(b'style3 123',b'style3'),
            legacy(heading='其他标题'),
            valid.replace(b'2020-01-02 12:00:00',b'not-a-date'),
            valid.replace(b'<td class="style3 123">',b'<td class="style3 123"><table><tr><td class="style3 123">'),
            valid.replace(b'</td></tr></table></td></tr></table>',b'</td></tr></table><table><tr><td class="style3 123">other</td></tr></table></td></tr></table>')):
            doc=cnkang.extract(raw,URL)
            with self.subTest(raw=raw):
                self.assertNotEqual(doc['template'],'legacy_table')
                self.assertIn('UNKNOWN_LAYOUT_REVIEW',doc['parser_flags'])

    def test_layout_wrapper_is_not_a_medical_table_cell_for_q1(self):
        doc=cnkang.extract(legacy('<p>3.甲。</p><p>2.乙。</p>'),URL)
        self.assertEqual(doc['template'],'legacy_table')
        self.assertIn('DESCENDING_NUMBERING_REVIEW',doc['parser_flags'])
        self.assertNotIn('导航文字',doc['text'])
        self.assertNotIn('侧栏广告文字',doc['text'])

    def test_audit_rejects_tampered_glyph_paths_replacements_layout_or_charset(self):
        for id_,field in ((1708607,'glyph_normalization'),(1708607,'encoding_resolution'),
                          (1708607,'encoding_uncertain_before_q2'),(1690503,'layout_evidence')):
            case=next(c for c in CASES if c['id']==id_)
            raw,doc=self.real(case)
            changed=copy.deepcopy(doc)
            changed[field]={} if isinstance(doc[field],dict) else False
            with self.subTest(id=id_,field=field),self.assertRaises(ValueError):
                cnkang.audit(raw,case['url'],changed,case['content_type'])

if __name__=='__main__':unittest.main()
