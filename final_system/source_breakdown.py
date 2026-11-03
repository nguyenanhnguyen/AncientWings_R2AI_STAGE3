"""Bài nộp lấy tài liệu từ những lô (run) nào: số tài liệu và chunk mỗi câu theo từng nguồn.

Mỗi id được gán cho run đầu tiên (theo thứ tự --runs) có id đó trong corpus/corpus.parquet; id không có ở run nào
thì xét các bài nộp --extra (vd. lo_004), còn lại ghi "khác". Chỉ đọc cột id nên chạy nhanh.

--per-query FILE.csv ghi thêm bảng chi tiết: mỗi dòng (câu, lô, số tài liệu, số chunk), để xem từng câu lấy tài
liệu từ những lô nào.

Ví dụ (ở thư mục gốc repo; không ghi --runs thì dùng 14 run của đội và lo_004):
  .\\env\\Scripts\\python.exe source_breakdown.py work/prf/f2_x50_rx_small/submission.zip
  .\\env\\Scripts\\python.exe source_breakdown.py work/prf/f2_x50_rx_small/submission.zip --per-query work/stats/per_query_source.csv
"""
import argparse
import csv
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from merge_submissions import read_rows  # noqa: E402

DEFAULT_RUNS = ('run_vi', 'run_b', 'run_c', 'run_d', 'run_e', 'run_f', 'run_g', 'run_zh_a', 'run_zh_b', 'run_zh_c',
                'run_h', 'run_archive', 'run_archive2', 'run_archive3')


def main():
    # Chấp nhận cờ bị dán sai gạch (---out, —out, –out, -out) do lỗi khi copy lệnh: đưa về --out.
    sys.argv = [sys.argv[0]] + [re.sub(r'^[-‐-―−]+(?=[A-Za-z]{2})', '--', arg)
                                for arg in sys.argv[1:]]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('submission')
    parser.add_argument('--runs', nargs='*', default=[])
    parser.add_argument('--extra', nargs='*', default=None, help='Bài nộp không còn run (mặc định lo_004/submission.zip).')
    parser.add_argument('--per-query', default='', help='Ghi bảng (câu, lô, tài liệu, chunk) ra file CSV này.')
    args = parser.parse_args()
    runs = args.runs or [f'work/{name}' for name in DEFAULT_RUNS if Path(f'work/{name}').exists()]
    extras = ['lo_004/submission.zip'] if args.extra is None else args.extra
    owner = {}
    for run in runs:
        path = Path(run) / 'corpus' / 'corpus.parquet'
        if not path.exists():
            print(f'(bỏ qua {run}: không có corpus/corpus.parquet)')
            continue
        for doc_id in pq.read_table(path, columns=['id'])['id'].to_pylist():
            owner.setdefault(int(doc_id), Path(run).name)
    for extra in extras:
        if Path(extra).exists():
            name = Path(extra).parent.name or Path(extra).stem
            for row in read_rows(extra):
                for doc_id in row['relevant_docs']:
                    owner.setdefault(int(doc_id), name)
    rows = read_rows(args.submission)
    n = max(1, len(rows))
    docs, chunks, distinct, table = {}, {}, {}, []
    queries_with = {}
    for row in rows:
        per_docs, per_chunks = {}, {}
        for doc_id in row['relevant_docs']:
            source = owner.get(int(doc_id), 'khác')
            docs[source] = docs.get(source, 0) + 1
            distinct.setdefault(source, set()).add(int(doc_id))
            per_docs[source] = per_docs.get(source, 0) + 1
        for chunk in row['relevant_chunks']:
            source = owner.get(int(chunk['doc_id']), 'khác')
            chunks[source] = chunks.get(source, 0) + 1
            per_chunks[source] = per_chunks.get(source, 0) + 1
        for source in sorted(set(per_docs) | set(per_chunks)):
            table.append((int(row['id']), source, per_docs.get(source, 0), per_chunks.get(source, 0)))
            if per_docs.get(source):
                queries_with[source] = queries_with.get(source, 0) + 1
    total_docs, total_chunks = max(1, sum(docs.values())), max(1, sum(chunks.values()))
    print(f"{'nguồn':<14} {'tài liệu/câu':>12} {'% tài liệu':>10} {'tài liệu khác nhau':>18} {'chunk/câu':>10} "
          f"{'% chunk':>8} {'số câu có':>10}")
    for source in sorted(docs, key=lambda s: -docs[s]):
        print(f'{source:<14} {docs[source] / n:12.1f} {100 * docs[source] / total_docs:9.1f}% '
              f'{len(distinct[source]):18,} {chunks.get(source, 0) / n:10.1f} {100 * chunks.get(source, 0) / total_chunks:7.1f}% '
              f'{queries_with.get(source, 0):10,}')
    print(f"{'tổng':<14} {sum(docs.values()) / n:12.1f} {'':>10} {len(set().union(*distinct.values())) if distinct else 0:18,} "
          f'{sum(chunks.values()) / n:10.1f}')
    if args.per_query:
        out = Path(args.per_query)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, 'w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerow(['query_id', 'source', 'docs', 'chunks'])
            writer.writerows(table)
        print(f'\nĐã ghi {len(table):,} dòng (câu × lô) vào {out}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
