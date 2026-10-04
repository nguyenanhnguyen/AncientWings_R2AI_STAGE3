"""Create a small, offline diagnostic ZIP from a crawl run, including partial runs."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import html
import io
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import zipfile


def read_json(path, warnings):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        warnings.append(f'{path.name}: {exc}')
        return {}


def read_jsonl(path, warnings):
    if not path.exists():
        return []
    rows = []
    with path.open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    warnings.append(f'{path.name}:{number}: {exc}')
    return rows


def csv_bytes(rows, fields):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                         for key, value in row.items() if key in fields})
    return stream.getvalue().encode('utf-8-sig')


def timing_summary(out, now, warnings):
    events = read_jsonl(out / 'logs' / 'invocations.jsonl', warnings)
    starts = [row for row in events if row.get('event') == 'start' and row.get('operation') == 'crawl']
    if not starts:
        return {'basis': 'unavailable', 'note': 'Không có log thời gian của notebook mới; không suy ra tốc độ từ số worker.'}
    start = starts[-1]
    invocation = start['invocation_id']
    progress = [row for row in read_jsonl(out / 'logs' / 'progress.jsonl', warnings)
                if row.get('invocation_id') == invocation]
    ends = [row for row in events if row.get('event') == 'end' and row.get('invocation_id') == invocation]
    if ends:
        seconds = ends[-1]['elapsed_seconds']
    else:
        seconds = (now - datetime.fromisoformat(start['at'])).total_seconds()
    latest = progress[-1] if progress else {}
    completed = latest.get('completed_this_invocation', 0)
    scheduled = latest.get('scheduled')
    rate = completed / seconds if completed and seconds > 0 else None
    return {
        'basis': 'latest_crawl_invocation_wall_time', 'invocation_id': invocation,
        'started_at': start['at'], 'finished': bool(ends), 'elapsed_seconds': round(seconds, 3),
        'completed_at_last_progress': completed, 'scheduled': scheduled,
        'urls_per_minute': round(rate * 60, 3) if rate else None,
        'seconds_per_url': round(1 / rate, 3) if rate else None,
        'eta_seconds': round(max(0, scheduled - completed) / rate, 1) if rate and scheduled is not None else None,
        'note': 'Tốc độ theo thời gian thực của lượt crawl gần nhất; số hoàn tất dựa trên log tiến độ. ETA chỉ là ước lượng.',
    }


def build_archive(out, archive):
    out, archive = Path(out), Path(archive)
    now = datetime.now(timezone.utc)
    warnings = []
    manifest = read_json(out / 'manifest.json', warnings)
    sample = read_jsonl(out / 'sample.jsonl', warnings)
    expected = {row['id']: row for row in sample}
    records, requests = [], []
    for path in sorted((out / 'records').glob('*.json')):
        record = read_json(path, warnings)
        if not record:
            continue
        if record.get('id') not in expected or record.get('url') != expected[record['id']]['url']:
            warnings.append(f'{path.name}: ID/URL ngoài mẫu; không tính vào tiến độ.')
            continue
        compact = {key: record.get(key) for key in (
            'id', 'url', 'domain', 'final_url', 'title', 'status', 'http_status', 'quality_status',
            'quality_flags', 'char_count', 'extractor', 'error', 'elapsed_seconds', 'started_at',
            'finished_at', 'raw_path', 'raw_sha256', 'text_sha256',
            'engine', 'access_status', 'requests_status', 'requests_http_status',
            'requests_error_kind', 'requests_error', 'browser_status', 'browser_http_status', 'browser_error',
        )}
        compact['domain'] = record.get('domain') or expected[record['id']].get('domain')
        compact['request_count'] = len(record.get('requests', []))
        compact['redirect_count'] = len(record.get('redirects', []))
        compact['raw_exists'] = (out / record['raw_path']).is_file() if record.get('raw_path') else None
        records.append(compact)
        for event in record.get('requests', []):
            requests.append({'id': record['id'], **{key: event.get(key) for key in ('url', 'at', 'attempt', 'http_status', 'error')}})
    records.sort(key=lambda row: row['id'])
    completed_ids = {row['id'] for row in records}
    pending = [row for row in sample if row['id'] not in completed_ids]
    flagged = [row for row in records if row.get('status') != 'extracted' or row.get('quality_status') != 'accepted'
               or row.get('quality_flags') or row.get('raw_exists') is False]
    by_domain = defaultdict(Counter)
    for row in sample:
        by_domain[row.get('domain', '')]['selected'] += 1
    for row in records:
        counts = by_domain[row.get('domain', '')]
        counts['completed'] += 1
        counts[str(row.get('quality_status') or 'unknown')] += 1
    summary = {
        'generated_at': now.isoformat(), 'run_name': out.name,
        'id_start_inclusive': manifest.get('id_start_inclusive'),
        'id_stop_exclusive': manifest.get('id_stop_exclusive'),
        'selected': len(sample), 'completed': len(records), 'pending': len(pending),
        'complete': bool(sample) and not pending,
        'status_counts': dict(Counter(str(row.get('status') or 'unknown') for row in records)),
        'quality_status_counts': dict(Counter(str(row.get('quality_status') or 'unknown') for row in records)),
        'http_status_counts': dict(Counter(str(row.get('http_status') or 'none') for row in records)),
        'quality_flags': dict(Counter(flag for row in records for flag in (row.get('quality_flags') or []))),
        'flagged_documents': len(flagged),
        'missing_raw_files': sum(row['raw_exists'] is False for row in records),
        'by_domain': {domain: dict(counts) for domain, counts in sorted(by_domain.items())},
        'timing': timing_summary(out, now, warnings), 'read_warnings': warnings,
        'scope': 'Snapshot chẩn đoán, không phải audit hash raw/text hay xác nhận chất lượng nội dung.',
    }
    fields = ('id', 'url', 'domain', 'final_url', 'title', 'status', 'http_status', 'quality_status',
              'quality_flags', 'char_count', 'extractor', 'error', 'request_count', 'redirect_count',
              'elapsed_seconds', 'started_at', 'finished_at', 'raw_exists', 'raw_path', 'raw_sha256', 'text_sha256')
    fields += ('engine', 'access_status', 'requests_status', 'requests_http_status',
               'requests_error_kind', 'requests_error', 'browser_status', 'browser_http_status', 'browser_error')
    pretty = json.dumps(summary, ensure_ascii=False, indent=2)
    timing = summary['timing']
    overview = [
        '<!doctype html><html lang="vi"><meta charset="utf-8"><title>Chẩn đoán crawl</title>',
        '<style>body{font:15px system-ui;margin:24px;line-height:1.5}table{border-collapse:collapse;width:100%}th,td{border:1px solid #ddd;padding:7px;text-align:left;vertical-align:top}td{overflow-wrap:anywhere}pre{white-space:pre-wrap}summary{cursor:pointer}</style>',
        f'<h1>Chẩn đoán crawl — {html.escape(out.name)}</h1>',
        f'<p>Snapshot: {html.escape(now.isoformat())}. Hoàn tất {len(records)}/{len(sample)}; còn chờ {len(pending)}.</p>',
        '<p>Extracted là đã chạy extractor; accepted là qua kiểm tra tự động. ZIP có một số mẫu record/raw để debug, không chứa toàn bộ corpus.</p>',
        '<p>Đây là snapshot tại thời điểm tạo ZIP; dữ liệu có thể tiếp tục thay đổi khi crawler đang chạy.</p>',
        '<h2>Tốc độ lượt crawl gần nhất</h2><pre>' + html.escape(json.dumps(timing, ensure_ascii=False, indent=2)) + '</pre>',
        '<h2>Trang cần xem lại / lỗi / có cờ</h2>',
        '<table><tr><th>ID</th><th>Trạng thái</th><th>QC</th><th>Cờ / lỗi</th><th>URL</th></tr>',
    ]
    for row in flagged:
        values = [row['id'], row.get('status'), row.get('quality_status'),
                  ' | '.join(row.get('quality_flags') or []) + ('; ' + str(row['error']) if row.get('error') else ''), row['url']]
        overview.append('<tr>' + ''.join(f'<td>{html.escape(str(value or ""))}</td>' for value in values) + '</tr>')
    overview.extend(['</table><details><summary>Thống kê JSON đầy đủ</summary><pre>', html.escape(pretty), '</pre></details></html>'])
    readme = f'''# Chẩn đoán crawl: {out.name}

Mở `overview.html` sau khi giải nén để xem tổng quan.
- `summary.json`: tiến độ, trạng thái, QC, từng domain, tốc độ/ETA của lượt crawl gần nhất.
- `records.csv`: metadata của mọi ID đã có checkpoint, không chứa text.
- `flagged.csv`: lỗi, review/rejected, các bản ghi có cờ hoặc thiếu raw.
- `pending.csv`: ID/URL chưa có checkpoint ở thời điểm tạo ZIP.
- `requests.csv`: thời điểm request, retry, HTTP status và lỗi theo ID.
- `redirects.csv`: chuỗi chuyển hướng theo ID.
- `environment.json`: Python, hệ điều hành và phiên bản thư viện.
- `code/`: snapshot crawler, audit, export và diagnostics đang dùng.
- `samples/`: tối đa 5 bản ghi có cờ/lỗi và 5 bản ghi khác, kèm raw nếu có; xem sample_manifest.json.
- `robots/`: tối đa 10 bằng chứng robots.txt, mỗi file tối đa 1 MiB.
- `metadata/`: manifest, cấu hình và báo cáo có sẵn; báo cáo có thể cũ hơn snapshot khi run đang chạy.
- `logs/`: log cài dependencies, lệnh chạy và tiến độ (tối đa 1 MiB cuối mỗi log).

ZIP chỉ chứa một số mẫu record/raw để debug, không chứa toàn bộ corpus. Raw mẫu có tổng ngân sách 10 MiB;
mỗi JSON record mẫu tối đa 1 MiB. `elapsed_seconds` trong records.csv
bao gồm cả chờ khóa/rate limit cùng domain; không dùng nó thay tốc độ toàn lượt crawl.
ZIP không chạy lại crawler, không kiểm tra toàn bộ hash raw/text và không thay checkpoint.
Hoàn tất: {len(records)}/{len(sample)}; còn chờ: {len(pending)}.
'''
    archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive.with_name(archive.name + '.tmp')
    environment = {'python': sys.version, 'platform': platform.platform(), 'packages': {}}
    for package in ('pyarrow', 'requests', 'trafilatura', 'pymupdf', 'tld'):
        try:
            environment['packages'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            environment['packages'][package] = None
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr('README.md', readme.encode('utf-8'))
            bundle.writestr('overview.html', '\n'.join(overview).encode('utf-8'))
            bundle.writestr('summary.json', pretty.encode('utf-8'))
            bundle.writestr('records.csv', csv_bytes(records, fields))
            bundle.writestr('flagged.csv', csv_bytes(flagged, fields))
            bundle.writestr('pending.csv', csv_bytes(pending, ('id', 'url', 'domain')))
            bundle.writestr('requests.csv', csv_bytes(requests, ('id', 'url', 'at', 'attempt', 'http_status', 'error')))
            redirects = []
            chosen = flagged[:5]
            chosen_ids = {row['id'] for row in chosen}
            chosen += [row for row in records if row['id'] not in chosen_ids][:5]
            chosen_ids = {row['id'] for row in chosen}
            sampled = []
            raw_budget = 10 * 1024 * 1024
            included_raw = set()
            for row in records:
                record = read_json(out / 'records' / f"{row['id']}.json", warnings)
                redirects.extend({'id': row['id'], **event} for event in record.get('redirects', []))
                if row['id'] not in chosen_ids:
                    continue
                record_path = out / 'records' / f"{row['id']}.json"
                case = {'id': row['id'], 'status': row['status'], 'quality_status': row['quality_status'],
                        'record_included': False, 'raw_included': False}
                if record_path.stat().st_size <= 1024 * 1024:
                    bundle.write(record_path, f"samples/records/{row['id']}.json")
                    case['record_included'] = True
                else:
                    case['record_skip_reason'] = 'record_exceeds_1_MiB'
                if row.get('raw_path'):
                    raw = (out / row['raw_path']).resolve()
                    if raw.is_relative_to((out / 'raw').resolve()) and raw.is_file():
                        relative = raw.relative_to(out.resolve()).as_posix()
                        if relative in included_raw:
                            case['raw_included'] = True
                        elif raw.stat().st_size <= raw_budget:
                            bundle.write(raw, 'samples/' + relative)
                            raw_budget -= raw.stat().st_size
                            included_raw.add(relative)
                            case['raw_included'] = True
                        else:
                            case['raw_skip_reason'] = 'raw_budget_exceeded'
                    else:
                        case['raw_skip_reason'] = 'missing_or_outside_raw_directory'
                sampled.append(case)
            bundle.writestr('redirects.csv', csv_bytes(redirects, ('id', 'from', 'to', 'status')))
            bundle.writestr('sample_manifest.json', json.dumps(sampled, ensure_ascii=False, indent=2).encode('utf-8'))
            bundle.writestr('environment.json', json.dumps(environment, ensure_ascii=False, indent=2).encode('utf-8'))
            for name in ('crawler_snapshot.py', 'audit_snapshot.py', 'export_snapshot.py', 'diagnostics_snapshot.py',
                         'priority_probe_snapshot.py', 'corpus_runner_snapshot.py'):
                path = out / name
                if path.is_file():
                    bundle.write(path, 'code/' + name)
            for path in sorted((out / 'robots').glob('*.json'))[:10]:
                if path.stat().st_size <= 1024 * 1024:
                    bundle.write(path, 'robots/' + path.name)
            for name in ('manifest.json', 'crawl_config.json', 'source_profile.json', 'quality_report.json',
                         'QUALITY_REPORT.md', 'audit_summary.json', 'AUDIT_REPORT.md', 'notebook_manifest.json',
                         'notebook_requirements.txt', 'export_manifest.json'):
                path = out / name
                if path.is_file():
                    bundle.write(path, 'metadata/' + name)
            for name in ('corpus_config.json', 'corpus_settings.json', 'priority_probe_config.json',
                         'recovery_manifest.json', 'browser_environment.json', 'browser_setup_error.json',
                         'access_summary.json', 'uu_tien_fix_domain.json', 'WEB_ERRORS.md',
                         'requests_vs_selenium.csv', 'khong_vao_duoc.csv'):
                path = out / name
                if path.is_file():
                    bundle.write(path, 'metadata/' + name)
            # Keep the original engine records for the same bounded set of debug samples.
            for row in chosen:
                for folder in ('requests_records', 'browser_records', 'recovery_records'):
                    path = out / folder / f"{row['id']}.json"
                    if path.is_file() and path.stat().st_size <= 1024 * 1024:
                        bundle.write(path, f"samples/{folder}/{path.name}")
            for path in sorted((out / 'logs').glob('*')):
                if path.is_file():
                    with path.open('rb') as stream:
                        stream.seek(max(0, path.stat().st_size - 1024 * 1024))
                        bundle.writestr('logs/' + path.name, stream.read())
        temporary.replace(archive)
    finally:
        temporary.unlink(missing_ok=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--archive', required=True)
    args = parser.parse_args()
    summary = build_archive(args.out, args.archive)
    print(json.dumps({'archive': args.archive, 'completed': summary['completed'], 'pending': summary['pending']}))


if __name__ == '__main__':
    main()
