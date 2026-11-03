"""Kiểm tra dữ liệu đã crawl có nằm hết trong các run đang dùng cho bài nộp chưa.

Lấy hợp các id trong corpus/corpus.parquet của các run (mặc định 14 run của bài cuối), rồi so với mọi id trong
các file crawl (ids_*.parquet, *.parquet có cột id). In số id đã crawl mà CHƯA có trong run nào, chia theo
ngôn ngữ (khoảng id) và tên miền, để biết còn lô nào chưa đưa vào pipeline.

Ví dụ (ở thư mục gốc repo):
  .\\env\\Scripts\\python.exe coverage_check.py --crawl "data/**/ids_*.parquet"
  .\\env\\Scripts\\python.exe coverage_check.py --crawl "data/**/*.parquet" "D:/crawl/**/*.parquet" --links data/links_corpus_vi_en_zh.parquet
"""
import argparse
import collections
import glob
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pyarrow.parquet as pq

DEFAULT_RUNS = ('run_vi', 'run_b', 'run_c', 'run_d', 'run_e', 'run_f', 'run_g', 'run_zh_a', 'run_zh_b', 'run_zh_c',
                'run_h', 'run_archive', 'run_archive2', 'run_archive3')


def lang_of(doc_id):
    return 'vi' if doc_id < 766442 else ('zh' if doc_id <= 4420561 else 'pubmed')


def main():
    sys.argv = [sys.argv[0]] + [re.sub(r'^[-\u2010-\u2015\u2212]+(?=[A-Za-z]{2})', '--', arg)
                                for arg in sys.argv[1:]]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', nargs='*', default=[])
    parser.add_argument('--crawl', nargs='+', required=True, help='Mẫu đường dẫn file crawl (.parquet có cột id).')
    parser.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet',
                        help='Chỉ tính id có trong danh sách chính thức (để trống = tính hết).')
    parser.add_argument('--with-text', action='store_true',
                        help='Chỉ tính id có văn bản (cột text/content khác rỗng) trong file crawl.')
    args = parser.parse_args()
    runs = args.runs or [f'work/{name}' for name in DEFAULT_RUNS]
    in_runs = set()
    for run in runs:
        path = Path(run) / 'corpus' / 'corpus.parquet'
        if path.exists():
            in_runs.update(int(x) for x in pq.read_table(path, columns=['id'])['id'].to_pylist())
        else:
            print(f'(bỏ qua {run}: không có corpus)')
    print(f'Id trong {len(runs)} run: {len(in_runs):,}')
    official = None
    if args.links and Path(args.links).exists():
        official = set(pq.read_table(args.links, columns=['id'])['id'].to_pylist())
    crawled, url_of = set(), {}
    files = sorted({p for pattern in args.crawl for p in glob.glob(pattern, recursive=True)})
    for path in files:
        try:
            schema = pq.read_schema(path)
        except Exception:  # noqa: BLE001 - not a parquet we can read
            continue
        if 'id' not in schema.names:
            continue
        columns = ['id'] + [c for c in ('url',) if c in schema.names]
        text_col = next((c for c in ('text', 'content', 'body') if c in schema.names), None)
        if args.with_text and text_col:
            columns.append(text_col)
        table = pq.read_table(path, columns=columns)
        ids = table['id'].to_pylist()
        urls = table['url'].to_pylist() if 'url' in table.column_names else [None] * len(ids)
        texts = table[text_col].to_pylist() if (args.with_text and text_col) else [True] * len(ids)
        for doc_id, url, text in zip(ids, urls, texts):
            if doc_id is None or not text:
                continue
            doc_id = int(doc_id)
            if official is not None and doc_id not in official:
                continue
            crawled.add(doc_id)
            if url:
                url_of[doc_id] = url
    print(f'File crawl đọc được: {len(files)} | id đã crawl (thuộc danh sách chính thức): {len(crawled):,}')
    missing = crawled - in_runs
    print(f'Đã crawl nhưng CHƯA có trong run nào: {len(missing):,} ({100 * len(missing) / max(1, len(crawled)):.1f}%)')
    by_lang = collections.Counter(lang_of(d) for d in missing)
    print('  theo ngôn ngữ:', dict(by_lang))
    by_site = collections.Counter(urlsplit(url_of[d]).netloc.lower().removeprefix('www.') for d in missing if d in url_of)
    for site, count in by_site.most_common(15):
        print(f'  {count:8,}  {site}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
