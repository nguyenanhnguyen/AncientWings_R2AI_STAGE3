"""Behavioral coverage for the shared cnkang parser, transport, sampling and resume."""
import ast
import base64
from contextlib import redirect_stdout
import io
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import pyarrow as pa
import pyarrow.parquet as pq
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cnkang
import cnkang_check as check
import cnkang_transport as transport

TEXT = '这是一段正文内容，保留医学术语和完整的段落顺序，不应拼入页面导航或广告。'
URL = 'http://www.cnkang.com/myjk/202001/1.html'


def page(body=None, encoding='utf-8', template='endText'):
    body = body or ''.join(f'<p>{TEXT}{i}</p>' for i in range(8))
    return (f'<html><head><meta charset="{encoding}"><title>正文标题</title></head><body>'
            f'<h1 id="h1title">正文标题</h1><p>来源：医院 2020-01-02</p>'
            f'<div id="{template}">{body}</div></body></html>').encode(encoding)


def response(status=200, body=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = page() if body is None else body
    r.headers.update(headers or {'Content-Type':'text/html; charset=utf-8'})
    return r


class ParserTests(unittest.TestCase):
    def test_strict_encoding_and_table_inline_order(self):
        for encoding in ('utf-8', 'gb2312', 'gb18030'):
            raw = page('<p>正文<a>中文</a>链接</p><table><tr><td>BRCA1</td><td>50mg</td></tr></table>',
                       encoding=encoding)
            doc = cnkang.extract(raw, URL, 'text/html')
            self.assertIn('正文中文链接', doc['text'])
            self.assertIn('BRCA1', doc['text'])
            self.assertEqual(len(doc['tables']), 1)
            self.assertFalse(doc['encoding_uncertain'])
            self.assertTrue(any(c['strict_valid'] for c in doc['encoding_candidates']))

    def test_duplicate_synopsis_same_line_preserves_body_and_evidence(self):
        anchor = TEXT * 2
        before = f'核心提示：{anchor[:35]}……{anchor}下一段保持不变。'
        after, actions = cnkang.deduplicate_intro(before)
        self.assertEqual(after, anchor + '下一段保持不变。')
        self.assertEqual(len(actions), 1)
        plain = '核心提示：只是摘要但没有重复……这是真正的新内容。'
        self.assertEqual(cnkang.deduplicate_intro(plain), (plain, []))

    def test_english_numeric_url_are_not_encoding_errors(self):
        text = 'Abstract: This study explores clinical outcomes.\nKeywords: BRCA1\n50 mg 20 kcal\nhttps://example.org/paper\n'
        doc = cnkang.extract(page('<p>'+text+'</p>'), URL)
        self.assertNotIn('CORRUPT_TEXT_REVIEW', doc['parser_flags'])
        self.assertNotIn('ENCODING_UNCERTAIN_REVIEW', doc['parser_flags'])

    def test_pua_fragment_vs_isolated_pua(self):
        for content, expected in (('文字\ue111?/P>损坏', 'CORRUPT_TEXT_REVIEW'),
                                  ('完整文字结尾\ue111', 'PUA_FORMATTING_REVIEW')):
            doc = cnkang.extract(page('<p>'+content+'</p>'), URL)
            self.assertIn(expected, doc['parser_flags'])
            if expected == 'PUA_FORMATTING_REVIEW':
                self.assertNotIn('CORRUPT_TEXT_REVIEW', doc['parser_flags'])

    def test_nested_conmain_metadata_and_parallel_ambiguity(self):
        raw = ('<html><title>页面</title><div class="conmain"><h1>正文标题</h1>'
               '<p>来源：医院 2024-10-01</p><div><section><article>' +
               ''.join(f'<p>{TEXT}{i}</p>' for i in range(20)) +
               '</article></section></div></div></html>').encode()
        doc = cnkang.extract(raw, URL)
        self.assertEqual(doc['template'], 'conmain')
        self.assertIn('/article', doc['selector'])
        self.assertEqual(doc['date_candidates'], ['2024-10-01'])
        self.assertEqual(doc['heading_title'], '正文标题')
        self.assertNotIn('来源', doc['text'])
        raw = ('<html><div class="conmain"><h1>标题</h1><section>' +
               TEXT*10 + '</section><section>' + TEXT*10 + '</section></div></html>').encode()
        doc = cnkang.extract(raw, URL)
        self.assertIn('AMBIGUOUS_BODY_REVIEW', doc['parser_flags'])
        self.assertEqual(doc['text'].count(TEXT), 20)
        # A 75% body must not silently discard a parallel 25% region.
        raw = ('<html><div class="conmain"><section>'+TEXT*30+
               '</section><section>'+TEXT*10+'</section></div></html>').encode()
        doc=cnkang.extract(raw, URL)
        self.assertIn('AMBIGUOUS_BODY_REVIEW',doc['parser_flags'])
        self.assertEqual(doc['text'].count(TEXT),40)

    def test_incomplete_date_does_not_make_fetch_failed_and_raw_audit(self):
        raw = page()
        doc = cnkang.extract(raw, URL)
        self.assertEqual(doc['quality_status'], 'accepted')
        self.assertTrue(cnkang.audit(raw, URL, doc)['cnkang_raw_reextraction_verified'])
        doc['text'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'mismatch'): cnkang.audit(raw, URL, doc)


class SamplingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.parquet'
        rows = [{'id':i, 'url':f"http://www.cnkang.com/b{i%15}/{i}.html"}
                for i in range(800)]
        rows += [{'id':900,'url':'https://cnkang.com/b0/0.html#fragment'},
                 {'id':901,'url':'https://evilcnkang.com/b0/999.html'},
                 {'id':902,'url':'https://cnkang.com/index.htm'}]
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([('id',pa.int64()),('url',pa.string())])), self.source)
        self.history = self.root/'review.jsonl'
        check.jsonl(self.history,[{'url':'http://cnkang.com/b1/1.html'}])
        self.config = {'parquet_path':str(self.source),'target':500,'seed':20261020,
                       'history_paths':[str(self.history)],'history_complete':True}

    def test_exact_500_all_branches_history_ids_and_resume_immutable(self):
        out = self.root/'run'
        samples, summary = check.prepare(self.config, out)
        self.assertEqual(len(samples),500)
        self.assertEqual(len({r['canonical_url'] for r in samples}),500)
        self.assertEqual(len({r['branch'] for r in samples}),15)
        self.assertNotIn('cnkang.com/b1/1.html', {r['canonical_url'] for r in samples})
        self.assertEqual(summary['profile']['excluded_not_detail_html'],1)
        population, _ = check.read_population(self.source)
        self.assertEqual(population['cnkang.com/b0/0.html']['ids'],[0,900])
        raw = (out/'sample_manifest.jsonl').read_bytes()
        with patch.object(check,'read_population',side_effect=AssertionError('must not resample')):
            resumed, _ = check.prepare(self.config,out)
        self.assertEqual(samples,resumed)
        self.assertEqual(raw,(out/'sample_manifest.jsonl').read_bytes())
        with self.assertRaisesRegex(ValueError,'Code/config changed'):
            check.prepare(dict(self.config,seed=123),out)

    def test_missing_history_is_explicit_and_empty_exports_parse(self):
        out = self.root/'blocked'
        config = dict(self.config,history_paths=[],history_complete=False)
        samples, state = check.prepare(config,out)
        self.assertEqual(samples,[])
        self.assertEqual(state['state'],'history_required')
        summary = check.export(out,samples,state)
        self.assertEqual(summary['selected'],0)
        self.assertEqual(pq.read_table(out/'results.parquet').num_rows,0)
        self.assertEqual(pq.read_table(out/'results.parquet').schema,check.RESULT_SCHEMA)
        for name in ('config.json','sample_manifest.jsonl','sampling_summary.csv','history_summary.json',
                     'robots_checks.json','crawl_journal.jsonl','results.jsonl','results.parquet',
                     'review.csv','summary_by_branch.csv','review_report.md'):
            self.assertTrue((out/name).exists(),name)
        # The empty manifest must not prevent adding history and selecting a real sample later.
        samples,state=check.prepare(self.config,out)
        self.assertEqual(len(samples),500)

    def test_allocation_small_branches_capacity_and_lowered_floor(self):
        allocation, baseline=check.allocate({'large':1000,'small':3,'medium':40},500)
        self.assertEqual(sum(allocation.values()),500)
        self.assertEqual(allocation['small'],3)
        allocation,baseline=check.allocate({str(i):10 for i in range(80)},500)
        self.assertLess(baseline,10)
        self.assertTrue(all(n>=1 for n in allocation.values()))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp')
        self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name)
        self.net=transport.Transport(self.out)
        self.addCleanup(self.net.close)
        self.sample={'id':1,'ids':[1],'source_url':URL,'url':URL,
                     'canonical_url':check.canonical(URL),'branch':'myjk'}
        self.sleep=patch.object(self.net,'wait')
        self.sleep.start(); self.addCleanup(self.sleep.stop)

    def test_success_checkpoint_and_resume_without_network(self):
        replies=[response(200,b'User-agent: *\nAllow: /\n',{'Content-Type':'text/plain'}),response()]
        with patch.object(self.net,'get',side_effect=replies) as get:
            r=self.net.fetch(self.sample)
        self.assertEqual(r['crawl_status'],'parsed')
        self.assertEqual(get.call_count,2)
        self.assertTrue((self.out/r['raw_html_path']).is_file())
        with patch.object(check.transport_module.Transport,'fetch',side_effect=AssertionError('already done')):
            check.run(self.out,[self.sample],{})

    def test_403_never_falls_back_and_unknown_robots_not_allowed(self):
        replies=[response(200,b'User-agent: *\nAllow: /\n',{'Content-Type':'text/plain'}),
                 response(403,b'<html>Denied</html>')]
        with patch.object(self.net,'get',side_effect=replies) as get:
            r=self.net.fetch(self.sample)
        self.assertEqual(r['http_status'],403)
        self.assertEqual(len(r['requests']),1)
        self.assertTrue(all(call.args[0].startswith('https:') for call in get.call_args_list))
        self.net.policies.clear()
        with patch.object(self.net,'get',return_value=response(503,b'error')):
            r=self.net.fetch(dict(self.sample,id=2))
        self.assertIsNone(r['robots']['allowed'])
        self.assertEqual(r['requests'],[])

    def test_timeout_fallback_checks_http_origin_and_long_429_persists(self):
        robots=response(200,b'User-agent: *\nAllow: /\n',{'Content-Type':'text/plain'})
        calls=[]
        def get(url):
            calls.append(url)
            if url.endswith('/robots.txt'):return robots
            if url.startswith('https:'):raise requests.Timeout('test timeout')
            return response()
        with patch.object(self.net,'get',side_effect=get):
            r=self.net.fetch(self.sample)
        self.assertEqual(r['status'],'extracted')
        self.assertIn('http://www.cnkang.com/robots.txt',calls)
        self.net.policies.clear()
        with patch.object(self.net,'get',side_effect=[
            robots,response(429,b'Busy',{'Retry-After':'600','Content-Type':'text/html'})]):
            r=self.net.fetch(dict(self.sample,id=2))
        self.assertTrue(self.net.stopped)
        state=json.loads((self.out/'cnkang_transport_state.json').read_text())
        self.assertGreater(state['not_before'],state.get('last_request',0))
        new=transport.Transport(self.out)
        try:
            with self.assertRaises(transport.Paused):new.wait()
        finally:new.close()
        original=(self.out/'records/2.json').read_bytes()
        with patch.object(check.transport_module.Transport,'fetch',side_effect=AssertionError('cooldown active')):
            check.run(self.out,[dict(self.sample,id=2)],{})
        self.assertEqual(original,(self.out/'records/2.json').read_bytes())
        # After expiry, retry only the deferred URL, preserving completed pages.
        state['not_before']=0
        state['last_request']=0
        transport.write_json(self.out/'cnkang_transport_state.json',state)
        with patch.object(check.transport_module.Transport,'fetch',return_value={
            'status':'extracted','crawl_status':'parsed','http_status':200}) as fetch:
            check.run(self.out,[self.sample,dict(self.sample,id=2)],{})
        self.assertEqual(fetch.call_count,1)
        self.assertEqual(fetch.call_args.args[0]['id'],2)

    def test_challenge_200_is_not_success(self):
        robots=response(200,b'User-agent: *\nAllow: /\n',{'Content-Type':'text/plain'})
        with patch.object(self.net,'get',side_effect=[robots,response(200,b'<html><title>Just a moment</title>checking your browser</html>')]):
            r=self.net.fetch(self.sample)
        self.assertEqual(r['crawl_status'],'fetch_failed')
        self.assertTrue(r['challenge_detected'])
        summary=check.export(self.out,[self.sample])
        self.assertEqual(summary['fetch_failed'],1)
        self.assertEqual(r['text_sha256'],cnkang.sha(r['text']))


class NotebookTests(unittest.TestCase):
    def test_schema_syntax_hashes_and_shared_snapshots(self):
        import nbformat
        values={}
        for filename in ('check_cnkang.com.ipynb','crawl_corpus_kaggle_hf_upload.ipynb',
                         'crawl_domain_samples.ipynb'):
            nb=json.loads((ROOT/'notebooks'/filename).read_text(encoding='utf-8'))
            nbformat.validate(nb)
            values[filename]={}
            for cell in nb['cells']:
                if cell['cell_type']!='code':continue
                source=''.join(cell['source']);compile(source,filename,'exec')
                for node in ast.parse(source).body:
                    if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name):
                        key=node.targets[0].id
                        if key in ('PAYLOADS','HASHES','EMBEDDED_FILES','EMBEDDED_SHA256',
                                   'CNKANG_PAYLOAD','CNKANG_SHA256'):
                            values[filename][key]=ast.literal_eval(node.value)
        main=values['crawl_corpus_kaggle_hf_upload.ipynb']
        checknb=values['check_cnkang.com.ipynb']
        for name in ('cnkang_snapshot.py','cnkang_transport_snapshot.py'):
            self.assertEqual(main['EMBEDDED_SHA256'][name],checknb['HASHES'][name])
            body=zlib.decompress(base64.b85decode(checknb['PAYLOADS'][name]))
            self.assertEqual(cnkang.sha(body),checknb['HASHES'][name])


if __name__=='__main__':
    unittest.main()
