"""DOM parser and observable-HTML QC for 120ask question pages.

The compact corpus keeps only ``text``.  Thread structure, pre-tail-removal text
and QC counters stay in the per-ID checkpoint record beside the raw HTML.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from urllib.parse import urlsplit

from lxml import html


VERSION = '120ask-parser-v2'
EXTRACTOR = '120ask_qa_dom_v2'
HOSTS = {'120ask.com', 'www.120ask.com'}
QUESTION_PATH = re.compile(r'/question/[0-9]+\.htm')
TAIL = re.compile(
    r'\s*以上是对[“"「『](?P<title>[^”"」』\n]{1,200})[”"」』](?:这个)?问题的建议'
    r'[，,。；;\s]*希望对您有帮助(?:[，,。；;\s]*祝您健康)?[！!。.\s]*$'
)
LABELS = {
    'doctor_answer': '医生回答',
    'patient_followup': '患者追问',
    'doctor_followup': '医生补充回答',
    'unknown_followup': '后续交流',
}
UI_MARKERS = (
    '其他类似问题', '相关文章', '相关药品', '医生在线免费咨询', '请使用微信扫一扫',
    '投诉', '赠送医生锦旗', '点击查看大图',
)
REMOVED_TAGS = {'script', 'style', 'iframe', 'form', 'button', 'input', 'noscript', 'svg'}
REMOVED_CLASSES = {
    'codeposition', 'tousu', 'b_askbox_btn', 'img', 'qrcode', 'qr-code',
    'b_ansaddtime', 'b_ansaddname', 'nickname', 'timestamp',
}


def normalize(text):
    return re.sub(r'\s+', ' ', text or '').strip()


def compact(text):
    return re.sub(r'\s+', '', text or '')


def is_question_url(url):
    parsed = urlsplit(str(url))
    return (parsed.scheme in ('http', 'https') and (parsed.hostname or '').lower() in HOSTS
            and QUESTION_PATH.fullmatch(parsed.path) is not None)


def _classes(node):
    return set((node.get('class') or '').split())


def _has_class(node, name):
    return name in _classes(node)


def _decode(body, content_type=''):
    header = re.search(r'charset\s*=\s*["\']?([\w-]+)', content_type or '', re.I)
    meta = re.search(rb'charset\s*=\s*["\']?([\w-]+)', body[:16384], re.I)
    declared = header.group(1) if header else meta.group(1).decode('ascii', 'ignore') if meta else ''
    candidates = [declared, 'utf-8', 'gb18030']
    tried = set()
    for candidate in candidates:
        encoding = candidate.lower().strip()
        if encoding in ('gb2312', 'gbk', 'x-gbk'):
            encoding = 'gb18030'
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            return body.decode(encoding, 'strict'), encoding, False
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode('utf-8', 'replace'), declared.lower() or None, True


def _tree(body, content_type=''):
    decoded, encoding, warning = _decode(body, content_type)
    try:
        return html.fromstring(decoded), encoding, warning
    except (ValueError, html.etree.ParserError) as exc:
        raise ValueError('120ask HTML is not parseable') from exc


def _remove_noise(node):
    clone = deepcopy(node)
    for child in list(clone.iterdescendants()):
        if not isinstance(child.tag, str):
            continue
        classes = _classes(child)
        if (child.tag.lower() in REMOVED_TAGS or classes & REMOVED_CLASSES
                or any('qrcode' in value.lower() for value in classes)):
            child.drop_tree()
    return clone


def _node_text(node, *, followup=False):
    if node is None:
        return ''
    clone = _remove_noise(node)
    if followup:
        # The verified template stores dialogue content in direct child p nodes.
        # Falling back to all visible text would silently include nickname/time/UI.
        paragraphs = [child for child in clone if isinstance(child.tag, str)
                      and child.tag.lower() == 'p']
        return normalize(' '.join(normalize(p.text_content()) for p in paragraphs))
    for child in list(clone.iterdescendants()):
        if _has_class(child, 'b_ansaddli'):
            child.drop_tree()
    cores = [node for node in clone.iterdescendants()
             if _has_class(node, 'crazy_new') and (node.get('id') or '').startswith('reply')]
    return normalize(' '.join(node.text_content() for node in (cores or [clone])))


def _nearest_answer_card(node):
    parent = node.getparent()
    while parent is not None:
        if _has_class(parent, 'b_answerli'):
            return parent
        parent = parent.getparent()
    return None


def _owned_blocks(card):
    return [node for node in card.iterdescendants()
            if (_has_class(node, 'b_anscont_cont') or _has_class(node, 'b_ansaddli'))
            and _nearest_answer_card(node) is card]


def _role(node):
    if _has_class(node, 'b_anscont_cont'):
        return 'doctor_answer'
    if any(_has_class(child, 'b_docaddti') for child in node.iterdescendants()):
        return 'doctor_followup'
    if any(_has_class(child, 'b_ansaddti') for child in node.iterdescendants()):
        return 'patient_followup'
    return 'unknown_followup'


def _remove_tail(text, title):
    match = TAIL.search(text)
    if not match or compact(match.group('title')) != compact(title):
        return text, False
    return text[:match.start()].rstrip(), True


def _published_reply_count(tree):
    values = []
    for value in tree.xpath('//text()[contains(., "人回复")]'):
        values.extend(int(number) for number in re.findall(r'([0-9]+)\s*人回复', str(value)))
    return values[0] if values and len(set(values)) == 1 else None


def _publication_date(tree):
    nodes = tree.xpath('//*[contains(concat(" ", normalize-space(@class), " "), " b_askab1 ")]')
    text = normalize(' '.join(node.text_content() for node in nodes))
    match = re.search(r'(?<![0-9])(20[0-9]{2}|19[0-9]{2})[-/.年]([01]?[0-9])[-/.月]([0-3]?[0-9])', text)
    if not match:
        return None
    return f'{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}'


def extract(body, url, content_type=''):
    """Extract one exact 120ask question URL without a generic-text fallback."""
    if not is_question_url(url):
        raise ValueError('Not a 120ask /question/<id>.htm URL')
    tree, encoding, decode_warning = _tree(body, content_type)
    title_nodes = tree.xpath('//*[@id="d_askH1"]')
    if not title_nodes:
        title_nodes = tree.xpath(
            '//*[contains(concat(" ", normalize-space(@class), " "), " b_askti ")]//h1')
    question_nodes = tree.xpath('//*[@id="d_msCon"]')
    if not question_nodes:
        question_nodes = tree.xpath(
            '//*[contains(concat(" ", normalize-space(@class), " "), " b_askbox ")]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " b_askcont ")]')
    title = normalize(title_nodes[0].text_content()) if title_nodes else ''
    question = _node_text(question_nodes[0]) if question_nodes else ''

    answer_boxes = tree.xpath(
        '//*[contains(concat(" ", normalize-space(@class), " "), " b_answerbox ")]')
    answer_boxes = [box for box in answer_boxes
                    if not any(_has_class(parent, 'b_answerbox') for parent in box.iterancestors())]
    cards = []
    for box in answer_boxes:
        cards.extend(node for node in box.iterdescendants() if _has_class(node, 'b_answerli')
                     and not any(_has_class(parent, 'b_answerli') for parent in node.iterancestors()))
    all_followups = [node for box in answer_boxes for node in box.iterdescendants()
                     if _has_class(node, 'b_ansaddli')]
    source_followups_with_text = sum(bool(_node_text(node, followup=True)) for node in all_followups)
    source_main_regions = 0
    empty_main_regions = 0
    attached_followups = 0
    unrecognized_followups = sum(
        not bool(_node_text(node, followup=True)) and bool(normalize(_remove_noise(node).text_content()))
        for node in all_followups
    )
    unknown_roles = 0
    removed_tails = 0
    threads = []

    for card in cards:
        blocks = _owned_blocks(card)
        main_blocks = [block for block in blocks if _has_class(block, 'b_anscont_cont')]
        source_main_regions += len(main_blocks)
        empty_main_regions += sum(not bool(_node_text(block)) for block in main_blocks)
        if not main_blocks:
            continue
        doctor_nodes = card.xpath(
            './/*[contains(concat(" ", normalize-space(@class), " "), " b_answertl ")]'
            '//*[contains(concat(" ", normalize-space(@class), " "), " b_sp1 ")]//a')
        reply_nodes = card.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " crazy_new ")]')
        reply = next((node for node in reply_nodes if (node.get('id') or '').startswith('reply')), None)
        thread = {'index': len(threads) + 1,
                  'doctor': normalize(doctor_nodes[0].text_content()) if doctor_nodes else '',
                  'reply_id': reply.get('id', '') if reply is not None else '', 'turns': []}
        thread_attached_followups = 0
        thread_unknown_roles = 0
        for block in blocks:
            role = _role(block)
            is_main = role == 'doctor_answer'
            raw_text = _node_text(block, followup=not is_main)
            if not raw_text:
                continue
            cleaned, removed = _remove_tail(raw_text, title) if role in (
                'doctor_answer', 'doctor_followup') else (raw_text, False)
            removed_tails += int(removed)
            if not is_main:
                thread_attached_followups += 1
                thread_unknown_roles += int(role == 'unknown_followup')
            if not cleaned:
                continue
            thread['turns'].append({'role': role, 'text': cleaned, 'raw_text': raw_text})
        if any(turn['role'] == 'doctor_answer' for turn in thread['turns']):
            attached_followups += thread_attached_followups
            unknown_roles += thread_unknown_roles
            threads.append(thread)
    # Follow-ups outside a usable card are observable but cannot be safely assigned.
    orphan_followups = max(0, source_followups_with_text - attached_followups)
    turns = [turn for thread in threads for turn in thread['turns']]
    main_answers = [turn['text'] for turn in turns if turn['role'] == 'doctor_answer']
    text_parts = [title, '问题：\n' + question] if title else ['问题：\n' + question]
    raw_parts = list(text_parts)
    for thread in threads:
        for turn in thread['turns']:
            suffix = f" {thread['index']}"
            if thread['doctor'] and turn['role'] in ('doctor_answer', 'doctor_followup'):
                suffix += f"（{thread['doctor']}）"
            label = LABELS[turn['role']] + suffix + '：'
            text_parts.append(label + '\n' + turn['text'])
            raw_parts.append(label + '\n' + turn['raw_text'])
    text = '\n\n'.join(part for part in text_parts if part.strip())
    text_raw = '\n\n'.join(part for part in raw_parts if part.strip())
    published_count = _published_reply_count(tree)
    page_probe = normalize(' '.join(tree.xpath('//title//text() | //h1//text() | //body//text()')))[:4000]
    challenge_detected = bool(re.search(
        r'access denied|just a moment|attention required|checking your browser|cookies must be enabled|'
        r'verify you are human|enable javascript and cookies|验证码|安全验证|访问受限',
        page_probe, re.I))
    duplicate_groups = {}
    for thread in threads:
        for turn in thread['turns']:
            key = compact(turn['text'])
            if key:
                duplicate_groups.setdefault(key, []).append((thread['index'], turn['role']))
    duplicate_groups = [locations for locations in duplicate_groups.values() if len(locations) > 1]
    qc = {
        'scope': 'observable_html_only',
        'source_main_answer_regions': source_main_regions,
        'extracted_main_answers': len(main_answers),
        'published_reply_count': published_count,
        'published_reply_difference': (None if published_count is None else len(main_answers) - published_count),
        'source_followup_blocks': len(all_followups),
        'source_followups_with_direct_p_text': source_followups_with_text,
        'attached_followups': attached_followups,
        'unrecognized_followup_blocks': unrecognized_followups,
        'orphan_followups': orphan_followups,
        'unknown_followup_roles': unknown_roles,
        'empty_main_answer_regions': empty_main_regions,
        'removed_template_tails': removed_tails,
        'duplicate_turn_groups': len(duplicate_groups),
        'ui_markers_in_text': [marker for marker in UI_MARKERS if marker in text],
    }
    reasons = []
    if len(title_nodes) != 1 or not title:
        reasons.append('ask120_missing_or_ambiguous_title')
    if len(question_nodes) != 1 or len(compact(question)) < 10:
        reasons.append('ask120_missing_or_ambiguous_question')
    if not main_answers:
        reasons.append('ask120_no_main_answer')
    if source_main_regions != len(main_answers) or empty_main_regions:
        reasons.append('ask120_main_answer_mismatch')
    if published_count is not None and published_count != len(main_answers):
        reasons.append('ask120_published_reply_mismatch')
    if unrecognized_followups:
        reasons.append('ask120_unrecognized_followup_structure')
    if orphan_followups:
        reasons.append('ask120_orphan_followup')
    if unknown_roles:
        reasons.append('ask120_unknown_followup_role')
    if attached_followups != source_followups_with_text:
        reasons.append('ask120_followup_count_mismatch')
    if qc['ui_markers_in_text']:
        reasons.append('ask120_ui_marker_suspect')
    if decode_warning or '\ufffd' in text:
        reasons.append('ask120_decode_suspect')
    if challenge_detected:
        reasons.append('error_or_challenge')
    access_pass = (bool(title) and len(compact(question)) >= 10 and bool(main_answers)
                   and sum(len(compact(answer)) for answer in main_answers) >= 20
                   and not reasons)
    return {
        'title': title, 'text': text, 'extractor': EXTRACTOR,
        'published_at': _publication_date(tree), 'declared_encoding': encoding,
        'decode_warning': decode_warning, 'source_question_chars': len(question),
        'source_answer_count': len(main_answers),
        'source_body_chars': sum(len(answer) for answer in main_answers),
        'source_followup_count': len(all_followups),
        'main_answer_count': len(main_answers), 'followup_count': attached_followups,
        'patient_followups': sum(turn['role'] == 'patient_followup' for turn in turns),
        'doctor_followups': sum(turn['role'] == 'doctor_followup' for turn in turns),
        'unknown_roles': unknown_roles, 'removed_template_tails': removed_tails,
        'ask120_question': question, 'ask120_main_answers': main_answers,
        'ask120_threads': threads, 'ask120_qc': qc,
        'ask120_text_raw': text_raw,
        'ask120_text_raw_sha256': hashlib.sha256(text_raw.encode('utf-8')).hexdigest(),
        'ask120_review_reasons': reasons, 'ask120_access_pass': access_pass,
        'ask120_challenge_detected': challenge_detected,
        'ask120_parser_version': VERSION,
        'extraction_selectors': ['#d_askH1 / .b_askti h1', '#d_msCon / .b_askbox .b_askcont',
                                 '.b_answerbox .b_answerli (DOM-order owned turns)'],
    }


def audit(body, url, record, content_type=''):
    """Re-extract raw evidence and compare the complete parser sidecar."""
    doc = extract(body, url, content_type)
    fields = (
        'title', 'text', 'extractor', 'published_at', 'source_question_chars',
        'source_answer_count', 'source_body_chars', 'source_followup_count',
        'main_answer_count', 'followup_count', 'patient_followups', 'doctor_followups',
        'unknown_roles', 'removed_template_tails',
        'ask120_question', 'ask120_main_answers', 'ask120_threads', 'ask120_qc',
        'ask120_text_raw', 'ask120_text_raw_sha256', 'ask120_review_reasons',
        'ask120_access_pass', 'ask120_parser_version',
        'ask120_challenge_detected',
    )
    mismatches = [field for field in fields if doc.get(field) != record.get(field)]
    if mismatches:
        raise ValueError('120ask raw/checkpoint mismatch: ' + ', '.join(mismatches))
    qc = doc['ask120_qc']
    return {
        'ask120_raw_reextraction_verified': True,
        'ask120_main_answers_verified': qc['extracted_main_answers'],
        'ask120_followups_verified': qc['attached_followups'],
        'ask120_orphan_followups': qc['orphan_followups'],
        'ask120_unknown_followup_roles': qc['unknown_followup_roles'],
        'ask120_qc_scope': qc['scope'],
    }
