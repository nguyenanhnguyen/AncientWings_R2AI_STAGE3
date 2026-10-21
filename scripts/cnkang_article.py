"""Verified page chains and deterministic full-article reconstruction/audit."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

VERSION = 'cnkang-article-4'


class PaginationError(ValueError):
    pass


def identity(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower().removeprefix('www.')
    try:
        safe = (host == 'cnkang.com' or host.endswith('.cnkang.com')) and p.port in (None, 80, 443)
    except ValueError:
        safe = False
    match = re.fullmatch(r'(.*/[0-9]+)(?:_([1-9][0-9]*))?\.html', p.path)
    if not safe or p.scheme not in ('http', 'https') or p.username or p.password or p.query or not match:
        raise PaginationError('unsafe_or_unknown_page_url')
    return host, match.group(1), int(match.group(2) or 1)


def key(url):
    host, path, index = identity(url)
    return host + path + (f'_{index}' if index > 1 else '') + '.html'


def cache_key(url):
    # Unsupported source URLs may be retained as a single reviewed page. They
    # never establish a chain or share a cache entry with a supported article.
    try:
        return key(url)
    except PaginationError:
        return 'unsupported:' + url


def next_page(doc, current, first):
    origin = identity(first)
    here = identity(current)
    if here[:2] != origin[:2]:
        raise PaginationError('page_identity_mismatch')
    proof = doc.get('pagination_navigation', {})
    if doc.get('template') == 'unknown':
        raise PaginationError('unknown_layout')
    if not doc.get('text', '').strip():
        raise PaginationError('empty_page_body')
    if proof.get('unverified_next'):
        raise PaginationError('unverified_next_link')
    targets, expected, previous = set(), here[2], []
    for container in proof.get('containers', []):
        for link in container['links']:
            target = urljoin(current, link.get('href') or '')
            target_id = identity(target)
            if target_id[:2] != origin[:2]:
                raise PaginationError('foreign_pager_link')
            if link['kind'] == 'number' and int(link['label'].strip('[]')) != target_id[2]:
                raise PaginationError('pager_number_mismatch')
            expected = max(expected, target_id[2])
            if link['kind'] == 'next':
                if target_id[2] != here[2] + 1:
                    raise PaginationError('next_page_jump_or_loop')
                p = urlsplit(target)
                targets.add(urlunsplit(('https', p.netloc, p.path, '', '')))
            elif link['kind'] == 'previous':
                previous.append(target_id[2])
    if any(index != here[2] - 1 for index in previous):
        raise PaginationError('previous_page_mismatch')
    if len({key(t) for t in targets}) > 1:
        raise PaginationError('ambiguous_next_page')
    if not targets and expected > here[2]:
        raise PaginationError('missing_next_link')
    if doc.get('pagination_candidates') and not targets:
        raise PaginationError('unverified_next_link')
    return (sorted(targets)[0] if targets else None), expected


def title(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFC', value or ''))


def dates(values):
    result = []
    for value in values:
        match = re.fullmatch(r'(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(.*)', value)
        result.append(('-'.join(str(int(n)) for n in match.groups()[:3]) + match.group(4))
                      if match else value)
    return sorted(result)


def compatible(first, following, seen):
    if not title(first.get('heading_title')) or title(first['heading_title']) != title(following.get('heading_title')):
        raise PaginationError('page_title_mismatch')
    if first['template'] == 'unknown' or first['template'] != following['template']:
        raise PaginationError('page_template_mismatch')
    dated = next((p for p in seen if p.get('date_candidates')), None)
    if dated is not None and following.get('date_candidates'):
        if dates(dated['date_candidates']) != dates(following['date_candidates']):
            raise PaginationError('page_date_mismatch')
    compact = lambda text: re.sub(r'\s+', '', text or '')
    if not compact(following.get('text')):
        raise PaginationError('empty_page_body')
    if compact(following['text']) in {compact(p['text']) for p in seen}:
        raise PaginationError('repeated_page_body')


def stitch(texts):
    merged, proof = [], []
    for index, text in enumerate(texts, 1):
        lines = text.splitlines()
        count = 0
        if merged:
            for size in range(1, min(len(lines), len(merged)) + 1):
                if merged[-size:] == lines[:size] and len(''.join(lines[:size]).strip()) >= 20:
                    count = size
        if count == len(lines) and lines:
            raise PaginationError('overlap_consumes_whole_page')
        proof.append({'page': index, 'paragraphs': count, 'removed': '\n'.join(lines[:count])})
        merged.extend(lines[count:])
    return '\n'.join(merged), proof


def assemble(parser, pages, complete, reason):
    if not pages:
        raise PaginationError('missing_first_page')
    result = dict(pages[0])
    text, overlaps = stitch([p['text'] for p in pages])
    before, before_overlaps = stitch([p['text_before'] for p in pages])
    paragraphs = []
    verified = all(p['qc_structure']['state'] == 'verified' for p in pages)
    for page_index,(page,overlap) in enumerate(zip(pages,overlaps),1):
        for item in page['qc_structure']['paragraphs'][overlap['paragraphs']:]:
            item = dict(item, article_page=page_index, paragraph=len(paragraphs)+1)
            if item.get('list_path'): item['list_path'] = f"page{page_index}:" + item['list_path']
            paragraphs.append(item)
    structure = parser.structural_qc(text, {'state':'verified' if verified else 'unverified',
                                            'paragraphs':paragraphs})
    flags, source, evidence, types = parser.review_text(text, None, {
        'encoding_uncertain': any(p['encoding_uncertain'] for p in pages)}, structure=structure)
    retained = {f for p in pages for f in p['parser_flags']} - {
        'SHORT_TEXT_REVIEW', 'PAGINATION_REVIEW',
        'DESCENDING_NUMBERING_REVIEW', 'REPEATED_PARAGRAPH_REVIEW'}
    if not complete:
        retained |= {'ARTICLE_INCOMPLETE_REVIEW', 'PAGINATION_REVIEW'}
    flags = sorted(retained | set(flags))
    actions = [dict(action, article_page=index) for index, p in enumerate(pages, 1)
               for action in p['cleaning_actions']]
    if any(o['paragraphs'] for o in overlaps):
        actions.append({'action': 'remove_exact_page_overlap', 'pages': overlaps})
    result.update(text=text, text_before=before, text_sha256=parser.sha(text),
        chars_before=len(parser.compact(before)), chars_after=len(parser.compact(text)), char_count=len(text),
        cleaning_actions=actions, tables=[table for p in pages for table in p['tables']],
        parser_flags=flags, quality_flags=flags,
        quality_status='rejected' if not text.strip() else 'review' if flags else 'accepted',
        source_flags=sorted(set(source)),
        flag_evidence=[dict(e, article_page=index) for index, p in enumerate(pages, 1)
                       for e in p['flag_evidence']] + evidence,
        content_types=types, article_complete=complete, article_page_count=len(pages),
        article_reason=reason, article_schema=VERSION,
        qc_structure=structure,
        article_encodings=[p['selected_encoding'] for p in pages],
        article_glyph_normalizations=[p['glyph_normalization'] for p in pages],
        article_encoding_resolutions=[p['encoding_resolution'] for p in pages],
        article_overlaps=overlaps, article_before_overlaps=before_overlaps)
    result['attributions'] = [dict(a, article_page=i) for i,p in enumerate(pages,1)
                              for a in p.get('attributions',[])]
    result['metadata_conflicts'] = [
        {'field':'author', 'article_page':i, 'first':pages[0]['author'], 'following':p['author']}
        for i,p in enumerate(pages[1:],2)
        if p.get('author') and pages[0].get('author') and p['author'] != pages[0]['author']]
    result['article_source_evidence'] = [
        {field:p[field] for field in parser.SOURCE.FIELDS} for p in pages]
    return parser.SOURCE.apply(result)


def safe_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Article evidence outside run')
    return path


def reconstruct(parser, manifest, root):
    if manifest.get('version') != VERSION or not manifest.get('parts'):
        raise ValueError('Invalid article manifest')
    pages, next_url = [], manifest['root_url']
    try:
        first_index = identity(manifest['root_url'])[2]
        unsupported = False
    except PaginationError:
        first_index, unsupported = 1, True
        if (len(manifest['parts']) != 1 or manifest['complete'] or manifest.get('rejected')
                or manifest['reason'] != 'unsafe_or_unknown_page_url'):
            raise ValueError('Unsupported source cannot establish an article chain')
    expected_count = first_index
    for offset, part in enumerate(manifest['parts']):
        index = first_index + offset
        if next_url is None or cache_key(part['requested_url']) != cache_key(next_url):
            raise ValueError('Article page sequence mismatch')
        if cache_key(part['url']) != cache_key(part['requested_url']):
            raise ValueError('Article redirect identity mismatch')
        if (not unsupported and identity(part['url'])[2] != index) or part['index'] != index:
            raise ValueError('Article page index mismatch')
        raw = gzip.decompress(safe_path(root, part['raw_path']).read_bytes())
        if parser.sha(raw) != part['raw_sha256']:
            raise ValueError('Article raw hash mismatch')
        if safe_path(root, part['raw_html_path']).read_bytes() != raw:
            raise ValueError('Article HTML/gzip mismatch')
        checkpoint = safe_path(root, part['checkpoint_path']).read_bytes()
        if parser.sha(checkpoint) != part['checkpoint_sha256']:
            raise ValueError('Article page checkpoint hash mismatch')
        saved = json.loads(checkpoint)
        if (cache_key(saved.get('final_url', '')) != cache_key(part['url'])
                or cache_key(saved.get('source_url', '')) != cache_key(part['requested_url'])
                or saved.get('raw_sha256') != part['raw_sha256']):
            raise ValueError('Article page checkpoint identity mismatch')
        parser.audit(raw, part['url'], saved, part['content_type'])
        doc = parser.extract(raw, part['url'], part['content_type'])
        if doc['text_sha256'] != part['text_sha256']:
            raise ValueError('Article page text hash mismatch')
        if pages:
            compatible(pages[0], doc, pages)
        pages.append(doc)
        try:
            next_url, count = next_page(doc, part['url'], manifest['root_url'])
            expected_count = max(expected_count, count)
        except PaginationError as exc:
            next_url = None
            if offset != len(manifest['parts']) - 1 or manifest['complete'] or manifest['reason'] != str(exc):
                raise ValueError('Invalid article pager proof') from exc
    complete = next_url is None and first_index == 1 and len(pages) >= expected_count
    if manifest['reason'] != 'complete':
        complete = False
    if manifest['complete'] != complete or manifest.get('next_url') != next_url:
        raise ValueError('Article completeness/next mismatch')
    if manifest['complete'] and (manifest['reason'] != 'complete' or first_index != 1 or manifest.get('rejected')):
        raise ValueError('Invalid complete article')
    if manifest['complete'] and identity(manifest['source_url']) != identity(manifest['root_url']):
        raise ValueError('Complete article source/redirect identity mismatch')
    if len(manifest.get('rejected', [])) > 1:
        raise ValueError('Unexpected rejected article pages')
    for rejected in manifest.get('rejected', []):
        if next_url is None or key(rejected['requested_url']) != key(next_url):
            raise ValueError('Rejected page is outside the verified chain')
        data = safe_path(root, rejected['checkpoint_path']).read_bytes()
        if parser.sha(data) != rejected['checkpoint_sha256']:
            raise ValueError('Rejected page checkpoint hash mismatch')
        saved = json.loads(data)
        if key(saved['source_url']) != key(next_url):
            raise ValueError('Rejected page request identity mismatch')
        raw = None
        if saved.get('raw_path'):
            raw = gzip.decompress(safe_path(root, saved['raw_path']).read_bytes())
            if parser.sha(raw) != saved['raw_sha256']:
                raise ValueError('Rejected page raw hash mismatch')
            if saved.get('raw_html_path') and safe_path(root, saved['raw_html_path']).read_bytes() != raw:
                raise ValueError('Rejected page HTML/gzip mismatch')
        if saved.get('status') == 'extracted':
            parser.audit(raw, saved['final_url'], saved, saved['content_type'])
            doc = parser.extract(raw, saved['final_url'], saved['content_type'])
            try:
                if identity(saved['final_url']) != identity(next_url):
                    raise PaginationError('page_redirect_identity_mismatch')
                compatible(pages[0], doc, pages)
                stitch([p['text'] for p in pages] + [doc['text']])
            except PaginationError as exc:
                if manifest['reason'] != str(exc):
                    raise ValueError('Rejected page reason mismatch') from exc
            else:
                raise ValueError('Unsubstantiated rejected page')
        elif manifest['reason'] != 'page_fetch_failed':
            raise ValueError('Rejected fetch reason mismatch')
    return assemble(parser, pages, complete, manifest['reason']), pages


def audit(parser, body, url, record, root):
    if root is None:
        raise ValueError('Full article audit requires the run directory and all raw pages')
    data = safe_path(root, record['article_manifest_path']).read_bytes()
    if parser.sha(data) != record['article_manifest_sha256']:
        raise ValueError('Article manifest hash mismatch')
    manifest = json.loads(data)
    if (manifest['source_id'], manifest['source_url']) != (record['id'], record['source_url']):
        raise ValueError('Article source identity mismatch')
    if parser.sha(body) != manifest['parts'][0]['raw_sha256'] or cache_key(url) != cache_key(manifest['parts'][0]['url']):
        raise ValueError('Article first raw mismatch')
    result, pages = reconstruct(parser, manifest, root)
    for field in ('text', 'text_before', 'text_sha256', 'char_count', 'chars_before', 'chars_after',
                  'cleaning_actions', 'tables', 'source_flags', 'article_complete', 'article_page_count',
                  'article_reason', 'article_schema', 'article_encodings', 'article_overlaps',
                  'article_before_overlaps', 'cnkang_parser_version', 'selected_encoding', 'selector',
                  'template', 'date_candidates', 'heading_title', 'html_title', 'source_dom_text',
                  'source_dom_text_sha256', 'formattext_evidence', 'pager_removals', 'quality_flags', 'qc_structure',
                  'layout_evidence', 'glyph_normalization', 'encoding_uncertain',
                  'encoding_uncertain_before_q2', 'encoding_resolution', 'encoding_uncertainty_reasons',
                  'encoding_candidates', 'encoding_selection', 'declared_encoding', 'metadata_method',
                  'article_glyph_normalizations', 'article_encoding_resolutions',
                  'attributions', 'author', 'published_at', 'source_name', 'metadata_version',
                  'metadata_conflicts', 'article_source_evidence') + parser.SOURCE.FIELDS:
        if record.get(field) != result.get(field):
            raise ValueError('Article reconstruction mismatch: ' + field)
    parser.SOURCE.audit_publication(record)
    if sorted(set(record['parser_flags']) - {'DUPLICATE_DOCUMENT_REVIEW'}) != result['parser_flags']:
        raise ValueError('Article parser flags mismatch')
    if record.get('quality_status') != result['quality_status']:
        raise ValueError('Article quality/completeness gate mismatch')
    if manifest.get('overlaps') != result['article_overlaps'] or manifest.get('before_overlaps') != result['article_before_overlaps']:
        raise ValueError('Article overlap proof mismatch')
    return {'cnkang_raw_reextraction_verified': True, 'cnkang_article_verified': True,
            'cnkang_article_pages_verified': len(pages), 'cnkang_article_complete': result['article_complete']}


def required(doc, url):
    navigation = doc.get('pagination_navigation', {})
    indicated = bool(doc.get('pagination_candidates') or navigation.get('containers')
                     or navigation.get('unverified_next'))
    try:
        return indicated or identity(url)[2] != 1
    except PaginationError:
        return indicated


def cache_sample(parser, url):
    return {'id': parser.sha(cache_key(url)), 'ids': [], 'url': url, 'source_url': url,
            'canonical_url': cache_key(url), 'article_member': True}


def checkpoint_evidence(parser, out, requested, storage):
    path = Path('cnkang_pages') / (parser.sha(cache_key(requested)) + '.json')
    data = (out / path).read_bytes()
    immutable = Path('cnkang_pages/evidence') / (parser.sha(cache_key(requested)) + '_' + parser.sha(data) + '.json')
    if not (out / immutable).exists(): storage.write_bytes(out / immutable, data)
    return {'requested_url': requested, 'checkpoint_path': immutable.as_posix(),
            'checkpoint_sha256': parser.sha(data)}


def part(parser, out, record, requested, storage):
    try:
        index = identity(requested)[2]
    except PaginationError:
        index = 1
    return {'index': index, 'requested_url': requested,
            'url': record['final_url'], **checkpoint_evidence(parser, out, requested, storage),
            **{k: record[k] for k in ('raw_path', 'raw_html_path', 'raw_sha256', 'content_type', 'text_sha256')}}


def complete(transport, record, sample, record_dir):
    parser, storage, out = transport.parser, transport.storage, transport.out
    first_url = record['final_url']
    page_sample = cache_sample(parser, first_url)
    first = dict(record, **{k: v for k, v in page_sample.items() if k != 'article_member'})
    first['article_member'] = True
    page_path = Path('cnkang_pages') / f"{page_sample['id']}.json"
    storage.write_json(out / page_path, first)
    pages, parts, rejected = [first], [part(parser, out, first, first_url, storage)], []
    attempted = [first]
    manifest_key = parser.sha(str(sample['id']) + ':' + sample['url'])
    manifest_path = Path('cnkang_articles') / (manifest_key + '.progress.json')
    manifest = {'version': VERSION, 'source_id': sample['id'],
                'source_url': sample.get('source_url') or sample['url'], 'root_url': first_url,
                'parts': parts, 'rejected': rejected, 'complete': False, 'reason': 'in_progress', 'next_url': None}
    expected_total, reason, next_url = parts[0]['index'], 'in_progress', None
    while True:
        try:
            next_url, total = next_page(pages[-1], pages[-1]['final_url'], first_url)
            expected_total = max(expected_total, total)
            if identity(first_url)[2] != 1:
                raise PaginationError('source_is_not_first_page')
            if identity(manifest['source_url']) != identity(first_url):
                raise PaginationError('source_redirect_identity_mismatch')
            if next_url is None:
                reason = 'complete' if len(pages) >= expected_total else 'missing_page_part'
            elif len(pages) >= transport.config['max_pages']:
                reason = 'page_limit'
            elif transport.config.get('postprocess_only'):
                # Cached parts remain usable in offline mode.
                candidate = cache_sample(parser, next_url)
                if transport.cached_record(candidate, 'cnkang_pages') is None:
                    reason = 'offline_missing_page'
            transport.budget('article_page')
        except PaginationError as exc:
            reason = str(exc)
            # Pager failures have no verified next target.
            if reason not in ('source_is_not_first_page', 'source_redirect_identity_mismatch'):
                next_url = None
        except transport.NetworkFailure:
            reason = 'article_deadline'
            transport.stopped, transport.stop_reason = True, reason
        manifest.update(complete=reason == 'complete', reason=reason, next_url=next_url)
        storage.write_json(out / manifest_path, manifest)
        if reason != 'in_progress':
            break
        transport._page_mode = True
        try:
            following = transport.fetch(cache_sample(parser, next_url), record_dir='cnkang_pages')
        finally:
            transport._page_mode = False
        attempted.append(following)
        if following.get('status') != 'extracted':
            reason = 'page_fetch_failed'
            manifest['retryable'] = (following.get('http_status') not in (401, 403)
                                     and not following.get('challenge_detected')
                                     and following.get('error_kind') != 'pagination_redirect_review')
            manifest['failure'] = {k: following[k] for k in
                ('error', 'error_kind', 'error_stage', 'error_causes', 'http_status', 'retry_after_seconds')
                if k in following}
            rejected.append(checkpoint_evidence(parser, out, next_url, storage))
            break
        try:
            if identity(following['final_url']) != identity(next_url):
                raise PaginationError('page_redirect_identity_mismatch')
            compatible(first, following, pages)
            stitch([p['text'] for p in pages] + [following['text']])
        except PaginationError as exc:
            reason = str(exc)
            rejected.append(part(parser, out, following, next_url, storage))
            break
        pages.append(following)
        parts.append(part(parser, out, following, next_url, storage))
        storage.write_json(out / manifest_path, dict(manifest, reason='in_progress'))
    manifest.update(complete=reason == 'complete', reason=reason, next_url=next_url)
    merged = assemble(parser, pages, manifest['complete'], reason)
    manifest['overlaps'] = merged['article_overlaps']
    manifest['before_overlaps'] = merged['article_before_overlaps']
    data = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
    manifest_path = Path('cnkang_articles') / (manifest_key + '_' + parser.sha(data) + '.json')
    storage.write_bytes(out / manifest_path, data)
    merged.update({k: record[k] for k in ('id', 'ids', 'url', 'source_url', 'canonical_url', 'branch',
                                         'started_at') if k in record})
    merged.pop('article_member', None)
    merged.update(article_manifest_path=manifest_path.as_posix(),
                  article_manifest_sha256=parser.sha((out / manifest_path).read_bytes()),
                  crawl_status='parsed' if merged['quality_status'] == 'accepted' else 'needs_review',
                  requests=[e for p in attempted for e in p['requests']],
                  network_requests=[e for p in attempted for e in p.get('network_requests', [])])
    merged['attempts'] = len(merged['requests'])
    if reason in ('article_deadline', 'page_limit', 'offline_missing_page') or (
            reason == 'page_fetch_failed' and manifest.get('retryable')):
        merged['retry_deferred'] = True
    else:
        merged.pop('retry_deferred', None)
    if transport.stopped:
        merged['stop_reason'] = transport.stop_reason
    if manifest.get('failure'):
        merged['article_failure'] = manifest['failure']
    # Reconstruct from raw and page checkpoints before publishing the merged record.
    audit(parser, (out / merged['raw_html_path']).read_bytes(), first_url, merged, out)
    return merged
