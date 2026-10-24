"""Evidence and review packets for an independent 120ask run, without human labels."""
from collections import Counter
import json
from pathlib import Path
import random
import re


def audit_question_context(gate, page, tree):
    proof=page['question_context']
    expected=gate.PARSER.question_context(page['title'],page['ask120_question'],
        title_dom_locator=proof['title']['dom_locator'],body_dom_locator=proof['body']['dom_locator'])
    assert proof==expected, 'Question context metadata differs from source fields/rules'
    assert proof['status']==page['question_context_status'] and proof['source']==page['question_context_source']
    assert proof['body']['dom_locator']==page['question_provenance']['dom_locator']
    count=0
    for name in ('title','body'):
        field=proof[name]
        assert field['text']==(page['title'] if name=='title' else page['ask120_question'])
        assert field['text_sha256']==gate.sha(field['text'])
        if field['dom_locator']:
            nodes=tree.xpath(field['dom_locator'])
            assert len(nodes)==1
            if name=='title':assert gate.PARSER.normalize(nodes[0].text_content())==page['title']
        for item in field['generic_evidence']+field['residual_spans']:
            start,stop=item['char_start'],item['char_end']
            assert 0<=start<=stop<=len(field['text'])
            assert item['text']==field['text'][start:stop]
            count+=1
    return count


def audit_question(gate, page, tree):
    """Verify question DOM and replay every normalization span from its raw text."""
    proof=page['question_provenance']
    if not proof['dom_locator']:
        assert not page.get('question_valid'), 'Valid question has no source locator'
    else:
        nodes=tree.xpath(proof['dom_locator'])
        assert len(nodes)==1, 'Question DOM locator is not unique'
        html=gate.PARSER.html.tostring(nodes[0],encoding='unicode',with_tail=False)
        assert html==proof['source_html'] and gate.sha(html)==proof['source_html_sha256']
        assert gate.PARSER._paragraph_text(nodes[0])==proof['raw_text']
    current=proof['raw_text']
    assert gate.sha(current)==proof['raw_text_sha256']
    spans=0
    for action in proof['actions']:
        assert action['offset_basis']=='text_before_action'
        assert gate.sha(current)==action['before_sha256']
        end=0
        for span in action['spans']:
            start,stop=span['char_start'],span['char_end']
            assert end<=start<=stop<=len(current)
            assert span['text']==current[start:stop]
            end=stop
            spans+=1
        for span in reversed(action['spans']):
            current=current[:span['char_start']]+span['replacement']+current[span['char_end']:]
        assert gate.sha(current)==action['after_sha256']
        for key,value in action['evidence'].items():
            if key.endswith('dom_locator'): assert len(tree.xpath(value))==1
    assert current==page['ask120_question']
    assert gate.sha(current)==proof['clean_text_sha256']
    assert page['question_qc']==gate.PARSER.question_qc(current)
    context_spans=audit_question_context(gate,page,tree) if page.get('question_context') else 0
    return dict(actions=len(proof['actions']),spans=spans,context_spans=context_spans)


def audit(gate, out):
    out = Path(out)
    samples = gate.read_jsonl_bytes((out/'sample.jsonl').read_bytes())
    pages = gate.read_jsonl_bytes((out/'results_reparsed.jsonl').read_bytes())
    usable = [p for p in pages if not p.get('replay_error') and p.get('access_status')=='VAO_DUOC'
              and 200 <= (p.get('http_status') or 0) < 300]
    threads = [t for p in usable for t in p.get('thread_decisions', [])]
    errors = []
    checked_raw = checked_dom = checked_flags = checked_evidence = 0
    checked_questions = checked_question_actions = checked_question_spans = 0
    checked_contexts=checked_context_spans=0
    reader = gate.RunInput(out)
    for page in usable:
        try:
            body = gate.safe_raw(reader, page)
            tree, _, _ = gate.PARSER._tree(body, page.get('content_type', ''))
            checked_raw += 1
            if page.get('question_provenance'):
                checked_question=audit_question(gate,page,tree)
                checked_questions+=1
                checked_question_actions+=checked_question['actions']
                checked_question_spans+=checked_question['spans']
                if page.get('question_context'):
                    checked_contexts+=1
                    checked_context_spans+=checked_question['context_spans']
            for thread in page['thread_decisions']:
                included = thread['corpus_decision']=='INCLUDE'
                if included and gate.author_admission_reasons(thread, gate.POLICY):
                    errors.append(dict(source_id=page['id'], thread_id=thread['thread_id'], issue='F2_author_admission'))
                if included and thread.get('source_flags'):
                    errors.append(dict(source_id=page['id'], thread_id=thread['thread_id'], issue='F3_flagged_INCLUDE'))
                if included and gate.question_admission_reasons(page):
                    errors.append(dict(source_id=page['id'], thread_id=thread['thread_id'], issue='question_admission_INCLUDE'))
                for turn in thread['turns']:
                    assert len(tree.xpath(turn['dom_locator']))==1, 'DOM locator is not unique'
                    checked_dom += 1
                    if included and turn['turn_kind']=='answer' and turn['answer_type']=='audio':
                        errors.append(dict(source_id=page['id'], thread_id=thread['thread_id'], issue='F1_audio_only_INCLUDE'))
                for flag in thread.get('source_flags', []):
                    turn = next(t for t in thread['turns'] if t['turn_index']==flag['turn_index'])
                    assert turn['speaker_role']=='responder', 'Source flag attributed to a patient'
                    assert flag['text_sha256']==gate.sha(turn['text'])
                    assert flag['raw_sha256']==page['raw_sha256']
                    assert flag['dom_locator']==turn['dom_locator'] and flag['reply_id']==turn['reply_id']
                    assert flag['excerpt']==turn['text'][flag['excerpt_start']:flag['excerpt_end']]
                    for span in flag['evidence']:
                        assert span['text']==turn['text'][span['char_start']:span['char_end']]
                        checked_evidence += 1
                    checked_flags += 1
        except (AssertionError, ValueError, OSError, KeyError) as exc:
            errors.append(dict(source_id=page['id'], issue='provenance_audit', detail=str(exc)))
    reader.close()
    broad = re.compile(r'我院|本院|我们医院|独家|祖传|秘方|特效|根治|治愈|复发|副作用|保证|百分之百|100%|免费|'
                       r'联系|微信|QQ|电话|点击|头像|名片|采纳|满意|在线咨询', re.I)
    included = [t for t in threads if t['corpus_decision']=='INCLUDE']
    random.Random(2026102003).shuffle(included)
    random_keys = {(t['source_id'],t['thread_id']) for t in included[:50]}
    packet = []
    context_by_id={p['id']:p.get('question_context',{}) for p in usable}
    for thread in threads:
        reasons = []
        if (thread['source_id'],thread['thread_id']) in random_keys: reasons.append('random_INCLUDE_sample')
        if thread.get('source_flags'): reasons.append('F3_all_flagged')
        if context_by_id[thread['source_id']].get('review_reasons'):reasons.append('F4_question_context_review')
        responder = [t for t in thread['turns'] if t.get('speaker_role')=='responder']
        if any(t.get('answer_type') in ('mixed','audio') or any(a.get('action')=='remove_reply_boilerplate'
               for a in t.get('normalization_actions', [])) for t in responder): reasons.append('F1_media_or_boilerplate')
        if any(broad.search(t['text']) for t in responder): reasons.append('broad_context_search_not_a_verdict')
        if any(gate.PARSER.author_review_reasons(t) for t in responder): reasons.append('F2_author_evidence_review')
        if reasons:
            packet.append(dict(review_reasons=reasons,question_context=context_by_id[thread['source_id']], **thread))
    gate.jsonl(out/'holdout_review_packet.jsonl', packet)
    complete = len(usable)==len(samples)
    result = dict(verdict='NOT_ASSESSED_ACCESS_BLOCKED' if not usable else
                  'AUTOMATED_AUDIT_FAILED' if errors else
                  'AUTOMATED_CHECKS_PASS_SEMANTIC_REVIEW_PENDING' if complete else 'PARTIAL_ACCESS_SEMANTIC_REVIEW_PENDING',
        selected=len(samples), attempted_urls=len(pages), usable_html=len(usable),
        pending_urls=len(samples)-len(pages),
        http_status=dict(Counter(str(p.get('http_status')) for p in pages)),
        F1='NOT_ASSESSED' if not threads else 'STRUCTURAL_CHECK_ONLY_SEMANTIC_REVIEW_PENDING',
        F2='NOT_ASSESSED' if not threads else 'SOURCE_EVIDENCE_CHECK_ONLY_SEMANTIC_REVIEW_PENDING',
        F3='NOT_ASSESSED' if not threads else 'FLAG_EVIDENCE_CHECK_ONLY_FALSE_NEGATIVE_REVIEW_PENDING',
        F5='NOT_ASSESSED' if not checked_questions else 'QUESTION_TRACE_CHECKED_SEMANTIC_REVIEW_PENDING',
        F4='NOT_ASSESSED' if not checked_contexts else 'CONTEXT_RULE_EVIDENCE_CHECKED_SEMANTIC_REVIEW_PENDING',
        question_context_checked=checked_contexts,question_context_spans_checked=checked_context_spans,
        question_provenance_checked=checked_questions,question_actions_checked=checked_question_actions,
        question_spans_checked=checked_question_spans,
        raw_hashes_checked=checked_raw, dom_locators_checked=checked_dom,
        flags_checked=checked_flags, evidence_spans_checked=checked_evidence,
        threads=len(threads), included_threads=len(included), review_packet_threads=len(packet), errors=errors,
        medical_accuracy_reviewed=False, human_labels_added=0)
    gate.write_json(out/'holdout_quality_audit.json', result)
    return result
