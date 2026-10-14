"""Small public-page access comparison: browser headers in Requests, optional Selenium."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import ctypes
import gzip
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import threading
from urllib.parse import urljoin, urldefrag
from collections import Counter, defaultdict

VERSION = 'priority-probe-v9'
HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Upgrade-Insecure-Requests': '1',
}


def network_error_kind(crawler, exc):
    detail = str(exc).lower()
    if isinstance(exc, crawler.requests.exceptions.SSLError):
        return 'ssl_error'
    if isinstance(exc, crawler.requests.exceptions.ConnectTimeout):
        return 'connect_timeout'
    if isinstance(exc, crawler.requests.exceptions.ReadTimeout):
        return 'read_timeout'
    if any(s in detail for s in ('nameresolutionerror', 'getaddrinfo failed', 'failed to resolve')):
        return 'dns_error'
    if 'remotedisconnected' in detail or 'closed connection without response' in detail:
        return 'connection_closed'
    if 'connection reset' in detail:
        return 'connection_reset'
    if isinstance(exc, crawler.requests.exceptions.Timeout):
        return 'timeout'
    return 'connection_error'


def challenge_page(headers, body):
    headers = {k.lower(): v for k, v in headers.items()}
    lower = body[:1024 * 1024].lower()
    cookie_prompt = bool(re.search(
        rb'<(title|h1)\b[^>]*>\s*cookies must be enabled\s*</\1\s*>', lower))
    explicit_challenge = bool(re.search(
        rb'<(title|h1)\b[^>]*>\s*(?:attention required!?\s*(?:\|\s*cloudflare)?|just a moment(?:\.{1,3})?|'
        rb'access denied!?|checking your browser(?:\.{1,3})?|checking your browser before accessing[^<]*)\s*</\1\s*>', lower))
    cookie_reload = False
    if (len(body) < 8192 and b'document.cookie' in lower
            and (b'location.reload' in lower or b'location.replace' in lower)):
        from lxml import html
        try:
            tree = html.fromstring(body)
            visible = ' '.join(tree.xpath('//body//text()[not(ancestor::script) and not(ancestor::style)]')).strip()
            cookie_reload = len(visible) < 120
        except (ValueError, html.etree.ParserError):
            cookie_reload = True
    return (headers.get('cf-mitigated', '').lower() == 'challenge' or cookie_prompt or explicit_challenge
            or b'<title>just a moment' in lower
            or b'performing security verification' in lower
            or b'<title>attention required' in lower or cookie_reload)


def refresh_session(fetcher, user_agent):
    """Discard the failed connection pool while preserving HTTP session state."""
    previous = fetcher.session()
    cookies, headers = previous.cookies.copy(), dict(previous.headers)
    settings = {k: getattr(previous, k) for k in ('verify', 'cert', 'auth', 'trust_env')}
    proxies, params, hooks = dict(previous.proxies), dict(previous.params), dict(previous.hooks)
    previous.close()
    del fetcher.local.session
    session = fetcher.session()
    session.headers.update(headers)
    session.headers.update(HEADERS, **{'User-Agent': user_agent})
    session.cookies.update(cookies)
    session.proxies.update(proxies)
    session.params.update(params)
    session.hooks.update(hooks)
    for key, value in settings.items():
        setattr(session, key, value)


def wait_for_retry(crawler, fetcher, event, deadline, attempt):
    site = crawler.get_fld(event['url'], fail_silently=True) or crawler.host(event['url'])
    now = time.monotonic()
    wait = max(2 ** attempt + crawler.random.uniform(0, .5), fetcher.next_at.get(site, 0) - now)
    if wait + .1 >= deadline - now:
        event['retry_deferred'] = 'Cooldown/backoff exceeds remaining request budget'
        return False
    event['retry_wait_seconds'] = round(wait, 3)
    time.sleep(wait)
    return True


def request_record(crawler, fetcher, sample, out, user_agent, timeout, budget, *,
                   respect_robots=False, record_dir='records'):
    """Shared page fetcher for domain diagnostics and the corpus notebook."""
    begin = time.monotonic()
    deadline = begin + budget
    record = dict(sample, started_at=crawler.utc(), requests=[], redirects=[],
                  engine='curl_cffi' if getattr(fetcher, 'uses_browser_fingerprint', False) else 'requests',
                  request_mode='robots_enforced' if respect_robots else 'direct_public_page_probe',
                  robots={'mode': 'pending' if respect_robots else 'not_used_to_gate_access_probe'})
    current = sample['url']
    session = fetcher.session()
    if not getattr(fetcher, 'uses_browser_fingerprint', False):
        session.headers.update(HEADERS, **{'User-Agent': user_agent})
    try:
        for _ in range(8):
            robot_delay = None
            if respect_robots:
                try:
                    robot_delay, record['robots'] = fetcher.robot_policy(current)
                except crawler.CrawlError:
                    record['robots'] = getattr(fetcher.local, 'robot_evidence', {})
                    raise
            for attempt in range(1, fetcher.attempts + 1):
                if time.monotonic() >= deadline:
                    raise crawler.CrawlError('response_deadline', 'Request budget exhausted before retry')
                event = {'url': current, 'attempt': attempt, 'at': crawler.utc()}
                record['requests'].append(event)
                started = time.monotonic()
                failure = None
                try:
                    status, headers, body = fetcher.request_once(current, 10 * 1024 * 1024,
                                                               delay=robot_delay,
                                                               timeout=timeout, deadline=deadline)
                except (crawler.requests.RequestException, OSError) as exc:
                    failure = exc
                    event.update(error=str(exc)[:500], exception_class=type(exc).__name__,
                                 error_kind=network_error_kind(crawler, exc))
                finally:
                    event['elapsed_seconds'] = round(time.monotonic() - started, 3)
                if failure is not None:
                    retryable = not isinstance(failure, crawler.requests.exceptions.SSLError)
                    event['retryable'] = retryable
                    if retryable and attempt < fetcher.attempts and wait_for_retry(crawler, fetcher, event, deadline, attempt):
                        if not getattr(fetcher, 'uses_browser_fingerprint', False):
                            refresh_session(fetcher, user_agent)
                            event['session_reset_for_retry'] = True
                        continue
                    record.update(error_kind=event['error_kind'], retryable=retryable)
                    if event.get('retry_deferred'):
                        record['retry_deferred'] = event['retry_deferred']
                    raise crawler.CrawlError('network_error', str(failure)[:500]) from failure
                headers = crawler.requests.structures.CaseInsensitiveDict(headers)
                event.update(http_status=status, response_headers={k: v for k, v in headers.items()
                             if k.lower() in ('content-type', 'location', 'server', 'retry-after', 'cf-mitigated', 'cf-ray')})
                raw_path = Path('raw/requests') / f"{sample['id']}_{crawler.digest(body)}.gz"
                crawler.atomic_bytes(Path(out) / raw_path, gzip.compress(body, mtime=0))
                event.update(raw_path=raw_path.as_posix(), raw_sha256=crawler.digest(body))
                event['retryable'] = status in (408, 429) or 500 <= status < 600
                if event['retryable'] and attempt < fetcher.attempts:
                    if wait_for_retry(crawler, fetcher, event, deadline, attempt):
                        continue
                    record['retry_deferred'] = event['retry_deferred']
                break
            record.update(http_status=status, content_type=headers.get('Content-Type', ''), final_url=current,
                          raw_path=raw_path.as_posix(), raw_sha256=crawler.digest(body),
                          response_headers=event['response_headers'])
            if status in (301, 302, 303, 307, 308) and headers.get('Location'):
                next_url = urljoin(current, headers['Location'])
                record['redirects'].append({'from': current, 'to': next_url, 'http_status': status})
                current = next_url
                continue
            challenge = challenge_page(headers, body)
            if not 200 <= status < 300 or challenge:
                # Keep the HTTP error body and its visible title for diagnosis.
                try:
                    record['title'] = crawler.extract(body, record['content_type'], current).get('title', '')
                except Exception:
                    pass
                record.update(challenge_detected=challenge, retryable=event['retryable'] and not challenge,
                              error_kind=f'http_{status}_challenge' if challenge else f'http_{status}')
                raise crawler.CrawlError('http_error', f'HTTP {status}' + ('; security challenge page' if challenge else ''))
            doc = crawler.extract(body, record['content_type'], current)
            record.update(doc, **crawler.quality(doc), status='extracted')
            crawler.flag_redirect(record)
            break
        else:
            raise crawler.CrawlError('redirect_limit')
    except crawler.CrawlError as exc:
        record.update(status=exc.status, error=str(exc)[:1000])
        if exc.status == 'response_deadline':
            record.update(error_kind='request_budget_exhausted', retryable=True)
    except Exception as exc:
        record.update(status='unexpected_error', error=f'{type(exc).__name__}: {exc}'[:1000])
    record.update(finished_at=crawler.utc(), elapsed_seconds=round(time.monotonic() - begin, 3))
    crawler.write_json(Path(out) / record_dir / f"{sample['id']}.json", record)
    return record


def seed_successful_requests(crawler, out, samples, source, *, record_dir='records'):
    """Start a recovery run with verified 2xx raw; failed checkpoints stay pending."""
    out, source = Path(out).resolve(), Path(source).resolve()
    if source == out or not (source / 'manifest.json').is_file():
        raise ValueError('Recovery source must be an existing different run with manifest.json.')
    marker = out / 'recovery_manifest.json'
    identity = {'source_run': str(source), 'samples': [[s['id'], s['url']] for s in samples],
                'record_dir': record_dir}
    if marker.exists():
        saved = crawler.load_json(marker)
        if any(saved.get(k) != v for k, v in identity.items()):
            raise ValueError('Recovery source changed; use a new run directory.')
        return saved
    if list((out / record_dir).glob('*.json')):
        raise ValueError('Recovery requires a new run directory.')
    reused, skipped = [], []
    for sample in samples:
        path = source / 'records' / f"{sample['id']}.json"
        if not path.exists():
            skipped.append(sample['id'])
            continue
        record = crawler.load_json(path)
        if (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
            raise ValueError('Recovery source ID/URL mismatch.')
        if (record.get('status') != 'extracted' or record.get('challenge_detected')
                or not 200 <= (record.get('http_status') or 0) < 300):
            skipped.append(sample['id'])
            continue
        raw_source = (source / record['raw_path']).resolve()
        if not raw_source.is_relative_to(source):
            raise ValueError('Recovery raw path is outside source run.')
        with gzip.open(raw_source, 'rb') as stream:
            body = stream.read(10 * 1024 * 1024 + 1)
        if len(body) > 10 * 1024 * 1024 or crawler.digest(body) != record['raw_sha256']:
            raise ValueError('Recovery raw hash/size mismatch.')
        if challenge_page(record.get('response_headers', {}), body):
            skipped.append(sample['id'])
            continue
        # Preserve per-attempt evidence too; otherwise recovery leaves dangling raw paths.
        def copy_evidence(value):
            if isinstance(value, list):
                for child in value:
                    copy_evidence(child)
            elif isinstance(value, dict):
                if value.get('raw_path'):
                    original = (source / value['raw_path']).resolve()
                    target = (out / value['raw_path']).resolve()
                    if not original.is_relative_to(source) or not target.is_relative_to(out):
                        raise ValueError('Recovery evidence path is outside run.')
                    with gzip.open(original, 'rb') as stream:
                        evidence = stream.read(10 * 1024 * 1024 + 1)
                    if len(evidence) > 10 * 1024 * 1024 or (value.get('raw_sha256') and crawler.digest(evidence) != value['raw_sha256']):
                        raise ValueError('Recovery evidence hash/size mismatch.')
                    crawler.atomic_bytes(target, gzip.compress(evidence, mtime=0))
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        copy_evidence(child)
        copy_evidence(record)
        crawler.write_json(out / 'recovery_records' / f"{sample['id']}.json", record)
        for key in ('requests_record_path', 'browser_record_path', 'screenshot_path'):
            record.pop(key, None)
        raw_path = Path('raw/requests') / f"{sample['id']}_{crawler.digest(body)}.gz"
        doc = crawler.extract(body, record['content_type'], record.get('final_url') or sample['url'])
        record.pop('domain_parser_fallback', None)
        record.update(doc, **crawler.quality(doc), **sample, reused_from=str(source),
                      reprocessed_at=crawler.utc(), raw_path=raw_path.as_posix(),
                      recovery_record_path=f"recovery_records/{sample['id']}.json")
        crawler.atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
        crawler.write_json(out / record_dir / f"{sample['id']}.json", record)
        reused.append(sample['id'])
    saved = dict(identity, reused_ids=reused, retry_ids=skipped, at=crawler.utc())
    crawler.write_json(marker, saved)
    return saved


def url_error_reason(row):
    """Access/extraction failures are distinct from non-fatal quality review flags."""
    status = row.get('status', '')
    if status not in ('extracted', 'rendered'):
        return row.get('error_kind') or status or 'missing_status'
    http_status = row.get('http_status')
    if http_status is None or not 200 <= http_status < 300:
        return f'http_{http_status}' if http_status is not None else 'missing_http_status'
    if row.get('challenge_detected') or 'error_or_challenge' in (row.get('quality_flags') or []):
        return row.get('error_kind') or 'security_challenge'
    if not (row.get('text') or '').strip():
        return 'empty_text'
    return None


class CrawlProgress:
    """Print failed URLs immediately; summarize progress and quality flags in batches."""
    def __init__(self, engine, scheduled, log_every=300):
        if type(log_every) is not int or log_every < 1:
            raise ValueError('log_every must be a positive integer.')
        self.engine, self.scheduled, self.log_every = engine, scheduled, log_every
        self.completed = self.failed = self.last_printed = 0
        self.statuses = Counter()
        self.quality_statuses = Counter()
        self.quality_flags = Counter()
        self.lock = threading.Lock()

    def _summary(self):
        print(json.dumps({'engine': self.engine, 'completed': self.completed,
                          'scheduled': self.scheduled, 'failed': self.failed,
                          'statuses': dict(self.statuses),
                          'quality_statuses': dict(self.quality_statuses),
                          'quality_flags': dict(self.quality_flags)}, ensure_ascii=False), flush=True)
        self.last_printed = self.completed

    def record(self, row):
        status = row.get('status', '')
        reason = url_error_reason(row)
        with self.lock:
            self.completed += 1
            self.statuses[status] += 1
            self.quality_statuses[row.get('quality_status') or 'unknown'] += 1
            self.quality_flags.update(set(row.get('quality_flags') or []))
            if reason:
                self.failed += 1
                print(json.dumps({'engine': self.engine, 'event': 'url_error',
                                  'domain': row.get('domain'), 'id': row.get('id'),
                                  'url': row.get('url'), 'status': status,
                                  'http': row.get('http_status'), 'chars': row.get('char_count'),
                                  'quality_status': row.get('quality_status'),
                                  'quality_flags': row.get('quality_flags', []),
                                  'error_kind': row.get('error_kind') or reason,
                                  'error': row.get('error') or reason}, ensure_ascii=False), flush=True)
            if self.completed % self.log_every == 0 or self.completed == self.scheduled:
                self._summary()

    def finish(self):
        with self.lock:
            if self.completed > self.last_printed:
                self._summary()


def crawl_requests(crawler, out, samples, *, workers=5, delay=1., attempts=3, user_agent,
                   timeout=(20., 45.), budget=180., max_new=None, respect_robots=False,
                   robots_options=None, record_dir='records', on_record=None, lock_run=True, log_every=300):
    out = Path(out)
    if any(type(v) is not int or v < 1 for v in (workers, attempts)):
        raise ValueError('Workers and attempts must be positive integers.')
    if len(timeout) != 2 or any(isinstance(v, bool) or not math.isfinite(v) or v <= 0 for v in (*timeout, budget)):
        raise ValueError('Timeouts and budget must be finite and positive.')
    if (not isinstance(user_agent, str) or not user_agent.strip()
            or any(ch in user_agent for ch in ('\r', '\n'))):
        raise ValueError('User-Agent must be a valid non-empty header.')
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('Delay must be finite and non-negative.')
    if max_new is not None and (type(max_new) is not int or max_new < 1):
        raise ValueError('max_new must be a positive integer or None.')
    fetcher = crawler.Fetcher(out, delay=delay, attempts=attempts, **(robots_options or {}))
    identity = {'version': VERSION, 'script_sha256': crawler.file_hash(__file__),
                'crawler_sha256': crawler.file_hash(crawler.__file__), 'user_agent': user_agent,
                'headers': HEADERS, 'request_mode': 'robots_enforced' if respect_robots else 'direct_public_page_probe',
                'robots_options': fetcher.robots_config if respect_robots else None, 'record_dir': record_dir,
                'timeout': list(timeout), 'budget': budget, 'attempts': attempts, 'delay': delay,
                'python': sys.version, 'platform': sys.platform}
    if (out / 'priority_probe_config.json').exists() and crawler.load_json(out / 'priority_probe_config.json') != identity:
        raise ValueError('Priority probe config changed; use a new run directory.')
    crawler.write_json(out / 'priority_probe_config.json', identity)
    pending = []
    for sample in samples:
        path = out / record_dir / f"{sample['id']}.json"
        if path.exists():
            record = crawler.load_json(path)
            if (record['id'], record['url']) != (sample['id'], sample['url']):
                raise ValueError('Checkpoint ID/URL mismatch.')
        else:
            pending.append(sample)
    if max_new is not None:
        pending = pending[:max_new]
    progress = CrawlProgress('requests', len(pending), log_every)
    groups = defaultdict(list)
    for sample in pending:
        site = crawler.get_fld(sample['url'], fail_silently=True) or sample['domain']
        groups[site].append(sample)
    stop = threading.Event()
    def domain_job(group):
        # One active sample per registered domain: its budget is not spent queued behind its siblings.
        completed = 0
        for sample in group:
            if stop.is_set():
                break
            row = request_record(crawler, fetcher, sample, out, user_agent, timeout, budget,
                                 respect_robots=respect_robots, record_dir=record_dir)
            if on_record:
                on_record(row)
            progress.record(row)
            completed += 1
        return completed
    with (crawler.run_lock(out) if lock_run else nullcontext()), ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(domain_job, group) for group in groups.values()]
        try:
            for future in as_completed(futures):
                future.result()
        except BaseException:
            # Executor shutdown waits for workers; stop their queues before waiting.
            # The current request may finish and commit its checkpoint within its budget.
            stop.set()
            for future in futures:
                future.cancel()
            raise
        finally:
            progress.finish()
    return [crawler.load_json(out / record_dir / f"{s['id']}.json") for s in samples
            if (out / record_dir / f"{s['id']}.json").exists()]


def prepare_pubmed_selenium(crawler, out, samples, *, enabled=True, max_new=None,
                           respect_robots=False, robots_options=None, record_dir='records'):
    """Record explicit HTTP skips, then route PubMed directly to the browser."""
    if type(enabled) is not bool:
        raise ValueError('pubmed_selenium_first must be bool.')
    if max_new is not None and (type(max_new) is not int or max_new < 1):
        raise ValueError('max_new must be a positive integer or None.')
    out = Path(out)
    if not any(crawler.host(sample['url']) == 'pubmed.ncbi.nlm.nih.gov' for sample in samples):
        return [], 0
    routing_path = out / 'selenium_first_config.json'
    routing = {'pubmed_selenium_first': enabled, 'respect_robots': respect_robots, 'record_dir': record_dir}
    if routing_path.exists() and crawler.load_json(routing_path) != routing:
        raise ValueError('Selenium-first config changed; use a new run directory and recovery.')
    crawler.write_json(routing_path, routing)
    if not enabled:
        return [], 0
    selected, created = [], 0
    fetcher = None
    for sample in samples:
        if crawler.host(sample['url']) != 'pubmed.ncbi.nlm.nih.gov':
            continue
        path = out / record_dir / f"{sample['id']}.json"
        if path.exists():
            record = crawler.load_json(path)
            if (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
                raise ValueError('Checkpoint ID/URL mismatch.')
        else:
            if max_new is not None and created >= max_new:
                continue
            record = dict(sample, engine='requests', status='skipped_selenium_first',
                          request_mode='not_run_selenium_first', requests=[], http_status=None,
                          started_at=crawler.utc(), elapsed_seconds=0,
                          robots={'mode': 'not_used_to_gate_access_probe'})
            if respect_robots:
                fetcher = fetcher or crawler.Fetcher(out, delay=0, attempts=1, **(robots_options or {}))
                try:
                    delay, record['robots'] = fetcher.robot_policy(sample['url'])
                    record['browser_min_delay'] = delay or 0
                except crawler.CrawlError as exc:
                    record.update(status=exc.status, error=str(exc),
                                  robots=getattr(fetcher.local, 'robot_evidence', {}))
            crawler.write_json(path, record)
            created += 1
        if (record.get('status', '').startswith('robots_')
                or record.get('status') in ('invalid_url', 'unsafe_address')):
            continue
        selected.append(dict(sample, browser_route='selenium_first',
                             browser_min_delay=record.get('browser_min_delay', 0)))
    return selected, created


def browser_fallback_reason(record):
    """Route every failed request or non-accepted extraction to Selenium."""
    status = record.get('status', '')
    if status.startswith('robots_') or status in ('invalid_url', 'unsafe_address'):
        return None
    if record.get('challenge_detected'):
        return record.get('error_kind') or 'security_challenge'
    if status != 'extracted':
        return record.get('error_kind') or status or 'missing_status'
    http_status = record.get('http_status')
    if http_status is None or not 200 <= http_status < 300:
        return f'http_{http_status}' if http_status is not None else 'missing_http_status'
    if not (record.get('text') or '').strip():
        return 'empty_text'
    quality = record.get('quality_status')
    if quality != 'accepted':
        return 'quality_' + (quality or 'unknown')
    if record.get('quality_flags'):
        return 'quality_flags'
    return None


def needs_browser(record):
    return browser_fallback_reason(record) is not None


def select_browser_samples(samples, records, mode):
    if mode not in ('off', 'failed_only', 'first_each_domain_and_failures', 'all'):
        raise ValueError('Unknown BROWSER_TEST_MODE.')
    if mode == 'off':
        return []
    by_id = {r['id']: r for r in records}
    result = []
    for sample in samples:
        record = by_id.get(sample['id'])
        if not record:
            continue
        if record.get('status', '').startswith('robots_') or record.get('status') in ('invalid_url', 'unsafe_address'):
            continue
        first = sample.get('sample_index') == 0
        if mode == 'all' or needs_browser(record) or (mode == 'first_each_domain_and_failures' and first):
            result.append(sample)
    return result


def main_document_status(messages, final_url, frame_id):
    """Do not confuse image/iframe responses with the main document's HTTP status."""
    responses = []
    for item in messages:
        try:
            message = json.loads(item['message'])['message']
        except (ValueError, KeyError, TypeError):
            continue
        params = message.get('params', {})
        if message.get('method') != 'Network.responseReceived' or params.get('type') != 'Document':
            continue
        response = params.get('response', {})
        if params.get('frameId') == frame_id and urldefrag(response.get('url', ''))[0] == urldefrag(final_url)[0]:
            responses.append(response)
    return int(responses[-1]['status']) if responses else None


def browser_outcome(record):
    status = record.get('http_status')
    if status is not None and not 200 <= status < 300:
        return 'http_error', f'Browser HTTP {status}'
    if record.get('final_url', '').startswith(('chrome-error:', 'data:')):
        return 'browser_network_error', record.get('browser_title', '')
    if record.get('final_url') == 'about:blank' or not record.get('char_count'):
        if record.get('navigation_warning'):
            return 'browser_navigation_timeout', record['navigation_warning']
        return 'browser_empty_document', 'Trình duyệt không lấy được nội dung bài viết.'
    return 'rendered', ''


def browser_page_ready(driver):
    value = driver.execute_script('return {title: document.title, text: document.body ? document.body.innerText : ""}')
    title, text = value['title'].lower(), value['text'].lower()
    challenge = (title.startswith(('just a moment', 'attention required'))
                 or 'performing security verification' in text or 'verify you are human' in text)
    return len(text) >= 150 and not challenge


def browser_attempt(crawler, driver, sample, out, *, load_timeout, wait_seconds, attempt):
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait
    started = time.monotonic()
    record = dict(sample, engine='selenium', started_at=crawler.utc(), attempt=attempt)
    try:
        crawler.Fetcher.validate(sample['url'])
        driver.set_page_load_timeout(load_timeout)
        driver.get('about:blank')
        driver.get_log('performance')
        try:
            driver.get(sample['url'])
        except TimeoutException as exc:
            record['navigation_warning'] = str(exc)[:500]
            driver.execute_script('window.stop()')
        try:
            WebDriverWait(driver, wait_seconds).until(browser_page_ready)
        except TimeoutException:
            record['render_wait_expired'] = True
        record.update(final_url=driver.current_url, browser_title=driver.title)
        frame_id = driver.execute_cdp_cmd('Page.getFrameTree', {})['frameTree']['frame']['id']
        record['http_status'] = main_document_status(driver.get_log('performance'), record['final_url'], frame_id)
        body = driver.page_source.encode('utf-8')
        raw_path = Path('raw/selenium') / f"{sample['id']}_{crawler.digest(body)}.gz"
        crawler.atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
        record.update(raw_path=raw_path.as_posix(), raw_sha256=crawler.digest(body))
        shot = Path('browser_screenshots') / f"{sample['id']}_a{attempt}.png"
        (out / shot).parent.mkdir(parents=True, exist_ok=True)
        if driver.save_screenshot(str(out / shot)):
            record['screenshot_path'] = shot.as_posix()
        doc = crawler.extract(body, 'text/html; charset=utf-8', record['final_url'])
        record.update(doc, **crawler.quality(doc))
        crawler.flag_redirect(record)
        record['status'], error = browser_outcome(record)
        if error:
            record['error'] = error
        if challenge_page({}, body):
            record.update(challenge_detected=True, quality_status='rejected',
                          error_kind=f"http_{record.get('http_status')}_challenge")
            if 'error_or_challenge' not in record['quality_flags']:
                record['quality_flags'].append('error_or_challenge')
    except Exception as exc:
        record.update(status='browser_error', error=f'{type(exc).__name__}: {exc}'[:1000])
    record.update(finished_at=crawler.utc(), elapsed_seconds=round(time.monotonic() - started, 3))
    return record


def retry_browser(record):
    if record.get('challenge_detected'):
        return False
    return (record.get('status') in ('browser_navigation_timeout', 'browser_network_error', 'browser_empty_document')
            or (record.get('http_status') or 0) in (408, 429)
            or 500 <= (record.get('http_status') or 0) < 600)


def access_outcome(record, browser=None):
    """Prefer usable browser content over a failed/poorer Requests extraction."""
    def accessible(item, statuses):
        return (item.get('status') in statuses and not item.get('challenge_detected')
                and 'error_or_challenge' not in (item.get('quality_flags') or ())
                and not re.match(r'^(?:cookies must be enabled|checking your browser)\b',
                                 (item.get('title') or item.get('browser_title') or '').strip(), re.I)
                and 200 <= (item.get('http_status') or 0) < 300)
    request_ok = accessible(record, ('extracted',))
    browser_ok = bool(browser and accessible(browser, ('rendered',)))

    def content_score(item):
        return ({'accepted': 3, 'review': 2, 'rejected': 1}.get(item.get('quality_status'), 0),
                bool((item.get('text') or '').strip()),
                'short_text' not in (item.get('quality_flags') or ()),
                -len(item.get('quality_flags') or ()))

    if browser_ok and (browser.get('browser_route') == 'selenium_first'
                       or not request_ok or content_score(browser) > content_score(record)):
        return 'VAO_DUOC', 'selenium', browser
    if request_ok:
        return 'VAO_DUOC', 'requests', record
    if record.get('status') == 'skipped_selenium_first':
        if browser:
            return 'KHONG_VAO_DUOC', 'selenium', browser
        return 'CHUA_CHAY', 'requests', record
    return ('CHUA_CHAY' if not record or record.get('status') == 'pending' else 'KHONG_VAO_DUOC'), 'requests', record


def prepare_chrome_runtime(crawler, out):
    """Install missing Chrome shared libraries on apt-based Linux notebook hosts."""
    out = Path(out)
    report = {'platform': sys.platform, 'checked_at': crawler.utc(), 'installed_packages': []}
    if not sys.platform.startswith('linux'):
        report['status'] = 'native_platform'
        crawler.write_json(out / 'browser_runtime.json', report)
        return report
    libraries = {
        'libatk-1.0.so.0': ('libatk1.0-0t64', 'libatk1.0-0'),
        'libatk-bridge-2.0.so.0': ('libatk-bridge2.0-0t64', 'libatk-bridge2.0-0'),
        'libnss3.so': ('libnss3',), 'libnspr4.so': ('libnspr4',),
        'libgbm.so.1': ('libgbm1',), 'libxkbcommon.so.0': ('libxkbcommon0',),
        'libXcomposite.so.1': ('libxcomposite1',), 'libXdamage.so.1': ('libxdamage1',),
        'libXfixes.so.3': ('libxfixes3',), 'libXrandr.so.2': ('libxrandr2',),
        'libasound.so.2': ('libasound2t64', 'libasound2'),
        'libcups.so.2': ('libcups2t64', 'libcups2'),
        'libpangocairo-1.0.so.0': ('libpangocairo-1.0-0',),
    }

    def missing_libraries():
        missing = []
        for library in libraries:
            try:
                ctypes.CDLL(library)
            except OSError:
                missing.append(library)
        return missing

    missing = missing_libraries()
    report['missing_before'] = missing
    try:
        if missing:
            apt, cache = shutil.which('apt-get'), shutil.which('apt-cache')
            if not apt or not cache:
                raise RuntimeError('Missing Chrome libraries; apt-get/apt-cache unavailable: ' + ', '.join(missing))
            prefix = []
            if os.geteuid() != 0:
                sudo = shutil.which('sudo')
                if not sudo:
                    raise RuntimeError('Installing Chrome libraries requires root or passwordless sudo.')
                prefix = [sudo, '-n']
            environment = dict(os.environ, DEBIAN_FRONTEND='noninteractive', LC_ALL='C')

            def run_install(arguments, timeout):
                result = subprocess.run(prefix + arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace',
                                        env=environment, timeout=timeout)
                with (out / 'chrome_dependencies.log').open('a', encoding='utf-8') as log:
                    log.write(' '.join(prefix + arguments) + '\n' + (result.stdout or '') + '\n')
                if result.returncode:
                    raise RuntimeError('Chrome library installation failed: ' + (result.stdout or '')[-1200:])

            run_install([apt, 'update', '-qq'], 180)
            packages = []
            for library in missing:
                for package in libraries[library]:
                    available = subprocess.run([cache, 'policy', package], stdout=subprocess.PIPE,
                                               stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                               errors='replace', env=environment, timeout=30)
                    candidate = re.search(r'Candidate:\s*(\S+)', available.stdout or '')
                    if available.returncode == 0 and candidate and candidate.group(1) != '(none)':
                        packages.append(package)
                        break
                else:
                    raise RuntimeError('No apt package available for ' + library)
            packages = sorted(set(packages))
            run_install([apt, 'install', '-y', '--no-install-recommends', *packages], 300)
            report['installed_packages'] = packages
        report['missing_after'] = missing_libraries()
        if report['missing_after']:
            raise RuntimeError('Chrome libraries still unavailable: ' + ', '.join(report['missing_after']))
        report['status'] = 'ready'
    except Exception as exc:
        report.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        crawler.write_json(out / 'browser_runtime.json', report)
        raise
    crawler.write_json(out / 'browser_runtime.json', report)
    return report


def create_browser(crawler, out, *, user_agent=None, chrome_binary=None, load_timeout=45.):
    out = Path(out)
    prepare_chrome_runtime(crawler, out)
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    options = webdriver.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--remote-debugging-pipe')
    options.add_argument('--window-size=1280,900')
    if user_agent:
        options.add_argument('--user-agent=' + user_agent)
    if sys.platform != 'win32':
        options.add_argument('--no-sandbox')
    if chrome_binary:
        options.binary_location = str(chrome_binary)
    options.page_load_strategy = 'eager'
    options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
    os.environ['SE_CACHE_PATH'] = str((out.parent / '.selenium_cache').resolve())
    os.environ['SE_TIMEOUT'] = '120'
    service = Service(log_output=str(out / 'chromedriver.log'),
                      popen_kw={'creation_flags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {})
    driver = webdriver.Chrome(service=service, options=options)
    try:
        driver.set_page_load_timeout(load_timeout)
        driver.execute_cdp_cmd('Network.enable', {})
        crawler.write_json(out / 'browser_environment.json', {
            'browser_version': driver.capabilities.get('browserVersion'),
            'user_agent': driver.execute_script('return navigator.userAgent'),
            'chrome': driver.capabilities.get('chrome', {}), 'load_timeout': load_timeout})
        (out / 'browser_setup_error.json').unlink(missing_ok=True)
        return driver
    except Exception:
        driver.quit()
        raise


def browser_preflight(crawler, out, **options):
    """Verify Chrome starts before spending time on the Requests pass."""
    driver = None
    try:
        driver = create_browser(crawler, Path(out), **options)
        driver.get('data:text/html,<title>crawl-preflight</title><main>Chrome ready</main>')
        if driver.title != 'crawl-preflight':
            raise RuntimeError('Chrome preflight page did not load.')
        crawler.write_json(Path(out) / 'browser_preflight.json', {'status': 'ready', 'at': crawler.utc()})
    except Exception as exc:
        crawler.write_json(Path(out) / 'browser_preflight.json', {
            'status': 'failed', 'error': f'{type(exc).__name__}: {exc}'[:1500], 'at': crawler.utc()})
        crawler.write_json(Path(out) / 'browser_setup_error.json', {
            'status': 'browser_setup_error', 'error': f'{type(exc).__name__}: {exc}'[:1500], 'at': crawler.utc()})
        raise RuntimeError('Chrome preflight failed; inspect browser_runtime.json and chromedriver.log.') from exc
    finally:
        if driver:
            driver.quit()


def crawl_browser(crawler, out, samples, *, user_agent=None, chrome_binary=None, load_timeout=45., wait_seconds=15., delay=1., attempts=2, on_record=None, log_every=300):
    """A normal isolated headless Chrome session; outputs are separate from Requests records."""
    out = Path(out)
    if type(attempts) is not int or attempts < 1:
        raise ValueError('Browser attempts must be a positive integer.')
    pending = [s for s in samples if not (out / 'browser_records' / f"{s['id']}.json").exists()]
    progress = CrawlProgress('selenium', len(pending), log_every)
    if not pending:
        return
    driver = None
    try:
        driver = create_browser(crawler, out, user_agent=user_agent,
                                chrome_binary=chrome_binary, load_timeout=load_timeout)
    except Exception as exc:
        error = {'status': 'browser_setup_error', 'error': f'{type(exc).__name__}: {exc}'[:1500], 'at': crawler.utc()}
        crawler.write_json(out / 'browser_setup_error.json', error)
        if driver:
            driver.quit()
        print(json.dumps(error, ensure_ascii=False), flush=True)
        return
    try:
        for sample in pending:
            started = time.monotonic()
            history = []
            for attempt in range(1, attempts + 1):
                record = browser_attempt(crawler, driver, sample, out, load_timeout=load_timeout,
                                         wait_seconds=wait_seconds, attempt=attempt)
                history.append({k: v for k, v in record.items() if k not in ('text', 'source_images')})
                if not retry_browser(record) or attempt == attempts:
                    break
                time.sleep(max(delay, 2 ** attempt))
            record.update(browser_attempts=history, attempt_count=len(history))
            record.update(finished_at=crawler.utc(), elapsed_seconds=round(time.monotonic() - started, 3))
            crawler.write_json(out / 'browser_records' / f"{sample['id']}.json", record)
            if on_record:
                on_record(record)
            progress.record(record)
            time.sleep(max(delay, sample.get('browser_min_delay', 0)))
    finally:
        progress.finish()
        driver.quit()
