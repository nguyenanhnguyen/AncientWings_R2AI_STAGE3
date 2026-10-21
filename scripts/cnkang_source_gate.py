"""Deterministic source evidence; report-only until independent label validation.

KEEP means a policy candidate, not verified clinical accuracy. No network, text
rewriting or learned thresholds. All spans refer to the unmodified article text.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

VERSION = 'cnkang-source-1'
POLICY_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
DEFAULT_MODE = 'report_only'
FIELDS = ('source_policy_version', 'source_policy_sha256', 'source_input_sha256',
          'source_type', 'source_signals', 'source_decision', 'source_reason_codes',
          'title_body_alignment', 'short_text_assessment')
LEGACY_FLAGS = {'AUTHOR_UNAVAILABLE_REVIEW', 'TITLE_BODY_ALIGNMENT_REVIEW',
                'PROMOTIONAL_CLAIM_REVIEW', 'PERSONAL_EXPERIENCE_REVIEW'}
CLAIM = re.compile(r'根治|包治(?:百病)?|(?:无|没有)副作用|百分之百|100\s*[%％]|永不[复復]发|保证(?:治愈|有效)')
CTA = re.compile(r'立即(?:购买|订购)|购买本品|咨询(?:平台|热线|电话)|拨打|加[微Vv]信|微信[：:]|订购|咨询中心了解')
PERSONAL = re.compile(r'亲身经历|我的经历|我(?:以前|曾经|自己|用过|服用|儿子|孩子|家|妈妈)|我带了|我听我的朋友')
PATIENT = re.compile(r'^\s*(?:患者|网友|读者|问)[：:]')
STOP = re.compile(r'请问|不知道|会不会|是不是|有没有|怎么样|怎么办|怎么|怎样|如何|为什么|什么|哪些|是否|需要|应该|可以|一下|我的|孩子|宝宝|形成|引起|症状|原因|方法|治疗|[的是了呢吗啊呀？?\s，,。！!：:]')
INTENTS = {
    'cause': (r'原因|形成|为什么|引起', r'原因|引起|导致|有关|因素|由于|感染|过敏'),
    'therapy': (r'治疗|怎么办|如何.*治|怎样.*治', r'治疗|建议|手术|药物|护理|处理|应当'),
    'symptoms': (r'症状|表现', r'症状|表现|出现|发病|可见'),
    'prevention': (r'预防|防止', r'预防|避免|注意|防止|接种'),
}


def digest(value):
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def compact(text):
    return re.sub(r'\s+', '', text or '')


def metadata_roles(tree, body, metadata_nodes, *, trusted):
    """Explicit labels only; a speaker in the body never becomes article author."""
    result, seen = [], set()

    def add(name, role, node, quote, method, *, institution=None, title=None):
        name = name.strip(' ：:，,。;；')
        if not name or len(name) > 80 or name in ('中华康网', '本站', '佚名', '未知'):
            return
        path = node.getroottree().getpath(node)
        identity = (name, role, path)
        if identity not in seen:
            seen.add(identity)
            result.append({'name': name, 'role': role, 'path': path, 'quote': quote[:200],
                           'method': method, 'confidence': 'explicit_source_label',
                           'institution': institution, 'professional_title': title})

    for node in tree.xpath('//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="author"]'):
        for name in re.split(r'[、;；]', node.get('content') or ''):
            add(name, 'article_author', node, node.get('content') or '', 'meta_author')
    if not trusted:
        return result
    for node in metadata_nodes:
        if any(n.tag in ('aside','nav') or re.search(r'(?:sidebar|related|doctor-card|navigation)', n.get('class') or '')
               for n in [node,*node.iterancestors()] if isinstance(n.tag,str)):
            continue
        text = '\n'.join(t.strip() for t in node.itertext() if t.strip())
        for match in re.finditer(r'(作者|撰文|审核|审稿|责任编辑|编辑)\s*[：:]\s*([^\n|：:]{2,50})', text):
            role = 'article_author' if match[1] in ('作者', '撰文') else 'reviewer' if match[1] in ('审核', '审稿') else 'editor'
            name = re.split(r'\s+(?:来源|时间|发布|审核|编辑)|[，,;；]', match[2])[0].strip()
            add(name, role, node, match[0], 'scoped_byline')
    # Only paragraph-leading labels with a colon, after a demonstrable Q&A turn.
    paragraphs = list(body.iter('p')) or [body]
    qa_seen = False
    for node in paragraphs:
        text = ''.join(node.itertext()).strip()
        if PATIENT.match(text) or re.match(r'^\s*[\d×]+的读者[：:]', text):
            qa_seen = True
            continue
        label = re.match(r'^\s*([^：:\n。！？!?]{2,70})[：:]', text)
        if not label:
            continue
        speaker = label[1]
        # A quote in narrative or an arbitrary heading is not an attribution.
        if not qa_seen or speaker in ('答', '建议', '专家介绍', '提示', '注意'):
            continue
        medical = re.search(r'(主任医师|主治医师|副主任医师|医师|医生|科|医院)([\u3400-\u9fff]{2,4})$', speaker)
        bare = re.fullmatch(r'[\u3400-\u9fff]{2,3}', speaker)
        if medical or bare:
            hospital = re.match(r'(.+?(?:医院|附院|中心))', speaker)
            job = re.search(r'副主任医师|主任医师|主治医师|医师|医生', speaker)
            quoted = any(n.tag in ('blockquote','q') for n in node.iterancestors())
            add(medical[2] if medical else speaker, 'quoted_person' if quoted else 'respondent', node, label[0], 'quoted_label' if quoted else 'qa_turn_label',
                institution=hospital[1] if hospital else None, title=job[0] if job else None)
    return result


def alignment(heading, text):
    if not heading.strip():
        return {'state': 'missing_heading', 'coverage': 0.0, 'terms': [], 'matched': [], 'intents': []}
    parts = re.findall(r'[\u3400-\u9fff]+|[A-Za-z][A-Za-z0-9-]+', STOP.sub(' ', heading))
    terms = sorted({word.lower() for p in parts for word in
                    ([p] if re.match('[A-Za-z]', p) or len(p) <= 2 else [p[i:i+2] for i in range(len(p)-1)])
                    if len(word) >= 2})
    target = compact(text).lower()
    matched = [term for term in terms if term in target]
    intents = [{'name': name, 'supported': bool(re.search(body, text))}
               for name, (title, body) in INTENTS.items() if re.search(title, heading)]
    coverage = len(matched) / max(1, len(terms))
    if not terms:
        state = 'insufficient_title_terms'
    elif coverage >= .5 and all(i['supported'] for i in intents):
        state = 'related_lexical'
    elif matched:
        state = 'topic_only' if any(not i['supported'] for i in intents) else 'uncertain'
    else:
        state = 'mismatch_candidate'
    return {'state': state, 'coverage': round(coverage, 4), 'terms': terms, 'matched': matched,
            'intents': intents, 'rule': 'char_bigram_coverage_0.5_report_only',
            'calibration': 'fixture_only_not_independent', 'heading': heading}


def context_signals(doc):
    signals, offset, speaker, page = [], 0, 'article_voice', 1
    paragraphs = doc.get('qc_structure', {}).get('paragraphs', [])
    for number, line in enumerate(doc.get('text', '').splitlines(), 1):
        location = paragraphs[number-1] if number <= len(paragraphs) else {}
        page = location.get('article_page', 1)
        if PATIENT.match(line):
            speaker = 'patient_or_questioner'
        elif any(a['role']=='quoted_person' and a['name'] in line.split('：')[0].split(':')[0]
                 for a in doc.get('attributions',[])):
            speaker = 'quoted_person'
        elif re.match(r'^\s*答[：:]', line) or any(
                a['role'] == 'respondent' and a['name'] in line.split('：')[0].split(':')[0]
                for a in doc.get('attributions', [])):
            speaker = 'respondent'
        for match in CLAIM.finditer(line):
            before, after = line[:match.start()], line[match.end():]
            # Negation cannot cross punctuation into a different clause.
            clause = re.split(r'[，,。；;！？!?]', before)[-1][-40:]
            surrounding = line[max(0, match.start()-60):match.end()+90]
            if match[0] == '根治' and before.endswith('葛'):
                kind, stance = 'herb_name_boundary', 'not_a_claim'
            elif match[0] == '根治' and (after.startswith('性') or re.search(r'^.{0,8}手术', after)):
                kind, stance = 'procedure_term', 'not_a_claim'
            elif match[0] == '根治' and re.match(r'^[^。；，！？]{1,12}后', after):
                kind, stance = 'treatment_outcome_description', 'descriptive'
            elif re.search(r'(?:不(?:能|可|会|可以)?|无法|难以|很难|不能保证|不保证|并非|未能).{0,8}$', clause):
                kind, stance = 'treatment_claim', 'negated'
            elif re.match(r'[^。；！？]{0,18}(?:的广告|的说法|这种宣传).{0,12}(?:不可信|错误|虚假|不能相信)', after):
                kind, stance = 'treatment_claim', 'rebutted'
            elif (speaker == 'quoted_person' or re.search(r'/(?:blockquote|q)(?:\[\d+\])?(?:/|$)',location.get('path') or '')
                  or re.search(r'声称|宣称',before[-40:]) or re.search(r'[「“"\x27][^」”"\x27]*$', before)):
                kind = 'quoted_claim'
                if re.search(r'不可信|不能相信|反对|错误|误导|虚假|并不可信|不应相信|不要(?:立即)?购买', after[:100]):
                    stance = 'quoted_rebutted'
                elif re.search(r'赞同|认同|确实如此|说得对', after[:100]):
                    stance = 'quoted_endorsed'
                else:
                    stance = 'quoted_uncertain'
            elif speaker == 'patient_or_questioner' or re.search(r'(?:能否|是否|有无|可以吗).{0,8}$', clause) or re.search(r'[？?]', after[:15]):
                kind, stance = 'patient_question', 'question'
            elif re.search(r'部分患者|有些患者|可能|通常|只有|才能|可以达到', clause):
                kind, stance = 'conditional_treatment_description', 'conditional'
            elif re.search(r'100\s*[%％]', match[0]) and not re.match(r'\s*(?:治愈|有效|成功|安全)', after):
                kind, stance = 'percentage_without_treatment_claim', 'uncertain'
            else:
                kind, stance = 'absolute_treatment_claim', 'asserted'
            signals.append({'code': 'CLAIM_CONTEXT', 'kind': kind, 'stance': stance,
                            'speaker': speaker, 'article_page': page, 'paragraph': number,
                            'path': location.get('path'), 'span': [offset+match.start(), offset+match.end()],
                            'quote': match[0], 'context': surrounding})
        for code, pattern in [('COMMERCIAL_CTA', CTA), ('PERSONAL_NARRATIVE', PERSONAL)]:
            for match in pattern.finditer(line):
                prefix=re.split(r'[，,。；;！？!?]',line[:match.start()])[-1][-15:]
                stance=('negated' if re.search(r'不要|不应|禁止|拒绝|不建议|不推荐|不能|不必|勿|别',prefix)
                        else 'question' if speaker=='patient_or_questioner' else 'asserted')
                signals.append({'code': code, 'kind': 'question_context' if speaker == 'patient_or_questioner' else 'source_narrative',
                                'stance':stance,
                                'speaker': speaker, 'article_page': page, 'paragraph': number,
                                'path': location.get('path'), 'span': [offset+match.start(), offset+match.end()],
                                'quote': match[0], 'context': line[max(0,match.start()-35):match.end()+80]})
        offset += len(line)+1
    return signals


def evaluate(doc):
    text = doc.get('text', '')
    attrs = doc.get('attributions', [])
    flags = set(doc.get('source_flags', [])) - LEGACY_FLAGS
    signals = context_signals(doc)
    reasons, types = [], []
    title_match = alignment(doc.get('heading_title', ''), text)
    if not any(a['role'] == 'article_author' for a in attrs):
        flags.add('AUTHOR_UNAVAILABLE_REVIEW')  # informational, never a lone hard veto
    if title_match['state'] != 'related_lexical':
        flags.add('TITLE_BODY_ALIGNMENT_REVIEW')
        reasons.append('TITLE_BODY_' + title_match['state'].upper())
    qa = bool(any(a['role'] == 'respondent' for a in attrs) or
              re.search(r'(?m)^\s*(?:患者|网友|读者|问|答)[：:]', text))
    if qa:
        types.append('qa')
        if not (any(a['role'] == 'respondent' for a in attrs) or re.search(r'(?m)^\s*答[：:]',text)):
            reasons.append('QA_ANSWER_UNVERIFIED_REVIEW')
    asserted = [s for s in signals if s['code']=='CLAIM_CONTEXT' and s.get('stance') in ('asserted', 'quoted_endorsed', 'quoted_uncertain', 'uncertain')
                and s.get('kind') != 'percentage_without_treatment_claim']
    if asserted:
        flags.add('PROMOTIONAL_CLAIM_REVIEW')
        reasons.append('TREATMENT_CLAIM_REQUIRES_REVIEW')
    ctas = [s for s in signals if s['code'] == 'COMMERCIAL_CTA' and s.get('stance')=='asserted']
    personal = [s for s in signals if s['code'] == 'PERSONAL_NARRATIVE' and s['speaker'] != 'patient_or_questioner']
    if personal:
        types.append('experience')
        flags.add('PERSONAL_EXPERIENCE_REVIEW')
        reasons.append('PERSONAL_NARRATIVE_REVIEW')
    if ctas:
        types.append('promotional_candidate')
        reasons.append('COMMERCIAL_CTA_REVIEW')
    if 'CONTEXTUAL_REPETITION_REVIEW' in flags:
        reasons.append('CONTEXTUAL_REPETITION_REVIEW')
    # Known source contamination is diagnosed, never removed or padded here.
    if re.search(r'搜狗\(www\.sogou\.com\)搜索|共找到\s*[\d,]+\s*个相关网页', text):
        flags.add('SOURCE_UI_CONTAMINATION_REVIEW')
        reasons.append('SOURCE_UI_CONTAMINATION_REVIEW')
    size = len(compact(text))
    if doc.get('article_complete') is False:
        short_state = 'article_incomplete'
    elif size >= 200:
        short_state = 'not_short'
    elif qa and re.search(r'(?m)^\s*(?:患者|网友|问)[：:]', text) and not (
            any(a['role'] == 'respondent' for a in attrs) or re.search(r'(?m)^\s*答[：:]', text)):
        short_state = 'question_only_or_unattributed_answer'
    elif size < 50:
        short_state = 'very_short_context_required'
    else:
        short_state = 'short_source_requires_review'
    short = {'state': short_state, 'compact_chars': size, 'threshold': 200,
             'body_selector': doc.get('selector'), 'body_template': doc.get('template'),
             'body_text_sha256': doc.get('text_sha256'), 'article_complete': doc.get('article_complete'),
             'evidence_status': 'source_dom_verified' if doc.get('template') not in ('unknown',None) else 'unverified',
             'clinical_label': 'not_adjudicated'}
    if size < 200 or doc.get('article_complete') is False:
        reasons.append('SHORT_' + short_state.upper())
    if not types:
        types.append('expository_candidate' if doc.get('template') not in ('unknown',None) else 'unknown')
    # EXCLUDE needs two independent, explicit signals in the same paragraph.
    commercial_absolute = any(s.get('stance') in ('asserted','quoted_endorsed')
                              and s['kind'] == 'absolute_treatment_claim'
                              and any(c['paragraph'] == s['paragraph'] for c in ctas) for s in asserted)
    decision = 'EXCLUDE' if commercial_absolute else 'REVIEW' if reasons else 'KEEP'
    if commercial_absolute:
        reasons.append('EXPLICIT_COMMERCIAL_ABSOLUTE_CLAIM')
    inputs = {key: doc.get(key) for key in ('text_sha256','heading_title','html_title','attributions',
              'published_at','source_name','article_complete','article_page_count','metadata_conflicts',
              'parser_flags','qc_structure','template','selector')}
    inputs['parser_flags'] = sorted(set(doc.get('parser_flags',[])) - {'DUPLICATE_DOCUMENT_REVIEW'})
    if doc.get('metadata_conflicts'):
        reasons.append('CONFLICTING_PAGE_METADATA')
        if decision == 'KEEP': decision = 'REVIEW'
    return {'source_policy_version': VERSION, 'source_policy_sha256': POLICY_SHA256,
            'source_input_sha256': digest(inputs), 'source_type': sorted(types),
            'source_signals': signals, 'source_decision': decision,
            'source_reason_codes': sorted(set(reasons)), 'title_body_alignment': title_match,
            'short_text_assessment': short, 'source_flags': sorted(flags)}


def apply(doc):
    doc.update(evaluate(doc))
    evidence = [e for e in doc.get('flag_evidence', [])
                if not (e.get('group') == 'source' and e.get('flag') in LEGACY_FLAGS)]
    for flag in sorted(set(doc['source_flags']) & LEGACY_FLAGS):
        evidence.append({'group':'source','flag':flag,'rule':VERSION,
                         'snippet':doc.get('heading_title','') if flag == 'TITLE_BODY_ALIGNMENT_REVIEW' else '',
                         'evidence_field':'title_body_alignment' if flag == 'TITLE_BODY_ALIGNMENT_REVIEW'
                         else 'attributions' if flag == 'AUTHOR_UNAVAILABLE_REVIEW' else 'source_signals'})
    doc['flag_evidence'] = evidence
    return doc


def audit(doc):
    expected = evaluate(doc)
    for field in FIELDS + ('source_flags',):
        if doc.get(field) != expected[field]:
            raise ValueError('cnkang source policy mismatch: ' + field)
    return True


def decision(doc):
    """Source result cannot bypass parser QC, completeness or a missing policy."""
    if doc.get('source_policy_version') != VERSION or doc.get('source_policy_sha256') != POLICY_SHA256:
        return 'REVIEW'
    if doc.get('source_decision') == 'EXCLUDE':
        return 'EXCLUDE'
    if (doc.get('article_complete') is not True or doc.get('quality_status') != 'accepted'
            or doc.get('parser_flags') or doc.get('source_decision') != 'KEEP'):
        return 'REVIEW'
    return 'KEEP'


def publish(doc, mode=DEFAULT_MODE):
    if mode not in ('report_only', 'enforce'):
        raise ValueError('Invalid cnkang source policy mode')
    if doc.get('source_policy_version'):
        audit(doc)
    value = dict(doc, source_policy_mode=mode, corpus_decision=decision(doc))
    value['source_gate_enforced'] = mode == 'enforce'
    return value


def audit_publication(doc):
    if 'source_policy_mode' not in doc:
        if 'corpus_decision' in doc or 'source_gate_enforced' in doc:
            raise ValueError('Missing cnkang publication policy mode')
        return
    mode = doc['source_policy_mode']
    if (mode not in ('report_only','enforce') or doc.get('corpus_decision') != decision(doc)
            or doc.get('source_gate_enforced') != (mode == 'enforce')):
        raise ValueError('cnkang publication source gate mismatch')


def export_eligible(doc, mode=DEFAULT_MODE):
    if mode not in ('report_only', 'enforce'):
        raise ValueError('Invalid cnkang source policy mode')
    if doc.get('source_policy_version'):
        audit(doc)
    if doc.get('status') not in (None,'extracted'):
        return False
    return (doc.get('quality_status') == 'accepted' if mode == 'report_only'
            else decision(doc) == 'KEEP')


def mode_for_run(out):
    modes = []
    out = Path(out)
    for name in ('corpus_config.json','config.json','cnkang_source_policy.json'):
        path = out / name
        if not path.exists(): continue
        config = json.loads(path.read_text(encoding='utf-8'))
        if name == 'cnkang_source_policy.json':
            if config.get('policy_sha256') != POLICY_SHA256 or config.get('policy_version') != VERSION:
                raise ValueError('Source policy changed; use a new run and recovery')
            mode = config.get('mode')
        else:
            mode = config.get('cnkang',config.get('network',{})).get('source_policy_mode')
        if mode is not None:
            if mode not in ('report_only','enforce'): raise ValueError('Invalid cnkang source policy mode')
            modes.append(mode)
    if len(set(modes)) > 1:
        raise ValueError('Conflicting cnkang source policy modes')
    return modes[0] if modes else DEFAULT_MODE
