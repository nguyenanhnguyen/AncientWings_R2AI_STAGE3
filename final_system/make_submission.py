"""Tạo biến thể bài nộp từ một lượt chạy đã có. Không cần GPU, không chạy lại model.

Đặt file này ở thư mục gốc repo (cạnh `scripts/` và `src/`). Nó chỉ đọc thư mục run, không sửa gì
trong đó, và ghi bài nộp mới vào `--out`.

Ví dụ (PowerShell, ở thư mục gốc repo):

  # 1) Giữ nguyên tài liệu và chunk của bài recall, chỉ bỏ trường chunk_order
  .\\env\\Scripts\\python.exe make_submission.py --run work/run_vi --out work/run_vi/v1_no_order

  # 2) Giữ nguyên tài liệu, đổi mỗi chunk thành cửa sổ lớn tới 1000 token quanh nó
  .\\env\\Scripts\\python.exe make_submission.py --run work/run_vi --out work/run_vi/v2_win1000 --window-tokens 1000

  # 3) Giữ nguyên chunk, nộp 30 tài liệu mỗi câu
  .\\env\\Scripts\\python.exe make_submission.py --run work/run_vi --out work/run_vi/v3_docs30 --docs 30

Mọi chunk_text đều là một lát cắt liên tục của văn bản tài liệu trong corpus của lượt chạy.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402
from vibiomir.submission import export  # noqa: E402


def score_of(candidate):
    value = candidate.get('ce_score')
    return candidate['rrf_score'] if value is None else value


def rank_documents(record, how):
    """Document ids, best first. `pipeline` keeps the order the pipeline wrote; `max` uses the best chunk."""
    if how == 'pipeline':
        return [int(item['doc_id']) for item in record.get('documents') or []]
    best = {}
    for candidate in record.get('candidates') or []:
        doc_id = int(candidate['doc_id'])
        best[doc_id] = max(best.get(doc_id, float('-inf')), score_of(candidate))
    return sorted(best, key=lambda doc_id: (-best[doc_id], doc_id))


def chunk_orders_by_document(record):
    """doc_id -> chunk orders of its candidate chunks, best score first."""
    grouped = {}
    for candidate in sorted(record.get('candidates') or [], key=score_of, reverse=True):
        grouped.setdefault(int(candidate['doc_id']), []).append(int(candidate['chunk_order']))
    return grouped


def window_tokens(text, spans, low, high):
    return schema.count_tokens(text[spans[low][0]:spans[high][1]])


def grow_window(text, spans, seed, limit, taken):
    """Largest run of neighbouring chunks around `seed` that stays within `limit` tokens."""
    low = high = seed
    prefer_right = True
    while True:
        right_ok = (high + 1 < len(spans) and (high + 1) not in taken
                    and window_tokens(text, spans, low, high + 1) <= limit)
        left_ok = (low - 1 >= 0 and (low - 1) not in taken
                   and window_tokens(text, spans, low - 1, high) <= limit)
        if not right_ok and not left_ok:
            return low, high
        if right_ok and (prefer_right or not left_ok):
            high += 1
        else:
            low -= 1
        prefer_right = not prefer_right


def tile_windows(text, spans, limit):
    """Cover the whole document with consecutive windows of at most `limit` tokens."""
    windows, low = [], 0
    while low < len(spans):
        high = low
        while high + 1 < len(spans) and window_tokens(text, spans, low, high + 1) <= limit:
            high += 1
        windows.append((low, high))
        low = high + 1
    return windows


def chunks_for_document(text, spans, seeds, args):
    """-> [(char_start, char_end)] to submit for one document, given its seed chunk orders."""
    seeds = [order for order in seeds if 0 <= order < len(spans)]
    if not args.window_tokens:
        return [spans[order] for order in dict.fromkeys(seeds)]
    if args.windows == 'all':
        windows = tile_windows(text, spans, args.window_tokens)
        if args.max_windows_per_doc:
            # Windows holding a seed first, then the others in reading order.
            wanted = set(seeds)
            windows.sort(key=lambda w: (not any(w[0] <= s <= w[1] for s in wanted), w[0]))
            windows = sorted(windows[:args.max_windows_per_doc])
    else:
        windows, taken = [], set()
        for seed in seeds:
            if seed in taken:
                continue
            low, high = grow_window(text, spans, seed, args.window_tokens, taken)
            taken.update(range(low, high + 1))
            windows.append((low, high))
            if args.max_windows_per_doc and len(windows) >= args.max_windows_per_doc:
                break
    return [(spans[low][0], spans[high][1]) for low, high in windows]


def build(args):
    run = Path(args.run)
    queries = load_queries(args.queries)
    query_ids = [row['id'] for row in queries]
    records = {int(row['query_id']): row for row in storage.iter_jsonl(run / 'retrieval' / 'candidates.jsonl')}
    missing = [query_id for query_id in query_ids if query_id not in records]
    if missing:
        raise ValueError(f'{len(missing)} câu hỏi không có trong candidates.jsonl, ví dụ {missing[:5]}')

    base_path = {'recall': run / 'submission' / 'submission.json',
                 'balanced': run / 'submission_balanced' / 'submission.json'}.get(args.base, Path(args.base))
    base = {int(row['id']): row for row in storage.read_json(base_path)}

    # 1) Decide documents and seed chunks for every query.
    plan, base_texts = {}, {}
    for query_id in query_ids:
        record = records[query_id]
        ranking = rank_documents(record, args.doc_rank)
        if args.docs:
            docs = ranking[:args.docs]
        else:
            docs = [int(value) for value in base[query_id]['relevant_docs']]
        if args.chunk_docs:
            orders = chunk_orders_by_document(record)
            seeds = [(doc_id, order) for doc_id in ranking[:args.chunk_docs]
                     for order in orders.get(doc_id, [])[:args.chunk_per_doc]]
        else:
            items = base[query_id]['relevant_chunks']
            if any('chunk_order' not in item for item in items):
                raise ValueError(f'{base_path} không có chunk_order; hãy dùng bài nộp do pipeline tạo ra làm --base.')
            seeds = [(int(item['doc_id']), int(item['chunk_order'])) for item in items]
            for item in items:
                base_texts[(query_id, int(item['doc_id']), int(item['chunk_order']))] = item['chunk_text']
        plan[query_id] = (docs, seeds)

    # 2) Load chunk spans and document texts for the documents that get chunks.
    needed = {doc_id for _docs, seeds in plan.values() for doc_id, _order in seeds}
    table = pq.read_table(run / 'chunks' / 'chunks.parquet',
                          columns=['doc_id', 'chunk_order', 'char_start', 'char_end'])
    spans = {}
    for doc_id, order, start, end in zip(table['doc_id'].to_pylist(), table['chunk_order'].to_pylist(),
                                         table['char_start'].to_pylist(), table['char_end'].to_pylist()):
        if doc_id in needed:
            spans.setdefault(doc_id, []).append((order, start, end))
    for doc_id, rows in spans.items():
        rows.sort()
        if [row[0] for row in rows] != list(range(len(rows))):
            raise ValueError(f'Tài liệu {doc_id}: thứ tự chunk không liên tục trong chunks.parquet.')
        spans[doc_id] = [(start, end) for _order, start, end in rows]
    del table
    texts = {}
    corpus = pq.read_table(run / 'corpus' / 'corpus.parquet', columns=['id', 'text'])
    for doc_id, text in zip(corpus['id'].to_pylist(), corpus['text'].to_pylist()):
        if doc_id in needed:
            texts[doc_id] = schema.document_text({'text': text})
    del corpus
    lost = needed - set(texts) | needed - set(spans)
    if lost:
        raise ValueError(f'{len(lost)} tài liệu của bài nộp gốc không có trong run này, ví dụ {sorted(lost)[:5]}.')

    # 3) Build the rows.
    rows, token_counts, added_docs, covered, uncovered = [], [], 0, 0, 0
    for query_id in query_ids:
        docs, seeds = plan[query_id]
        by_doc = {}
        for doc_id, order in seeds:
            by_doc.setdefault(doc_id, []).append(order)
        chunks = []
        if not args.window_tokens:
            # Chunks stay exactly as chosen, in their original order.
            by_doc = {}
            done = set()
            for doc_id, order in seeds:
                if (doc_id, order) in done or not 0 <= order < len(spans[doc_id]):
                    continue
                done.add((doc_id, order))
                start, end = spans[doc_id][order]
                piece = texts[doc_id][start:end]
                original = base_texts.get((query_id, doc_id, order))
                if original is not None:
                    if original != piece:
                        raise ValueError(f'Câu {query_id}, tài liệu {doc_id}: chunk gốc không khớp đoạn cắt lại; '
                                         'corpus hoặc chunks của run đã bị thay đổi.')
                    covered += 1
                token_counts.append(schema.count_tokens(piece))
                item = {'doc_id': int(doc_id), 'chunk_text': piece}
                if args.chunk_order == 'position':
                    item['chunk_order'] = len(chunks)
                chunks.append(item)
        for doc_id, orders in by_doc.items():
            text = texts[doc_id]
            pieces = [text[start:end] for start, end in chunks_for_document(text, spans[doc_id], orders, args)]
            pieces = [piece for piece in pieces if piece.strip()]
            for order in orders:
                # The chunk the pipeline chose must still be inside what is submitted for its document.
                original = base_texts.get((query_id, doc_id, order))
                if original is None:
                    continue
                if any(original in piece for piece in pieces):
                    covered += 1
                elif args.max_windows_per_doc:
                    uncovered += 1
                else:
                    raise ValueError(f'Câu {query_id}, tài liệu {doc_id}: chunk gốc không nằm trong đoạn cắt lại; '
                                     'corpus hoặc chunks của run đã bị thay đổi.')
            for piece in pieces:
                token_counts.append(schema.count_tokens(piece))
                item = {'doc_id': int(doc_id), 'chunk_text': piece}
                if args.chunk_order == 'position':
                    item['chunk_order'] = len(chunks)
                chunks.append(item)
        docs = list(dict.fromkeys(int(value) for value in docs))
        for item in chunks:
            # Every submitted chunk's document is listed, as the pipeline does.
            if item['doc_id'] not in docs:
                docs.append(item['doc_id'])
                added_docs += 1
        rows.append({'id': int(query_id), 'relevant_docs': docs, 'relevant_chunks': chunks})

    problems = schema.validate_submission_shape(rows, query_ids)
    if problems:
        raise ValueError('Bài nộp sai cấu trúc: ' + '; '.join(problems[:5]))
    official = pq.read_table(args.links, columns=['id'])['id'].to_numpy()
    used = np.array(sorted({doc for row in rows for doc in row['relevant_docs']}), dtype=np.int64)
    outside = used[~np.isin(used, official)]
    if len(outside):
        raise ValueError(f'{len(outside)} id không có trong links_corpus, ví dụ {outside[:5].tolist()}.')

    json_path, zip_path = export.write_submission(rows, args.out)
    doc_counts = [len(row['relevant_docs']) for row in rows]
    chunk_counts = [len(row['relevant_chunks']) for row in rows]
    token_counts.sort()
    summary = {
        'run': str(run), 'base': str(base_path),
        'settings': {'docs': args.docs, 'doc_rank': args.doc_rank, 'chunk_docs': args.chunk_docs,
                     'chunk_per_doc': args.chunk_per_doc, 'window_tokens': args.window_tokens,
                     'windows': args.windows, 'max_windows_per_doc': args.max_windows_per_doc,
                     'chunk_order': args.chunk_order},
        'queries': len(rows),
        'docs_mean': round(sum(doc_counts) / len(rows), 2), 'docs_min': min(doc_counts), 'docs_max': max(doc_counts),
        'chunks_mean': round(sum(chunk_counts) / len(rows), 2), 'chunks_max': max(chunk_counts),
        'docs_added_for_chunks': added_docs,
        'base_chunks_still_covered': covered, 'base_chunks_dropped_by_window_cap': uncovered,
        'chunk_tokens_median': token_counts[len(token_counts) // 2] if token_counts else 0,
        'chunk_tokens_p95': token_counts[int(len(token_counts) * 0.95)] if token_counts else 0,
        'chunk_tokens_max': token_counts[-1] if token_counts else 0,
        'json_mb': round(json_path.stat().st_size / 1e6, 1), 'zip_mb': round(zip_path.stat().st_size / 1e6, 1),
    }
    storage.write_json(Path(args.out) / 'variant_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nNộp file: {zip_path}')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run', required=True, help='Thư mục run của pipeline, ví dụ work/run_vi.')
    parser.add_argument('--out', required=True, help='Thư mục ghi bài nộp mới.')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--links', default='data/links_corpus.parquet')
    parser.add_argument('--base', default='recall',
                        help='Bài nộp gốc: recall, balanced, hoặc đường dẫn tới một submission.json của pipeline.')
    parser.add_argument('--docs', type=int, default=0,
                        help='Số tài liệu nộp cho mỗi câu. 0 = giữ danh sách của bài nộp gốc.')
    parser.add_argument('--doc-rank', choices=['pipeline', 'max'], default='pipeline',
                        help='Cách xếp hạng tài liệu khi dùng --docs/--chunk-docs: thứ tự của pipeline, '
                             'hoặc theo chunk tốt nhất.')
    parser.add_argument('--chunk-docs', type=int, default=0,
                        help='Lấy chunk từ ngần này tài liệu đứng đầu. 0 = giữ chunk của bài nộp gốc.')
    parser.add_argument('--chunk-per-doc', type=int, default=1,
                        help='Số chunk hạt giống mỗi tài liệu khi dùng --chunk-docs.')
    parser.add_argument('--window-tokens', type=int, default=0,
                        help='Gộp chunk liền kề thành cửa sổ tối đa ngần này token. 0 = giữ chunk gốc.')
    parser.add_argument('--windows', choices=['covering', 'all'], default='covering',
                        help='covering: cửa sổ quanh mỗi chunk được chọn; all: phủ toàn bộ tài liệu.')
    parser.add_argument('--max-windows-per-doc', type=int, default=0, help='0 = không giới hạn.')
    parser.add_argument('--chunk-order', choices=['none', 'position'], default='none',
                        help='none: không ghi chunk_order; position: ghi vị trí trong mảng.')
    args = parser.parse_args()
    if min(args.docs, args.chunk_docs, args.window_tokens, args.max_windows_per_doc) < 0 or args.chunk_per_doc < 1:
        parser.error('Các số phải không âm, --chunk-per-doc từ 1 trở lên.')
    build(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
