"""Small public-page access comparison: browser headers in Requests, optional Selenium."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import gzip
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urljoin, urldefrag
from collections import defaultdict

VERSION = 'priority-probe-v3'
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
    return (headers.get('cf-mitigated', '').lower() == 'challenge'
            or b'<title>just a moment' in lower
            or b'performing security verification' in lower
            or b'<title>attention required' in lower)


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
                  engine='requests', request_mode='robots_enforced' if respect_robots else 'direct_public_page_probe',
                  robots={'mode': 'pending' if respect_robots else 'not_used_to_gate_access_probe'})
    current = sample['url']
    session = fetcher.session()
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
        record.update(doc, **crawler.quality(doc), **sample, reused_from=str(source),
                      reprocessed_at=crawler.utc(), raw_path=raw_path.as_posix(),
                      recovery_record_path=f"recovery_records/{sample['id']}.json")
        crawler.atomic_bytes(out / raw_path, gzip.compress(body, mtime=0))
        crawler.write_json(out / record_dir / f"{sample['id']}.json", record)
        reused.append(sample['id'])
    saved = dict(identity, reused_ids=reused, retry_ids=skipped, at=crawler.utc())
    crawler.write_json(marker, saved)
    return saved


def crawl_requests(crawler, out, samples, *, workers=5, delay=1., attempts=3, user_agent,
                   timeout=(20., 45.), budget=180., max_new=None, respect_robots=False,
                   robots_options=None, record_dir='records', on_record=None, lock_run=True):
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
    groups = defaultdict(list)
    for sample in pending:
        site = crawler.get_fld(sample['url'], fail_silently=True) or sample['domain']
        groups[site].append(sample)
    def domain_job(group):
        # One active sample per registered domain: its budget is not spent queued behind its siblings.
        for sample in group:
            row = request_record(crawler, fetcher, sample, out, user_agent, timeout, budget,
                                 respect_robots=respect_robots, record_dir=record_dir)
            if on_record:
                on_record(row)
            print(json.dumps({'domain': row['domain'], 'id': row['id'], 'status': row['status'],
                              'http': row.get('http_status'), 'chars': row.get('char_count')}, ensure_ascii=False), flush=True)
        return len(group)
    with (crawler.run_lock(out) if lock_run else nullcontext()), ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(domain_job, group) for group in groups.values()]
        completed = 0
        for future in as_completed(futures):
            completed += future.result()
            print(json.dumps({'completed': completed, 'scheduled': len(pending)}, ensure_ascii=False), flush=True)
    return [crawler.load_json(out / record_dir / f"{s['id']}.json") for s in samples
            if (out / record_dir / f"{s['id']}.json").exists()]


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
        needs_browser = record.get('status') != 'extracted'
        first = sample.get('sample_index') == 0
        if mode == 'all' or needs_browser or (mode == 'first_each_domain_and_failures' and first):
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
    """Report a successful browser fallback without overwriting Requests evidence."""
    def accessible(item, statuses):
        return (item.get('status') in statuses and not item.get('challenge_detected')
                and 200 <= (item.get('http_status') or 0) < 300)
    if accessible(record, ('extracted',)):
        return 'VAO_DUOC', 'requests', record
    if browser and accessible(browser, ('rendered',)):
        return 'VAO_DUOC', 'selenium', browser
    return ('CHUA_CHAY' if not record or record.get('status') == 'pending' else 'KHONG_VAO_DUOC'), 'requests', record


def crawl_browser(crawler, out, samples, *, user_agent=None, chrome_binary=None, load_timeout=45., wait_seconds=15., delay=1., attempts=2, on_record=None):
    """A normal isolated headless Chrome session; outputs are separate from Requests records."""
    out = Path(out)
    if type(attempts) is not int or attempts < 1:
        raise ValueError('Browser attempts must be a positive integer.')
    pending = [s for s in samples if not (out / 'browser_records' / f"{s['id']}.json").exists()]
    if not pending:
        return
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--disable-dev-shm-usage')
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
        driver.set_page_load_timeout(load_timeout)
        driver.execute_cdp_cmd('Network.enable', {})
        crawler.write_json(out / 'browser_environment.json', {
            'browser_version': driver.capabilities.get('browserVersion'), 'user_agent': driver.execute_script('return navigator.userAgent'),
            'chrome': driver.capabilities.get('chrome', {}), 'load_timeout': load_timeout, 'wait_seconds': wait_seconds})
        (out / 'browser_setup_error.json').unlink(missing_ok=True)
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
            print(json.dumps({'browser_id': sample['id'], 'domain': sample['domain'], 'status': record['status'],
                              'http': record.get('http_status'), 'chars': record.get('char_count')}, ensure_ascii=False), flush=True)
            time.sleep(delay)
    finally:
        driver.quit()
