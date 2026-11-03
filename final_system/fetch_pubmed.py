"""Lấy tiêu đề + tóm tắt các bài PubMed trong kho qua NCBI E-utilities (EFetch), không cần crawl từng trang.

Mỗi lần gọi lấy tới 200 bài. Mặc định 3 lần gọi/giây (giới hạn của NCBI khi không có API key); có
--api-key (tạo miễn phí trong tài khoản NCBI) thì 10 lần/giây. Kết quả ghi theo đúng định dạng file
crawl (ids_<đầu>_<cuối>_synced.parquet, mỗi file --per-file id), dùng thẳng với merge_ids.py và
pipeline. Chạy lại an toàn: file đã có thì bỏ qua. Bài không có tóm tắt được giữ với text = tiêu đề.

Ví dụ (PowerShell, ở thư mục gốc repo):

  # Lô thử: 1 trong 4 bài (khoảng 60 nghìn, trải đều các năm)
  .\\env\\Scripts\\python.exe fetch_pubmed.py --links data/links_corpus_vi_en_zh.parquet --out data/crawl_en_test --every 4

  # Toàn bộ khoảng 240 nghìn bài PubMed của kho
  .\\env\\Scripts\\python.exe fetch_pubmed.py --links data/links_corpus_vi_en_zh.parquet --out data/crawl_en --email ban@example.com
"""
import argparse
import hashlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

EFETCH = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
DOMAIN = 'pubmed.ncbi.nlm.nih.gov'
SCHEMA = pa.schema([
    ('id', pa.int64()), ('url', pa.string()), ('final_url', pa.string()), ('title', pa.string()),
    ('text', pa.string()), ('domain', pa.string()), ('extractor', pa.string()), ('lang', pa.string()),
    ('status', pa.string()), ('quality_flags', pa.list_(pa.string())), ('published_at', pa.string()),
    ('text_sha256', pa.string()),
])
_SPACE = re.compile(r'\s+')


def clean(element):
    return _SPACE.sub(' ', ''.join(element.itertext())).strip() if element is not None else ''


def abstract_text(abstract):
    """Structured abstracts keep their section labels the way the PubMed page shows them."""
    parts = []
    for node in abstract.findall('AbstractText') if abstract is not None else []:
        body = clean(node)
        if not body:
            continue
        label = (node.get('Label') or '').strip()
        parts.append(f'{label.capitalize()}: {body}' if label and label.upper() != 'UNLABELLED' else body)
    return '\n'.join(parts)


def parse(xml_bytes):
    """-> {pmid: (title, abstract, year)} for journal articles and book chapters."""
    root = ET.fromstring(xml_bytes)
    found = {}
    for article in root:
        if article.tag == 'PubmedArticle':
            citation = article.find('MedlineCitation')
            pmid = clean(citation.find('PMID'))
            body = citation.find('Article')
            title = clean(body.find('ArticleTitle'))
            abstract = abstract_text(body.find('Abstract'))
            if not abstract:
                for other in citation.findall('OtherAbstract'):
                    if (other.get('Language') or 'eng') == 'eng':
                        abstract = abstract_text(other)
                        break
            year = clean(body.find('Journal/JournalIssue/PubDate/Year')) or clean(
                body.find('Journal/JournalIssue/PubDate/MedlineDate'))[:4]
        elif article.tag == 'PubmedBookArticle':
            document = article.find('BookDocument')
            pmid = clean(document.find('PMID'))
            title = clean(document.find('ArticleTitle')) or clean(document.find('Book/BookTitle'))
            abstract = abstract_text(document.find('Abstract'))
            year = clean(document.find('Book/PubDate/Year'))
        else:
            continue
        if pmid:
            found[pmid] = (title, abstract, year or None)
    return found


def efetch(pmids, args):
    data = {'db': 'pubmed', 'id': ','.join(pmids), 'retmode': 'xml', 'tool': 'ancientwings_r2ai'}
    if args.email:
        data['email'] = args.email
    if args.api_key:
        data['api_key'] = args.api_key
    body = urllib.parse.urlencode(data).encode()
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(EFETCH, data=body), timeout=120) as response:
                return parse(response.read())
        except (urllib.error.URLError, TimeoutError, ET.ParseError, ConnectionError) as error:
            code = getattr(error, 'code', None)
            if code is not None and code not in (429, 500, 502, 503, 504):
                raise
            wait = min(60, 2 ** attempt * 3)
            print(f'  lỗi {code or type(error).__name__}, thử lại sau {wait}s', flush=True)
            time.sleep(wait)
    raise RuntimeError(f'EFetch thất bại sau 6 lần, PMID đầu {pmids[0]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--out', default='data/crawl_en')
    parser.add_argument('--per-file', type=int, default=20000)
    parser.add_argument('--batch', type=int, default=200)
    parser.add_argument('--limit', type=int, default=0, help='Chỉ lấy N bài đầu (thử nhanh). 0 = tất cả.')
    parser.add_argument('--every', type=int, default=1,
                        help='Lấy 1 trong mỗi K bài theo thứ tự id (mẫu trải đều các năm cho lô thử). 1 = tất cả.')
    parser.add_argument('--from-id', type=int, default=0)
    parser.add_argument('--to-id', type=int, default=0)
    parser.add_argument('--email', default='')
    parser.add_argument('--api-key', default='')
    args = parser.parse_args()

    table = pq.read_table(args.links, columns=['id', 'url'])
    table = table.filter(pc.match_substring(table['url'], DOMAIN))
    if args.from_id:
        table = table.filter(pc.greater_equal(table['id'], args.from_id))
    if args.to_id:
        table = table.filter(pc.less_equal(table['id'], args.to_id))
    table = table.sort_by('id')
    rows = list(zip(table['id'].to_pylist(), table['url'].to_pylist()))[::max(1, args.every)]
    if args.limit:
        rows = rows[:args.limit]
    items = []
    for doc_id, url in rows:
        match = re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)', url)
        if match:
            items.append((doc_id, url, match.group(1)))
    print(f'{len(items):,} bài PubMed cần lấy', flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    interval = 1 / (10 if args.api_key else 3)
    last_call = 0.0
    totals = {'docs': 0, 'no_abstract': 0, 'missing': 0}
    started = time.time()
    for start in range(0, len(items), args.per_file):
        group = items[start:start + args.per_file]
        path = out / f'ids_{group[0][0]}_{group[-1][0]}_synced.parquet'
        if path.exists():
            print(f'Đã có {path.name}, bỏ qua', flush=True)
            continue
        records = []
        for offset in range(0, len(group), args.batch):
            batch = group[offset:offset + args.batch]
            wait = interval - (time.time() - last_call)
            if wait > 0:
                time.sleep(wait)
            last_call = time.time()
            found = efetch([pmid for _id, _url, pmid in batch], args)
            for doc_id, url, pmid in batch:
                if pmid not in found:
                    totals['missing'] += 1
                    continue
                title, abstract, year = found[pmid]
                text = abstract or title
                if not text:
                    totals['missing'] += 1
                    continue
                flags = [] if abstract else ['no_abstract']
                totals['no_abstract'] += not abstract
                records.append({'id': doc_id, 'url': url, 'final_url': url, 'title': title, 'text': text,
                                'domain': DOMAIN, 'extractor': 'efetch', 'lang': 'en', 'status': 'ok',
                                'quality_flags': flags, 'published_at': year,
                                'text_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()})
        totals['docs'] += len(records)
        temporary = path.with_suffix('.tmp')
        pq.write_table(pa.Table.from_pylist(records, schema=SCHEMA), temporary, compression='zstd')
        temporary.replace(path)
        done = start + len(group)
        rate = done / max(1e-9, time.time() - started)
        print(f'{path.name}: {len(records):,}/{len(group):,} bài | tổng {done:,}/{len(items):,} | '
              f'còn ~{(len(items) - done) / max(rate, 1e-9) / 60:.0f} phút', flush=True)
    print(f"Xong: {totals['docs']:,} bài, {totals['no_abstract']:,} bài chỉ có tiêu đề, "
          f"{totals['missing']:,} PMID không lấy được.", flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
