"""Raw-backed extraction QC and candidate Parquet export for ask.39.net.

All decisions are recomputed from trusted source evidence at export time.
Production release remains a separate F5/F6 step.
"""
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

VERSION = 'ask39-gate-v8-independent-audit-integrity'
PARSER_VERSION = 'ask39-parser-v2-patient-evaluations'
CLAIM_RULE_VERSION = 'ask39-treatment-claim-v1'
METHOD = re.compile(r'靶位定向(?:体液疗法|给药)|定点\s*祛炎')
STRONG_CLAIM = re.compile(r'从根本上(?:治愈|根治)|(?:保证|确保|彻底|完全)(?:治愈|根治)|(?:实现|能够|可以|可)?阻断(?:病情|疾病)?(?:发展|进展)|(?:病情)?不易(?:反复)?复发')
NEGATED = re.compile(r'不(?:能|可|会|可能|一定|保证|确保|代表|建议|推荐|应该|应)|无法|并非|并不|未能|没有证据|尚无证据|并无证据|缺乏证据|请勿|切勿|不要')
REPORTED = re.compile(r'(?:患者|病人|广告|商家|宣传)(?:中)?(?:说|称|宣称|声称|提到|写)|宣称|声称|听说|据说|所谓')
REBUTTAL = re.compile(r'不可信|不能相信|不可相信|不应相信|没有依据|无依据|缺乏依据|缺乏证据|尚无证据|没有证据|并无证据|虚假|夸大|不实')
SAFETY_RULE_VERSION = 'ask39-absolute-safety-v1'
CTA_RULE_VERSION = 'ask39-consultation-cta-v1'
SUPERLATIVE_RULE_VERSION = 'ask39-specific-method-superlative-v1'
SUPERLATIVE_METHOD = re.compile(
    r'(?:(?:腹腔镜(?:下)?(?:微创)?(?:手术|术)?|微创(?:手术|术))(?:联合|结合)?'
    r'(?:转基因|基因(?:转移|修复|治疗)))|' + METHOD.pattern)
SUPERLATIVE_CLAIM = re.compile(
    r'(?:最好|最佳)(?:的)?(?:治疗)?(?:方法|疗法|方案|选择)'
    r'|(?:效果|疗效)(?:是|为)?(?:最好|最佳)|(?:是|为)(?:最好|最佳)(?:的)?')
SUPERLATIVE_DENIAL = re.compile(
    r'并非|并不|不是|不算|未必|不一定|不见得|不(?:认为|觉得|代表|建议|推荐|应该|应)|不要|请勿|切勿'
    r'|(?:不能|不可|不应|无法)(?:证明|保证|确认|认为|断言|说|称)'
    r'|(?:没有|尚无|并无|缺乏)(?:任何)?(?:证据|依据)|不要(?:说|称)|请勿(?:说|称)')
SUPERLATIVE_REPORTED = re.compile(
    r'(?:患者|病人|家属|广告|商家|宣传|网上|有人|他人|其他医生|医生)(?:中)?'
    r'(?:说|问|称|宣称|声称|提到|写|表示|自述|认为|告诉|介绍|建议|推荐)|听说|据说|所谓|宣称|声称')
SAFETY_METHOD = re.compile(r'激光(?:治疗)?|放射(?:治疗|疗法)|放疗|(?:阴茎)?延长手术|微创(?:技术|手术)|手术|脉络舒通颗粒')
SAFETY_GENERIC_METHOD = re.compile(r'[\u4e00-\u9fff]{2,12}(?:胶囊|颗粒|药片|疗法)')
SAFETY_CLAIM = re.compile(
    r'不(?:会)?(?:损伤|伤害)(?:周围)?(?:健康|正常)(?:的)?组织'
    r'|不(?:会)?(?:增加|提高)(?:出血|不良反应|并发症)?(?:的)?风险'
    r'|不(?:会)?影响(?:正常)?性生活'
    r'|(?:完全|绝对)?(?:无|没有)(?:任何)?(?:副作用|毒副作用|风险)'
    r'|(?:零|0)(?:风险|副作用)')
SAFETY_DENIAL = re.compile(r'不能|不可|无法|并非|并不|不是|不代表|不一定|未必|不保证|不确保|没有证据|尚无证据|缺乏证据|不推荐|不建议|不要|请勿|切勿')
SAFETY_ASSERTION_DENIAL = re.compile(r'(?:不能|不可|无法|不应|不)(?:保证|确保|证明|断言|声称|认为)|并非|没有证据|尚无证据|缺乏证据')
SAFETY_QUALIFIER = re.compile(r'通常|一般|可能|较少|未必|不一定')
CTA_NEGATED = re.compile(r'不要|请勿|切勿|别|无需|不用|没有(?:让|要求)|不(?:必|需要|能|可|应|建议|推荐)')
CONSULTATION_CTA = re.compile(
    r'(?:点击|点开|进入)[^。！？!?；;\n]{0,28}(?:在线咨询|线上咨询|咨询按钮|咨询入口|咨询医生)(?:】|\])?'
    r'|(?:欢迎|请|可以随时|可随时)[^。！？!?；;\n]{0,18}(?:在线咨询|线上咨询|一对一咨询)(?:】|\])?')
NAMED_PRODUCT_RULE_VERSION = 'ask39-named-product-claims-v1'
SOURCE_POLICY_VERSION = 'ask39-organization-specialist-holds-v1'
ORGANIZATION_AUTHOR = re.compile(r'制\s*药|药\s*业|药\s*厂|公司|集团|医院|卫生院|卫生服务中心|诊所|医疗中心|协会|基金会')
# Explicit unresolved source reviews, not a general medical classifier. A changed
# body/answer stays on hold until the review is resolved in a versioned policy.
PENDING_SPECIALIST_REVIEWS = {
    '/question/_4n3605.html': dict(reference='ask39-holdout650:2407658',
        answer_id='ask39:_4n3605:answer:170477078',
        raw_sha256='b434f4ca5495618d440b965e4665dc8c965885b65f1d0e4c6f6f3d95252a8876',
        quote='没有抗体接种疫苗无效。'),
    '/question/_u5h605.html': dict(reference='ask39-holdout650:2459843',
        answer_id='ask39:_u5h605:answer:170473746',
        raw_sha256='c98b9a786c3c73cb3262cdfab278b4bd4898a50a4b0e9d731e8685d2bb19767b',
        quote='hbsag阴性无感染风险者无需接种乙肝疫苗。'),
}


def organization_author_evidence(answer):
    """Corporate account names do not establish an individual clinician identity."""
    name=answer.get('author_name') or ''
    match=ORGANIZATION_AUTHOR.search(name)
    if not match: return []
    return [dict(rule='source_organization_author_review',rule_version=SOURCE_POLICY_VERSION,
        answer_id=answer.get('answer_id'),message_id=answer.get('answer_id'),
        locator=answer.get('locator'),field='author_name',quote=name,quote_span=[0,len(name)],
        organization_signal=match.group(),organization_signal_span=list(match.span()),
        qualification_raw=answer.get('qualification_raw'),
        review_status='organization_identity_review_pending',
        reason='Organization account name requires source review regardless of the displayed clinician title.')]


def pending_specialist_evidence(record):
    parsed=urlsplit(record.get('url') or '')
    hold=PENDING_SPECIALIST_REVIEWS.get(parsed.path) if parsed.hostname=='ask.39.net' else None
    if hold is None: return []
    answer=next((a for a in record.get('answers',[]) if a.get('answer_id')==hold['answer_id']),None)
    value=answer.get('text','') if answer else ''
    at=value.find(hold['quote'])
    return [dict(rule='source_specialist_review_pending',rule_version=SOURCE_POLICY_VERSION,
        review_reference=hold['reference'],review_status='pending_specialist_review',
        expected_answer_id=hold['answer_id'],answer_id=answer.get('answer_id') if answer else None,
        message_id=answer.get('answer_id') if answer else None,locator=answer.get('locator') if answer else None,
        expected_quote=hold['quote'],quote=hold['quote'] if at>=0 else None,
        quote_span=[at,at+len(hold['quote'])] if at>=0 else None,
        reviewed_source_raw_sha256=hold['raw_sha256'],observed_raw_sha256=record.get('raw_sha256'),
        source_unchanged=record.get('raw_sha256')==hold['raw_sha256'] and at>=0,
        reason='Specialist adjudication is pending; source changes and cached acceptance do not clear the hold.')]
NAMED_PRODUCT = re.compile(r'人参皂苷\s*(?:Rh2|G35)(?![A-Za-z0-9])(?:\s*[(（]护命素[)）])?|护命素',re.I)
NAMED_DEVICE = re.compile(r'韩氏(?:疼痛)?治疗仪')
PRODUCT_EFFICACY = re.compile(
    r'抗(?:肿瘤|癌)(?!能力)|逆转(?:肿瘤|癌)?细胞耐药性'
    r'|(?:防止|预防|阻断|避免)(?:术后)?(?:肿瘤|癌症|癌)?的?'
    r'(?:复发(?:[和及、与]转移)?|转移(?:[和及、与]复发)?)')
PRODUCT_DENIAL = re.compile(
    SUPERLATIVE_DENIAL.pattern + r'|不(?:能|可|会|具有|具备|支持|足以|保证|确保)'
    r'|无法|未(?:被)?(?:证实|证明)|(?:无|没有)(?:明确的?|已证实的?)?$|不$')
PRODUCT_QUALIFIER = re.compile(r'可能|也许|或许|假如|如果|尚在研究|仍在研究|(?:有待|尚待)(?:研究|证实|证明)|尚不明确|不确定')
PRODUCT_UNPROVEN = re.compile(r'(?:尚|并|仍)?未(?:被)?(?:证实|证明)|(?:无法|不能)(?:证实|证明)|不成立')
PRODUCT_TOPIC_SWITCH = re.compile(r'其他(?:药物|产品|设备|方法)|另(?:一|一种)(?:药物|产品|设备|方法)|至于|而(?:化疗|放疗|手术)|[，,]\s*(?:化疗|放疗|手术)(?:可|能|有|具|是|的)')
PRODUCT_REPORTED = re.compile(SUPERLATIVE_REPORTED.pattern +
    r'|(?:厂家|厂商|说明书|文献|论文)(?:中)?(?:说|称|写|表示|认为|介绍|建议|推荐)|据(?:研究|报道|文献)')


def named_product_assessments(message, answer_id):
    """Review observed named products/devices plus affirmative source claims."""
    if message.get('speaker_role')!='responder': return []
    value=message.get('text','')
    sentences=list(re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?',value))
    quoted=[m.span() for pattern in (r'“[^”\n]*”',r'「[^」\n]*」',r'『[^』\n]*』',
            r'‘[^’\n]*’',r'"[^"\n]*"',r"'[^'\n]*'") for m in re.finditer(pattern,value)]
    result=[]
    for index,sentence in enumerate(sentences):
        text=sentence.group()
        for kind,method_pattern,claim_pattern,rule in (
            ('named_product_efficacy',NAMED_PRODUCT,PRODUCT_EFFICACY,'source_named_product_efficacy_review'),
            ('named_device_safety',NAMED_DEVICE,SAFETY_CLAIM,'source_named_device_safety_review')):
            methods=list(method_pattern.finditer(text))
            for claim in claim_pattern.finditer(text):
                start,end=sentence.start()+claim.start(),sentence.start()+claim.end()
                preceding=[m for m in methods if m.end()<=claim.start() and claim.start()-m.end()<=300]
                following=[m for m in methods if claim.end()<=m.start() and m.start()-claim.end()<=100
                           and not re.search(r'[，,:：]',text[claim.end():m.start()])
                           and re.search(r'的(?:药物|产品|制剂|设备|治疗仪)?(?:是|为|包括)\s*$',text[claim.end():m.start()])]
                relation='same_sentence';context_start=sentence.start()
                if preceding or following:
                    method=preceding[-1] if preceding else following[0]
                    ms,me=sentence.start()+method.start(),sentence.start()+method.end()
                elif index and re.match(r'\s*(?:该|此|这种|上述)(?:产品|制剂|药物|药品|设备|治疗仪)',text):
                    previous=sentences[index-1];prior=list(method_pattern.finditer(previous.group()))
                    if (len(prior)!=1 or '\n' in value[previous.end():sentence.start()]
                            or previous.group().rstrip().endswith(('；',';'))): continue
                    ms,me=previous.start()+prior[-1].start(),previous.start()+prior[-1].end()
                    context_start=previous.start();relation='previous_sentence_reference'
                else: continue
                lo,hi=min(ms,start),max(me,end)
                # Scope speech/polarity to this assertion; explicit contrast can start a new one.
                prefix=re.split(r'但是|然而|不过|但|我认为|我建议|我推荐',value[max(context_start,lo-64):lo])[-1]
                assertion=prefix+value[lo:start]+(value[end:ms] if ms>=end else '')
                # Reported speech may introduce a long passage before the named method.
                # Do not drop that attribution when bounding the local polarity window.
                speech=re.split(r'但是|然而|不过|但|我认为|我建议|我推荐',value[context_start:lo])[-1]+value[lo:hi]
                suffix=value[hi:sentence.end()]
                reason=None
                if any(a<end and start<b or a<me and ms<b for a,b in quoted): reason='quoted_product_claim'
                elif (re.search(r'是否|能否|是不是|请问|想知道',speech) or re.search(r'吗|么|[？?]',suffix)
                      or re.search(r'有(?:没有|无)',value[max(context_start,start-1):end])): reason='questioned_product_claim'
                elif PRODUCT_REPORTED.search(speech): reason='reported_product_claim'
                elif PRODUCT_DENIAL.search(assertion): reason='denied_product_claim'
                elif (PRODUCT_QUALIFIER.search(assertion) or PRODUCT_QUALIFIER.search(re.split(r'[，,]',suffix,1)[0])
                      or kind=='named_device_safety' and SAFETY_QUALIFIER.search(assertion)): reason='qualified_product_claim'
                elif PRODUCT_TOPIC_SWITCH.search(value[me:start]): reason='different_treatment_context'
                elif PRODUCT_UNPROVEN.search(re.split(r'[，,]',suffix,1)[0]): reason='unproven_product_claim'
                elif REBUTTAL.search(re.split(r'[，,]',suffix,1)[0]): reason='rebutted_product_claim'
                elif re.match(r'^[，,]\s*(?:(?:这种|该|上述|此)(?:说法|宣传|承诺)|这)',suffix) and REBUTTAL.search(suffix): reason='rebutted_product_claim'
                if reason is None and index+1<len(sentences):
                    next_sentence=sentences[index+1]
                    if ('\n' not in value[sentence.end():next_sentence.start()]
                            and re.match(r'\s*(?:这种|该|上述|此)(?:说法|宣传|承诺)',next_sentence.group())
                            and REBUTTAL.search(next_sentence.group())): reason='rebutted_product_claim'
                result.append(dict(rule=rule,rule_version=NAMED_PRODUCT_RULE_VERSION,statement_kind=kind,
                    answer_id=answer_id,message_id=message.get('message_id') or answer_id,
                    speaker_role='responder',locator=message.get('locator'),
                    quote=value[context_start:sentence.end()],quote_span=[context_start,sentence.end()],
                    method=value[ms:me],method_span=[ms,me],claim=value[start:end],claim_span=[start,end],
                    context_relation=relation,decision='suppressed' if reason else 'review',suppression_reason=reason))
    return result


def _safety_methods(text):
    known = list(SAFETY_METHOD.finditer(text))
    generic = [m for m in SAFETY_GENERIC_METHOD.finditer(text)
               if not any(m.start() < k.end() and k.start() < m.end() for k in known)]
    return sorted([*known, *generic], key=lambda m: m.start())


def superlative_assessments(message, answer_id):
    """Triage superlatives tied to observed specific methods, within source speech."""
    if message.get('speaker_role') != 'responder': return []
    value = message.get('text', '')
    sentences = list(re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?', value))
    quoted = [m.span() for pattern in (r'“[^”\n]*”', r'「[^」\n]*」', r'『[^』\n]*』',
              r'"[^"\n]*"', r'‘[^’\n]*’', r"'[^'\n]*'") for m in re.finditer(pattern, value)]
    result = []
    for index, sentence in enumerate(sentences):
        text = sentence.group()
        for claim in SUPERLATIVE_CLAIM.finditer(text):
            start, end = sentence.start()+claim.start(), sentence.start()+claim.end()
            pairs = []
            for method in SUPERLATIVE_METHOD.finditer(text):
                lo, hi = min(method.start(), claim.start()), max(method.end(), claim.end())
                if hi-lo <= 160 and not re.search(r'[，,:：]', text[lo:hi]):
                    pairs.append((abs(method.start()-claim.start()), sentence.start()+method.start(), sentence.start()+method.end()))
            relation = 'same_clause'
            if pairs:
                _, method_start, method_end = min(pairs)
                context_start = sentence.start()
            elif index and re.match(r'\s*(?:该|此|这种|上述)(?:方法|疗法|治疗|手术)', text):
                previous = sentences[index-1]
                methods = list(SUPERLATIVE_METHOD.finditer(previous.group()))
                if (not methods or '\n' in value[previous.end():sentence.start()]
                        or previous.group().rstrip().endswith(('；', ';'))): continue
                method_start, method_end = previous.start()+methods[-1].start(), previous.start()+methods[-1].end()
                context_start, relation = previous.start(), 'previous_sentence_reference'
            else: continue
            lo, hi = min(start, method_start), max(end, method_end)
            clause_start = max(value.rfind(ch, context_start, lo) for ch in ('，', ',', ':', '：'))+1
            clause_start = max(clause_start, context_start)
            prefix = re.split(r'但是|然而|不过|但|我认为|我建议', value[clause_start:lo])[-1]
            assertion = prefix + value[lo:hi]
            speech_prefix = re.split(r'但是|然而|不过|但|我认为|我建议', re.split(r'[，,]', value[context_start:lo])[-1])[-1]
            suffix = value[hi:sentence.end()]
            reason = None
            question_context = assertion + re.split(r'[，,]', suffix, 1)[0]
            if re.search(r'是否|能否|是不是|请问|想知道|吗|么|[？?]', question_context): reason = 'questioned_superlative'
            elif any(a < end and start < b or a < method_end and method_start < b for a,b in quoted): reason = 'quoted_superlative'
            elif SUPERLATIVE_REPORTED.search(speech_prefix) or SUPERLATIVE_REPORTED.search(assertion): reason = 'reported_superlative'
            elif SUPERLATIVE_DENIAL.search(assertion): reason = 'denied_superlative'
            elif re.search(r'可能|也许|或许|如果|假如', assertion): reason = 'qualified_superlative'
            elif REBUTTAL.search(re.split(r'[，,]', suffix, 1)[0]): reason = 'rebutted_superlative'
            elif re.search(r'[，,]\s*(?:(?:这种|该|上述|此)(?:说法|宣传|承诺)|这)', suffix) and REBUTTAL.search(suffix): reason = 'rebutted_superlative'
            if reason is None and index+1 < len(sentences):
                following = sentences[index+1]
                if ('\n' not in value[sentence.end():following.start()]
                        and re.match(r'\s*(?:这种|该|上述|此)(?:说法|宣传|承诺)', following.group())
                        and REBUTTAL.search(following.group())): reason = 'rebutted_superlative'
            result.append(dict(rule='source_specific_method_superlative_review', rule_version=SUPERLATIVE_RULE_VERSION,
                statement_kind='specific_method_superlative', answer_id=answer_id,
                message_id=message.get('message_id') or answer_id, speaker_role='responder', locator=message.get('locator'),
                quote=text, quote_span=[sentence.start(),sentence.end()], method=value[method_start:method_end],
                method_span=[method_start,method_end], claim=value[start:end], claim_span=[start,end],
                context_relation=relation, decision='suppressed' if reason else 'review', suppression_reason=reason))
    return result


def source_context_assessments(message, answer_id):
    """Triage source assertions/invitations without changing or medically judging text."""
    if message.get('speaker_role') != 'responder':
        return []
    value = message.get('text', '')
    sentences = list(re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?', value))
    quoted = []
    for pattern in (r'“[^”\n]*”', r'「[^」\n]*」', r'"[^"\n]*"'):
        for match in re.finditer(pattern, value):
            if value[:match.start()].strip() or value[match.end():].strip():
                quoted.append(match.span())
    result = []
    for index, sentence in enumerate(sentences):
        text = sentence.group()
        methods = _safety_methods(text)
        for kind, pattern, rule, version in (
            ('safety', SAFETY_CLAIM, 'source_absolute_safety_claim_review', SAFETY_RULE_VERSION),
            ('consultation_cta', CONSULTATION_CTA, 'source_consultation_cta_review', CTA_RULE_VERSION),
        ):
            for claim in pattern.finditer(text):
                method_span = None
                context_start = sentence.start()
                relation = 'same_sentence'
                if kind == 'safety':
                    preceding = [m for m in methods if m.start() <= claim.start() and claim.start()-m.end() <= 400]
                    if preceding:
                        method = preceding[-1]
                        method_span = (sentence.start()+method.start(), sentence.start()+method.end())
                    elif index and re.match(r'\s*(?:该|此|这种|上述)(?:技术|方法|疗法|治疗|手术|药物|药)', text):
                        previous = sentences[index-1]
                        prior = _safety_methods(previous.group())
                        if prior and '\n' not in value[previous.end():sentence.start()]:
                            method_span = (previous.start()+prior[-1].start(), previous.start()+prior[-1].end())
                            context_start = previous.start()
                            relation = 'previous_sentence_reference'
                    if method_span is None:
                        continue
                start, end = sentence.start()+claim.start(), sentence.start()+claim.end()
                clause_start = max(text.rfind(ch, 0, claim.start()) for ch in ('，', ',', '：', ':'))+1
                prefix, suffix = text[clause_start:claim.start()], text[claim.end():]
                reason = None
                if re.search(r'是否|能否', text[:claim.start()]) or re.search(r'吗|么|[？?]', suffix):
                    reason = 'questioned_statement'
                elif (SAFETY_DENIAL if kind == 'safety' else CTA_NEGATED).search(prefix):
                    reason = 'denied_assertion' if kind == 'safety' else 'negated_invitation'
                elif kind == 'safety' and SAFETY_QUALIFIER.search(prefix):
                    reason = 'qualified_safety_statement'
                elif REPORTED.search(text[:claim.start()]):
                    reason = 'reported_statement'
                elif any(a <= start and end <= b for a, b in quoted):
                    reason = 'quoted_statement'
                elif REBUTTAL.search(re.split(r'[，,]', suffix, 1)[0]):
                    reason = 'rebutted_statement'
                elif re.match(r'^[，,]\s*(?:(?:这种|该|上述|此)(?:说法|宣传|承诺)|这)', suffix) and REBUTTAL.search(suffix):
                    reason = 'rebutted_statement'
                if method_span is not None:
                    method_prefix = re.split(r'[，,:：]', value[context_start:method_span[0]])[-1]
                    if reason is None and SAFETY_DENIAL.search(method_prefix):
                        reason = 'negated_method_context'
                    if reason is None and REPORTED.search(method_prefix):
                        reason = 'reported_method_context'
                    # Negation between method and claim must not be lost at a comma.
                    between = value[method_span[1]:start]
                    if reason is None and SAFETY_ASSERTION_DENIAL.search(between):
                        reason = 'denied_assertion'
                if reason is None and index+1 < len(sentences):
                    following = sentences[index+1]
                    if '\n' not in value[sentence.end():following.start()] and re.match(r'\s*(?:这种|该|上述|此)(?:说法|宣传|承诺)', following.group()) and REBUTTAL.search(following.group()):
                        reason = 'rebutted_statement'
                result.append(dict(rule=rule, rule_version=version, statement_kind=kind,
                    answer_id=answer_id, message_id=message.get('message_id') or answer_id,
                    speaker_role='responder', locator=message.get('locator'),
                    quote=text, quote_span=[sentence.start(), sentence.end()],
                    method=value[method_span[0]:method_span[1]] if method_span else None,
                    method_span=list(method_span) if method_span else None,
                    claim=value[start:end], claim_span=[start, end], context_relation=relation,
                    decision='suppressed' if reason else 'review', suppression_reason=reason))
    return result + superlative_assessments(message, answer_id) + named_product_assessments(message, answer_id)


def treatment_claims(message, answer_id):
    """Review observed method/claim combinations; classify source speech, not medical truth."""
    if message.get('speaker_role') != 'responder': return []
    value = message.get('text','')
    sentences=list(re.finditer(r'[^。！？!?；;\n]+[。！？!?；;]?',value))
    quoted=[]
    for pattern in (r'“[^”\n]*”',r'「[^」\n]*」',r'"[^"\n]*"'):
        for match in re.finditer(pattern,value):
            # Entire-answer wrapping quotes occur in the real source as formatting.
            if value[:match.start()].strip() or value[match.end():].strip(): quoted.append(match.span())
    result=[]
    for index,sentence in enumerate(sentences):
        text=sentence.group();methods=list(METHOD.finditer(text))
        inherited=None
        if not methods and index:
            previous=sentences[index-1]
            if '\n' not in value[previous.end():sentence.start()] and re.match(r'\s*(?:该|这种|此|上述)(?:方法|疗法|治疗|法)',text):
                prior=list(METHOD.finditer(previous.group()))
                if prior: inherited=(previous.start()+prior[-1].start(),previous.start()+prior[-1].end())
        for claim in STRONG_CLAIM.finditer(text):
            preceding=[m for m in methods if m.start()<=claim.start() and claim.start()-m.end()<=400]
            if preceding:
                method=preceding[-1];method_span=(sentence.start()+method.start(),sentence.start()+method.end())
            elif inherited:
                method_span=inherited
            else:
                continue
            start,end=sentence.start()+claim.start(),sentence.start()+claim.end()
            # Polarity belongs to this clause, not an unrelated sentence on the page.
            clause_start=max(text.rfind('，',0,claim.start()),text.rfind(',',0,claim.start()),text.rfind('：',0,claim.start()),text.rfind(':',0,claim.start()))+1
            prefix=text[clause_start:claim.start()]
            suffix=text[claim.end():]
            reason=None
            if re.search(r'是否|能否',text[:claim.start()]) or re.search(r'吗|么|[？?]',suffix): reason='questioned_claim'
            elif NEGATED.search(prefix): reason='negated_claim'
            elif REPORTED.search(text[:claim.start()]): reason='reported_claim'
            elif any(a<=start and end<=b for a,b in quoted): reason='quoted_claim'
            elif REBUTTAL.search(re.split(r'[，,]',suffix,1)[0]): reason='rebutted_claim'
            elif re.match(r'^[，,]\s*(?:(?:这种|该|上述|此)(?:说法|宣传|承诺)|这)(?:是|并)?[^。！？!?；;]{0,20}',suffix) and REBUTTAL.search(suffix): reason='rebutted_claim'
            # A negated/reported method cannot supply an affirmative treatment context.
            context_start=sentences[index-1].start() if inherited else sentence.start()
            method_prefix=value[context_start:method_span[0]]
            method_prefix=re.split(r'[，,:：]',method_prefix)[-1]
            if reason is None and NEGATED.search(method_prefix): reason='negated_method'
            if reason is None and REPORTED.search(method_prefix): reason='reported_method'
            if reason is None and any(a<=method_span[0] and method_span[1]<=b for a,b in quoted): reason='quoted_method'
            result.append(dict(rule='source_treatment_claim_review',rule_version=CLAIM_RULE_VERSION,
                answer_id=answer_id,message_id=message.get('message_id') or answer_id,speaker_role='responder',
                locator=message.get('locator'),quote=text,quote_span=[sentence.start(),sentence.end()],
                method=value[method_span[0]:method_span[1]],method_span=list(method_span),
                claim=value[start:end],claim_span=[start,end],
                decision='suppressed' if reason else 'review',suppression_reason=reason,
                context_relation='previous_sentence_reference' if inherited else 'same_sentence'))
    return result


def _audit_module():
    path = Path(__file__).with_name('ask39_audit.py')
    if not path.is_file(): path = Path(__file__).with_name('ask39_audit_snapshot.py')
    spec = importlib.util.spec_from_file_location('_ask39_gate_audit', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def render(record):
    compact = lambda s: re.sub(r'\s+', '', s or '')
    lines = ['问题：' + record.get('title', '')]
    lines.extend(q['text'] for q in record.get('question', {}).get('blocks', [])
                 if compact(q['text']) != compact(record.get('title')))
    for answer in record.get('answers', []):
        lines.extend(['回答者：' + (answer.get('author_name') or '未注明'), answer['text']])
        for message in answer.get('followups', []):
            label = {'patient':'患者追问', 'responder':'回答者补充回答'}.get(message['speaker_role'], '后续交流（身份未明）')
            lines.append(label + '：' + message['text'])
    for message in record.get('followups', []):
        if message.get('parent_answer_id') is None:
            lines.append('后续交流（所属回答未明）：' + message['text'])
    return '\n\n'.join(lines)


def _evaluate(record, body, evidence):
    """Return REVIEW on absent/invalid evidence; never inherit old acceptance."""
    access, parser, audit_flags, source = [], [], [], []
    audit_result, source_evidence, claim_assessments = None, [], []
    context_assessments = []
    if record.get('http_status') != 200 or record.get('status') not in ('extracted','rendered'):
        access.append('page_not_verified_accessible')
    if record.get('challenge_detected'): access.append('challenge_detected')
    expected_url = evidence.get('url') if evidence else None
    if not evidence or record.get('id') != evidence.get('id') or record.get('url') != expected_url:
        access.append('source_identity_mismatch')
    parsed = urlsplit(record.get('final_url') or record.get('url') or '')
    original = urlsplit(expected_url or '')
    if (parsed.hostname != 'ask.39.net' or original.hostname != 'ask.39.net'
            or parsed.scheme not in ('http','https') or parsed.path != original.path
            or not re.fullmatch(r'/question/[A-Za-z0-9_-]+\.html', parsed.path)):
        access.append('unsupported_page_or_redirect')
    digest = hashlib.sha256(body).hexdigest() if isinstance(body, bytes) else None
    if not digest or not evidence or digest != evidence.get('raw_sha256') or digest != record.get('raw_sha256'):
        access.append('raw_evidence_missing_or_mismatch')
    if record.get('extractor') != 'ask39_qa_dom_v2' or record.get('parser_version') != PARSER_VERSION:
        parser.append('legacy_or_unsupported_parser')
    parser.extend(record.get('parser_flags') or [])
    if record.get('parser_status') != 'parsed': parser.append('parser_not_complete')
    answers, followups = record.get('answers', []), record.get('followups', [])
    if not record.get('title') or not record.get('question', {}).get('blocks'): parser.append('question_missing')
    if not answers: parser.append('no_main_answers')
    if record.get('source_answer_count') != len(answers) or record.get('main_answer_count') != len(answers):
        parser.append('answer_count_mismatch')
    if record.get('source_followup_count') != len(followups) or record.get('followup_count') != len(followups):
        parser.append('followup_count_mismatch')
    if len({a.get('answer_id') for a in answers}) != len(answers): parser.append('duplicate_answer_id')
    question_id=original.path.rsplit('/',1)[-1][:-5]
    if record.get('source_question_id')!=question_id: parser.append('question_identity_mismatch')
    for answer in answers:
        if answer.get('identity_status')!='verified' or not answer.get('source_answer_id'):
            parser.append('answer_identity_not_verified')
        if answer.get('source_question_id')!=question_id: parser.append('question_identity_mismatch')
    if len({m.get('message_id') for m in followups}) != len(followups): parser.append('duplicate_message_id')
    for message in [*answers, *followups]:
        value = message.get('text', '')
        if not value.strip(): parser.append('empty_message')
        if message.get('text_sha256') != hashlib.sha256(value.encode()).hexdigest(): parser.append('message_hash_mismatch')
    for message in followups:
        if message.get('speaker_role') not in ('patient','responder'): parser.append('unknown_followup_role')
        if message.get('parent_answer_id') not in {a.get('answer_id') for a in answers}: parser.append('orphan_followup')
    try:
        if record.get('text') != render(record): parser.append('rendered_text_mismatch')
    except (KeyError, TypeError):
        parser.append('invalid_structure')
    text = record.get('text') or ''
    if record.get('text_sha256') != hashlib.sha256(text.encode()).hexdigest(): parser.append('text_hash_mismatch')
    if record.get('char_count') != len(text): parser.append('char_count_mismatch')
    if not access:
        try:
            audit_result = _audit_module().audit_record(record, body)
            audit_flags.extend(audit_result['flags'])
        except Exception as exc:
            audit_flags.append('raw_audit_failed:' + type(exc).__name__)
    else:
        audit_flags.append('raw_audit_not_verified')
    # Source review is separate from extraction completeness; no medical verdict.
    for answer in answers:
        organization=organization_author_evidence(answer)
        source_evidence.extend(organization)
        source.extend(e['rule'] for e in organization)
        if not answer.get('author_name') or not answer.get('qualification_raw'):
            source.append('source_author_unverified')
            source_evidence.append(dict(rule='source_author_unverified',answer_id=answer.get('answer_id'),locator=answer.get('locator')))
        elif not re.fullmatch(r'(?:(?:副主任|主任|主治|住院|执业助理|执业)?医师|医士|医生|(?:副主任|主任|主管|执业)?中?药师|药士|(?:副主任|主任|主管)?护师|护士)', answer['qualification_raw'][0].strip()):
            source.append('source_qualification_unrecognized')
            source_evidence.append(dict(rule='source_qualification_unrecognized',answer_id=answer.get('answer_id'),locator=answer.get('locator'),qualification_raw=answer.get('qualification_raw')))
        for message in [answer, *answer.get('followups',[])]:
            if message.get('speaker_role')!='responder': continue
            value = message.get('text','')
            assessments=treatment_claims(message,answer.get('answer_id'))
            claim_assessments.extend(assessments)
            for assessment in assessments:
                if assessment['decision']=='review':
                    source.append('source_treatment_claim_review');source_evidence.append(assessment)
            contexts=source_context_assessments(message,answer.get('answer_id'))
            context_assessments.extend(contexts)
            for assessment in contexts:
                if assessment['decision']=='review':
                    source.append(assessment['rule']);source_evidence.append(assessment)
            for rule, pattern in [('source_contact_signal',r'(?:微信|QQ)\s*[:：号]?\s*[A-Za-z0-9_-]{5,}|点击.{0,12}(?:头像|名字).{0,20}(?:咨询|联系)'),
                                  ('source_promotion_signal',r'推荐.{0,12}(?:疗法|人参皂苷)')]:
                match = re.search(pattern,value)
                if match:
                    source.append(rule)
                    source_evidence.append(dict(rule=rule,answer_id=answer.get('answer_id'),message_id=message.get('message_id'),locator=message.get('locator'),quote=value[max(0,match.start()-30):match.end()+60]))
    pending=pending_specialist_evidence(record)
    source_evidence.extend(pending)
    source.extend(e['rule'] for e in pending)
    access, parser, audit_flags, source = [sorted(set(values)) for values in (access,parser,audit_flags,source)]
    extraction_ok = not (access or parser or audit_flags)
    eligible = extraction_ok and not source
    return dict(gate_version=VERSION, evidence_sha256=digest,
        extraction_status='accepted' if extraction_ok else 'review',
        quality_status='accepted' if eligible else 'review',
        candidate_eligible=eligible, corpus_eligible=False,
        access_flags=access, parser_flags=parser, audit_flags=audit_flags, source_flags=source,
        source_evidence=source_evidence,
        claim_assessments=claim_assessments,
        source_context_assessments=context_assessments,
        quality_flags=sorted(set(access + parser + audit_flags + source)), audit=audit_result)


def evaluate(record, body, evidence):
    try:
        return _evaluate(record, body, evidence)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        return dict(gate_version=VERSION, extraction_status='review', quality_status='review',
                    candidate_eligible=False, corpus_eligible=False, access_flags=[],
                    parser_flags=['invalid_record_structure'],audit_flags=[],source_flags=[],
                    quality_flags=['invalid_record_structure'],audit=None,error=type(exc).__name__)


def export_candidates(records, raw_dir, output, sources):
    """Write local candidates only; recompute every decision, including cached accepted."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    records, output, raw_dir = list(records), Path(output), Path(raw_dir).resolve()
    if output.exists() or output.with_suffix('.decisions.jsonl').exists():
        raise ValueError('Output already exists; preserve previous evidence')
    if len({r['id'] for r in records}) != len(records): raise ValueError('Duplicate source IDs')
    rows, decisions = [], []
    for record in records:
        try:
            path = (raw_dir/record['raw_path']).resolve()
            if not path.is_relative_to(raw_dir): raise ValueError('Raw path outside run')
            body = gzip.decompress(path.read_bytes())
        except (KeyError, ValueError, OSError, EOFError):
            body = None
        decision = evaluate(record, body, sources.get(record['id']))
        decisions.append(dict(id=record['id'], url=record['url'], **decision))
        if decision['candidate_eligible']:
            rows.append(dict(id=record['id'],url=record['url'],title=record['title'],text=record['text'],
                             text_sha256=record['text_sha256'],quality_status='accepted'))
    schema = pa.schema([('id',pa.int64()),('url',pa.string()),('title',pa.string()),
                        ('text',pa.string()),('text_sha256',pa.string()),('quality_status',pa.string())])
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary = output.with_suffix(output.suffix+'.tmp')
    pq.write_table(pa.Table.from_pylist(rows,schema=schema), temporary)
    temporary.replace(output)
    output.with_suffix('.decisions.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in decisions),encoding='utf-8')
    return dict(attempted=len(records),candidate_exported=len(rows),review=len(records)-len(rows),
                source_flags=dict(Counter(f for d in decisions for f in d['source_flags'])),
                gate_version=VERSION, production_exported=0)
