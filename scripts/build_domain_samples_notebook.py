"""Refresh unique per-host samples from the pinned corpus and embed IP diagnostics."""
import ast
import base64
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from pprint import pformat
import random
from urllib.parse import urlsplit
import zlib

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / 'notebooks/crawl_domain_samples.ipynb'
SOURCE = ROOT / 'data/links_corpus_vi_en_zh.parquet'
SEED = 20261014
QUOTA = 20


def assignments(source):
    result = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return result


def replace(source, values):
    lines = source.splitlines(keepends=True)
    edits = [(node.lineno - 1, node.end_lineno, node.targets[0].id)
             for node in ast.parse(source).body if isinstance(node, ast.Assign)
             and isinstance(node.targets[0], ast.Name) and node.targets[0].id in values]
    found = {name for _, _, name in edits}
    for start, stop, name in sorted(edits, reverse=True):
        lines[start:stop] = [name + ' = ' + pformat(values[name], sort_dicts=False) + '\n']
    additions = ''.join(name + ' = ' + pformat(value, sort_dicts=False) + '\n'
        for name, value in values.items() if name not in found)
    return ''.join(lines).rstrip() + '\n' + ('\n' + additions if additions else '')


def select_samples(source, excluded_ids, excluded_urls, seed=SEED, quota=QUOTA):
    seen, counts, unique, available = set(), Counter(), Counter(), Counter()
    reservoirs, rng = defaultdict(list), {}
    id_min, id_max = None, None
    for batch in pq.ParquetFile(source).iter_batches(batch_size=65536, columns=['id', 'url']):
        for row in batch.to_pylist():
            ident, url = row['id'], row['url']
            domain = (urlsplit(url).hostname or '').lower()
            if not domain:
                raise ValueError('Source URL has no hostname')
            counts[domain] += 1
            id_min = ident if id_min is None else min(id_min, ident)
            id_max = ident if id_max is None else max(id_max, ident)
            if url in seen:
                continue
            seen.add(url)
            unique[domain] += 1
            if ident in excluded_ids or url in excluded_urls:
                continue
            available[domain] += 1
            if domain not in rng:
                rng[domain] = random.Random(f'{seed}:{domain}')
            bucket = reservoirs[domain]
            if len(bucket) < quota:
                bucket.append(row)
            else:
                index = rng[domain].randrange(available[domain])
                if index < quota:
                    bucket[index] = row
    samples = []
    for domain in sorted(counts):
        for index, row in enumerate(sorted(reservoirs[domain], key=lambda r: r['id'])):
            samples.append(dict(row, domain=domain, sample_index=index, sample_role='additional'))
    profile = {'rows': sum(counts.values()), 'id_min': id_min, 'id_max': id_max, 'hosts': len(counts),
               'host_counts': dict(sorted(counts.items())), 'unique_host_counts': dict(sorted(unique.items())),
               'available_host_counts': {domain: available[domain] for domain in sorted(counts)},
               'sample_host_counts': {domain: len(reservoirs[domain]) for domain in sorted(counts)}}
    return samples, profile


def main():
    notebook = json.loads(NOTEBOOK.read_text(encoding='utf-8'))
    pack_source = ''.join(notebook['cells'][7]['source'])
    pack = assignments(pack_source)
    with SOURCE.open('rb') as stream:
        actual_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual_hash != pack['SOURCE_SHA256']:
        raise ValueError('Parquet hash differs from the pinned notebook source')
    excluded_ids = set(pack.get('EXCLUDED_SAMPLE_IDS', [r['id'] for r in pack['SAMPLES']]))
    excluded_urls = set(pack.get('EXCLUDED_SAMPLE_URLS', [r['url'] for r in pack['SAMPLES']]))
    # Exclude the fixed PubMed probes and the Kaggle 403 URLs already examined in this task.
    excluded_ids.update([6034570, 6264823, 6272144, 6331460, 6494525, 6584929, 6689567, 6713129,
        6743359, 6806142, 6814865, 7000989, 7009785, 7025795, 7117564, 7181339, 7226872, 7279666,
        7280508, 7410454, 5880584, 5880586, 5880597, 5880598, 5880636, 5880645, 5880663, 5880664,
        5880681, 5880684])
    excluded_urls.update(r['url'] for r in pq.read_table(SOURCE, columns=['url'],
        filters=[('id', 'in', sorted(excluded_ids))]).to_pylist())
    samples, profile = select_samples(SOURCE, excluded_ids, excluded_urls)
    if set(profile['host_counts']) != set(pack['SOURCE_PROFILE']['host_counts']):
        raise ValueError('Hostname inventory changed')
    baseline = {domain: {'error_type': 'not_previously_tested',
                        'shortfall': max(0, QUOTA - profile['sample_host_counts'][domain])}
                for domain in profile['host_counts']}
    helper = (ROOT / 'scripts/domain_ip_diagnostics.py').read_bytes()
    values = {'SAMPLES': samples, 'SOURCE_PROFILE': profile, 'BASELINE_DOMAINS': baseline,
              'EXPECTED_URL_COUNT': len(samples), 'EXPECTED_DOMAIN_COUNT': len(profile['host_counts']),
              'PROBE_KIND': 'all_hosts_ip_access_probe_v1',
              'SAMPLING_METHOD': 'fresh_per_host_reservoir_unique_urls_excluding_previous_samples',
              'EXCLUDED_SAMPLE_IDS': sorted(excluded_ids), 'EXCLUDED_SAMPLE_URLS': sorted(excluded_urls),
              'EMBEDDED_SAMPLE_SEED': SEED,
              'IP_DIAGNOSTICS_PAYLOAD': base64.b85encode(zlib.compress(helper, 9)).decode('ascii'),
              'IP_DIAGNOSTICS_SHA256': hashlib.sha256(helper).hexdigest()}
    pack_source = replace(pack_source, values)
    old_validation = "if (set(r['domain'] for r in SAMPLES) != set(TARGET_DOMAINS)\n        or any(sum(r['domain'] == domain for r in SAMPLES) != SAMPLES_PER_DOMAIN for domain in TARGET_DOMAINS)):\n    raise ValueError('Mẫu phải có đúng 20 URL cho mỗi domain VOV và Long Châu.')"
    selection = '''# Runtime filtering is limited to the freshly embedded URLs; no source download is needed.
if SAMPLE_SEED != EMBEDDED_SAMPLE_SEED:
    raise ValueError('Mẫu đã nhúng theo seed cố định; build lại notebook để đổi SAMPLE_SEED.')
ALL_SAMPLES = SAMPLES
TARGET_DOMAINS = tuple(sorted(SOURCE_PROFILE['host_counts'])) if TARGET_DOMAINS is None else tuple(TARGET_DOMAINS)
if (not TARGET_DOMAINS or len(set(TARGET_DOMAINS)) != len(TARGET_DOMAINS)
        or set(TARGET_DOMAINS) - set(SOURCE_PROFILE['host_counts'])):
    raise ValueError('TARGET_DOMAINS phải thuộc danh sách hostname trong corpus.')
if type(SAMPLES_PER_DOMAIN) is not int or not 1 <= SAMPLES_PER_DOMAIN <= 20:
    raise ValueError('Notebook nhúng tối đa 20 URL/hostname; SAMPLES_PER_DOMAIN phải từ 1 đến 20.')
SAMPLES = [r for r in ALL_SAMPLES if r['domain'] in TARGET_DOMAINS and r['sample_index'] < SAMPLES_PER_DOMAIN]
NETWORK_CHECK_DOMAINS = TARGET_DOMAINS
SOURCE_PROFILE = json.loads(json.dumps(SOURCE_PROFILE))
SOURCE_PROFILE['sample_host_counts'] = {domain: sum(r['domain'] == domain for r in SAMPLES)
                                      for domain in SOURCE_PROFILE['host_counts']}
EXPECTED_DOMAIN_COUNT = len(TARGET_DOMAINS)
EXPECTED_URL_COUNT = len(SAMPLES)
BASELINE_DOMAINS = {domain: BASELINE_DOMAINS[domain] for domain in TARGET_DOMAINS}
if any(SOURCE_PROFILE['sample_host_counts'][domain] != min(
        SAMPLES_PER_DOMAIN, SOURCE_PROFILE['available_host_counts'][domain]) for domain in TARGET_DOMAINS):
    raise ValueError('Số mẫu không khớp số URL duy nhất có sẵn.')
sample_bytes = ''.join(json.dumps(r, ensure_ascii=False) + '\\n' for r in SAMPLES).encode('utf-8')
'''
    if old_validation in pack_source:
        pack_source = pack_source.replace(old_validation, selection.rstrip())
    else:
        # Replace the generated selection block when rebuilding, without accumulating code.
        start = pack_source.index('# Runtime filtering is limited')
        stop = pack_source.index('manifest_path =', start)
        pack_source = pack_source[:start] + selection + pack_source[stop:]
    # The helper definitions must precede execution, even if replace() appended new literals.
    tree = ast.parse(pack_source)
    generated_names = ('EXCLUDED_SAMPLE_IDS', 'EXCLUDED_SAMPLE_URLS', 'EMBEDDED_SAMPLE_SEED', 'IP_DIAGNOSTICS_PAYLOAD', 'IP_DIAGNOSTICS_SHA256')
    lines = pack_source.splitlines(keepends=True)
    moves = [(n.lineno - 1, n.end_lineno) for n in tree.body if isinstance(n, ast.Assign)
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id in generated_names]
    definitions = ''.join(''.join(lines[a:b]) for a, b in moves)
    for start, stop in sorted(moves, reverse=True):
        del lines[start:stop]
    pack_source = definitions.rstrip() + '\n\n' + ''.join(lines).lstrip('\n')
    # Older notebooks computed bytes before filtering TARGET_DOMAINS; only retain the new one.
    lines = pack_source.splitlines(keepends=True)
    selection_start = pack_source.index('# Runtime filtering is limited')
    early_bytes = [(n.lineno - 1, n.end_lineno) for n in ast.parse(pack_source).body
                   if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)
                   and n.targets[0].id == 'sample_bytes'
                   and sum(len(line) for line in lines[:n.lineno - 1]) < selection_start]
    for start, stop in sorted(early_bytes, reverse=True):
        del lines[start:stop]
    pack_source = ''.join(lines)
    helper_load = '''
ip_path = RUN_DIR / 'ip_diagnostics_snapshot.py'
ip_bytes = zlib.decompress(base64.b85decode(IP_DIAGNOSTICS_PAYLOAD))
if sha256(ip_bytes) != IP_DIAGNOSTICS_SHA256:
    raise ValueError('IP diagnostics snapshot bị hỏng.')
if ip_path.exists() and sha256(ip_path.read_bytes()) != IP_DIAGNOSTICS_SHA256:
    raise ValueError('IP diagnostics khác run cũ; tạo run mới.')
ip_path.write_bytes(ip_bytes)
ip_spec = importlib.util.spec_from_file_location('domain_ip_diagnostics', ip_path)
IP_DIAGNOSTICS = importlib.util.module_from_spec(ip_spec)
sys.modules[ip_spec.name] = IP_DIAGNOSTICS
ip_spec.loader.exec_module(IP_DIAGNOSTICS)
'''
    if "ip_path = RUN_DIR / 'ip_diagnostics_snapshot.py'" not in pack_source:
        pack_source += helper_load
    notebook['cells'][7]['source'] = (pack_source.strip() + '\n').splitlines(keepends=True)
    config = ''.join(notebook['cells'][3]['source'])
    config = config.replace("TARGET_DOMAINS = ('vov.vn', 'nhathuoclongchau.com.vn')", "TARGET_DOMAINS = None  # None: toàn bộ hostname; hoặc tuple hostname cần thử")
    config = config.replace('SAMPLE_SEED = 42', f'SAMPLE_SEED = {SEED}')
    if 'IP_CHECK_ENABLED =' not in config:
        config = config.replace('NETWORK_CHECK_DOMAINS = TARGET_DOMAINS',
            "NETWORK_CHECK_DOMAINS = TARGET_DOMAINS\nIP_CHECK_ENABLED = True\n"
            "IP_HOMEPAGE_CHECK = True  # 1 lượt Requests tới homepage/hostname làm đối chứng\n"
            "IP_BROWSER_EGRESS_CHECK = True  # Đo IP của Chrome, đối chiếu với Requests\n"
            "IP_CHECK_TIMEOUT = (5.0, 10.0)\nIP_CHECK_BUDGET = 20.0")
    if 'IP_RECHECK_ON_RESUME =' not in config:
        config = config.replace('IP_CHECK_ENABLED = True', 'IP_CHECK_ENABLED = True\nIP_RECHECK_ON_RESUME = True  # Đo lại IP/homepage khi resume session mới')
    notebook['cells'][3]['source'] = config.splitlines(keepends=True)
    # Remove the old DNS-only check; full diagnostics live inside try/finally for interruption safety.
    crawl = ''.join(notebook['cells'][11]['source'])
    if '# DNS check is diagnostic only;' in crawl:
        start = crawl.index('# DNS check is diagnostic only;')
        stop = crawl.index('try:\n    if DIRECT_PUBLIC_PROBE:', start)
        crawl = crawl[:start] + crawl[stop:]
        crawl = crawl.replace('try:\n    if DIRECT_PUBLIC_PROBE:', '''try:
    if IP_CHECK_ENABLED:
        network = IP_DIAGNOSTICS.collect_network(
            crawler, priority_probe, RUN_DIR, NETWORK_CHECK_DOMAINS, user_agent=USER_AGENT,
            browser_user_agent=BROWSER_USER_AGENT, chrome_binary=CHROME_BINARY,
            browser_ip=IP_BROWSER_EGRESS_CHECK and BROWSER_TEST_MODE != 'off', homepage=IP_HOMEPAGE_CHECK,
            workers=WORKERS, timeout=IP_CHECK_TIMEOUT, budget=IP_CHECK_BUDGET)
        print('IP Requests:', network.get('requests_ips', []), '; IP Selenium:', network.get('selenium_ips', []))
        rows, summary, zip_path = save_outputs(show=False)
    if DIRECT_PUBLIC_PROBE:''')
    notebook['cells'][11]['source'] = crawl.splitlines(keepends=True)
    if 'force=IP_RECHECK_ON_RESUME' not in crawl:
        crawl = crawl.replace('workers=WORKERS, timeout=IP_CHECK_TIMEOUT, budget=IP_CHECK_BUDGET)',
                              'workers=WORKERS, timeout=IP_CHECK_TIMEOUT, budget=IP_CHECK_BUDGET, force=IP_RECHECK_ON_RESUME)')
        notebook['cells'][11]['source'] = crawl.splitlines(keepends=True)
    reporting = ''.join(notebook['cells'][9]['source'])
    if "IP_DIAGNOSTICS.build_report" not in reporting:
        reporting = reporting.replace('    # Archive outside the run directory',
            "    if IP_CHECK_ENABLED:\n"
            "        summary['ip_diagnostics'] = IP_DIAGNOSTICS.build_report(crawler, RUN_DIR, SAMPLES, SOURCE_PROFILE)\n"
            "        (RUN_DIR / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')\n"
            "    # Archive outside the run directory")
    reporting = reporting.replace("lấy được {r['additional_urls']}/4 URL mới", "lấy được {r['selected_urls']}/{SAMPLES_PER_DOMAIN} URL mới")
    reporting = reporting.replace('Lỗi baseline:', 'Trạng thái trước lượt thử:')
    reporting = reporting.replace('URL đã xử lý nhưng chưa request bài viết vì dừng trước bước tải bài.',
                                  'URL đã xử lý nhưng Requests chưa gửi tới bài viết (gồm PubMed dùng Selenium trực tiếp).')
    notebook['cells'][9]['source'] = reporting.splitlines(keepends=True)
    output = ''.join(notebook['cells'][13]['source'])
    output = output.replace("for name in ['WEB_ERRORS.md',", "for name in ['IP_BLOCK_REPORT.md', 'ip_block_report.html', 'ip_block_report.csv', 'ip_url_evidence.csv', 'network_check.json', 'WEB_ERRORS.md',")
    if 'if (RUN_DIR / name).exists():' not in output:
        output = output.replace('    display(FileLink(str(RUN_DIR / name)))', '    if (RUN_DIR / name).exists():\n        display(FileLink(str(RUN_DIR / name)))')
    notebook['cells'][13]['source'] = output.splitlines(keepends=True)
    descriptions = {
        0: f'''# Test tất cả hostname — URL mới và chẩn đoán IP

Upload notebook lên Kaggle, bật **Internet**, chạy **Run All**; không cần GPU hay clone repo.
Notebook nhúng **{len(samples):,} URL mới thuộc 94 hostname**, tối đa 20 URL duy nhất/hostname,
seed {SEED}, giữ ID/URL từ corpus 1.220.598 dòng đã ghim revision/hash.
Mẫu cũ của VOV/Long Châu và các URL PubMed đã thử được loại khỏi lượt chọn này.
Các hostname không đủ 20 URL có bảng số thiếu; không lặp URL để đủ quota.

Phần IP đo IP đầu ra của Requests và Chrome, DNS, một lượt homepage đối chứng/hostname,
và phân tích HTTP/raw/screenshot của các trang mẫu. **403 không tự chứng minh chặn IP**.
`IP_BLOCK_MESSAGE` chỉ ghi khi trang thông báo rõ chặn IP; `ACCESS_BLOCK_SUSPECTED`
là nghi ngờ chặn truy cập/anti-bot, chưa tách riêng nguyên nhân IP.
Giữ cùng notebook/mẫu khi chạy local và Kaggle để so sánh hai môi trường.

PubMed mặc định chạy Selenium trước; các hostname khác chạy Requests rồi Selenium khi lỗi/QC lỗi.
IP check dùng Requests tới **homepage**, không thay đổi việc bỏ Requests tới **bài viết PubMed**.
Chạy tất cả hostname có thể mất nhiều giờ. Có thể dừng cell và resume từ output đã lưu.
''',
        1: '''`TARGET_DOMAINS = None` chọn toàn bộ hostname trong corpus. Muốn giới hạn lượt thử,
đặt tuple hostname trong ô cấu hình. Mỗi hostname có tối đa 20 URL mới không trùng nhau.
Homepage, URL lỗi, challenge và lỗi parser/QC được báo riêng.
''',
        2: '''## 1. Cấu hình

Mặc định thử toàn bộ mẫu mới với `WORKERS = 2`, `MAX_NEW = None`.
`MAX_NEW` giới hạn URL bài viết mới, gồm PubMed chạy Selenium trực tiếp;
homepage/IP check là phép đo riêng. `IP_CHECK_ENABLED = False` tắt chẩn đoán IP.
`IP_HOMEPAGE_CHECK` và `IP_BROWSER_EGRESS_CHECK` có thể tắt riêng.

Dùng `RESUME_RUN_DIR` để tiếp tục cùng mẫu/code/cấu hình; checkpoint đã có, kể cả lỗi,
không tự thử lại. Để thử lại lỗi hoặc nâng cấp từ notebook 40 URL cũ, tạo run mới
và dùng `RECOVERY_RUN_DIR` nếu cần reuse raw cho ID/URL trùng mẫu.
''',
        6: '''## 3. Mẫu mới và snapshot

Mẫu được nhúng từ `links_corpus_vi_en_zh.parquet`, không cần tải Parquet trên Kaggle.
Danh sách hostname, số URL nguồn, URL duy nhất có sẵn và số mẫu thực tế được lưu
trong `source_profile.json`. ID/URL và hash mẫu được kiểm tra khi resume.
Code chẩn đoán IP được nhúng cùng notebook và có SHA-256 riêng.
''',
        10: '''## 5. Chẩn đoán mạng, crawl và đối chiếu Selenium

IP check đo Requests/Chrome qua ipify; ghi riêng lỗi dịch vụ đo IP, khác biệt IP và proxy.
Mỗi hostname được tra DNS và thử homepage một lần, có timeout/ngân sách hữu hạn,
không retry liên tục khi gặp 403/429. Lỗi kiểm tra IP không ngăn crawler thử trang mẫu.

PubMed đi Selenium trực tiếp; các hostname khác dùng engine/cấu hình chung với notebook corpus.
Hostname xử lý tuần tự, giới hạn tốc độ theo registered domain. Selenium fallback cho lỗi
HTTP/mạng/timeout/challenge và QC review/rejected. `off` tắt browser.
Ngắt cell giữ các checkpoint đã hoàn tất; chạy lại ô crawl để tiếp tục phần còn thiếu.

`ip_block_report.csv/html`, `IP_BLOCK_REPORT.md` và `ip_url_evidence.csv` được cập nhật
khi xuất báo cáo, kể cả ở finally sau gián đoạn. Chạy ô cuối để tạo lại báo cáo từ raw/checkpoint.
HTTP 2xx không đồng nghĩa nội dung đạt QC; 20 URL không đại diện cho toàn bộ hostname.
''',
        12: '''## 6. Xem bằng chứng và tải output

Mở **`ip_block_report.html`** để xem IP, kết luận từng hostname, số 403/429 và homepage đối chứng.
`ip_url_evidence.csv` ghi từng ID/URL/engine, phân loại, đoạn thông báo và đường dẫn raw/screenshot.
`network_check.json` ghi thời điểm, IP Requests/Chrome, DNS và việc có biến proxy (không ghi giá trị proxy).
`network_controls/` giữ raw/redirect/header của homepage và các lượt đo IP.

Không suy từ 403 thành chặn IP. Nếu trang ghi rõ IP/network bị chặn, đối chiếu thông báo với IP
đã đo; IP có thể khác theo proxy hoặc đích. Các lỗi parser, thiếu abstract, DNS, SSL, 404 và lỗi Chrome
được phân biệt với bằng chứng chặn truy cập.

ZIP chứa mẫu, snapshot, kết quả, raw và screenshot, gồm cả output dở dang.
Kaggle: tải ZIP trong Output rồi gửi lại để đối chiếu; có thể chạy cùng notebook local làm đối chứng.
'''
    }
    for index, body in descriptions.items():
        notebook['cells'][index]['source'] = body.splitlines(keepends=True)
    for cell in notebook['cells']:
        if cell['cell_type'] == 'code':
            compile(''.join(cell['source']), '<domain-notebook>', 'exec')
            cell['execution_count'], cell['outputs'] = None, []
    NOTEBOOK.write_text(json.dumps(notebook, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(json.dumps({'selected': len(samples), 'hosts': len(profile['host_counts']),
                      'shortages': {h: n for h, n in profile['sample_host_counts'].items() if n < QUOTA},
                      'ip_helper_sha256': hashlib.sha256(helper).hexdigest()}))


if __name__ == '__main__':
    main()
