"""Evidence-preserving cnkang parser ported from the supplied v6 notebook/specification.

Original code is archived under docs/references/cnkang; the 120 raw pages were not supplied.
Source-quality heuristics are review signals, never medical judgements.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import html as html_std
import re
from urllib.parse import urlsplit

from lxml import html, etree

VERSION = 'cnkang-v6-spec-2'
EXTRACTOR = 'cnkang_v6_spec_dom'


def is_host(url):
    host = (urlsplit(url).hostname or '').lower()
    return host == 'cnkang.com' or host.endswith('.cnkang.com')


def compact(value):
    return re.sub(r'\s+', '', value or '')


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def decode_bytes(body, content_type=''):
    """Rank strict decodes using multiple corruption signals, preserving uncertainty."""
    declarations = re.findall(r'charset\s*=\s*["\']?([\w-]+)', content_type, re.I)
    declarations += re.findall(r'charset\s*=\s*["\']?([\w-]+)', body[:16384].decode('ascii', 'replace'), re.I)
    declared = declarations[0].lower() if declarations else None
    alias = {'gb2312': 'gb18030', 'gbk': 'gb18030', 'utf8': 'utf-8', 'x-gbk': 'gb18030'}
    declared_normal = alias.get(declared, declared)
    choices = list(dict.fromkeys([e for e in (declared_normal, 'utf-8', 'gb18030', 'gbk', 'big5') if e]))
    candidates, decoded = [], {}
    for encoding in choices:
        try:
            text = body.decode(encoding, 'strict')
        except (UnicodeError, LookupError) as exc:
            candidates.append({'encoding': encoding, 'strict_valid': False, 'error': str(exc)[:160]})
            continue
        # Measure visible text; ASCII markup must not swamp the signal.
        visible = re.sub(r'<[^>]*>', '', text)
        size = max(1, len(visible))
        cjk = sum('\u3400' <= c <= '\u9fff' for c in visible) / size
        pua = sum('\ue000' <= c <= '\uf8ff' for c in visible) / size
        replacement = visible.count('\ufffd') / size
        mojibake = len(re.findall(r'(?:Ã.|Â.|â€|ä¸|æ–|å­|锟斤拷){2,}', visible))
        score = 4 * cjk - 30 * pua - 100 * replacement - 2 * mojibake
        if encoding == 'utf-8': score += 3.0
        if encoding == declared_normal: score += 1.5
        item = {'encoding': encoding, 'strict_valid': True, 'score': round(score, 6),
                'cjk_ratio': round(cjk, 6), 'replacement_ratio': replacement,
                'pua_ratio': pua, 'mojibake_runs': mojibake}
        candidates.append(item)
        decoded[encoding] = text
    valid = sorted((c for c in candidates if c['strict_valid']), key=lambda c: c['score'], reverse=True)
    if not valid:
        # Explicit, flagged fallback for inspection only; original bytes remain the evidence.
        return body.decode('utf-8', 'replace'), {
            'selected_encoding': 'utf-8-replacement-fallback', 'declared_encoding': declared,
            'encoding_candidates': candidates, 'encoding_uncertain': True}
    best = valid[0]
    uncertain = bool(best['replacement_ratio'] or best['mojibake_runs'] or best['pua_ratio'] > .002)
    if len(valid) > 1 and best['score'] - valid[1]['score'] < .25:
        if decoded[best['encoding']] != decoded[valid[1]['encoding']]:
            uncertain = True
    return decoded[best['encoding']], {
        'selected_encoding': best['encoding'], 'declared_encoding': declared,
        'encoding_candidates': candidates, 'encoding_uncertain': uncertain}


def has_class(node, name):
    return name in (node.get('class') or '').split()


def class_nodes(tree, name):
    return tree.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," ' + name + ' ")]')


def clean_node(node):
    node = copy.deepcopy(node)
    for child in node.xpath('.//script|.//style|.//noscript|.//iframe|.//nav'):
        child.drop_tree()
    # Only exact, previously documented page furniture.
    for child in list(node.iterdescendants()):
        if (child.get('id') or '').lower() == 'jkpl' or has_class(child, 'article_intro'):
            if child.getparent() is not None:
                child.drop_tree()
        elif child.tag == 'p' and re.match(r'^\s*相关文章[：:]', child.text_content()):
            if child.getparent() is not None:
                child.drop_tree()
    return node


def node_text(node):
    """Block separators preserve DOM order; inline link text stays adjacent."""
    node = clean_node(node)
    for element in node.iter():
        if element.tag == 'br':
            element.tail = '\n' + (element.tail or '')
        elif element.tag in ('p', 'div', 'section', 'article', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'blockquote'):
            element.text = '\n' + (element.text or '')
            element.tail = '\n' + (element.tail or '')
        elif element.tag in ('td', 'th'):
            element.tail = '\t' + (element.tail or '')
    text = node.text_content().replace('\r\n', '\n').replace('\xa0', ' ')
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines() if line.strip())


def link_ratio(node):
    return sum(len(compact(a.text_content())) for a in node.iter('a')) / max(1, len(compact(node_text(node))))


def descriptor(node):
    return node.getroottree().getpath(node)


def choose_body(tree):
    """Return the body and evidence; parallel candidate bodies remain reviewable."""
    flags, candidates = [], []
    known = class_nodes(tree, 'detailc') + tree.xpath(
        '//*[translate(@id,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="endtext"]')
    known = list(dict.fromkeys(known))
    parallel = [n for n in known if not any(a in known for a in n.iterancestors())]
    if len(parallel) > 1:
        combined = html.Element('article')
        for node in parallel:
            candidates.append({'path':descriptor(node), 'chars':len(compact(node_text(node))),
                               'coverage':1., 'link_ratio':round(link_ratio(node),5)})
            combined.append(copy.deepcopy(node))
        return combined, 'combined_known', candidates, ['AMBIGUOUS_BODY_REVIEW'], parallel[0]
    for template, nodes in (
        ('detailc', class_nodes(tree, 'detailc')),
        ('endtext', tree.xpath('//*[translate(@id,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="endtext"]')),
        ('conmain', class_nodes(tree, 'conmain')),
    ):
        if not nodes:
            continue
        if len(nodes) > 1:
            flags.append('AMBIGUOUS_BODY_REVIEW')
        root = nodes[0]
        candidates.extend({'path': descriptor(n), 'chars': len(compact(node_text(n))),
                           'coverage': 1.0, 'link_ratio': round(link_ratio(n), 5)} for n in nodes)
        if len(nodes) > 1:
            # Preserve all regions in DOM order instead of silently dropping a parallel region.
            joined = html.Element('article')
            for node in nodes: joined.append(copy.deepcopy(node))
            return joined, template, candidates, flags, root
        if template != 'conmain':
            return root, template, candidates, flags, root
        total = len(compact(node_text(root)))
        qualifying = []
        substantial = []
        for node in root.iterdescendants():
            if node.tag not in ('div', 'section', 'article'):
                continue
            size = len(compact(node_text(node)))
            coverage = size / max(1, total)
            ratio = link_ratio(node)
            evidence = {'path': descriptor(node), 'chars': size,
                        'coverage': round(coverage, 5), 'link_ratio': round(ratio, 5)}
            candidates.append(evidence)
            if size >= 40 and ratio < .3 and coverage >= .25:
                substantial.append(node)
            if size >= 40 and coverage >= .72 and ratio < .3:
                qualifying.append(node)
        # Parallel significant regions warrant review even if their common parent qualifies.
        if any(a is not b and a not in b.iterancestors() and b not in a.iterancestors()
               for i, a in enumerate(substantial) for b in substantial[i + 1:]):
            flags.append('AMBIGUOUS_BODY_REVIEW')
            return root, template, candidates, flags, root
        if qualifying:
            selected = min(qualifying, key=lambda n: (len(compact(node_text(n))), -len(list(n.iterancestors()))))
            return selected, template, candidates, flags, root
        flags.append('CONMAIN_BODY_UNSEPARATED_REVIEW')
        return root, template, candidates, flags, root
    flags.append('UNKNOWN_LAYOUT_REVIEW')
    root = tree.find('body')
    if root is None: root = tree
    return root, 'unknown', candidates, flags, root


DATE = re.compile(r'(?<!\d)(?:19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?')


def metadata(tree, body, template, container):
    html_title = ''.join(tree.xpath('//title/text()')).strip()
    heading, context, method = '', '', 'not_found'
    if template == 'detailc':
        detail = next((n for n in container.iterancestors() if has_class(n, 'detail')), None)
        if detail is not None:
            headings = detail.xpath('.//h1|.//h2')
            heading = node_text(headings[0]) if headings else ''
            context = '\n'.join(node_text(n) for n in detail.iterdescendants() if has_class(n, 'detailb'))
            method = 'detail_heading_and_detailb'
    elif template == 'conmain':
        headings = container.xpath('.//h1|.//h2')
        # Only preceding heading and metadata, never dates anywhere in the article.
        if headings:
            preceding = [h for h in headings if h is not body and body not in h.iterancestors()]
            heading = node_text(preceding[0]) if preceding else ''
        pieces = []
        for event, node in etree.iterwalk(container, events=('start',)):
            if node is body: break
            if node.tag in ('h1', 'h2', 'p', 'span', 'time') and body not in node.iterdescendants():
                pieces.append(''.join(node.itertext()).strip())
        context = '\n'.join(dict.fromkeys(p for p in pieces if p))[:3000]
        method = 'conmain_pre_body_metadata'
    elif template == 'endtext':
        headings = tree.xpath('//*[@id="h1title"]')
        if not headings:
            headings = body.xpath('preceding::h1[1]')
        heading = node_text(headings[0]) if headings else ''
        # Comments and processing instructions are not metadata elements. Filter
        # before taking the window so they cannot hide the actual date/source.
        before = [n for n in body.itersiblings(preceding=True)
                  if isinstance(n.tag, str)][:4]
        context = '\n'.join(node_text(n) for n in reversed(before) if len(node_text(n)) < 1000)
        method = 'endtext_adjacent_metadata'
    dates = list(dict.fromkeys(DATE.findall(context)))
    source = re.search(r'(?:来源|稿源)\s*[：:]\s*([^\n|]{1,100})', context)
    return {'html_title': html_title, 'heading_title': heading, 'title': heading or html_title,
            'date_candidates': dates, 'date_context': context, 'metadata_method': method,
            'source_name': source.group(1).strip() if source else None,
            'published_at': dates[0] if len(dates) == 1 else None}


def deduplicate_intro(text, title=''):
    """Only remove a labelled truncated synopsis with a verified later anchor."""
    normalized, positions = [], []
    for i, character in enumerate(text):
        if not character.isspace():
            normalized.append(character)
            positions.append(i)
    normalized = ''.join(normalized)
    label = re.search(r'核心提示[：:]?', normalized[:300])
    if not label:
        return text, []
    start = label.end()
    if compact(title) and normalized.startswith(compact(title), start):
        start += len(compact(title))
    cut = re.search(r'……|\.{3,}', normalized[start:])
    if not cut:
        return text, []
    end = start + cut.end()
    synopsis = normalized[start:start + cut.start()]
    if len(synopsis) < 20:
        return text, []
    # A prefix of at least 20 characters must reappear after the truncation marker.
    anchor = synopsis[:min(30, len(synopsis))]
    found = normalized.find(anchor, end)
    if found < 0:
        return text, []
    start_pos, end_pos = positions[label.start()], positions[end - 1] + 1
    removed = text[start_pos:end_pos]
    return (text[:start_pos] + text[end_pos:]).strip(), [
        {'action': 'remove_verified_duplicate_synopsis', 'removed': removed,
         'anchor': anchor, 'later_anchor_offset_compact': found}]


def review_text(text, tree, encoding):
    parser, source, evidence = [], [], []
    def flag(name, snippet, paragraph=None, group='parser'):
        (parser if group == 'parser' else source).append(name)
        evidence.append({'group': group, 'flag': name, 'paragraph': paragraph, 'snippet': snippet[:500]})
    if len(compact(text)) < 200:
        flag('SHORT_TEXT_REVIEW', text)
    if encoding['encoding_uncertain']:
        flag('ENCODING_UNCERTAIN_REVIEW', text[:300])
    numbers, content_types = [], []
    for i, line in enumerate(text.splitlines(), 1):
        pua = sum('\ue000' <= c <= '\uf8ff' for c in line)
        strong = ('\ufffd' in line or bool(re.search(r'(?:Ã.|Â.|â€|ä¸|æ–|å­){3,}|\?/[A-Za-z]+>', line)))
        if strong or (pua >= 2 and re.search(r'\?/[A-Za-z]+>|[ÃÂ]', line)):
            flag('CORRUPT_TEXT_REVIEW', line, i)
        elif pua:
            flag('PUA_FORMATTING_REVIEW', line, i)
        if re.fullmatch(r'\s*(?:手机查看|扫描二维码|立即咨询|免费提问|上一篇|下一篇|精彩推荐|最新文章排行|月排行|总排行)\s*', line):
            flag('REMAINING_UI_NOISE_REVIEW', line, i)
        if re.fullmatch(r'https?://\S+', line):
            content_types.append({'paragraph': i, 'type': 'url'})
        elif re.search(r'\b(?:abstract|keywords|references)\b', line, re.I):
            content_types.append({'paragraph': i, 'type': 'english_scientific'})
        elif re.search(r'\d.*(?:mg|kg|ml|kcal|g/L|mmol|c\.\d|p\.[A-Z])', line, re.I):
            content_types.append({'paragraph': i, 'type': 'numeric_or_gene'})
        # Low CJK alone deliberately produces no encoding flag.
        number = re.match(r'^\s*(?:[^（(\d]{0,30})[（(]([一二三四五六七八九十]+)[）)]|^\s*[（(]?(\d{1,3})[、.．）)]', line)
        if number:
            chinese = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
            val = int(number.group(2)) if number.group(2) else chinese.get(number.group(1))
            if val is not None: numbers.append((val, i, line))
    for left, right in zip(numbers, numbers[1:]):
        if right[0] < left[0]:
            flag('DESCENDING_NUMBERING_REVIEW', left[2] + '\n' + right[2], right[1])
    repeats = Counter(compact(p) for p in text.splitlines() if len(compact(p)) >= 20)
    for paragraph, count in repeats.items():
        if count > 1: flag('REPEATED_PARAGRAPH_REVIEW', paragraph)
    if re.search(r'(?:\.{6,}|…{2,})\s*$', text):
        flag('POSSIBLY_TRUNCATED_REVIEW', text[-300:])
    for name, pattern in (
        ('PROMOTIONAL_CLAIM_REVIEW', r'根治|包治|无副作用|百分之百|100%\s*(?:治愈|有效)'),
        ('PERSONAL_EXPERIENCE_REVIEW', r'亲身经历|我的经历|楼主|网友'),
    ):
        match = re.search(pattern, text)
        if match: flag(name, text[max(0, match.start()-60):match.end()+100], group='source')
    return sorted(set(parser)), sorted(set(source)), evidence, content_types


def extract(body, url, content_type='text/html'):
    decoded, encoding = decode_bytes(body, content_type)
    # Decoding has already selected the encoding. Strip only the leading XML
    # declaration that lxml rejects on Unicode input; keep Unicode HTML parsing
    # so the original declaration cannot trigger a second, incorrect decode.
    parse_input = re.sub(r'\A(\ufeff?\s*)<\?xml\s[^?]*\?>', r'\1', decoded, count=1, flags=re.I)
    tree = html.fromstring(parse_input)
    node, template, candidates, flags, container = choose_body(tree)
    before = node_text(node)
    fallback = None
    if template == 'unknown':
        import trafilatura
        fallback = trafilatura.extract(decoded, url=url, include_tables=False, include_comments=False)
        if fallback: before = fallback
    info = metadata(tree, node, template, container)
    text, actions = deduplicate_intro(before, info['title'])
    parser, source, evidence, types = review_text(text, tree, encoding)
    flags += parser
    if not info['heading_title']: flags.append('TITLE_HEADING_MISSING_REVIEW')
    if len(info['date_candidates']) > 1: flags.append('AMBIGUOUS_DATE_REVIEW')
    if len(compact(text)) < .6 * max(1, len(compact(before))):
        flags.append('LARGE_CLEANING_REVIEW')
    author_nodes = tree.xpath('//meta[translate(@name,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz")="author"]/@content')
    if not author_nodes:
        source.append('AUTHOR_UNAVAILABLE_REVIEW')
        evidence.append({'group':'source','flag':'AUTHOR_UNAVAILABLE_REVIEW',
                         'snippet':'No explicit author meta tag found; author attribution remains unverified.'})
    # Heading/body lexical overlap is only an evidence-backed review heuristic.
    terms = set(re.findall(r'[\u3400-\u9fff]{2,}|[A-Za-z]{4,}', info['heading_title']))
    if terms and len(compact(text)) >= 200 and not any(t in text for t in terms):
        source.append('TITLE_BODY_ALIGNMENT_REVIEW')
        evidence.append({'group':'source','flag':'TITLE_BODY_ALIGNMENT_REVIEW',
                         'snippet':text[:300], 'title_terms':sorted(terms)})
    tables = [html.tostring(t, encoding='unicode') for t in node.iter('table')]
    pagination = [{'text': ''.join(a.itertext()).strip(), 'href': a.get('href')}
                  for a in tree.iter('a') if re.fullmatch(r'\s*(?:下一页|下页|阅读全文|继续阅读)\s*', ''.join(a.itertext()))]
    if pagination: flags.append('PAGINATION_REVIEW')
    flags = sorted(set(flags))
    result = {'extractor': EXTRACTOR, 'cnkang_parser_version': VERSION, **encoding, **info,
            'text': text, 'text_before': before, 'text_sha256': sha(text),
            'chars_before': len(compact(before)), 'chars_after': len(compact(text)),
            'cleaning_actions': actions, 'parser_flags': flags, 'source_flags': sorted(set(source)),
            'flag_evidence': evidence, 'content_types': types, 'tables': tables,
            'selector': descriptor(node) if node.getparent() is not None else 'combined_regions',
            'template': template, 'body_candidates': candidates,
            'pagination_candidates': pagination, 'author': author_nodes[0] if author_nodes else None,
            'quality_status': 'rejected' if not text.strip() else 'review' if flags else 'accepted',
            'quality_flags': flags, 'char_count': len(text)}
    if set(flags) & {'UNKNOWN_LAYOUT_REVIEW','AMBIGUOUS_BODY_REVIEW','TITLE_HEADING_MISSING_REVIEW'}:
        result['domain_parser_fallback'] = True
    return result


def audit(body, url, record, content_type='text/html'):
    doc = extract(body, url, content_type)
    for key in ('text', 'text_before', 'selected_encoding', 'selector', 'template', 'cleaning_actions',
                'date_candidates', 'tables', 'body_candidates', 'source_flags'):
        if record.get(key) != doc.get(key):
            raise ValueError('cnkang raw re-extraction mismatch: ' + key)
    # Cross-document duplicate flags are added by aggregation, not the per-page parser.
    if sorted(set(record.get('parser_flags', [])) - {'DUPLICATE_DOCUMENT_REVIEW'}) != doc['parser_flags']:
        raise ValueError('cnkang parser flags mismatch')
    return {'cnkang_raw_reextraction_verified': True}
