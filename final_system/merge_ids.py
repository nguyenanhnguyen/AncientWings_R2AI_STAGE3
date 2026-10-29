"""Gộp các file ids_*_synced.parquet thành một file, mỗi id một dòng. Có thể bỏ các dải id đã chạy rồi và các trang yếu.

Cách dùng (chạy ở thư mục gốc repo):
    python merge_ids.py "data/crawl/ids_*_synced.parquet" data/crawl/all.parquet
    python merge_ids.py "data/crawl_d/ids_*_synced.parquet" data/crawl_d/all.parquet --exclude 504810-522469 500000 --exclude-site laodong.vn

--exclude nhận dải "đầu-cuối" (tính cả hai đầu) hoặc một id lẻ. --exclude-site bỏ mọi tài liệu của trang đó (kể cả tên miền con).
--keep-in chỉ giữ các id có trong một file links (vd. kho rút gọn data/links_corpus_vi_en_zh.parquet).
"""
import argparse
import collections
import glob
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


def parse_range(text):
    low, _, high = text.partition('-')
    low, high = int(low), int(high or low)
    if low > high:
        raise argparse.ArgumentTypeError(f'Dải id sai: {text}')
    return low, high


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('pattern', help='Mẫu tên file, ví dụ "data/crawl/ids_*_synced.parquet" (để trong ngoặc kép).')
    parser.add_argument('out', help='File parquet kết quả.')
    parser.add_argument('--exclude', nargs='+', type=parse_range, default=[], metavar='DẢI',
                        help='Dải id cần bỏ, dạng 504810-522469 hoặc một id lẻ.')
    parser.add_argument('--exclude-site', nargs='+', default=[], metavar='TRANG',
                        help='Trang cần bỏ, ví dụ laodong.vn.')
    parser.add_argument('--keep-in', metavar='LINKS',
                        help='Chỉ giữ id có trong file links này, vd. data/links_corpus_vi_en_zh.parquet.')
    args = parser.parse_args()

    files = sorted(glob.glob(args.pattern))
    if not files:
        sys.exit(f'Không thấy file nào khớp: {args.pattern}')
    table = pa.concat_tables([pq.read_table(f) for f in files], promote_options='default')
    rows_in = table.num_rows

    seen, keep = set(), []
    for row, doc_id in enumerate(table['id'].to_pylist()):
        if doc_id not in seen:
            seen.add(doc_id)
            keep.append(row)
    duplicates = rows_in - len(keep)
    table = table.take(pa.array(keep))

    ids = table['id']
    drop_range = pa.array([False] * table.num_rows)
    for low, high in args.exclude:
        drop_range = pc.or_(drop_range, pc.and_(pc.greater_equal(ids, low), pc.less_equal(ids, high)))
    sites = [site.lower().removeprefix('www.') for site in args.exclude_site]
    domains = [(d or '').lower().removeprefix('www.') for d in table['domain'].to_pylist()]
    drop_site = pa.array([any(d == s or d.endswith('.' + s) for s in sites) for d in domains])
    by_range = pc.sum(pc.cast(drop_range, pa.int64())).as_py() or 0
    by_site = pc.sum(pc.cast(pc.and_(drop_site, pc.invert(drop_range)), pa.int64())).as_py() or 0
    table = table.filter(pc.invert(pc.or_(drop_range, drop_site))).sort_by('id')
    by_keep = 0
    if args.keep_in:
        allowed = pq.read_table(args.keep_in, columns=['id'])['id']
        inside = pc.is_in(table['id'], value_set=allowed)
        by_keep = table.num_rows - (pc.sum(pc.cast(inside, pa.int64())).as_py() or 0)
        table = table.filter(inside)
    if table.num_rows == 0:
        sys.exit('Không còn tài liệu nào sau khi lọc.')
    pq.write_table(table, args.out, compression='zstd')

    print(f'{len(files)} file, {rows_in} dòng, bỏ {duplicates} dòng trùng id, '
          f'bỏ {by_range} dòng thuộc dải đã chạy, bỏ {by_site} dòng của trang bị loại'
          + (f', bỏ {by_keep} dòng không có trong {args.keep_in}' if args.keep_in else '') + f' -> {args.out}')
    counts = collections.Counter(table['domain'].to_pylist())
    print('Còn lại theo trang: ' + ', '.join(f'{site} {count}' for site, count in counts.most_common()))
    print(f'Dùng: --limit {table.num_rows}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
