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


VERSION = '120ask-parser-v3.1'
EXTRACTOR = '120ask_qa_dom_v3'
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



LEGACY_MARKUP = re.compile(r'</?(?:p|br|div|span)\b[^<>]*>', re.I)
AUDIO_FALLBACK = re.compile(r'您的浏览器不支持\s*audio\s*元素[。.]?|your browser does not support.*?audio[.]?', re.I)
QUESTION_LABELS = re.compile(r'健康咨询描述\s*[：:]|曾经的治疗情况和效果\s*[：:]|想得到怎样的帮助\s*[：:]')


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


def classify_reply_media(node, url, *, followup=False):
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
    # Source labels alone are not an answer.
    semantic = re.sub(r'^(?:(?:病情分析|指导意见|医生询问)\s*[：:]\s*)+', '',clean).strip()
    if not compact(semantic): clean = ''
    kind = 'mixed' if has_audio and clean else 'audio' if has_audio else 'text' if clean else 'empty'
    return {'answer_type':kind,'media_urls':urls,'raw_text':raw,'clean_text':clean,'text':clean,
            'attachment_urls':attachment_urls,
            'raw_text_sha256':sha(raw),'clean_text_sha256':sha(clean),'normalization_actions':actions,
            'residual_markup':bool(LEGACY_MARKUP.search(clean) or re.search(r'&lt;/?(?:p|br|div|span)\b',clean,re.I))}


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
    question = QUESTION_LABELS.sub('',question_raw).strip()
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
        main = [n for n in blocks if _role(n) == 'doctor_answer']
        if not main: continue
        card_path = _locator(card)
        names = card.xpath('.//*[contains(concat(" ",normalize-space(@class)," ")," b_answertl ")]'
                          '//*[contains(concat(" ",normalize-space(@class)," ")," b_sp1 ")]/*[self::a or self::var]')
        card_doctor = normalize(names[0].text_content()) if len(names)==1 else None
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
                media.update(text=cleaned,clean_text=cleaned,clean_text_sha256=sha(cleaned))
                removed_tails += int(tail)
                if tail: media['normalization_actions'].append({'action':'remove_title_matched_doctor_tail'})
                if media['answer_type'] == 'empty': empty_regions += 1
                index = len(threads)+1
                reply_id = core.get('id') if (core.get('id') or '').startswith('reply') else None
                # Card-level doctor identity is safe only for one reply in the card.
                t = {'index':index,'thread_id':f'card{card_index}:{reply_id or _locator(core)}',
                     'card_index':card_index,'card_id':card.get('id'),'card_locator':card_path,
                     'reply_id':reply_id,'doctor':card_doctor,'card_doctor':card_doctor,
                     'doctor_identity_scope':'card','ownership_status':'resolved',
                     'parser_flags':[],'turns':[]}
                turn = dict(media,role='doctor_answer',turn_index=1,reply_id=reply_id,
                            card_index=card_index,dom_locator=_locator(core),source_block_locator=_locator(block))
                t['turns'].append(turn)
                threads.append(t);card_threads.append(t);node_to_thread.setdefault(block,[]).append(t)
        if len(card_threads)>1:
            for t in card_threads:
                t.update(doctor=None,doctor_identity_scope='unresolved_per_reply')
                t['parser_flags'].append('REPLY_AUTHOR_REVIEW')
        for block in [b for b in blocks if _role(b) != 'doctor_answer']:
            represented_followups.add(_locator(block))
            role = _role(block)
            media = classify_reply_media(block,url,followup=True)
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
            cleaned, tail = _remove_tail(media['text'],title) if role=='doctor_followup' else (media['text'],False)
            removed_tails += int(tail)
            media.update(text=cleaned,clean_text=cleaned,clean_text_sha256=sha(cleaned))
            if tail: media['normalization_actions'].append({'action':'remove_title_matched_doctor_tail'})
            owner['turns'].append(dict(media,role=role,turn_index=len(owner['turns'])+1,
                reply_id=owner['reply_id'],card_index=card_index,dom_locator=_locator(block),
                source_block_locator=_locator(block)))
            attached += 1
            if role=='unknown_followup': owner['parser_flags'].append('UNKNOWN_FOLLOWUP_ROLE')
        card_evidence.append({'card_index':card_index,'card_id':card.get('id'),'dom_locator':card_path,
                              'main_blocks':len(main),'reply_ids':[t['reply_id'] for t in card_threads],
                              'card_doctor':card_doctor})
    for block in all_followups:
        if _locator(block) not in represented_followups:
            unresolved.append({'dom_locator':_locator(block),'reason':'ORPHAN_FOLLOWUP'})
    published = _published_reply_count(tree)
    card_count = len(card_evidence)
    semantics = ('card_count_matches_template' if published is not None and published==card_count
                 else 'unresolved' if published is not None else 'not_available')
    # Detect repeats separately by role. Equal text in different replies is not DOM duplication.
    repeats = []
    for role, label in (('doctor_answer','duplicate_main_answer'),('patient_followup','repeated_patient_followup'),
                        ('doctor_followup','repeated_doctor_followup')):
        values = {}
        for t in threads:
            for turn in t['turns']:
                if turn['role']==role and turn['text']:
                    values.setdefault(compact(turn['text']),[]).append({'thread_id':t['thread_id'],
                        'reply_id':turn['reply_id'],'dom_locator':turn['dom_locator'],
                        'raw_text_sha256':turn['raw_text_sha256']})
        for text, locations in values.items():
            if len(locations)>1:
                same_reply=(role=='doctor_answer' and len({x['reply_id'] for x in locations})==1
                            and bool(locations[0]['reply_id'])
                            and len({x['raw_text_sha256'] for x in locations})==1)
                kind='duplicate_dom_representation' if same_reply else label
                repeats.append({'kind':kind,'text_sha256':sha(text),'locations':locations,
                                'action':'preserved_for_review'})
                if role=='doctor_answer':
                    for t in threads:
                        if any(x['thread_id']==t['thread_id'] for x in locations):
                            t['parser_flags'].append('DUPLICATE_DOM_REPRESENTATION_REVIEW' if same_reply
                                                     else 'DUPLICATE_MAIN_ANSWER_REVIEW')
    main_turns = [t['turns'][0] for t in threads]
    text_answers = [t['text'] for t in main_turns if t['text']]
    all_turns = [turn for t in threads for turn in t['turns']]
    def formatted(raw=False):
        parts = [title,'问题：\n'+(question_raw if raw else question)]
        for t in threads:
            for turn in t['turns']:
                value = turn['raw_text'] if raw else turn['text']
                if not value: continue
                name = f"（{t['doctor']}）" if t['doctor'] and turn['role']!='patient_followup' else ''
                parts.append(f"{LABELS[turn['role']]} {t['index']}{name}：\n{value}")
        return '\n\n'.join(p for p in parts if p.strip())
    text, rawtext = formatted(),formatted(True)
    challenge = bool(re.search(r'just a moment|checking your browser|verify you are human|安全验证|访问受限',
        ' '.join(tree.xpath('//title/text()'))+' '+text[:2000],re.I))
    reasons = []
    if len(titles)!=1 or not title: reasons.append('ask120_missing_or_ambiguous_title')
    if not question_valid: reasons.append('ask120_missing_or_ambiguous_question')
    if question_media: reasons.append('ask120_question_media_review')
    if not text_answers: reasons.append('ask120_no_main_answer')
    if semantics=='unresolved': reasons.append('PUBLISHED_COUNT_SEMANTICS_REVIEW')
    if unresolved: reasons.append('ask120_unresolved_followups')
    if any(u['reason']=='ORPHAN_FOLLOWUP' for u in unresolved): reasons.append('ask120_orphan_followup')
    if unrecognized: reasons.append('ask120_unrecognized_followup_structure')
    if any(t['role']=='unknown_followup' for t in all_turns): reasons.append('ask120_unknown_followup_role')
    if any(t['answer_type']=='audio' for t in main_turns): reasons.append('ask120_audio_reply_present')
    if any(t['residual_markup'] for t in all_turns): reasons.append('ask120_residual_markup')
    if any(marker in text for marker in UI_MARKERS): reasons.append('ask120_ui_marker_suspect')
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
          'ui_markers_in_text':[m for m in UI_MARKERS if m in text]}
    return {'title':title,'text':text,'extractor':EXTRACTOR, 'published_at':_publication_date(tree),
        'question_asked_at':_publication_date(tree),'declared_encoding':encoding,'decode_warning':decode_warning,
        'source_question_chars':len(question),'source_answer_count':len(text_answers),
        'source_body_chars':sum(len(a) for a in text_answers),'source_followup_count':len(all_followups),
        'main_answer_count':len(text_answers),'followup_count':attached,
        'patient_followups':sum(t['role']=='patient_followup' for t in all_turns),
        'doctor_followups':sum(t['role']=='doctor_followup' for t in all_turns),
        'unknown_roles':qc['unknown_followup_roles'],'removed_template_tails':removed_tails,
        'ask120_question':question,'ask120_question_raw':question_raw,'question_valid':question_valid,
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
              'usable_text_main_answers','question_media','question_attachment_urls')
    mismatches = [k for k in fields if record.get(k)!=doc.get(k)]
    if mismatches: raise ValueError('120ask raw/checkpoint mismatch: '+', '.join(mismatches))
    qc=doc['ask120_qc']
    return {'ask120_raw_reextraction_verified':True,'ask120_main_answers_verified':doc['main_answer_count'],
            'ask120_followups_verified':doc['followup_count'],'ask120_orphan_followups':qc['orphan_followups'],
            'ask120_unknown_followup_roles':qc['unknown_followup_roles'],'ask120_qc_scope':qc['scope']}
