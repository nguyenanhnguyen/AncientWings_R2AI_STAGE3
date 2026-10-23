"""Offline DOM checks against saved ask.39.net HTML; no network or corpus admission."""
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from lxml import html

VERSION = 'ask39-independent-audit-v3-render-roles'

def normalized(text):
    return re.sub(r'\s+', '', text or '')


def audit_record(record, body):
    raw_digest = hashlib.sha256(body).hexdigest() if isinstance(body,bytes) else hashlib.sha256(body.encode('utf-8')).hexdigest()
    if isinstance(body, bytes):
        declared = re.search(r'charset\s*=\s*["\']?([\w-]+)', record.get('content_type') or '', re.I)
        meta = re.search(rb'charset\s*=\s*["\']?([\w-]+)', body[:16384], re.I)
        encoding = declared.group(1) if declared else meta.group(1).decode('ascii') if meta else 'utf-8'
        if encoding.lower() in ('gb2312', 'gbk', 'x-gbk'): encoding = 'gb18030'
        body = body.decode(encoding, 'strict')
    root = html.fromstring(body)
    # Audit owns its boundary rules; it does not call the candidate parser.
    excluded = {'jbk_txt', 'jbbk_top', 'jbk_xxin', 'ask_doc_box', 'drug-box',
                'relevant_ask', 'relev_all', 'cont_right', 'header_bg', 'footer',
                'link_fot', 'fship_link', 'txt_answer', 'txt_answer1', 'askdoc_bot',
                'ask_doc', 'txt_complaint', 'hfu_box', 'txt_yuedu', 'txt_dayad',
                'askCenterAd', 'banner_g', 'w_left_ads', 'w_right_ads',
                'cpu-feeds-block', 'txt_label', 'txt_nametime'}
    fields = {'sele_txt', 'txt_ms', 'txt_bc', 'doc_zw', 'ask_tit'}
    def source_answer_identity(owner):
        if owner is None: return None, None, []
        pairs, links = set(), []
        qid = urlsplit(record.get('final_url') or record['url']).path.rsplit('/',1)[-1][:-5]
        for anchor in owner.xpath('.//a[@id="reportBtn"]'):
            parents = anchor.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," sele_all ")][1]')
            if len(parents)!=1 or parents[0] is not owner or anchor.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," doc_zw ")]'):
                continue
            if any(set((p.get('class') or '').split()).intersection(excluded-{'txt_complaint'}) for p in anchor.iterancestors()): continue
            # Independent raw check of the report-link's question and answer arguments.
            matched = re.match(r'''^(?:javascript:\s*)?showReportModal\(\s*(['"])https://askapi\.39\.net/produce/topic/pub/asksys/feedback\1\s*,\s*(['"])([A-Za-z0-9_-]+)\2\s*,\s*([1-9][0-9]*)\s*,''', (anchor.get('href') or '').strip())
            if not matched: return None,None,[]
            pair=(matched.group(3),matched.group(4));pairs.add(pair)
            links.append(dict(question_id=pair[0],source_answer_id=pair[1],locator=root.getroottree().getpath(anchor)))
        if len(pairs)!=1 or next(iter(pairs))[0]!=qid: return None,None,links
        source_id=next(iter(pairs))[1]
        return f'ask39:{qid}:answer:{source_id}',source_id,links
    def outside(n):
        return any(set((p.get('class') or '').split()).intersection(excluded)
                   or p.tag in {'script','style','iframe','form','button','input','textarea','nav','footer','select','noscript'}
                   for p in [n, *n.iterancestors()])
    def nodes(cls):
        found = root.xpath('//*[contains(concat(" ", normalize-space(@class), " "), $token)]', token=' '+cls+' ')
        return [n for n in found if not outside(n)] if cls in fields else found
    extracted = normalized(record.get('text', ''))
    def text(node, answer_content=False):
        # Form controls belong to the page UI, not a follow-up message.
        node = deepcopy(node)
        for child in list(node.iterdescendants()):
            reply_control = (child.tag == 'i' and 'hfu' in (child.get('class') or '').split()
                             and any('zw2' in (p.get('class') or '').split() for p in child.iterancestors()))
            rating = answer_content and child.tag == 'span' and 'pingjia' in (child.get('class') or '').split()
            if child.getparent() is not None and (child.tag in {'script','style','iframe','form','textarea','input','button','select','noscript','nav','footer'}
                    or reply_control or rating
                    or set((child.get('class') or '').split()).intersection(excluded | {'doctor_all','doc_xinx','doc_time','doc_sc','zw1'})):
                child.drop_tree()
        return normalized(node.text_content())
    answers = []
    def empty_answer_parts(node):
        # Independent audit of repaired paragraph ownership, without parser calls.
        parent = node.getparent()
        following = node.getnext()
        if (parent is not None and 'sele_all' in (parent.get('class') or '').split()
                and following is not None and following.tag == 'p'
                and not following.get('class') and not outside(following)
                and re.fullmatch(r'content[1-9][0-9]*', following.get('id') or '')):
            return [text(following, answer_content=True)]
        parts = []
        for sibling in node.itersiblings():
            if sibling.tag != 'p' or sibling.get('class') or sibling.get('id'): break
            if text(sibling, answer_content=True): parts.append(text(sibling, answer_content=True))
        return parts

    repaired_answers = 0
    for n in nodes('sele_txt'):
        content = text(n, answer_content=True)
        if not content:
            # Invalid <p class=sele_txt><p>...</p></p> becomes sibling paragraphs in lxml.
            parts = empty_answer_parts(n)
            if parts:
                content = ''.join(parts)
                repaired_answers += 1
        if content: answers.append(content)
    # A duplicate description can be rendered once without the UI field label.
    # Keep supplemental content exact; only the observed field prefix is optional.
    questions = [re.sub(r'^补充说明[：:]', '', text(n))
                 for cls in ('txt_ms', 'txt_bc') for n in nodes(cls) if text(n)]
    followups = []
    for n in nodes('doc_zw'):
        # zw2 contains the message; adjacent hfu_box contains reply controls.
        parts = [part for part in n.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," zw2 ")]') if not outside(part)]
        if parts:
            followups.extend(text(part) for part in parts if text(part))
        else:
            followups.append(text(n))
    encyclopedia = [text(n) for n in nodes('jbk_txt') if len(text(n)) >= 30]
    missing_answers = [a for a in answers if a not in extracted]
    missing_questions = [q for q in questions if q not in extracted]
    missing_followups = [f for f in followups if f and f not in extracted]
    source_content = ''.join(answers + questions + followups)
    contamination = [s for s in encyclopedia if s in extracted and s not in source_content]
    # A literal mention in a real message is not evidence of copied UI.
    ui = [s for s in ('我要咨询', '举报', '向医生提问', '取消 提交', '回复追问：')
          if normalized(s) in extracted and normalized(s) not in source_content]
    ancillary = []
    for cls in ('relevant_ask', 'drug-box', 'txt_yuedu', 'cont_right', 'txt_label'):
        for node in nodes(cls):
            value = text(node)
            if len(value) >= 8 and value in extracted and value not in source_content:
                ancillary.append(dict(locator=root.getroottree().getpath(node), class_name=cls, text_preview=value[:160]))
    flags = []
    if not answers: flags.append('source_answers_not_identified')
    if missing_answers: flags.append('main_answer_text_missing')
    if missing_questions: flags.append('question_text_missing')
    if missing_followups: flags.append('followup_text_missing')
    if contamination: flags.append('encyclopedia_contamination')
    if ui: flags.append('ui_boilerplate')
    if ancillary: flags.append('ancillary_dom_contamination')
    if 'question' in record:
        titles = nodes('ask_tit')
        if len(titles) != 1 or normalized(record.get('title')) != text(titles[0]) or normalized(record.get('question',{}).get('title')) != text(titles[0]):
            flags.append('question_title_mismatch')
        expected_question = []
        source_nodes = root.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," txt_ms ") or contains(concat(" ",normalize-space(@class)," ")," txt_bc ")]')
        for node in source_nodes:
            if outside(node): continue
            value = re.sub(r'^补充说明[：:]', '', text(node))
            if value and value not in expected_question: expected_question.append(value)
        actual_question = [normalized(b.get('text')) for b in record.get('question',{}).get('blocks',[])]
        if actual_question != expected_question: flags.append('question_blocks_mismatch')
    if 'answers' in record:
        source_answers = nodes('sele_txt')
        actual_answers = record['answers']
        expected_paths = [root.getroottree().getpath(n) for n in source_answers]
        actual_paths = [a.get('body_locators', [None])[0] if a.get('body_locators') else None for a in actual_answers]
        if actual_paths != expected_paths: flags.append('answer_order_or_coverage_mismatch')
        for n in source_answers:
            path = root.getroottree().getpath(n)
            matches = [a for a in actual_answers if a.get('body_locators') and a['body_locators'][0] == path]
            if len(matches) != 1:
                flags.append('answer_mapping_mismatch')
                continue
            a = matches[0]
            if a.get('speaker_role') != 'responder': flags.append('answer_speaker_role_mismatch')
            parents = n.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," sele_all ")][1]')
            owner = parents[0] if len(parents) == 1 else None
            ids = owner.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," doctor_all ")]/@id') if owner is not None else []
            if record.get('extractor') == 'ask39_qa_dom_v2':
                expected_key,expected_source,links=source_answer_identity(owner)
                if expected_key is None or a.get('answer_id')!=expected_key or a.get('source_answer_id')!=expected_source:
                    flags.append('answer_source_identity_mismatch')
                evidence=a.get('identity_evidence',{})
                if a.get('identity_status')!='verified' or evidence.get('links')!=links or evidence.get('raw_sha256')!=raw_digest or evidence.get('answer_locator')!=root.getroottree().getpath(owner):
                    flags.append('answer_identity_evidence_mismatch')
                if len(ids)!=1 or a.get('reply_dom_id')!=ids[0]: flags.append('answer_header_identity_mismatch')
            elif len(ids) != 1 or a.get('answer_id') != ids[0]: flags.append('answer_owner_mismatch')
            if owner is not None:
                names = owner.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," doc_name ")]')
                qualifications = owner.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," doc_yshi ")]')
                expected_name = text(names[0]) if len(names) == 1 else ''
                if normalized(a.get('author_name')) != expected_name or [normalized(v) for v in a.get('qualification_raw', [])] != [text(n) for n in qualifications]:
                    flags.append('answer_author_metadata_mismatch')
            content = text(n, answer_content=True)
            if not content:
                content = ''.join(empty_answer_parts(n))
            if normalized(a.get('text')) != content: flags.append('answer_message_text_mismatch')
            # Derive rating fields from raw siblings, not record-provided locators.
            rating_fields = [n]
            for sibling in n.itersiblings():
                if (len(rating_fields)==1 and not text(n, answer_content=True)
                        and n.getparent() is owner and sibling.tag=='p' and not sibling.get('class')
                        and re.fullmatch(r'content[1-9][0-9]*',sibling.get('id') or '')):
                    rating_fields.append(sibling);break
                if sibling.tag!='p' or sibling.get('class') or sibling.get('id'): break
                rating_fields.append(sibling)
            rating_nodes = []
            for field in rating_fields:
                for rating in field.xpath('.//span[contains(concat(" ",normalize-space(@class)," ")," pingjia ")]'):
                    if outside(rating): continue
                    if rating.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," doc_zw ")]'): continue
                    if any(p.tag=='span' and 'pingjia' in (p.get('class') or '').split() for p in rating.iterancestors()): continue
                    rating_nodes.append((rating,field))
            actual_ratings=a.get('patient_evaluations',[])
            if len(actual_ratings)!=len(rating_nodes): flags.append('patient_evaluation_metadata_mismatch')
            for order,((rating,field),metadata) in enumerate(zip(rating_nodes,actual_ratings),1):
                provenance=metadata.get('provenance',{})
                value=metadata.get('text','')
                if (metadata.get('evaluation_id')!=a.get('answer_id')+f':patient-evaluation:{order}'
                        or metadata.get('parent_answer_id')!=a.get('answer_id') or metadata.get('order')!=order
                        or metadata.get('speaker_role')!='patient' or normalized(value)!=text(rating)
                        or metadata.get('source_text')!=value
                        or metadata.get('text_sha256')!=hashlib.sha256(value.encode()).hexdigest()
                        or metadata.get('locator')!=root.getroottree().getpath(rating)
                        or provenance!=dict(rule='patient_evaluation_dom',raw_sha256=raw_digest,
                            answer_locator=root.getroottree().getpath(owner),body_locator=root.getroottree().getpath(field),
                            source_html_sha256=hashlib.sha256(html.tostring(rating,encoding='utf-8',with_tail=False)).hexdigest())):
                    flags.append('patient_evaluation_metadata_mismatch')
    structure_issues = []
    if 'followups' in record:
        source_nodes = nodes('doc_zw')
        actual = record['followups']
        expected_locators = [root.getroottree().getpath(n) for n in source_nodes]
        if [m.get('locator') for m in actual] != expected_locators:
            flags.append('followup_order_or_coverage_mismatch')
        for node in source_nodes:
            locator = root.getroottree().getpath(node)
            matches = [m for m in actual if m.get('locator') == locator]
            if len(matches) != 1:
                structure_issues.append(dict(locator=locator, issue='message_mapping'))
                continue
            message = matches[0]
            parents = node.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," sele_all ")][1]')
            parent = parents[0] if len(parents) == 1 else None
            header_ids = parent.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," doctor_all ")]/@id') if parent is not None else []
            expected_owner = (source_answer_identity(parent)[0] if record.get('extractor')=='ask39_qa_dom_v2'
                              else header_ids[0] if len(header_ids)==1 else None)
            labels = node.xpath('./*[contains(concat(" ",normalize-space(@class)," ")," zw1 ")]')
            label = text(labels[0]).rstrip('：:') if len(labels) == 1 else ''
            role = {'追问': 'patient', '回复': 'responder'}.get(label, 'unknown')
            if message.get('parent_answer_id') != expected_owner:
                flags.append('followup_owner_mismatch')
                structure_issues.append(dict(locator=locator, issue='owner', expected=expected_owner))
            if message.get('speaker_role') != role:
                flags.append('followup_role_mismatch')
                structure_issues.append(dict(locator=locator, issue='role', expected=role))
            bodies = node.xpath('./*[contains(concat(" ",normalize-space(@class)," ")," zw2 ")]')
            if len(bodies) != 1 or normalized(message.get('text')) != text(bodies[0]):
                flags.append('followup_message_text_mismatch')
                structure_issues.append(dict(locator=locator, issue='message_text'))
        for answer in record.get('answers', []):
            expected_messages = [m for m in actual if m.get('parent_answer_id') == answer['answer_id']]
            expected = [m.get('locator') for m in expected_messages]
            if [m.get('locator') for m in answer.get('followups', [])] != expected:
                flags.append('followup_thread_mismatch')
                structure_issues.append(dict(answer_id=answer['answer_id'], issue='nested_thread'))
            if answer.get('followups', []) != expected_messages:
                flags.append('followup_nested_message_mismatch')
                structure_issues.append(dict(answer_id=answer['answer_id'],issue='nested_message_content_or_role'))
        flags = sorted(set(flags))
    # Reconstruct the clinical rendering directly from raw nodes. Comparing only
    # message fields would miss UI or a fabricated speaker label in record.text.
    if 'answers' in record and 'question' in record and len(nodes('ask_tit'))==1:
        title=text(nodes('ask_tit')[0]);rendered=['问题：'+title]
        rendered.extend(q for q in expected_question if q!=title)
        for field in nodes('sele_txt'):
            owners=field.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," sele_all ")][1]')
            owner=owners[0] if len(owners)==1 else None
            names=owner.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," doc_name ")]') if owner is not None else []
            name=text(names[0]) if len(names)==1 else '未注明'
            content=text(field,answer_content=True) or ''.join(empty_answer_parts(field))
            rendered.extend(['回答者：'+name,content])
            for message in nodes('doc_zw'):
                parents=message.xpath('ancestor::*[contains(concat(" ",normalize-space(@class)," ")," sele_all ")][1]')
                if len(parents)!=1 or parents[0] is not owner: continue
                labels=message.xpath('./*[contains(concat(" ",normalize-space(@class)," ")," zw1 ")]')
                label=text(labels[0]).rstrip('：:') if len(labels)==1 else ''
                bodies=message.xpath('./*[contains(concat(" ",normalize-space(@class)," ")," zw2 ")]')
                content=text(bodies[0]) if len(bodies)==1 else ''
                role_label={'追问':'患者追问','回复':'回答者补充回答'}.get(label,'后续交流（身份未明）')
                rendered.append(role_label+'：'+content)
        if normalized(''.join(rendered))!=extracted: flags.append('raw_rendered_text_mismatch')
    flags=sorted(set(flags))
    return dict(id=record['id'], url=record['url'], audit_version=VERSION, baseline_qc=record.get('quality_status'),
        source_answers=len(answers), missing_answers=len(missing_answers),
        repaired_nested_p_answers=repaired_answers,
        source_question_blocks=len(questions), missing_question_blocks=len(missing_questions),
        source_followup_blocks=len(followups), missing_followup_blocks=len(missing_followups),
        encyclopedia_blocks_in_text=len(contamination), ui_markers=ui, flags=flags,
        ancillary_contamination=ancillary,
        missing_answer_snippets=[s[:160] for s in missing_answers],
        missing_followup_snippets=[s[:160] for s in missing_followups],
        followup_structure_issues=structure_issues,
        review_decision='REVIEW' if flags else 'NO_ISSUE_DETECTED')


def run(directory):
    directory = Path(directory)
    records_path = directory/'results.jsonl'
    audits = []
    for line in records_path.read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        item = dict(id=record['id'], url=record['url'])
        try:
            if record.get('access') != 'VAO_DUOC':
                raise ValueError('Page not accessible')
            path = (directory/record['raw_path']).resolve()
            if not path.is_relative_to(directory.resolve()):
                raise ValueError('Raw path outside run directory')
            body = gzip.decompress(path.read_bytes())
            if hashlib.sha256(body).hexdigest() != record['raw_sha256']:
                raise ValueError('Raw hash mismatch')
            item = audit_record(record, body)
        except Exception as exc:
            item.update(flags=['not_auditable'], error=f'{type(exc).__name__}: {exc}', review_decision='REVIEW')
        audits.append(item)
    summary = dict(pages=len(audits), audited_pages=sum('baseline_qc' in r for r in audits),
        review_pages=sum(r['review_decision'] == 'REVIEW' for r in audits),
        flags=dict(Counter(f for r in audits for f in r['flags'])),
        source_answers=sum(r.get('source_answers', 0) for r in audits),
        missing_answers=sum(r.get('missing_answers', 0) for r in audits),
        repaired_nested_p_answers=sum(r.get('repaired_nested_p_answers', 0) for r in audits),
        source_followup_blocks=sum(r.get('source_followup_blocks', 0) for r in audits),
        missing_followup_blocks=sum(r.get('missing_followup_blocks', 0) for r in audits),
        method='Whitespace-normalized exact DOM text comparison on sele_txt, txt_ms/txt_bc, doc_zw and jbk_txt; heuristic, not human labels or medical validation.')
    (directory/'dom_audit.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in audits), encoding='utf-8')
    (directory/'dom_audit_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    print(json.dumps(run(parser.parse_args().directory), ensure_ascii=False, indent=2))
