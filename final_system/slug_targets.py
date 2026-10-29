"""Lập danh sách trang CHƯA CRAWL cần lấy qua web.archive.org: các ứng viên tìm theo URL mà 4B chấm cao.

Đọc pairs.parquet + scores.parquet của bước chấm slug trên Kaggle (slug_rerank.py), lấy mỗi câu --top trang
điểm cao nhất có điểm >= --min-score, gộp lại (bỏ trùng giữa các câu) rồi ghi (id, url) ra parquet để
upload lên Kaggle cho notebook archive_fetch_kaggle.ipynb.

Ví dụ (ở thư mục gốc repo):
  .\\env\\Scripts\\python.exe slug_targets.py --pairs work/slug_rerank300/pairs.parquet --scores work/slug_rerank300/scores.parquet --report
  .\\env\\Scripts\\python.exe slug_targets.py --pairs work/slug_rerank300/pairs.parquet --scores work/slug_rerank300/scores.parquet --top 40 --min-score 0.05 --out work/archive/targets.parquet

  # Lô sau: bỏ các trang lô trước đã thử và các trang đã có trong corpus của run khác (chia 2 phần: part1/, part2/)
  .\\env\\Scripts\\python.exe slug_targets.py --pairs work/slug_rerank300/pairs.parquet --scores work/slug_rerank300/scores.parquet --exclude work/archive/targets.parquet work/run_h/corpus/corpus.parquet --top 100 --min-score 0.05 --out work/archive2/targets.parquet
"""
import argparse
import collections
import glob
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common.console import emit  # noqa: E402
from slug_rerank import load_scores  # noqa: E402


def ranked_by_query(pairs_path, score_paths):
    table = pq.read_table(pairs_path, columns=['qid', 'doc_id', 'run', 'chunk_order'])
    scores = load_scores(score_paths)
    ranked = collections.defaultdict(list)
    for qid, doc_id, run, order in zip(*(table[c].to_pylist() for c in table.column_names)):
        score = scores.get(f'{qid}:{doc_id}:{run}:{order}')
        if score is not None:
            ranked[qid].append((score, doc_id))
    for items in ranked.values():
        items.sort(key=lambda item: (-item[0], item[1]))
    return ranked


def pick(ranked, top, min_score, exclude=frozenset()):
    """Pages among the first `top` of each query with score >= min_score, minus `exclude`."""
    return {d for items in ranked.values() for s, d in items[:top] if s >= min_score and d not in exclude}


def excluded_ids(paths):
    ids = set()
    for path in paths:
        found = sorted(glob.glob(path, recursive=True)) or [path]
        for item in found:
            ids.update(pq.read_table(item, columns=['id'])['id'].to_pylist())
        emit(f'Bỏ qua id có trong {path}: {len(ids):,} id (cộng dồn)')
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pairs', required=True)
    parser.add_argument('--scores', nargs='+', required=True)
    parser.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--top', type=int, default=40)
    parser.add_argument('--min-score', type=float, default=0.05)
    parser.add_argument('--out')
    parser.add_argument('--exclude', nargs='*', default=[],
                        help='File parquet có cột id (targets.parquet lô trước, corpus.parquet của run, file crawl...): '
                             'bỏ các trang này. Có thể dùng dấu *.')
    parser.add_argument('--parts', type=int, default=1,
                        help='Chia danh sách thành N phần (khoảng id liền nhau), mỗi phần một thư mục partK/ chứa '
                             'targets.parquet, để chạy N notebook song song.')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    if not args.report and not args.out:
        parser.error('Cần --out (hoặc --report).')

    ranked = ranked_by_query(args.pairs, args.scores)
    emit(f'Câu có điểm: {len(ranked)}')
    exclude = excluded_ids(args.exclude)
    if args.report:
        emit('\ntop  ngưỡng   số trang cần tải (bỏ trùng' + (', đã trừ --exclude)' if exclude else ')'))
        for top in (20, 40, 60, 100, 150, 200, 300):
            for floor in (0.0, 0.05, 0.1, 0.2, 0.3):
                emit(f'{top:4d}  {floor:5.2f}   {len(pick(ranked, top, floor, exclude)):,}')
        return
    wanted = pick(ranked, args.top, args.min_score, exclude)
    links = pq.read_table(args.links, columns=['id', 'url'])
    rows = [(i, u) for i, u in zip(links['id'].to_pylist(), links['url'].to_pylist()) if i in wanted]
    rows.sort()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    parts = max(1, args.parts)
    size = -(-len(rows) // parts) if rows else 0
    written = []
    for index in range(parts):
        piece = rows[index * size:(index + 1) * size]
        if not piece and index:
            continue
        # Each part keeps the file name targets.parquet (what the notebook looks for), in its own folder.
        target = out if parts == 1 else out.parent / f'part{index + 1}' / out.name
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({'id': pa.array([r[0] for r in piece], pa.int64()),
                                 'url': pa.array([r[1] for r in piece], pa.string())}), target)
        written.append(f'{target} ({len(piece):,} trang)')
    sites = collections.Counter(u.split('/')[2].removeprefix('www.') for _i, u in rows)
    summary = {'pages': len(rows), 'top': args.top, 'min_score': args.min_score, 'excluded_from': args.exclude,
               'sites': dict(sites.most_common(15))}
    (out.with_name('targets_manifest.json')).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                                        encoding='utf-8')
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit('\nUpload lên Kaggle (mỗi file một notebook):\n  ' + '\n  '.join(written))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
