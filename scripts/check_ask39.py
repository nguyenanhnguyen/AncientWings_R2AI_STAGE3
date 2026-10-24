"""Probe ask.39.net using production snapshots; preserve source IDs and raw evidence."""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics
import sys
from urllib.parse import urlsplit
import zlib

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
HOST = 'ask.39.net'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'


def select(source, limit=50, seed=20261021, exclude=(), path_strata=False):
    groups, seen = defaultdict(list), set()
    excluded_urls = {r['url'] for r in exclude}
    excluded_ids = {r['id'] for r in exclude}
    excluded_count = 0
    source_rows = domain_rows = 0
    for batch in pq.ParquetFile(source).iter_batches(columns=['id', 'url']):
        source_rows += batch.num_rows
        for row in batch.to_pylist():
            parsed = urlsplit(row['url'] or '')
            if parsed.hostname != HOST or parsed.scheme not in ('http', 'https'):
                continue
            domain_rows += 1
            if row['url'] in seen:
                continue
            seen.add(row['url'])
            if row['url'] in excluded_urls or row['id'] in excluded_ids:
                excluded_count += 1
                continue
            key = parsed.scheme + ':' + (parsed.path.strip('/').split('/')[0] or 'home')
            if path_strata:
                stem = Path(parsed.path).stem
                key += ':' + ('numeric' if stem.isdigit() else 'underscore' if stem.startswith('_') else 'other')
            groups[key].append(dict(row, domain=HOST, sampling_stratum=key))
    counts = {key: len(rows) for key, rows in sorted(groups.items())}
    for key, rows in groups.items():
        rows.sort(key=lambda r: (r['id'], r['url']))
        random.Random(f'{seed}:{key}').shuffle(rows)
    samples = []
    while len(samples) < limit:
        progressed = False
        for key in sorted(groups):
            if groups[key] and len(samples) < limit:
                samples.append(groups[key].pop())
                progressed = True
        if not progressed:
            break
    if not samples or len({r['id'] for r in samples}) != len(samples):
        raise ValueError('No matching URLs or duplicate source IDs in selection')
    return samples, dict(source_rows=source_rows, domain_rows=domain_rows,
        unique_domain_urls=len(seen), source_strata=counts,
        selected_strata=dict(Counter(r['sampling_stratum'] for r in samples)),
        seed=seed, requested=limit, selected=len(samples),
        excluded_urls=excluded_count,
        method='Equal allocation across scheme/path strata; fixed seed; not population weighted.')


def snapshots(notebook, out):
    dns_path = Path(__file__).with_name('ask39_dns.py')
    if dns_path.is_file():
        dns_spec = importlib.util.spec_from_file_location('_ask39_dns_guard', dns_path)
        dns = importlib.util.module_from_spec(dns_spec)
        dns_spec.loader.exec_module(dns)
        dns.install()
    values = {}
    for cell in json.loads(Path(notebook).read_text(encoding='utf-8'))['cells']:
        if cell.get('cell_type', 'code') != 'code':
            continue
        for node in ast.parse(''.join(cell['source'])).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('EMBEDDED_FILES', 'EMBEDDED_SHA256'):
                    values[node.targets[0].id] = ast.literal_eval(node.value)
    hashes = {}
    if dns_path.is_file():
        dns_body = dns_path.read_bytes()
        (out/'ask39_dns.py').write_bytes(dns_body)
        hashes['ask39_dns.py'] = hashlib.sha256(dns_body).hexdigest()
    for name, payload in values['EMBEDDED_FILES'].items():
        if Path(name).name != name:
            raise ValueError('Invalid snapshot name')
        body = zlib.decompress(base64.b85decode(payload))
        digest = hashlib.sha256(body).hexdigest()
        if digest != values['EMBEDDED_SHA256'][name]:
            raise ValueError('Snapshot hash mismatch: ' + name)
        (out / name).write_bytes(body)
        hashes[name] = digest
    modules = []
    for name in ('crawler_snapshot', 'priority_probe_snapshot'):
        module_name = '_ask39_' + name + '_' + hashes[name + '.py'][:12]
        spec = importlib.util.spec_from_file_location(module_name, out / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        modules.append(module)
    return *modules, hashes


def report(crawler, probe, out, samples, selection, records, browsers, complete):
    selected = [probe.access_outcome(records[r['id']], browsers.get(r['id']))
                for r in samples if r['id'] in records]
    usable = [r for state, _, r in selected if state == 'VAO_DUOC']
    candidate = any(r.get('extractor') in ('ask39_qa_dom_v1','ask39_qa_dom_v2') for r in usable)
    gate_spec = importlib.util.spec_from_file_location('_ask39_export_gate', Path(__file__).with_name('ask39_gate.py'))
    gate = importlib.util.module_from_spec(gate_spec)
    gate_spec.loader.exec_module(gate)
    sources = {}
    for state, engine, r in selected:
        row = next(s for s in samples if s['id'] == r['id'])
        events = [e for e in r.get('requests',[]) if e.get('raw_sha256')]
        raw_hash = events[-1]['raw_sha256'] if events and engine == 'requests' else r.get('raw_sha256')
        sources[r['id']] = dict(id=row['id'], url=row['url'], raw_sha256=raw_hash)
    export = gate.export_candidates([r for _,_,r in selected], out, Path(out)/'candidate.parquet', sources)
    decisions = {d['id']:d for d in (json.loads(line) for line in (Path(out)/'candidate.decisions.jsonl').read_text(encoding='utf-8').splitlines())}
    for _, _, r in selected:
        decision = decisions[r['id']]
        r.update(quality_status=decision['quality_status'], quality_flags=decision['quality_flags'],
                 extraction_status=decision['extraction_status'], candidate_eligible=decision['candidate_eligible'],
                 corpus_eligible=False, ask39_gate=decision)
    summary = dict(complete=complete, selection=selection, attempted_urls=len(records),
        pending_urls=len(samples)-len(records), accessible_urls=len(usable),
        requests_http_status=dict(Counter(str(r.get('http_status')) for r in records.values())),
        requests_status=dict(Counter(r['status'] for r in records.values())),
        browser_attempted=len(browsers),
        browser_status=dict(Counter(r['status'] for r in browsers.values())),
        quality_status=dict(Counter(r.get('quality_status') for r in usable)),
        quality_flags=dict(Counter(f for r in usable for f in r.get('quality_flags', []))),
        extractors=dict(Counter(r.get('extractor', '') for r in usable)),
        main_answers=sum(r.get('main_answer_count', 0) for r in usable),
        followup_messages=sum(r.get('followup_count', 0) for r in usable),
        orphan_followups=sum(r.get('orphan_followup_count', 0) for r in usable),
        unknown_followup_roles=sum(r.get('unknown_followup_roles', 0) for r in usable),
        candidate_export=export,
        median_chars=statistics.median(r.get('char_count', 0) for r in usable) if usable else None,
        duplicate_text_records=sum(n-1 for n in Counter(r.get('text_sha256') for r in usable
                                                      if r.get('text_sha256')).values()),
        assessment=('F4: raw-backed QC and local candidate export; production release pending F5/F6.'
                    if candidate else 'Generic extraction QC only; inspect question/answer boundaries and boilerplate before corpus admission.')
                   if usable else 'No usable pages; extraction quality cannot be assessed on this network.')
    crawler.write_json(out / 'summary.json', summary)
    crawler.jsonl(out / 'results.jsonl', [dict(r, access=state, selected_engine=engine)
                                       for state, engine, r in selected])
    lines = ['# ask.39.net check', '', '```json', json.dumps(summary, ensure_ascii=False, indent=2),
             '```', '', '| ID | Engine | HTTP | Access | QC | Chars | Flags/error |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for state, engine, r in selected:
        detail = (', '.join(r.get('quality_flags', [])) or r.get('error', '')).replace('|', '/').replace('\n', ' ')
        lines.append(f"| [{r['id']}]({r['url']}) | {engine} | {r.get('http_status')} | {state} | {r.get('quality_status', '')} | {r.get('char_count', 0)} | {detail[:240]} |")
    for r in usable:
        lines.extend(['', f"## {r['id']}: {r.get('title', '')}", '', r['url'], '', r.get('text', '')])
    (out / 'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return summary


def install_candidate(crawler, out):
    """Patch only this check's in-memory snapshot; do not rebuild production."""
    body = Path(__file__).with_name('ask39.py').read_bytes()
    path = Path(out)/'ask39_snapshot.py'
    path.write_bytes(body)
    spec = importlib.util.spec_from_file_location('_ask39_f1_' + hashlib.sha256(body).hexdigest()[:12], path)
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    original_extract, original_quality = crawler.extract, crawler.quality
    def extract(body, content_type, url):
        if urlsplit(url).hostname == HOST:
            return candidate.extract(body, url, content_type)
        return original_extract(body, content_type, url)
    def quality(doc):
        if doc.get('extractor') == candidate.EXTRACTOR:
            return {key: doc[key] for key in ('quality_status', 'quality_flags', 'char_count', 'text_sha256')}
        return original_quality(doc)
    crawler.extract, crawler.quality = extract, quality
    return hashlib.sha256(body).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--notebook', type=Path, default=ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20261021)
    parser.add_argument('--delay', type=float, default=2.)
    parser.add_argument('--attempts', type=int, default=2)
    parser.add_argument('--connect-timeout', type=float, default=8.)
    parser.add_argument('--read-timeout', type=float, default=20.)
    parser.add_argument('--budget', type=float, default=60.)
    parser.add_argument('--browser-limit', type=int, default=3)
    parser.add_argument('--respect-robots', action='store_true')
    parser.add_argument('--trust-env', action='store_true')
    parser.add_argument('--parser', choices=('candidate', 'baseline'), default='candidate')
    parser.add_argument('--exclude-sample', type=Path)
    parser.add_argument('--path-strata', action='store_true')
    args = parser.parse_args(argv)
    if args.limit < 1 or args.attempts < 1 or args.browser_limit < 0:
        parser.error('Invalid limit/attempts/browser-limit')
    for key in ('delay', 'connect_timeout', 'read_timeout', 'budget'):
        value = getattr(args, key)
        if not math.isfinite(value) or (value < 0 if key == 'delay' else value <= 0):
            parser.error('Invalid ' + key)
    out = (args.out or ROOT/'runs'/datetime.now(timezone.utc).strftime('check_ask39_%Y%m%dT%H%M%S%fZ')).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Output must be empty to preserve evidence')
    excluded = [json.loads(line) for line in args.exclude_sample.read_text(encoding='utf-8').splitlines()] if args.exclude_sample else []
    samples, selection = select(args.source, args.limit, args.seed, excluded, args.path_strata)
    if len(samples) != args.limit: parser.error('Insufficient eligible URLs for requested sample size')
    out.mkdir(parents=True, exist_ok=True)
    crawler, probe, hashes = snapshots(args.notebook, out)
    if args.parser == 'candidate':
        hashes['ask39_snapshot.py'] = install_candidate(crawler, out)
    crawler.TRUST_ENV = args.trust_env
    crawler.jsonl(out/'sample.jsonl', samples)
    crawler.write_json(out/'manifest.json', dict(created_at=crawler.utc(), source=str(args.source.resolve()),
        source_sha256=crawler.file_hash(args.source), snapshot_sha256=hashes, selection=selection,
        config={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}))
    print(json.dumps(dict(out=str(out), selection=selection)), flush=True)
    fetcher = crawler.Fetcher(out, delay=args.delay, attempts=args.attempts)
    records, browsers, driver, complete = {}, {}, None, False
    try:
        for i, row in enumerate(samples, 1):
            record = probe.request_record(crawler, fetcher, row, out, UA,
                (args.connect_timeout, args.read_timeout), args.budget, respect_robots=args.respect_robots)
            records[row['id']] = record
            print(json.dumps(dict(done=i, id=row['id'], http=record.get('http_status'),
                status=record['status'], qc=record.get('quality_status'), chars=record.get('char_count', 0))), flush=True)
            if record.get('http_status') == 429 or record.get('challenge_detected'):
                crawler.write_json(out/'deferred.json',dict(reason='rate_limit_or_challenge',id=row['id']))
                break
        candidates = [r for r in samples if r['id'] in records and probe.needs_browser(records[r['id']])
                      and (records[r['id']].get('status') != 'extracted' or not records[r['id']].get('text'))][:args.browser_limit]
        if candidates:
            try:
                driver = probe.create_browser(crawler, out, load_timeout=30.)
            except Exception as exc:
                crawler.write_json(out/'browser_setup_error.json', dict(error=f'{type(exc).__name__}: {exc}'))
            if driver:
                for row in candidates:
                    record = probe.browser_attempt(crawler, driver, row, out, load_timeout=30., wait_seconds=5., attempt=1)
                    browsers[row['id']] = record
                    crawler.write_json(out/'browser_records'/f"{row['id']}.json", record)
        complete = len(records) == len(samples)
    finally:
        try:
            if driver:
                driver.quit()
        finally:
            fetcher.session().close()
            summary = report(crawler, probe, out, samples, selection, records, browsers, complete)
            print(json.dumps(dict(out=str(out), summary=summary)), flush=True)
    return summary


if __name__ == '__main__':
    main()
