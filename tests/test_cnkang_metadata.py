"""Q3 metadata oracles are explicit source labels, not clinical author verification."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cnkang

URL = 'https://www.cnkang.com/jibing/test/123.html'


def page(body, byline='', meta=''):
    return (f'<html><head><meta charset="utf-8">{meta}<title>湿疹的治疗_中华康网</title></head>'
            f'<body><h1 id="h1title">湿疹的治疗</h1><p>2020-01-02</p>{byline}'
            f'<div id="endText">{body}</div></body></html>').encode('utf-8')


class MetadataTests(unittest.TestCase):
    def test_explicit_byline_reviewer_and_sidebar_have_separate_roles(self):
        raw = page('<p>湿疹需要治疗。</p>',
                   '<aside class="sidebar">作者：广告医生</aside>'
                   '<p>作者：张三<br>审核：李四</p>')
        doc = cnkang.extract(raw,URL)
        self.assertEqual(doc['author'],'张三')
        self.assertEqual([(a['name'],a['role']) for a in doc['attributions']],
                         [('张三','article_author'),('李四','reviewer')])
        for a in doc['attributions']:
            self.assertTrue(a['path'].startswith('/html/body/'))
            self.assertIn(a['name'],a['quote'])
        cnkang.audit(raw,URL,doc)

    def test_multiple_explicit_meta_authors_preserve_all_names(self):
        doc = cnkang.extract(page('湿疹。',meta='<meta name="AUTHOR" content="张三；李四">'),URL)
        self.assertEqual(doc['author'],'张三; 李四')
        self.assertEqual(len(doc['attributions']),2)

    def test_quoted_people_headings_and_doctor_sidebar_are_not_authors(self):
        raw = page('<p>患者：朋友王五说治疗有效。</p><p>治疗方法：保持清洁。</p>'
                   '<p>文章引用李医生的意见。</p>', '<aside>作者：某某</aside>')
        doc = cnkang.extract(raw,URL)
        self.assertIsNone(doc['author'])
        self.assertFalse(doc['attributions'])

    def test_real_respondents_are_not_article_authors_and_have_raw_locators(self):
        fixtures = ROOT/'tests/fixtures/cnkang_q3'
        cases = json.loads((fixtures/'manifest.json').read_text(encoding='utf-8'))['cases']
        for case in cases:
            expected = case['expected']
            if 'respondent' not in expected: continue
            with self.subTest(id=case['id']):
                raw=(fixtures/case['file']).read_bytes()
                doc=cnkang.extract(raw,case['url'],case['content_type'])
                matches=[a for a in doc['attributions'] if a['role']=='respondent' and a['name']==expected['respondent']]
                self.assertTrue(matches)
                self.assertIsNone(doc['author'])
                decoded,_=cnkang.decode_bytes(raw,case['content_type'])
                tree=cnkang.html.fromstring(decoded)
                self.assertIn(expected['respondent'],''.join(tree.xpath(matches[0]['path'])[0].itertext()))

    def test_metadata_tampering_is_audit_failure(self):
        raw=page('<p>湿疹需要治疗。</p>','<p>作者：张三</p>')
        doc=cnkang.extract(raw,URL)
        for field,value in [('author','李四'),('published_at','2030-01-01'),('source_name','伪造')]:
            changed=copy.deepcopy(doc);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):cnkang.audit(raw,URL,changed)
        for field,value in [('name','李四'),('role','reviewer'),('path','/html/body/aside')]:
            changed=copy.deepcopy(doc);changed['attributions'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):cnkang.audit(raw,URL,changed)

    def test_named_quote_after_patient_is_not_misattributed_as_respondent(self):
        doc=cnkang.extract(page('<p>患者：请问如何治疗？</p><blockquote><p>张三：本品包治。</p></blockquote>'),URL)
        self.assertEqual([(a['name'],a['role']) for a in doc['attributions']],[('张三','quoted_person')])
        self.assertIsNone(doc['author'])


if __name__=='__main__': unittest.main()
