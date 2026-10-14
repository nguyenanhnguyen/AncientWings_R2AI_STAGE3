"""Offline integrity/content diagnostics and an unlabelled review sheet for a crawl run."""
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
import xml.etree.ElementTree as ET
from functools import lru_cache
from urllib.parse import urlsplit

from lxml import html
import pyarrow.parquet as pq


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def compact(text):
    return ' '.join(unicodedata.normalize('NFC', text).split())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def raw_html_tree(body, encoding):
    decoded = body.decode(encoding, 'replace')
    if not decoded.strip():
        return None, 'empty_raw_document'
    try:
        return html.fromstring(decoded), None
    except (html.etree.ParserError, ValueError):
        return None, 'unparseable_raw_document'


@lru_cache(maxsize=4)
def raw_evidence(path):
    body = gzip.decompress(Path(path).read_bytes())
    return body, sha(body)


@lru_cache(maxsize=4)
def pubmed_xml_records(body):
    root = ET.fromstring(body)
    if root.tag != 'PubmedArticleSet':
        raise ValueError('PubMed evidence is not EFetch XML.')
    records = {}
    for record in root:
        location = 'MedlineCitation' if record.tag == 'PubmedArticle' else 'BookDocument'
        pmid = record.findtext(location + '/PMID', '')
        records.setdefault(pmid, []).append(record)
    return records


def audit_pubmed_xml(record, body):
    """Verify source title, every abstract section and labels independently of the crawler parser."""
    pmid = urlsplit(record['url']).path.strip('/')
    if record.get('pubmed_pmid') != pmid:
        raise ValueError(f"PubMed PMID/URL mismatch: {record['id']}")
    matches = pubmed_xml_records(body).get(pmid, [])
    if record.get('pubmed_api_status') == 'missing_pmid':
        if matches or record.get('text') or record.get('quality_status') == 'accepted':
            raise ValueError(f"PubMed missing PMID evidence mismatch: {record['id']}")
        return '', {'pubmed_pmid_missing': True}
    if record.get('pubmed_api_status') == 'duplicate_api_pmid':
        if len(matches) < 2 or record.get('quality_status') == 'accepted':
            raise ValueError(f"PubMed duplicate PMID evidence mismatch: {record['id']}")
        return '', {'pubmed_duplicate_pmid': True}
    if len(matches) != 1 or record.get('pubmed_pmid_verified') is not True:
        raise ValueError(f"PubMed PMID not uniquely verified: {record['id']}")
    element = matches[0]
    citation = element.find('MedlineCitation') if element.tag == 'PubmedArticle' else element.find('BookDocument')
    article = citation.find('Article') if element.tag == 'PubmedArticle' else citation
    title_node = article.find('ArticleTitle')
    title = ''.join(title_node.itertext()) if title_node is not None else ''
    no_space = lambda text: re.sub(r'\s+', '', unicodedata.normalize('NFC', text))
    if no_space(title) != no_space(record.get('title', '')):
        raise ValueError(f"PubMed title/XML mismatch: {record['id']}")
    reference, sections = [title], []
    abstracts = [(n, 'Abstract') for n in article.findall('Abstract')]
    abstracts.extend((n, 'OtherAbstract') for n in citation.findall('OtherAbstract'))
    for parent, origin in abstracts:
        parts = []
        for node in parent.findall('AbstractText'):
            text = ''.join(node.itertext())
            label, category = node.get('Label', '').strip(), node.get('NlmCategory', '').strip()
            display_label = label or (category if category != 'UNASSIGNED' else '')
            sections.append({'text': text, 'label': label, 'nlm_category': category,
                             'origin': origin, 'language': parent.get('Language', ''), 'type': parent.get('Type', '')})
            if text.strip():
                parts.append((display_label.rstrip(':') + ': ' if display_label else '') + text)
        if parts:
            if origin == 'OtherAbstract':
                language = parent.get('Language', '')
                reference.append('Other abstract' + (f' ({language})' if language else '') + ':')
            reference.extend(parts)
    stored = record.get('abstract_sections', [])
    if len(stored) != len(sections) or any(
            no_space(actual.get('text', '')) != no_space(expected['text'])
            or any(actual.get(key) != expected[key] for key in ('label', 'nlm_category', 'origin', 'language', 'type'))
            for actual, expected in zip(stored, sections)):
        raise ValueError(f"PubMed abstract sections/XML mismatch: {record['id']}")
    source_text = '\n\n'.join(p for p in reference if p.strip())
    if no_space(source_text) != no_space(record.get('text', '')):
        raise ValueError(f"PubMed abstract text/XML mismatch: {record['id']}")
    has_abstract = any(s['text'].strip() for s in sections)
    if not has_abstract and record.get('quality_status') == 'accepted':
        raise ValueError(f"PubMed accepted without abstract: {record['id']}")
    return source_text, {'pubmed_xml_verified': True, 'pubmed_abstract_sections': len(sections),
                         'pubmed_has_abstract': has_abstract}


def main():
    raw_evidence.cache_clear()
    pubmed_xml_records.cache_clear()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--review-size', type=int, default=100)
    parser.add_argument('--source', help='Verified source Parquet relocated from an older session')
    args = parser.parse_args()
    out = Path(args.out)
    manifest = read(out / 'manifest.json')
    if sha((out / 'sample.jsonl').read_bytes()) != manifest['sample_sha256']:
        raise ValueError('Sample hash mismatch')
    with (out / 'sample.jsonl').open(encoding='utf-8') as stream:
        sample = [json.loads(line) for line in stream if line.strip()]
    if len({r['id'] for r in sample}) != len(sample):
        raise ValueError('Duplicate sample IDs')
    expected = {r['id']: r['url'] for r in sample}
    source_path = Path(args.source or manifest['source'])
    if manifest.get('source_sha256'):
        digest = hashlib.sha256()
        with source_path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != manifest['source_sha256']:
            raise ValueError('Source Parquet hash mismatch')
    source = pq.read_table(source_path, filters=[('id', 'in', list(expected))]).to_pylist()
    if len(source) != len(expected) or {r['id']: r['url'] for r in source} != expected:
        raise ValueError('Sample does not match source Parquet')
    records = [read(p) for p in sorted((out / 'records').glob('*.json'))]
    actual = {r['id']: r['url'] for r in records}
    if actual != expected or len(records) != len(expected):
        raise ValueError('Run incomplete or contains unexpected IDs; wait for all checkpoints')
    cases = []
    source_views = {}
    for r in records:
        case = {'id': r['id'], 'url': r['url'], 'quality_status': r.get('quality_status'), 'flags': []}
        if 'text' in r and sha(r['text'].encode()) != r['text_sha256']:
            raise ValueError(f"Text hash mismatch: {r['id']}")
        if r.get('status') == 'extracted' and not r.get('raw_path'):
            raise ValueError(f"Missing raw evidence: {r['id']}")
        if r.get('raw_path'):
            body, raw_sha = raw_evidence(str(out / r['raw_path']))
            if raw_sha != r['raw_sha256']:
                raise ValueError(f"Raw hash mismatch: {r['id']}")
            if r.get('engine') == 'efetch':
                source_views[r['id']], details = audit_pubmed_xml(r, body)
                case.update(details)
            elif not body.startswith(b'%PDF-'):
                enc = r.get('declared_encoding') or 'utf-8'
                tree, parse_flag = raw_html_tree(body, enc)
                if parse_flag:
                    case['flags'].append(parse_flag)
                    source_views[r['id']] = '(Raw rỗng/không parse được DOM; xem checkpoint và raw gốc.)'
                else:
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
               'pubmed_xml_records_verified': sum(c.get('pubmed_xml_verified', False) for c in cases),
               'pubmed_abstract_sections_verified': sum(c.get('pubmed_abstract_sections', 0) for c in cases),
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


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
