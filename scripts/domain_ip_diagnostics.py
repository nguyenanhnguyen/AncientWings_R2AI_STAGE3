"""Observe egress IP and access denials; a 403 alone does not establish an IP ban."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import gzip
import hashlib
import html as html_escape
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
import uuid
from urllib.parse import urljoin, urlsplit

VERSION = 'domain-ip-diagnostics-v1'
IP_PROVIDERS = ('https://api.ipify.org?format=json', 'https://api64.ipify.org?format=json')
SCOPE = ('IP được quan sát qua dịch vụ check IP, có thể khác theo proxy/đích truy cập. '
         'HTTP 403, 429 và challenge không tự chứng minh IP bị chặn. '
         'Kết luận chỉ áp dụng cho mẫu, thời điểm và môi trường của run này.')


def parse_ip(text):
    try:
        value = json.loads(text)
        value = value.get('ip') if isinstance(value, dict) else value
    except ValueError:
        value = text.strip()
    try:
        address = ipaddress.ip_address(str(value).strip())
    except ValueError:
        return None
    return str(address) if address.is_global else None


def visible_text(body):
    from lxml import html
    try:
        tree = html.fromstring(body)
        text = ' '.join(tree.xpath('//text()[not(ancestor::script) and not(ancestor::style)]'))
    except (ValueError, html.etree.ParserError):
        text = body.decode('utf-8', 'replace')
    return re.sub(r'\s+', ' ', text).strip()


def classify(record, body=b''):
    """Return an observation category, never infer an IP ban from status alone."""
    if not record or record.get('status') in ('pending', 'skipped_selenium_first'):
        return {'category': 'NOT_TESTED', 'ip_block_message': False, 'snippet': ''}
    text = visible_text(body) if body else (record.get('text') or record.get('error') or '')
    title = record.get('title') or record.get('browser_title') or ''
    message = title + ' ' + text
    # These are direct server messages, not incidental mentions in normal articles.
    ip_pattern = (r'\b(?:your\s+(?:ip(?:\s+address)?|network)|ip\s+address\s+[0-9a-f:.]+)'
                  r'\s+(?:(?:is|was|has\s+been)\s+)?(?:blocked|banned|blacklisted|denied)\b'
                  r'|\b(?:blocked|banned|blacklisted)\s+your\s+ip(?:\s+address)?\b'
                  r'|địa chỉ ip (?:của bạn )?(?:đã |đang )?bị (?:chặn|cấm)'
                  r'|您的\s*IP\s*(?:地址)?\s*(?:已被|被)?\s*(?:封禁|屏蔽|封锁)')
    status = record.get('http_status')
    ip_match = re.search(ip_pattern, message, re.I)
    explicit = bool(ip_match) and (status in (403, 429)
                                   or (len(text) < 1500 and ip_match.start() < 200))
    headers = {k.lower(): v for k, v in (record.get('response_headers') or {}).items()}
    gate = (record.get('challenge_detected') or headers.get('cf-mitigated', '').lower() == 'challenge'
            or bool(re.search(r'just a moment|verify you are human|cookies must be enabled|captcha|checking your browser', title, re.I))
            or (len(text) < 3000 and bool(re.search(r'verify you are human|cookies must be enabled|enable javascript and cookies', text, re.I)))
            or bool(re.match(r'^(?:just a moment|attention required|access denied|403 forbidden|checking your browser)\b', text, re.I)))
    if explicit:
        category = 'IP_BLOCK_MESSAGE'
    elif gate:
        category = 'CHALLENGE_OR_ERROR_PAGE'
    elif status == 429:
        category = 'RATE_LIMITED'
    elif status in (401, 403):
        category = 'ACCESS_DENIED'
    elif 'error_or_challenge' in (record.get('quality_flags') or []):
        category = 'CHALLENGE_OR_ERROR_PAGE'
    elif status in (404, 410):
        category = 'URL_NOT_FOUND'
    elif status is not None and 500 <= status < 600:
        category = 'SERVER_ERROR'
    elif status is not None and 200 <= status < 300:
        category = 'HTTP_ACCESS_OK'  # QC and extraction are separate observations.
    elif record.get('status', '').startswith('robots_'):
        category = 'ROBOTS_GATE'
    else:
        category = 'NETWORK_OR_BROWSER_ERROR'
    match = re.search(ip_pattern, message, re.I) if explicit else None
    start = max(0, match.start() - 100) if match else 0
    return {'category': category, 'ip_block_message': explicit, 'snippet': message[start:start + 700]}


def bounded_raw(crawler, out, record):
    if not record.get('raw_path'):
        return b''
    path = (Path(out) / record['raw_path']).resolve()
    if not path.is_relative_to(Path(out).resolve()):
        raise ValueError('Raw evidence outside run')
    with gzip.open(path, 'rb') as stream:
        body = stream.read(10 * 1024 * 1024 + 1)
    if len(body) > 10 * 1024 * 1024 or crawler.digest(body) != record.get('raw_sha256'):
        raise ValueError('Raw evidence hash/size mismatch')
    return body


def fetch_control(crawler, fetcher, out, url, *, timeout=(5, 10), budget=20, maximum=1024 * 1024):
    """Single-attempt bounded fetch; preserve redirects and deny-page evidence."""
    started = time.monotonic()
    row = {'url': url, 'engine': 'requests', 'started_at': crawler.utc(), 'redirects': []}
    current = url
    try:
        for _ in range(4):
            status, headers, body = fetcher.request_once(current, maximum, timeout=timeout,
                                                        deadline=started + budget)
            headers = crawler.requests.structures.CaseInsensitiveDict(headers)
            raw_path = 'network_controls/raw/' + crawler.digest(body) + '.gz'
            crawler.atomic_bytes(Path(out) / raw_path, gzip.compress(body, mtime=0))
            row.update(http_status=status, final_url=current, status='observed',
                       raw_path=raw_path, raw_sha256=crawler.digest(body),
                       response_headers={k: v for k, v in headers.items() if k.lower() in (
                           'server', 'content-type', 'retry-after', 'cf-mitigated', 'cf-ray', 'via', 'location')})
            if status in (301, 302, 303, 307, 308) and headers.get('Location'):
                target = urljoin(current, headers['Location'])
                row['redirects'].append({'from': current, 'to': target, 'status': status})
                current = target
                continue
            row.update(classify(row, body))
            row['final_hostname'] = crawler.host(current)
            return row, body
        row.update(status='redirect_limit', error='Control redirect limit exceeded')
    except Exception as exc:
        row.update(status='control_error', error=f'{type(exc).__name__}: {exc}'[:500])
    row.update(classify(row), elapsed_seconds=round(time.monotonic() - started, 3))
    return row, b''


def measurement_key(value):
    return value if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{32}', value) else uuid.uuid4().hex


def collect_network(crawler, probe, out, domains, *, user_agent, browser_user_agent=None,
                    chrome_binary=None, browser_ip=True, homepage=True, workers=2, timeout=(5, 10), budget=20, force=True):
    """Diagnostic failures are recorded and do not prevent the article crawl."""
    out = Path(out)
    target = out / 'network_check.json'
    domains = sorted(set(domains))
    expected = {'version': VERSION, 'domains': domains, 'homepage_enabled': homepage,
                'browser_ip_enabled': browser_ip}
    if target.exists():
        saved = crawler.load_json(target)
        if not force and saved.get('status') == 'complete' and all(saved.get(k) == v for k, v in expected.items()):
            return saved
        crawler.write_json(out / 'network_history' / measurement_key(saved.get('measurement_id')) / 'network_check.json', saved)
    network = dict(expected, checked_at=crawler.utc(), status='running',
                   measurement_id=uuid.uuid4().hex,
                   environment='kaggle' if sys.platform != 'win32' and Path('/kaggle/working').is_dir() else
                   'colab' if sys.platform != 'win32' and Path('/content').is_dir() else 'local',
                   proxy_environment_present={k: bool(os.environ.get(k)) for k in
                       ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY')},
                   ip_observations=[], dns=[], scope=SCOPE)
    crawler.write_json(target, network)
    fetcher = crawler.Fetcher(out, delay=1, attempts=1)
    fetcher.session().headers.update(probe.HEADERS, **{'User-Agent': user_agent})
    for url in IP_PROVIDERS:
        row, body = fetch_control(crawler, fetcher, out, url, timeout=timeout, budget=budget, maximum=8192)
        row['ip'] = parse_ip(body.decode('utf-8', 'replace')) if row.get('http_status') == 200 else None
        network['ip_observations'].append(row)
        crawler.write_json(target, network)
    if browser_ip:
        driver = None
        try:
            driver = probe.create_browser(crawler, out / 'network_controls/browser_environment',
                                          user_agent=browser_user_agent, chrome_binary=chrome_binary,
                                          load_timeout=timeout[1])
            for url in IP_PROVIDERS:
                row = {'url': url, 'engine': 'selenium', 'ip': None}
                try:
                    driver.get(url)
                    body = driver.execute_script('return document.body ? document.body.innerText : ""')
                    row.update(ip=parse_ip(body), final_url=driver.current_url)
                except Exception as exc:
                    row['error'] = f'{type(exc).__name__}: {exc}'[:500]
                network['ip_observations'].append(row)
                crawler.write_json(target, network)
        except Exception as exc:
            network['browser_ip_error'] = f'{type(exc).__name__}: {exc}'[:500]
        finally:
            if driver is not None:
                driver.quit()
    network['requests_ips'] = sorted({r['ip'] for r in network['ip_observations'] if r.get('ip') and r['engine'] == 'requests'})
    network['selenium_ips'] = sorted({r['ip'] for r in network['ip_observations'] if r.get('ip') and r['engine'] == 'selenium'})
    network['egress_difference_observed'] = bool(network['requests_ips'] and network['selenium_ips']
                                               and set(network['requests_ips']) != set(network['selenium_ips']))
    crawler.write_json(target, network)

    def host_control(domain):
        start = time.monotonic()
        dns = {'hostname': domain}
        try:
            dns['addresses'] = sorted({r[4][0] for r in socket.getaddrinfo(domain, 443)})
        except OSError as exc:
            dns['error'] = str(exc)[:300]
        dns['elapsed_seconds'] = round(time.monotonic() - start, 3)
        if homepage:
            path = out / 'network_controls' / (hashlib.sha256(domain.encode()).hexdigest() + '.json')
            previous = crawler.load_json(path) if path.exists() else {}
            if previous.get('measurement_id') != network['measurement_id']:
                if previous:
                    crawler.write_json(out / 'network_history' / measurement_key(previous.get('measurement_id')) / path.name, previous)
                # Thread-local sessions need the same browser headers as the article pass.
                fetcher.session().headers.update(probe.HEADERS, **{'User-Agent': user_agent})
                row, _ = fetch_control(crawler, fetcher, out, 'https://' + domain + '/', timeout=timeout, budget=budget)
                row['hostname'] = domain
                row['measurement_id'] = network['measurement_id']
                crawler.write_json(path, row)
        return dns

    # Keep durable results per host; Ctrl-C can be resumed without redoing completed controls.
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(host_control, domain) for domain in domains]
    try:
        for future in as_completed(futures):
            network['dns'].append(future.result())
            crawler.write_json(target, network)
            if len(network['dns']) % 10 == 0 or len(network['dns']) == len(domains):
                print(json.dumps({'ip_check_hosts_completed': len(network['dns']), 'selected_hosts': len(domains)}), flush=True)
        network.update(status='complete', completed_at=crawler.utc())
    finally:
        for future in futures:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        crawler.write_json(target, network)
    return network


def verdict(observations, controls=()):
    tested = [r for r in observations if r['category'] != 'NOT_TESTED']
    if not tested:
        return 'NOT_TESTED', 'Chưa có kết quả trang mẫu; homepage chỉ là phép kiểm tra đối chứng.'
    if any(r['ip_block_message'] for r in tested):
        return 'IP_BLOCK_MESSAGE', 'Trang mẫu thông báo rõ chặn IP/network; xem raw và đối chiếu IP đầu ra.'
    if any(r['category'] == 'HTTP_ACCESS_OK' for r in tested):
        return 'SOME_URL_ACCESSIBLE', 'Có mẫu trả HTTP 2xx; chưa có bằng chứng chặn toàn bộ hostname. Xem riêng QC/challenge.'
    denial = {'ACCESS_DENIED', 'CHALLENGE_OR_ERROR_PAGE', 'RATE_LIMITED'}
    denied = sum(r['category'] in denial for r in tested)
    if denied and denied == len(tested):
        return 'ACCESS_BLOCK_SUSPECTED', 'Các lượt đã thử đều bị từ chối/challenge/rate limit; chưa tách được IP với anti-bot/session.'
    if denied:
        return 'MIXED_ACCESS_ERRORS', 'Có lỗi từ chối truy cập và lỗi khác; chưa đủ bằng chứng kết luận do IP.'
    return 'OTHER_ERRORS', 'Lỗi DNS/mạng/browser/URL/server; chưa có bằng chứng chặn IP.'


def write_csv(path, rows, fields):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def build_report(crawler, out, samples, profile):
    out = Path(out)
    network = crawler.load_json(out / 'network_check.json') if (out / 'network_check.json').exists() else {}
    evidence, hosts = [], []
    for sample in samples:
        for engine, folder in [('requests', 'records'), ('selenium', 'browser_records')]:
            path = out / folder / f"{sample['id']}.json"
            record = crawler.load_json(path) if path.exists() else {}
            if record and (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
                raise ValueError('IP report checkpoint ID/URL mismatch')
            try:
                observation = classify(record, bounded_raw(crawler, out, record))
            except (OSError, ValueError) as exc:
                observation = {'category': 'RAW_EVIDENCE_INVALID', 'ip_block_message': False, 'snippet': str(exc)}
            evidence.append(dict(observation, hostname=sample['domain'], id=sample['id'], url=sample['url'],
                                 engine=record.get('engine', engine), http_status=record.get('http_status'),
                                 quality_status=record.get('quality_status'), raw_path=record.get('raw_path'),
                                 screenshot_path=record.get('screenshot_path')))
    for domain in sorted({s['domain'] for s in samples}):
        observations = [r for r in evidence if r['hostname'] == domain]
        control_path = out / 'network_controls' / (hashlib.sha256(domain.encode()).hexdigest() + '.json')
        control = crawler.load_json(control_path) if control_path.exists() else {}
        state, reason = verdict(observations)
        if control.get('ip_block_message'):
            state, reason = 'IP_BLOCK_MESSAGE_ON_HOMEPAGE', 'Homepage thông báo chặn IP; xem riêng IP của từng engine và kết quả trang mẫu.'
        elif state == 'ACCESS_BLOCK_SUSPECTED' and (control.get('category') == 'HTTP_ACCESS_OK'
                                                  and control.get('final_hostname') == domain):
            state, reason = 'ARTICLES_DENIED_HOMEPAGE_OK', 'Homepage Requests truy cập được nhưng trang mẫu bị từ chối; có thể khác quy tắc URL/engine/session, chưa kết luận do IP.'
        tested = [r for r in observations if r['category'] != 'NOT_TESTED']
        counts = Counter(r['category'] for r in tested)
        selected = sum(s['domain'] == domain for s in samples)
        hosts.append({'hostname': domain, 'source_rows': profile['host_counts'][domain],
                      'selected_urls': selected, 'shortfall_to_20': max(0, 20 - selected),
                      'urls_with_any_attempt': len({r['id'] for r in tested}),
                      'requests_attempted': sum(r['engine'] == 'requests' for r in tested),
                      'curl_cffi_attempted': sum(r['engine'] == 'curl_cffi' for r in tested),
                      'selenium_attempted': sum(r['engine'] == 'selenium' for r in tested),
                      'http_403': sum(r['http_status'] == 403 for r in tested),
                      'http_429': sum(r['http_status'] == 429 for r in tested),
                      'ip_block_messages': counts['IP_BLOCK_MESSAGE'],
                      'homepage_http_status': control.get('http_status'),
                      'homepage_category': control.get('category', 'NOT_TESTED'),
                      'homepage_ip_block_message': control.get('ip_block_message', False),
                      'homepage_final_hostname': control.get('final_hostname'),
                      'verdict': state, 'reason': reason,
                      'requests_ips': '; '.join(network.get('requests_ips', [])),
                      'selenium_ips': '; '.join(network.get('selenium_ips', []))})
    report = {'version': VERSION, 'generated_at': crawler.utc(), 'scope': SCOPE,
              'network_status': network.get('status', 'not_run'), 'hostnames': len(hosts), 'selected_urls': len(samples),
              'verdict_counts': dict(Counter(r['verdict'] for r in hosts)), 'hosts': hosts,
              'requests_ips': network.get('requests_ips', []), 'selenium_ips': network.get('selenium_ips', [])}
    crawler.write_json(out / 'ip_block_report.json', report)
    crawler.jsonl(out / 'ip_url_evidence.jsonl', evidence)
    write_csv(out / 'ip_block_report.csv', hosts, list(hosts[0]) if hosts else ['hostname', 'verdict', 'reason'])
    write_csv(out / 'ip_url_evidence.csv', evidence, list(evidence[0]) if evidence else ['hostname', 'id', 'category'])
    fields = ['hostname', 'selected_urls', 'urls_with_any_attempt', 'http_403', 'http_429', 'ip_block_messages',
              'homepage_http_status', 'homepage_category', 'verdict', 'reason']
    esc = lambda value: html_escape.escape(str(value if value is not None else ''), quote=True)
    table = '<table><thead><tr>' + ''.join('<th>' + esc(f) + '</th>' for f in fields) + '</tr></thead><tbody>'
    table += ''.join('<tr>' + ''.join('<td>' + esc(row[f]) + '</td>' for f in fields) + '</tr>' for row in hosts)
    table += '</tbody></table>'
    page = ('<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Chẩn đoán IP và truy cập theo hostname</title><style>body{font:14px/1.5 system-ui;margin:24px;color:#17304c}'
            'table{border-collapse:collapse}td,th{padding:9px;border:1px solid #dae2eb;text-align:left;vertical-align:top}'
            'th{background:#eaf0f7;position:sticky;top:0}input{padding:9px;width:320px}.scroll{overflow:auto}</style>'
            '<h1>Chẩn đoán IP và truy cập</h1><p>' + esc(SCOPE) + '</p><p>Requests IP: ' + esc(report['requests_ips']) +
            ' · Selenium IP: ' + esc(report['selenium_ips']) + '</p><p>' + esc(report['verdict_counts']) + '</p>'
            '<input id="search" placeholder="Tìm hostname hoặc kết luận" aria-label="Tìm hostname"><div class="scroll">' + table +
            '</div><script>document.getElementById("search").addEventListener("input",e=>{for(const r of document.querySelectorAll("tbody tr"))'
            'r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase())})</script></html>')
    crawler.atomic_bytes(out / 'ip_block_report.html', page.encode('utf-8'))
    lines = ['# Chẩn đoán IP và truy cập', '', SCOPE, '',
             f"Requests IP: {report['requests_ips']}; Selenium IP: {report['selenium_ips']}.", '',
             '| Hostname | Mẫu | 403 | 429 | Kết luận |', '| --- | ---: | ---: | ---: | --- |']
    lines.extend(f"| {r['hostname']} | {r['urls_with_any_attempt']}/{r['selected_urls']} | {r['http_403']} | {r['http_429']} | {r['verdict']} |" for r in hosts)
    lines += ['', 'Chi tiết từng URL/engine: `ip_url_evidence.csv`; bằng chứng: raw, screenshot và `network_controls/`.',
              'Để đối chiếu môi trường khác, giữ nguyên notebook/mẫu và chạy lại trên Kaggle/local. Một phép đo IP không chứng minh quan hệ nhân quả.', '']
    crawler.atomic_bytes(out / 'IP_BLOCK_REPORT.md', '\n'.join(lines).encode('utf-8'))
    return {k: report[k] for k in ('network_status', 'hostnames', 'selected_urls', 'verdict_counts', 'requests_ips', 'selenium_ips')}
