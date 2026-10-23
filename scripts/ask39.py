"""Candidate ask.39.net DOM parser: questions, answers and owned follow-ups.

This candidate never grants corpus admission; production notebooks are not
patched by this module. Unknown message roles/owners remain explicit for review.
"""
from copy import deepcopy
import hashlib
import re
from urllib.parse import urljoin, urlsplit

from lxml import html

VERSION = 'ask39-parser-v2-patient-evaluations'
EXTRACTOR = 'ask39_qa_dom_v2'

# Observed ancillary containers, matched as class tokens, never as text keywords.
EXCLUDED_CLASSES = {
    'jbk_txt', 'jbbk_top', 'jbk_xxin', 'ask_doc_box', 'drug-box', 'relevant_ask',
    'relev_all', 'cont_right', 'header_bg', 'footer', 'link_fot', 'fship_link',
    'txt_answer', 'txt_answer1', 'askdoc_bot', 'ask_doc', 'txt_complaint',
    'hfu_box', 'txt_yuedu', 'txt_dayad', 'askCenterAd', 'banner_g',
    'w_left_ads', 'w_right_ads', 'cpu-feeds-block', 'txt_label', 'txt_nametime',
}
EXCLUDED_TAGS = {'script', 'style', 'iframe', 'form', 'button', 'input', 'textarea',
                 'select', 'noscript', 'nav', 'footer'}
CONTENT_METADATA_CLASSES = {'doctor_all', 'doc_xinx', 'doc_time', 'doc_sc', 'zw1'}


def _exclusion(node, content=False):
    # The site's reply control can be nested inside the actual message field.
    # Match its DOM signature, never the word "回复" in a patient's message.
    if (node.tag == 'i' and 'hfu' in (node.get('class') or '').split()
            and any('zw2' in (p.get('class') or '').split() for p in node.iterancestors())):
        return 'followup_reply_control'
    if node.tag in EXCLUDED_TAGS: return 'tag:' + node.tag
    classes = set((node.get('class') or '').split())
    matches = classes.intersection(EXCLUDED_CLASSES | (CONTENT_METADATA_CLASSES if content else set()))
    return 'class:' + sorted(matches)[0] if matches else None


def _outside_content(node):
    return any(_exclusion(p) for p in [node, *node.iterancestors()])


def _content_text(node, answer=False):
    clean = deepcopy(node)
    # Remove only the outermost excluded subtree; drop_tree preserves its tail.
    for child in list(clean.iterdescendants()):
        rating = answer and child.tag == 'span' and 'pingjia' in (child.get('class') or '').split()
        if child.getparent() is not None and (rating or _exclusion(child, content=True)):
            child.drop_tree()
    return _text(clean)


def _exclusion_evidence(root, tree, answer_fields=()):
    result = []
    def reason_for(node):
        if (node.tag == 'span' and 'pingjia' in (node.get('class') or '').split()
                and any(p in answer_fields for p in node.iterancestors())):
            return 'patient_evaluation_metadata'
        in_field = any(set((p.get('class') or '').split()).intersection({'ask_tit','txt_ms','txt_bc','sele_txt','zw2'})
                       for p in node.iterancestors())
        return _exclusion(node, content=in_field)
    for node in root.iterdescendants():
        reason = reason_for(node)
        if not reason or any(reason_for(p) for p in node.iterancestors()): continue
        raw = html.tostring(node, encoding='utf-8', with_tail=False)
        source_text = _text(node)
        result.append(dict(rule='exclude_dom_subtree', reason=reason, locator=tree.getpath(node),
                           source_text_preview=source_text[:240],
                           source_text_sha256=hashlib.sha256(source_text.encode()).hexdigest(),
                           source_html_sha256=hashlib.sha256(raw).hexdigest()))
    return result


def _patient_evaluations(parts, container, identity, tree, raw_hash):
    evaluations = []
    for part in parts:
        for node in part.xpath('.//span[contains(concat(" ",normalize-space(@class)," ")," pingjia ")]'):
            if (_outside_content(node) or _nearest(node, 'sele_all') is not container
                    or _nearest(node, 'doc_zw') is not None
                    or any(p.tag == 'span' and 'pingjia' in (p.get('class') or '').split()
                           for p in node.iterancestors() if p is not part)):
                continue
            value = _text(node)
            order = len(evaluations) + 1
            evaluations.append(dict(evaluation_id=identity['answer_id'] + f':patient-evaluation:{order}',
                parent_answer_id=identity['answer_id'], order=order, speaker_role='patient',
                text=value, source_text=value, text_sha256=hashlib.sha256(value.encode()).hexdigest(),
                locator=tree.getpath(node), provenance=dict(rule='patient_evaluation_dom',
                    raw_sha256=raw_hash, answer_locator=tree.getpath(container), body_locator=tree.getpath(part),
                    source_html_sha256=hashlib.sha256(html.tostring(node,encoding='utf-8',with_tail=False)).hexdigest())))
    return evaluations


def supported_url(url):
    parsed = urlsplit(str(url))
    return (parsed.scheme in ('http', 'https') and parsed.hostname == 'ask.39.net'
            and re.fullmatch(r'/question/[A-Za-z0-9_-]+\.html', parsed.path) is not None)


def compact(value):
    return re.sub(r'\s+', '', value or '')


def _nodes(node, cls):
    return [n for n in node.xpath('.//*[contains(concat(" ",normalize-space(@class)," "),$token)]', token=' '+cls+' ')
            if not _outside_content(n)]


def _nearest(node, cls):
    return next((p for p in node.iterancestors() if cls in (p.get('class') or '').split()), None)


def _answer_identity(container, question_id, tree, raw_hash, flags):
    """Read static report-link IDs in this answer, never an author/header ID."""
    found, invalid = [], []
    pattern = re.compile(r'''^(?:javascript:\s*)?showReportModal\(\s*(['"])https://askapi\.39\.net/produce/topic/pub/asksys/feedback\1\s*,\s*(['"])([A-Za-z0-9_-]+)\2\s*,\s*([1-9][0-9]*)\s*,''')
    for link in container.xpath('.//a[@id="reportBtn"]'):
        if _nearest(link, 'sele_all') is not container or _nearest(link, 'doc_zw') is not None:
            continue
        if any(set((p.get('class') or '').split()).intersection(EXCLUDED_CLASSES - {'txt_complaint'})
               for p in link.iterancestors() if p is not container):
            continue
        match = pattern.match((link.get('href') or '').strip())
        if match:
            found.append(dict(question_id=match.group(3),source_answer_id=match.group(4),locator=tree.getpath(link)))
        else:
            invalid.append(tree.getpath(link))
    pairs = {(x['question_id'],x['source_answer_id']) for x in found}
    verified = len(pairs)==1 and next(iter(pairs))[0]==question_id and not invalid
    if invalid: flags.append('unrecognized_answer_identity_evidence')
    if not pairs: flags.append('missing_answer_source_id')
    if len(pairs)>1: flags.append('answer_identity_conflict')
    if any(q != question_id for q,_ in pairs): flags.append('answer_question_id_mismatch')
    source_id = next(iter(pairs))[1] if verified else None
    locator = tree.getpath(container)
    key = (f'ask39:{question_id}:answer:{source_id}' if verified else
           f'ask39:{question_id}:provisional:{raw_hash[:16]}:{hashlib.sha256(locator.encode()).hexdigest()[:16]}')
    return dict(answer_id=key,source_answer_id=source_id,source_question_id=question_id,
                identity_status='verified' if verified else 'provisional',
                identity_evidence=dict(rule='scoped_report_link' if verified else 'unresolved',
                                       answer_locator=locator,links=found,invalid_links=invalid,
                                       raw_sha256=raw_hash))


def _followups(root, owners, tree, flags):
    messages, source_ids = [], set()
    blocks = _nodes(root, 'doc_zw')
    for index, node in enumerate(blocks, 1):
        owner = owners.get(_nearest(node, 'sele_all'))
        # Nested message containers are ambiguous, not another user's body text.
        labels = [p for p in _nodes(node, 'zw1') if _nearest(p, 'doc_zw') is node]
        bodies = [p for p in _nodes(node, 'zw2') if _nearest(p, 'doc_zw') is node]
        label = _text(labels[0]) if len(labels) == 1 else ''
        key = compact(label).rstrip('：:')
        role = {'追问': 'patient', '回复': 'responder'}.get(key, 'unknown')
        if role == 'unknown': flags.append('unknown_followup_role')
        if owner is None: flags.append('orphan_followup')
        if _nearest(node, 'doc_zw') is not None or _nodes(node, 'doc_zw'):
            flags.append('nested_followup_container')
        content = _content_text(bodies[0]) if len(bodies) == 1 else ''
        if len(bodies) != 1: flags.append('followup_body_unrecognized')
        if not content: flags.append('empty_followup')
        # Read static identifiers only; never execute a page's event handler.
        identifiers = set()
        for handler in node.xpath('.//*[@onclick]/@onclick'):
            match = re.search(r'''editInquire\(\s*this\s*,\s*['"][^'"]+['"]\s*,\s*['"]\s*([0-9]+)\s*['"]''', handler)
            if match: identifiers.add(match.group(1))
        source_id = next(iter(identifiers)) if len(identifiers) == 1 else None
        if len(identifiers) > 1: flags.append('ambiguous_followup_id')
        if source_id and source_id in source_ids: flags.append('duplicate_followup_id')
        if source_id: source_ids.add(source_id)
        locator = tree.getpath(node)
        message = dict(message_id='followup-' + (source_id or hashlib.sha256(locator.encode()).hexdigest()[:16]),
            source_message_id=source_id, order=index,
            thread_order=len(owner['followups']) + 1 if owner is not None else None,
            parent_answer_id=owner['answer_id'] if owner is not None else None,
            speaker_role=role, source_label=label, author_name=None, published_at=None,
            text=content, source_text=_text(bodies[0]) if len(bodies) == 1 else '', text_sha256=hashlib.sha256(content.encode()).hexdigest(),
            locator=locator, body_locator=tree.getpath(bodies[0]) if len(bodies) == 1 else None,
            role_evidence=dict(label_locator=tree.getpath(labels[0]) if len(labels) == 1 else None,
                               label=label, rule='source_label' if role != 'unknown' else 'unknown'),
            ownership_evidence=dict(answer_locator=owner['locator'] if owner is not None else None,
                                    rule='nearest_answer_container' if owner is not None else 'unresolved'))
        messages.append(message)
        if owner is not None: owner['followups'].append(message)
    return messages


def _text(node):
    node = deepcopy(node)
    for child in node.xpath('.//script|.//style|.//iframe|.//form|.//button|.//input|.//textarea'):
        child.drop_tree()
    # Keep paragraph and line boundaries; do not invent spaces around inline tags.
    for child in node.iterdescendants():
        if child.tag == 'br':
            child.tail = '\n' + (child.tail or '')
        elif child.tag in ('p', 'div', 'li'):
            child.text = '\n' + (child.text or '')
            child.tail = '\n' + (child.tail or '')
    return '\n'.join(re.sub(r'[^\S\n]+', ' ', line).strip()
                     for line in node.text_content().splitlines() if line.strip())


def _decode(body, content_type):
    if isinstance(body, str):
        return body, None, False
    declared = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type or '', re.I)
    meta = re.search(rb'charset\s*=\s*["\']?([\w-]+)', body[:16384], re.I)
    encoding = declared.group(1) if declared else meta.group(1).decode('ascii') if meta else 'utf-8'
    if encoding.lower() in ('gb2312', 'gbk', 'x-gbk'): encoding = 'gb18030'
    try:
        return body.decode(encoding, 'strict'), encoding, False
    except (UnicodeDecodeError, LookupError):
        return body.decode('utf-8', 'replace'), encoding, True


def extract(body, url, content_type='text/html'):
    if not supported_url(url):
        raise ValueError('Unsupported ask.39.net question URL')
    decoded, encoding, warning = _decode(body, content_type)
    root = html.fromstring(decoded)
    tree = root.getroottree()
    raw_hash = hashlib.sha256(body.encode('utf-8') if isinstance(body,str) else body).hexdigest()
    question_id = urlsplit(url).path.rsplit('/',1)[-1][:-5]
    flags = []
    regions = _nodes(root, 'ask_cont')
    if len(regions) != 1:
        flags.append('question_container_unrecognized')
    region = regions[0] if len(regions) == 1 else None
    titles = _nodes(region, 'ask_tit') if region is not None else []
    title = _content_text(titles[0]) if len(titles) == 1 else ''
    if not title: flags.append('missing_question_title')
    questions, actions, seen = [], [], set()
    if region is not None:
        # Document order preserves supplemental questions after their original question.
        for node in region.iterdescendants():
            classes = set((node.get('class') or '').split())
            if not classes.intersection({'txt_ms', 'txt_bc'}): continue
            if _outside_content(node): continue
            raw_text = _text(node)
            cleaned = re.sub(r'^补充说明\s*[：:]\s*', '', _content_text(node))
            value = compact(cleaned)
            if value in seen:
                actions.append(dict(rule='duplicate_question', locator=tree.getpath(node), source_text=raw_text))
                continue
            if not value: continue
            seen.add(value)
            questions.append(dict(kind='description' if 'txt_ms' in classes else 'supplement',
                                  text=cleaned, source_text=raw_text, locator=tree.getpath(node)))
    if not questions: flags.append('missing_question_body')
    answers, owners, answer_fields = [], {}, []
    selected = _nodes(root, 'selected')
    containers = [n for section in selected for n in _nodes(section, 'sele_all')]
    # A nested container is ambiguous; never assign its content to its parent.
    for index, container in enumerate(containers, 1):
        if _nodes(container, 'sele_all'):
            flags.append('nested_answer_container')
            continue
        blocks = _nodes(container, 'sele_txt')
        if len(blocks) != 1:
            flags.append('answer_body_unrecognized')
            continue
        block = blocks[0]
        parts = [block]
        recovered_content = None
        # HTML parsers repair nested <p> by moving its children to sibling <p>s.
        # Only recover inside this answer, stopping at the first structural boundary.
        for sibling in block.itersiblings():
            # One observed repair puts the answer in a named paragraph directly
            # after an empty sele_txt. Do not search past UI/structural siblings,
            # accept arbitrary IDs, or consume any paragraphs after this field.
            if (len(parts) == 1 and not _content_text(block, answer=True)
                    and block.getparent() is container and sibling.tag == 'p'
                    and not sibling.get('class')
                    and re.fullmatch(r'content[1-9][0-9]*', sibling.get('id') or '')
                    and _nearest(sibling, 'sele_all') is container):
                parts.append(sibling)
                recovered_content = tree.getpath(sibling)
                break
            if sibling.tag != 'p' or sibling.get('class') or sibling.get('id'):
                break
            parts.append(sibling)
        text = '\n\n'.join(_content_text(part, answer=True) for part in parts if _content_text(part, answer=True))
        answer_fields.extend(parts)
        if recovered_content:
            actions.append(dict(rule='recover_empty_answer_content_paragraph', locator=tree.getpath(block),
                                recovered_locator=recovered_content, answer_locator=tree.getpath(container)))
        elif len(parts) > 1:
            actions.append(dict(rule='recover_nested_paragraphs', locator=tree.getpath(block),
                                recovered_paragraphs=len(parts)-1))
        headers = _nodes(container, 'doctor_all')
        header = headers[0] if len(headers) == 1 else None
        names = _nodes(header, 'doc_name') if header is not None else []
        profiles = names[0].xpath('.//a/@href') if names else []
        times = _nodes(container, 'doc_time')
        reply_dom_id = header.get('id') if header is not None else None
        identity = _answer_identity(container,question_id,tree,raw_hash,flags)
        if not text: flags.append('empty_main_answer')
        if header is None: flags.append('answer_author_unrecognized')
        answers.append(dict(**identity, reply_dom_id=reply_dom_id, order=index,
            text=text, source_text='\n\n'.join(_text(part) for part in parts if _text(part)), text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            locator=tree.getpath(container), body_locators=[tree.getpath(p) for p in parts],
            author_name=_text(names[0]) if len(names) == 1 else None,
            author_profile_url=urljoin(url, profiles[0]) if profiles else None,
            author_header_raw='\n'.join(_text(n) for n in _nodes(header, 'doc_xinx')) if header is not None else '',
            qualification_raw=[_text(n) for n in _nodes(header, 'doc_yshi')] if header is not None else [],
            answered_at=_text(times[0]) if times else None,
            speaker_role='responder', followups=[],
            patient_evaluations=_patient_evaluations(parts,container,identity,tree,raw_hash)))
        owners[container] = answers[-1]
    all_blocks = _nodes(root, 'sele_txt')
    if len(all_blocks) != len(answers): flags.append('unmapped_answer_blocks')
    if not answers: flags.append('no_main_answers')
    if len({a['answer_id'] for a in answers}) != len(answers):
        flags.append('duplicate_answer_id')
    followups = _followups(root, owners, tree, flags)
    if warning: flags.append('decode_suspect')
    rendered = ['问题：' + title]
    rendered.extend(q['text'] for q in questions if compact(q['text']) != compact(title))
    for answer in answers:
        rendered.extend(['回答者：' + (answer['author_name'] or '未注明'), answer['text']])
        for message in answer['followups']:
            label = {'patient': '患者追问', 'responder': '回答者补充回答'}.get(message['speaker_role'], '后续交流（身份未明）')
            rendered.append(label + '：' + message['text'])
    for message in followups:
        if message['parent_answer_id'] is None:
            rendered.append('后续交流（所属回答未明）：' + message['text'])
    text = '\n\n'.join(rendered)
    flags = sorted(set(flags))
    return dict(title=title, source_question_id=question_id, question=dict(title=title, blocks=questions), answers=answers, followups=followups,
        text=text, char_count=len(text), text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        extractor=EXTRACTOR, parser_version=VERSION, declared_encoding=encoding,
        decode_warning=warning, source_answer_count=len(all_blocks), main_answer_count=len(answers),
        source_followup_count=len(followups), followup_count=sum(bool(m['text']) for m in followups),
        orphan_followup_count=sum(m['parent_answer_id'] is None for m in followups),
        unknown_followup_roles=sum(m['speaker_role'] == 'unknown' for m in followups),
        normalization_actions=actions,
        dom_exclusions=_exclusion_evidence(root, tree, answer_fields),
        parser_status='review' if flags else 'parsed', parser_flags=flags,
        quality_status='review', quality_flags=sorted(set(flags + ['candidate_only'])),
        corpus_eligible=False)
