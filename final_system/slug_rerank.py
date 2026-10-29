"""Chấm lại ứng viên tìm theo URL (slug_retrieval.py) bằng Qwen3-Reranker-4B trên Kaggle, rồi chọn lại.

Hai bước, ở thư mục gốc repo:

  # 1) Xuất cặp (câu hỏi, tiêu đề lấy từ URL) cho N ứng viên đầu mỗi câu
  .\\env\\Scripts\\python.exe slug_rerank.py export --slug-scores work/slug_top20/slug_scores.jsonl --top 50 --out work/slug_rerank/pairs.parquet

  #    -> upload pairs.parquet lên Kaggle, chạy notebooks/rerank_kaggle.ipynb (TOP_K = 100, PASSAGE_RANKS = 1)
  #    -> tải scores.parquet về work/slug_rerank/

  # 2) Xem phân bố điểm, rồi tạo bài nộp chỉ gồm tài liệu
  .\\env\\Scripts\\python.exe slug_rerank.py build --pairs work/slug_rerank/pairs.parquet --scores work/slug_rerank/scores.parquet --report
  .\\env\\Scripts\\python.exe slug_rerank.py build --pairs work/slug_rerank/pairs.parquet --scores work/slug_rerank/scores.parquet --top 20 --out work/slug_4b_top20

slug_scores.jsonl do slug_retrieval.py ghi (100 ứng viên đầu mỗi câu), nên dùng file của bất kỳ lần chạy nào.
Bài nộp không có chunk (các trang này chưa crawl, không có văn bản); gộp vào bài chính bằng "=0:0".
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402
from export_rerank_candidates import PAIR_SCHEMA  # noqa: E402
from merge_submissions import write_streaming  # noqa: E402
from slug_retrieval import slug_words  # noqa: E402

RUN = 'slug'


def site_of(url):
    return url.split('/')[2].removeprefix('www.') if url.count('/') >= 2 else ''


def export(args):
    queries = {int(r['id']): r['query'] for r in load_queries(args.queries)}
    links = pq.read_table(args.links, columns=['id', 'url'])
    urls = dict(zip(links['id'].to_pylist(), links['url'].to_pylist()))
    rows = []
    for record in storage.iter_jsonl(args.slug_scores):
        qid = int(record['query_id'])
        if qid not in queries:
            continue
        for rank, (doc_id, bm25) in enumerate(record['docs'][:args.top]):
            url = urls.get(int(doc_id), '')
            # The reranker sees the title words recovered from the URL (no diacritics) and the site name.
            text = f"{' '.join(slug_words(url))}\n({site_of(url)})"
            rows.append((qid, queries[qid], int(doc_id), RUN, 0, float(bm25), rank, 0, text))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = list(zip(*rows))
    table = pa.Table.from_arrays([pa.array(c, type=f.type) for c, f in zip(columns, PAIR_SCHEMA)], schema=PAIR_SCHEMA)
    pq.write_table(table, out, compression='zstd')
    summary = {'pairs': table.num_rows, 'top': args.top, 'file_mb': round(out.stat().st_size / 1e6, 2)}
    storage.write_json(out.with_name('pairs_manifest.json'), summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'Upload lên Kaggle: {out}')


def load_scores(paths):
    scores = {}
    for path in paths:
        if path.endswith('.parquet'):
            t = pq.read_table(path, columns=['key', 'score'])
            items = zip(t['key'].to_pylist(), t['score'].to_pylist())
        else:
            items = ((r['key'], r['score']) for r in storage.iter_jsonl(path))
        for key, score in items:
            if score is not None and math.isfinite(score):
                scores[key] = score
    return scores


def build(args):
    table = pq.read_table(args.pairs, columns=['qid', 'doc_id', 'run', 'chunk_order', 'old_score'])
    scores = load_scores(args.scores)
    ranked, scored = {}, 0
    for qid, doc_id, run, order, bm25 in zip(*(table[c].to_pylist() for c in table.column_names)):
        score = scores.get(f'{qid}:{doc_id}:{run}:{order}')
        if score is None:
            continue
        scored += 1
        ranked.setdefault(qid, []).append((score, doc_id))
    for items in ranked.values():
        items.sort(key=lambda item: (-item[0], item[1]))
    emit(f'Cặp có điểm: {scored}/{table.num_rows}')
    if not scored:
        raise ValueError('Không cặp nào có điểm: kiểm tra --scores có đúng của --pairs này.')
    if args.report:
        emit('\nĐiểm 4B của tài liệu hạng N (trung vị qua các câu):')
        for n in (1, 3, 5, 10, 20, 30, 50):
            values = [r[n - 1][0] for r in ranked.values() if len(r) >= n]
            if values:
                emit(f'  hạng {n:3d}: {np.median(values):.3f}')
        emit('\nSố tài liệu mỗi câu nếu cắt theo ngưỡng điểm:')
        for floor in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1):
            counts = [sum(1 for s, _d in r if s >= floor) for r in ranked.values()]
            emit(f'  >= {floor:.1f}: trung bình {np.mean(counts):5.1f}, câu có 0: {sum(1 for c in counts if c == 0)}')
        return
    query_ids = [int(r['id']) for r in load_queries(args.queries)]
    rows = []
    for qid in query_ids:
        chosen = [d for s, d in ranked.get(qid, []) if s >= args.min_score][:args.top]
        rows.append({'id': qid, 'relevant_docs': [int(d) for d in chosen], 'relevant_chunks': []})
    problems = schema.validate_submission_shape(rows, query_ids)
    if problems:
        raise ValueError('; '.join(problems[:5]))
    _json, zip_path = write_streaming(rows, args.out, lzma=True)
    counts = [len(r['relevant_docs']) for r in rows]
    summary = {'top': args.top, 'min_score': args.min_score, 'docs_mean': round(float(np.mean(counts)), 2),
               'queries_without_docs': sum(1 for c in counts if not c)}
    storage.write_json(Path(args.out) / 'slug_rerank_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nNộp file: {zip_path}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('export')
    e.add_argument('--slug-scores', required=True)
    e.add_argument('--top', type=int, default=50)
    e.add_argument('--out', default='work/slug_rerank/pairs.parquet')
    e.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    e.add_argument('--queries', default='data/query.parquet')
    b = sub.add_parser('build')
    b.add_argument('--pairs', required=True)
    b.add_argument('--scores', nargs='+', required=True)
    b.add_argument('--top', type=int, default=20)
    b.add_argument('--min-score', type=float, default=0.0)
    b.add_argument('--out')
    b.add_argument('--report', action='store_true')
    b.add_argument('--queries', default='data/query.parquet')
    args = parser.parse_args()
    if args.command == 'export':
        export(args)
    else:
        if not args.report and not args.out:
            parser.error('Cần --out (hoặc --report).')
        build(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
