"""Sequential PubMed EFetch GET with PMID joins and durable batch checkpoints."""
import csv
from collections import deque
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import io
import json
import math
import os
from pathlib import Path
import re
import random
import time
from urllib.parse import quote_plus, urlsplit

import requests

import xml.etree.ElementTree as ET

def xml_text(node):
    """Preserve mixed inline text without adding spaces inside words; retain block boundaries."""
    if node is None:
        return ''
    blocks = {'p', 'para', 'div', 'li', 'list-item', 'br'}
    def walk(element):
        pieces = [element.text or '']
        for child in element:
            block = child.tag.rsplit('}', 1)[-1].lower() in blocks
            if block:
                pieces.append('\n\n')
            pieces.append(walk(child))
            if block:
                pieces.append('\n\n')
            pieces.append(child.tail or '')
        return ''.join(pieces)
    return '\n\n'.join(' '.join(part.split()) for part in walk(node).split('\n') if part.strip())

def extract_record(record):
    if record.tag == 'PubmedArticle':
        citation = record.find('MedlineCitation')
        article = citation.find('Article') if citation is not None else None
        pmid_node = citation.find('PMID') if citation is not None else None
        title_node = article.find('ArticleTitle') if article is not None else None
        abstracts = [] if article is None else [(n, 'Abstract') for n in article.findall('Abstract')]
        if citation is not None:
            abstracts.extend((n, 'OtherAbstract') for n in citation.findall('OtherAbstract'))
    else:
        document = record.find('BookDocument')
        pmid_node = document.find('PMID') if document is not None else None
        title_node = document.find('ArticleTitle') if document is not None else None
        abstracts = [] if document is None else [(n, 'Abstract') for n in document.findall('Abstract')]
        if document is not None:
            abstracts.extend((n, 'OtherAbstract') for n in document.findall('OtherAbstract'))
    pmid = xml_text(pmid_node)
    if not re.fullmatch(r'[1-9][0-9]*', pmid):
        raise ValueError('Bản ghi XML thiếu PMID hợp lệ')
    title = xml_text(title_node)
    sections, lines = [], []
    for abstract, origin in abstracts:
        language, kind = abstract.get('Language', ''), abstract.get('Type', '')
        group_lines = []
        for node in abstract.findall('AbstractText'):
            body = xml_text(node)
            label = node.get('Label', '').strip()
            category = node.get('NlmCategory', '').strip()
            display_label = label or (category if category != 'UNASSIGNED' else '')
            sections.append({'origin': origin, 'language': language, 'type': kind,
                             'label': label, 'nlm_category': category, 'text': body})
            if body:
                prefix = display_label.rstrip(':') + ': ' if display_label else ''
                group_lines.append(prefix + body)
        if group_lines:
            if origin == 'OtherAbstract':
                lines.append('Other abstract' + (f' ({language})' if language else '') + ':')
            lines.extend(group_lines)
    abstract_text = '\n\n'.join(lines)
    text = '\n\n'.join(part for part in [title, abstract_text] if part)
    has_abstract = any(section['text'] for section in sections)
    status = 'no_abstract' if not has_abstract else ('missing_title' if not title else 'accepted')
    return {'pmid': pmid, 'title': title, 'abstract_sections': sections, 'text': text,
            'status': status, 'has_abstract': has_abstract, 'error': ''}

def parse_efetch(payload, requested_pmids):
    if b'<!ENTITY' in payload.upper():
        raise ValueError('XML có ENTITY không được hỗ trợ')
    root = ET.fromstring(payload)
    errors = [xml_text(n) for n in root.iter() if n.tag.upper() == 'ERROR']
    if errors:
        raise ValueError('EFetch ERROR: ' + '; '.join(errors))
    if root.tag != 'PubmedArticleSet':
        raise ValueError(f'XML root không đúng: {root.tag}')
    requested = set(requested_pmids)
    records, duplicate_pmids, anomalies = {}, set(), []
    for element in root:
        if element.tag not in {'PubmedArticle', 'PubmedBookArticle'}:
            anomalies.append({'kind': 'unexpected_xml_element', 'tag': element.tag})
            continue
        try:
            item = extract_record(element)
        except ValueError as exc:
            anomalies.append({'kind': 'invalid_record_pmid', 'error': str(exc)})
            continue
        pmid = item['pmid']
        if pmid not in requested:
            anomalies.append({'kind': 'unexpected_pmid', 'pmid': pmid})
            continue
        if pmid in records:
            duplicate_pmids.add(pmid)
            anomalies.append({'kind': 'duplicate_api_pmid', 'pmid': pmid})
        else:
            records[pmid] = item
    for pmid in duplicate_pmids:
        records[pmid] = {'pmid': pmid, 'title': '', 'abstract_sections': [], 'text': '',
                         'has_abstract': False, 'status': 'duplicate_api_pmid',
                         'error': 'XML trả nhiều bản ghi cùng PMID; cần kiểm tra raw.'}
    return records, anomalies


VERSION = 'pubmed-efetch-v1'
TRANSPORT_VERSION = 'pubmed-efetch-transport-v2'  # XML/record contract stays compatible with saved v1 batches.
ENDPOINT = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
DEFAULTS = {'batch_size': 100, 'workers': 1, 'gap_seconds': .5, 'attempts': 5,
            'timeout': [10., 90.], 'budget': 300., 'min_batch_size': 1,
            'max_split_requests': 50, 'fallback_budget': 900., 'pending_retry_passes': 1,
            'max_consecutive_failed_batches': 3, 'checkpoint': {'enabled': False}}
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


def validate_config(config):
    config = {**DEFAULTS, **config}
    if type(config['batch_size']) is not int or not 1 <= config['batch_size'] <= 100:
        raise ValueError('EFetch GET batch_size must be an integer in 1..100.')
    if type(config['workers']) is not int or config['workers'] != 1:
        raise ValueError('EFetch uses exactly one worker.')
    if type(config['attempts']) is not int or config['attempts'] < 1:
        raise ValueError('EFetch attempts must be a positive integer.')
    for key, minimum in [('gap_seconds', .5), ('budget', .01)]:
        if not isinstance(config[key], (int, float)) or not math.isfinite(config[key]) or config[key] < minimum:
            raise ValueError(f'Invalid EFetch {key}.')
    timeout = config['timeout']
    if len(timeout) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in timeout):
        raise ValueError('EFetch timeout needs two finite positive numbers.')
    for key, minimum in [('min_batch_size', 1), ('max_split_requests', 1),
                         ('pending_retry_passes', 0), ('max_consecutive_failed_batches', 1)]:
        if type(config[key]) is not int or config[key] < minimum:
            raise ValueError(f'Invalid EFetch {key}.')
    if config['min_batch_size'] > config['batch_size'] or config['pending_retry_passes'] > 3:
        raise ValueError('Invalid minimum batch size or pending retry passes (0..3).')
    if not math.isfinite(config['fallback_budget']) or config['fallback_budget'] <= 0:
        raise ValueError('EFetch fallback_budget must be finite and positive.')
    config['checkpoint'] = checkpoint_module().validate_config(config['checkpoint'])
    return config


def pmid_from_url(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r'/([1-9][0-9]*)/?', parsed.path)
    if parsed.hostname != 'pubmed.ncbi.nlm.nih.gov' or not match:
        raise ValueError('PubMed URL has no valid PMID.')
    return match.group(1)


def redact(value):
    text = str(value)
    for name in ('NCBI_API_KEY', 'NCBI_EMAIL'):
        secret = os.environ.get(name, '')
        if secret:
            text = text.replace(secret, '[redacted]').replace(quote_plus(secret), '[redacted]')
    return text[:1500]


def retry_after_seconds(value):
    try:
        result = float(value)
        return max(0., result) if math.isfinite(result) else 0.
    except (ValueError, TypeError):
        try:
            return max(0., (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0.


def transient_400(payload):
    """NCBI sometimes wraps its viewer timeout in a 400; invalid request parameters stay permanent."""
    import html
    text = re.sub(r'<[^>]*>', ' ', html.unescape(payload.decode('utf-8', 'replace'))).casefold()
    if re.search(r'\b(?:invalid|unknown|unsupported)\s+(?:\w+\s+){0,2}(?:parameter|uid|id)\b', text):
        return False
    return bool(re.search(r'\b(?:timeout|timed\s+out|empty\s+response)\b', text))


class BatchFailure(RuntimeError):
    def __init__(self, evidence):
        super().__init__('EFetch batch failed; URLs remain pending: ' + evidence['error'])
        self.evidence = evidence
        self.retryable = evidence.get('retryable', False)
        self.split_allowed = evidence.get('split_allowed', False)
        self.deferred = evidence.get('deferred', False)


def checkpoint_module():
    import importlib.util
    path = Path(__file__).parent / 'checkpoint_snapshot.py'
    if not path.exists(): path = Path(__file__).parent / 'corpus_checkpoint.py'
    spec = importlib.util.spec_from_file_location('efetch_checkpoints', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EFetchClient:
    def __init__(self, crawler, out, config, session=None):
        self.crawler, self.out, self.config = crawler, Path(out), config
        self.session = session if session is not None else requests.Session()
        self.session.headers.update({'User-Agent': 'AncientWings-PubMed-EFetch/1.0', 'Accept': 'application/xml'})
        self.gate_path = self.out / 'pubmed_request_gate.json'
        self.not_before = (crawler.load_json(self.gate_path).get('not_before', 0.)
                           if self.gate_path.exists() else 0.)
        self.total_requests = 0

    def close(self):
        self.session.close()

    def wait_ready(self, deadline):
        if self.not_before - time.time() >= deadline - time.monotonic():
            raise TimeoutError('EFetch pacing/Retry-After exceeds batch request budget; resume later.')
        while time.time() < self.not_before:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('EFetch pacing/Retry-After exceeds batch request budget; resume later.')
            time.sleep(min(1., self.not_before - time.time(), remaining))

    def failed(self, batch_samples, traces, *, error, retryable=False, split_allowed=False, deferred=False):
        key = self.crawler.digest(json.dumps(batch_samples, sort_keys=True).encode())
        evidence = {'samples': batch_samples, 'pmids': list(dict.fromkeys(pmid_from_url(s['url']) for s in batch_samples)),
            'requests': traces, 'error': redact(error), 'retryable': retryable, 'split_allowed': split_allowed,
            'deferred': deferred, 'transport_version': TRANSPORT_VERSION, 'urls_pending_at_failure': True,
            'at': self.crawler.utc(), 'failure_path': f'pubmed_batch_failures/{key}.json'}
        self.crawler.write_json(self.out / evidence['failure_path'], evidence)
        with (self.out / 'pubmed_batch_failures/history.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(evidence, ensure_ascii=False) + '\n')
        raise BatchFailure(evidence)

    def fetch(self, batch_samples, *, deadline=None, max_requests=None):
        pmids = list(dict.fromkeys(pmid_from_url(s['url']) for s in batch_samples))
        params = {'db': 'pubmed', 'retmode': 'xml', 'id': ','.join(pmids), 'tool': 'AncientWingsPubMedCrawler'}
        for name, parameter in [('NCBI_EMAIL', 'email'), ('NCBI_API_KEY', 'api_key')]:
            if os.environ.get(name):
                params[parameter] = os.environ[name]
        deadline = min(float('inf') if deadline is None else deadline, time.monotonic() + self.config['budget'])
        traces, last = [], {}
        initial_requests = self.total_requests
        retryable, split_allowed, deferred = True, True, False
        for attempt in range(1, self.config['attempts'] + 1):
            if max_requests is not None and self.total_requests - initial_requests >= max_requests:
                break
            try:
                self.wait_ready(deadline)
            except TimeoutError as exc:
                cooldown = self.not_before - time.time() >= self.config['budget']
                return self.failed(batch_samples, traces, error=str(exc), retryable=True,
                                   split_allowed=not cooldown, deferred=cooldown)
            event = {'method': 'GET', 'url': ENDPOINT, 'attempt': attempt, 'pmids': pmids,
                     'started_at': self.crawler.utc(), 'http_status': None}
            started = time.monotonic()
            payload, pause, retryable, split_allowed, success = b'', 0., True, True, False
            chunks, size, response_started, raw_complete = [], 0, False, False
            try:
                remaining = deadline - started
                if remaining <= 0:
                    raise TimeoutError('EFetch batch budget exhausted.')
                timeout = tuple(min(v, remaining / 2) for v in self.config['timeout'])
                # Sequential GET; no hidden retries or redirects outside the pacing guard.
                self.total_requests += 1
                with self.session.get(ENDPOINT, params=params, timeout=timeout,
                                      allow_redirects=False, stream=True) as response:
                    status = response.status_code
                    response_started = True
                    event.update(http_status=status, content_type=response.headers.get('Content-Type', ''))
                    pause = retry_after_seconds(response.headers.get('Retry-After'))
                    for chunk in response.iter_content(64 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            retryable = False
                            split_allowed = True
                            raise ValueError('EFetch response exceeds 16 MiB; reduce batch_size.')
                        if time.monotonic() > deadline:
                            raise TimeoutError('EFetch response exceeded batch budget.')
                        chunks.append(chunk)
                    payload = b''.join(chunks)
                    raw_complete = True
                    if status != 200:
                        retryable = status in {408, 429} or 500 <= status < 600 or (status == 400 and transient_400(payload))
                        split_allowed = retryable and status != 429
                        event['error_kind'] = 'transient_http_400' if status == 400 and retryable else f'http_{status}'
                        raise ValueError(f'HTTP {status}; see saved EFetch response.')
                    records, anomalies = parse_efetch(payload, pmids)
                    success = True
            except (requests.RequestException, ValueError, ET.ParseError, TimeoutError) as exc:
                event['error'] = redact(f'{type(exc).__name__}: {exc}')
                if isinstance(exc, requests.exceptions.SSLError):
                    retryable = split_allowed = False
                if event.get('http_status') == 200 and payload.lstrip().lower().startswith((b'<html', b'<!doctype html')):
                    split_allowed = False
            except BaseException as exc:
                event['error'] = type(exc).__name__
                raise
            finally:
                if response_started:
                    payload = b''.join(chunks)
                    raw_sha = self.crawler.digest(payload)
                    raw_path = f'raw/efetch/{raw_sha[:2]}/{raw_sha}.gz'
                    self.crawler.atomic_bytes(self.out / raw_path, gzip.compress(payload, mtime=0))
                    event.update(raw_path=raw_path, raw_sha256=raw_sha, raw_bytes=len(payload), raw_complete=raw_complete)
                event.update(retryable=retryable, split_allowed=split_allowed)
                backoff = (max(self.config['gap_seconds'], pause, 2 ** (attempt - 1) + random.uniform(0., .5))
                           if not success and retryable and attempt < self.config['attempts'] else 0.)
                if backoff: event['retry_wait_seconds'] = round(backoff, 3)
                event['elapsed_seconds'] = round(time.monotonic() - started, 3)
                event['finished_at'] = self.crawler.utc()
                self.not_before = time.time() + max(self.config['gap_seconds'], pause, backoff)
                self.crawler.write_json(self.gate_path, {'not_before': self.not_before})
                with (self.out / 'pubmed_requests.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                traces.append(event)
                last = event
            if success:
                return {'version': VERSION, 'samples': batch_samples, 'pmids': pmids,
                        'transport_version': TRANSPORT_VERSION,
                        'raw_path': last['raw_path'], 'raw_sha256': last['raw_sha256'],
                        'requests': traces, 'anomalies': anomalies}
            print(json.dumps({'pubmed_efetch_attempt': attempt, 'http_status': last['http_status'],
                              'error': last.get('error'), 'pmid_count': len(pmids)}, ensure_ascii=False), flush=True)
            if self.not_before - time.time() >= deadline - time.monotonic():
                deferred = self.not_before - time.time() >= self.config['budget']
                if deferred: split_allowed = False
                break  # Preserve the server cooldown; a later resume respects it too.
            if not retryable or attempt == self.config['attempts']:
                break
        return self.failed(batch_samples, traces, error=last.get('error', 'Fallback request/time budget exhausted'),
                           retryable=retryable, split_allowed=split_allowed, deferred=deferred)


def read_record(crawler, out, sample):
    path = Path(out) / 'pubmed_records' / f"{sample['id']}.json"
    if not path.exists():
        return None
    item = crawler.load_json(path)
    if (item.get('id'), item.get('url')) != (sample['id'], sample['url']):
        raise ValueError('EFetch checkpoint ID/URL mismatch.')
    return item


def make_record(crawler, sample, item, batch):
    pmid = pmid_from_url(sample['url'])
    doc = {'title': '', 'text': '', 'pubmed_pmid': pmid, 'pubmed_pmid_verified': False,
           'extractor': 'pubmed_efetch_xml_v1', 'abstract_sections': [], 'source_abstract_chars': 0}
    if item:
        doc.update(title=item['title'], text=item['text'], abstract_sections=item['abstract_sections'],
                   pubmed_pmid_verified=item['status'] != 'duplicate_api_pmid',
                   source_abstract_chars=sum(len(s['text']) for s in item['abstract_sections']))
    record = dict(sample, **doc, **crawler.quality(doc), engine='efetch', pubmed_route='efetch',
                  pubmed_api_status=item['status'] if item else 'missing_pmid',
                  status='extracted' if item and item['status'] != 'duplicate_api_pmid' else 'pubmed_missing_pmid' if not item else 'pubmed_duplicate_pmid',
                  http_status=200, content_type='application/xml; charset=utf-8', declared_encoding='utf-8',
                  final_url=sample['url'], api_endpoint=ENDPOINT, raw_path=batch['raw_path'],
                  raw_sha256=batch['raw_sha256'], started_at=batch['requests'][0]['started_at'],
                  finished_at=batch['requests'][-1]['finished_at'],
                  elapsed_seconds=round(sum(t['elapsed_seconds'] for t in batch['requests']) / len(batch['samples']), 3),
                  efetch_batch_elapsed_seconds=round(sum(t['elapsed_seconds'] for t in batch['requests']), 3),
                  requests=[{k: t.get(k) for k in ('method', 'url', 'attempt', 'http_status', 'elapsed_seconds', 'error')}
                            for t in batch['requests']])
    if not item or item['status'] in ('no_abstract', 'duplicate_api_pmid'):
        flag = 'pubmed_' + record['pubmed_api_status']
        record['quality_flags'].append(flag)
        record['quality_status'] = 'review' if item and item['status'] == 'no_abstract' else 'rejected'
        record['error'] = item.get('error') if item else 'Requested PMID missing from valid EFetch XML.'
    return record


def apply_batch(crawler, out, batch, samples_by_id, on_record=None):
    if batch.get('version') != VERSION:
        raise ValueError('EFetch batch parser version changed; use recovery in a new run.')
    raw = (Path(out) / batch['raw_path']).resolve()
    if not raw.is_relative_to((Path(out) / 'raw').resolve()):
        raise ValueError('EFetch raw path escapes run raw directory.')
    for sample in batch['samples']:
        if samples_by_id.get(sample['id']) != sample:
            raise ValueError('EFetch batch sample ID/URL/provenance changed.')
    # A durable batch can repair partially written per-ID checkpoints without another GET.
    body = gzip.decompress(raw.read_bytes())
    if crawler.digest(body) != batch['raw_sha256']:
        raise ValueError('EFetch raw hash mismatch.')
    records, _ = parse_efetch(body, batch['pmids'])
    for sample in batch['samples']:
        existing = read_record(crawler, out, sample)
        if existing is None:
            record = make_record(crawler, sample, records.get(pmid_from_url(sample['url'])), batch)
            crawler.write_json(Path(out) / 'pubmed_records' / f"{sample['id']}.json", record)
        else:
            record = existing
        if on_record:
            on_record(record)


def seed_recovery(crawler, out, samples, previous, on_record=None):
    """Reuse verified EFetch XML only; the new API route refetches old HTML PubMed rows."""
    previous, out = Path(previous), Path(out)
    by_raw = {}
    for sample in samples:
        old = read_record(crawler, previous, sample)
        if old and old.get('pubmed_pmid_verified') and old.get('quality_status') == 'accepted':
            by_raw.setdefault(old['raw_path'], []).append(sample)
    for raw_path, group in by_raw.items():
        old = read_record(crawler, previous, group[0])
        path = (previous / raw_path).resolve()
        if not path.is_relative_to((previous / 'raw').resolve()):
            raise ValueError('Recovery raw path escapes source run.')
        body = gzip.decompress(path.read_bytes())
        if crawler.digest(body) != old['raw_sha256']:
            raise ValueError('Recovery EFetch raw hash mismatch.')
        target = f"raw/efetch/{old['raw_sha256'][:2]}/{old['raw_sha256']}.gz"
        crawler.atomic_bytes(out / target, gzip.compress(body, mtime=0))
        batch = {'version': VERSION, 'samples': group,
                 'pmids': list(dict.fromkeys(pmid_from_url(s['url']) for s in group)),
                 'raw_path': target, 'raw_sha256': old['raw_sha256'], 'requests': old['requests'], 'anomalies': [],
                 'recovered_from': str(previous)}
        # Old compact traces may not retain timestamps; preserve the record's timestamps explicitly.
        batch['requests'] = [dict(t, started_at=old['started_at'], finished_at=old['finished_at']) for t in old['requests']]
        key = crawler.digest(json.dumps(group, sort_keys=True).encode())
        crawler.write_json(out / 'pubmed_batches' / f'{key}.json', batch)
        apply_batch(crawler, out, batch, {s['id']: s for s in samples}, on_record)


def crawl(crawler, out, samples, config, *, max_new=None, recovery_source=None, on_record=None, log_every=300):
    out = Path(out)
    config = validate_config(config)
    if max_new is not None and (type(max_new) is not int or max_new < 1):
        raise ValueError('max_new must be a positive integer or None.')
    selected = [s for s in samples if crawler.host(s['url']) == 'pubmed.ncbi.nlm.nih.gov']
    by_id = {s['id']: s for s in selected}
    if len(by_id) != len(selected): raise ValueError('Duplicate corpus IDs in EFetch sample.')
    if recovery_source:
        seed_recovery(crawler, out, selected, recovery_source, on_record)
    for path in sorted((out / 'pubmed_batches').glob('*.json')):
        apply_batch(crawler, out, crawler.load_json(path), by_id, on_record)
    pending = [s for s in selected if read_record(crawler, out, s) is None]
    completed_before = len(selected) - len(pending)
    print(json.dumps({'engine': 'efetch', 'event': 'resume', 'transport_version': TRANSPORT_VERSION,
        'selected': len(selected), 'completed': len(selected) - len(pending), 'pending': len(pending)}, ensure_ascii=False), flush=True)
    if max_new is not None:
        pending = pending[:max_new]
    client = EFetchClient(crawler, out, config)
    checkpoint = checkpoint_module().PeriodicCheckpoint(crawler, out, config['checkpoint'])
    completed, visited, errors = 0, set(), {}
    stop_reason = None

    def process_root(group, round_number):
        nonlocal completed
        queue = deque([group])
        deadline = time.monotonic() + config['fallback_budget']
        first_request = client.total_requests
        before = completed
        deferred = False
        while queue:
            node = [s for s in queue.popleft() if read_record(crawler, out, s) is None]
            if not node: continue
            visited.update(s['id'] for s in node)
            remaining_calls = config['max_split_requests'] - (client.total_requests - first_request)
            try:
                if time.monotonic() >= deadline or remaining_calls <= 0:
                    client.failed(node, [], error='Fallback request/time budget exhausted', retryable=True)
                batch = client.fetch(node, deadline=deadline, max_requests=remaining_calls)
            except BatchFailure as exc:
                for s in node: errors[s['id']] = exc.evidence
                print(json.dumps({'engine': 'efetch', 'event': 'batch_pending', 'round': round_number,
                    'url_count': len(node), 'retryable': exc.retryable, 'error': exc.evidence['error'],
                    'failure_path': exc.evidence['failure_path']}, ensure_ascii=False), flush=True)
                if exc.deferred:
                    deferred = True
                    break  # A server-wide cooldown also applies to the next root batch.
                pmids = list(dict.fromkeys(pmid_from_url(s['url']) for s in node))
                if (exc.split_allowed and len(pmids) > config['min_batch_size']
                        and time.monotonic() < deadline and client.total_requests - first_request < config['max_split_requests']):
                    left = set(pmids[:len(pmids)//2])
                    children = [[s for s in node if pmid_from_url(s['url']) in left],
                                [s for s in node if pmid_from_url(s['url']) not in left]]
                    queue.extend(children)
                    print(json.dumps({'engine': 'efetch', 'event': 'batch_split', 'parent_pmids': len(pmids),
                                      'child_pmids': [len({pmid_from_url(s['url']) for s in g}) for g in children]}), flush=True)
                continue
            key = crawler.digest(json.dumps(node, sort_keys=True).encode())
            crawler.write_json(out / 'pubmed_batches' / f'{key}.json', batch)
            apply_batch(crawler, out, batch, by_id, on_record)
            completed += len(node)
            for s in node: errors.pop(s['id'], None)
            checkpoint.maybe_save(new_completed=len(node))
        return completed - before, deferred

    try:
        groups = [pending[start:start + config['batch_size']] for start in range(0, len(pending), config['batch_size'])]
        for round_number in range(config['pending_retry_passes'] + 1):
            failed_roots = 0
            for group in groups:
                new, deferred = process_root(group, round_number)
                failed_roots = failed_roots + 1 if new == 0 else 0
                print(json.dumps({'engine': 'efetch', 'completed_this_invocation': completed,
                    'scheduled_this_invocation': len(pending), 'attempted_urls_this_invocation': len(visited),
                    'round': round_number, 'remaining_selected': len(selected) - completed_before - completed}), flush=True)
                checkpoint.maybe_save()
                if deferred or failed_roots >= config['max_consecutive_failed_batches']:
                    stop_reason = 'server_cooldown' if deferred else 'consecutive_failed_batches'
                    break
            if stop_reason: break
            retry = [s for s in pending if read_record(crawler, out, s) is None
                     and errors.get(s['id'], {}).get('retryable') and not errors[s['id']].get('deferred')]
            if not retry: break
            groups = [retry[start:start + config['batch_size']] for start in range(0, len(retry), config['batch_size'])]
    finally:
        client.close()
        write_reports(crawler, out, selected)
        checkpoint.maybe_save(force=True)
    if stop_reason:
        print(json.dumps({'engine': 'efetch', 'event': 'deferred', 'reason': stop_reason,
                          'complete': False}, ensure_ascii=False), flush=True)
    # MAX_NEW counts scheduled source URLs, including a failed attempt; retries do not consume it twice.
    return len(visited)


def write_reports(crawler, out, samples):
    out = Path(out)
    failures, anomalies = {}, []
    failure_items = [crawler.load_json(path) for path in (out / 'pubmed_batch_failures').glob('*.json')]
    for failure in sorted(failure_items, key=lambda value: value.get('at', '')):
        for sample in failure['samples']:
            failures[sample['id']] = failure
    for path in (out / 'pubmed_batches').glob('*.json'):
        batch = crawler.load_json(path)
        anomalies.extend(dict(a, batch_path=path.relative_to(out).as_posix()) for a in batch.get('anomalies', []))
    rows = []
    for sample in samples:
        record = read_record(crawler, out, sample)
        if record is None:
            failed = failures.get(sample['id'], {})
            last_request = (failed.get('requests') or [{}])[-1]
            record = dict(sample, pubmed_pmid=pmid_from_url(sample['url']), pubmed_api_status='pending',
                          error=failed.get('error'), batch_failure=bool(failed), quality_status='pending',
                          retryable=failed.get('retryable'), failure_path=failed.get('failure_path'),
                          http_status=last_request.get('http_status'), raw_path=last_request.get('raw_path'))
        rows.append({k: record.get(k) for k in ('id', 'url', 'pubmed_pmid', 'pubmed_api_status', 'quality_status',
                                               'quality_flags', 'title', 'text', 'http_status', 'raw_path', 'error', 'batch_failure', 'retryable', 'failure_path')})
    fields = list(rows[0]) if rows else ['id', 'url', 'pubmed_pmid', 'pubmed_api_status', 'quality_status', 'error']
    for name, items in [('pubmed_results', rows), ('pubmed_missing_pmids', [r for r in rows if r['pubmed_api_status'] == 'missing_pmid']),
                        ('pubmed_no_abstract', [r for r in rows if r['pubmed_api_status'] == 'no_abstract']),
                        ('pubmed_pending', [r for r in rows if r['pubmed_api_status'] == 'pending']),
                        ('pubmed_review', [r for r in rows if r['quality_status'] != 'accepted'])]:
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        writer.writerows(items)
        crawler.atomic_bytes(out / f'{name}.csv', buffer.getvalue().encode('utf-8-sig'))
    crawler.jsonl(out / 'pubmed_api_anomalies.jsonl', anomalies)
    from collections import Counter
    log = out / 'pubmed_requests.jsonl'
    requests_count = 0
    if log.exists():
        with log.open(encoding='utf-8') as stream:
            requests_count = sum(1 for line in stream if line.strip())
    crawler.write_json(out / 'pubmed_efetch_summary.json', {
        'selected': len(rows), 'completed': sum(r['pubmed_api_status'] != 'pending' for r in rows),
        'pending': sum(r['pubmed_api_status'] == 'pending' for r in rows),
        'complete': not any(r['pubmed_api_status'] == 'pending' for r in rows), 'transport_version': TRANSPORT_VERSION,
        'accepted': sum(r['quality_status'] == 'accepted' for r in rows),
        'statuses': dict(Counter(r['pubmed_api_status'] for r in rows)),
        'get_requests_attempted': requests_count, 'api_anomalies': len(anomalies)})
