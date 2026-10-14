"""Long Chau content boundaries and a sequential Chrome-impersonating HTTP route."""
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import urlsplit

from lxml import html

VERSION = 'longchau-v1'
HOSTS = {'nhathuoclongchau.com.vn', 'www.nhathuoclongchau.com.vn'}
ARTICLE_SELECTOR = '[data-theme-element="article"][data-scale-font]'
DISEASE_FIELDS = ('description', 'symptom', 'aetiologies', 'risk', 'diagnoseAndTreaty', 'livingAndPreventive')
DEFAULTS = {'workers': 1, 'delay': 1.75, 'attempts': 3, 'timeout': [10., 45.], 'budget': 180.,
            'impersonate': 'chrome', 'retry_failed_on_resume': True}
BLOCK_TAGS = {'p', 'div', 'section', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'blockquote', 'figcaption', 'dt', 'dd'}


def is_host(url):
    return (urlsplit(url).hostname or '').lower() in HOSTS


def normalize(text):
    text = unicodedata.normalize('NFC', text or '').replace('\r', '\n')
    text = re.sub(r'[\t \u00a0]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(line.strip() for line in text.split('\n'))).strip()


def dom_text(node):
    pieces = []
    def walk(element):
        if not isinstance(element.tag, str): return
        tag = element.tag.lower()
        if tag in {'script', 'style', 'svg', 'iframe', 'noscript', 'form', 'button'}: return
        if tag in BLOCK_TAGS or tag == 'br': pieces.append('\n\n')
        pieces.append(element.text or '')
        for child in element:
            walk(child)
            pieces.append(child.tail or '')
        if tag in {'td', 'th'}: pieces.append(' | ')
        if tag in BLOCK_TAGS or tag == 'br': pieces.append('\n\n')
    walk(node)
    return normalize(''.join(pieces))


def fragment(text):
    return html.fragment_fromstring(text or '<div></div>', create_parent='div')


def path_identity(value):
    if not isinstance(value, str): return None
    parsed = urlsplit(value)
    if parsed.hostname and parsed.hostname.lower() not in HOSTS: return None
    return parsed.path.strip('/')


def current_data(tree, url):
    nodes = tree.xpath('//script[@id="__NEXT_DATA__"]')
    if len(nodes) != 1: return {}, ['longchau_missing_current_json']
    try:
        payload = json.loads(nodes[0].text or '')
        page = payload['props']['pageProps']
        data = page.get('data') if urlsplit(url).path.startswith('/benh/') else page.get('detail', {}).get('data')
        if not isinstance(data, dict): raise ValueError('Current article object missing')
        canonical = tree.xpath('//link[@rel="canonical"]/@href')
        requested = path_identity(url)
        if (not is_host(url) or path_identity(data.get('slug')) != requested
                or len(canonical) != 1 or path_identity(canonical[0]) != requested):
            return {}, ['longchau_identity_mismatch']
        return data, []
    except (KeyError, TypeError, ValueError):
        return {}, ['longchau_invalid_current_json']


def anchor_only(node, labels=()):
    clone = copy.deepcopy(node)
    if not clone.xpath('.//a[@href]'): return False
    for anchor in clone.xpath('.//a'):
        anchor.drop_tree()
    residual = ' '.join(clone.text_content().split()).strip(' :;,.')
    allowed = {label.casefold().strip(' :;,.') for label in labels} if labels else {''}
    return residual.casefold() in allowed


def clean_region(root, metadata):
    """Remove whole identified components/blocks, never words from medical prose."""
    root = copy.deepcopy(root)
    removed, signatures = [], []
    for node in list(root.xpath('.//*[@data-lcpr or @data-component or @class or @id]')):
        attrs = ' '.join(node.get(k, '') for k in ('data-lcpr', 'data-component', 'class', 'id')).lower()
        if any(token in attrs for token in ('article-disclaimer', 'site-disclaimer', 'author-profile',
                                            'related-articles', 'product-recommendations', 'table-of-content')):
            removed.append({'reason': 'component', 'component': attrs, 'text': normalize(node.text_content())})
            node.drop_tree()
    labels = ('Xem thêm', 'Tìm hiểu thêm', 'Xem thêm thông tin', 'Tham khảo thêm')
    for node in list(root.xpath('.//p')):
        text = ' '.join(node.text_content().split())
        if anchor_only(node, labels):
            removed.append({'reason': 'related_links', 'text': text})
            node.drop_tree()
        elif text.rstrip(': ').casefold() in {s.casefold() for s in labels}:
            next_node = node.getnext()
            if next_node is not None and next_node.tag in ('ul', 'ol') and anchor_only(next_node):
                removed.extend([{'reason': 'related_links', 'text': text},
                                {'reason': 'related_links', 'text': normalize(next_node.text_content())}])
                next_node.drop_tree()
                node.drop_tree()
    # Legacy CMS signature: a right-aligned author followed by a right-aligned source note.
    # Right-aligned medical instructions/dates are preserved unless this metadata pair is present.
    for node in list(root.xpath('.//p')):
        if node.getparent() is None: continue
        style = node.get('style', '').replace(' ', '').lower()
        text = normalize(node.text_content())
        if 'text-align:right' in style and text.startswith('Nguồn tham khảo:'):
            prior = node.getprevious()
            name = normalize(prior.text_content()) if prior is not None else ''
            name_words = name.split()
            person_name = (2 <= len(name_words) <= 6 and all(
                word[0].isupper() and all(c.isalpha() or c in "-'’" for c in word) for word in name_words))
            # Title-cased clinical instructions are not signatures. This guard only preserves
            # candidate paragraphs; it never deletes medical words elsewhere in the article.
            if name.casefold().startswith(('không ', 'cấm ', 'cảnh báo', 'chống chỉ định', 'lưu ý')):
                person_name = False
            if (prior is not None and prior.tag == 'p' and 'text-align:right' in prior.get('style', '').replace(' ', '').lower()
                    and prior.xpath('.//strong') and person_name and node.getnext() is None):
                signatures.append(name)
                removed.append({'reason': 'author_signature', 'text': signatures[-1]})
                prior.drop_tree()
            removed.append({'reason': 'reference_metadata', 'text': text})
            node.drop_tree()
    # Shared disclaimer must occupy its own terminal paragraph, not a clinical warning paragraph.
    for node in list(root.xpath('.//p')):
        text = normalize(node.text_content())
        if (text.startswith('Thông tin và sản phẩm gợi ý trong bài viết chỉ mang tính chất tham khảo')
                and node.getnext() is None and len(text) < 1000):
            removed.append({'reason': 'site_disclaimer', 'text': text})
            node.drop_tree()
    for node in root.xpath('.//script|.//style|.//iframe|.//noscript|.//svg|.//button|.//form'):
        node.drop_tree()
    return root, removed, signatures


def blocks(root):
    result = []
    for node in root.iter():
        if not isinstance(node.tag, str): continue
        if node.tag in {'h1','h2','h3','h4','h5','h6','p','li','tr','figcaption','blockquote','dt','dd'}:
            # Count outer table rows/list items only when there is no nested paragraph/block.
            if node.tag in {'li','blockquote'} and node.xpath('.//p|.//li|.//blockquote'): continue
            if node.tag == 'p' and node.xpath('.//figcaption'): continue
            text = dom_text(node)
            if text: result.append({'tag': node.tag, 'text': text})
    return result


def extract(body, url):
    try:
        tree = html.fromstring(body.decode('utf-8', 'strict'))
    except (UnicodeDecodeError, ValueError, html.etree.ParserError):
        return {'title': '', 'text': '', 'extractor': 'longchau_dom_v1',
                'longchau_review_reasons': ['longchau_invalid_utf8_or_html'], 'longchau_parser_version': VERSION}
    headings = tree.xpath('//h1')
    title = normalize(headings[0].text_content()) if len(headings) == 1 else ''
    data, reasons = current_data(tree, url)
    kind = urlsplit(url).path.strip('/').split('/')[0]
    author = (data.get('author') or {}).get('fullName')
    reviewer = (data.get('approver') or {}).get('fullName')
    metadata = {'author': author, 'reviewed_by': reviewer, 'published_at': data.get('publishedAt'),
                'updated_at': data.get('updatedAt'), 'longchau_content_id': data.get('id')}
    regions, removed, signatures, section_keys = [], [], [], []
    intro = fragment(data.get('shortDescription', ''))
    intro_text = dom_text(intro)
    if not title: reasons.append('longchau_missing_or_ambiguous_title')
    if not intro_text: reasons.append('longchau_missing_sapo')
    if kind == 'bai-viet':
        candidates = tree.xpath('//*[@data-theme-element="article" and @data-scale-font]')
        if len(candidates) != 1:
            reasons.append('longchau_article_boundary_ambiguous')
        else:
            root, deleted, signature = clean_region(candidates[0], metadata)
            regions.append(root)
            removed.extend(deleted)
            signatures.extend(signature)
            # Assert this is the current CMS description, not a related/advertising component.
            if not isinstance(data.get('description'), str):
                reasons.append('longchau_description_identity_unverified')
            else:
                cms, _, _ = clean_region(fragment(data['description']), metadata)
                if re.sub(r'\s+', '', dom_text(cms)) != re.sub(r'\s+', '', dom_text(root)):
                    reasons.append('longchau_dom_cms_content_mismatch')
            section_keys.append('description')
        selector = ARTICLE_SELECTOR
        extractor = 'longchau_article_dom_v1'
    elif kind == 'benh':
        selector = '__NEXT_DATA__.props.pageProps.data (slug/canonical verified); medical HTML fields + FAQs'
        extractor = 'longchau_disease_dom_v1'
        for key in DISEASE_FIELDS:
            if key not in data or not isinstance(data[key], (str, type(None))):
                reasons.append('longchau_missing_disease_field_' + key)
                continue
            if not data[key]: continue
            root, deleted, signature = clean_region(fragment(data[key]), metadata)
            # Preserve rendered section h2 labels; CMS fragments contain their h3/h4 and all prose.
            visible_heading = tree.xpath(f'//*[@id="{key}"]//*[@data-theme-element="article"]/h2')
            if len(visible_heading) == 1:
                root.insert(0, copy.deepcopy(visible_heading[0]))
            if key in ('description', 'symptom', 'aetiologies'):
                visible = tree.xpath(f'//*[@id="{key}"]//*[@data-theme-element="article"]')
                if len(visible) != 1:
                    reasons.append('longchau_disease_visible_section_unverified_' + key)
                else:
                    clean_visible, _, _ = clean_region(visible[0], metadata)
                    if re.sub(r'\s+', '', dom_text(root)) != re.sub(r'\s+', '', dom_text(clean_visible)):
                        reasons.append('longchau_disease_dom_cms_mismatch_' + key)
            regions.append(root)
            removed.extend(deleted)
            signatures.extend(signature)
            section_keys.append(key)
        faqs = data.get('faqs', [])
        if not isinstance(faqs, list):
            reasons.append('longchau_invalid_faq_schema')
        else:
            for entry in faqs:
                if not isinstance(entry, dict) or not isinstance(entry.get('question'), str) or not isinstance(entry.get('answer'), str):
                    reasons.append('longchau_invalid_faq_record')
                    continue
                root, deleted, _ = clean_region(fragment(entry['answer']), metadata)
                h3 = html.Element('h3')
                h3.text = entry['question']
                root.insert(0, h3)
                regions.append(root)
                removed.extend(deleted)
                section_keys.append('faq:' + str(entry.get('id', '')))
    else:
        selector, extractor = 'unsupported', 'longchau_unsupported_dom_v1'
        reasons.append('longchau_unsupported_path_template')
    # The sapo is a verified current article field; no author/font control sibling enters the text.
    all_blocks = ([{'tag': 'sapo', 'text': intro_text}] if intro_text else []) + [b for root in regions for b in blocks(root)]
    body_text = normalize('\n\n'.join([intro_text] + [dom_text(root) for root in regions]))
    if not regions or len(body_text) < 150: reasons.append('longchau_missing_article_body')
    if any(b['tag'] == 'h1' and b['text'] == title for b in all_blocks):
        reasons.append('longchau_duplicate_title_in_body')
    text = normalize('\n\n'.join([title, body_text]))
    controls = {'Kích thước chữ', 'Mặc định', 'Lớn hơn'}
    boilerplate = sorted({line.strip() for line in body_text.splitlines() if line.strip() in controls})
    if boilerplate: reasons.append('longchau_boilerplate_detected')
    if not metadata['author'] and signatures:
        metadata['author'] = signatures[0]
    metadata['longchau_signature_authors'] = signatures
    source_heads = [b for b in all_blocks if b['tag'] in {'h2','h3','h4','h5','h6'}]
    missing = [b for b in all_blocks if normalize(b['text']) not in text]
    if missing: reasons.append('longchau_missing_source_blocks')
    return dict(metadata, title=title, text=text, extractor=extractor, declared_encoding='utf-8',
                longchau_parser_version=VERSION, longchau_selector=selector, longchau_template=kind,
                longchau_boilerplate_signals=boilerplate,
                longchau_review_reasons=sorted(set(reasons)), source_body_chars=len(body_text),
                longchau_sapo=intro_text, longchau_section_keys=section_keys,
                source_heading_count=len(source_heads), kept_heading_count=len(source_heads),
                source_block_count=len(all_blocks), kept_block_count=len(all_blocks) - len(missing),
                missing_blocks=len(missing), source_table_count=sum(len(r.xpath('.//table')) for r in regions),
                source_image_count=sum(len(r.xpath('.//img')) for r in regions),
                source_blocks_sha256=hashlib.sha256(json.dumps(all_blocks, ensure_ascii=False).encode()).hexdigest(),
                longchau_removed_blocks=removed, longchau_removed_count=len(removed))


def validate_config(config):
    result = {**DEFAULTS, **config}
    if result['workers'] != 1 or type(result['workers']) is not int:
        raise ValueError('Long Chau runs sequentially with workers=1.')
    if not math.isfinite(result['delay']) or result['delay'] < 1.5:
        raise ValueError('Long Chau delay must be finite and at least 1.5 seconds.')
    if type(result['attempts']) is not int or result['attempts'] < 1:
        raise ValueError('Long Chau attempts must be a positive integer.')
    if len(result['timeout']) != 2 or any(not math.isfinite(v) or v <= 0 for v in (*result['timeout'], result['budget'])):
        raise ValueError('Long Chau timeouts/budget must be finite and positive.')
    if result['impersonate'] != 'chrome':
        raise ValueError('The verified Long Chau profile is impersonate=chrome.')
    if type(result['retry_failed_on_resume']) is not bool:
        raise ValueError('retry_failed_on_resume must be bool.')
    return result


def make_fetcher(crawler, out, config, robots_options=None):
    from curl_cffi import requests as curl_requests

    class CurlFetcher(crawler.Fetcher):
        uses_browser_fingerprint = True

        def __init__(self):
            super().__init__(out, delay=config['delay'], attempts=config['attempts'], **(robots_options or {}))
            self.curl_session = curl_requests.Session(impersonate='chrome', verify=True)
            self.gate_path = Path(out) / 'longchau_request_gate.json'
            saved = crawler.load_json(self.gate_path) if self.gate_path.exists() else {}
            self.next_wall = saved.get('not_before', 0.)
            self.next_at['nhathuoclongchau.com.vn'] = time.monotonic() + max(0., self.next_wall - time.time())

        def session(self): return self.curl_session
        def close(self): self.curl_session.close()

        def request_once(self, url, limit, delay=None, *, timeout=None, deadline=None):
            self.validate(url)
            site = crawler.get_fld(url, fail_silently=True) or crawler.host(url)
            wait = max(0., self.next_at.get(site, 0.) - time.monotonic())
            if deadline is not None and wait >= deadline - time.monotonic():
                raise crawler.CrawlError('response_deadline', 'Long Chau cooldown exceeds request budget; deferred until resume.')
            time.sleep(wait)
            started = time.monotonic()
            pause, chunks, size, callback_error = max(self.delay, delay or 0.), [], 0, None
            def callback(chunk):
                nonlocal size, callback_error
                size += len(chunk)
                if size > limit:
                    callback_error = crawler.CrawlError('oversized', f'More than {limit} decompressed bytes')
                    return 0
                if deadline is not None and time.monotonic() >= deadline:
                    callback_error = crawler.CrawlError('response_deadline')
                    return 0
                chunks.append(chunk)
                return len(chunk)
            try:
                request_timeout = timeout or config['timeout']
                if deadline is not None:
                    remaining = deadline - started
                    if remaining <= 0: raise crawler.CrawlError('response_deadline')
                    request_timeout = tuple(min(v, remaining / 2) for v in request_timeout)
                response = self.curl_session.get(url, allow_redirects=False, timeout=tuple(request_timeout),
                                                content_callback=callback)
                if callback_error: raise callback_error
                headers = crawler.requests.structures.CaseInsensitiveDict(response.headers)
                if response.status_code in (408, 429) or 500 <= response.status_code < 600:
                    value = headers.get('Retry-After', '')
                    try: cooldown = float(value)
                    except ValueError:
                        try: cooldown = parsedate_to_datetime(value).timestamp() - time.time()
                        except (ValueError, TypeError, OverflowError): cooldown = 0.
                    if math.isfinite(cooldown): pause = max(pause, cooldown)
                return response.status_code, headers, b''.join(chunks)
            except curl_requests.exceptions.RequestException as exc:
                if callback_error: raise callback_error from exc
                if isinstance(exc, curl_requests.exceptions.Timeout):
                    raise crawler.requests.exceptions.Timeout(str(exc)) from exc
                if isinstance(exc, curl_requests.exceptions.SSLError):
                    raise crawler.requests.exceptions.SSLError(str(exc)) from exc
                raise crawler.requests.exceptions.ConnectionError(str(exc)) from exc
            finally:
                self.next_at[site] = time.monotonic() + pause
                self.next_wall = time.time() + pause
                crawler.write_json(self.gate_path, {'not_before': self.next_wall})

    return CurlFetcher()


def crawl(crawler, probe, out, samples, config, *, user_agent, respect_robots=False, robots_options=None,
          record_dir='requests_records', max_new=None, on_record=None, log_every=300):
    """One session/worker; successful current parser checkpoints survive resume unchanged."""
    config = validate_config(config)
    out = Path(out)
    if max_new is not None and (type(max_new) is not int or max_new < 1):
        raise ValueError('max_new must be a positive integer or None.')
    identity = {'version': VERSION, 'sha256': crawler.file_hash(__file__), 'settings': config,
                'respect_robots': respect_robots, 'record_dir': record_dir, 'robots_options': robots_options or {}}
    config_path = out / 'longchau_config.json'
    if config_path.exists() and crawler.load_json(config_path) != identity:
        raise ValueError('Long Chau code/config changed; use a new run directory and recovery.')
    crawler.write_json(config_path, identity)
    selected = [s for s in samples if is_host(s['url'])]
    pending = []
    for sample in selected:
        path = out / record_dir / f"{sample['id']}.json"
        if path.exists():
            record = crawler.load_json(path)
            if (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
                raise ValueError('Long Chau checkpoint ID/URL mismatch.')
            if record.get('status') == 'extracted' and record.get('longchau_parser_version') == VERSION:
                raw = gzip.decompress((out / record['raw_path']).read_bytes())
                if crawler.digest(raw) != record['raw_sha256'] or crawler.digest(record['text'].encode()) != record['text_sha256']:
                    raise ValueError('Long Chau checkpoint raw/text hash mismatch.')
                if on_record: on_record(record)
                continue
            if not config['retry_failed_on_resume']: continue
            # A resumed failure may be replaced; retain its status/attempt history and raw references.
            previous = path.read_bytes()
            history = out / 'longchau_previous_records' / f"{sample['id']}_{crawler.digest(previous)}.json"
            crawler.atomic_bytes(history, previous)
        pending.append(sample)
    if max_new is not None: pending = pending[:max_new]
    if not pending:
        write_reports(crawler, out, selected, record_dir)
        return 0
    fetcher = make_fetcher(crawler, out, config, robots_options)
    completed = 0
    progress = probe.CrawlProgress('curl_cffi', len(pending), log_every)
    try:
        for sample in pending:
            record = probe.request_record(crawler, fetcher, sample, out, user_agent, config['timeout'], config['budget'],
                                          respect_robots=respect_robots, record_dir=record_dir)
            if fetcher.next_wall - time.time() >= config['budget'] and record.get('status') != 'extracted':
                record.setdefault('retry_deferred', 'Long Chau cooldown exceeds next URL budget; resume later.')
            record.update(engine='curl_cffi', longchau_http_client='curl_cffi', impersonate='chrome')
            crawler.write_json(out / record_dir / f"{sample['id']}.json", record)
            if on_record: on_record(record)
            completed += 1
            progress.record(record)
            if record.get('retry_deferred') or record.get('status') == 'response_deadline':
                break
    finally:
        fetcher.close()
        progress.finish()
        write_reports(crawler, out, selected, record_dir)
    return completed


def write_reports(crawler, out, samples, record_dir='records'):
    out = Path(out)
    rows = []
    for sample in samples:
        path = out / record_dir / f"{sample['id']}.json"
        record = crawler.load_json(path) if path.exists() else dict(sample, status='pending')
        fields = ('id','url','final_url','http_status','status','engine','quality_status','quality_flags','title',
                  'char_count','source_body_chars','source_heading_count','kept_heading_count','source_block_count',
                  'kept_block_count','missing_blocks','longchau_removed_count','longchau_template','longchau_selector',
                  'source_table_count','source_image_count','longchau_boilerplate_signals','source_blocks_sha256',
                  'longchau_parser_version','longchau_review_reasons','author','reviewed_by','published_at','updated_at',
                  'error','error_kind','challenge_detected','retry_deferred','raw_path','raw_sha256','text_sha256','elapsed_seconds')
        row = {k: record.get(k) for k in fields}
        row['preview_start'] = record.get('text','')[:600]
        row['preview_end'] = record.get('text','')[-600:]
        rows.append(row)
    crawler.jsonl(out / 'longchau_results.jsonl', rows)
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]) if rows else ['id','url','status'])
    writer.writeheader()
    writer.writerows(rows)
    crawler.atomic_bytes(out / 'longchau_results.csv', buffer.getvalue().encode('utf-8-sig'))
    summary = {'selected': len(samples), 'completed': sum(r['status'] != 'pending' for r in rows),
               'accepted': sum(r['quality_status'] == 'accepted' for r in rows),
               'statuses': dict(Counter(r['status'] for r in rows)),
               'http_statuses': dict(Counter(str(r['http_status']) for r in rows)),
               'quality_statuses': dict(Counter(r['quality_status'] or ('pending' if r['status'] == 'pending' else 'not_extracted') for r in rows)),
               'templates': dict(Counter(r['longchau_template'] or 'unclassified' for r in rows)),
               'boilerplate_signals': dict(Counter(s for r in rows for s in (r['longchau_boilerplate_signals'] or []))),
               'review_reasons': dict(Counter(reason for r in rows for reason in (r.get('longchau_review_reasons') or [])))}
    crawler.write_json(out / 'longchau_summary.json', summary)
    lines = ['# Long Châu — kết quả thực tế', '', json.dumps(summary, ensure_ascii=False, indent=2), '',
             'Heading/block nguồn là vùng y khoa sau loại component, gồm sapo; không đếm menu/UI của toàn trang.',
             'Preview giới hạn 600 ký tự ở CSV/JSONL báo cáo; text đầy đủ nằm trong records và corpus xuất.',
             'Đầu/cuối bài, HTTP/QC, selector, số block/heading và lý do review nằm trong longchau_results.csv.', '']
    crawler.atomic_bytes(out / 'LONGCHAU_REPORT.md', '\n'.join(lines).encode())
