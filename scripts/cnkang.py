"""Evidence-preserving cnkang parser ported from the supplied v6 notebook/specification.

Original code is archived under docs/references/cnkang; the 120 raw pages were not supplied.
Source-quality heuristics are review signals, never medical judgements.
"""
from __future__ import annotations

import copy
import hashlib
import html as html_std
import re
from urllib.parse import urlsplit, urljoin

from lxml import html, etree

VERSION = 'cnkang-v6-spec-7'
GLYPH_RULE = 'cnkang-glyph-1'
STRUCTURE_RULE = 'cnkang-structure-1'
EXTRACTOR = 'cnkang_v6_spec_dom'
FORMATTEXT_RULE = 'cnkang-formattext-1'
# Verified source: /images/jkpl.js, fetched 2026-10-20. Runtime ports this
# deterministic rule; it neither downloads nor executes website JavaScript.
FORMATTEXT_JS_SHA256 = '55e84799edcefd67fa1f98addc24e1eed6b803d44824054bad1aa2040b7b674f'


def source_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name('cnkang_source_gate_snapshot.py')
    if not path.exists(): path = Path(__file__).with_name('cnkang_source_gate.py')
    spec = importlib.util.spec_from_file_location('_cnkang_source_' + str(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SOURCE = source_module()


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
            'encoding_candidates': candidates, 'encoding_uncertain': True,
            'encoding_uncertainty_reasons': ['no_strict_decode']}
    best = valid[0]
    ranking_best = best['encoding']
    declared_candidate = next((c for c in valid if c['encoding'] == declared_normal),None)
    preserve_pua = bool(declared_candidate and declared_candidate['pua_ratio']
        and not declared_candidate['mojibake_runs'] and not declared_candidate['replacement_ratio']
        and best['encoding'] != declared_normal
        and best['score'] <= declared_candidate['score'] + 30*declared_candidate['pua_ratio'])
    # Do not silently turn a private scientific glyph into unrelated CJK merely
    # because another strict decoder has a lower PUA penalty.
    if preserve_pua: best = declared_candidate
    reasons = []
    if best['replacement_ratio']: reasons.append('replacement_character')
    if best['mojibake_runs']: reasons.append('mojibake')
    if best['pua_ratio'] > .002: reasons.append('pua_ratio')
    if preserve_pua: reasons.append('declared_pua_candidate_conflict')
    if len(valid) > 1 and best['score'] - valid[1]['score'] < .25:
        if decoded[best['encoding']] != decoded[valid[1]['encoding']]:
            reasons.append('ambiguous_decode')
    return decoded[best['encoding']], {
        'selected_encoding': best['encoding'], 'declared_encoding': declared,
        'encoding_candidates': candidates, 'encoding_uncertain': bool(reasons),
        'encoding_uncertainty_reasons': reasons,
        'encoding_selection':{'rule':'preserve_declared_private_glyphs' if preserve_pua else 'ranked_strict_decodes',
                              'ranking_best':ranking_best,'selected':best['encoding']}}


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


def _text_dom(node):
    node = clean_node(node)
    for element in node.iter():
        if element.tag == 'br':
            element.tail = '\n' + (element.tail or '')
        elif element.tag in ('p', 'div', 'section', 'article', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'blockquote'):
            element.text = '\n' + (element.text or '')
            element.tail = '\n' + (element.tail or '')
        elif element.tag in ('td', 'th'):
            element.tail = '\t' + (element.tail or '')
    return node


def node_text(node):
    """Block separators preserve DOM order; inline link text stays adjacent."""
    node = _text_dom(node)
    text = node.text_content().replace('\r\n', '\n').replace('\xa0', ' ')
    return '\n'.join(re.sub(r'[ \t]+', ' ', line).strip() for line in text.splitlines() if line.strip())


def text_context(node, text, *, trusted=True):
    """Project the exact text renderer back to DOM; never infer missing matches."""
    dom = _text_dom(node)
    chunks = []
    def walk(element):
        if not isinstance(element.tag, str): return
        if element.text: chunks.append((element.text, element))
        for child in element:
            walk(child)
            if child.tail: chunks.append((child.tail, element))
    walk(dom)
    lines, pieces = [], []
    def flush():
        visible = [(s, n) for s, n in pieces if s.strip()]
        value = re.sub(r'[ \t]+', ' ', ''.join(s for s, _ in pieces)).strip()
        if not value: return
        owner = visible[0][1]
        ancestry = [owner, *owner.iterancestors()]
        def nearest(tags):
            return next((n for n in ancestry if n.tag in tags), None)
        block = nearest({'p','li','h1','h2','h3','h4','h5','h6','td','th','div','section','article'})
        listing, cell = nearest({'ol','ul'}), nearest({'td','th'})
        if cell is dom: cell = None  # A selected legacy body TD is a layout wrapper.
        emphasized = all(any(a.tag in ('b','strong') for a in [n, *n.iterancestors()])
                         for _, n in visible)
        lines.append((value, {'path': descriptor(block if block is not None else owner),
            'heading': any(a.tag in ('h1','h2','h3','h4','h5','h6') for a in ancestry),
            'emphasized': emphasized, 'table_cell': descriptor(cell) if cell is not None else None,
            'list_path': descriptor(listing) if listing is not None else None,
            'list_depth': sum(a.tag in ('ol','ul') for a in ancestry),
            'list_reversed': listing is not None and listing.get('reversed') is not None,
            'speaker_label': next((compact(''.join(a.itertext())) for a in
                (block.iter('strong','b') if block is not None else [])
                if compact(value).startswith(compact(''.join(a.itertext()))) and
                0 < len(compact(''.join(a.itertext()))) <= 80), None)}))
    for chunk, owner in chunks:
        parts = chunk.replace('\r\n','\n').replace('\xa0',' ').split('\n')
        for index, part in enumerate(parts):
            if index: flush(); pieces = []
            pieces.append((part, owner))
    flush()
    rendered, final = [v for v,_ in lines], text.splitlines()
    # A deletion can make identical lines match the wrong source occurrence.
    # Require the entire renderer projection; cleaned/unaligned text stays
    # conservative instead of guessing a DOM scope from a partial match.
    aligned = rendered == final
    contexts = [c for _,c in lines] if aligned else [None] * len(final)
    state = 'verified' if trusted and aligned else 'unverified'
    return {'state': state, 'paragraphs': [dict(c or {}, paragraph=i, text_sha256=sha(line))
            for i,(line,c) in enumerate(zip(final,contexts),1)]}


_WIDTH = str.maketrans('０１２３４５６７８９（）．，：', '0123456789().,:')


def _chinese_number(value):
    digits = dict(zip('一二三四五六七八九', range(1,10)))
    if value in digits: return digits[value]
    if value == '十': return 10
    if value.count('十') == 1:
        left, right = value.split('十')
        if (not left or left in digits) and (not right or right in digits):
            return digits.get(left,1)*10 + digits.get(right,0)
    return None


def number_marker(line):
    value = line.translate(_WIDTH).strip()
    match = re.match(r'^([一二三四五六七八九十]+)[、.:]', value)
    if match:
        number = _chinese_number(match[1])
        return {'style':'chinese', 'value':[number], 'end':match.end()} if number else None
    match = re.match(r'^\(([一二三四五六七八九十]+)\)', value)
    if match:
        number = _chinese_number(match[1])
        return {'style':'chinese_paren', 'value':[number], 'end':match.end()} if number else None
    match = re.match(r'^(\d{1,3}(?:\.\d{1,3})+)\.?\s*([^\d.\s].*)$', value)
    if match:
        tail = match[2]
        # Decimal quantities/table cells are not outline labels.
        if (int(match[1].split('.')[0]) == 0 or re.match(
                r'[%±×~～℃°/]|(?:mg|kg|ml|mmol|g/L|cm|mm|[μu]g|mSv|Sv)(?=[^A-Za-z]|$)|'
                r'毫克|微克|克|千克|公斤|毫升|升|厘米|毫米|米|岁|年|个月|小时|分钟|秒|万|亿', tail, re.I)):
            return None
        return {'style':'arabic', 'value':[int(n) for n in match[1].split('.')],
                'end':match.start(2)}
    match = re.match(r'^(\()?(\d{1,3})([)、.])', value)
    if match:
        if match[1] and match[3] != ')': return None
        if match[3] == '.' and value[match.end():match.end()+1].isdigit(): return None
        style = ('arabic_paren' if match[1] else 'arabic_close' if match[3] == ')' else
                 'arabic')
        return {'style':style, 'value':[int(match[2])], 'end':match.end()}
    return None


def structural_qc(text, context=None):
    """QC within demonstrated sections/lists; content is never rewritten."""
    context = context or {'state':'unverified', 'paragraphs':[]}
    verified = context['state'] == 'verified'
    paragraphs = context.get('paragraphs', [])
    if verified and (len(paragraphs) != len(text.splitlines()) or any(
            p.get('text_sha256') != sha(line) for p,line in zip(paragraphs,text.splitlines()))):
        raise ValueError('Structure/text projection mismatch')
    flags, source, evidence, decisions, events, occurrences = [], [], [], [], [], {}
    section, section_label, section_valid, stack, dom_lists = 'root', '', False, [], {}
    def flag(name, snippet, paragraph, **details):
        flags.append(name)
        evidence.append(dict(group='parser', flag=name, paragraph=paragraph, snippet=snippet[:500], **details))
    legacy = []
    for index, line in enumerate(text.splitlines(),1):
        item = paragraphs[index-1] if verified else {}
        token = number_marker(line) if verified else None
        speaker = item.get('speaker_label')
        speaker = bool(speaker and re.search(r'患者|提问|回复|医院|医师|医生|教授', speaker)
                       and re.match(re.escape(speaker) + r'\s*[：:]', line))
        plain_heading = verified and not token and not item.get('table_cell') and (
            item.get('heading') or speaker or
            (len(compact(line)) <= 80 and ((item.get('emphasized') and not re.search(r'[。；;]', line)) or
             (re.search(r'[：:？?]$', line) and not re.search(r'[。；;]', line)) or
             re.fullmatch(r'.{0,30}[【\[].{1,30}[】\]]', line))))
        if plain_heading:
            section_label, section_valid = compact(line), True
            section = 'heading:' + section_label
            stack, dom_lists = [], {}
            decisions.append({'paragraph':index, 'decision':'section_boundary',
                              'path':item.get('path'), 'label':line[:100]})
        if not verified:
            match = re.match(r'^\s*(?:[^（(\d]{0,30})[（(]([一二三四五六七八九十]+)[）)]|^\s*[（(]?(\d{1,3})[、.．）)]', line)
            if match:
                val = int(match[2]) if match[2] else _chinese_number(match[1])
                if val is not None:
                    if legacy and val < legacy[-1][0]:
                        flag('DESCENDING_NUMBERING_REVIEW', legacy[-1][2]+'\n'+line, index,
                             reason='unverified_structure')
                    legacy.append((val,index,line))
        elif token and item.get('table_cell'):
            decisions.append({'paragraph':index, 'decision':'table_value_not_list', 'path':item['table_cell']})
            token = None
        elif token:
            values = token['value']
            short_heading = len(compact(line)) <= 60 and not re.search(r'[。；;!?！？]', line)
            frames = dom_lists.setdefault(item['list_path'], []) if item.get('list_path') else stack
            position = next((i for i in range(len(frames)-1,-1,-1) if frames[i]['style'] == token['style']), None)
            reason = None
            if position is not None:
                previous = frames[position]
                if values < previous['value'] and not item.get('list_reversed'):
                    flag('DESCENDING_NUMBERING_REVIEW', previous['line']+'\n'+line, index,
                         reason='same_list_scope', previous_paragraph=previous['paragraph'],
                         scope=section, marker_style=token['style'])
                if position < len(frames)-1:
                    reason = 'return_to_parent_list'
                del frames[position:]
            elif frames:
                previous = frames[-1]
                if values[0] == 1 and (previous['heading'] or previous['style'] == 'chinese'):
                    reason = 'nested_marker_under_parent'
                elif values < previous['value']:
                    flag('DESCENDING_NUMBERING_REVIEW', previous['line']+'\n'+line, index,
                         reason='unverified_marker_change', previous_paragraph=previous['paragraph'])
            frames.append(dict(token, line=line, paragraph=index, heading=short_heading))
            events.append(dict(token, paragraph=index, scope=section,
                               list_path=item.get('list_path'), path=item.get('path')))
            if reason: decisions.append({'paragraph':index, 'decision':reason})
            # Numbered short headings define repeat contexts, but never reset
            # their own numbering sequence (bold 3 -> bold 2 still fails QC).
            if short_heading:
                section_label, section_valid = compact(line), True
                section = 'item:' + section_label
        if len(compact(line)) >= 20:
            occurrences.setdefault(compact(line), []).append({
                'paragraph':index, 'scope':section, 'scope_verified':section_valid,
                'path':item.get('path'), 'label':section_label})
    lines = [compact(line) for line in text.splitlines()]
    for paragraph, items in occurrences.items():
        if len(items) < 2: continue
        if not re.search(r'[^\W_]', paragraph, re.UNICODE):
            decisions.append({'decision':'repeated_separator', 'paragraphs':[i['paragraph'] for i in items]})
            continue
        following = [lines[i['paragraph']] for i in items
                     if i['paragraph'] < len(lines) and len(lines[i['paragraph']]) >= 20]
        repeated_run = len(following) != len(set(following))
        contextual = (verified and not repeated_run and all(i['scope_verified'] for i in items)
                      and len({i['scope'] for i in items}) == len(items))
        if contextual:
            source.append('CONTEXTUAL_REPETITION_REVIEW')
            evidence.append({'group':'source', 'flag':'CONTEXTUAL_REPETITION_REVIEW',
                             'snippet':paragraph[:500], 'occurrences':items})
            decisions.append({'decision':'repeat_in_distinct_sections', 'occurrences':items})
        else:
            flag('REPEATED_PARAGRAPH_REVIEW', paragraph, items[0]['paragraph'],
                 occurrences=items, reason='repeated_block' if repeated_run else 'same_or_unverified_scope')
    return {'rule':STRUCTURE_RULE, **context, 'numbering':events, 'decisions':decisions,
            'parser_flags':sorted(set(flags)), 'source_flags':sorted(set(source)), 'evidence':evidence}


def link_ratio(node):
    return sum(len(compact(a.text_content())) for a in node.iter('a')) / max(1, len(compact(node_text(node))))


def descriptor(node):
    return node.getroottree().getpath(node)


def _inner_html(node):
    return html_std.escape(node.text or '', quote=False) + ''.join(
        html.tostring(child, encoding='unicode') for child in node)


def restore_formattext(tree, body, template, url):
    """Apply only the verified formatter's DOM operation, without decoding again."""
    calls = [script for script in tree.xpath('//script[not(@src)]')
             if re.search(r'\bformattext\s*\(', script.text or '')]
    numbered = [n for n in tree.iter() if isinstance(n.tag, str)
                and re.fullmatch(r'jbk\d+', n.get('id') or '')]
    relevant = [n for n in body.iter() if isinstance(n.tag, str)
                and re.fullmatch(r'jbk\d+', n.get('id') or '')]
    proof = {'state': 'not_applicable', 'rule': FORMATTEXT_RULE,
             'javascript_sha256': FORMATTEXT_JS_SHA256}
    if not calls and not relevant:
        return proof, [], []

    def blocked(reason):
        return {**proof, 'state': 'unverified', 'reason': reason}, ['FORMATTEXT_UNVERIFIED_REVIEW'], []

    if template != 'endtext' or len(calls) != 1:
        return blocked('Expected one formatter call in a known endText body')
    match = re.fullmatch(r'\s*(?:<!--\s*)?formattext\(\s*(\d+)\s*\)\s*;?\s*(?:-->\s*)?',
                         calls[0].text or '')
    if not match or int(match.group(1)) > 10000 or body not in calls[0].iterancestors():
        return blocked('Unverified formatter expression, count or scope')
    count = int(match.group(1))
    sources = [urljoin(url, src) for src in tree.xpath('//script/@src')]
    known = []
    for source in sources:
        try:
            parts = urlsplit(source)
            valid = (parts.scheme in ('http', 'https')
                     and (parts.hostname or '').lower() in ('cnkang.com', 'www.cnkang.com')
                     and parts.path == '/images/jkpl.js' and not parts.query and not parts.fragment
                     and not parts.username and not parts.password and parts.port in (None, 80, 443))
        except ValueError:
            valid = False
        if valid:
            known.append(source)
    targets = tree.xpath('//*[@id="jkpl"]')
    if not known or len(targets) != 1:
        return blocked('Missing verified script source or unique jkpl target')
    target = targets[0]
    parent = target.getparent()
    if (body not in target.iterancestors() or list(target) or compact(target.text)
            or not relevant or len(relevant) != len(numbered)):
        return blocked('Nonempty target or blocks outside the selected body')
    by_id = {}
    for node in relevant:
        index = int(node.get('id')[3:])
        if index in by_id or index > count or node.getparent() is not parent:
            return blocked('Duplicate, out-of-range or nested jbk block')
        by_id[index] = node
    fragments = {index: _inner_html(node) for index, node in by_id.items()}
    combined = ''.join(fragments[index] for index in sorted(fragments))
    # Construct before mutating the source tree: an ambiguous DOM stays untouched.
    try:
        replacement = html.fragment_fromstring('<div id="cnkang_verified_jkpl">' + combined + '</div>')
    except (etree.ParserError, ValueError):
        return blocked('Cannot reconstruct formatter output')
    proof.update(state='restored', count=count, script_sources=known,
                 target_path=descriptor(target), dom_ids=list(by_id), ordered_ids=sorted(by_id),
                 combined_html_sha256=sha(combined))
    replacement.tail = target.tail
    parent.replace(target, replacement)
    for node in relevant:
        # JS hides the blocks; their tails stay visible. drop_tree retains tails.
        node.drop_tree()
    return proof, [], [{'action': 'restore_verified_formattext', **proof}]


def _article_identity(url):
    parts = urlsplit(url)
    try:
        if (not is_host(url) or parts.scheme not in ('http', 'https') or parts.query
                or parts.username or parts.password or parts.port not in (None, 80, 443)):
            return None
    except ValueError:
        return None
    match = re.fullmatch(r'(.+?)(?:_([1-9]\d*))?\.html', parts.path)
    if not match:
        return None
    return (parts.hostname.lower().removeprefix('www.'), match.group(1))


def remove_verified_pagers(body, url):
    """Remove only demonstrated pager markup whose links stay in this article."""
    actions, flags = [], []
    identity = _article_identity(url)
    for node in list(body.iter('b')):
        label = compact(node.text_content())
        if (not re.fullmatch(r'(?:(?:上一页|下一页)|\[\d+\])+', label)
                or not re.search(r'上一页|下一页', label)):
            continue
        links = list(node.iter('a'))
        targets = [urljoin(url, a.get('href') or '') for a in links]
        safe_tags = all(n.tag in ('a', 'font', 'span') for n in node.iterdescendants())
        if (not identity or not links or not safe_tags or any(not a.get('href') for a in links)
                or any(_article_identity(target) != identity for target in targets)):
            flags.append('PAGER_UNVERIFIED_REVIEW')
            continue
        actions.append({'action': 'remove_verified_pager', 'rule': 'cnkang-pager-1',
                        'path': descriptor(node), 'removed': node.text_content(), 'links': targets})
        node.drop_tree()
    return actions, sorted(set(flags))


def legacy_table_nodes(tree, url):
    """Numeric body class + adjacent header/body tables in one article column."""
    match = re.fullmatch(r'.*/(\d+)(?:_[1-9]\d*)?\.html', urlsplit(url or '').path)
    if not match or not is_host(url): return []
    article_id = match[1]
    title = compact(''.join(tree.xpath('//title/text()')))
    found = []
    nodes = [n for n in tree.iter('td') if has_class(n,'style3')
             and [c for c in (n.get('class') or '').split() if c.isdigit()] == [article_id]]
    if len(nodes) != 1: return []
    for node in nodes:
        table = next((a for a in node.iterancestors() if a.tag == 'table'), None)
        if table is None: continue
        scope = table.getparent()
        if scope is None or scope.tag != 'td': continue
        tables = scope.xpath('./table')
        if len(tables) != 2 or tables[1] is not table: continue
        header = tables[0]
        headings = [h for h in header.xpath('.//th//span') if has_class(h,'style8')
                    and next((a for a in h.iterancestors() if a.tag == 'table'), None) is header]
        metas = [n for n in header.xpath('.//td')
                 if has_class(n,'style4') and len(DATE.findall(node_text(n))) == 1
                 and any(is_host(href) for href in n.xpath('.//a/@href'))]
        if len(headings) != 1 or len(metas) != 1: continue
        heading = compact(node_text(headings[0]))
        same_title = title == heading or (title.startswith(heading) and title.endswith('_中华康网')
                                          and title[len(heading):len(heading)+1] in ('_',',','，'))
        if not heading or not same_title: continue
        found.append({'body':node,'scope':scope,'heading':headings[0],
                      'metadata':metas[0],'article_id':article_id})
    return found


def choose_body(tree, url=None):
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
    legacy = legacy_table_nodes(tree,url)
    if len(legacy) == 1:
        root = legacy[0]['body']
        candidates.append({'path':descriptor(root),'chars':len(compact(node_text(root))),
                           'coverage':1.,'link_ratio':round(link_ratio(root),5)})
        return root, 'legacy_table', candidates, flags, legacy[0]['scope']
    if len(legacy) > 1: flags.append('AMBIGUOUS_BODY_REVIEW')
    flags.append('UNKNOWN_LAYOUT_REVIEW')
    root = tree.find('body')
    if root is None: root = tree
    return root, 'unknown', candidates, flags, root


DATE = re.compile(r'(?<!\d)(?:19|20)\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?')


def metadata(tree, body, template, container):
    html_title = ''.join(tree.xpath('//title/text()')).strip()
    heading, context, method = '', '', 'not_found'
    metadata_nodes = []
    if template == 'detailc':
        detail = next((n for n in container.iterancestors() if has_class(n, 'detail')), None)
        if detail is not None:
            headings = detail.xpath('.//h1|.//h2')
            heading = node_text(headings[0]) if headings else ''
            metadata_nodes = [n for n in detail.iterdescendants() if has_class(n, 'detailb')]
            context = '\n'.join(node_text(n) for n in metadata_nodes)
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
                if node.tag not in ('h1','h2'): metadata_nodes.append(node)
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
        metadata_nodes = [n for n in reversed(before) if len(node_text(n)) < 1000
                          and n.tag not in ('h1','h2')]
        context = '\n'.join(node_text(n) for n in reversed(before) if len(node_text(n)) < 1000)
        method = 'endtext_adjacent_metadata'
    elif template == 'legacy_table':
        table = container.xpath('./table')[0]
        headings = [n for n in table.xpath('.//th//span') if has_class(n,'style8')
                    and next((a for a in n.iterancestors() if a.tag == 'table'),None) is table]
        heading = node_text(headings[0])
        metas = [n for n in table.xpath('.//td')
                 if has_class(n,'style4') and len(DATE.findall(node_text(n))) == 1
                 and any(is_host(href) for href in n.xpath('.//a/@href'))]
        context = node_text(metas[0])
        metadata_nodes = [metas[0]]
        method = 'legacy_table_title_and_pre_body_metadata'
    dates = list(dict.fromkeys(DATE.findall(context)))
    source = re.search(r'(?:来源|稿源)\s*[：:]\s*([^\n|]{1,100})', context)
    attributions = SOURCE.metadata_roles(tree, body, metadata_nodes, trusted=template != 'unknown')
    authors = list(dict.fromkeys(a['name'] for a in attributions if a['role'] == 'article_author'))
    return {'html_title': html_title, 'heading_title': heading, 'title': heading or html_title,
            'date_candidates': dates, 'date_context': context, 'metadata_method': method,
            'source_name': source.group(1).strip() if source else None,
            'published_at': dates[0] if len(dates) == 1 else None,
            'metadata_version': 'cnkang-metadata-1', 'attributions': attributions,
            'author': '; '.join(authors) if authors else None, 'metadata_conflicts': []}


def normalize_glyphs(body, template, title, encoding):
    """Context-bound formatting only. Unknown private glyphs remain visible."""
    node = clean_node(body)
    actions = []
    trusted = template not in ('unknown','combined_known')
    legacy_spacing = (encoding['selected_encoding'] == 'gb18030'
                      and encoding['declared_encoding'] in ('gb2312','gbk','gb18030','x-gbk'))
    paragraphs = list(node.iter('p'))
    quoted = set(re.findall(r'[“「『"]([\u3400-\u9fff])[”」』"]',title))
    labels = {m[1] for p in paragraphs if (m := re.match(r'^\s*([\u3400-\u9fff])\ue5e5',p.text or ''))}
    labelled = trusted and legacy_spacing and len(labels) >= 2 and labels <= quoted
    bullet_groups = {}
    for p in paragraphs:
        if re.match(r'^\s*\uf06c(?=[\u3400-\u9fff])',p.text or ''):
            bullet_groups.setdefault(p.getparent(),[]).append(p)
    bullets = {p for group in bullet_groups.values() if len(group) >= 2 for p in group} if trusted else set()
    for element in node.iter():
        if not isinstance(element.tag,str): continue
        medical_cell = any(a.tag in ('td','th') and a is not node
                           for a in [element,*element.iterancestors()])
        for field in ('text','tail'):
            value = getattr(element,field) or ''
            edits = []
            if trusted and not medical_cell:
                prefix = field == 'text' and element.tag in ('p','li','div')
                prefix |= field == 'tail' and element.tag == 'br'
                indent = re.match(r'^[\s\ue5e5]*',value) if prefix and legacy_spacing else None
                if indent and (indent[0].count('\ue5e5') >= 2 or
                               (indent[0].count('\ue5e5') == 1 and re.search(r'\s',indent[0]))):
                    edits += [(m.start(),' ','paragraph_indent') for m in re.finditer('\ue5e5',indent[0])]
                if labelled and field == 'text' and element.tag == 'p':
                    match = re.match(r'^\s*([\u3400-\u9fff])(\ue5e5)',value)
                    if match and match[1] in labels:
                        edits.append((match.start(2),' ','quoted_section_label_separator'))
                if element in bullets and field == 'text':
                    match = re.match(r'^\s*(\uf06c)',value)
                    edits.append((match.start(1),'• ','parallel_list_bullet'))
            updated = value
            for offset,replacement,reason in sorted(edits,reverse=True):
                actions.append({'action':'normalize_verified_pua','rule':GLYPH_RULE,
                    'path':descriptor(element),'field':field,'offset':offset,
                    'original':value[offset],'replacement':replacement,
                    'codepoint':f'U+{ord(value[offset]):04X}','reason':reason,
                    'context':value[max(0,offset-30):offset+60],
                    'font_style':element.get('style') or element.get('face')})
                updated = updated[:offset]+replacement+updated[offset+1:]
            setattr(element,field,updated)
    unresolved = [{'path':descriptor(n),'field':field,'offset':i,'original':c,
                   'codepoint':f'U+{ord(c):04X}','context':value[max(0,i-30):i+60]}
                  for n in node.iter() if isinstance(n.tag,str)
                  for field in ('text','tail') for value in [getattr(n,field) or '']
                  for i,c in enumerate(value) if '\ue000'<=c<='\uf8ff']
    return node, {'rule':GLYPH_RULE,'actions':actions,'unresolved':unresolved,
        'before_sha256':sha(node_text(body)),'after_sha256':sha(node_text(node))}


def resolve_encoding(encoding, glyphs):
    encoding = dict(encoding)
    original = encoding['encoding_uncertain']
    reasons = encoding['encoding_uncertainty_reasons']
    alias = {'gb2312':'gb18030','gbk':'gb18030','utf8':'utf-8','x-gbk':'gb18030'}
    declared = (encoding['declared_encoding'] or '').lower()
    compatible = alias.get(declared,declared) == encoding['selected_encoding']
    resolved = (original and reasons == ['pua_ratio'] and compatible
                and bool(glyphs['actions']) and not glyphs['unresolved'])
    if resolved: encoding['encoding_uncertain'] = False
    encoding.update(encoding_uncertain_before_q2=original, encoding_resolution={
        'state':'verified_body_formatting' if resolved else 'unresolved' if original else 'not_needed',
        'original_reasons':reasons, 'rule':GLYPH_RULE,
        'normalized_body_glyphs':len(glyphs['actions']),
        'unresolved_body_glyphs':len(glyphs['unresolved'])})
    return encoding


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


def review_text(text, tree, encoding, *, structure=None):
    parser, source, evidence = [], [], []
    def flag(name, snippet, paragraph=None, group='parser'):
        (parser if group == 'parser' else source).append(name)
        evidence.append({'group': group, 'flag': name, 'paragraph': paragraph, 'snippet': snippet[:500]})
    if len(compact(text)) < 200:
        flag('SHORT_TEXT_REVIEW', text)
    if encoding['encoding_uncertain']:
        flag('ENCODING_UNCERTAIN_REVIEW', text[:300])
    content_types = []
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
    structure = structure or structural_qc(text)
    parser += structure['parser_flags']
    source += structure['source_flags']
    evidence += structure['evidence']
    if re.search(r'(?:\.{6,}|…{2,})\s*$', text):
        flag('POSSIBLY_TRUNCATED_REVIEW', text[-300:])
    return sorted(set(parser)), sorted(set(source)), evidence, content_types


def pagination_navigation(tree, body, template, container):
    """Only demonstrated endText bold pagers or pageStyle inside this article."""
    pagers = []
    if template != 'unknown':
        pagers += [n for n in body.iter('b') if re.fullmatch(
            r'(?:(?:上一页|下一页)|\[\d+\])+', compact(n.text_content()))]
        scope = container
        if template == 'detailc':
            scope = next((n for n in body.iterancestors() if has_class(n, 'detail')), body)
        pagers += [n for n in scope.iter() if isinstance(n.tag, str) and has_class(n, 'pageStyle')]
    trusted, proof = set(), []
    for node in pagers:
        links = []
        for a in node.iter('a'):
            label = compact(''.join(a.itertext()))
            kind = ('next' if label in ('下一页', '下页', '阅读全文', '继续阅读') else
                    'previous' if label in ('上一页', '上页') else
                    'number' if re.fullmatch(r'\[?\d+\]?', label) else None)
            if kind:
                trusted.add(a)
                links.append({'kind': kind, 'href': a.get('href'), 'label': label})
        if links:
            proof.append({'path': descriptor(node), 'links': links})
    unverified = [{'href': a.get('href'), 'path': descriptor(a)} for a in tree.iter('a')
                  if compact(''.join(a.itertext())) in ('下一页', '下页', '阅读全文', '继续阅读')
                  and a not in trusted]
    return {'containers': proof, 'unverified_next': unverified}


def extract(body, url, content_type='text/html'):
    decoded, encoding = decode_bytes(body, content_type)
    # Decoding has already selected the encoding. Strip only the leading XML
    # declaration that lxml rejects on Unicode input; keep Unicode HTML parsing
    # so the original declaration cannot trigger a second, incorrect decode.
    parse_input = re.sub(r'\A(\ufeff?\s*)<\?xml\s[^?]*\?>', r'\1', decoded, count=1, flags=re.I)
    tree = html.fromstring(parse_input)
    node, template, candidates, flags, container = choose_body(tree,url)
    layout = {'state':'not_applicable'}
    if template == 'legacy_table':
        matched = legacy_table_nodes(tree,url)[0]
        layout = {'state':'verified','rule':'cnkang-legacy-table-1',
                  'article_id':matched['article_id'],'body_path':descriptor(node),
                  'heading_path':descriptor(matched['heading']),
                  'metadata_path':descriptor(matched['metadata']),
                  'heading':node_text(matched['heading'])}
    source_dom_text = node_text(node)
    # Discover links before removing their presentation from the article text.
    pagination = [{'text': ''.join(a.itertext()).strip(), 'href': a.get('href')}
                  for a in tree.iter('a') if re.fullmatch(r'\s*(?:下一页|下页|阅读全文|继续阅读)\s*', ''.join(a.itertext()))]
    info = metadata(tree, node, template, container)
    navigation = pagination_navigation(tree, node, template, container)
    order, order_flags, normalization = restore_formattext(tree, node, template, url)
    pager_actions, pager_flags = remove_verified_pagers(node, url) if template != 'unknown' else ([], [])
    flags += order_flags + pager_flags
    normalization += pager_actions
    before = node_text(node)
    glyph_node, glyphs = normalize_glyphs(node,template,info['title'],encoding)
    normalized = node_text(glyph_node)
    fallback = None
    if template == 'unknown':
        import trafilatura
        fallback = trafilatura.extract(decoded, url=url, include_tables=False, include_comments=False)
        if fallback: before = normalized = fallback
    text, actions = deduplicate_intro(normalized, info['title'])
    actions = normalization + glyphs['actions'] + actions
    encoding = resolve_encoding(encoding,glyphs)
    structure = structural_qc(text, text_context(glyph_node, text, trusted=template != 'unknown'))
    parser, source, evidence, types = review_text(text, tree, encoding, structure=structure)
    flags += parser
    if not info['heading_title']: flags.append('TITLE_HEADING_MISSING_REVIEW')
    if len(info['date_candidates']) > 1: flags.append('AMBIGUOUS_DATE_REVIEW')
    if len(compact(text)) < .6 * max(1, len(compact(before))):
        flags.append('LARGE_CLEANING_REVIEW')
    tables = [html.tostring(t, encoding='unicode') for t in node.iter('table')]
    if pagination: flags.append('PAGINATION_REVIEW')
    flags = sorted(set(flags))
    result = {'extractor': EXTRACTOR, 'cnkang_parser_version': VERSION, **encoding, **info,
            'text': text, 'text_before': before, 'text_sha256': sha(text),
            'chars_before': len(compact(before)), 'chars_after': len(compact(text)),
            'cleaning_actions': actions, 'parser_flags': flags, 'source_flags': sorted(set(source)),
            'source_dom_text': source_dom_text, 'source_dom_text_sha256': sha(source_dom_text),
            'formattext_evidence': order, 'pager_removals': pager_actions,
            'flag_evidence': evidence, 'content_types': types, 'tables': tables,
            'selector': descriptor(node) if node.getparent() is not None else 'combined_regions',
            'template': template, 'body_candidates': candidates,
            'pagination_candidates': pagination,
            'pagination_navigation': navigation,
            'qc_structure': structure,
            'layout_evidence': layout, 'glyph_normalization': glyphs,
            'quality_status': 'rejected' if not text.strip() else 'review' if flags else 'accepted',
            'quality_flags': flags, 'char_count': len(text)}
    if set(flags) & {'UNKNOWN_LAYOUT_REVIEW','AMBIGUOUS_BODY_REVIEW','TITLE_HEADING_MISSING_REVIEW'}:
        result['domain_parser_fallback'] = True
    return SOURCE.apply(result)


def article_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).with_name('cnkang_article_snapshot.py')
    if not path.exists(): path = Path(__file__).with_name('cnkang_article.py')
    spec = importlib.util.spec_from_file_location('_cnkang_article_' + str(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit(body, url, record, content_type='text/html', *, base_dir=None):
    if record.get('article_manifest_path'):
        return article_module().audit(_parser_api(), body, url, record, base_dir)
    doc = extract(body, url, content_type)
    runtime_record = record.get('engine') == 'requests' and 'id' in record
    if runtime_record:
        article = article_module()
        member = record.get('article_member') is True and record['id'] == sha(article.cache_key(url))
        if article.required(doc, url) and not member:
            raise ValueError('Paginated cnkang runtime record requires a full article manifest')
        if record.get('article_complete') is False and record.get('quality_status') == 'accepted':
            raise ValueError('Incomplete cnkang article cannot be accepted')
    for key in ('text', 'text_before', 'selected_encoding', 'selector', 'template', 'cleaning_actions',
                'date_candidates', 'tables', 'body_candidates', 'source_flags',
                'cnkang_parser_version', 'source_dom_text', 'source_dom_text_sha256',
                'formattext_evidence', 'pager_removals', 'pagination_navigation', 'qc_structure',
                'layout_evidence', 'glyph_normalization', 'encoding_uncertain',
                'encoding_uncertain_before_q2', 'encoding_resolution', 'encoding_uncertainty_reasons',
                'encoding_candidates', 'encoding_selection', 'declared_encoding',
                'heading_title', 'html_title', 'metadata_method'):
        if record.get(key) != doc.get(key):
            raise ValueError('cnkang raw re-extraction mismatch: ' + key)
    for key in ('author','published_at','source_name','attributions','metadata_version','metadata_conflicts'):
        if record.get(key) != doc.get(key):
            raise ValueError('cnkang metadata mismatch: ' + key)
    # Runtime completeness is established separately from the single-page parser.
    source_doc = dict(doc)
    for key in ('article_complete','article_page_count'):
        if key in record: source_doc[key] = record[key]
    expected_source = SOURCE.evaluate(source_doc)
    for key in SOURCE.FIELDS + ('source_flags',):
        if record.get(key) != expected_source[key]:
            raise ValueError('cnkang source re-extraction mismatch: ' + key)
    SOURCE.audit_publication(record)
    # Cross-document duplicate flags are added by aggregation, not the per-page parser.
    if sorted(set(record.get('parser_flags', [])) - {'DUPLICATE_DOCUMENT_REVIEW'}) != doc['parser_flags']:
        raise ValueError('cnkang parser flags mismatch')
    return {'cnkang_raw_reextraction_verified': True}


def _parser_api():
    # Dynamically loaded standalone snapshots need not be registered in sys.modules.
    from types import SimpleNamespace
    return SimpleNamespace(extract=extract, audit=audit, sha=sha, compact=compact,
                           review_text=review_text, structural_qc=structural_qc, SOURCE=SOURCE)
