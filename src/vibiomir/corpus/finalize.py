"""Block A, after crawling: `audit` checks a finished run offline; `export` writes the compact corpus."""
import argparse
from collections import Counter
import gzip
import hashlib
import html as html_escape
import json
from pathlib import Path
import random
import re
import sys
import unicodedata

from lxml import html
import pyarrow as pa
import pyarrow.parquet as pq


# --- audit: offline integrity/content diagnostics and an unlabelled review sheet ---

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def compact(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def audit(args):
    out = Path(args.out)
    manifest = read(out / 'manifest.json')
    if sha((out / 'sample.jsonl').read_bytes()) != manifest['sample_sha256']:
        raise ValueError('Sample hash mismatch')
    sample = [json.loads(s) for s in (out / 'sample.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = {r['id']: r['url'] for r in sample}
    source = pq.read_table(manifest['source'], filters=[('id', 'in', list(expected))]).to_pylist()
    if {r['id']: r['url'] for r in source} != expected:
        raise ValueError('Sample does not match source Parquet')
    records = [read(p) for p in sorted((out / 'records').glob('*.json'))]
    actual = {r['id']: r['url'] for r in records}
    if actual != expected or len(records) != len(expected):
        raise ValueError('Run incomplete or contains unexpected IDs; wait for all checkpoints')
    cases = []
    source_views = {}
    for r in records:
        case = {'id': r['id'], 'url': r['url'], 'quality_status': r.get('quality_status'), 'flags': []}
        if r.get('raw_path'):
            body = gzip.decompress((out / r['raw_path']).read_bytes())
            if sha(body) != r['raw_sha256']:
                raise ValueError(f"Raw hash mismatch: {r['id']}")
            if 'text' in r and sha(r['text'].encode()) != r['text_sha256']:
                raise ValueError(f"Text hash mismatch: {r['id']}")
            if not body.startswith(b'%PDF-'):
                enc = r.get('declared_encoding') or 'utf-8'
                tree = html.fromstring(body.decode(enc, 'replace'))
                bodies = [e for e in tree.iter('div') if 'content-editor-post' in (e.get('class') or '').split()]
                intros = [e for e in tree.iter('div') if 'content-excerpt' in (e.get('class') or '').split()]
                clean = compact(r.get('text', ''))
                intro = compact(' '.join(e.text_content() for e in intros))
                case['source_intro_chars'] = len(intro)
                case['intro_preserved'] = intro in clean if intro else None
                if intro and intro not in clean:
                    case['flags'].append('intro_not_fully_preserved')
                if bodies:
                    article = bodies[0]
                    case['source_table_count'] = len(article.xpath('.//table'))
                    case['source_image_count'] = len(article.xpath('.//img'))
                    links = [a.get('href') for a in article.iter('a') if a.get('href')]
                    case['attachment_urls'] = [u for u in links if re.search(r'\.(pdf|docx?|xlsx?)(?:$|[?#])', u, re.I)]
                    if len(clean) < 150 and case['source_image_count']:
                        case['flags'].append('image_text_requires_ocr_review')
                    # Independent block reference from raw DOM, never generated from the clean text.
                    for el in article.xpath('.//script|.//style|.//iframe|.//noscript'):
                        el.drop_tree()
                    source_views[r['id']] = '\n'.join(t.strip() for t in article.itertext() if t.strip())
                else:
                    source_views[r['id']] = '(Không có selector Bạch Mai; kiểm tra raw gốc theo raw_path.)'
        text = r.get('text', '')
        if re.search(r'MicrosoftInternetExplorer|mso-style|mso-tstyle|<!\[endif|<style>|<xml>', text, re.I):
            case['flags'].append('office_or_markup_leak')
        if r.get('quality_status') != 'accepted':
            case['flags'].extend(r.get('quality_flags', []))
        case['flags'] = sorted(set(case['flags']))
        cases.append(case)
    counts = Counter(f for c in cases for f in c['flags'])
    summary = {'selected': len(sample), 'completed': len(records), 'source_mapping_verified': True,
               'raw_and_text_hashes_verified': True, 'diagnostic_flags': dict(counts),
               'documents_with_intro': sum(c.get('intro_preserved') is not None for c in cases),
               'documents_with_intro_preserved': sum(c.get('intro_preserved') is True for c in cases),
               'documents_with_source_tables': sum(c.get('source_table_count', 0) > 0 for c in cases),
               'scope': 'Automated raw/DOM diagnostics; not expert gold extraction quality.',
               'human_review_completed': 0}
    (out / 'audit_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'audit_cases.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in cases), encoding='utf-8')
    accepted = sorted((r for r in records if r.get('quality_status') == 'accepted'), key=lambda r: r['id'])
    review_rows = random.Random(42).sample(accepted, min(args.review_size, len(accepted)))
    sheet = out / 'review_100.jsonl'
    if not sheet.exists():
        items = [{'id': r['id'], 'url': r['url'], 'title': r.get('title'), 'raw_path': r.get('raw_path'),
                  'correct_page': None, 'completeness_0_to_2': None, 'cleanliness_0_to_2': None,
                  'medical_numbers_preserved': None, 'reviewer': None, 'notes': ''} for r in review_rows]
        sheet.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in items), encoding='utf-8')
    page = ['<!doctype html><html lang="vi"><meta charset="utf-8"><title>Audit corpus</title>',
            '<style>body{font:16px system-ui;margin:24px;line-height:1.6}details{border:1px solid #ccc;padding:12px;margin:12px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px system-ui}.flag{color:#963}</style>',
            '<h1>Phiếu kiểm tra 100 tài liệu accepted</h1><p>Mẫu ngẫu nhiên seed 42. Cột trái là text từ DOM thân bài raw, cột phải là corpus. Đây chưa phải kết quả chấm của người đánh giá.</p>']
    for r in review_rows:
        esc = html_escape.escape
        page.append(f"<details><summary>{r['id']} — {esc(r.get('title', ''))}</summary><p>{esc(r['url'])}</p><div class='pair'><section><h3>DOM nguồn (thân bài, chưa gồm excerpt)</h3><pre>{esc(source_views.get(r['id'], 'Xem raw gốc'))}</pre></section><section><h3>Corpus (excerpt + thân bài)</h3><pre>{esc(r.get('text', ''))}</pre></section></div></details>")
    page.append('</html>')
    (out / 'review_100.html').write_text('\n'.join(page), encoding='utf-8')
    md = ['# Kiểm tra offline corpus', '', f"- ID/URL khớp nguồn: {len(records)}/{len(sample)}.",
          '- Raw và text được kiểm tra SHA-256.',
          f"- Excerpt giữ đủ sau gộp whitespace: {summary['documents_with_intro_preserved']}/{summary['documents_with_intro']} bài có excerpt.",
          f"- Bài có bảng trong HTML nguồn: {summary['documents_with_source_tables']}.",
          f"- Phiếu audit: {len(review_rows)} tài liệu accepted; chưa có người chấm.", '',
          'Các phép kiểm tra này xác nhận provenance và phát hiện một số lỗi; không chứng minh đầy đủ nội dung bằng gold passages.', '',
          '| Cờ | Số tài liệu |', '| --- | ---: |']
    md.extend(f'| {key} | {count} |' for key, count in sorted(counts.items()))
    md.extend(['', 'Xem `audit_cases.jsonl` để tra ID; `review_100.html` để đọc nguồn và corpus cạnh nhau; điền đánh giá vào `review_100.jsonl`.', ''])
    (out / 'AUDIT_REPORT.md').write_text('\n'.join(md), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=True))


# --- export: ID-preserving corpus.parquet/jsonl from corpus.accepted.jsonl ---

def read_jsonl(path):
    # str.splitlines() also splits U+2028/U+0085 inside valid JSON string values.
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def export(args):
    out = Path(args.out)
    source = read_jsonl(out / 'corpus.accepted.jsonl')
    expected = {r['id']: r for r in source}
    if not source or len(expected) != len(source):
        raise ValueError('Empty corpus or duplicate IDs')
    fields = ('id', 'url', 'final_url', 'title', 'text', 'domain', 'extractor', 'published_at',
              'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids')
    rows = [{key: r.get(key) for key in fields} for r in sorted(source, key=lambda r: r['id'])]
    for r in source:
        if r['quality_status'] != 'accepted' or not r['text'].strip():
            raise ValueError('Non-accepted or empty record')
        if hashlib.sha256(r['text'].encode()).hexdigest() != r['text_sha256']:
            raise ValueError('Text hash mismatch')
    schema = pa.schema([
        (key, pa.int64() if key == 'id' else pa.list_(pa.int64()) if key == 'duplicate_doc_ids' else pa.string())
        for key in fields
    ])
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, out / 'corpus.parquet', compression='zstd')
    (out / 'corpus.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    reread = pq.read_table(out / 'corpus.parquet').to_pylist()
    if reread != rows:
        raise ValueError('Parquet round-trip mismatch')
    if read_jsonl(out / 'corpus.jsonl') != rows:
        raise ValueError('JSONL round-trip mismatch')
    result = {'documents': len(rows), 'id_type': 'int64', 'accepted_source_ids_preserved': True,
              'parquet_round_trip_verified': True, 'jsonl_round_trip_verified': True, 'files': {}}
    for name in ('corpus.jsonl', 'corpus.parquet'):
        data = (out / name).read_bytes()
        result['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    (out / 'export_manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('audit', help='Verify raw/text hashes and write the review sheet.')
    p.add_argument('--out', required=True)
    p.add_argument('--review-size', type=int, default=100)
    p.set_defaults(func=audit)
    p = sub.add_parser('export', help='Write corpus.parquet and corpus.jsonl.')
    p.add_argument('--out', required=True)
    p.set_defaults(func=export)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
