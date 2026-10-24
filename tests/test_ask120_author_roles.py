"""F2: conversation position does not establish an author's profession."""
import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ask120
import ask120_gate as gate

URL = 'https://www.120ask.com/question/123.htm'
ANSWER = '这是一段完整的来源回答，必须保留原文和对话关系，同时不能从昵称猜测作者的职业。'
FIXTURES = ROOT / 'tests/fixtures/120ask_f2'


def body(qualification='主治医师', name='张甲', extra='', followups=''):
    return ('<html><meta charset="utf-8"><h1 id="d_askH1">真实问题</h1>'
            '<div id="d_msCon">健康咨询描述：患者提供了足够的症状和检查背景，希望了解如何复查。</div>'
            '<span>1人回复</span><div class="b_answerbox"><div class="b_answerli">'
            '<div class="b_answertl"><span class="b_sp1">'
            f'<a href="//www.120ask.com/user/p/abc">{name}</a> {qualification}</span></div>'
            f'<div class="b_anscont_cont"><p id="reply123">{ANSWER}</p>{extra}{followups}</div>'
            '</div></div></html>').encode()


def parse(raw, metadata=None):
    data = dict(metadata or {})
    data.setdefault('id', 1)
    data.setdefault('url', URL)
    data.update(access_status='VAO_DUOC', raw_path='raw/1.gz', raw_sha256=ask120.sha(raw),
                parser_sha256='test-parser', policy_sha256='test-policy')
    page = gate.parse_source_response(raw, data)
    page['thread_decisions'] = [gate.review_thread(t, page, gate.POLICY) for t in page['ask120_threads']]
    return page


class AuthorRoleTests(unittest.TestCase):
    def test_conversation_roles_are_neutral_and_independent_of_profession(self):
        thread = parse(body())['thread_decisions'][0]
        turn = thread['turns'][0]
        self.assertEqual(turn['role'], 'responder_answer')
        self.assertEqual(turn['turn_kind'], 'answer')
        self.assertEqual(turn['speaker_role'], 'responder')
        self.assertEqual(thread['source_role'], 'physician')
        self.assertNotIn('doctor', thread)
        self.assertNotIn('医生回答', parse(body())['text'])

    def test_source_roles_and_default_admission(self):
        for qualification, role, decision in (
            ('某医院 主治医师', 'physician', 'INCLUDE'), ('医士', 'physician', 'INCLUDE'),
            ('医生', 'physician', 'INCLUDE'), ('副主任护师', 'nurse', 'INCLUDE'),
            ('护士', 'nurse', 'INCLUDE'), ('主管中药师', 'pharmacist', 'INCLUDE'),
            ('药士', 'pharmacist', 'INCLUDE'), ('二级心理咨询师', 'psychologist', 'REVIEW'),
            ('三级检验师', 'laboratory_professional', 'REVIEW'), ('其他', 'other', 'REVIEW'),
            ('', 'unknown', 'REVIEW'), ('主任', 'unknown', 'REVIEW'),
            ('白医生门诊部', 'unknown', 'REVIEW'), ('不是 医师', 'unknown', 'REVIEW'),
            ('医师 药师', 'unknown', 'REVIEW'),
        ):
            with self.subTest(qualification=qualification):
                thread = parse(body(qualification))['thread_decisions'][0]
                self.assertEqual(thread['qualification_raw'], qualification)
                self.assertEqual(thread['source_role'], role)
                self.assertEqual(thread['corpus_decision'], decision)

    def test_nickname_cannot_establish_a_profession(self):
        for name in ('开开心心医生', '张永斌医师', '60.221.216.128', '药师护士'):
            for qualification in ('其他', ''):
                with self.subTest(name=name, qualification=qualification):
                    thread = parse(body(qualification, name))['thread_decisions'][0]
                    self.assertEqual(thread['author_name'], name)
                    self.assertIn(thread['source_role'], ('other', 'unknown'))
                    self.assertEqual(thread['corpus_decision'], 'REVIEW')
                    self.assertIn('AUTHOR_ROLE_REVIEW', thread['decision_reasons'])

    def test_real_header_fixtures(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
        for case in manifest['cases']:
            with self.subTest(source_id=case['source_id']):
                raw = gzip.decompress((FIXTURES / case['raw_file']).read_bytes())
                self.assertEqual(ask120.sha(raw), case['raw_sha256'])
                page = parse(raw, dict(case, id=case['source_id']))
                thread = next(t for t in page['thread_decisions'] if t['thread_id'] == case['thread_id'])
                for key in ('author_name', 'source_role', 'qualification_title'):
                    self.assertEqual(thread[key], case[key])
                evidence = thread['author_evidence']
                tree, _, _ = ask120._tree(raw, case['content_type'])
                self.assertEqual(ask120.normalize(tree.xpath(evidence['header_dom_locator'])[0].text_content()), thread['header_raw'])
                self.assertEqual(evidence['credential_verification'], 'source_only')
                if case['source_role'] == 'other' and case['source_id'] != 1029798:
                    self.assertEqual(thread['corpus_decision'], 'REVIEW')

    def test_header_profile_and_qualification_are_preserved_with_provenance(self):
        thread = parse(body('某医院 主治医师'))['thread_decisions'][0]
        self.assertEqual(thread['author_name'], '张甲')
        self.assertEqual(thread['author_profile_url'], 'https://www.120ask.com/user/p/abc')
        self.assertEqual(thread['header_raw'], '张甲 某医院 主治医师')
        self.assertEqual(thread['qualification_raw'], '某医院 主治医师')
        self.assertEqual(thread['qualification_title'], '主治医师')
        self.assertEqual(thread['author_evidence']['attribution_status'], 'resolved')
        self.assertIn('b_sp1', thread['author_evidence']['header_html'])

    def test_multiple_replies_do_not_inherit_card_identity(self):
        page = parse(body(extra='<p id="reply456">' + ANSWER + '</p>'))
        self.assertEqual(len(page['thread_decisions']), 2)
        for thread in page['thread_decisions']:
            self.assertIsNone(thread['author_name'])
            self.assertEqual(thread['source_role'], 'unknown')
            self.assertEqual(thread['card_author']['source_role'], 'physician')
            self.assertEqual(thread['corpus_decision'], 'REVIEW')
            self.assertIn('REPLY_AUTHOR_REVIEW', thread['decision_reasons'])
            self.assertIsNone(thread['turns'][0]['author_name'])

    def test_missing_or_ambiguous_header_is_review(self):
        raw = body().decode()
        for changed in (
            raw.replace('<a href="//www.120ask.com/user/p/abc">张甲</a>', ''),
            raw.replace('张甲</a>', '张甲</a><a>李乙</a>'),
            raw.replace('class="b_sp1"', 'class="unknown_header"'),
        ):
            with self.subTest(changed=changed[:80]):
                thread = parse(changed.encode())['thread_decisions'][0]
                self.assertEqual(thread['corpus_decision'], 'REVIEW')
                self.assertEqual(thread['source_role'], 'unknown')

    def test_patient_does_not_inherit_responder_profession(self):
        followups = ('<div class="b_ansaddli"><span class="b_ansaddti"><em>患者甲</em>追问</span>'
                     '<p>患者提供新的情况，需要保留对话顺序。</p></div>'
                     '<div class="b_ansaddli"><span class="b_docaddti">补充回答</span>'
                     '<p>' + ANSWER + '</p></div>')
        thread = parse(body(followups=followups))['thread_decisions'][0]
        answer, patient, responder = thread['turns']
        self.assertEqual(patient['speaker_role'], 'patient')
        self.assertEqual(patient['turn_kind'], 'followup')
        self.assertEqual(patient['source_role'], 'unknown')
        self.assertNotEqual(patient['author_name'], answer['author_name'])
        self.assertEqual(responder['role'], 'responder_followup')
        self.assertEqual(responder['source_role'], 'physician')
        self.assertEqual(thread['corpus_decision'], 'INCLUDE')

    def test_different_followup_responder_requires_review(self):
        followup = ('<div class="b_ansaddli"><span class="b_docaddti"><em>另一位作者</em>回答</span>'
                    '<p>' + ANSWER + '</p></div>')
        thread = parse(body(followups=followup))['thread_decisions'][0]
        self.assertEqual(thread['turns'][1]['source_role'], 'unknown')
        self.assertEqual(thread['corpus_decision'], 'REVIEW')
        self.assertIn('AUTHOR_IDENTITY_REVIEW', thread['decision_reasons'])

    def test_conflicting_conversation_markers_do_not_inherit_profession(self):
        followup = ('<div class="b_ansaddli"><span class="b_docaddti">回答</span>'
                    '<span class="b_ansaddti">追问</span><p>' + ANSWER + '</p></div>')
        thread = parse(body(followups=followup))['thread_decisions'][0]
        self.assertEqual(thread['turns'][1]['speaker_role'], 'unknown')
        self.assertEqual(thread['turns'][1]['source_role'], 'unknown')
        self.assertEqual(thread['corpus_decision'], 'REVIEW')

    def test_candidate_sidecar_has_author_evidence_without_new_parquet_columns(self):
        page = parse(body('副主任护师'))
        doc = gate.build_candidate_document(page, page['thread_decisions'])
        self.assertEqual(doc['thread_authors'][0]['source_role'], 'nurse')
        self.assertEqual(doc['source_spans'][0]['author']['qualification_title'], '副主任护师')
        self.assertIn('来源职称：副主任护师', doc['text'])
        self.assertNotIn('医生回答', doc['text'])
        self.assertNotIn('thread_authors', gate.PRODUCTION_FIELDS)

    def test_raw_audit_detects_changed_qualification_metadata(self):
        raw = body()
        page = parse(raw)
        page['ask120_threads'][0]['qualification_raw'] = '伪造职称'
        with self.assertRaisesRegex(ValueError, 'ask120_threads'):
            ask120.audit(raw, URL, page)

    def test_manual_include_cannot_bypass_unresolved_author_role(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as directory:
            root = Path(directory)
            source, output = root / 'source', root / 'output'
            (source / 'raw').mkdir(parents=True)
            raw = body('其他', '开开心心医生')
            gate.write_json(source / 'manifest.json', {})
            gate.jsonl(source / 'sample.jsonl', [{'id':1, 'url':URL}])
            (source / 'raw/1.gz').write_bytes(gzip.compress(raw, mtime=0))
            gate.write_json(source / 'records/1.json', dict(id=1, url=URL, http_status=200,
                raw_path='raw/1.gz', raw_sha256=gate.sha(raw), content_type='text/html; charset=utf-8'))
            with patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected HTTP')):
                gate.replay(source, output)
                gate.build_outputs(output)
            import csv
            with (output / 'manual_review_sheet.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            rows[0].update(reviewer_decision='INCLUDE', reviewer_notes='Synthetic test label', reviewed_at='2026-10-20')
            labels = root / 'labels.csv'
            gate.save_csv(labels, rows, list(rows[0]))
            gate.build_outputs(output, manual_review_path=labels)
            self.assertEqual((output / 'corpus_candidates.jsonl').read_text(encoding='utf-8'), '')


if __name__ == '__main__':
    unittest.main()
