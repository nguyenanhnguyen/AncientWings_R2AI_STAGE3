"""Bước A1: xuất ứng viên của mọi lô để rerank lại bằng mô hình lớn trên Kaggle. Không cần GPU.

Đặt file này ở thư mục gốc repo. Với mỗi câu hỏi, gom ứng viên trong retrieval/candidates.jsonl của
mọi run, điểm tài liệu = điểm reranker cũ cao nhất trong các chunk của nó (cùng hai reranker cho mọi
lô nên so được giữa các lô), giữ --docs-per-query tài liệu đứng đầu, mỗi tài liệu --passages-per-doc
đoạn điểm cao nhất, kèm văn bản đoạn đó đúng như pipeline đưa vào reranker (title + text).

Ví dụ (PowerShell, ở thư mục gốc repo; liệt kê đủ các run tiếng Việt đã chạy):

  .\\env\\Scripts\\python.exe export_rerank_candidates.py --runs work/run_04 work/run_vi work/run_b work/run_c work/run_d work/run_e work/run_f work/run_g --out work/rerank/pairs.parquet

Kết quả: pairs.parquet (upload lên Kaggle làm Dataset) và pairs_manifest.json.
"""
import argparse
import heapq
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from vibiomir.common import storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402

PAIR_SCHEMA = pa.schema([
    ('qid', pa.int32()), ('query', pa.string()), ('doc_id', pa.int64()), ('run', pa.string()),
    ('chunk_order', pa.int32()), ('old_score', pa.float32()), ('old_doc_rank', pa.int32()),
    ('passage_rank', pa.int8()), ('text', pa.string()),
])


def run_names(runs):
    names = [Path(run).name for run in runs]
    if len(set(names)) != len(names):
        raise ValueError(f'Tên thư mục run bị trùng: {names}. Mỗi run cần một tên thư mục khác nhau.')
    return names


def candidate_score(candidate):
    value = candidate.get('ce_score')
    return candidate['rrf_score'] if value is None else value


def collect(runs, names, keep_passages):
    """{qid: {doc_id: [(score, run, chunk_order), ...best first, at most keep_passages]}}."""
    pool = {}
    for run, name in zip(runs, names):
        path = Path(run) / 'retrieval' / 'candidates.jsonl'
        if not path.exists():
            raise FileNotFoundError(f'Không thấy {path}')
        emit(f'Đọc {path}')
        reranked = total = 0
        for record in storage.iter_jsonl(path):
            docs = pool.setdefault(int(record['query_id']), {})
            for candidate in record.get('candidates') or []:
                total += 1
                if candidate.get('ce_score') is not None:
                    reranked += 1
                entry = (float(candidate_score(candidate)), name, int(candidate['chunk_order']))
                passages = docs.setdefault(int(candidate['doc_id']), [])
                if any(p[1] == name and p[2] == entry[2] for p in passages):
                    continue
                passages.append(entry)
                passages.sort(key=lambda p: -p[0])
                del passages[keep_passages:]
        if total and reranked < total:
            emit(f'  Cảnh báo: {name} có {total - reranked}/{total} ứng viên không có ce_score '
                 '(điểm RRF không so được với các lô khác).')
    return pool


def load_passages(run, wanted):
    """{(doc_id, chunk_order): retrieval text} for the wanted pairs of one run."""
    path = Path(run) / 'chunks' / 'chunks.parquet'
    docs = pa.array(sorted({doc for doc, _order in wanted}), type=pa.int64())
    table = pq.read_table(path, columns=['doc_id', 'chunk_order', 'title', 'text'])
    table = table.filter(pc.is_in(table['doc_id'], value_set=docs))
    result = {}
    for doc_id, order, title, text in zip(*(table[name].to_pylist() for name in
                                            ('doc_id', 'chunk_order', 'title', 'text'))):
        if (doc_id, order) in wanted:
            title = (title or '').strip()
            result[(doc_id, order)] = f'{title}\n{text}' if title else text
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', nargs='+', required=True)
    parser.add_argument('--out', default='work/rerank/pairs.parquet')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--docs-per-query', type=int, default=100)
    parser.add_argument('--passages-per-doc', type=int, default=1)
    args = parser.parse_args()
    if args.docs_per_query < 1 or not 1 <= args.passages_per_doc <= 5:
        parser.error('--docs-per-query >= 1, --passages-per-doc trong khoảng 1..5')

    names = run_names(args.runs)
    queries = {row['id']: row['query'] for row in load_queries(args.queries)}
    pool = collect(args.runs, names, args.passages_per_doc)
    missing = [qid for qid in queries if qid not in pool]
    if missing:
        emit(f'Cảnh báo: {len(missing)} câu không có ứng viên nào, ví dụ {missing[:5]}')

    selected = []  # (qid, doc_rank, passage_rank, doc_id, score, run, order)
    for qid in queries:
        docs = pool.get(qid, {})
        best = heapq.nsmallest(args.docs_per_query, docs, key=lambda d: (-docs[d][0][0], d))
        for rank, doc_id in enumerate(best):
            for p_rank, (score, name, order) in enumerate(docs[doc_id]):
                selected.append((qid, rank, p_rank, doc_id, score, name, order))
    del pool

    texts = {}
    for run, name in zip(args.runs, names):
        wanted = {(doc, order) for _q, _r, _p, doc, _s, run_name, order in selected if run_name == name}
        if wanted:
            emit(f'Lấy văn bản {len(wanted)} đoạn từ {name}')
            for key, text in load_passages(run, wanted).items():
                texts[(name, *key)] = text
    lost = [row for row in selected if (row[5], row[3], row[6]) not in texts]
    if lost:
        raise ValueError(f'{len(lost)} đoạn không có trong chunks.parquet, ví dụ {lost[:3]}. '
                         'candidates.jsonl và chunks.parquet của run không khớp nhau.')

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = list(zip(*[(qid, queries[qid], doc, name, order, score, rank, p_rank, texts[(name, doc, order)])
                         for qid, rank, p_rank, doc, score, name, order in selected]))
    table = pa.Table.from_arrays([pa.array(col, type=field.type) for col, field in zip(columns, PAIR_SCHEMA)],
                                 schema=PAIR_SCHEMA)
    pq.write_table(table, out, compression='zstd')
    lengths = sorted(len(t) for t in columns[8])
    summary = {'runs': dict(zip(names, map(str, args.runs))), 'docs_per_query': args.docs_per_query,
               'passages_per_doc': args.passages_per_doc, 'pairs': table.num_rows,
               'queries': len(set(columns[0])),
               'docs_mean': round(sum(1 for r in selected if r[2] == 0) / max(1, len(queries)), 2),
               'pairs_by_run': {name: sum(1 for r in selected if r[5] == name) for name in names},
               'passage_chars_median': lengths[len(lengths) // 2], 'file_mb': round(out.stat().st_size / 1e6, 1)}
    storage.write_json(out.with_name('pairs_manifest.json'), summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nUpload lên Kaggle: {out}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
