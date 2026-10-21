"""Sequential, robots-aware Requests transport shared by check and corpus jobs."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import base64
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
ARTICLE = PARSER.article_module()
_network_path = Path(__file__).with_name('cnkang_network_snapshot.py')
if not _network_path.exists(): _network_path = Path(__file__).with_name('cnkang_network.py')
_network_spec = importlib.util.spec_from_file_location('_cnkang_network_' + str(_network_path), _network_path)
NETWORK = importlib.util.module_from_spec(_network_spec)
_network_spec.loader.exec_module(NETWORK)
NetworkFailure = NETWORK.NetworkFailure
_storage_path = Path(__file__).with_name('cnkang_checkpoint_snapshot.py')
if not _storage_path.exists(): _storage_path = Path(__file__).with_name('cnkang_checkpoint.py')
_storage_spec = importlib.util.spec_from_file_location('_cnkang_checkpoint_' + str(_storage_path), _storage_path)
STORAGE = importlib.util.module_from_spec(_storage_spec)
_storage_spec.loader.exec_module(STORAGE)
CheckpointError = STORAGE.CheckpointError
DEFAULTS = {'gap': 1.5, 'timeout': [10., 30.], 'attempts': 2,
            'user_agent': 'ViBioMIR-CnkangCheck/1.0', 'trust_env': False,
            'max_inline_wait': 30., 'max_bytes': 10 * 1024 * 1024,
            'request_deadline': 45., 'url_deadline': 120.,
            'max_consecutive_network_errors': 3,
            'max_pages': 6, 'article_deadline': 360., 'postprocess_only': False}


def failure_details(exc, stage='network'):
    if isinstance(exc, CheckpointError):
        return dict(exc.details)
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
    STORAGE.write_json(path, value)


def append(path, value):
    STORAGE.append(path, value)


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
        for key in ('request_deadline', 'url_deadline', 'article_deadline'):
            if not math.isfinite(self.config[key]) or self.config[key] <= 0:
                raise ValueError('Invalid cnkang ' + key)
        for key in ('max_bytes', 'max_consecutive_network_errors', 'max_pages'):
            if type(self.config[key]) is not int or self.config[key] < 1:
                raise ValueError('Invalid cnkang ' + key)
        if self.config.get('source_policy_mode','report_only') not in ('report_only','enforce'):
            raise ValueError('Invalid cnkang source policy mode')
        if (self.out/'cnkang_source_policy.json').exists():
            if PARSER.SOURCE.mode_for_run(self.out) != self.config.get('source_policy_mode','report_only'):
                raise ValueError('Source policy mode changed; use a new run and recovery')
        self.worker = NETWORK.NetworkWorker()
        self.parser, self.storage, self.NetworkFailure = PARSER, STORAGE, NetworkFailure
        self._page_mode, self._article_limit, self._article_started = False, None, None
        self._url_limit = None
        self.network_events = []
        self.consecutive_network_errors = 0
        self.robots, self.policies = {}, {}
        self.state_path = self.out / 'cnkang_transport_state.json'
        self.state = STORAGE.load_state(self.state_path)
        self.writer = STORAGE.WriterLock(self.out)
        self.stopped = False
        self.stop_reason = None

    def budget(self, stage):
        if self._article_limit is not None and NETWORK.remaining(self._article_limit) <= 0:
            raise NetworkFailure({'error_kind': 'article_deadline', 'error_stage': stage,
                                  'error': 'Article deadline exceeded during ' + stage,
                                  'deadline_exceeded': True, 'error_causes': []})
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
        if self._article_limit is not None and delay >= NETWORK.remaining(self._article_limit):
            raise NetworkFailure({'error_kind': 'article_deadline', 'error_stage': 'throttle',
                                  'error': 'Remaining article budget cannot cover required wait',
                                  'deadline_exceeded': True, 'error_causes': []})
        if self._url_limit is not None and delay >= NETWORK.remaining(self._url_limit):
            raise NetworkFailure({'error_kind': 'url_deadline', 'error_stage': 'throttle',
                                  'error': 'Remaining URL budget cannot cover required wait',
                                  'deadline_exceeded': True, 'error_causes': [],
                                  'required_wait_seconds': delay})
        if delay > 0: time.sleep(delay)
        self.budget('throttle')

    def cooldown(self, seconds):
        self.writer.acquire()
        self.state['not_before'] = max(self.state.get('not_before', 0), time.time() + seconds)
        self.save_state()

    def save_state(self):
        self.writer.acquire()
        self.state = STORAGE.save_state(self.state_path, self.state)

    def get(self, url):
        if self.config.get('postprocess_only'):
            raise ARTICLE.PaginationError('offline_missing_page')
        parsed = urlsplit(url)
        if (parsed.scheme not in ('http', 'https') or not PARSER.is_host(url)
                or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
            raise ValueError('Unsafe or non-cnkang URL: ' + url)
        self.wait()
        self.state['last_request'] = time.time()
        self.save_state()
        start = time.monotonic()
        event = {'url': url, 'at': utc()}
        self.network_events.append(event)
        response = None
        try:
            self.budget('request_start')
            limit = NETWORK.deadline(self.config['request_deadline'])
            scope = 'request'
            if self._url_limit is not None and NETWORK.remaining(self._url_limit) < NETWORK.remaining(limit):
                limit, scope = self._url_limit, 'url'
            if self._article_limit is not None and NETWORK.remaining(self._article_limit) < NETWORK.remaining(limit):
                limit, scope = self._article_limit, 'article'
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
            # Persist 429 before any raw/record I/O can fail. A failed replace leaves
            # this conservative state in its fsynced recovery file.
            if response is not None and response.status_code == 429:
                self.state['not_before'] = max(self.state.get('not_before', 0),
                                              time.time() + self.retry_after(response))
            try:
                self.save_state()
            except CheckpointError as exc:
                exc.response = response
                raise

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

    def pending_response_path(self, sample, record_dir):
        return self.out / 'cnkang_pending' / record_dir / f"{sample['id']}.json"

    def validate_record(self, record, sample):
        source = sample.get('source_url') or sample['url']
        if (record.get('id'), record.get('source_url') or record.get('url')) != (sample['id'], source):
            raise CheckpointError(self.out, 'recover_record', ValueError('Checkpoint ID/URL mismatch'))
        if record.get('status') == 'extracted':
            try:
                raw = (self.out / record['raw_html_path']).read_bytes()
                if PARSER.sha(raw) != record['raw_sha256']:
                    raise ValueError('Raw checkpoint hash mismatch')
                if gzip.decompress((self.out / record['raw_path']).read_bytes()) != raw:
                    raise ValueError('Compressed raw checkpoint mismatch')
                for key, field in (('text_before_path', 'text_before'), ('text_clean_path', 'text')):
                    if (self.out / record[key]).read_bytes() != record[field].encode('utf-8'):
                        raise ValueError('Text checkpoint mismatch: ' + key)
                PARSER.audit(raw, record['final_url'], record, record['content_type'], base_dir=self.out)
            except (OSError, ValueError, KeyError) as exc:
                raise CheckpointError(self.out, 'verify_record', exc) from exc
        return record

    def cached_record(self, sample, record_dir='records'):
        path = self.out / record_dir / f"{sample['id']}.json"
        if path.exists():
            return self.validate_record(STORAGE.read_json(path), sample)
        for pending in STORAGE.pending_paths(path):
            try:
                record = self.validate_record(STORAGE.read_json(pending), sample)
            except CheckpointError:
                continue  # A durable response bundle can reconstruct an incomplete write.
            self.writer.acquire()
            return self.commit_record(record, sample, record_dir)
        return None

    def stage_response(self, sample, record_dir, record, response):
        if 200 <= response.status_code < 300:
            record['network_requests'] = self.network_events
            write_json(self.pending_response_path(sample, record_dir), {
                'record': record, 'body_sha256': PARSER.sha(response.content),
                'body_base64': base64.b64encode(response.content).decode('ascii'),
                'headers': dict(response.headers), 'status': response.status_code})

    def save_raw(self, record, response, key, current, event):
        body, body_hash = response.content, PARSER.sha(response.content)
        raw = Path('raw') / (key + '_' + body_hash + '.gz')
        html_path = Path('raw_html') / (key + '_' + body_hash + '.html')
        STORAGE.write_bytes(self.out / raw, gzip.compress(body, mtime=0))
        STORAGE.write_bytes(self.out / html_path, body)
        if (PARSER.sha((self.out / html_path).read_bytes()) != body_hash
                or gzip.decompress((self.out / raw).read_bytes()) != body):
            raise CheckpointError(self.out / raw, 'verify_raw', ValueError('Raw write hash mismatch'))
        event.update(http_status=response.status_code, raw_path=raw.as_posix(), raw_sha256=body_hash)
        record.update(http_status=response.status_code,
            content_type=response.headers.get('Content-Type', ''),
            raw_path=raw.as_posix(), raw_html_path=html_path.as_posix(), raw_sha256=body_hash,
            final_url=current, fetched_at=utc())

    def parse_response(self, record, response, key, current):
        content_type = record['content_type'].lower()
        if 'html' not in content_type and not re_html(response.content):
            record.update(error='Unsupported content type: ' + content_type, error_kind='content_type')
            return
        decoded, _ = PARSER.decode_bytes(response.content, content_type)
        if is_error_page(decoded):
            record.update(error='Challenge, soft error or empty HTML', error_kind='soft_error_or_challenge',
                          challenge_detected=True)
            return
        record.update(status='fetched', crawl_status='fetched')
        for field in ('error', 'error_kind', 'error_stage', 'error_causes', 'error_context',
                      'retry_deferred', 'retry_after_seconds'):
            record.pop(field, None)
        append(self.out / 'crawl_journal.jsonl', dict(record, event='fetched'))
        doc = PARSER.extract(response.content, current, record['content_type'])
        record.update(doc, status='extracted',
                      crawl_status='needs_review' if doc['quality_status'] != 'accepted' else 'parsed')
        for folder, field in (('text_before', 'text_before'), ('text_clean', 'text')):
            path = Path(folder) / (key + '_' + PARSER.sha(record[field]) + '.txt')
            STORAGE.write_bytes(self.out / path, record[field].encode('utf-8'))
            record[folder + '_path'] = path.as_posix()

    def commit_record(self, record, sample, record_dir):
        if (not self._page_mode and record.get('status') == 'extracted'
                and not record.get('article_schema')):
            if ARTICLE.required(record, record['final_url']):
                record = ARTICLE.complete(self, record, sample, record_dir)
                root_key = PARSER.sha(record['canonical_url'])
                for folder, field in (('text_before', 'text_before'), ('text_clean', 'text')):
                    target = Path(folder) / (root_key + '_' + PARSER.sha(record[field]) + '.txt')
                    STORAGE.write_bytes(self.out / target, record[field].encode('utf-8'))
                    record[folder + '_path'] = target.as_posix()
            else:
                record.update(article_complete=record['template'] != 'unknown', article_page_count=1)
        if record.get('status') == 'extracted':
            policy_path = self.out / 'cnkang_source_policy.json'
            policy = {'mode':self.config.get('source_policy_mode','report_only'),
                      'policy_version':PARSER.SOURCE.VERSION,'policy_sha256':PARSER.SOURCE.POLICY_SHA256}
            if policy_path.exists() and STORAGE.read_json(policy_path) != policy:
                raise ValueError('Source policy changed; use a new run and recovery')
            if not policy_path.exists(): write_json(policy_path,policy)
            PARSER.SOURCE.apply(record)
            record = PARSER.SOURCE.publish(record, self.config.get('source_policy_mode', 'report_only'))
        if not self._page_mode and self._article_started is not None:
            record['elapsed_seconds'] = round(time.monotonic() - self._article_started, 3)
        path = self.out / record_dir / f"{sample['id']}.json"
        write_json(path, record)
        append(self.out / 'crawl_journal.jsonl', dict(record, event='checkpoint'))
        for target in (path, self.pending_response_path(sample, record_dir)):
            for pending in STORAGE.pending_paths(target): STORAGE.discard(pending)
        STORAGE.discard(self.pending_response_path(sample, record_dir))
        return record

    def restore_response(self, sample, record_dir):
        path = self.pending_response_path(sample, record_dir)
        candidates = ([path] if path.exists() else []) + STORAGE.pending_paths(path)
        if not candidates: return None
        bundle = STORAGE.read_json(candidates[0])
        source = sample.get('source_url') or sample['url']
        try:
            record = bundle['record']
            if (record.get('id'), record.get('source_url')) != (sample['id'], source):
                raise ValueError('Pending response ID/URL mismatch')
            body = base64.b64decode(bundle['body_base64'], validate=True)
            if PARSER.sha(body) != bundle['body_sha256'] or not 200 <= bundle['status'] < 300:
                raise ValueError('Pending response hash/status mismatch')
            if not record.get('requests') or not isinstance(bundle['headers'], dict):
                raise ValueError('Missing pending request/headers')
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise CheckpointError(path, 'recover_response', exc) from exc
        response = requests.Response()
        response.status_code, response._content = bundle['status'], body
        response.headers.update(bundle['headers'])
        begin = time.monotonic()
        current = record['final_url']
        key = PARSER.sha(record['canonical_url'])
        self.network_events = record.get('network_requests', [])
        self.save_raw(record, response, key, current, record['requests'][-1])
        try:
            self.parse_response(record, response, key, current)
        except CheckpointError:
            raise
        except Exception as exc:
            record.update(status='parse_failed', crawl_status='needs_review',
                          error_kind='parser_exception', error=f'{type(exc).__name__}: {exc}'[:700],
                          parser_flags=['PARSER_EXCEPTION_REVIEW'])
        record.update(attempts=len(record['requests']), finished_at=utc(),
                      recovered_from_checkpoint=True, recovery_elapsed_seconds=round(time.monotonic() - begin, 3))
        record.setdefault('elapsed_seconds', sum(e.get('elapsed_seconds', 0) for e in self.network_events))
        return self.commit_record(record, sample, record_dir)

    def fetch(self, sample, *, record_dir='records'):
        root_call = not self._page_mode
        if root_call:
            self._article_limit = NETWORK.deadline(self.config['article_deadline'])
            self._article_started = time.monotonic()
        try:
            self.writer.acquire()
            cached = self.cached_record(sample, record_dir)
            member_retry = (self._page_mode and cached is not None and cached.get('status') != 'extracted'
                            and cached.get('http_status') not in (401, 403)
                            and not cached.get('challenge_detected'))
            if cached is not None and not cached.get('retry_deferred') and not member_retry:
                return cached
            if cached is not None and cached.get('article_manifest_path'):
                manifest = STORAGE.read_json(self.out / cached['article_manifest_path'])
                first = STORAGE.read_json(self.out / manifest['parts'][0]['checkpoint_path'])
                first.update({k: cached[k] for k in ('id', 'ids', 'url', 'source_url', 'canonical_url', 'branch')
                              if k in cached})
                first.pop('article_member', None)
                return self.commit_record(first, sample, record_dir)
            restored = self.restore_response(sample, record_dir)
            return restored if restored is not None else self._fetch(sample, record_dir=record_dir)
        except CheckpointError as exc:
            self.stopped, self.stop_reason = True, 'CHECKPOINT_WRITE_FAILED'
            exc.details['id'] = sample['id']
            if exc.details['error_code'] != 'CHECKPOINT_WRITER_BUSY':
                try:
                    write_json(self.out / 'cnkang_checkpoint_error.json', exc.details)
                except CheckpointError:
                    pass
            print(json.dumps(exc.details, ensure_ascii=False), flush=True)
            self.worker.close()
            raise
        finally:
            self._url_limit = None
            if root_call:
                self._article_limit = self._article_started = None

    def _fetch(self, sample, *, record_dir='records'):
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
                        record['final_url'] = current
                        try:
                            response = self.get(current)
                        except CheckpointError as exc:
                            if getattr(exc, 'response', None) is not None:
                                self.stage_response(sample, record_dir, record, exc.response)
                            raise
                        self.budget('response')
                        self.stage_response(sample, record_dir, record, response)
                        self.save_raw(record, response, key, current, event)
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
                    if self._page_mode:
                        try:
                            if ARTICLE.identity(target) != ARTICLE.identity(source):
                                raise ARTICLE.PaginationError('page_redirect_identity_mismatch')
                        except ARTICLE.PaginationError as exc:
                            record.update(error=str(exc), error_kind='pagination_redirect_review')
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
                self.parse_response(record, response, key, current)
                break
            else:
                record.update(error='Redirect limit exceeded', error_kind='redirect_limit')
        except CheckpointError:
            raise
        except NetworkFailure as exc:
            record.update(exc.details)
            self.stopped, self.stop_reason = True, exc.details['error_kind']
        except Paused as exc:
            self.stopped = True
            record.update(error=str(exc), retry_deferred=True, error_kind='cooldown')
        except (requests.RequestException, ValueError) as exc:
            record.update(error=f'{type(exc).__name__}: {exc}'[:700], error_kind='fetch_or_parse_error')
        except OSError as exc:
            raise CheckpointError(self.out, 'fetch_checkpoint', exc) from exc
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
        return self.commit_record(record, sample, record_dir)

    def close(self):
        try:
            self.worker.close()
        finally:
            self.writer.close()


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


def crawl(crawler, probe, out, samples, config=None, *, max_new=None, on_record=None, log_every=25,
          record_dir='requests_records'):
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
            previous = transport.cached_record(sample, record_dir)
            if previous is not None:
                if not previous.get('retry_deferred'):
                    if on_record: on_record(previous)
                    continue
            if transport.stopped or (max_new is not None and done >= max_new):
                break
            record = transport.fetch(sample, record_dir=record_dir)
            done += 1
            if on_record: on_record(record)
            if done % log_every == 0 or record['status'] != 'extracted' or record.get('article_complete') is False:
                print(json.dumps({'engine':'cnkang_requests', 'completed':done,
                                  'id':sample['id'], 'status':record['crawl_status'],
                                  'http':record.get('http_status')}, ensure_ascii=False), flush=True)
    finally:
        transport.close()
    return done


def seed_recovery(out, samples, source, config=None, *, record_dir='requests_records'):
    """Re-extract every available member raw in a new run, with networking disabled."""
    out, source = Path(out).resolve(), Path(source).resolve()
    if out == source:
        raise ValueError('cnkang recovery requires a separate output run')
    net = Transport(out, {**(config or {}), 'postprocess_only': True})
    reused = []
    try:
        net.writer.acquire()
        prior = STORAGE.load_state(source / 'cnkang_transport_state.json')
        if prior:
            net.state.update({k: max(net.state.get(k, 0), prior.get(k, 0))
                              for k in ('not_before', 'last_request')})
            net.save_state()
        marker = out / 'cnkang_recovery_manifest.json'
        identity = {'source': str(source), 'samples': [[s['id'], s['url']] for s in samples],
                    'parser_version': PARSER.VERSION, 'article_version': ARTICLE.VERSION,
                    'source_policy_sha256': PARSER.SOURCE.POLICY_SHA256}
        if marker.exists():
            saved = STORAGE.read_json(marker)
            if any(saved.get(k) != v for k, v in identity.items()):
                raise ValueError('cnkang recovery identity changed')
            return saved
        cache_index = {}
        for cache in (source / 'cnkang_pages').glob('*.json'):
            saved = STORAGE.read_json(cache)
            try:
                page_identity = ARTICLE.identity(saved['source_url'])[:2]
            except (KeyError, ARTICLE.PaginationError):
                continue
            if saved.get('status') == 'extracted':
                cache_index.setdefault(page_identity, []).append(saved)

        def reextract(saved, requested):
            raw = gzip.decompress(ARTICLE.safe_path(source, saved['raw_path']).read_bytes())
            if len(raw) > net.config['max_bytes'] or PARSER.sha(raw) != saved['raw_sha256']:
                raise ValueError('cnkang recovery raw hash/size mismatch')
            if not 200 <= (saved.get('http_status') or 0) < 300:
                return None
            doc = PARSER.extract(raw, saved['final_url'], saved.get('content_type') or 'text/html')
            page_sample = ARTICLE.cache_sample(PARSER, requested)
            member = dict(page_sample, **doc, engine='requests', status='extracted',
                crawl_status='parsed' if doc['quality_status'] == 'accepted' else 'needs_review',
                final_url=saved['final_url'], http_status=saved.get('http_status', 200),
                content_type=saved.get('content_type') or 'text/html',
                started_at=saved.get('started_at', utc()), fetched_at=saved.get('fetched_at'),
                requests=[], redirects=[], attempts=0, network_requests=[],
                reused_from=str(source), reprocessed_at=utc())
            event = {}
            net.save_raw(member, _response(raw, member['content_type']), PARSER.sha(page_sample['canonical_url']),
                         member['final_url'], event)
            for folder, field in (('text_before', 'text_before'), ('text_clean', 'text')):
                path = Path(folder) / (PARSER.sha(page_sample['canonical_url']) + '_' + PARSER.sha(member[field]) + '.txt')
                STORAGE.write_bytes(out / path, member[field].encode('utf-8'))
                member[folder + '_path'] = path.as_posix()
            STORAGE.write_json(out / 'cnkang_pages' / f"{page_sample['id']}.json", member)
            return member

        for sample in samples:
            old_path = source / 'records' / f"{sample['id']}.json"
            if not old_path.exists(): old_path = source / record_dir / f"{sample['id']}.json"
            if not old_path.exists(): continue
            old = STORAGE.read_json(old_path)
            if (old['id'], old['url']) != (sample['id'], sample['url']):
                raise ValueError('cnkang recovery ID/URL mismatch')
            if old.get('status') != 'extracted' or not old.get('raw_path'):
                continue
            sources = [(old, old['final_url'])]
            if old.get('article_manifest_path'):
                data = ARTICLE.safe_path(source, old['article_manifest_path']).read_bytes()
                if PARSER.sha(data) != old['article_manifest_sha256']:
                    raise ValueError('cnkang recovery article manifest hash mismatch')
                manifest = json.loads(data)
                sources = []
                for part in manifest['parts']:
                    data = ARTICLE.safe_path(source, part['checkpoint_path']).read_bytes()
                    if PARSER.sha(data) != part['checkpoint_sha256']:
                        raise ValueError('cnkang recovery page checkpoint hash mismatch')
                    saved = json.loads(data)
                    if ARTICLE.cache_key(saved['final_url']) != ARTICLE.cache_key(part['requested_url']):
                        raise ValueError('cnkang recovery page URL mismatch')
                    sources.append((saved, part['requested_url']))
            # Include durable page caches beyond the manifest after a crash.
            try:
                source_identity = ARTICLE.identity(old['final_url'])[:2]
            except ARTICLE.PaginationError:
                source_identity = None
            for saved in cache_index.get(source_identity, []):
                sources.append((saved, saved['source_url']))
            first = None
            seen = set()
            for saved, requested in sources:
                if ARTICLE.cache_key(requested) in seen: continue
                seen.add(ARTICLE.cache_key(requested))
                member = reextract(saved, requested)
                if first is None: first = member
            if first is None: continue
            first.update({k: sample[k] for k in ('id', 'ids', 'url', 'source_url', 'canonical_url', 'branch')
                          if k in sample})
            first['ids'] = sample.get('ids', [sample['id']])
            first['source_url'] = sample.get('source_url') or sample['url']
            first['url'] = sample['url']
            first['canonical_url'] = sample.get('canonical_url') or sample['url']
            first.setdefault('branch', urlsplit(sample['url']).path.strip('/').split('/')[0])
            first.pop('article_member', None)
            net.commit_record(first, sample, record_dir)
            reused.append(sample['id'])
        result = {**identity, 'reused_ids': reused, 'postprocess_only': True}
        STORAGE.write_json(marker, result)
        return result
    finally:
        net.close()


def _response(body, content_type):
    response = requests.Response()
    response.status_code, response._content = 200, body
    response.headers['Content-Type'] = content_type
    return response


def audit_saved(out, record):
    raw = gzip.decompress(ARTICLE.safe_path(out, record['raw_path']).read_bytes())
    if PARSER.sha(raw) != record['raw_sha256']:
        raise ValueError('cnkang raw checkpoint hash mismatch')
    return PARSER.audit(raw, record['final_url'], record, record['content_type'], base_dir=out)
