"""DOM parser and observable-HTML QC for 120ask question pages.

The compact corpus keeps only ``text``.  Thread structure, pre-tail-removal text
and QC counters stay in the per-ID checkpoint record beside the raw HTML.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from urllib.parse import urlsplit, urljoin

from lxml import html


VERSION = '120ask-parser-v4.2'
EXTRACTOR = '120ask_qa_dom_v4'
HOSTS = {'120ask.com', 'www.120ask.com'}
QUESTION_PATH = re.compile(r'/question/[0-9]+\.htm')
TAIL = re.compile(
    r'\s*以上是对[“"「『](?P<title>[^”"」』\n]{1,200})[”"」』](?:这个)?问题的建议'
    r'[，,。；;\s]*希望对您有帮助(?:[，,。；;\s]*祝您健康)?[！!。.\s]*$'
)
LABELS = {
    'responder_answer': '回答者',
    'patient_followup': '患者追问',
    'responder_followup': '回答者补充回答',
    'unknown_followup': '后续交流',
}
ADMISSIBLE_SOURCE_ROLES = ('physician', 'pharmacist', 'nurse')
AUTHOR_FIELDS = ('author_name', 'author_profile_url', 'header_raw', 'qualification_raw',
                 'qualification_title', 'source_role', 'source_role_status', 'author_evidence')
QUALIFICATION_RULES = tuple((role, re.compile(r'(?:^|\s)(' + titles + r')(?=\s|$)'))
    for role, titles in (
        ('physician', r'(?:(?:副主任|主任|主治|住院|执业助理|执业)医师|医师|医士|医生)'),
        ('pharmacist', r'(?:(?:副主任|主任|主管|执业)?中?药师|药士)'),
        ('nurse', r'(?:(?:副主任|主任|主管)?护师|护士)'),
        ('psychologist', r'(?:(?:一级|二级|三级|高级)?心理咨询师|心理治疗师)'),
        ('laboratory_professional', r'(?:(?:一级|二级|三级|副主任|主任|主管)?(?:检验师|检验士|技师|技士))'),
    ))
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
        return 'responder_answer'
    responder = any(_has_class(child, 'b_docaddti') for child in node.iterdescendants())
    patient = any(_has_class(child, 'b_ansaddti') for child in node.iterdescendants())
    if responder and patient:
        return 'unknown_followup'
    if responder:
        return 'responder_followup'
    if patient:
        return 'patient_followup'
    return 'unknown_followup'


def classify_source_role(qualification):
    """Use an unambiguous title in the qualification field, never the nickname."""
    value = normalize(qualification)
    if value == '其他':
        return 'other', None, 'source_asserted'
    if re.search(r'不是|并非|非执业|未认证|待认证|(?:^|\s)非\s', value):
        return 'unknown', None, 'unrecognized'
    matches = [(role, m.group(1), m.end()) for role, pattern in QUALIFICATION_RULES
               for m in pattern.finditer(value)]
    if len({role for role, _, _ in matches}) == 1 and any(end == len(value) for _, _, end in matches):
        role, title, _ = next(match for match in matches if match[2] == len(value))
        return role, title, 'source_asserted'
    return 'unknown', None, 'unrecognized'


def _empty_author(status='missing', **evidence):
    return dict(author_name=None, author_profile_url=None, header_raw='', qualification_raw='',
                qualification_title=None, source_role='unknown', source_role_status='unrecognized',
                author_evidence=dict(attribution_status=status, credential_verification='source_only',
                                     role_basis='qualification_only', **evidence))


def author_snapshot(source):
    return {key:deepcopy(source.get(key)) for key in AUTHOR_FIELDS}


def _card_author(card, url):
    headers = [n for n in card.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," b_answertl ")]'
               '//*[contains(concat(" ",normalize-space(@class)," ")," b_sp1 ")]')
               if _nearest_answer_card(n) is card]
    if len(headers) != 1:
        return _empty_author('ambiguous' if headers else 'missing', scope='card',
                             header_candidates=[_locator(n) for n in headers])
    header = headers[0]
    result = _empty_author(scope='card', header_dom_locator=_locator(header),
                           header_html=html.tostring(header, encoding='unicode', with_tail=False))
    result['header_raw'] = normalize(header.text_content())
    names = header.xpath('./*[self::a or self::var]')
    if len(names) != 1 or not normalize(names[0].text_content()):
        result['author_evidence']['attribution_status'] = 'ambiguous' if names else 'missing'
        return result
    name = names[0]
    clone = deepcopy(header)
    clone.xpath('./*[self::a or self::var]')[0].drop_tree()
    qualification = normalize(clone.text_content())
    role, title, status = classify_source_role(qualification)
    href = urljoin(url, name.get('href', '')) if name.get('href') else None
    if href and urlsplit(href).scheme not in ('http', 'https'):
        href = None
    result.update(author_name=normalize(name.text_content()), author_profile_url=href,
                  qualification_raw=qualification, qualification_title=title,
                  source_role=role, source_role_status=status)
    result['author_evidence'].update(attribution_status='resolved', name_dom_locator=_locator(name))
    return result


def author_review_reasons(author, allowed_roles=ADMISSIBLE_SOURCE_ROLES):
    evidence = author.get('author_evidence') or {}
    reasons = []
    if (not author.get('author_name') or evidence.get('attribution_status') != 'resolved'
            or not evidence.get('header_dom_locator') or not evidence.get('name_dom_locator')):
        reasons.append('AUTHOR_IDENTITY_REVIEW')
    role, title, _ = classify_source_role(author.get('qualification_raw', ''))
    if role in ('unknown', 'other') or (role, title) != (author.get('source_role'), author.get('qualification_title')):
        reasons.append('AUTHOR_ROLE_REVIEW')
    elif role not in allowed_roles:
        reasons.append('AUTHOR_PROFESSION_REVIEW')
    return reasons


def _followup_author(thread, block, role):
    if role != 'responder_followup':
        result = _empty_author(scope='followup', turn_dom_locator=_locator(block))
        names = block.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," b_ansaddti ")]//em')
        if role == 'patient_followup' and len(names) == 1:
            result['author_name'] = normalize(names[0].text_content())
            result['author_evidence']['name_dom_locator'] = _locator(names[0])
        return result
    names = block.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," b_docaddti ")]//*[self::em or self::a]')
    if names and (len(names) != 1 or normalize(names[0].text_content()) != thread.get('author_name')):
        result = _empty_author('unresolved_name_mismatch', scope='followup', turn_dom_locator=_locator(block))
        result['author_name'] = normalize(names[0].text_content()) if len(names) == 1 else None
        return result
    result = author_snapshot(thread)
    result['author_evidence'].update(scope='owned_reply_followup', turn_dom_locator=_locator(block),
        attribution_basis='owned_single_reply_responder_channel' if result['author_evidence']['attribution_status']=='resolved'
                          else 'owner_reply_author_unresolved')
    return result


def render_turn(thread, turn, value):
    """Render a neutral conversation label and the source-asserted title."""
    details = []
    if turn.get('author_name') and turn['speaker_role'] != 'unknown':
        details.append(turn['author_name'])
    if (turn['speaker_role'] == 'responder' and turn.get('qualification_title')
            and (turn.get('author_evidence') or {}).get('attribution_status') == 'resolved'):
        details.append('来源职称：' + turn['qualification_title'])
    suffix = '（' + '；'.join(details) + '）' if details else ''
    return f"{LABELS[turn['role']]} {thread['index']}{suffix}：\n{value}"


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



LEGACY_MARKUP = re.compile(r'</?(?:p|br|div|span)\b[^<>]*>', re.I)
AUDIO_FALLBACK = re.compile(r'您的浏览器不支持\s*audio\s*元素[。.]?|your browser does not support.*?audio[.]?', re.I)
QUESTION_LABELS = re.compile(r'健康咨询描述\s*[：:]|曾经的治疗情况和效果\s*[：:]|想得到怎样的帮助\s*[：:]')
# Verified reply templates, not individual keywords such as 咨询/采纳. Sentence
# boundaries avoid removing quoted examples or a prefix inside a longer clause.
REPLY_BOILERPLATE = tuple((rule_id, re.compile(
    r'(?<![^\s。！？.!?：:])' + expression + r'(?:[。！!.]|(?=\s|$))'))
    for rule_id, expression in (
        ('accept_satisfied_answer', r'如果有了满意的回答请及时采纳[，,]\s*不要辜负了回答者'),
        ('accept_volunteer_answer', r'(?:你好[，,]\s*)?这里的医生都是利用工作之余在作热心的解答[，,]\s*'
         r'如果我的回答对你有所帮助[，,]\s*请你点击采纳答案[，,]\s*这是对我们的唯一支持'),
        ('accept_spare_time_answer', r'这里的医生都是用业余时间在这里回答问题的[，,]\s*'
         r'请及时点击["“]?采纳为答案["”]?[，,]\s*这是对他们热心帮助的唯一肯定'),
        ('online_consultation_reminder', r'我的回答如果还有什么不明白最好到在线咨询与医生面对面的交流'),
        ('generic_health_wish', r'愿有病的人早日恢复健康[，,]\s*没病的人永远健康'),
    ))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def normalize_legacy_markup(text):
    """Two bounded entity passes, only for known escaped formatting tags."""
    import html as entity
    original = text
    actions = []
    for step in range(2):
        decoded = entity.unescape(text)
        if not LEGACY_MARKUP.search(decoded):
            break
        matches = [m.group() for m in LEGACY_MARKUP.finditer(decoded)]
        # Replace only allowlisted formatting markup; inequalities/gene symbols survive.
        text = LEGACY_MARKUP.sub(lambda m: '\n' if re.match(r'</?(?:p|br|div)\b', m.group(), re.I) else '', decoded)
        actions.append({'action':'normalize_legacy_formatting', 'pass':step + 1,
                        'matched_tags':matches, 'before_sha256':sha(original), 'after_sha256':sha(text)})
    text = '\n'.join(re.sub(r'[ \t\u00a0]+',' ',line).strip() for line in text.splitlines() if line.strip())
    return text, actions


def _paragraph_text(node):
    clone = _remove_noise(node)
    for e in clone.iter():
        if not isinstance(e.tag, str): continue
        if e.tag.lower() == 'br':
            e.tail = '\n' + (e.tail or '')
        elif e.tag.lower() in ('p','div','section','li'):
            e.text = '\n' + (e.text or '')
            e.tail = '\n' + (e.tail or '')
    return '\n'.join(re.sub(r'[ \t\u00a0]+',' ',s).strip() for s in clone.text_content().splitlines() if s.strip())


QUESTION_NORMALIZER_VERSION = '120ask-question-normalization-v1'
QUESTION_FORMAT_TOKEN = re.compile(
    r'(?:<|&lt;|&amp;lt;)/?(?:p|br|div|span)\b[^<>\n]{0,256}?(?:>|&gt;|&amp;gt;)', re.I)
QUESTION_LABEL_LINE = re.compile(
    r'(?m)^[ \t]*(?:健康咨询描述|曾经的治疗情况和效果|想得到怎样的帮助)\s*[：:][ \t]*')
QUESTION_FOOTER_LINE = re.compile(
    r'(?m)^[ \t]*\|[ \t]*投诉[ \t]*\|[ \t]*评价[（(][ \t]*\d+[ \t]*[)）]?[ \t]*$')
QUESTION_MARKUP_SUSPECT = re.compile(
    r'(?:<|&(?:amp;){0,5}lt;)/?(?:p|br|div|span)\b[^\n]{0,120}?'
    r'(?:>|&(?:amp;){0,5}gt;|$)|(?<![A-Za-z0-9_])BR\s*/?>', re.I)


def _question_replace(text, matches, actions, rule_id, *, evidence=None):
    """Record exact spans on the text before this action, with replacements."""
    if not matches:
        return text
    before = text
    for item in reversed(matches):
        text = text[:item['char_start']] + item['replacement'] + text[item['char_end']:]
    actions.append({'action':'normalize_question', 'rule_id':rule_id, 'ruleset_version':QUESTION_NORMALIZER_VERSION,
                    'offset_basis':'text_before_action', 'spans':matches,
                    'before_sha256':sha(before), 'after_sha256':sha(text),
                    'evidence':evidence or {}})
    return text


def _question_layout(text, actions):
    clean = '\n'.join(re.sub(r'[ \t\u00a0]+',' ',line).strip()
                      for line in text.splitlines() if line.strip())
    if clean != text:
        return _question_replace(text, [{'char_start':0, 'char_end':len(text), 'text':text,
                                        'replacement':clean}], actions, 'question_whitespace_v1')
    return text


def _question_template_evidence(node):
    """Only the observed question paragraph/header, never an arbitrary BR> occurrence."""
    evidence = {}
    if node is None or not (node.get('id')=='d_msCon' or _has_class(node,'b_askcont')):
        return evidence
    for paragraph in node.iterdescendants():
        if paragraph.tag != 'p' or not _has_class(paragraph,'crazy_new'):
            continue
        children = list(paragraph)
        if (not children or children[0].tag!='span' or normalize(paragraph.text or '')
                or not re.fullmatch(r'健康咨询描述\s*[：:]', normalize(children[0].text_content()))):
            continue
        label = children[0]
        starts_question = (paragraph.getparent() is node and not normalize(node.text or '')
            and all(not normalize((s.text_content() if isinstance(s.tag,str) else '')+(s.tail or ''))
                    for s in paragraph.itersiblings(preceding=True)))
        if starts_question and re.match(r'^\s*BR>', label.tail or ''):
            evidence['leading_br'] = {'header_dom_locator':_locator(label),
                'paragraph_dom_locator':_locator(paragraph), 'source':'literal prefix in header span tail'}
        if (len(children)>=3 and children[-1].tag=='br' and children[-2].tag=='br'
                and not normalize(children[-2].tail or '')
                and QUESTION_FOOTER_LINE.fullmatch(normalize(children[-1].tail or ''))):
            evidence['footer'] = {'dom_locator':_locator(children[-1]),
                'paragraph_dom_locator':_locator(paragraph), 'source':'terminal two-br complaint/evaluation template'}
    return evidence


def question_qc(text):
    """Question-only formatting/UI evidence; clinical symbols and narrative words survive."""
    markup = [{'char_start':m.start(), 'char_end':m.end(), 'text':m.group()}
              for m in QUESTION_MARKUP_SUSPECT.finditer(text)]
    ui = [{'char_start':m.start(), 'char_end':m.end(), 'text':m.group(),
           'rule_id':'question_complaint_evaluation_footer_v1'} for m in QUESTION_FOOTER_LINE.finditer(text)]
    # A narrative containing 投诉 or a quoted UI term is not an interface footer.
    markers = [m for m in UI_MARKERS if m!='投诉']
    for match in re.finditer(r'(?m)^[ \t]*([^\n]+?)[ \t]*$', text):
        if match.group(1).strip(' |') in markers:
            ui.append({'char_start':match.start(), 'char_end':match.end(), 'text':match.group(),
                       'rule_id':'question_standalone_ui_line_v1'})
    reasons = (['QUESTION_MARKUP_REVIEW'] if markup else []) + (['QUESTION_UI_CONTAMINATION_REVIEW'] if ui else [])
    return {'scope':'question_only', 'ruleset_version':QUESTION_NORMALIZER_VERSION,
            'clean_text_sha256':sha(text), 'residual_markup':bool(markup),
            'markup_matches':markup, 'ui_matches':ui, 'review_reasons':reasons}


def normalize_question(node, *, node_count=1):
    import html as entity
    raw = _paragraph_text(node) if node is not None else ''
    source_html = html.tostring(node,encoding='unicode',with_tail=False) if node is not None else ''
    actions = []
    text = raw
    matches = []
    for match in QUESTION_FORMAT_TOKEN.finditer(text):
        token = match.group()
        decoded = token
        for _ in range(2):
            decoded = entity.unescape(decoded)
        if not LEGACY_MARKUP.fullmatch(decoded):
            continue
        matches.append({'char_start':match.start(), 'char_end':match.end(), 'text':token,
            'replacement':'\n' if re.match(r'</?(?:p|br|div)\b',decoded,re.I) else '', 'decoded_tag':decoded})
    text = _question_replace(text,matches,actions,'question_known_formatting_v1')
    text = _question_replace(text,[{'char_start':m.start(), 'char_end':m.end(), 'text':m.group(), 'replacement':''}
                                  for m in QUESTION_LABEL_LINE.finditer(text)],actions,'question_label_prefix_v1')
    text = _question_layout(text,actions)
    evidence = _question_template_evidence(node)
    if text.startswith('BR>') and evidence.get('leading_br'):
        text = _question_replace(text,[{'char_start':0,'char_end':3,'text':'BR>','replacement':''}],
            actions,'question_leading_br_fragment_v1',evidence=evidence['leading_br'])
    if evidence.get('footer'):
        matches = [{'char_start':m.start(),'char_end':m.end(),'text':m.group(),'replacement':''}
                   for m in QUESTION_FOOTER_LINE.finditer(text) if m.end()==len(text)]
        text = _question_replace(text,matches,actions,'question_complaint_evaluation_footer_v1',
            evidence=evidence['footer'])
    text = _question_layout(text,actions)
    provenance = {'normalizer_version':QUESTION_NORMALIZER_VERSION,'dom_locator':_locator(node) if node is not None else None,
        'node_count':node_count,'raw_text_basis':'paragraph_text_after_existing_dom_noise_filter',
        'raw_text':raw,'raw_text_sha256':sha(raw),'source_html_basis':'serialized_source_question_dom',
        'source_html':source_html,'source_html_sha256':sha(source_html),
        'clean_text_sha256':sha(text),'actions':actions}
    return text, provenance, question_qc(text)


QUESTION_CONTEXT_VERSION = '120ask-question-context-v1'
QUESTION_CONTEXT_RULES = tuple((name,re.compile(pattern)) for name,pattern in (
    ('field_label',r'(?m)^(?:本次发病及持续(?:的)?时间|患者年龄|患者性别|病史|目前一般情况|以往(?:的)?诊断(?:和)?治疗经过(?:及效果)?|辅助检查|其它|其他|问题描述|咨询目的|化验[、,，]?检查结果|想得到(?:的)?帮助)\s*[:：]?'),
    ('calendar_date',r'\d{4}[-./年]\d{1,2}[-./月]\d{1,2}日?'),
    ('duration_age',r'(?:[0-9０-９一二三四五六七八九十百两半]+)(?:[~～—-][0-9一二三四五六七八九十两]+)?(?:多|余|个)?(?:年|个月|月|周|星期|天|日|小时|分钟|岁)(?:前|后|左右|以来|了|多)?'),
    ('vague_duration',r'很多年|好几年|几年|多年|数年|好几(?:年|月|天)|一段时间|很长时间|长时间|很久|好久|多日|一阵子'),
    ('relative_time',r'今年|昨天|今天|前天|今早|上午|下午|晚上'),
    ('demographic',r'(?m)^\s*(?:(?:男|女|男性|女性)\s*(?:[0-9０-９一二三四五六七八九十两]+)?(?:岁|周岁)?|[0-9０-９一二三四五六七八九十两]+(?:岁|周岁)?|岁|周岁|时间了?|无症状|无明显症状|没有不适)\s*[:：]?\s*$'),
    ('greeting_request',r'您好|你好|谢谢(?:您|你|医生|专家)?|多谢|感谢|请帮助回答|请给予指教|请告诉我|告诉我|请(?:问|教)|求求好心人|谁能告诉我|麻烦(?:医生|专家)?|专业人士|各位(?:专家|医生)|医生们|专家们|(?:专业)?(?:医生|大夫|专家)|帮(?:帮我|忙)|指教|回答一下|咨询一下|想(?:问|知道|了解)|了解|要知道'),
    ('generic_care_question',r'(?:(?:还|到底|究竟)?(?:能不能|可不可以|能否|可以|能|会不会|可否))?(?:治疗好|治疗|治愈|治好|治吗|治过|医治|康复)|(?:怎么|怎样|如何|咋)(?:办|治疗|治|处理|解决)|怎么办|什么办法|什么方法|用什么药|吃什么药|治疗方法|方法治疗|如何是好|什么原因|怎么回事|为什么|是否严重|严重吗|正常吗|有问题吗|好不好|好转|好像|好象|(?:吃|服|用|停)(?:药物|药)'),
    ('generic_reference',r'(?:(?:我|你|他|她|这|那|这个|那个|这种|那种|上述)(?:的)?)(?:病情|情况|问题|病(?=$|[\s，。！？!?、；;：:]|能|可|会|怎么|怎样|如何|还|要|没|未|已经))|这个结果|我说的这些|上述结果|病情|情况|问题|这种病|某种病|咨询'),
    ('history_and_filler',r'没有治疗过|没治疗过|没治过|未治疗|没有治疗|没治疗|没求过医|没有|无|不清楚|不知道|应该|该|请|是否|什么|怎么|怎样|如何|究竟|到底|现在|已经|一直|最近|目前|以后|之前|时间|一下|一点点|一点|一次|本人|患者|我们|你们|他们|我|你|他|她|它|这些|那些|这个|那个|这种|那种|这里|那里|这样|那样|的|了|吗|么|呢|啊|呀|吧|哦|过|没|未|要|还|能|可|不|是|有|在|都|就|很|和|及|与|也|又|再|才|着'),
))
QUESTION_CONTEXT_WEAK_RESIDUES = frozenset(('病','症状','药','检查报告','化验结果','检查结果','报告','结果',
    '哪里','医院','年龄','病史','知道','告诉','开始','想看看','想','希望','方法','办法','建议','意见','帮助','请教','回答','健康'))
QUESTION_DEICTIC_ONLY = re.compile(
    r'^(?=.*(?:我说的这些|上述(?:疾病|问题|情况)|这些(?:病|东西)))'
    r'(?:别人|就是|被|我|吃下去|吞下去|喝下去|会不会|能不能|感染|染上|我说的这些|上述疾病|上述问题|上述情况|这些病|这些东西|了|吗|呢|医生|大夫)+$')
QUESTION_REPORT_TERM = re.compile(r'病理|报告|检查结果|化验(?:单|结果)')
QUESTION_REPORT_REQUEST = re.compile(r'咨询|请(?:问|教|看)|帮.{0,5}看|解读|分析|(?:我|他|她|这|那).{0,15}(?:病理|报告)')
QUESTION_FAMILY_REFERENCE = re.compile(r'叔叔|阿姨|父亲|母亲|爸爸|妈妈|哥哥|姐姐|弟弟|妹妹|儿子|女儿|亲人|亲戚|家人|爱人|老婆|老公|这样的病情')
QUESTION_REPORT_SCAFFOLD = re.compile(
    r'化验结果|检查结果|检验报告|检查报告|化验报告|病理报告|病理|报告|化验单|'
    r'叔叔|阿姨|父亲|母亲|爸爸|妈妈|哥哥|姐姐|弟弟|妹妹|儿子|女儿|亲人|亲戚|家人|爱人|老婆|老公|'
    r'建议|意见|效果|药物|药|服用|了解|分析|解读|看看|看|给|开|想|希望|您|什|好|以')


def _question_context_field(text, dom_locator):
    """Mask only generic scaffolding for analysis; never edit the source question."""
    masked = text
    evidence = []
    for rule_id,pattern in QUESTION_CONTEXT_RULES:
        matches = list(pattern.finditer(masked))
        for match in matches:
            evidence.append({'rule_id':rule_id,'char_start':match.start(),'char_end':match.end(),
                             'text':text[match.start():match.end()]})
        # Equal-length masks retain offsets and line boundaries for subsequent rules.
        masked = pattern.sub(lambda m:''.join('\n' if c=='\n' else ' ' for c in m.group()),masked)
    report_without_details = False
    definition = (bool(re.search(r'什么(?:是|叫)|(?:病理|报告)(?:是)?什么',text))
                  and not QUESTION_FAMILY_REFERENCE.search(text))
    if QUESTION_REPORT_TERM.search(text) and QUESTION_REPORT_REQUEST.search(text) and not definition:
        report_matches = list(QUESTION_REPORT_SCAFFOLD.finditer(masked))
        remainder = QUESTION_REPORT_SCAFFOLD.sub(' ',masked)
        if not re.search(r'[A-Za-z\u3400-\u9fff]',remainder):
            report_without_details = True
            for match in report_matches:
                evidence.append({'rule_id':'referenced_report_without_details','char_start':match.start(),
                    'char_end':match.end(),'text':text[match.start():match.end()]})
            masked = remainder
    residuals = [{'char_start':m.start(),'char_end':m.end(),'text':text[m.start():m.end()]}
                 for m in re.finditer(r'[A-Za-z\u3400-\u9fff]+',masked)]
    residue = ''.join(item['text'] for item in residuals)
    folded = re.sub(r'[\W_\d０-９]+','',text)
    if not text.strip():
        status,reason = 'empty','empty_field'
    elif report_without_details:
        status,reason = 'unresolved','referenced_report_or_treatment_without_details'
    elif QUESTION_DEICTIC_ONLY.fullmatch(folded):
        status,reason = 'unresolved','deictic_reference_without_named_issue'
    elif not residue:
        status,reason = 'insufficient','only_generic_requests_demographics_or_time'
    elif residue in QUESTION_CONTEXT_WEAK_RESIDUES:
        status,reason = 'unresolved','unresolved_generic_topic_reference'
    else:
        status,reason = 'context_present','non_generic_content_observed'
    return {'text':text,'text_sha256':sha(text),'dom_locator':dom_locator,'status':status,
            'analysis_basis':'equal_length_generic_masks_in_ruleset_order_source_text_unchanged',
            'reason':reason,'generic_evidence':evidence,'residual_spans':residuals}


def question_context(title, body, *, title_dom_locator=None, body_dom_locator=None):
    """Bounded context screening using title/body only, with no answer inference or length cutoff."""
    title_evidence = _question_context_field(title,title_dom_locator)
    body_evidence = _question_context_field(body,body_dom_locator)
    title_present = title_evidence['status']=='context_present'
    body_present = body_evidence['status']=='context_present'
    if body_present:
        status,source,reasons = 'context_present','both' if title_present else 'body',[]
    elif title_present:
        status,source,reasons = 'title_only','title',['QUESTION_TITLE_ONLY_REVIEW']
    elif 'unresolved' in (title_evidence['status'],body_evidence['status']):
        status,source,reasons = 'unresolved','unresolved',['QUESTION_CONTEXT_UNRESOLVED_REVIEW']
    else:
        status,source,reasons = 'insufficient','unresolved',['QUESTION_CONTEXT_MISSING_REVIEW']
    return {'ruleset_version':QUESTION_CONTEXT_VERSION,'status':status,'source':source,
            'review_reasons':reasons,'title':title_evidence,'body':body_evidence,
            'scope':'title_and_normalized_question_only_not_clinical_completeness'}


def _remove_reply_boilerplate(text):
    actions = []
    for rule_id, pattern in REPLY_BOILERPLATE:
        matches = list(pattern.finditer(text))
        if not matches:
            continue
        before = text
        text = pattern.sub('', text)
        text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        actions.append({'action':'remove_reply_boilerplate', 'rule_id':rule_id,
                        'offset_basis':'clean_text_before_action',
                        'removed_spans':[{'char_start':m.start(), 'char_end':m.end(), 'text':m.group()}
                                         for m in matches],
                        'before_sha256':sha(before), 'after_sha256':sha(text)})
    return text, actions


def _finalize_reply_text(media, text):
    """Classify the remaining text, including after title-matched tail removal."""
    semantic = re.sub(r'^(?:(?:病情分析|指导意见|医生询问)\s*[：:]\s*)+', '', text).strip()
    clean = text if compact(semantic) else ''
    has_audio = media['answer_type'] in ('audio', 'mixed')
    kind = 'mixed' if has_audio and clean else 'audio' if has_audio else 'text' if clean else 'empty'
    media.update(text=clean, clean_text=clean, clean_text_sha256=sha(clean), answer_type=kind)
    return media


def classify_reply_media(node, url, *, followup=False, remove_boilerplate=True):
    from urllib.parse import urljoin
    clone = _remove_noise(node)
    if followup:
        paragraphs = [c for c in clone if isinstance(c.tag,str) and c.tag.lower() == 'p']
        wrapper = html.Element('div')
        for child in paragraphs: wrapper.append(deepcopy(child))
        clone = wrapper
    else:
        for child in list(clone.iterdescendants()):
            if _has_class(child,'b_ansaddli'): child.drop_tree()
    raw = _paragraph_text(clone)
    audio_nodes = clone.xpath('.//audio|.//source')
    urls = []
    for el in audio_nodes:
        src = el.get('src')
        if src:
            resolved = urljoin(url,src)
            if urlsplit(resolved).scheme in ('http','https') and resolved not in urls: urls.append(resolved)
    for a in clone.xpath('.//a[@href]'):
        if re.search(r'\.(?:mp3|wav|m4a|ogg)(?:[?#]|$)',a.get('href'),re.I):
            src = urljoin(url,a.get('href'))
            if src not in urls: urls.append(src)
    has_audio = bool(audio_nodes or urls)
    attachment_urls = [urljoin(url,n.get('src')) for n in clone.xpath('.//img[@src]')]
    for el in list(clone.xpath('.//audio|.//source')):
        if el.getparent() is not None: el.drop_tree()
    clean, actions = normalize_legacy_markup(_paragraph_text(clone))
    if has_audio and AUDIO_FALLBACK.search(clean):
        clean = AUDIO_FALLBACK.sub('',clean).strip()
        actions.append({'action':'remove_dom_audio_fallback','evidence':'audio/source node present'})
    if remove_boilerplate:
        clean, removed = _remove_reply_boilerplate(clean)
        actions.extend(removed)
    return _finalize_reply_text({'answer_type':'audio' if has_audio else 'text',
            'media_urls':urls,'raw_text':raw,
            'attachment_urls':attachment_urls,
            'raw_text_sha256':sha(raw),'normalization_actions':actions,
            'residual_markup':bool(LEGACY_MARKUP.search(clean) or re.search(r'&lt;/?(?:p|br|div|span)\b',clean,re.I))}, clean)


def _locator(node):
    return node.getroottree().getpath(node)


def _question_media(nodes, url):
    evidence = []
    for node in nodes:
        for element in node.xpath('.//img|.//audio|.//video|.//source'):
            attributes = {key:element.get(key) for key in ('src','data-src','data-original','poster','srcset','data-srcset')
                          if element.get(key)}
            values = [value for key,value in attributes.items() if 'srcset' not in key]
            for key,value in attributes.items():
                if 'srcset' in key:
                    values.extend(part.strip().split()[0] for part in value.split(',') if part.strip())
            urls = list(dict.fromkeys(urljoin(url,value) for value in values))
            evidence.append({'tag':element.tag, 'urls':urls, 'attributes':attributes,
                             'alt':element.get('alt'), 'dom_locator':_locator(element)})
    return evidence


def extract(body, url, content_type=''):
    if not is_question_url(url): raise ValueError('Not a 120ask question URL')
    tree, encoding, decode_warning = _tree(body, content_type)
    titles = tree.xpath('//*[@id="d_askH1"]') or tree.xpath(
        '//*[contains(concat(" ",normalize-space(@class)," ")," b_askti ")]//h1')
    questions = tree.xpath('//*[@id="d_msCon"]') or tree.xpath(
        '//*[contains(concat(" ",normalize-space(@class)," ")," b_askbox ")]'
        '//*[contains(concat(" ",normalize-space(@class)," ")," b_askcont ")]')
    title = normalize(titles[0].text_content()) if titles else ''
    question_raw = _node_text(questions[0]) if questions else ''
    question, question_provenance, question_quality = normalize_question(
        questions[0] if questions else None,node_count=len(questions))
    context = question_context(title,question,title_dom_locator=_locator(titles[0]) if titles else None,
                               body_dom_locator=question_provenance['dom_locator'])
    question_valid = len(questions) == 1 and bool(compact(question))
    question_media = _question_media(questions, url)
    boxes = tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," b_answerbox ")]')
    boxes = [b for b in boxes if not any(_has_class(p,'b_answerbox') for p in b.iterancestors())]
    cards, all_followups = [], []
    for box in boxes:
        cards.extend(n for n in box.iterdescendants() if _has_class(n,'b_answerli')
                     and not any(_has_class(p,'b_answerli') for p in n.iterancestors()))
        all_followups.extend(n for n in box.iterdescendants() if _has_class(n,'b_ansaddli'))
    threads, unresolved, card_evidence = [], [], []
    main_regions = empty_regions = removed_tails = unrecognized = attached = 0
    represented_followups = set()
    for card_index, card in enumerate(cards,1):
        blocks = _owned_blocks(card)
        main = [n for n in blocks if _role(n) == 'responder_answer']
        if not main: continue
        card_path = _locator(card)
        card_author = _card_author(card, url)
        card_threads = []
        node_to_thread = {}
        for block in main:
            main_regions += 1
            reply_nodes = [n for n in block.iter() if (n.get('id') or '').startswith('reply')]
            reply_nodes = [n for n in reply_nodes if not any(
                p in reply_nodes for p in n.iterancestors())]
            # Keep each source reply distinct, including p[id^=reply] audio replies.
            for core in reply_nodes or [block]:
                media = classify_reply_media(core,url)
                text = media['text']
                cleaned, tail = _remove_tail(text,title)
                _finalize_reply_text(media, cleaned)
                removed_tails += int(tail)
                if tail: media['normalization_actions'].append({'action':'remove_title_matched_doctor_tail'})
                if media['answer_type'] == 'empty': empty_regions += 1
                index = len(threads)+1
                reply_id = core.get('id') if (core.get('id') or '').startswith('reply') else None
                t = {'index':index,'thread_id':f'card{card_index}:{reply_id or _locator(core)}',
                     'card_index':card_index,'card_id':card.get('id'),'card_locator':card_path,
                     'reply_id':reply_id,**author_snapshot(card_author),'card_author':deepcopy(card_author),
                     'ownership_status':'resolved',
                     'parser_flags':[],'turns':[]}
                turn = dict(media,role='responder_answer',turn_kind='answer',speaker_role='responder',turn_index=1,reply_id=reply_id,
                            card_index=card_index,dom_locator=_locator(core),source_block_locator=_locator(block))
                t['turns'].append(turn)
                threads.append(t);card_threads.append(t);node_to_thread.setdefault(block,[]).append(t)
        if len(card_threads)>1:
            for t in card_threads:
                t.update(_empty_author('unresolved_per_reply', scope='card', card_dom_locator=card_path))
                t['parser_flags'].append('REPLY_AUTHOR_REVIEW')
        for t in card_threads:
            t['turns'][0].update(author_snapshot(t))
        for block in [b for b in blocks if _role(b) != 'responder_answer']:
            represented_followups.add(_locator(block))
            role = _role(block)
            media = classify_reply_media(block,url,followup=True,remove_boilerplate=role=='responder_followup')
            if not media['raw_text']:
                if normalize(_remove_noise(block).text_content()): unrecognized += 1
                unresolved.append({'dom_locator':_locator(block),'reason':'UNRECOGNIZED_FOLLOWUP_STRUCTURE'})
                continue
            # Single reply in card proves ownership. For multiple replies require a common
            # b_anscontc ancestor containing exactly one of their main source blocks.
            owner = card_threads[0] if len(card_threads)==1 else None
            if owner is None:
                for parent in block.iterancestors():
                    if parent is card: break
                    eligible = [t for b,ts in node_to_thread.items() if parent in b.iterancestors() for t in ts]
                    if len(eligible)==1: owner=eligible[0]; break
            if owner is None:
                unresolved.append({'dom_locator':_locator(block),'reason':'UNRESOLVED_FOLLOWUP_OWNERSHIP',
                                   'role':role,**media})
                for t in card_threads: t['parser_flags'].append('UNRESOLVED_OWNERSHIP')
                continue
            cleaned, tail = _remove_tail(media['text'],title) if role=='responder_followup' else (media['text'],False)
            removed_tails += int(tail)
            _finalize_reply_text(media, cleaned)
            if tail: media['normalization_actions'].append({'action':'remove_title_matched_doctor_tail'})
            owner['turns'].append(dict(media,role=role,turn_kind='followup',
                speaker_role='responder' if role=='responder_followup' else 'patient' if role=='patient_followup' else 'unknown',
                **_followup_author(owner,block,role),turn_index=len(owner['turns'])+1,
                reply_id=owner['reply_id'],card_index=card_index,dom_locator=_locator(block),
                source_block_locator=_locator(block)))
            attached += 1
            if role=='unknown_followup': owner['parser_flags'].append('UNKNOWN_FOLLOWUP_ROLE')
        card_evidence.append({'card_index':card_index,'card_id':card.get('id'),'dom_locator':card_path,
                              'main_blocks':len(main),'reply_ids':[t['reply_id'] for t in card_threads],
                              'card_author':card_author})
    for block in all_followups:
        if _locator(block) not in represented_followups:
            unresolved.append({'dom_locator':_locator(block),'reason':'ORPHAN_FOLLOWUP'})
    published = _published_reply_count(tree)
    card_count = len(card_evidence)
    semantics = ('card_count_matches_template' if published is not None and published==card_count
                 else 'unresolved' if published is not None else 'not_available')
    # Detect repeats separately by role. Equal text in different replies is not DOM duplication.
    repeats = []
    for role, label in (('responder_answer','duplicate_main_answer'),('patient_followup','repeated_patient_followup'),
                        ('responder_followup','repeated_responder_followup')):
        values = {}
        for t in threads:
            for turn in t['turns']:
                if turn['role']==role and turn['text']:
                    values.setdefault(compact(turn['text']),[]).append({'thread_id':t['thread_id'],
                        'reply_id':turn['reply_id'],'dom_locator':turn['dom_locator'],
                        'raw_text_sha256':turn['raw_text_sha256']})
        for text, locations in values.items():
            if len(locations)>1:
                same_reply=(role=='responder_answer' and len({x['reply_id'] for x in locations})==1
                            and bool(locations[0]['reply_id'])
                            and len({x['raw_text_sha256'] for x in locations})==1)
                kind='duplicate_dom_representation' if same_reply else label
                repeats.append({'kind':kind,'text_sha256':sha(text),'locations':locations,
                                'action':'preserved_for_review'})
                if role=='responder_answer':
                    for t in threads:
                        if any(x['thread_id']==t['thread_id'] for x in locations):
                            t['parser_flags'].append('DUPLICATE_DOM_REPRESENTATION_REVIEW' if same_reply
                                                     else 'DUPLICATE_MAIN_ANSWER_REVIEW')
    for thread in threads:
        for turn in thread['turns']:
            if turn['speaker_role'] == 'responder':
                thread['parser_flags'].extend(author_review_reasons(turn))
    main_turns = [t['turns'][0] for t in threads]
    text_answers = [t['text'] for t in main_turns if t['text']]
    all_turns = [turn for t in threads for turn in t['turns']]
    def formatted(raw=False):
        parts = [title,'问题：\n'+(question_raw if raw else question)]
        for t in threads:
            for turn in t['turns']:
                value = turn['raw_text'] if raw else turn['text']
                if not value: continue
                parts.append(render_turn(t,turn,value))
        return '\n\n'.join(p for p in parts if p.strip())
    text, rawtext = formatted(),formatted(True)
    challenge = bool(re.search(r'just a moment|checking your browser|verify you are human|安全验证|访问受限',
        ' '.join(tree.xpath('//title/text()'))+' '+text[:2000],re.I))
    reasons = []
    if len(titles)!=1 or not title: reasons.append('ask120_missing_or_ambiguous_title')
    if not question_valid: reasons.append('ask120_missing_or_ambiguous_question')
    if question_media: reasons.append('ask120_question_media_review')
    reasons.extend(question_quality['review_reasons'])
    reasons.extend(context['review_reasons'])
    if not text_answers: reasons.append('ask120_no_main_answer')
    if semantics=='unresolved': reasons.append('PUBLISHED_COUNT_SEMANTICS_REVIEW')
    if unresolved: reasons.append('ask120_unresolved_followups')
    if any(u['reason']=='ORPHAN_FOLLOWUP' for u in unresolved): reasons.append('ask120_orphan_followup')
    if unrecognized: reasons.append('ask120_unrecognized_followup_structure')
    if any(t['role']=='unknown_followup' for t in all_turns): reasons.append('ask120_unknown_followup_role')
    if any(t['answer_type']=='audio' for t in main_turns): reasons.append('ask120_audio_reply_present')
    if any(t['residual_markup'] for t in all_turns): reasons.append('ask120_residual_markup')
    if question_quality['ui_matches'] or any(marker in turn['text'] for turn in all_turns for marker in UI_MARKERS):
        reasons.append('ask120_ui_marker_suspect')
    if decode_warning or '\ufffd' in text: reasons.append('ask120_decode_suspect')
    if challenge: reasons.append('error_or_challenge')
    for t in threads:
        t['parser_flags'] = sorted(set(t['parser_flags']))
        t['ownership_status'] = 'unresolved' if 'UNRESOLVED_OWNERSHIP' in t['parser_flags'] else 'resolved'
        reasons.extend(t['parser_flags'])
    counters = {
        'source_reply_blocks':main_regions,'source_card_count':card_count,'source_reply_count':len(main_turns),
        'text_main_answers':sum(t['answer_type']=='text' for t in main_turns),
        'audio_main_answers':sum(t['answer_type']=='audio' for t in main_turns),
        'mixed_main_answers':sum(t['answer_type']=='mixed' for t in main_turns),
        'usable_text_main_answers':len(text_answers)}
    qc = {'scope':'observable_html_only',**counters,'source_main_answer_regions':main_regions,
          'extracted_main_answers':len(text_answers),'published_reply_count':published,
          'published_reply_difference':None if published is None else card_count-published,
          'published_count_semantics':semantics,'card_evidence':card_evidence,
          'source_followup_blocks':len(all_followups),'source_followups_with_direct_p_text':attached+len(unresolved),
          'attached_followups':attached,'unrecognized_followup_blocks':unrecognized,
          'orphan_followups':sum(u['reason']=='ORPHAN_FOLLOWUP' for u in unresolved),
          'unknown_followup_roles':sum(t['role']=='unknown_followup' for t in all_turns),
          'empty_main_answer_regions':empty_regions,'removed_template_tails':removed_tails,
          'duplicate_turn_groups':len(repeats),'duplicates_by_role':repeats,
          'duplicate_dom_representation':[g for g in repeats if g['kind']=='duplicate_dom_representation'],
          'unresolved_blocks':unresolved,
          'question_node_count':len(questions),'title_node_count':len(titles),
          'question_content_excerpt':question[:300],
          'question_qc':question_quality,
          'question_context_status':context['status'],'question_context_source':context['source'],
          'ui_markers_in_text':[m for m in UI_MARKERS if m in text]}
    return {'title':title,'text':text,'extractor':EXTRACTOR, 'published_at':_publication_date(tree),
        'question_asked_at':_publication_date(tree),'declared_encoding':encoding,'decode_warning':decode_warning,
        'source_question_chars':len(question),'source_answer_count':len(text_answers),
        'source_body_chars':sum(len(a) for a in text_answers),'source_followup_count':len(all_followups),
        'main_answer_count':len(text_answers),'followup_count':attached,
        'patient_followups':sum(t['role']=='patient_followup' for t in all_turns),
        'responder_followups':sum(t['role']=='responder_followup' for t in all_turns),
        'unknown_roles':qc['unknown_followup_roles'],'removed_template_tails':removed_tails,
        'ask120_question':question,'ask120_question_raw':question_raw,'question_valid':question_valid,
        'question_provenance':question_provenance,'question_qc':question_quality,
        'question_context':context,'question_context_status':context['status'],'question_context_source':context['source'],
        'question_media':question_media,
        'question_attachment_urls':list(dict.fromkeys(u for item in question_media for u in item['urls'])),
        'ask120_main_answers':text_answers,'ask120_threads':threads,'ask120_qc':qc,
        'ask120_text_raw':rawtext,'ask120_text_raw_sha256':sha(rawtext),
        'ask120_review_reasons':sorted(set(reasons)),
        'ask120_access_pass':bool(question_valid and text_answers and not reasons),
        'ask120_challenge_detected':challenge,'ask120_parser_version':VERSION,
        'raw_response_sha256':sha(body),**counters,
        'extraction_selectors':['#d_askH1 / .b_askti h1','#d_msCon / .b_askbox .b_askcont',
                                '.b_answerbox .b_answerli (reply/card-owned DOM turns)']}


def audit(body, url, record, content_type=''):
    doc = extract(body,url,content_type)
    fields = ('title','text','extractor','published_at','ask120_question','ask120_threads','ask120_qc',
              'ask120_text_raw','ask120_text_raw_sha256','ask120_review_reasons','ask120_parser_version',
              'source_reply_blocks','text_main_answers','audio_main_answers','mixed_main_answers',
              'usable_text_main_answers','question_media','question_attachment_urls',
              'ask120_question_raw','question_provenance','question_qc',
              'question_context','question_context_status','question_context_source')
    mismatches = [k for k in fields if record.get(k)!=doc.get(k)]
    if mismatches: raise ValueError('120ask raw/checkpoint mismatch: '+', '.join(mismatches))
    qc=doc['ask120_qc']
    return {'ask120_raw_reextraction_verified':True,'ask120_main_answers_verified':doc['main_answer_count'],
            'ask120_followups_verified':doc['followup_count'],'ask120_orphan_followups':qc['orphan_followups'],
            'ask120_unknown_followup_roles':qc['unknown_followup_roles'],'ask120_qc_scope':qc['scope']}
