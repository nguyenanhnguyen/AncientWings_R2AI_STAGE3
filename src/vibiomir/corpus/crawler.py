"""ViBioMIR crawl-only pilot. No query labels, models, training or indexing."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import hashlib
import importlib.metadata
import ipaddress
import json
import math
from pathlib import Path
import random
import re
import shutil
import socket
import statistics
import sys
import threading
import time
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import requests
import trafilatura
from tld import get_fld

VERSION = 'v5'
UA = 'ViBioMIRResearchCrawler/0.1'
ROBOT_AGENT = 'ViBioMIRResearchCrawler'


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{threading.get_ident()}.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def write_json(path, obj):
    atomic_bytes(path, json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8'))


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def jsonl(path, rows):
    atomic_bytes(path, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows).encode('utf-8'))


def host(url):
    return (urlsplit(url).hostname or '').lower()


def normalize(text):
    text = unicodedata.normalize('NFC', text or '').replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'[\t \u00a0]+', ' ', text)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(x.strip() for x in text.split('\n'))).strip()


def prepare(args):
    out = Path(args.out)
    if (out / 'manifest.json').exists():
        raise ValueError('Output already has a manifest; reuse it or choose a new --out.')
    source = Path(args.source)
    pf = pq.ParquetFile(source)
    if pf.schema_arrow.names != ['id', 'url'] or not pa.types.is_integer(pf.schema_arrow.field('id').type):
        raise ValueError('Expected integer id and string url columns.')
    ids = pq.read_table(source, columns=['id'])['id']
    if ids.null_count or pc.count_distinct(ids).as_py() != len(ids):
        raise ValueError('Missing or duplicate source IDs.')
    counts = Counter()
    first_counts = Counter()
    # URL authority is sufficient for profiling; validate fully before fetching.
    for batch in pf.iter_batches(columns=['url']):
        for url in batch.column(0).to_pylist():
            if not isinstance(url, str) or not re.match(r'^https?://[^/]+', url):
                raise ValueError(f'Invalid source URL: {url!r}')
            domain = url.split('/', 3)[2].lower()
            counts[domain] += 1
            if sum(first_counts.values()) < 1000:
                first_counts[domain] += 1
    if args.size > sum(counts.values()) or args.size < 1:
        raise ValueError('Invalid sample size.')
    # Equal-host allocation with redistribution for hosts with few rows.
    quota = dict.fromkeys(sorted(counts), 0)
    while sum(quota.values()) < args.size:
        for domain in quota:
            if quota[domain] < counts[domain] and sum(quota.values()) < args.size:
                quota[domain] += 1
    rng = random.Random(args.seed)
    reservoirs = defaultdict(list)
    seen = Counter()
    for batch in pf.iter_batches():
        for doc_id, url in zip(batch.column(0).to_pylist(), batch.column(1).to_pylist()):
            domain = url.split('/', 3)[2].lower()
            seen[domain] += 1
            pool = reservoirs[domain]
            limit = quota[domain]
            if len(pool) < limit:
                pool.append({'id': doc_id, 'url': url, 'domain': domain})
            else:
                index = rng.randrange(seen[domain])
                if index < limit:
                    pool[index] = {'id': doc_id, 'url': url, 'domain': domain}
    sample = sorted((r for pool in reservoirs.values() for r in pool), key=lambda r: r['id'])
    start, stop = getattr(args, 'id_start', None), getattr(args, 'id_stop', None)
    if (start is None) != (stop is None):
        raise ValueError('Specify both --id-start and --id-stop (exclusive).')
    if start is not None:
        selected = pq.read_table(source, filters=[('id', '>=', start), ('id', '<', stop)]).to_pylist()
        sample = sorted(({**r, 'domain': host(r['url'])} for r in selected), key=lambda r: r['id'])
        if len(sample) != args.size:
            raise ValueError(f'ID interval has {len(sample)} rows, expected --size {args.size}.')
        quota = {domain: 0 for domain in counts}
        quota.update(Counter(r['domain'] for r in sample))
    out.mkdir(parents=True, exist_ok=True)
    jsonl(out / 'sample.jsonl', sample)
    write_json(out / 'source_profile.json', {
        'rows': pf.metadata.num_rows, 'id_min': pc.min(ids).as_py(), 'id_max': pc.max(ids).as_py(),
        'duplicate_ids': 0, 'hosts': len(counts), 'host_counts': counts,
        'first_1000_host_counts': first_counts, 'sample_host_counts': quota,
    })
    write_json(out / 'manifest.json', {
        'created_at': utc(), 'dataset': 'AIGuruTinix/ViBioMIR', 'config': 'corpus', 'split': 'train',
        'source': str(source.resolve()), 'source_sha256': file_hash(source),
        'sampling': 'id_interval' if start is not None else 'equal_host_reservoir',
        'id_start_inclusive': start, 'id_stop_exclusive': stop, 'seed': args.seed, 'selected': len(sample),
        'sample_sha256': file_hash(out / 'sample.jsonl'), 'source_rows': pf.metadata.num_rows,
    })
    if getattr(args, 'reuse_run', None):
        previous = Path(args.reuse_run)
        reused = []
        for row in sample:
            old = previous / 'records' / f"{row['id']}.json"
            if not old.exists():
                continue
            record = load_json(old)
            if record['id'] != row['id'] or record['url'] != row['url']:
                raise ValueError('Reuse ID/URL mismatch.')
            if record.get('raw_path') and 200 <= record.get('http_status', 0) < 300:
                raw = previous / record['raw_path']
                body = gzip.decompress(raw.read_bytes())
                if digest(body) != record['raw_sha256']:
                    raise ValueError('Reuse raw hash mismatch.')
                doc = extract(body, record['content_type'], record['final_url'])
                record.update(doc)
                record.update(quality(doc))
                flag_redirect(record)
                target = out / record['raw_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(raw, target)
                record.update(reused_from=str(previous.resolve()), reprocessed_at=utc())
                write_json(out / 'records' / old.name, record)
                reused.append(record['id'])
        write_json(out / 'reuse_manifest.json', {'source_run': str(previous.resolve()), 'reused_ids': reused})
    print(json.dumps({'selected': len(sample), 'hosts': len(counts), 'out': str(out)}), flush=True)


class CrawlError(Exception):
    def __init__(self, status, detail=''):
        self.status = status
        super().__init__(detail or status)


class Fetcher:
    def __init__(self, out, delay=1.0, attempts=3, *, robots_attempts=None,
                 robots_connect_timeout=15.0, robots_read_timeout=30.0,
                 robots_retry_budget=90.0, robots_failure_ttl=30.0):
        self.out, self.delay, self.attempts = Path(out), delay, attempts
        self.robots_attempts = attempts if robots_attempts is None else robots_attempts
        if type(self.robots_attempts) is not int or self.robots_attempts < 1:
            raise ValueError('robots_attempts must be a positive integer.')
        self.robots_config = {'robots_attempts': self.robots_attempts,
                              'robots_connect_timeout': robots_connect_timeout,
                              'robots_read_timeout': robots_read_timeout,
                              'robots_retry_budget': robots_retry_budget,
                              'robots_failure_ttl': robots_failure_ttl}
        for key, value in self.robots_config.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'{key} must be finite and positive.')
        self.robots_timeout = (robots_connect_timeout, robots_read_timeout)
        self.robots_retry_budget, self.robots_failure_ttl = robots_retry_budget, robots_failure_ttl
        self.guard = threading.Lock()
        self.locks, self.next_at, self.robots_locks, self.robots = {}, {}, {}, {}
        self.robots_expiry = {}
        self.local = threading.local()

    def lock_for(self, registry, key):
        with self.guard:
            return registry.setdefault(key, threading.Lock())

    def session(self):
        if not hasattr(self.local, 'session'):
            self.local.session = requests.Session()
            self.local.session.headers.update({'User-Agent': UA, 'Accept': 'text/html,application/pdf;q=0.9,*/*;q=0.5'})
        return self.local.session

    @staticmethod
    def validate(url):
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise CrawlError('invalid_url')
        if parsed.port not in (None, 80, 443):
            raise CrawlError('invalid_url', 'Nonstandard port')
        # Apply to source and every redirect. Never fetch local/private endpoints.
        for item in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)):
            if not ipaddress.ip_address(item[4][0]).is_global:
                raise CrawlError('unsafe_address', parsed.hostname)

    def request_once(self, url, limit, delay=None, *, timeout=None, deadline=None):
        self.validate(url)
        site = get_fld(url, fail_silently=True) or host(url)
        lock = self.lock_for(self.locks, site)
        if deadline is None:
            lock.acquire()
        elif not lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise CrawlError('response_deadline', 'Request budget exhausted waiting for domain lock')
        try:
            wait = max(0, self.next_at.get(site, 0) - time.monotonic())
            if deadline is not None and wait >= deadline - time.monotonic():
                raise CrawlError('response_deadline', 'Request budget exhausted by domain cooldown')
            time.sleep(wait)
            try:
                start = time.monotonic()
                request_timeout = timeout or (8, 20)
                if deadline is not None:
                    remaining = deadline - start
                    if remaining <= 0:
                        raise CrawlError('response_deadline', 'Request budget exhausted')
                    request_timeout = tuple(min(value, remaining / 2) for value in request_timeout)
                with self.session().get(url, timeout=request_timeout, stream=True, allow_redirects=False) as response:
                    chunks, total = [], 0
                    for chunk in response.iter_content(65536):
                        total += len(chunk)
                        if total > limit:
                            raise CrawlError('oversized', f'More than {limit} decompressed bytes')
                        if time.monotonic() - start > 45 or (deadline is not None and time.monotonic() >= deadline):
                            raise CrawlError('response_deadline')
                        chunks.append(chunk)
                    if deadline is not None and time.monotonic() >= deadline:
                        raise CrawlError('response_deadline', 'Request budget exhausted reading response')
                    status, headers, body = response.status_code, requests.structures.CaseInsensitiveDict(response.headers), b''.join(chunks)
                    cooldown = max(self.delay, delay or 0)
                    if status in (429, 503):
                        value = response.headers.get('Retry-After', '0')
                        try:
                            cooldown = max(cooldown, float(value))
                        except ValueError:
                            try:
                                cooldown = max(cooldown, parsedate_to_datetime(value).timestamp() - time.time())
                            except (ValueError, TypeError, OverflowError):
                                pass
                    self.next_at[site] = time.monotonic() + cooldown
                    return status, headers, body
            finally:
                self.next_at[site] = max(self.next_at.get(site, 0), time.monotonic() + max(self.delay, delay or 0))
        finally:
            lock.release()

    def load_robots(self, origin):
        robot_url = origin + '/robots.txt'
        started = time.monotonic()
        deadline = started + self.robots_retry_budget
        fetch_id = digest(f'{origin}:{time.time_ns()}'.encode())[:16]
        evidence = {'origin': origin, 'url': robot_url, 'fetched_at': utc(), 'fetch_id': fetch_id,
                    'requests': [], 'attempt_count': 0, 'retryable': False}
        policy, error = None, 'robots_unknown'
        retryable = False
        for attempt in range(1, self.robots_attempts + 1):
            if time.monotonic() >= deadline:
                evidence.update(error='Robots retry budget exhausted', error_kind='retry_budget_exhausted')
                retryable = True
                break
            evidence['attempt_count'] = attempt
            retryable = False
            evidence.pop('error_kind', None)
            # A retry starts at the original robots URL, preserving every redirect check.
            current = robot_url
            try:
                for hop in range(6):
                    event = {'url': current, 'attempt': attempt, 'redirect_hop': hop, 'at': utc()}
                    evidence['requests'].append(event)
                    begin = time.monotonic()
                    try:
                        status, headers, body = self.request_once(current, 1024 * 1024,
                                                                 timeout=self.robots_timeout, deadline=deadline)
                        headers = requests.structures.CaseInsensitiveDict(headers)
                        event.update(http_status=status, content_type=headers.get('Content-Type', ''),
                                     response_headers={k: v for k, v in headers.items() if k.lower() in
                                                       ('content-type', 'location', 'retry-after', 'server')},
                                     body_sha256=digest(body))
                        raw = Path('robots/raw') / digest(origin.encode()) / f'{fetch_id}_a{attempt}_r{hop}.gz'
                        atomic_bytes(self.out / raw, gzip.compress(body, mtime=0))
                        event['raw_path'] = str(raw.as_posix())
                    except Exception as exc:
                        event.update(error=str(exc)[:500], exception_class=type(exc).__name__)
                        raise
                    finally:
                        event['elapsed_seconds'] = round(time.monotonic() - begin, 3)
                    evidence.update(status=status, final_url=current, content_type=event['content_type'],
                                    body_sha256=event['body_sha256'], raw_path=event['raw_path'])
                    if status in (301, 302, 303, 307, 308) and headers.get('Location'):
                        current = urljoin(current, headers['Location'])
                        continue
                    break
                else:
                    raise CrawlError('robots_unknown', 'Robots redirect limit exceeded')
                if 200 <= status < 300:
                    text = body.decode('utf-8', 'replace')
                    if '<html' in text[:1000].lower() or '<!doctype' in text[:1000].lower():
                        evidence['error_kind'] = 'invalid_html'
                        raise CrawlError('robots_unknown', 'HTML instead of robots.txt')
                    policy = RobotFileParser(robot_url)
                    policy.parse(text.splitlines())
                    evidence['text'] = text
                elif status in (404, 410):
                    policy = RobotFileParser(robot_url)
                    policy.parse([])
                elif status in (401, 403):
                    evidence['error_kind'] = f'http_{status}'
                    raise CrawlError('robots_denied', f'robots HTTP {status}')
                else:
                    retryable = status in (408, 429) or 500 <= status < 600
                    evidence['error_kind'] = f'http_{status}'
                    raise CrawlError('robots_unknown', f'robots HTTP {status}')
                error, retryable = None, False
                evidence.pop('error', None)
                evidence.pop('error_kind', None)
                break
            except Exception as exc:
                error = exc.status if isinstance(exc, CrawlError) else 'robots_unknown'
                if isinstance(exc, (requests.RequestException, OSError)):
                    retryable = (not isinstance(exc, requests.exceptions.SSLError)
                                 and (isinstance(exc, requests.RequestException)
                                      or 'http_status' not in evidence['requests'][-1]))
                    evidence['error_kind'] = type(exc).__name__
                elif isinstance(exc, CrawlError) and exc.status == 'response_deadline':
                    error, retryable = 'robots_unknown', True
                    evidence['error_kind'] = 'retry_budget_exhausted'
                evidence['error'] = str(exc)[:500]
            if not retryable or attempt == self.robots_attempts:
                break
            site = get_fld(current, fail_silently=True) or host(current)
            backoff = 2 ** (attempt - 1) + random.uniform(0, .25)
            wait = max(backoff, self.next_at.get(site, 0) - time.monotonic())
            if wait >= deadline - time.monotonic():
                evidence['retry_deferred'] = 'Cooldown/backoff exceeds remaining robots retry budget'
                break
            evidence['requests'][-1]['retry_wait_seconds'] = round(wait, 3)
            time.sleep(wait)
        evidence.update(retryable=retryable, elapsed_seconds=round(time.monotonic() - started, 3),
                        cache_hit=False)
        return policy, evidence, error

    def robot_policy(self, url):
        p = urlsplit(url)
        origin = f'{p.scheme}://{p.netloc}'
        waiting = time.monotonic()
        with self.lock_for(self.robots_locks, origin):
            lock_wait = time.monotonic() - waiting
            cached = origin in self.robots and time.monotonic() < self.robots_expiry.get(origin, math.inf)
            if not cached:
                self.robots[origin] = self.load_robots(origin)
                policy, evidence, error = self.robots[origin]
                if error and evidence['retryable']:
                    site = get_fld(origin, fail_silently=True) or p.hostname
                    ttl = max(self.robots_failure_ttl, self.next_at.get(site, 0) - time.monotonic())
                    self.robots_expiry[origin] = time.monotonic() + ttl
                    evidence['failure_cache_ttl_seconds'] = round(ttl, 3)
                else:
                    self.robots_expiry.pop(origin, None)
                write_json(self.out / 'robots' / (digest(origin.encode()) + '.json'), evidence)
            policy, evidence, error = self.robots[origin]
            evidence = dict(evidence, cache_hit=cached, lock_wait_seconds=round(lock_wait, 3))
            self.local.robot_evidence = evidence
        if error:
            raise CrawlError(error, evidence.get('error', error))
        if not policy.can_fetch(ROBOT_AGENT, url):
            raise CrawlError('robots_disallowed', url)
        delay = policy.crawl_delay(ROBOT_AGENT) or 0
        rate = policy.request_rate(ROBOT_AGENT)
        if rate and rate.requests:
            delay = max(delay, rate.seconds / rate.requests)
        return delay, evidence

    def fetch(self, url, trace):
        current = url
        chain = []
        for _ in range(8):
            try:
                delay, robots = self.robot_policy(current)
            except CrawlError:
                evidence = getattr(self.local, 'robot_evidence', {})
                parsed = urlsplit(current)
                if evidence.get('origin') == f'{parsed.scheme}://{parsed.netloc}':
                    trace['robots'] = evidence
                raise
            trace['robots'] = robots
            for attempt in range(1, self.attempts + 1):
                event = {'url': current, 'attempt': attempt, 'at': utc()}
                trace['requests'].append(event)
                try:
                    status, headers, body = self.request_once(current, 10 * 1024 * 1024, delay)
                    event['http_status'] = status
                except (requests.RequestException, OSError) as exc:
                    event['error'] = str(exc)[:300]
                    if attempt == self.attempts:
                        raise CrawlError('network_error', str(exc)[:500]) from exc
                    time.sleep(2 ** attempt)
                    continue
                if status in (408, 429, 500, 502, 503, 504) and attempt < self.attempts:
                    # Long server cooldowns are deferred to a later recovery run.
                    site = get_fld(current, fail_silently=True) or host(current)
                    if self.next_at.get(site, 0) - time.monotonic() > 60:
                        raise CrawlError('rate_limited_deferred', 'Retry-After exceeds pilot wait budget')
                    time.sleep(2 ** attempt)
                    continue
                break
            trace.update(http_status=status, final_url=current, redirects=chain, content_type=headers.get('Content-Type', ''),
                         response_headers={k: v for k, v in headers.items() if k.lower() in ('content-type', 'etag', 'last-modified', 'location')})
            if status in (301, 302, 303, 307, 308) and headers.get('Location'):
                target = urljoin(current, headers['Location'])
                chain.append({'from': current, 'to': target, 'status': status})
                current = target
                continue
            return body
        raise CrawlError('redirect_limit')


def dom_text(element):
    """Keep source text and block boundaries without an article-summary heuristic."""
    result = []
    blocks = {'p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'tr', 'section', 'blockquote'}

    def visit(node):
        # lxml comments have a callable tag; Office conditional comments are not article text.
        if not isinstance(node.tag, str):
            return
        tag = str(node.tag).lower()
        if tag in ('script', 'style', 'iframe', 'noscript', 'svg', 'form'):
            return
        if tag in blocks or tag == 'br':
            result.append('\n')
        if node.text:
            result.append(node.text)
        for child in node:
            visit(child)
            if child.tail:
                result.append(child.tail)
        if tag in ('td', 'th'):
            result.append(' | ')
        if tag in blocks:
            result.append('\n')

    visit(element)
    return normalize(''.join(result))


def bachmai_publication_date(tree):
    """Read the current article's print header, never dates from related stories."""
    articles = tree.xpath('//*[@id="content-post"]')
    if len(articles) != 1:
        return None
    headers = articles[0].xpath('.//*[@id="title-print"]')
    if len(headers) != 1:
        return None
    text = ' '.join(headers[0].itertext())
    dates = re.findall(r'Ngày đăng\s*:\s*(\d{1,2}/\d{1,2}/\d{4})(?!\d)', text)
    if len(dates) != 1:
        return None
    try:
        return datetime.strptime(dates[0], '%d/%m/%Y').date().isoformat()
    except ValueError:
        return None


def bachmai_article_body(element):
    """Remove confirmed related-story widgets while preserving surrounding text."""
    from copy import deepcopy
    article = deepcopy(element)
    for node in list(article.iterdescendants()):
        if not isinstance(node.tag, str):
            continue
        classes = set((node.get('class') or '').split())
        related = 'post-detail__same-category-content' in classes
        if node.tag == 'article' and 'story' in classes:
            labels = node.xpath('./header/h4[contains(concat(" ", normalize-space(@class), " "), " label ")]')
            links = node.xpath('./header/a[contains(concat(" ", normalize-space(@class), " "), " title ")][@href]')
            related = bool(links) and any(' '.join(label.itertext()).strip().upper() == 'TIN LIÊN QUAN'
                                          for label in labels)
        if related:
            node.drop_tree()  # lxml keeps the tail (article text following the widget).
    return article


def extract(body, content_type, url):
    if body.startswith(b'%PDF-') or 'application/pdf' in content_type.lower():
        import pymupdf
        with pymupdf.open(stream=body, filetype='pdf') as pdf:
            pages = [normalize(page.get_text(sort=True)) for page in pdf]
            return {'title': pdf.metadata.get('title') or '', 'text': normalize('\n\n'.join(pages)),
                    'extractor': 'pymupdf', 'page_count': len(pages), 'empty_pages': sum(len(p) < 30 for p in pages)}
    if 'html' not in content_type.lower() and b'<html' not in body[:2000].lower() and b'<!doctype html' not in body[:2000].lower():
        raise CrawlError('unsupported_content_type', content_type)
    # Prefer the declared charset; statistical detection misread a real GB2312 page as Cyrillic.
    charset = re.search(r'charset\s*=\s*[\"\']?([\w-]+)', content_type, re.I)
    if not charset:
        charset = re.search(r'charset\s*=\s*[\"\']?([\w-]+)', body[:16384].decode('ascii', 'ignore'), re.I)
    encoding = charset.group(1).lower() if charset else None
    if encoding in ('gb2312', 'gbk', 'x-gbk'):
        encoding = 'gb18030'
    html_input = body
    decode_warning = False
    if encoding:
        try:
            html_input = body.decode(encoding, 'strict')
        except (UnicodeDecodeError, LookupError):
            decode_warning = True
    result = trafilatura.extract(html_input, url=url, output_format='json', with_metadata=True,
                                 include_comments=False, include_tables=True, deduplicate=False)
    doc = json.loads(result) if result else {}
    output = {'title': normalize(doc.get('title')), 'text': normalize(doc.get('text')),
            'extractor': 'trafilatura', 'published_at': doc.get('date'), 'author': doc.get('author'),
            'declared_encoding': encoding, 'decode_warning': decode_warning}
    if host(url) == 'bachmai.gov.vn':
        from lxml import html
        tree = html.fromstring(html_input)
        output['published_at'] = bachmai_publication_date(tree)
        bodies = [el for el in tree.iter('div') if 'content-editor-post' in (el.get('class') or '').split()]
        intros = [el for el in tree.iter('div') if 'content-excerpt' in (el.get('class') or '').split()]
        if len(bodies) == 1:
            article = bachmai_article_body(bodies[0])
            main = dom_text(article)
            intro = '\n\n'.join(dom_text(el) for el in intros)
            text = main if not intro or main.startswith(intro) else intro + '\n\n' + main
            output.update(text=normalize(text), extractor='bachmai_dom_v2',
                          source_body_chars=len(main), source_intro_chars=len(intro),
                          extraction_selectors=['div.content-excerpt', 'div.content-editor-post'],
                          source_images=[{'url': el.get('src'), 'alt': el.get('alt')} for el in article.iter('img')])
        else:
            output['domain_parser_fallback'] = True
    return output


def flag_redirect(record):
    if host(record['url']) != host(record['final_url']) or (urlsplit(record['final_url']).path in ('', '/') and urlsplit(record['url']).path not in ('', '/')):
        record['quality_flags'].append('redirect_review')
        if record['quality_status'] == 'accepted':
            record['quality_status'] = 'review'


def quality(doc):
    text, title = doc['text'], doc.get('title', '')
    flags = []
    n = len(text)
    cjk = sum('\u3400' <= c <= '\u9fff' for c in text)
    replacement = text.count('\ufffd') / max(1, n)
    letters = sum(c.isalpha() for c in text) / max(1, n)
    lines = [s.strip() for s in text.splitlines() if len(s.strip()) >= 20]
    repeats = 1 - len(set(lines)) / max(1, len(lines)) if lines else 0
    # Script hints only; this is not a calibrated language classifier.
    if cjk / max(1, n) > .2:
        language = 'zh_hint'
    elif re.search('[ăâđêôơưĂÂĐÊÔƠƯ]', text):
        language = 'vi_hint'
    else:
        language = 'latin_or_unknown'
    if n < (120 if language == 'zh_hint' else 300):
        flags.append('short_text')
    if not title:
        flags.append('missing_title')
    if replacement > .001:
        flags.append('decode_suspect')
    if doc.get('decode_warning') or sum('\u0400' <= ch <= '\u04ff' for ch in text) / max(1, n) > .1:
        flags.append('encoding_or_script_review')
    # Strong template markers observed in the smoke sample, counted without deleting source text.
    markers = ('涉嫌广告宣传', '其他投诉理由', '医生在线免费咨询', '明星药品', '网站导航',
               '买卖器官', '复制粘贴内容', 'Đăng nhập để bình luận', 'Chính sách bảo mật')
    if sum(marker in text for marker in markers) >= 3:
        flags.append('boilerplate_suspect')
    if letters < .45:
        flags.append('low_letter_ratio')
    if repeats > .2:
        flags.append('repeated_lines')
    if doc.get('empty_pages', 0):
        flags.append('pdf_needs_ocr_review')
    if doc.get('domain_parser_fallback'):
        flags.append('domain_parser_fallback')
    if doc.get('extractor') in ('bachmai_dom_v1', 'bachmai_dom_v2') and doc.get('source_body_chars', 0) < 150:
        flags.append('short_article_body')
        if doc.get('source_images'):
            flags.append('image_text_requires_ocr_review')
    if re.search(r'MicrosoftInternetExplorer|mso-style|mso-tstyle|<!\[endif|<style>|<xml>', text, re.I):
        flags.append('office_or_markup_leak')
    error_pattern = r'^(?:404|403|access denied|just a moment|attention required|页面不存在|页面未找到|trang không tồn tại|không tìm thấy trang)'
    if re.search(error_pattern, title.strip(), re.I) or (n < 2000 and re.search(r'verify you are human|checking your browser|enable javascript and cookies|验证码|captcha', text, re.I)):
        flags.append('error_or_challenge')
    status = 'accepted' if not flags else 'review'
    if not text or 'error_or_challenge' in flags:
        status = 'rejected'
    return {'quality_status': status, 'quality_flags': flags, 'char_count': n,
            'language_hint': language, 'replacement_ratio': replacement, 'letter_ratio': letters,
            'repeated_line_ratio': repeats, 'text_sha256': digest(text.encode('utf-8'))}


def crawl_one(row, fetcher, out):
    record = {**row, 'started_at': utc(), 'requests': [], 'status': 'pending'}
    begin = time.monotonic()
    try:
        body = fetcher.fetch(row['url'], record)
        raw_hash = digest(body)
        raw_path = Path('raw') / raw_hash[:2] / (raw_hash + '.gz')
        atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
        record.update(raw_sha256=raw_hash, raw_path=raw_path.as_posix(), raw_bytes=len(body))
        if not 200 <= record['http_status'] < 300:
            raise CrawlError('http_error', str(record['http_status']))
        doc = extract(body, record['content_type'], record['final_url'])
        record.update(doc)
        record.update(quality(doc))
        # Redirects to another site/homepage need verification even if text is long.
        flag_redirect(record)
        record['status'] = 'extracted'
    except CrawlError as exc:
        record.update(status=exc.status, error=str(exc))
    except Exception as exc:
        record.update(status='unexpected_error', error=f'{type(exc).__name__}: {exc}'[:1000])
    record.update(finished_at=utc(), elapsed_seconds=round(time.monotonic() - begin, 3))
    write_json(out / 'records' / f"{row['id']}.json", record)
    return record


def crawl(args):
    out = Path(args.out)
    manifest = load_json(out / 'manifest.json')
    if file_hash(out / 'sample.jsonl') != manifest['sample_sha256']:
        raise ValueError('Sample hash changed.')
    robots_options = {key: getattr(args, key, default) for key, default in {
        'robots_attempts': None, 'robots_connect_timeout': 15.0, 'robots_read_timeout': 30.0,
        'robots_retry_budget': 90.0, 'robots_failure_ttl': 30.0}.items()}
    fetcher = Fetcher(out, args.delay, args.attempts, **robots_options)
    identity = {'version': VERSION, 'script_sha256': file_hash(__file__), 'delay': args.delay,
                'attempts': args.attempts, 'user_agent': UA,
                'robot_agent': ROBOT_AGENT, **fetcher.robots_config,
                'python_version': sys.version.split()[0], 'platform': sys.platform,
                'packages': {p: importlib.metadata.version(p) for p in ('requests', 'pyarrow', 'trafilatura', 'pymupdf')}}
    path = out / 'crawl_config.json'
    if path.exists() and load_json(path) != identity:
        raise ValueError('Crawler/config changed; use a new run directory to preserve provenance.')
    write_json(path, identity)
    rows = [json.loads(line) for line in (out / 'sample.jsonl').read_text(encoding='utf-8').splitlines()]
    pending = []
    for row in rows:
        checkpoint = out / 'records' / f"{row['id']}.json"
        if checkpoint.exists():
            saved = load_json(checkpoint)
            if saved['id'] != row['id'] or saved['url'] != row['url']:
                raise ValueError('Checkpoint identity mismatch.')
            if saved.get('raw_path') and not (out / saved['raw_path']).exists():
                raise ValueError('Checkpoint raw missing.')
        else:
            pending.append(row)
    random.Random(42).shuffle(pending)
    if args.max_new:
        pending = pending[:args.max_new]
    summary = Counter()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(crawl_one, row, fetcher, out) for row in pending]
        for index, future in enumerate(as_completed(futures), 1):
            row = future.result()
            summary[row['status']] += 1
            if index % 25 == 0 or index == len(pending):
                print(json.dumps({'completed_this_invocation': index, 'scheduled': len(pending), 'statuses': summary}), flush=True)
    report(argparse.Namespace(out=args.out))


@contextmanager
def run_lock(out):
    """OS lock survives stale lock files and is released automatically after process termination."""
    path = Path(out) / '.crawl.lock'
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        if sys.platform == 'win32':
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError('Another crawler owns this run; do not start a second resume.') from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError('Another crawler owns this run; do not start a second resume.') from exc
        try:
            yield
        finally:
            handle.seek(0)
            if sys.platform == 'win32':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def locked_crawl(args):
    with run_lock(args.out):
        crawl(args)


def report(args):
    out = Path(args.out)
    manifest = load_json(out / 'manifest.json')
    profile = load_json(out / 'source_profile.json')
    sample = [json.loads(x) for x in (out / 'sample.jsonl').read_text(encoding='utf-8').splitlines()]
    if file_hash(out / 'sample.jsonl') != manifest['sample_sha256']:
        raise ValueError('Sample hash changed.')
    rows = []
    for item in sample:
        p = out / 'records' / f"{item['id']}.json"
        if p.exists():
            r = load_json(p)
            if r['id'] != item['id'] or r['url'] != item['url']:
                raise ValueError('Record ID/URL mismatch.')
            if r.get('raw_path'):
                if digest(gzip.decompress((out / r['raw_path']).read_bytes())) != r['raw_sha256']:
                    raise ValueError(f"Corrupt raw: {r['id']}")
            if 'text' in r and digest(r['text'].encode('utf-8')) != r['text_sha256']:
                raise ValueError('Text hash mismatch.')
            rows.append(r)
    accepted = [r for r in rows if r.get('quality_status') == 'accepted']
    extracted = [r for r in rows if r['status'] == 'extracted']
    groups = defaultdict(list)
    for r in extracted:
        if r.get('text'):
            groups[r['text_sha256']].append(r['id'])
    aliases = [{'text_sha256': h, 'doc_ids': sorted(ids)} for h, ids in groups.items() if len(ids) > 1]
    for r in extracted:
        r['duplicate_doc_ids'] = sorted(groups.get(r['text_sha256'], [])) if r.get('text') else []
    jsonl(out / 'documents.jsonl', extracted)
    jsonl(out / 'corpus.accepted.jsonl', accepted)
    jsonl(out / 'quarantine.jsonl', [r for r in rows if r.get('quality_status') != 'accepted'])
    jsonl(out / 'duplicates.jsonl', aliases)
    by_host = []
    for domain, population in sorted(profile['host_counts'].items()):
        rs = [r for r in rows if r['domain'] == domain]
        n = profile['sample_host_counts'][domain]
        by_host.append({'domain': domain, 'population': population, 'selected': n, 'completed': len(rs),
                        'extracted': sum(r['status'] == 'extracted' for r in rs),
                        'accepted': sum(r.get('quality_status') == 'accepted' for r in rs),
                        'statuses': dict(Counter(r['status'] for r in rs))})
    weighted = sum(x['population'] * x['accepted'] / x['selected'] for x in by_host if x['selected']) / profile['rows']
    lengths = sorted(r['char_count'] for r in extracted)
    summary = {'selected': len(sample), 'completed': len(rows), 'pending': len(sample) - len(rows),
               'http_2xx': sum(200 <= r.get('http_status', 0) < 300 for r in rows),
               'extracted': len(extracted), 'accepted': len(accepted),
               'review': sum(r.get('quality_status') == 'review' for r in rows),
               'rejected': sum(r.get('quality_status') == 'rejected' for r in rows),
               'status_counts': dict(Counter(r['status'] for r in rows)),
               'quality_flags': dict(Counter(f for r in rows for f in r.get('quality_flags', []))),
               'language_hints': dict(Counter(r.get('language_hint', 'unknown') for r in extracted)),
               'exact_duplicate_groups': len(aliases),
               'accepted_rate_selected': len(accepted) / len(sample),
               'weighted_accepted_rate': weighted if len(rows) == len(sample) and all(x['selected'] for x in by_host) else None,
               'text_chars_median': statistics.median(lengths) if lengths else None,
               'text_chars_p95': lengths[math.ceil(.95 * len(lengths)) - 1] if lengths else None,
               'manual_review': 'pending; automatic acceptance is provisional', 'by_host': by_host}
    write_json(out / 'quality_report.json', summary)
    # Reproducible review sheet: one example per host plus failures; never overwrite human labels.
    review = out / 'manual_review.jsonl'
    if not review.exists() and len(rows) == len(sample):
        chosen = []
        rng = random.Random(42)
        for domain in sorted(profile['host_counts']):
            candidates = [r for r in rows if r['domain'] == domain]
            if candidates:
                r = rng.choice(candidates)
                chosen.append({k: r.get(k) for k in ('id', 'url', 'raw_path', 'status', 'quality_status')})
        for item in chosen:
            item.update(correct_page=None, completeness_0_to_2=None, cleanliness_0_to_2=None,
                        medical_numbers_preserved=None, reviewer=None, notes='')
        jsonl(review, chosen)
    lines = ['# Kết quả crawl pilot ViBioMIR', '', f"- Chọn: {len(sample)} URL; hoàn tất: {len(rows)}; còn chờ: {summary['pending']}.",
             f"- HTTP 2xx: {summary['http_2xx']}; trích xuất: {len(extracted)}; tự động chấp nhận: {len(accepted)}.",
             f"- Cần xem lại: {summary['review']}; nội dung bị loại: {summary['rejected']}.",
             f"- Tỷ lệ chấp nhận / URL đã chọn: {summary['accepted_rate_selected']:.2%}.",
             f"- Nhóm trùng text: {len(aliases)}; vẫn giữ tất cả ID gốc.",
             '- Nhãn accepted là heuristic; chưa thay thế kiểm tra thủ công. Không phải điểm contest.',
             f"- Phương pháp chọn: {manifest['sampling']}; tỷ lệ mẫu không đại diện trực tiếp cho toàn corpus.", '',
             '| Website | Tổng URL | Mẫu | Hoàn tất | Trích xuất | Accepted |', '| --- | ---: | ---: | ---: | ---: | ---: |']
    for x in by_host:
        lines.append(f"| {x['domain']} | {x['population']} | {x['selected']} | {x['completed']} | {x['extracted']} | {x['accepted']} |")
    lines.extend(['', '## Trạng thái', '', '```json', json.dumps(summary['status_counts'], indent=2), '```', '',
                  '## Cờ chất lượng', '', '```json', json.dumps(summary['quality_flags'], indent=2), '```', ''])
    atomic_bytes(out / 'QUALITY_REPORT.md', '\n'.join(lines).encode('utf-8'))
    write_json(out / 'artifact_manifest.json', {'generated_at': utc(), 'source_manifest_sha256': file_hash(out / 'manifest.json'),
               'files': {p: file_hash(out / p) for p in ('documents.jsonl', 'corpus.accepted.jsonl', 'quarantine.jsonl', 'duplicates.jsonl', 'quality_report.json')}})
    print(json.dumps({k: v for k, v in summary.items() if k != 'by_host'}, ensure_ascii=True), flush=True)


def reprocess(args):
    """Create a new version from saved raw, retaining fetch evidence and every source ID."""
    source, out = Path(args.source_run), Path(args.out)
    if out.exists():
        raise ValueError('Reprocess requires a new output directory.')
    manifest = load_json(source / 'manifest.json')
    if file_hash(source / 'sample.jsonl') != manifest['sample_sha256']:
        raise ValueError('Source sample hash changed.')
    out.mkdir(parents=True)
    for name in ('sample.jsonl', 'source_profile.json'):
        shutil.copyfile(source / name, out / name)
    manifest.update(parent_run=str(source.resolve()), reprocessed_at=utc(), reprocess_script_sha256=file_hash(__file__))
    write_json(out / 'manifest.json', manifest)
    if (source / 'robots').exists():
        shutil.copytree(source / 'robots', out / 'robots')
    allowed = {r['id']: r['url'] for r in (json.loads(s) for s in (source / 'sample.jsonl').read_text(encoding='utf-8').splitlines())}
    for path in sorted((source / 'records').glob('*.json')):
        record = load_json(path)
        if allowed.get(record['id']) != record['url']:
            raise ValueError('Record outside sample.')
        if record.get('raw_path'):
            raw = source / record['raw_path']
            body = gzip.decompress(raw.read_bytes())
            if digest(body) != record['raw_sha256']:
                raise ValueError('Corrupt source raw.')
            target = out / record['raw_path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(raw, target)
            if 200 <= record.get('http_status', 0) < 300:
                try:
                    doc = extract(body, record['content_type'], record['final_url'])
                    record.update(doc)
                    record.update(quality(doc))
                    record['status'] = 'extracted'
                    if host(record['url']) != host(record['final_url']) or (urlsplit(record['final_url']).path in ('', '/') and urlsplit(record['url']).path not in ('', '/')):
                        record['quality_flags'].append('redirect_review')
                        if record['quality_status'] == 'accepted':
                            record['quality_status'] = 'review'
                except CrawlError as exc:
                    record.update(status=exc.status, error=str(exc), quality_status='rejected')
        record['reprocessed_at'] = utc()
        write_json(out / 'records' / path.name, record)
    report(argparse.Namespace(out=out))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--source', default='data/links_corpus.parquet')
    p.add_argument('--out', required=True)
    p.add_argument('--size', type=int, default=1000)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--id-start', type=int, help='Inclusive first source ID')
    p.add_argument('--id-stop', type=int, help='Exclusive source ID upper bound')
    p.add_argument('--reuse-run', help='Reuse verified successful raw and re-extract under current code')
    p.set_defaults(func=prepare)
    p = sub.add_parser('crawl')
    p.add_argument('--out', required=True)
    p.add_argument('--workers', type=int, default=12)
    p.add_argument('--delay', type=float, default=1.0)
    p.add_argument('--attempts', type=int, default=3)
    p.add_argument('--robots-attempts', type=int, default=None, help='Default: inherit --attempts')
    p.add_argument('--robots-connect-timeout', type=float, default=15.0)
    p.add_argument('--robots-read-timeout', type=float, default=30.0)
    p.add_argument('--robots-retry-budget', type=float, default=90.0)
    p.add_argument('--robots-failure-ttl', type=float, default=30.0)
    p.add_argument('--max-new', type=int)
    p.set_defaults(func=locked_crawl)
    p = sub.add_parser('report')
    p.add_argument('--out', required=True)
    p.set_defaults(func=report)
    p = sub.add_parser('reprocess')
    p.add_argument('--source-run', required=True)
    p.add_argument('--out', required=True)
    p.set_defaults(func=reprocess)
    args = parser.parse_args()
    if getattr(args, 'workers', 1) < 1 or getattr(args, 'delay', 1) < 0 or getattr(args, 'attempts', 1) < 1:
        parser.error('workers/attempts must be positive; delay nonnegative')
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
