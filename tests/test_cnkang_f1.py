"""Production coverage for the verified formatter and article pager rules."""
from collections import Counter
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import cnkang

URL = 'https://www.cnkang.com/jibing/test/123.html'
FIXTURES = ROOT/'tests/fixtures/cnkang_f1'


def page(blocks, call='formattext(3);', source='/images/jkpl.js', encoding='utf-8'):
    return (f'<html><head><meta charset="{encoding}"><title>正文标题</title>'
            f'<script src="{source}"></script></head><body><h1 id="h1title">正文标题</h1>'
            '<p>来源：医院 2020-01-02</p><div id="endText"><div id="jkpl"></div>'
            + blocks + f'<script>{call}</script></div></body></html>').encode(encoding)


class FormattextTests(unittest.TestCase):
    def test_original_encoding_metadata_inline_table_and_block_tails_survive(self):
        for encoding in ('utf-8', 'gb2312', 'gb18030'):
            raw = page('<div id="jbk2"><p>结尾<a>链接</a></p></div>旁注'
                       '<div id="jbk1"><table><tr><td>BRCA1</td><td>50mg</td></tr></table></div>'
                       '<div id="jbk0"><p>开头</p></div>', encoding=encoding)
            original = bytes(raw)
            doc = cnkang.extract(raw, URL)
            self.assertEqual(raw, original)
            self.assertEqual(doc['selected_encoding'], 'utf-8' if encoding == 'utf-8' else 'gb18030')
            self.assertEqual(doc['declared_encoding'], encoding)
            self.assertFalse(doc['encoding_uncertain'])
            self.assertEqual(doc['date_candidates'], ['2020-01-02'])
            self.assertEqual(doc['heading_title'], '正文标题')
            self.assertTrue(doc['text'].startswith('开头'))
            self.assertLess(doc['text'].index('BRCA1'), doc['text'].index('结尾链接'))
            self.assertEqual(doc['text'].count('旁注'), 1)
            self.assertEqual(len(doc['tables']), 1)
            self.assertEqual(Counter(cnkang.compact(doc['text'])), Counter(cnkang.compact(doc['source_dom_text'])))
            self.assertEqual(doc['formattext_evidence']['ordered_ids'], [0, 1, 2])
            self.assertTrue(cnkang.audit(raw, URL, doc)['cnkang_raw_reextraction_verified'])

    def test_missing_indices_match_website_accumulation(self):
        doc = cnkang.extract(page('<div id="jbk2">尾</div><div id="jbk0">首</div>'), URL)
        self.assertEqual(doc['text'], '首尾')
        self.assertEqual(doc['formattext_evidence']['ordered_ids'], [0, 2])

    def test_no_formatter_keeps_static_text_without_normalization(self):
        doc = cnkang.extract(page('<p>正文<a>链接</a></p>', call=''), URL)
        self.assertEqual(doc['text'], '正文链接')
        self.assertEqual(doc['text'], doc['source_dom_text'])
        self.assertEqual(doc['cleaning_actions'], [])
        self.assertEqual(doc['formattext_evidence']['state'], 'not_applicable')

    def test_ambiguous_or_unverified_formatter_never_silently_accepts(self):
        cases = [page('<div id="jbk0">内容</div>', source='https://evil.test/images/jkpl.js'),
                 page('<div id="jbk0">甲</div><div id="jbk0">乙</div>'),
                 page('<section><div id="jbk0">内容</div></section>'),
                 page('<div id="jbk4">内容</div>'),
                 page('<div id="jbk0">内容</div>', call='formattext(3);formattext(3);'),
                 page('<div id="jbk0">内容</div>', call='formattext(dynamicCount);'),
                 page('<div id="jbk0">内容</div>', call=''),
                 page('<div id="jbk0">内容</div>').replace(b'<div id="jkpl"></div>', b'<div id="jkpl">existing</div>')]
        for raw in cases:
            with self.subTest(raw=raw):
                doc = cnkang.extract(raw, URL)
                self.assertIn('FORMATTEXT_UNVERIFIED_REVIEW', doc['parser_flags'])
                self.assertNotEqual(doc['quality_status'], 'accepted')
                self.assertEqual(doc['formattext_evidence']['state'], 'unverified')
                self.assertEqual(doc['text'], doc['source_dom_text'])

    def test_real_article_openings_and_enumeration_follow_verified_js(self):
        expected = {1869305: '肛裂非手术疗法①', 1733228: '咽扁桃体炎是怎么回事？',
                    1780432: '日光性皮炎怎么治呢？'}
        for item in json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8')):
            if item['id'] not in expected:
                continue
            raw = (FIXTURES/f"{item['id']}.html").read_bytes()
            self.assertEqual(cnkang.sha(raw), item['raw_sha256'])
            doc = cnkang.extract(raw, item['url'], item['content_type'])
            self.assertTrue(doc['text'].startswith(expected[item['id']]))
            self.assertEqual(doc['selected_encoding'], item['encoding'])
            self.assertEqual(Counter(cnkang.compact(doc['source_dom_text'])), Counter(cnkang.compact(doc['text'])))
            if item['id'] == 1869305:
                self.assertEqual(sorted('①②③④⑤', key=doc['text'].index), list('①②③④⑤'))

    @unittest.skipUnless(shutil.which('node'), 'Node is optional; required only for the source-JS oracle')
    def test_real_fixture_html_accumulation_matches_pinned_javascript(self):
        raw_js = (FIXTURES/'formattext.js.raw').read_bytes()
        self.assertEqual(cnkang.sha(raw_js), cnkang.FORMATTEXT_JS_SHA256)
        js = raw_js.decode('ascii')
        code = r'''const vm=require('vm');let input='';process.stdin.setEncoding('utf8');
process.stdin.on('data',c=>input+=c);process.stdin.on('end',()=>{
const data=JSON.parse(input),nodes={jkpl:{innerHTML:'',style:{}}};
for(const [i,value] of Object.entries(data.fragments))nodes['jbk'+i]={innerHTML:value,style:{}};
vm.runInNewContext(data.js+'\nformattext('+data.count+');',{document:{getElementById:id=>nodes[id]||null}},{timeout:1000});
process.stdout.write(JSON.stringify({html:nodes.jkpl.innerHTML,hidden:Object.entries(nodes).filter(([k])=>k!=='jkpl').every(([,v])=>v.style.display==='none')}));});'''
        for item in json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8')):
            if item['id'] == 1816933:
                continue
            raw = (FIXTURES/f"{item['id']}.html").read_bytes()
            decoded, _ = cnkang.decode_bytes(raw, item['content_type'])
            tree = cnkang.html.fromstring(decoded)
            fragments = {n.get('id')[3:]: cnkang._inner_html(n) for n in tree.iter('div')
                         if __import__('re').fullmatch(r'jbk\d+', n.get('id') or '')}
            doc = cnkang.extract(raw, item['url'], item['content_type'])
            proof = doc['formattext_evidence']
            result = subprocess.run(['node','-e',code], input=json.dumps({'js':js,'count':proof['count'],
                                     'fragments':fragments}), text=True, encoding='utf-8', capture_output=True,
                                    check=True, timeout=10)
            oracle = json.loads(result.stdout)
            self.assertEqual(cnkang.sha(oracle['html']), proof['combined_html_sha256'])
            self.assertTrue(oracle['hidden'])


class PagerTests(unittest.TestCase):
    def test_only_verified_pager_removed_next_link_retained(self):
        raw = page('<p>正文内容</p><b><a href="123.html#t">[1]</a><font>[2]</font>'
                   '<a href="123_3.html#t">下一页</a></b>', call='')
        doc = cnkang.extract(raw, URL.replace('.html', '_2.html'))
        self.assertEqual(doc['text'], '正文内容')
        self.assertEqual(len(doc['pager_removals']), 1)
        self.assertEqual(doc['pagination_candidates'], [{'text':'下一页','href':'123_3.html#t'}])
        self.assertIn('PAGINATION_REVIEW', doc['parser_flags'])
        self.assertIn('[1]', doc['source_dom_text'])

    def test_unverified_pagers_preserved_and_reviewed(self):
        for href in ['124_3.html', 'https://evil.test/jibing/test/123_3.html',
                     '123_3.html?x=1', 'javascript:void(0)']:
            doc = cnkang.extract(page(f'<b><a href="{href}">下一页</a><font>[2]</font></b>', call=''), URL)
            self.assertIn('下一页', doc['text'])
            self.assertEqual(doc['pager_removals'], [])
            self.assertIn('PAGER_UNVERIFIED_REVIEW', doc['parser_flags'])

    def test_body_numbered_text_and_medical_links_are_preserved(self):
        doc = cnkang.extract(page('<p>第一组 [1]，下一页的描述仍是正文。</p>'
                                 '<b><a href="124.html">相关文章</a></b>', call=''), URL)
        self.assertIn('第一组 [1]，下一页的描述仍是正文。', doc['text'])
        self.assertIn('相关文章', doc['text'])
        self.assertEqual(doc['pager_removals'], [])

    def test_real_pager_keeps_pagination_review_and_metadata(self):
        item = next(x for x in json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8')) if x['id']==1816933)
        doc = cnkang.extract((FIXTURES/'1816933.html').read_bytes(), item['url'], item['content_type'])
        self.assertEqual(len(doc['pager_removals']), 1)
        self.assertNotIn('下一页', doc['text'])
        self.assertIn('PAGINATION_REVIEW', doc['parser_flags'])
        self.assertEqual(doc['date_candidates'], ['2011-9-27'])

    def test_audit_detects_normalization_provenance_tampering(self):
        raw = page('<div id="jbk1"><p>尾</p></div><div id="jbk0"><p>首</p></div>')
        doc = cnkang.extract(raw, URL)
        for key, value in [('formattext_evidence', {}), ('source_dom_text', 'changed'),
                           ('pager_removals', [{'removed':'fake'}]), ('cnkang_parser_version', 'old')]:
            changed = copy.deepcopy(doc)
            changed[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'mismatch'):
                cnkang.audit(raw, URL, changed)


if __name__ == '__main__':
    unittest.main()
