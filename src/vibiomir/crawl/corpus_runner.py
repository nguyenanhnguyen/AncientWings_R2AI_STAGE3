"""Run the shared domain probe engines and publish ID-preserving corpus checkpoints."""
import argparse
from collections import Counter, defaultdict
import csv
import importlib.util
import io
import json
import math
from pathlib import Path
import sys
import threading

VERSION = 'corpus-runner-v1'
DEFAULTS = {
    'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'delay': 1., 'attempts': 3, 'timeout': [20., 45.], 'budget': 180.,
    'respect_robots': False,
    'robots_options': {'robots_attempts': 3, 'robots_connect_timeout': 15.,
                       'robots_read_timeout': 30., 'robots_retry_budget': 90., 'robots_failure_ttl': 30.},
    'browser_mode': 'failed_only', 'browser_user_agent': None, 'chrome_binary': None,
    'browser_load_timeout': 45., 'browser_wait_seconds': 15., 'browser_attempts': 2,
}


def read_samples(crawler, out):
    manifest = crawler.load_json(out / 'manifest.json')
    if crawler.file_hash(out / 'sample.jsonl') != manifest['sample_sha256']:
        raise ValueError('Sample hash changed.')
    with (out / 'sample.jsonl').open(encoding='utf-8') as stream:
        samples = [json.loads(line) for line in stream if line.strip()]
    if len({r['id'] for r in samples}) != len(samples):
        raise ValueError('Duplicate sample IDs.')
    return samples


def read_record(crawler, out, folder, sample):
    path = out / folder / f"{sample['id']}.json"
    if not path.exists():
        return None
    record = crawler.load_json(path)
    if (record.get('id'), record.get('url')) != (sample['id'], sample['url']):
        raise ValueError(f'Checkpoint ID/URL mismatch: {path}')
    return record


def publish_record(crawler, probe, out, sample):
    request = read_record(crawler, out, 'requests_records', sample)
    if request is None:
        return None
    browser = read_record(crawler, out, 'browser_records', sample)
    access, engine, chosen = probe.access_outcome(request, browser)
    record = dict(chosen)
    record.update(access_status=access, engine=chosen.get('engine', engine),
                  requests_status=request.get('status'), requests_http_status=request.get('http_status'),
                  requests_error_kind=request.get('error_kind'), requests_error=request.get('error'),
                  requests_record_path=f"requests_records/{sample['id']}.json")
    if browser:
        record.update(browser_status=browser.get('status'), browser_http_status=browser.get('http_status'),
                      browser_error=browser.get('error'), browser_record_path=f"browser_records/{sample['id']}.json")
    if engine == 'selenium':
        record.update(status='extracted', content_type='text/html; charset=utf-8',
                      requests=request.get('requests', []), robots=request.get('robots'),
                      started_at=request.get('started_at'),
                      elapsed_seconds=round(request.get('elapsed_seconds', 0) + browser.get('elapsed_seconds', 0), 3))
    crawler.write_json(out / 'records' / f"{sample['id']}.json", record)
    return record


def write_access_report(crawler, probe, out, samples):
    populations = crawler.load_json(out / 'source_profile.json')['host_counts']
    setup = crawler.load_json(out / 'browser_setup_error.json') if (out / 'browser_setup_error.json').exists() else {}
    rows, errors = [], defaultdict(list)
    for sample in samples:
        record = read_record(crawler, out, 'records', sample)
        if not record:
            continue
        row = {key: record.get(key) for key in (
            'id', 'url', 'domain', 'access_status', 'engine', 'status', 'http_status',
            'quality_status', 'quality_flags', 'error', 'error_kind', 'requests_status',
            'requests_http_status', 'requests_error_kind', 'requests_error',
            'browser_status', 'browser_http_status', 'browser_error')}
        if not row['browser_status'] and row['access_status'] != 'VAO_DUOC' and setup:
            row.update(browser_status='browser_setup_error', browser_error=setup['error'])
        row['dataset_url_count'] = populations.get(sample['domain'], 0)
        rows.append(row)
        if row['access_status'] != 'VAO_DUOC':
            errors[sample['domain']].append(row)
    rows.sort(key=lambda r: (-r['dataset_url_count'], r['domain'], r['id']))
    priorities = [{'domain': domain, 'dataset_url_count': populations.get(domain, 0),
                   'failed_urls_in_run': len(group),
                   'errors': dict(Counter(r.get('error_kind') or r['status'] for r in group))}
                  for domain, group in errors.items()]
    priorities.sort(key=lambda r: (-r['dataset_url_count'], r['domain']))
    summary = {'selected': len(samples), 'completed': len(rows), 'pending': len(samples) - len(rows),
               'accessible': sum(r['access_status'] == 'VAO_DUOC' for r in rows),
               'browser_recovered': sum(r['engine'] == 'selenium' and r['access_status'] == 'VAO_DUOC' for r in rows),
               'failed': sum(len(group) for group in errors.values()), 'failed_domains': len(priorities)}
    crawler.write_json(out / 'access_summary.json', summary)
    crawler.write_json(out / 'uu_tien_fix_domain.json', priorities)
    fields = ['id', 'url', 'domain', 'dataset_url_count', 'access_status', 'engine', 'status', 'http_status',
              'quality_status', 'quality_flags', 'error_kind', 'error', 'requests_status', 'requests_http_status',
              'requests_error_kind', 'requests_error', 'browser_status', 'browser_http_status', 'browser_error']
    for name, data in [('requests_vs_selenium.csv', rows),
                       ('khong_vao_duoc.csv', [r for r in rows if r['access_status'] != 'VAO_DUOC'])]:
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(data)
        crawler.atomic_bytes(out / name, stream.getvalue().encode('utf-8-sig'))
    lines = ['# Các website còn lỗi truy cập', '',
             'Ưu tiên theo tổng URL của hostname trong dataset, giảm dần.', '',
             f"Đã thử {len(rows)}/{len(samples)} URL; vào được {summary['accessible']}; lỗi {summary['failed']}.",
             'Truy cập được và chất lượng accepted là hai kết quả riêng; xem QUALITY_REPORT.md.', '',
             '| Domain | Tổng URL dataset | URL lỗi trong run | Lỗi Requests |',
             '| --- | ---: | ---: | --- |']
    for item in priorities:
        lines.append(f"| {item['domain']} | {item['dataset_url_count']} | {item['failed_urls_in_run']} | {json.dumps(item['errors'], ensure_ascii=False)} |")
    lines += ['', 'Chi tiết HTTP, lỗi mạng và Selenium cho từng URL: `khong_vao_duoc.csv`.', '']
    crawler.atomic_bytes(out / 'WEB_ERRORS.md', '\n'.join(lines).encode('utf-8'))
    return summary


def run(crawler, probe, out, config, *, workers=4, max_new=None, recovery_source=None):
    out = Path(out)
    config = {**DEFAULTS, **config}
    if config['browser_mode'] not in ('off', 'failed_only', 'first_each_domain_and_failures', 'all'):
        raise ValueError('Unknown browser_mode.')
    if type(config['respect_robots']) is not bool:
        raise ValueError('respect_robots must be bool.')
    for key in ('browser_load_timeout', 'browser_wait_seconds'):
        if not math.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f'{key} must be finite and positive.')
    if type(config['browser_attempts']) is not int or config['browser_attempts'] < 1:
        raise ValueError('browser_attempts must be a positive integer.')
    samples = read_samples(crawler, out)
    identity = {'version': VERSION, 'settings': config,
                'runner_sha256': crawler.file_hash(__file__),
                'crawler_sha256': crawler.file_hash(crawler.__file__),
                'probe_sha256': crawler.file_hash(probe.__file__)}
    with crawler.run_lock(out):
        config_path = out / 'corpus_config.json'
        if config_path.exists():
            if crawler.load_json(config_path) != identity:
                raise ValueError('Corpus code/config changed; use a new RUN_TAG and RECOVERY_RUN_PATH.')
        elif (out / 'crawl_config.json').exists() or list((out / 'records').glob('*.json')):
            raise ValueError('Legacy run: use a new RUN_TAG and RECOVERY_RUN_PATH to upgrade.')
        crawler.write_json(config_path, identity)
        crawler.UA = config['user_agent']
        crawler.ROBOT_AGENT = config['user_agent'].split('/', 1)[0]
        if recovery_source:
            probe.seed_successful_requests(crawler, out, samples, recovery_source, record_dir='requests_records')
        elif (out / 'recovery_manifest.json').exists():
            # Resume a recovered run without requiring its old source to remain mounted.
            pass
        # Repair canonical output after an interruption between the engine checkpoint and publication.
        for sample in samples:
            publish_record(crawler, probe, out, sample)
        progress_lock = threading.Lock()
        completed = 0
        scheduled = sum(not (out / 'requests_records' / f"{s['id']}.json").exists() for s in samples)
        if max_new is not None:
            scheduled = min(scheduled, max_new)

        def publish_request(record):
            nonlocal completed
            publish_record(crawler, probe, out, record)
            with progress_lock:
                completed += 1
                if completed % 25 == 0 or completed == scheduled:
                    print(json.dumps({'completed_this_invocation': completed, 'scheduled': scheduled}), flush=True)

        try:
            records = probe.crawl_requests(
                crawler, out, samples, workers=workers, delay=config['delay'], attempts=config['attempts'],
                user_agent=config['user_agent'], timeout=config['timeout'], budget=config['budget'],
                max_new=max_new, respect_robots=config['respect_robots'], robots_options=config['robots_options'],
                record_dir='requests_records', on_record=publish_request, lock_run=False)
            browser_samples = probe.select_browser_samples(samples, records, config['browser_mode'])
            if config['respect_robots']:
                allowed = {r['id'] for r in records if not r.get('status', '').startswith('robots_')
                           and r.get('status') not in ('invalid_url', 'unsafe_address')}
                browser_samples = [s for s in browser_samples if s['id'] in allowed]
            if browser_samples:
                probe.crawl_browser(
                    crawler, out, browser_samples, user_agent=config['browser_user_agent'],
                    chrome_binary=config['chrome_binary'], load_timeout=config['browser_load_timeout'],
                    wait_seconds=config['browser_wait_seconds'], attempts=config['browser_attempts'],
                    delay=config['delay'], on_record=lambda r: publish_record(crawler, probe, out, r))
        finally:
            for sample in samples:
                publish_record(crawler, probe, out, sample)
            crawler.report(argparse.Namespace(out=out))
            summary = write_access_report(crawler, probe, out, samples)
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return summary


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['crawl'])
    parser.add_argument('--out', required=True)
    parser.add_argument('--config', required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--max-new', type=int)
    parser.add_argument('--recovery-source')
    args = parser.parse_args()
    root = Path(__file__).parent
    crawler = load_module('corpus_core', root / 'crawler_snapshot.py')
    probe = load_module('corpus_probe', root / 'priority_probe_snapshot.py')
    run(crawler, probe, args.out, crawler.load_json(Path(args.config)), workers=args.workers,
        max_new=args.max_new, recovery_source=args.recovery_source)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
