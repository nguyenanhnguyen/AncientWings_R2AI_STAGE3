"""Bước A3: tạo bài nộp từ điểm rerank mới của Kaggle. Không cần GPU.

Đặt file này ở thư mục gốc repo (cạnh make_submission.py). Điểm tài liệu = điểm cao nhất trong các
đoạn của nó (điểm mới, hoặc trộn với điểm cũ bằng --mix). Mỗi câu lấy --docs tài liệu đứng đầu (hoặc
theo ngưỡng --min-score / --ratio), và --chunk-docs tài liệu đầu được nộp chunk: cửa sổ dài tới
--window-tokens token quanh đoạn điểm cao nhất, cắt nguyên văn từ corpus của đúng run chứa tài liệu.

Ví dụ (PowerShell, ở thư mục gốc repo; --runs đúng danh sách đã dùng ở bước xuất):

  # Xem trước điểm mới phân bố thế nào, chưa ghi file
  .\\env\\Scripts\\python.exe build_rerank_submission.py --pairs work/rerank/pairs.parquet --scores work/rerank/scores.parquet --runs work/run_04 work/run_vi ... --report

  # Tạo bài nộp: 60 tài liệu, 40 tài liệu đầu có chunk dài
  .\\env\\Scripts\\python.exe build_rerank_submission.py --pairs work/rerank/pairs.parquet --scores work/rerank/scores.parquet --runs work/run_04 work/run_vi ... --docs 60 --chunk-docs 40 --out work/rerank/sub_d60_c40

  # Nhiều lượt chấm: ghi nhiều file sau --pairs và --scores (vd. pool4 + lượt chấm thêm run mới)
  .\\env\\Scripts\\python.exe build_rerank_submission.py --pairs work/rerank_pool4/pairs.parquet work/rerank_h_arch/pairs.parquet --scores work/rerank_pool4/scores.parquet work/rerank_h_arch/scores.parquet --runs ... --out ...
"""
import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402
from make_submission import chunks_for_document  # noqa: E402
from merge_submissions import write_streaming  # noqa: E402


def pair_key(qid, doc_id, run, order):
    return f'{int(qid)}:{int(doc_id)}:{run}:{int(order)}'


def read_pairs(paths, columns):
    """One or more pairs.parquet files as one table. A pair listed twice is harmless (best score wins)."""
    tables = [pq.read_table(path, columns=columns) for path in paths]
    tables = [table.cast(tables[0].schema) for table in tables]
    return pa.concat_tables(tables) if len(tables) > 1 else tables[0]


def load_scores(patterns):
    scores = {}
    for pattern in patterns:
        files = sorted(glob.glob(pattern)) or [pattern]
        for path in files:
            path = Path(path)
            if path.suffix == '.parquet':
                table = pq.read_table(path, columns=['key', 'score'])
                rows = zip(table['key'].to_pylist(), table['score'].to_pylist())
            else:
                rows = ((r['key'], r['score']) for r in storage.iter_jsonl(path))
            for key, score in rows:
                if score is not None and np.isfinite(score):
                    scores[key] = max(score, scores.get(key, float('-inf')))
    return scores


def rank_documents(pairs, scores, mix):
    """{qid: [(score, doc_id, run, chunk_order) best first]} — one entry per document, its best passage."""
    best, scored = {}, 0
    for qid, doc_id, run, order, old in pairs:
        new = scores.get(pair_key(qid, doc_id, run, order))
        if new is None:
            continue
        scored += 1
        # Pairs from a submission without a run (export_pool_pairs --extra) have no old score.
        value = new if old is None or not np.isfinite(old) else mix * new + (1 - mix) * old
        docs = best.setdefault(qid, {})
        if doc_id not in docs or value > docs[doc_id][0]:
            docs[doc_id] = (value, doc_id, run, order)
    ranked = {qid: sorted(docs.values(), key=lambda item: (-item[0], item[1])) for qid, docs in best.items()}
    return ranked, scored


def choose_docs(ranked, args):
    if not ranked:
        return []
    if args.min_score or args.ratio:
        floor = max(args.min_score, args.ratio * ranked[0][0])
        kept = [item for item in ranked if item[0] >= floor]
        if len(kept) < args.min_docs:
            kept = ranked[:args.min_docs]
        return kept[:args.max_docs] if args.max_docs else kept
    return ranked[:args.docs]


def load_run_texts(run, doc_ids):
    """Spans and normalised texts for the given documents of one run, as make_submission reads them."""
    wanted = pa.array(sorted(doc_ids), type=pa.int64())
    table = pq.read_table(Path(run) / 'chunks' / 'chunks.parquet',
                          columns=['doc_id', 'chunk_order', 'char_start', 'char_end'])
    table = table.filter(pc.is_in(table['doc_id'], value_set=wanted))
    spans = {}
    for doc_id, order, start, end in zip(*(table[c].to_pylist() for c in table.column_names)):
        spans.setdefault(doc_id, []).append((order, start, end))
    for doc_id, rows in spans.items():
        rows.sort()
        if [row[0] for row in rows] != list(range(len(rows))):
            raise ValueError(f'{run}: tài liệu {doc_id} có thứ tự chunk không liên tục.')
        spans[doc_id] = [(start, end) for _order, start, end in rows]
    corpus = pq.read_table(Path(run) / 'corpus' / 'corpus.parquet', columns=['id', 'text'])
    corpus = corpus.filter(pc.is_in(corpus['id'], value_set=wanted))
    texts = {doc_id: schema.document_text({'text': text})
             for doc_id, text in zip(corpus['id'].to_pylist(), corpus['text'].to_pylist())}
    return spans, texts


def report(ranked_by_query, pairs_count, scored):
    emit(f'Cặp đã có điểm mới: {scored}/{pairs_count} ({100 * scored / max(1, pairs_count):.1f}%)')
    lists = list(ranked_by_query.values())
    emit('\nĐiểm của tài liệu hạng N (trung vị qua các câu):')
    for n in (1, 5, 10, 20, 30, 40, 60, 80, 100):
        values = [r[n - 1][0] for r in lists if len(r) >= n]
        if values:
            emit(f'  hạng {n:3d}: {np.median(values):.3f}  (có ở {len(values)} câu)')
    emit('\nSố tài liệu mỗi câu nếu cắt theo ngưỡng điểm:')
    for floor in (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1):
        counts = [sum(1 for item in r if item[0] >= floor) for r in lists]
        emit(f'  >= {floor:.1f}: trung bình {np.mean(counts):6.1f}, trung vị {np.median(counts):5.0f}, '
             f'câu có 0: {sum(1 for c in counts if c == 0)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pairs', nargs='+', required=True,
                        help='Một hay nhiều pairs.parquet (mỗi lượt chấm trên Kaggle một file).')
    parser.add_argument('--scores', nargs='+', required=True, help='scores.parquet hoặc *.jsonl của Kaggle.')
    parser.add_argument('--runs', nargs='+', required=True)
    parser.add_argument('--out')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--mix', type=float, default=1.0, help='1 = chỉ điểm mới; 0.7 = 70%% mới + 30%% cũ.')
    parser.add_argument('--docs', type=int, default=60)
    parser.add_argument('--min-score', type=float, default=0.0)
    parser.add_argument('--ratio', type=float, default=0.0)
    parser.add_argument('--min-docs', type=int, default=10)
    parser.add_argument('--max-docs', type=int, default=0)
    parser.add_argument('--chunk-docs', type=int, default=40)
    parser.add_argument('--window-tokens', type=int, default=1000)
    parser.add_argument('--report', action='store_true')
    parser.add_argument('--lzma', action='store_true', help='Nén LZMA (file nhỏ hơn khoảng 38%%).')
    parser.add_argument('--text-runs', nargs='*', default=[],
                        help='Nguồn lấy từ bài nộp (export_pool_pairs --extra): chunk nộp đúng đoạn đã chấm, '
                             'không cắt cửa sổ từ run.')
    args = parser.parse_args()
    if not args.report and not args.out:
        parser.error('Cần --out (hoặc dùng --report).')
    if not 0 <= args.mix <= 1:
        parser.error('--mix trong khoảng 0..1')

    runs = {Path(run).name: run for run in args.runs}
    table = read_pairs(args.pairs, ['qid', 'doc_id', 'run', 'chunk_order', 'old_score'])
    pairs = list(zip(*(table[c].to_pylist() for c in table.column_names)))
    unknown = sorted({p[2] for p in pairs} - set(runs) - set(args.text_runs))
    if unknown:
        parser.error(f'pairs.parquet có run không nằm trong --runs: {unknown}')
    scores = load_scores(args.scores)
    ranked, scored = rank_documents(pairs, scores, args.mix)
    if args.report:
        report(ranked, len(pairs), scored)
        return
    if not scored:
        raise ValueError('Không cặp nào có điểm mới: kiểm tra file --scores có đúng của pairs.parquet này.')

    query_ids = [row['id'] for row in load_queries(args.queries)]
    plan = {qid: choose_docs(ranked.get(qid, []), args) for qid in query_ids}
    needed = {}
    text_runs = set(args.text_runs)
    for chosen in plan.values():
        for _score, doc_id, run, _order in chosen[:args.chunk_docs]:
            if run not in text_runs:
                needed.setdefault(run, set()).add(doc_id)
    verbatim = {}
    if text_runs:
        extra = read_pairs(args.pairs, ['qid', 'doc_id', 'run', 'chunk_order', 'text'])
        extra = extra.filter(pc.is_in(extra['run'], value_set=pa.array(sorted(text_runs))))
        for qid, doc_id, run, order, text in zip(*(extra[c].to_pylist() for c in extra.column_names)):
            verbatim[(qid, doc_id, run, order)] = text
    sources = {}
    for run, doc_ids in needed.items():
        emit(f'Cắt chunk từ {run}: {len(doc_ids)} tài liệu')
        spans, texts = load_run_texts(runs[run], doc_ids)
        lost = (doc_ids - set(spans)) | (doc_ids - set(texts))
        if lost:
            raise ValueError(f'{run}: {len(lost)} tài liệu không có trong chunks/corpus, ví dụ {sorted(lost)[:5]}')
        sources[run] = (spans, texts)

    window = argparse.Namespace(window_tokens=args.window_tokens, windows='covering', max_windows_per_doc=1)
    rows, tokens = [], []
    for qid in query_ids:
        chosen = plan[qid]
        chunks = []
        for _score, doc_id, run, order in chosen[:args.chunk_docs]:
            if run in text_runs:
                piece = verbatim.get((qid, doc_id, run, order), '')
                if piece.strip():
                    chunks.append({'doc_id': int(doc_id), 'chunk_text': piece})
                    tokens.append(schema.count_tokens(piece))
                continue
            spans, texts = sources[run]
            text = texts[doc_id]
            for start, end in chunks_for_document(text, spans[doc_id], [order], window):
                piece = text[start:end]
                if piece.strip():
                    chunks.append({'doc_id': int(doc_id), 'chunk_text': piece})
                    tokens.append(schema.count_tokens(piece))
        docs = list(dict.fromkeys(int(item[1]) for item in chosen))
        listed = set(docs)
        for item in chunks:
            if item['doc_id'] not in listed:
                docs.append(item['doc_id'])
                listed.add(item['doc_id'])
        rows.append({'id': int(qid), 'relevant_docs': docs, 'relevant_chunks': chunks})

    problems = schema.validate_submission_shape(rows, query_ids)
    if problems:
        raise ValueError('Bài nộp sai cấu trúc: ' + '; '.join(problems[:5]))
    official = pq.read_table(args.links, columns=['id'])['id'].to_numpy()
    used = np.array(sorted({d for row in rows for d in row['relevant_docs']}), dtype=np.int64)
    outside = used[~np.isin(used, official)]
    if len(outside):
        raise ValueError(f'{len(outside)} id không có trong links_corpus, ví dụ {outside[:5].tolist()}.')
    json_path, zip_path = write_streaming(rows, args.out, lzma=args.lzma)
    tokens.sort()
    summary = {
        'pairs': args.pairs, 'scores': args.scores, 'pairs_scored': scored, 'pairs_total': len(pairs),
        'settings': {k: getattr(args, k) for k in ('mix', 'docs', 'min_score', 'ratio', 'min_docs', 'max_docs',
                                                   'chunk_docs', 'window_tokens', 'text_runs')},
        'docs_mean': round(float(np.mean([len(r['relevant_docs']) for r in rows])), 2),
        'chunks_mean': round(float(np.mean([len(r['relevant_chunks']) for r in rows])), 2),
        'queries_without_docs': sum(1 for r in rows if not r['relevant_docs']),
        'chunk_tokens_median': tokens[len(tokens) // 2] if tokens else 0,
        'zip_mb': round(zip_path.stat().st_size / 1e6, 1), 'zip_mib': round(zip_path.stat().st_size / 2 ** 20, 2),
    }
    storage.write_json(Path(args.out) / 'rerank_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nNộp file: {zip_path}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
