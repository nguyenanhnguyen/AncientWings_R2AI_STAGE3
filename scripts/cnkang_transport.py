"""Sequential, robots-aware Requests transport shared by check and corpus jobs."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import importlib.util
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit, urlunsplit, urljoin
from urllib.robotparser import RobotFileParser

import requests


def load_parser():
    path = Path(__file__).with_name('cnkang_snapshot.py')
    if not path.exists(): path = Path(__file__).with_name('cnkang.py')
    spec = importlib.util.spec_from_file_location('_cnkang_parser_' + str(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PARSER = load_parser()
_network_path = Path(__file__).with_name('cnkang_network_snapshot.py')
if not _network_path.exists(): _network_path = Path(__file__).with_name('cnkang_network.py')
_network_spec = importlib.util.spec_from_file_location('_cnkang_network_' + str(_network_path), _network_path)
NETWORK = importlib.util.module_from_spec(_network_spec)
_network_spec.loader.exec_module(NETWORK)
NetworkFailure = NETWORK.NetworkFailure
DEFAULTS = {'gap': 1.5, 'timeout': [10., 30.], 'attempts': 2,
            'user_agent': 'ViBioMIR-CnkangCheck/1.0', 'trust_env': False,
            'max_inline_wait': 30., 'max_bytes': 10 * 1024 * 1024,
            'request_deadline': 45., 'url_deadline': 120.,
            'max_consecutive_network_errors': 3}


def failure_details(exc, stage='network'):
    if isinstance(exc, NetworkFailure):
        return dict(exc.details)
    if isinstance(exc, OSError) and not isinstance(exc, requests.RequestException):
        return {'error_kind': 'checkpoint_error', 'error_stage': 'checkpoint',
                'error': f'{type(exc).__name__}: {exc}'[:700]}
    return {'error_kind': ('read_timeout' if isinstance(exc, requests.Timeout) else 'connection_error'),
            'error_stage': stage, 'error': f'{type(exc).__name__}: {exc}'[:700],
            'error_causes': [{'type': type(exc).__name__, 'message': str(exc)[:700]}]}


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def append(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')
        stream.flush()


class Paused(RuntimeError):
    pass


class Transport:
    def __init__(self, out, config=None):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.config = {**DEFAULTS, **(config or {})}
        for key in ('gap', 'max_inline_wait'):
            if not math.isfinite(self.config[key]) or self.config[key] < 0:
                raise ValueError('Invalid cnkang ' + key)
        if self.config['gap'] < 1.5:
            raise ValueError('cnkang request gap must be at least 1.5 seconds')
        if type(self.config['attempts']) is not int or self.config['attempts'] < 1:
            raise ValueError('Invalid cnkang attempts')
        if len(self.config['timeout']) != 2 or any(not math.isfinite(x) or x <= 0 for x in self.config['timeout']):
            raise ValueError('Invalid cnkang timeout')
        for key in ('request_deadline', 'url_deadline'):
            if not math.isfinite(self.config[key]) or self.config[key] <= 0:
                raise ValueError('Invalid cnkang ' + key)
        for key in ('max_bytes', 'max_consecutive_network_errors'):
            if type(self.config[key]) is not int or self.config[key] < 1:
                raise ValueError('Invalid cnkang ' + key)
        self.worker = NETWORK.NetworkWorker()
        self._url_limit = None
        self.network_events = []
        self.consecutive_network_errors = 0
        self.robots, self.policies = {}, {}
        self.state_path = self.out / 'cnkang_transport_state.json'
        self.state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {}
        self.stopped = False
        self.stop_reason = None

    def budget(self, stage):
        if self._url_limit is not None and NETWORK.remaining(self._url_limit) <= 0:
            raise NetworkFailure({'error_kind': 'url_deadline', 'error_stage': stage,
                                  'error': 'URL deadline exceeded during ' + stage,
                                  'deadline_exceeded': True, 'error_causes': []})

    def wait(self, extra=0):
        delay = max(self.state.get('not_before', 0) - time.time(),
                    self.state.get('last_request', 0) + self.config['gap'] - time.time(), extra)
        if delay > self.config['max_inline_wait']:
            raise Paused('Cooldown active; resume after ' +
                         datetime.fromtimestamp(time.time() + delay, timezone.utc).isoformat())
        self.budget('throttle')
        if self._url_limit is not None and delay >= NETWORK.remaining(self._url_limit):
            raise NetworkFailure({'error_kind': 'url_deadline', 'error_stage': 'throttle',
                                  'error': 'Remaining URL budget cannot cover required wait',
                                  'deadline_exceeded': True, 'error_causes': [],
                                  'required_wait_seconds': delay})
        if delay > 0: time.sleep(delay)
        self.budget('throttle')

    def cooldown(self, seconds):
        self.state['not_before'] = max(self.state.get('not_before', 0), time.time() + seconds)
        write_json(self.state_path, self.state)

    def get(self, url):
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not PARSER.is_host(url)
                or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
            raise ValueError('Unsafe or non-cnkang URL: ' + url)
        self.wait()
        self.state['last_request'] = time.time()
        write_json(self.state_path, self.state)
        start = time.monotonic()
        event = {'url': url, 'at': utc()}
        self.network_events.append(event)
        try:
            self.budget('request_start')
            limit = NETWORK.deadline(self.config['request_deadline'])
            scope = 'request'
            if self._url_limit is not None and NETWORK.remaining(self._url_limit) < NETWORK.remaining(limit):
                limit, scope = self._url_limit, 'url'
            event['deadline_seconds'] = max(0., round(NETWORK.remaining(limit), 3))
            response = self.worker.get(url, self.config, limit, scope=scope)
            event.update(response.network, http_status=response.status_code)
            return response
        except NetworkFailure as exc:
            event.update(exc.details)
            raise
        finally:
            event['elapsed_seconds'] = round(time.monotonic() - start, 3)
            # Gap is measured from completion, including robots, redirects and retries.
            self.state['last_request'] = time.time()
            write_json(self.state_path, self.state)

    def retry_after(self, response):
        value = response.headers.get('Retry-After', '')
        try:
            return max(0., float(value))
        except ValueError:
            try:
                return max(0., parsedate_to_datetime(value).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                return 60.

    def robot_policy(self, url):
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, '', '', ''))
        if origin not in self.policies:
            entry = {'origin': origin, 'url': origin + '/robots.txt', 'checked_at': utc(),
                     'status': 'unknown', 'allowed': None}
            policy = RobotFileParser()
            try:
                response = self.get(entry['url'])
                entry['http_status'] = response.status_code
                # Redirected robots must not be silently treated as an allow.
                if response.status_code == 200:
                    text, info = PARSER.decode_bytes(response.content, response.headers.get('Content-Type', ''))
                    entry['body_sha256'] = PARSER.sha(response.content)
                    entry['selected_encoding'] = info['selected_encoding']
                    if '<html' in text[:1000].lower() or info['encoding_uncertain']:
                        entry['status'] = 'unverifiable'
                    else:
                        policy.parse(text.splitlines())
                        entry['status'] = 'checked'
                elif response.status_code in (404, 410):
                    policy.parse([])
                    entry['status'] = 'absent_404_410'
                elif response.status_code in (401, 403):
                    policy.parse(['User-agent: *', 'Disallow: /'])
                    entry['status'] = 'denied'
                elif response.status_code == 429:
                    self.cooldown(self.retry_after(response))
                    self.stopped = True
                    entry['status'] = 'rate_limited'
                else:
                    entry['status'] = 'unverifiable'
            except NetworkFailure as exc:
                entry.update(status='unverifiable', **exc.details)
                if (exc.details.get('deadline_exceeded')
                        or exc.details['error_kind'] == 'network_worker_error'):
                    self.stopped, self.stop_reason = True, exc.details['error_kind']
            except (requests.RequestException, ValueError) as exc:
                entry.update(status='unverifiable', **failure_details(exc, 'robots'))
            self.policies[origin], self.robots[origin] = policy, entry
        entry = dict(self.robots[origin], target_url=url)
        if entry['status'] in ('checked', 'absent_404_410', 'denied'):
            policy = self.policies[origin]
            entry['allowed'] = policy.can_fetch(self.config['user_agent'], url)
            delay = policy.crawl_delay(self.config['user_agent']) or policy.crawl_delay('*')
            # Waiting happens once per actual request, rather than on each cached policy lookup.
            entry['crawl_delay'] = float(delay or 0)
        else:
            entry['allowed'] = None
        self.robots[origin].setdefault('decisions', {})[url] = entry['allowed']
        write_json(self.out / 'robots_checks.json', self.robots)
        return entry

    def fetch(self, sample, *, record_dir='records'):
        source = sample.get('source_url') or sample['url']
        parts = urlsplit(source)
        preferred = urlunsplit(('https', parts.netloc, parts.path, parts.query, ''))
        identifier = sample.get('canonical_url', source)
        key = PARSER.sha(identifier)
        record = dict(sample, url=source, source_url=source, engine='requests', status='fetch_failed',
                      crawl_status='fetch_failed', started_at=utc(), requests=[], redirects=[],
                      attempts=0, parser_flags=[], source_flags=[], final_url=preferred)
        for name, default in {
            'ids':[sample['id']], 'canonical_url':identifier,
            'branch':parts.path.strip('/').split('/')[0], 'selected_encoding':'',
            'encoding_candidates':[], 'declared_encoding':None, 'selector':'', 'template':'not_parsed',
            'html_title':'', 'heading_title':'', 'title':'', 'date_candidates':[],
            'date_context':'', 'source_name':None, 'text':'', 'text_before':'',
            'text_sha256':PARSER.sha(''), 'chars_before':0, 'chars_after':0, 'cleaning_actions':[],
            'flag_evidence':[], 'raw_html_path':None, 'text_before_path':None,
            'text_clean_path':None, 'fetched_at':None
        }.items():
            record.setdefault(name, default)
        attempts = 0
        begin = time.monotonic()
        self._url_limit = NETWORK.deadline(self.config['url_deadline'])
        self.network_events = []
        record['network_limits'] = {key: self.config[key] for key in ('request_deadline', 'url_deadline')}
        current, used_original = preferred, preferred == source
        error = None
        try:
            for redirect in range(9):
                self.budget('redirect')
                record['final_url'] = current
                robot = self.robot_policy(current)
                record['robots'] = robot
                if robot['allowed'] is not True:
                    record.update(error='robots ' + robot['status'], error_kind='robots_not_allowed_or_unknown',
                                  error_stage='robots')
                    if robot.get('error_kind'):
                        record.update({key: robot[key] for key in
                            ('error', 'error_kind', 'error_stage', 'error_causes', 'deadline_exceeded')
                            if key in robot})
                        record['error_context'] = 'robots'
                    break
                response = None
                while attempts < self.config['attempts']:
                    attempts += 1
                    response = None
                    event = {'url': current, 'attempt': attempts, 'at': utc()}
                    record['requests'].append(event)
                    start = time.monotonic()
                    try:
                        # An HTTPS -> original-HTTP fallback has a different robots origin.
                        robot = self.robot_policy(current)
                        record['robots'] = robot
                        if robot['allowed'] is not True:
                            error = 'robots ' + robot['status']
                            record.update(error_kind=robot.get('error_kind', 'robots_not_allowed_or_unknown'),
                                          error_stage=robot.get('error_stage', 'robots'), error_context='robots')
                            record.update({key: robot[key] for key in
                                ('error', 'error_causes', 'deadline_exceeded') if key in robot})
                            error = robot.get('error', error)
                            break
                        self.wait(extra=robot.get('crawl_delay', 0))
                        response = self.get(current)
                        self.budget('response')
                        body = response.content
                        body_hash = PARSER.sha(body)
                        raw = Path('raw') / (key + '_' + body_hash + '.gz')
                        (self.out / raw).parent.mkdir(parents=True, exist_ok=True)
                        (self.out / raw).write_bytes(gzip.compress(body, mtime=0))
                        html_path = Path('raw_html') / (key + '.html')
                        (self.out / html_path).parent.mkdir(parents=True, exist_ok=True)
                        (self.out / html_path).write_bytes(body)
                        event.update(http_status=response.status_code, raw_path=raw.as_posix(), raw_sha256=body_hash)
                        record.update(http_status=response.status_code,
                            content_type=response.headers.get('Content-Type', ''),
                            raw_path=raw.as_posix(), raw_html_path=html_path.as_posix(), raw_sha256=body_hash,
                            final_url=current, fetched_at=utc())
                        if response.status_code == 429:
                            wait = self.retry_after(response)
                            self.cooldown(wait)
                            record.update(error='HTTP 429', error_kind='http_429', error_stage='http',
                                          retry_deferred=True, retry_after_seconds=wait)
                            if wait > self.config['max_inline_wait']:
                                self.stopped = True
                                break
                            self.wait()
                            continue
                        if response.status_code >= 500 and attempts < self.config['attempts']:
                            self.wait(extra=2 ** attempts)
                            if not used_original and parts.scheme == 'http':
                                current, used_original = source, True
                            continue
                        break
                    except (NetworkFailure, requests.ConnectionError, requests.Timeout) as exc:
                        details = failure_details(exc)
                        event.update(details)
                        record.update(details)
                        error = str(exc)[:500]
                        if details.get('deadline_exceeded') or details['error_kind'] == 'network_worker_error':
                            self.stopped, self.stop_reason = True, details['error_kind']
                            raise
                        if attempts < self.config['attempts']:
                            self.wait(extra=2 ** attempts)
                            if (not used_original and parts.scheme == 'http'
                                    and details['error_kind'] not in ('dns_error',)):
                                current, used_original = source, True
                            continue
                        response = None
                    finally:
                        event['elapsed_seconds'] = round(time.monotonic() - start, 3)
                if response is None:
                    record['error'] = error or 'No response'
                    break
                status = response.status_code
                if status in (301, 302, 303, 307, 308):
                    target = urljoin(current, response.headers.get('Location', ''))
                    if not response.headers.get('Location') or not PARSER.is_host(target):
                        record.update(error='Redirect outside cnkang or missing Location', error_kind='redirect_review')
                        break
                    record['redirects'].append({'from':current, 'to':target, 'http_status':status})
                    current = target
                    # Redirect hops are not retries; each target gets a bounded attempt allocation.
                    attempts = 0
                    continue
                if not 200 <= status < 300:
                    record.update(error='HTTP ' + str(status), error_kind='http_' + str(status), error_stage='http')
                    if status in (401, 403):
                        self.stopped, self.stop_reason = True, 'http_' + str(status)
                    break
                content_type = record['content_type'].lower()
                if 'html' not in content_type and not re_html(response.content):
                    record.update(error='Unsupported content type: ' + content_type, error_kind='content_type')
                    break
                decoded, _ = PARSER.decode_bytes(response.content, content_type)
                if is_error_page(decoded):
                    record.update(error='Challenge, soft error or empty HTML', error_kind='soft_error_or_challenge',
                                  challenge_detected=True)
                    break
                record.update(status='fetched', crawl_status='fetched')
                for field in ('error', 'error_kind', 'error_stage', 'error_causes', 'error_context'):
                    record.pop(field, None)
                append(self.out / 'crawl_journal.jsonl', dict(record, event='fetched'))
                doc = PARSER.extract(response.content, current, record['content_type'])
                record.update(doc, status='extracted',
                              crawl_status='needs_review' if doc['quality_status'] != 'accepted' else 'parsed')
                for folder, field in (('text_before', 'text_before'), ('text_clean', 'text')):
                    path = Path(folder) / (key + '.txt')
                    (self.out / path).parent.mkdir(parents=True, exist_ok=True)
                    (self.out / path).write_text(record[field], encoding='utf-8')
                    record[folder + '_path'] = path.as_posix()
                break
            else:
                record.update(error='Redirect limit exceeded', error_kind='redirect_limit')
        except NetworkFailure as exc:
            record.update(exc.details)
            self.stopped, self.stop_reason = True, exc.details['error_kind']
        except Paused as exc:
            self.stopped = True
            record.update(error=str(exc), retry_deferred=True, error_kind='cooldown')
        except (requests.RequestException, ValueError) as exc:
            record.update(error=f'{type(exc).__name__}: {exc}'[:700], error_kind='fetch_or_parse_error')
        except OSError as exc:
            record.update(failure_details(exc))
            self.stopped, self.stop_reason = True, 'checkpoint_error'
        except Exception as exc:
            # A malformed DOM/parser failure is durable and distinguishable from HTTP success.
            record.update(error=f'{type(exc).__name__}: {exc}'[:700], error_kind='parser_exception')
        record.update(attempts=len(record['requests']), finished_at=utc(),
                      elapsed_seconds=round(time.monotonic() - begin, 3),
                      network_requests=self.network_events)
        self._url_limit = None
        if record.get('error_kind') in ('dns_error', 'connect_timeout', 'read_timeout',
                                       'connection_reset', 'connection_error'):
            self.consecutive_network_errors += 1
            if self.consecutive_network_errors >= self.config['max_consecutive_network_errors']:
                self.stopped, self.stop_reason = True, 'consecutive_network_errors'
        else:
            self.consecutive_network_errors = 0
        if self.stopped:
            record['stop_reason'] = self.stop_reason or record.get('error_kind', 'cooldown')
        if record.get('status') == 'fetched':
            record.update(status='parse_failed', crawl_status='needs_review',
                          parser_flags=['PARSER_EXCEPTION_REVIEW'])
        write_json(self.out / record_dir / f"{sample['id']}.json", record)
        append(self.out / 'crawl_journal.jsonl', dict(record, event='checkpoint'))
        return record

    def close(self):
        self.worker.close()


def re_html(body):
    return b'<html' in body[:2000].lower() or b'<!doctype html' in body[:2000].lower()


def is_error_page(decoded):
    import re
    title = re.search(r'<title[^>]*>(.*?)</title>', decoded, re.I | re.S)
    title = title.group(1).strip() if title else ''
    text = re.sub(r'<[^>]+>', '', decoded)
    return (len(PARSER.compact(text)) < 10
            or bool(re.match(r'^(?:404|403|access denied|just a moment|页面不存在|页面未找到|访问受限)', title, re.I))
            or (len(text) < 10000 and bool(re.search(
                r'verify you are human|checking your browser|安全验证|请输入验证码', text, re.I))))


def crawl(crawler, probe, out, samples, config=None, *, max_new=None, on_record=None, log_every=25):
    """Production adapter: same transport/parser as the standalone check; no browser."""
    transport = Transport(out, config)
    done = 0
    try:
        try:
            transport.wait()
        except Paused as exc:
            print(str(exc), flush=True)
            return 0
        for sample in samples:
            path = Path(out) / 'requests_records' / f"{sample['id']}.json"
            if path.exists():
                previous = json.loads(path.read_text(encoding='utf-8'))
                if not previous.get('retry_deferred'):
                    if on_record: on_record(previous)
                    continue
            if transport.stopped or (max_new is not None and done >= max_new):
                break
            record = transport.fetch(sample, record_dir='requests_records')
            done += 1
            if on_record: on_record(record)
            if done % log_every == 0 or record['status'] != 'extracted':
                print(json.dumps({'engine':'cnkang_requests', 'completed':done,
                                  'id':sample['id'], 'status':record['crawl_status'],
                                  'http':record.get('http_status')}, ensure_ascii=False), flush=True)
    finally:
        transport.close()
    return done
