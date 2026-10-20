"""Sampling, durable resume and artifact export for the standalone cnkang notebook."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import random
import shutil
from urllib.parse import urlsplit

import pyarrow as pa
import pyarrow.parquet as pq


def load_transport():
    path = Path(__file__).with_name('cnkang_transport_snapshot.py')
    if not path.exists(): path = Path(__file__).with_name('cnkang_transport.py')
    spec = importlib.util.spec_from_file_location('_cnkang_transport_check_' + str(path), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transport_module = load_transport()
parser = transport_module.PARSER
write_json = transport_module.write_json


def canonical(url):
    p = urlsplit(url)
    host = (p.hostname or '').lower().rstrip('.')
    if host == 'www.cnkang.com': host = 'cnkang.com'
    port = ':' + str(p.port) if p.port and p.port not in (80, 443) else ''
    return host + port + p.path + ('?' + p.query if p.query else '')


def read_jsonl(path):
    rows = []
    with Path(path).open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip(): continue
            try: rows.append(json.loads(line))
            except ValueError as exc: raise ValueError(f'Invalid JSONL: {path}:{number}: {exc}') from exc
    return rows


def jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    temporary.replace(path)


def find_source(config):
    if config.get('parquet_path'):
        path = Path(config['parquet_path'])
        if not path.is_file(): raise FileNotFoundError('PARQUET_PATH does not exist: ' + str(path))
        return path
    expected = Path('/kaggle/input/datasets/lighth/r2ai-stage3/links_corpus_vi_en_zh.parquet')
    if expected.is_file(): return expected
    found = sorted(Path('/kaggle/input').rglob('links_corpus_vi_en_zh.parquet'))
    if len(found) != 1:
        raise ValueError(f'Found {len(found)} matching Parquet files; set PARQUET_PATH explicitly: {found}')
    return found[0]


def read_population(path):
    source = pq.ParquetFile(path)
    if not {'id', 'url'} <= set(source.schema_arrow.names):
        raise ValueError('Input requires columns id (int64), url (string)')
    if source.schema_arrow.field('id').type != pa.int64() or not pa.types.is_string(source.schema_arrow.field('url').type):
        raise ValueError('Unexpected schema; expected id=int64 and url=string')
    population, counts = {}, Counter()
    for batch in source.iter_batches(columns=['id', 'url']):
        for row in batch.to_pylist():
            counts['source_rows'] += 1
            url = row['url']
            try:
                if not isinstance(url, str) or not parser.is_host(url): continue
                counts['domain_rows'] += 1
                parts = urlsplit(url)
                if not parts.path.lower().endswith('.html'):
                    counts['excluded_not_detail_html'] += 1
                    continue
                if parts.scheme not in ('http', 'https') or parts.username or parts.password:
                    counts['excluded_invalid_url'] += 1
                    continue
                key = canonical(url)
            except ValueError:
                counts['excluded_invalid_url'] += 1
                continue
            branch = parts.path.strip('/').split('/')[0]
            if key not in population:
                population[key] = {'id':row['id'], 'ids':[], 'source_url':url, 'url':url,
                                   'source_urls':[], 'canonical_url':key, 'branch':branch}
            if row['id'] not in population[key]['ids']: population[key]['ids'].append(row['id'])
            if url not in population[key]['source_urls']: population[key]['source_urls'].append(url)
    counts['unique_canonical_detail_urls'] = len(population)
    return population, dict(counts)


HISTORY_NAMES = ('review.jsonl', 'samples.jsonl', 'sample_manifest.jsonl')


def read_history(paths, bundled_path=None):
    files, urls, reports = set(), set(), []
    for value in paths:
        path = Path(value)
        if not path.exists(): raise FileNotFoundError('History path missing: ' + str(path))
        if path.is_file():
            files.add(path)
        else:
            files.update(p for name in HISTORY_NAMES for p in path.rglob(name))
    # Automatic discovery is deliberately limited to known check output directories.
    for root in (Path('/kaggle/working'), Path('/kaggle/input')):
        if root.exists():
            for folder in root.rglob('*'):
                if folder.is_dir() and (folder.name.startswith('cnkang_review') or folder.name == 'cnkang_test'):
                    files.update(folder / name for name in HISTORY_NAMES if (folder / name).is_file())
    for path in sorted(files):
        rows = read_jsonl(path)
        accepted = 0
        for row in rows:
            url = row.get('source_url') or row.get('url')
            if url and parser.is_host(url):
                urls.add(canonical(url)); accepted += 1
        reports.append({'path':str(path), 'rows':len(rows), 'url_rows':accepted,
                        'sha256':parser.sha(path.read_bytes())})
    if bundled_path:
        for row in read_jsonl(bundled_path):
            urls.add(canonical(row.get('source_url') or row['url']))
    return urls, reports


def allocate(capacities, target):
    """Per-branch floor, then capped Hamilton allocation; no replacement."""
    capacities = {k:v for k,v in sorted(capacities.items()) if v > 0}
    if sum(capacities.values()) < target: raise ValueError('Not enough new URLs for target')
    if len(capacities) > target:
        raise ValueError('More branches than target; increase TARGET_URLS to cover every branch')
    baseline = 10
    while sum(min(baseline, n) for n in capacities.values()) > target:
        baseline -= 1
    allocation = {k:min(baseline, n) for k,n in capacities.items()}
    remaining = target - sum(allocation.values())
    room = {k:n-allocation[k] for k,n in capacities.items()}
    total_room = sum(room.values())
    quotas = {k:remaining*n/total_room if total_room else 0 for k,n in room.items()}
    for k in capacities: allocation[k] += math.floor(quotas[k])
    residual = target - sum(allocation.values())
    order = sorted(capacities, key=lambda k: (-(quotas[k] % 1), k))
    for k in order:
        if residual and allocation[k] < capacities[k]:
            allocation[k] += 1; residual -= 1
    assert residual == 0 and sum(allocation.values()) == target
    return allocation, baseline


def prepare(config, out, bundled_history=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if type(config['target']) is not int or config['target'] < 1: raise ValueError('Invalid target')
    manifest = out / 'sample_manifest.jsonl'
    saved_path = out / 'config.json'
    identity = {**config, 'parser_sha256': parser.sha(Path(parser.__file__).read_bytes()),
                'check_sha256':parser.sha(Path(__file__).read_bytes()),
                'transport_sha256':parser.sha(Path(transport_module.__file__).read_bytes()),
                'network_sha256':parser.sha(Path(transport_module.NETWORK.__file__).read_bytes()),
                'network_worker_sha256':parser.sha(transport_module.NETWORK.WORKER_PATH.read_bytes()),
                'bundled_history_sha256':parser.sha(Path(bundled_history).read_bytes()) if bundled_history else None}
    if manifest.exists() and manifest.stat().st_size:
        if not saved_path.exists() or json.loads(saved_path.read_text(encoding='utf-8')) != identity:
            raise ValueError('Code/config changed. Use a new OUTPUT_DIR; preserve the previous run.')
        summary = json.loads((out / 'history_summary.json').read_text(encoding='utf-8'))
        samples = read_jsonl(manifest)
        if len(samples) != config['target'] or len({r['canonical_url'] for r in samples}) != len(samples):
            raise ValueError('Corrupt sample manifest')
        if parser.sha(manifest.read_bytes()) != summary.get('manifest_sha256'):
            raise ValueError('Manifest hash changed')
        return samples, summary
    source = find_source(config)
    population, profile = read_population(source)
    history, files = read_history(config.get('history_paths', []), bundled_history)
    complete = bool(config.get('history_complete') and files and any(f['url_rows'] for f in files))
    warning = ('' if complete else
        'Chỉ loại các URL đã biết từ lịch sử hiện có; lịch sử chưa đầy đủ, '
        'không bảo đảm toàn bộ mẫu chưa từng được kiểm tra.')
    history_summary = {'source':str(source), 'source_sha256':parser.sha(source.read_bytes()),
        'requested':config['target'],
        'profile':profile, 'history_files':files, 'history_unique_urls':len(history),
        'history_complete_confirmed':complete,
        'all_urls_previously_untested_guaranteed':complete,
        'history_scope':'complete_declared_history' if complete else 'known_urls_only',
        'history_warning':warning,
        'bundled_history_is_partial':True}
    write_json(out / 'history_summary.json', history_summary)
    write_json(saved_path, identity)
    # Missing history is an explicit, reviewable state, not an unhandled exception or fake sample.
    if not complete and not config.get('allow_incomplete_history', False):
        history_summary.update(state='history_required', reason=(
            'Bundled URLs are partial evidence only. Mount complete previous review/samples manifests, '
            'set HISTORY_PATHS, then HISTORY_COMPLETE=True after checking coverage. No requests sent.'))
        write_json(out / 'history_summary.json', history_summary)
        return [], history_summary
    groups, eligible, excluded = defaultdict(list), Counter(), Counter()
    for key, row in population.items():
        eligible[row['branch']] += 1
        if key in history: excluded[row['branch']] += 1
        else: groups[row['branch']].append(row)
    capacity = {branch:len(rows) for branch,rows in groups.items()}
    if sum(capacity.values()) < config['target']:
        history_summary.update(state='insufficient_new_urls', available=sum(capacity.values()),
                               requested=config['target'], reason='Not enough unique new URLs; no requests sent.')
        write_json(out / 'history_summary.json', history_summary)
        save_csv(out / 'sampling_summary.csv', [
            {'branch':k,'eligible':eligible[k],'excluded_history':excluded[k],'selected':0} for k in sorted(eligible)],
            ['branch','eligible','excluded_history','selected'])
        return [], history_summary
    allocation, baseline = allocate(capacity, config['target'])
    samples = []
    for branch in sorted(groups):
        rows = sorted(groups[branch], key=lambda r:r['canonical_url'])
        chosen = random.Random(f"{config['seed']}:{branch}").sample(rows, allocation[branch])
        samples.extend(chosen)
    random.Random(config['seed']).shuffle(samples)
    if {r['canonical_url'] for r in samples} & history: raise AssertionError('History overlap')
    for sample in samples:
        sample.update(history_scope=history_summary['history_scope'],
                      all_urls_previously_untested_guaranteed=complete,
                      history_warning=warning)
    history_summary.update(state='ready' if complete else 'ready_partial_history', baseline_per_branch=baseline,
        baseline_note='Reduced baseline to fit target' if baseline < 10 else 'Up to 10 URLs per branch',
        selected=len(samples), excluded_history=sum(excluded.values()), overlap_with_history=0)
    save_csv(out / 'sampling_summary.csv', [
        {'branch':k,'eligible':eligible[k],'excluded_history':excluded[k],'selected':allocation.get(k,0)}
        for k in sorted(eligible)], ['branch','eligible','excluded_history','selected'])
    write_json(saved_path, identity)
    jsonl(manifest, samples)
    history_summary['manifest_sha256'] = parser.sha(manifest.read_bytes())
    write_json(out / 'history_summary.json', history_summary)
    return samples, history_summary


def save_csv(path, rows, fields):
    with Path(path).open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(row.get(k), ensure_ascii=False) if isinstance(row.get(k), (dict,list))
                             else row.get(k) for k in fields})


# Stable typed Parquet columns; the complete nested record is also available as JSON.
RESULT_SCHEMA = pa.schema([
    ('id',pa.int64()), ('ids',pa.list_(pa.int64())), ('source_url',pa.string()),
    ('canonical_url',pa.string()), ('final_url',pa.string()), ('branch',pa.string()),
    ('status',pa.string()), ('crawl_status',pa.string()), ('attempts',pa.int64()),
    ('selected_encoding',pa.string()), ('template',pa.string()), ('selector',pa.string()),
    ('title',pa.string()), ('date_candidates',pa.list_(pa.string())), ('date_context',pa.string()),
    ('source_name',pa.string()), ('text',pa.string()), ('text_sha256',pa.string()),
    ('chars_before',pa.int64()), ('chars_after',pa.int64()),
    ('parser_flags',pa.list_(pa.string())), ('source_flags',pa.list_(pa.string())),
    ('raw_html_path',pa.string()), ('text_before_path',pa.string()), ('text_clean_path',pa.string()),
    ('fetched_at',pa.string()), ('record_json',pa.string())])


def export(out, samples, history_summary=None):
    out = Path(out)
    records = []
    for sample in samples:
        path = out / 'records' / f"{sample['id']}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('canonical_url') != sample['canonical_url']:
                raise ValueError('Record differs from manifest')
            records.append(record)
    hashes = Counter(r.get('text_sha256') for r in records if r.get('text'))
    for r in records:
        if r.get('text') and hashes[r['text_sha256']] > 1:
            r['parser_flags'] = sorted(set(r.get('parser_flags', []) + ['DUPLICATE_DOCUMENT_REVIEW']))
            r['crawl_status'] = 'needs_review'
    jsonl(out / 'results.jsonl', records)
    parquet_rows = []
    for r in records:
        row = {name:r.get(name) for name in RESULT_SCHEMA.names if name != 'record_json'}
        row['record_json'] = json.dumps(r, ensure_ascii=False)
        parquet_rows.append(row)
    pq.write_table(pa.Table.from_pylist(parquet_rows, schema=RESULT_SCHEMA), out / 'results.parquet')
    review = [r for r in records if r.get('parser_flags') or r.get('source_flags') or r['status'] != 'extracted']
    save_csv(out / 'review.csv', review, ['id','source_url','branch','status','crawl_status','template',
                                        'parser_flags','source_flags','flag_evidence','error'])
    by_branch = []
    for branch in sorted({r['branch'] for r in samples}):
        rows = [r for r in records if r['branch'] == branch]
        by_branch.append({'branch':branch,'selected':sum(r['branch']==branch for r in samples),
            'completed':len(rows),
            'responses_received':sum(bool(r.get('fetched_at')) for r in rows),
            'fetched':sum(r['status'] in ('fetched','parse_failed','extracted') for r in rows),
            'parsed':sum(r['status']=='extracted' for r in rows),
            'fetch_failed':sum(r['crawl_status']=='fetch_failed' for r in rows),
            'parser_review':sum(bool(r.get('parser_flags')) for r in rows),
            'source_review':sum(bool(r.get('source_flags')) for r in rows),
            'date_checked':sum(r['status']=='extracted' for r in rows),
            'date_missing':sum(r['status']=='extracted' and not r.get('date_candidates') for r in rows)})
    save_csv(out / 'summary_by_branch.csv', by_branch, ['branch','selected','completed','fetched','parsed',
                                                       'fetch_failed','parser_review','source_review',
                                                       'responses_received','date_checked','date_missing'])
    summary = {'target': (history_summary or {}).get('requested',len(samples)),
        'selected':len(samples),'completed':len(records),'pending':len(samples)-len(records),
        'responses_received':sum(bool(r.get('fetched_at')) for r in records),
        'fetched':sum(r['status'] in ('fetched','parse_failed','extracted') for r in records),
        'parsed':sum(r['status']=='extracted' for r in records),
        'parse_failed':sum(r['status']=='parse_failed' for r in records),
        'parser_clean_pages':sum(r['status']=='extracted' and not r.get('parser_flags') for r in records),
        'fetch_failed':sum(r['crawl_status']=='fetch_failed' for r in records),
        'parser_review_pages':sum(bool(r.get('parser_flags')) for r in records),
        'source_review_pages':sum(bool(r.get('source_flags')) for r in records),
        'parser_flags':dict(Counter(f for r in records for f in set(r.get('parser_flags', [])))),
        'source_flags':dict(Counter(f for r in records for f in set(r.get('source_flags', [])))),
        'templates':dict(Counter(r.get('template','not_parsed') for r in records)),
        'date_checked':sum(r['status']=='extracted' for r in records),
        'date_missing':sum(r['status']=='extracted' and not r.get('date_candidates') for r in records),
        'history_state':(history_summary or {}).get('state'),
        'history_scope':(history_summary or {}).get('history_scope'),
        'history_warning':(history_summary or {}).get('history_warning', ''),
        'history_unique_urls':(history_summary or {}).get('history_unique_urls', 0),
        'excluded_history':(history_summary or {}).get('excluded_history', 0),
        'all_urls_previously_untested_guaranteed':(history_summary or {}).get(
            'all_urls_previously_untested_guaranteed', False)}
    write_json(out / 'summary.json', summary)
    lines = ['# Báo cáo cnkang', '', summary['history_warning'], '',
             json.dumps(summary,ensure_ascii=False,indent=2), '',
             'responses_received đếm URL có phản hồi HTTP, kể cả redirect/lỗi. '
             'fetched chỉ đếm HTML đã qua kiểm tra fetch, kể cả trang sau đó lỗi parser. '
             'parsed đếm trang trích xuất được; parser_clean_pages là số trang không có cờ parser. '
             'date_missing chỉ tính trên date_checked trang trích xuất được.', '',
             'QC là heuristic trích xuất; không xác nhận độ đúng y khoa.', '',
             '## Mẫu từng nhánh (giới hạn đầu/cuối)', '']
    for i, branch in enumerate(sorted({r['branch'] for r in records})):
        rows = [r for r in records if r['branch']==branch]
        preferred = [r for r in rows if bool(r.get('parser_flags')) == bool(i % 2)]
        r = (preferred or rows)[0]
        lines += [f"### {branch}: {r.get('title','')}",r['source_url'],
                  f"Template: {r.get('template')}; parser: {r.get('parser_flags')}; source: {r.get('source_flags')}",
                  r.get('text','')[:400], r.get('text','')[-400:], '']
    lines += ['## Bằng chứng theo cờ (tối đa 10 trang mỗi nhóm)', '']
    for flag in sorted(set(summary['parser_flags']) | set(summary['source_flags'])):
        lines += ['### ' + flag]
        for r in [r for r in records if flag in r.get('parser_flags', []) + r.get('source_flags', [])][:10]:
            proof = [e for e in r.get('flag_evidence',[]) if e['flag']==flag]
            lines += [r['source_url'], json.dumps(proof,ensure_ascii=False)[:1500]]
    lines += ['','## Kết luận theo template', '']
    for template in sorted(summary['templates']):
        group = [r for r in records if r.get('template','not_parsed')==template]
        clean = sum(r['status']=='extracted' and not r.get('parser_flags') for r in group)
        lines += [f"- {template}: {clean}/{len(group)} trang không có cờ parser. " +
                  ('Cần parser riêng/đối chiếu raw trước khi mở rộng.' if template=='unknown' or clean<len(group)
                   else 'Có cơ sở giữ template trong mẫu này; cần kiểm tra nguồn và tính đầy đủ bằng đọc mẫu.')]
    if not samples:
        lines += ['',(history_summary or {}).get('reason','Chưa có mẫu; chưa gửi request.')]
    lines += ['', 'Chưa xác minh toàn corpus hoặc độ đúng y khoa. Không suy rộng tỷ lệ mẫu phân tầng '
              'thành tỷ lệ toàn domain. Không tự tải phân trang chưa xác minh thuộc cùng bài.']
    (out / 'review_report.md').write_text('\n\n'.join(lines), encoding='utf-8')
    # All mandatory structured artifacts exist even when history blocks fetching.
    for name in ('sample_manifest.jsonl','crawl_journal.jsonl'):
        (out / name).touch(exist_ok=True)
    if not (out/'robots_checks.json').exists(): write_json(out/'robots_checks.json', {})
    if not (out/'sampling_summary.csv').exists():
        save_csv(out/'sampling_summary.csv', [], ['branch','eligible','excluded_history','selected'])
    for folder in ('raw_html','text_before','text_clean'): (out/folder).mkdir(exist_ok=True)
    return summary


def run(out, samples, config):
    network = transport_module.Transport(out, config)
    try:
        try:
            network.wait()
        except transport_module.Paused as exc:
            print(str(exc), flush=True)
            return
        for index, sample in enumerate(samples, 1):
            path = Path(out) / 'records' / f"{sample['id']}.json"
            if path.exists():
                previous = json.loads(path.read_text(encoding='utf-8'))
                if not previous.get('retry_deferred'): continue
            if network.stopped: break
            record = network.fetch(sample)
            if index % 10 == 0 or record['status'] != 'extracted':
                print(f"{index}/{len(samples)} | {sample['branch']} | {record['crawl_status']} | HTTP {record.get('http_status')}",
                      flush=True)
    finally:
        network.close()
