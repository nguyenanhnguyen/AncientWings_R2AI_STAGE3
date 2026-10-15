"""120ask V2 thread extraction, QC, routing and notebook snapshot regressions."""
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import pyarrow as pa
import pyarrow.parquet as pq

from test_notebook_selenium_fallback import assignments, load_module


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/fixtures/120ask'


def fixture(identifier):
    return (FIXTURES / f'{identifier}.html').read_bytes()


def page(title='示例问题', question='健康咨询描述：这是用于测试的患者问题，包含足够的信息。', cards='', replies=1):
    return (f'''<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head><body>
<h1 id="d_askH1">{title}</h1><div id="d_msCon"><p>{question}</p></div><span>{replies}人回复</span>
<div class="b_answerbox">{cards}</div></body></html>''').encode()


def card(doctor, main, followups=''):
    return f'''<div class="b_answerli"><div class="b_answertl"><span class="b_sp1"><a>{doctor}</a></span></div>
<div class="b_anscont_cont"><div class="crazy_new" id="reply-{doctor}"><p>{main}</p></div>{followups}</div></div>'''


class Ask120ParserV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp')
        cls.root = Path(cls.temp.name)
        main = json.loads((ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb').read_text(encoding='utf-8'))
        cls.main_config = ''.join(main['cells'][2]['source'])
        cls.main_setup = ''.join(main['cells'][6]['source'])
        pack = assignments(cls.main_setup)
        for name in ('crawler_snapshot.py', 'ask120_snapshot.py', 'audit_snapshot.py', 'export_snapshot.py'):
            body = zlib.decompress(base64.b85decode(pack['EMBEDDED_FILES'][name]))
            if hashlib.sha256(body).hexdigest() != pack['EMBEDDED_SHA256'][name]:
                raise AssertionError('Snapshot hash mismatch: ' + name)
            (cls.root / name).write_bytes(body)
        domain = json.loads((ROOT / 'notebooks/crawl_domain_samples.ipynb').read_text(encoding='utf-8'))
        cls.domain_config = ''.join(domain['cells'][3]['source'])
        cls.domain_setup = ''.join(domain['cells'][7]['source'])
        domain_pack = assignments(cls.domain_setup)
        for payload, digest, name in (
            ('CRAWLER_PAYLOAD', 'CRAWLER_SHA256', 'domain_crawler.py'),
            ('ASK120_PAYLOAD', 'ASK120_SHA256', 'domain_ask120.py'),
        ):
            body = zlib.decompress(base64.b85decode(domain_pack[payload]))
            if hashlib.sha256(body).hexdigest() != domain_pack[digest]:
                raise AssertionError('Domain snapshot hash mismatch: ' + name)
            (cls.root / name).write_bytes(body)
        # The domain crawler resolves the parser next to itself under this fixed name.
        (cls.root / 'ask120_snapshot.py').write_bytes((cls.root / 'domain_ask120.py').read_bytes())
        cls.parser = load_module('ask120_v2_parser', cls.root / 'ask120_snapshot.py')
        cls.crawler = load_module('ask120_v2_crawler', cls.root / 'crawler_snapshot.py')
        cls.domain_crawler = load_module('ask120_v2_domain_crawler', cls.root / 'domain_crawler.py')
        cls.audit = load_module('ask120_v2_audit', cls.root / 'audit_snapshot.py')
        cls.export_source = (cls.root / 'export_snapshot.py').read_text(encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_three_manually_expected_fixtures_keep_7_answers_and_10_followups(self):
        expected = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
        totals = {'main': 0, 'followups': 0, 'patient': 0, 'doctor': 0, 'tails': 0}
        for identifier, counts in expected.items():
            with self.subTest(identifier=identifier):
                doc = self.parser.extract(
                    fixture(identifier), f'https://www.120ask.com/question/{identifier}.htm',
                    'text/html; charset=utf-8')
                self.assertEqual(doc['main_answer_count'], counts['main_answers'])
                self.assertEqual(doc['followup_count'], counts['followups'])
                self.assertEqual(doc['patient_followups'], counts['patient_followups'])
                self.assertEqual(doc['doctor_followups'], counts['doctor_followups'])
                self.assertEqual(doc['ask120_review_reasons'], [])
                self.assertTrue(doc['ask120_access_pass'])
                self.assertEqual(doc['ask120_qc']['scope'], 'observable_html_only')
                totals['main'] += doc['main_answer_count']
                totals['followups'] += doc['followup_count']
                totals['patient'] += doc['patient_followups']
                totals['doctor'] += doc['doctor_followups']
                totals['tails'] += doc['removed_template_tails']
        self.assertEqual(totals, {'main': 7, 'followups': 10, 'patient': 5, 'doctor': 5, 'tails': 1})

    def test_thread_order_doctor_assignment_and_page_furniture_exclusion(self):
        doc = self.parser.extract(fixture('74708648'),
                                  'https://www.120ask.com/question/74708648.htm', 'text/html')
        self.assertEqual([thread['doctor'] for thread in doc['ask120_threads']], ['陈医生', '孙医生'])
        self.assertEqual([turn['role'] for turn in doc['ask120_threads'][0]['turns']],
                         ['doctor_answer', 'patient_followup', 'doctor_followup',
                          'patient_followup', 'doctor_followup'])
        self.assertEqual([turn['role'] for turn in doc['ask120_threads'][1]['turns']],
                         ['doctor_answer', 'patient_followup', 'doctor_followup',
                          'patient_followup', 'doctor_followup'])
        first_followup = doc['text'].index('空腹时也会反酸')
        second_doctor = doc['text'].index('少量多餐并记录')
        self.assertLess(first_followup, second_doctor)
        for unwanted in ('其他类似问题', '相关药品', '主任 已帮助多人', '二维码'):
            self.assertNotIn(unwanted, doc['text'])

    def test_tail_removal_is_anchored_doctor_only_and_title_specific(self):
        exact = '先观察症状。以上是对“示例问题”这个问题的建议，希望对您有帮助，祝您健康！'
        patient = ('<div class="b_ansaddli"><span class="b_ansaddti">追问</span>'
                   '<p>以上是对“示例问题”这个问题的建议，希望对您有帮助，祝您健康！</p></div>')
        doctor = ('<div class="b_ansaddli"><span class="b_docaddti">回答</span>'
                  '<p>以上是对“示例问题”这个问题的建议，希望对您有帮助，祝您健康！之后还要复诊。</p></div>')
        doc = self.parser.extract(page(cards=card('甲医生', exact, patient + doctor)),
                                  'https://120ask.com/question/1.htm', 'text/html')
        self.assertEqual(doc['removed_template_tails'], 1)
        self.assertIn('先观察症状。', doc['text'])
        self.assertIn('患者追问 1：\n以上是对“示例问题”', doc['text'])
        self.assertIn('之后还要复诊。', doc['text'])
        self.assertIn('祝您健康！', doc['ask120_text_raw'])

    def test_equal_text_in_two_threads_is_reported_but_not_deduplicated(self):
        answer = '相同的合法医学建议，需要在两个医生线程中分别保留。'
        doc = self.parser.extract(page(cards=card('甲医生', answer) + card('乙医生', answer), replies=2),
                                  'https://www.120ask.com/question/2.htm', 'text/html')
        self.assertEqual(doc['main_answer_count'], 2)
        self.assertEqual(doc['text'].count(answer), 2)
        self.assertEqual(doc['ask120_qc']['duplicate_turn_groups'], 1)

    def test_unknown_unrecognized_and_orphan_followups_are_visible_to_qc(self):
        followups = (
            '<div class="b_ansaddli"><p>角色标签缺失但内容必须保留。</p></div>'
            '<div class="b_ansaddli"><span class="b_docaddti">回答</span><div>没有直接的 p 结构</div></div>'
        )
        orphan = '<div class="b_ansaddli"><span class="b_ansaddti">追问</span><p>无法归属医生。</p></div>'
        body = page(cards=card('甲医生', '这是长度足够的主要回答内容，用于验证异常结构。', followups) + orphan)
        doc = self.parser.extract(body, 'https://www.120ask.com/question/3.htm', 'text/html')
        self.assertIn('角色标签缺失但内容必须保留。', doc['text'])
        self.assertEqual(doc['unknown_roles'], 1)
        self.assertEqual(doc['ask120_qc']['unrecognized_followup_blocks'], 1)
        self.assertEqual(doc['ask120_qc']['orphan_followups'], 1)
        self.assertIn('ask120_unknown_followup_role', doc['ask120_review_reasons'])
        self.assertIn('ask120_unrecognized_followup_structure', doc['ask120_review_reasons'])
        self.assertIn('ask120_orphan_followup', doc['ask120_review_reasons'])

    def test_exact_route_and_short_valid_page_are_accepted_in_both_notebooks(self):
        body = fixture('104875176')
        for crawler in (self.crawler, self.domain_crawler):
            with self.subTest(crawler=crawler.__name__):
                doc = crawler.extract(body, 'text/html; charset=utf-8',
                                      'https://www.120ask.com/question/104875176.htm')
                self.assertEqual(doc['extractor'], '120ask_qa_dom_v2')
                self.assertLess(len(doc['text']), 300)
                self.assertEqual(crawler.quality(doc)['quality_status'], 'accepted')
        other_path = self.crawler.extract(body, 'text/html', 'https://www.120ask.com/article/104875176.htm')
        other_host = self.crawler.extract(body, 'text/html', 'https://ask.120ask.com/question/104875176.htm')
        self.assertNotEqual(other_path['extractor'], '120ask_qa_dom_v2')
        self.assertNotEqual(other_host['extractor'], '120ask_qa_dom_v2')

    def test_challenge_missing_content_and_home_redirect_do_not_become_accepted(self):
        challenge = b'<html><head><title>Just a moment...</title></head><body><h1>Checking your browser</h1></body></html>'
        doc = self.crawler.extract(challenge, 'text/html', 'https://www.120ask.com/question/4.htm')
        quality = self.crawler.quality(doc)
        self.assertEqual(quality['quality_status'], 'rejected')
        self.assertIn('error_or_challenge', quality['quality_flags'])
        missing_body = '<html><meta charset="utf-8"><h1 id="d_askH1">只有标题</h1></html>'.encode()
        missing = self.crawler.extract(missing_body,
                                       'text/html', 'https://www.120ask.com/question/5.htm')
        self.assertNotEqual(self.crawler.quality(missing)['quality_status'], 'accepted')
        record = {'url': 'https://www.120ask.com/question/5.htm',
                  'final_url': 'https://www.120ask.com/', 'quality_status': 'accepted', 'quality_flags': []}
        self.crawler.flag_redirect(record)
        self.assertEqual(record['quality_status'], 'review')
        self.assertIn('redirect_review', record['quality_flags'])
        canonical = {'url': 'https://120ask.com/question/5.htm',
                     'final_url': 'https://www.120ask.com/question/5.htm',
                     'quality_status': 'accepted', 'quality_flags': []}
        self.crawler.flag_redirect(canonical)
        self.assertEqual(canonical['quality_status'], 'accepted')
        wrong_question = {'url': 'https://www.120ask.com/question/5.htm',
                          'final_url': 'https://www.120ask.com/question/6.htm',
                          'quality_status': 'accepted', 'quality_flags': []}
        self.crawler.flag_redirect(wrong_question)
        self.assertEqual(wrong_question['quality_status'], 'review')

    def test_raw_audit_checks_threads_qc_and_preclean_hash(self):
        body = fixture('71762369')
        url = 'https://www.120ask.com/question/71762369.htm'
        record = self.parser.extract(body, url, 'text/html; charset=utf-8')
        details = self.parser.audit(body, url, record, 'text/html; charset=utf-8')
        self.assertTrue(details['ask120_raw_reextraction_verified'])
        damaged = json.loads(json.dumps(record, ensure_ascii=False))
        damaged['ask120_threads'][0]['turns'][0]['text'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'ask120_threads'):
            self.parser.audit(body, url, damaged, 'text/html; charset=utf-8')

    def test_resume_guard_and_export_schema_preserve_old_records_and_compact_contract(self):
        self.assertIn('HAS_ASK120_SAMPLE = False', self.main_setup)
        self.assertIn("('ask120_snapshot.py', 'ask120_sha256')", self.main_setup)
        self.assertIn('không tự thay text/checkpoint đã trích bằng parser cũ', self.main_setup)
        self.assertIn("ask120_path = RUN_DIR / 'ask120_snapshot.py'", self.domain_setup)
        self.assertIn('120ask parser changed; use a new run and RECOVERY_RUN_DIR', self.domain_setup)
        self.assertNotIn("'ask120_threads'", self.export_source)
        self.assertIn("'raw_path', 'raw_sha256', 'text_sha256'", self.export_source)

    def test_live_smoke_helper_unpacks_the_parser_dependency(self):
        helper = load_module('ask120_v2_smoke_helper', ROOT / 'scripts/check_120ask.py')
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            crawler, probe, hashes = helper.snapshots(
                ROOT / 'notebooks/crawl_corpus_kaggle_hf_upload.ipynb', Path(directory))
            self.assertTrue(callable(crawler.extract))
            self.assertTrue(hasattr(probe, 'request_record'))
            self.assertIn('ask120_snapshot.py', hashes)
            self.assertTrue((Path(directory) / 'ask120_snapshot.py').is_file())

    def test_requests_proxy_inheritance_is_explicit_and_configurable(self):
        self.assertIn('REQUESTS_TRUST_ENV = False', self.main_config)
        self.assertIn('REQUESTS_TRUST_ENV = False', self.domain_config)
        self.assertIn('crawler.TRUST_ENV = REQUESTS_TRUST_ENV', self.domain_setup)
        original = self.crawler.TRUST_ENV
        session = None
        try:
            self.crawler.TRUST_ENV = False
            fetcher = self.crawler.Fetcher(self.root, delay=0, attempts=1)
            session = fetcher.session()
            self.assertFalse(session.trust_env)
        finally:
            if session is not None:
                session.close()
            self.crawler.TRUST_ENV = original

    def test_full_corpus_auditor_reextracts_120ask_raw_and_reports_counts(self):
        with tempfile.TemporaryDirectory(dir=self.root) as directory:
            out = Path(directory)
            (out / 'records').mkdir()
            (out / 'raw').mkdir()
            identifier = 71762369
            url = f'https://www.120ask.com/question/{identifier}.htm'
            source = out / 'source.parquet'
            pq.write_table(pa.Table.from_pylist([{'id': identifier, 'url': url}]), source)
            self.crawler.jsonl(out / 'sample.jsonl', [{'id': identifier, 'url': url}])
            self.crawler.write_json(out / 'manifest.json', {
                'sample_sha256': self.crawler.file_hash(out / 'sample.jsonl'),
                'source': str(source), 'source_sha256': self.crawler.file_hash(source),
            })
            body = fixture(str(identifier))
            doc = self.parser.extract(body, url, 'text/html; charset=utf-8')
            raw_path = Path('raw/page.gz')
            (out / raw_path).write_bytes(gzip.compress(body, mtime=0))
            record = {
                'id': identifier, 'url': url, 'final_url': url, 'status': 'extracted',
                'quality_status': 'accepted', 'quality_flags': [],
                'content_type': 'text/html; charset=utf-8',
                'raw_path': raw_path.as_posix(), 'raw_sha256': hashlib.sha256(body).hexdigest(),
                'text_sha256': hashlib.sha256(doc['text'].encode()).hexdigest(), **doc,
            }
            self.crawler.write_json(out / f'records/{identifier}.json', record)
            (out / 'ask120_snapshot.py').write_bytes((self.root / 'ask120_snapshot.py').read_bytes())
            with patch.object(sys, 'argv', ['audit', '--out', str(out), '--source', str(source)]), \
                    redirect_stdout(io.StringIO()):
                self.audit.main()
            summary = json.loads((out / 'audit_summary.json').read_text(encoding='utf-8'))
            self.assertEqual(summary['ask120_raw_records_verified'], 1)
            self.assertEqual(summary['ask120_main_answers_verified'], 4)
            self.assertEqual(summary['ask120_followups_verified'], 2)


if __name__ == '__main__':
    unittest.main()
