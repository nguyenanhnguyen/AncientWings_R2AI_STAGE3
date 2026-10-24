"""Crawl an independent 120ask sample with the current gate; preserve access failures.

Prepare without network, then use --crawl on the same --out. A circuit breaker
stops after five consecutive HTTP access failures, or the gate's 429/challenge.
No browser, upload, synthetic labels, or production parser changes are involved.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from unittest.mock import patch

import ask120_gate as gate
from check_120ask import snapshots

ROOT = Path(__file__).resolve().parents[1]


class AccessStopped(BaseException):
    pass


class Prepared(BaseException):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--seed', type=int, default=2026102003)
    parser.add_argument('--limit', type=int, default=1000)
    parser.add_argument('--crawl', action='store_true')
    args = parser.parse_args()
    out = (args.out or ROOT/'runs'/datetime.now(timezone.utc).strftime('ask120_holdout_%Y%m%dT%H%M%S%fZ')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    support = out/'support'
    support.mkdir(exist_ok=True)
    config_path = out/'holdout_config.json'
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if config['source'] != str(args.source.resolve()) or config['seed'] != args.seed or config['limit'] != args.limit:
            raise ValueError('Holdout configuration changed; use a new run directory')
    else:
        history = sorted(p.resolve() for p in (ROOT/'runs').rglob('sample.jsonl') if not p.is_relative_to(out))
        downloads = Path('C:/Users/HP/Downloads')
        history.extend(sorted(downloads.glob('check_120ask_*.zip')))
        if not history:
            raise ValueError('Prior sample history is required for an independent holdout')
        config = dict(source=str(args.source.resolve()), seed=args.seed, limit=args.limit,
                      history_paths=[str(p) for p in history], stop_after_consecutive_access_errors=5,
                      created_at=gate.utc())
        gate.write_json(config_path, config)
    _, _, snapshot_hashes = snapshots(ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb', support)
    assert snapshot_hashes['ask120_snapshot.py'] == gate.sha(Path(gate.PARSER.__file__).read_bytes())
    for name in ('ask120.py', 'ask120_gate.py', 'check_120ask.py', 'check_120ask_holdout.py'):
        source = ROOT/'scripts'/name
        destination = support/name
        if destination.exists() and destination.read_bytes() != source.read_bytes():
            raise ValueError('Frozen source changed; use a new run directory: '+name)
        shutil.copy2(source, destination)
    gate.write_json(out/'support_hashes.json', {p.name:gate.sha(p.read_bytes()) for p in support.glob('*.py')})
    gate.write_json(ROOT/'tmp/120ask_holdout_location.json', {'run_dir':str(out)})
    print('RUN_DIR='+str(out), flush=True)

    import requests
    original = requests.sessions.Session.request
    events = []
    consecutive = 0
    def guarded_request(session, method, url, *positional, **kwargs):
        nonlocal consecutive
        if not args.crawl:
            raise Prepared('Sample prepared; network disabled')
        if consecutive >= 5:
            raise AccessStopped('Five consecutive HTTP access failures; no usable access established')
        event = {'at':gate.utc(), 'method':method, 'url':url}
        try:
            response = original(session, method, url, *positional, **kwargs)
            event.update(http_status=response.status_code, final_url=response.url)
            if response.status_code >= 400:
                consecutive += 1
            elif 200 <= response.status_code < 300:
                consecutive = 0
            return response
        except requests.RequestException as exc:
            consecutive += 1
            event.update(error=type(exc).__name__+': '+str(exc)[:500])
            raise
        finally:
            events.append(event)

    stopped = None
    summary = None
    try:
        with patch('requests.sessions.Session.request', new=guarded_request):
            gate.crawl_new(args.source, out, limit=args.limit, seed=args.seed,
                history_paths=config['history_paths'], support_dir=support,
                delay=2., attempts=1, timeout=(8.,20.), budget=40.,
                trust_env=False, respect_robots=False, stop_on_block=True)
    except Prepared:
        stopped = 'PREPARED_NO_NETWORK'
    except AccessStopped as exc:
        stopped = 'ACCESS_BLOCKED: '+str(exc)
    finally:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        gate.jsonl(out/f'network_events_{stamp}.jsonl', events)
        if args.crawl and (out/'manifest.json').exists():
            summary = gate.build_outputs(out)

    samples = gate.read_jsonl_bytes((out/'sample.jsonl').read_bytes())
    current = {gate.canonical_question(row['url']) for row in samples}
    previous = set()
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    for history in manifest['history_files']:
        path = Path(history['path'])
        if path.suffix.lower() == '.zip':
            reader = gate.RunInput(path)
            try:
                content = reader.read('sample.jsonl')
            finally:
                reader.close()
        else:
            content = path.read_bytes()
        assert gate.sha(content) == history['sha256']
        for row in gate.read_jsonl_bytes(content):
            url = row.get('source_url') or row.get('url')
            if url and gate.PARSER.is_question_url(url):
                previous.add(gate.canonical_question(url))
    assert len(samples) == len(current) == args.limit
    assert not current.intersection(previous)
    audit = dict(selected=len(samples), unique_canonical_questions=len(current),
        history_files=len(manifest['history_files']), history_unique_questions=len(previous),
        overlap_with_provided_history=len(current.intersection(previous)), seed=args.seed,
        source_sha256=manifest['source_sha256'], sample_sha256=manifest['sample_sha256'],
        scope='all available local sample.jsonl history plus downloaded 120ask check ZIPs',
        no_guarantee_for_unavailable_history=True)
    gate.write_json(out/'sample_independence_audit.json', audit)
    fetches = [json.loads(p.read_text(encoding='utf-8')) for p in (out/'fetch_records').glob('*.json')]
    status = dict(state=stopped or ('CRAWL_COMPLETE' if summary and summary['pending']==0 else 'CRAWL_STOPPED'),
        sample_independence=audit, attempted_urls=len(fetches),
        http_status=dict(Counter(str(row.get('http_status')) for row in fetches)),
        accessible_urls=sum(row.get('status')=='extracted' and 200<=row.get('http_status',0)<300 for row in fetches),
        request_events_this_invocation=len(events), finished_at=gate.utc(), summary=summary)
    gate.write_json(out/'holdout_status.json', status)
    print(json.dumps(status, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
