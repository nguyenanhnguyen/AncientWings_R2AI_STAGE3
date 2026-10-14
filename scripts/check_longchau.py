"""Stratified Long Chau smoke run using the exact main notebook snapshots; no HF upload."""
import argparse
import ast
import base64
from collections import Counter, defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
import uuid
import zlib

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_URLS = {
    'https://nhathuoclongchau.com.vn/bai-viet/dyslexia-la-gi-trieu-chung-va-nguyen-nhan-gay-ra-tinh-trang-nay.html',
    'https://nhathuoclongchau.com.vn/bai-viet/cach-so-cuu-sot-xuat-huyet-hieu-qua-an-toan-58740.html',
    'https://nhathuoclongchau.com.vn/bai-viet/thieu-mau-cap-la-gi-nguyen-nhan-nao-gay-ra-thieu-mau-cap.html',
}


def stratum(url):
    path = urlsplit(url).path
    prefix = path.strip('/').split('/')[0]
    return prefix + (':numeric_suffix' if re.search(r'-\d+\.html$', path) else ':plain_html' if path.endswith('.html') else ':other')


def select(source, limit=50, seed=20261014, id_from=None, id_to=None):
    if type(limit) is not int or limit < 1: raise ValueError('limit must be a positive integer.')
    if any(v is not None and (type(v) is not int or v < 0) for v in (id_from, id_to)):
        raise ValueError('ID bounds must be nonnegative integers or None.')
    if id_from is not None and id_to is not None and id_to < id_from:
        raise ValueError('id_to must be at least id_from.')
    all_rows = pq.read_table(source, columns=['id', 'url']).to_pylist()
    groups = defaultdict(list)
    source_strata = Counter()
    for row in all_rows:
        if urlsplit(row['url']).hostname not in ('nhathuoclongchau.com.vn','www.nhathuoclongchau.com.vn'): continue
        source_strata[stratum(row['url'])] += 1
        if id_from is not None and row['id'] < id_from: continue
        if id_to is not None and row['id'] > id_to: continue
        if row['url'] in FIXTURE_URLS: continue
        groups[stratum(row['url'])].append(row)
    pools = {}
    for key, rows in sorted(groups.items()):
        unique = {r['url']: r for r in sorted(rows, key=lambda r:r['id'], reverse=True)}
        pools[key] = sorted(unique.values(), key=lambda r:r['id'])
        random.Random(f'{seed}:{key}').shuffle(pools[key])
    samples = []
    while len(samples) < limit:
        progressed = False
        for key in sorted(pools):
            if pools[key] and len(samples) < limit:
                row = pools[key].pop()
                samples.append(dict(row, domain=(urlsplit(row['url']).hostname or '').lower(), sampling_stratum=key))
                progressed = True
        if not progressed: break
    samples.sort(key=lambda r:r['id'])
    if not samples or len({r['id'] for r in samples}) != len(samples):
        raise ValueError('No valid Long Chau URLs or duplicate source IDs.')
    populations = Counter((urlsplit(r['url']).hostname or '').lower() for r in all_rows)
    return samples, {'source_rows': len(all_rows), 'source_host_counts': dict(populations),
                     'longchau_source_strata': dict(source_strata),
                     'longchau_strata': {k: len(v) for k,v in groups.items()},
                     'selected_strata': dict(Counter(r['sampling_stratum'] for r in samples)),
                     'seed': seed, 'requested_urls': limit, 'actual_urls': len(samples),
                     'id_from_inclusive': id_from, 'id_to_inclusive': id_to,
                     'date_note': 'Numeric URL suffix is a URL shape, not proof of publication age. Dates are read from verified article metadata.'}


def unpack(notebook, out):
    nb = json.loads(Path(notebook).read_text(encoding='utf-8'))
    values = {}
    for node in ast.parse(''.join(nb['cells'][6]['source'])).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try: values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError): pass
    for name, data in values['EMBEDDED_FILES'].items():
        payload = zlib.decompress(base64.b85decode(data))
        if hashlib.sha256(payload).hexdigest() != values['EMBEDDED_SHA256'][name]:
            raise ValueError('Notebook snapshot hash mismatch: ' + name)
        target = out / name
        if target.exists() and target.read_bytes() != payload:
            raise ValueError('Resume code changed; use new output and --recovery-source.')
        target.write_bytes(payload)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run(source, notebook, out, *, limit=50, seed=20261014, id_from=None, id_to=None, max_new=None,
        delay=1.75, attempts=3, timeout=(10.,45.), budget=180., respect_robots=False, recovery_source=None):
    source, out = Path(source).resolve(), Path(out).resolve()
    samples, selection = select(source, limit, seed, id_from, id_to)
    out.mkdir(parents=True, exist_ok=True)
    unpack(notebook, out)
    crawler = load('longchau_smoke_core', out / 'crawler_snapshot.py')
    probe = load('longchau_smoke_probe', out / 'priority_probe_snapshot.py')
    runner = load('longchau_smoke_runner', out / 'corpus_runner_snapshot.py')
    selected_counts = Counter(r['domain'] for r in samples)
    sample_bytes = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in samples).encode()
    source_sha = crawler.file_hash(source)
    manifest_path = out / 'manifest.json'
    if manifest_path.exists():
        manifest = crawler.load_json(manifest_path)
        if source_sha != manifest['source_sha256'] or crawler.digest(sample_bytes) != manifest['sample_sha256']:
            raise ValueError('Resume source/selection changed.')
        if crawler.load_json(out / 'longchau_selection.json') != selection:
            raise ValueError('Resume sampling configuration changed; use a new run directory.')
    else:
        crawler.atomic_bytes(out / 'sample.jsonl', sample_bytes)
        crawler.write_json(manifest_path, {'source': str(source), 'source_sha256': source_sha,
            'selected': len(samples), 'source_rows': selection['source_rows'], 'sampling': 'longchau_stratified_fixed_seed',
            'sample_sha256': crawler.digest(sample_bytes), 'seed': seed, 'id_start_inclusive': id_from,
            'id_stop_exclusive': None if id_to is None else id_to + 1})
        crawler.write_json(out / 'source_profile.json', {'rows': selection['source_rows'],
            'host_counts': selection['source_host_counts'],
            'sample_host_counts': {h:selected_counts[h] for h in selection['source_host_counts']}})
        crawler.write_json(out / 'longchau_selection.json', selection)
    def execute(script, *args):
        subprocess.run([sys.executable, '-u', str(script), *map(str,args)], check=True)
    config = {'browser_mode':'off', 'respect_robots':respect_robots,
              'longchau':{'delay':delay, 'attempts':attempts, 'timeout':list(timeout), 'budget':budget}}
    try:
        runner.run(crawler, probe, out, config, workers=1, max_new=max_new,
                   recovery_source=recovery_source, log_every=5)
        counts = crawler.load_json(out / 'quality_report.json')
        if counts['pending'] == 0:
            execute(out / 'audit_snapshot.py', '--out', out, '--source', source)
            if counts['accepted']: execute(out / 'export_snapshot.py', '--out', out)
    finally:
        execute(out / 'diagnostics_snapshot.py', '--out', out, '--archive', str(out) + '_diagnostics.zip')
        shutil.make_archive(str(out), 'zip', root_dir=out.parent, base_dir=out.name)
    print(json.dumps({'output':str(out), 'selection':selection['selected_strata'],
                      'summary':crawler.load_json(out/'longchau_summary.json'), 'full_zip':str(out)+'.zip'}, ensure_ascii=False), flush=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--notebook', type=Path, default=ROOT/'notebooks/crawl_corpus_kaggle_hf_upload.ipynb')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20261014)
    parser.add_argument('--id-from', type=int)
    parser.add_argument('--id-to', type=int)
    parser.add_argument('--max-new', type=int)
    parser.add_argument('--delay', type=float, default=1.75)
    parser.add_argument('--attempts', type=int, default=3)
    parser.add_argument('--connect-timeout', type=float, default=10.)
    parser.add_argument('--read-timeout', type=float, default=45.)
    parser.add_argument('--budget', type=float, default=180.)
    parser.add_argument('--respect-robots', action='store_true')
    parser.add_argument('--recovery-source', type=Path)
    args = parser.parse_args()
    if args.limit < 1: parser.error('--limit must be positive')
    out = args.out or ROOT/'runs'/('longchau_50_'+uuid.uuid4().hex[:8])
    run(args.source,args.notebook,out,limit=args.limit,seed=args.seed,id_from=args.id_from,id_to=args.id_to,
        max_new=args.max_new,delay=args.delay,attempts=args.attempts,timeout=(args.connect_timeout,args.read_timeout),
        budget=args.budget,respect_robots=args.respect_robots,recovery_source=args.recovery_source)


if __name__ == '__main__':
    main()
