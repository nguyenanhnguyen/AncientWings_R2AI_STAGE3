"""Small public-page access comparison: browser headers in Requests, optional Selenium."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urljoin, urldefrag
from collections import defaultdict

VERSION = 'priority-probe-v1'
HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Upgrade-Insecure-Requests': '1',
}


def request_record(crawler, fetcher, sample, out, user_agent, timeout, budget):
    """Fetch the supplied public URL directly; robots policy does not gate this diagnostic."""
    begin = time.monotonic()
    deadline = begin + budget
    record = dict(sample, started_at=crawler.utc(), requests=[], redirects=[],
                  engine='requests', request_mode='direct_public_page_probe',
                  robots={'mode': 'not_used_to_gate_access_probe'})
    current = sample['url']
    session = fetcher.session()
    session.headers.update(HEADERS, **{'User-Agent': user_agent})
    try:
        for _ in range(8):
            for attempt in range(1, fetcher.attempts + 1):
                event = {'url': current, 'attempt': attempt, 'at': crawler.utc()}
                record['requests'].append(event)
                started = time.monotonic()
                try:
                    status, headers, body = fetcher.request_once(current, 10 * 1024 * 1024,
                                                               timeout=timeout, deadline=deadline)
                    event.update(http_status=status, response_headers={k: v for k, v in headers.items()
                                 if k.lower() in ('content-type', 'location', 'server', 'retry-after')})
                except (crawler.requests.RequestException, OSError) as exc:
                    event.update(error=str(exc)[:500], exception_class=type(exc).__name__)
                    if attempt == fetcher.attempts or time.monotonic() + 2 ** attempt >= deadline:
                        raise crawler.CrawlError('network_error', str(exc)[:500]) from exc
                    time.sleep(2 ** attempt)
                    continue
                finally:
                    event['elapsed_seconds'] = round(time.monotonic() - started, 3)
                if status in (408, 429, 500, 502, 503, 504) and attempt < fetcher.attempts:
                    if time.monotonic() + 2 ** attempt < deadline:
                        time.sleep(2 ** attempt)
                        continue
                break
            record.update(http_status=status, content_type=headers.get('Content-Type', ''), final_url=current)
            if status in (301, 302, 303, 307, 308) and headers.get('Location'):
                next_url = urljoin(current, headers['Location'])
                record['redirects'].append({'from': current, 'to': next_url, 'http_status': status})
                current = next_url
                continue
            raw_path = Path('raw/requests') / f"{sample['id']}_{crawler.digest(body)}.gz"
            crawler.atomic_bytes(Path(out) / raw_path, gzip.compress(body, mtime=0))
            record.update(raw_path=raw_path.as_posix(), raw_sha256=crawler.digest(body))
            if not 200 <= status < 300:
                # Keep the HTTP error body and its visible title for diagnosis.
                try:
                    record['title'] = crawler.extract(body, record['content_type'], current).get('title', '')
                except Exception:
                    pass
                raise crawler.CrawlError('http_error', f'HTTP {status}')
            doc = crawler.extract(body, record['content_type'], current)
            record.update(doc, **crawler.quality(doc), status='extracted')
            crawler.flag_redirect(record)
            break
        else:
            raise crawler.CrawlError('redirect_limit')
    except crawler.CrawlError as exc:
        record.update(status=exc.status, error=str(exc)[:1000])
    except Exception as exc:
        record.update(status='unexpected_error', error=f'{type(exc).__name__}: {exc}'[:1000])
    record.update(finished_at=crawler.utc(), elapsed_seconds=round(time.monotonic() - begin, 3))
    crawler.write_json(Path(out) / 'records' / f"{sample['id']}.json", record)
    return record


def crawl_requests(crawler, out, samples, *, workers=5, delay=1., attempts=2, user_agent,
                   timeout=(15., 25.), budget=75., max_new=None):
    out = Path(out)
    identity = {'version': VERSION, 'script_sha256': crawler.file_hash(__file__),
                'crawler_sha256': crawler.file_hash(crawler.__file__), 'user_agent': user_agent,
                'headers': HEADERS, 'request_mode': 'direct_public_page_probe',
                'timeout': list(timeout), 'budget': budget, 'attempts': attempts, 'delay': delay,
                'python': sys.version, 'platform': sys.platform}
    if (out / 'priority_probe_config.json').exists() and crawler.load_json(out / 'priority_probe_config.json') != identity:
        raise ValueError('Priority probe config changed; use a new run directory.')
    crawler.write_json(out / 'priority_probe_config.json', identity)
    pending = []
    for sample in samples:
        path = out / 'records' / f"{sample['id']}.json"
        if path.exists():
            record = crawler.load_json(path)
            if (record['id'], record['url']) != (sample['id'], sample['url']):
                raise ValueError('Checkpoint ID/URL mismatch.')
        else:
            pending.append(sample)
    if max_new is not None:
        pending = pending[:max_new]
    fetcher = crawler.Fetcher(out, delay=delay, attempts=attempts)
    groups = defaultdict(list)
    for sample in pending:
        site = crawler.get_fld(sample['url'], fail_silently=True) or sample['domain']
        groups[site].append(sample)
    def domain_job(group):
        # One active sample per registered domain: its budget is not spent queued behind its siblings.
        for sample in group:
            row = request_record(crawler, fetcher, sample, out, user_agent, timeout, budget)
            print(json.dumps({'domain': row['domain'], 'id': row['id'], 'status': row['status'],
                              'http': row.get('http_status'), 'chars': row.get('char_count')}, ensure_ascii=False), flush=True)
        return len(group)
    with crawler.run_lock(out), ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(domain_job, group) for group in groups.values()]
        completed = 0
        for future in as_completed(futures):
            completed += future.result()
            print(json.dumps({'completed': completed, 'scheduled': len(pending)}, ensure_ascii=False), flush=True)
    return [crawler.load_json(out / 'records' / f"{s['id']}.json") for s in samples
            if (out / 'records' / f"{s['id']}.json").exists()]


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
        first = sample['sample_index'] == 0
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


def crawl_browser(crawler, out, samples, *, user_agent, chrome_binary=None, load_timeout=30., wait_seconds=15., delay=1.):
    """A normal isolated headless Chrome session; outputs are separate from Requests records."""
    out = Path(out)
    pending = [s for s in samples if not (out / 'browser_records' / f"{s['id']}.json").exists()]
    if not pending:
        return
    driver = None
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.common.exceptions import TimeoutException
        options = webdriver.ChromeOptions()
        options.add_argument('--headless=new')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--window-size=1280,900')
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
            record = dict(sample, engine='selenium', started_at=crawler.utc())
            try:
                crawler.Fetcher.validate(sample['url'])
                driver.get('about:blank')
                driver.get_log('performance')  # Clear the previous page's network events.
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
                shot = Path('browser_screenshots') / f"{sample['id']}.png"
                (out / shot).parent.mkdir(parents=True, exist_ok=True)
                if driver.save_screenshot(str(out / shot)):
                    record['screenshot_path'] = shot.as_posix()
                doc = crawler.extract(body, 'text/html; charset=utf-8', record['final_url'])
                record.update(doc, **crawler.quality(doc))
                crawler.flag_redirect(record)
                status, error = browser_outcome(record)
                record['status'] = status
                if error:
                    record['error'] = error
                challenge = (record.get('browser_title', '').lower().startswith(('just a moment', 'attention required'))
                             or 'performing security verification' in record.get('text', '').lower())
                if challenge:
                    record.update(challenge_detected=True, quality_status='rejected')
                    if 'error_or_challenge' not in record['quality_flags']:
                        record['quality_flags'].append('error_or_challenge')
            except Exception as exc:
                record.update(status='browser_error', error=f'{type(exc).__name__}: {exc}'[:1000])
            record.update(finished_at=crawler.utc(), elapsed_seconds=round(time.monotonic() - started, 3))
            crawler.write_json(out / 'browser_records' / f"{sample['id']}.json", record)
            print(json.dumps({'browser_id': sample['id'], 'domain': sample['domain'], 'status': record['status'],
                              'http': record.get('http_status'), 'chars': record.get('char_count')}, ensure_ascii=False), flush=True)
            time.sleep(delay)
    finally:
        driver.quit()
