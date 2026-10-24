"""F1: template text is not a transcribed audio answer; real content survives."""
import gzip
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import ask120
import ask120_gate as gate
from test_ask120_corpus_gate import small_page

FIXTURES = ROOT / 'tests/fixtures/120ask_f1'
ACCEPT = '如果有了满意的回答请及时采纳，不要辜负了回答者！'
SPARE_TIME = '这里的医生都是用业余时间在这里回答问题的,请及时点击"采纳为答案",这是对他们热心帮助的唯一肯定.'
GREETING = '愿有病的人早日恢复健康，没病的人永远健康！'
GOOD = '转奶可以这样转：先在老的奶粉里添加三分之一的新奶粉，注意观察宝宝的反应，再逐步过渡。'
AUDIO = '<audio src="/voice.mp3">您的浏览器不支持 audio 元素。</audio>'
URL = 'https://www.120ask.com/question/123.htm'


def parsed_page(body, metadata=None):
    metadata = dict(metadata or {})
    metadata.setdefault('id', 42)
    metadata.setdefault('url', URL)
    metadata.update(access_status='VAO_DUOC', raw_sha256=ask120.sha(body),
                    raw_path='raw/test.gz', parser_sha256='test-parser', policy_sha256='test-policy')
    page = gate.parse_source_response(body, metadata)
    page['thread_decisions'] = [gate.review_thread(t, page, gate.POLICY) for t in page['ask120_threads']]
    return page


class AudioBoilerplateTests(unittest.TestCase):
    def test_all_nine_reviewed_real_mixed_replies(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['cases']), 9)
        for case in manifest['cases']:
            with self.subTest(source_id=case['source_id'], thread_id=case['thread_id']):
                body = gzip.decompress((FIXTURES / case['raw_file']).read_bytes())
                self.assertEqual(ask120.sha(body), case['raw_sha256'])
                page = parsed_page(body, dict(case, id=case['source_id']))
                thread = next(t for t in page['thread_decisions'] if t['thread_id'] == case['thread_id'])
                turn = thread['turns'][0]
                self.assertEqual(turn['text'], case['expected_text'])
                self.assertEqual(turn['answer_type'], case['expected_answer_type'])
                self.assertEqual(thread['corpus_decision'], case['expected_decision'])
                self.assertEqual(turn['raw_text_sha256'], ask120.sha(turn['raw_text']))
                self.assertEqual(turn['clean_text_sha256'], ask120.sha(turn['text']))
                self.assertTrue(turn['media_urls'])
                if not case['expected_text']:
                    self.assertIn('AUDIO_ONLY', thread['decision_reasons'])
                if case['source_id'] != 1199818:
                    self.assertTrue(any(a['action'] == 'remove_reply_boilerplate'
                                        for a in turn['normalization_actions']))

    def test_ui_only_with_or_without_audio_has_no_text_answer(self):
        for audio in (AUDIO, '<audio></audio>', ''):
            with self.subTest(audio=audio):
                page = parsed_page(small_page('指导意见：<br>医生询问：<br>' + ACCEPT + audio))
                thread = page['thread_decisions'][0]
                turn = thread['turns'][0]
                self.assertEqual(turn['text'], '')
                self.assertEqual(turn['answer_type'], 'audio' if audio else 'empty')
                self.assertEqual(thread['corpus_decision'], 'EXCLUDE')
                self.assertEqual(thread['decision_reasons'], ['AUDIO_ONLY' if audio else 'NO_TEXT_MAIN_ANSWER'])

    def test_removes_only_template_span_beside_real_content(self):
        for audio in (AUDIO, ''):
            for answer in (ACCEPT + '<br>' + GOOD, GOOD + '<br>' + ACCEPT, GREETING + GOOD):
                with self.subTest(audio=audio, answer=answer):
                    page = parsed_page(small_page(answer + audio))
                    thread = page['thread_decisions'][0]
                    turn = thread['turns'][0]
                    self.assertEqual(turn['text'], GOOD)
                    self.assertEqual(turn['answer_type'], 'mixed' if audio else 'text')
                    self.assertEqual(thread['corpus_decision'], 'INCLUDE')
                    self.assertIn(GOOD, turn['raw_text'])
        # Two additional real replay answers had an inline footer, including
        # ASCII sentence punctuation, rather than a separate DOM paragraph.
        for content in (GOOD, GOOD[:-1] + '.'):
            with self.subTest(inline_footer=content):
                turn = parsed_page(small_page(content + SPARE_TIME))['ask120_threads'][0]['turns'][0]
                self.assertEqual(turn['text'], content)
                self.assertEqual(turn['answer_type'], 'text')

    def test_short_text_after_greeting_is_review_not_discarded(self):
        page = parsed_page(small_page(GREETING + '伊可新钙尓奇d' + AUDIO))
        thread = page['thread_decisions'][0]
        self.assertEqual(thread['turns'][0]['text'], '伊可新钙尓奇d')
        self.assertEqual(thread['turns'][0]['answer_type'], 'mixed')
        self.assertEqual(thread['corpus_decision'], 'REVIEW')
        self.assertIn('SHORT_MAIN_ANSWER_REVIEW', thread['decision_reasons'])

    def test_removal_actions_preserve_auditable_text_spans(self):
        page = parsed_page(small_page(GOOD + '<br>' + ACCEPT))
        turn = page['ask120_threads'][0]['turns'][0]
        action = next(a for a in turn['normalization_actions'] if a['action'] == 'remove_reply_boilerplate')
        self.assertEqual(action['before_sha256'], ask120.sha(turn['raw_text']))
        self.assertEqual(action['after_sha256'], ask120.sha(GOOD))
        self.assertTrue(action['rule_id'])
        for span in action['removed_spans']:
            self.assertEqual(turn['raw_text'][span['char_start']:span['char_end']], span['text'])
        self.assertEqual(turn['clean_text_sha256'], ask120.sha(GOOD))

    def test_similar_words_and_quoted_templates_are_preserved(self):
        answers = [
            '这是关于 audio 检查的真实回答。BRCA1 < 2 且数值 > 1，建议结合病史进行复查。',
            '建议到医院咨询与医生面对面交流，以便结合病史进行检查，不应仅凭文字判断病情。',
            '如果有了满意的回答请及时记录症状变化，并在复诊时向医生说明具体的用药情况。',
            '页面提示“' + ACCEPT + '”，这属于网站操作提示，不是对患者的治疗建议。',
        ]
        for answer in answers:
            with self.subTest(answer=answer):
                turn = parsed_page(small_page(answer))['ask120_threads'][0]['turns'][0]
                self.assertEqual(turn['text'], answer)
                self.assertEqual(turn['answer_type'], 'text')

    def test_patient_followup_is_not_subject_to_responder_templates(self):
        body = small_page(GOOD).decode()
        followup = '<div class="b_ansaddli"><span class="b_ansaddti"></span><p>' + GREETING + '</p></div>'
        body = body.replace('</div></div></div></html>', '</div>' + followup + '</div></div></html>')
        turns = parsed_page(body.encode())['ask120_threads'][0]['turns']
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[1]['role'], 'patient_followup')
        self.assertEqual(turns[1]['text'], GREETING)

    def test_final_media_type_follows_text_after_title_tail_removal(self):
        tail = '以上是对“患者问题”这个问题的建议，希望对您有帮助！'
        page = parsed_page(small_page(tail + AUDIO))
        turn = page['ask120_threads'][0]['turns'][0]
        self.assertEqual(turn['text'], '')
        self.assertEqual(turn['answer_type'], 'audio')
        self.assertEqual(page['audio_main_answers'], 1)
        self.assertEqual(page['thread_decisions'][0]['corpus_decision'], 'EXCLUDE')

    def test_real_other_answer_content_survives_author_policy(self):
        manifest = json.loads((FIXTURES / 'manifest.json').read_text(encoding='utf-8'))
        for identifier in (1025409, 1029798, 1053679, 1087866):
            with self.subTest(source_id=identifier):
                case = next(c for c in manifest['cases'] if c['source_id'] == identifier)
                body = gzip.decompress((FIXTURES / case['raw_file']).read_bytes())
                page = parsed_page(body, dict(case, id=identifier))
                threads = page['thread_decisions']
                self.assertEqual(next(t for t in threads if t['thread_id'] == case['thread_id'])['corpus_decision'], 'EXCLUDE')
                self.assertTrue(any(t['turns'][0]['text'] for t in threads if t['thread_id'] != case['thread_id']))
                included = [t for t in threads if t['corpus_decision'] == 'INCLUDE']
                if included:
                    doc = gate.build_candidate_document(page, included)
                    self.assertNotIn(case['thread_id'], doc['included_thread_ids'])
                else:
                    self.assertEqual(gate.decide_page(threads, page)['corpus_decision'], 'REVIEW')


if __name__ == '__main__':
    unittest.main()
