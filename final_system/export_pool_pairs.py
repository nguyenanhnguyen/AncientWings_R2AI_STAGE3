"""Bước B1: xuất ứng viên của MỌI nguồn (run tiếng Việt, run tiếng Trung, bài nộp không còn run) để chấm
chung bằng Qwen3-Reranker-4B trên Kaggle. Không cần GPU.

Khác export_rerank_candidates.py: mỗi nguồn được một hạn mức riêng (QUOTA tài liệu đầu của chính nó),
nên run tiếng Trung không bị run tiếng Việt chèn mất chỗ và ngược lại. Với run có thư mục, đoạn đem chấm
là chunk điểm cao nhất của tài liệu (title + text, giống hệt bước A), nên các cặp tiếng Việt đã chấm ở
bước A có cùng key và Kaggle bỏ qua, không chấm lại. Với bài nộp không còn run (--extra), đoạn đem chấm
là chunk đầu tiên của tài liệu trong bài nộp đó (tài liệu không có chunk thì bỏ qua).

Ví dụ (PowerShell, ở thư mục gốc repo):

  .\\env\\Scripts\\python.exe export_pool_pairs.py --runs work/run_vi=25 work/run_b=25 work/run_c=25 work/run_d=25 work/run_e=25 work/run_f=25 work/run_g=25 work/run_zh_a=15 work/run_zh_b=15 work/run_zh_c=40 --extra lo_004_win1000/submission.zip=lo_004:40 --out work/rerank_pool/pairs.parquet

Kết quả: pairs.parquet (+ pairs_manifest.json). Upload lên Kaggle, chạy notebooks/rerank_kaggle.ipynb như
bước A (Add Input thêm scores.parquet cũ của bước A để bỏ qua các cặp đã chấm).
"""
import argparse
import heapq
import json
import math
import re
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402
from export_rerank_candidates import PAIR_SCHEMA, candidate_score, load_passages  # noqa: E402
from merge_submissions import read_rows  # noqa: E402

SPEC = re.compile(r'^(.*?)(?:=(\d+))?$')
EXTRA_SPEC = re.compile(r'^(.*)=([A-Za-z0-9_.-]+)(?::(\d+))?$')


def parse_run(text, default):
    path, quota = SPEC.match(text).groups()
    return path, int(quota) if quota else default


def parse_extra(text, default):
    match = EXTRA_SPEC.match(text)
    if not match:
        raise argparse.ArgumentTypeError(f'--extra cần dạng file.zip=TÊN hoặc file.zip=TÊN:SỐ, nhận "{text}"')
    path, name, quota = match.groups()
    return path, name, int(quota) if quota else default


def run_pool(run, quota, query_ids, passages=1, passage_docs=0, force=None):
    """-> [(qid, rank, doc_id, score, chunk_order, passage_rank)] for the top `quota` documents of each query.

    Passage 0 is the document's best candidate chunk (same key as step A). With passages > 1, the first
    `passage_docs` documents also get their other candidate chunks, then the chunks next to the best one,
    so the reranker sees more of the document. Every passage carries the document's best old score.
    """
    path = Path(run) / 'retrieval' / 'candidates.jsonl'
    if not path.exists():
        raise FileNotFoundError(f'Không thấy {path}')
    emit(f'Đọc {path} (lấy {quota} tài liệu đầu mỗi câu)')
    selected, missing_ce = [], 0
    for record in storage.iter_jsonl(path):
        qid = int(record['query_id'])
        if qid not in query_ids:
            continue
        best, chunks = {}, {}
        for candidate in record.get('candidates') or []:
            if candidate.get('ce_score') is None:
                missing_ce += 1
            score = float(candidate_score(candidate))
            doc_id = int(candidate['doc_id'])
            order = int(candidate['chunk_order'])
            chunks.setdefault(doc_id, []).append((score, order))
            if doc_id not in best or score > best[doc_id][0]:
                best[doc_id] = (score, order)
        top = heapq.nsmallest(quota, best, key=lambda d: (-best[d][0], d))
        # Documents of the --force-from submission outside the quota are scored too (one passage each).
        extra = sorted((force or {}).get(qid, set()) & set(best) - set(top), key=lambda d: (-best[d][0], d))
        for doc_id in extra:
            score, order = best[doc_id]
            selected.append((qid, quota, doc_id, score, order, 0))
        for rank, doc_id in enumerate(top):
            score, order = best[doc_id]
            selected.append((qid, rank, doc_id, score, order, 0))
            if passages > 1 and rank < passage_docs:
                others = [o for _s, o in sorted(chunks[doc_id], reverse=True) if o != order]
                for near in (order + 1, order - 1, order + 2, order - 2):
                    if near >= 0 and near not in others and near != order:
                        others.append(near)
                for p_rank, extra in enumerate(dict.fromkeys(others).keys(), start=1):
                    if p_rank >= passages:
                        break
                    selected.append((qid, rank, doc_id, score, extra, p_rank))
    if missing_ce:
        emit(f'  Cảnh báo: {missing_ce} ứng viên không có ce_score.')
    return selected


def extra_pool(path, quota, query_ids, force=None):
    """-> [(qid, rank, doc_id, chunk_index, chunk_text)] from a submission: first chunk of each document.

    Past the quota, documents listed in --force-from for that query are still taken."""
    emit(f'Đọc {path} (lấy {quota} tài liệu có chunk đầu tiên mỗi câu)')
    selected = []
    for row in read_rows(path):
        qid = int(row['id'])
        if qid not in query_ids:
            continue
        seen = set()
        for index, chunk in enumerate(row['relevant_chunks']):
            doc_id = int(chunk['doc_id'])
            text = chunk['chunk_text']
            if doc_id in seen or not text.strip():
                continue
            if len(seen) >= quota and doc_id not in (force or {}).get(qid, ()):
                continue
            seen.add(doc_id)
            selected.append((qid, min(len(seen) - 1, quota), doc_id, index, text))
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--runs', nargs='+', required=True, help='work/run_x hoặc work/run_x=QUOTA')
    parser.add_argument('--extra', nargs='*', default=[], help='bài_nộp.zip=TÊN hoặc bài_nộp.zip=TÊN:QUOTA')
    parser.add_argument('--per-run', type=int, default=25, help='Hạn mức mặc định khi không ghi =QUOTA.')
    parser.add_argument('--passages', type=int, default=1,
                        help='Số đoạn chấm cho mỗi tài liệu (1 = như bước B1 đầu tiên).')
    parser.add_argument('--force-from', help='Bài nộp: mọi tài liệu của nó cũng được chấm (1 đoạn), kể cả ngoài hạn mức.')
    parser.add_argument('--passage-docs', type=int, default=15,
                        help='Chỉ các tài liệu hạng < N trong run của nó được chấm thêm đoạn.')
    parser.add_argument('--out', default='work/rerank_pool/pairs.parquet')
    parser.add_argument('--queries', default='data/query.parquet')
    args = parser.parse_args()

    queries = {int(row['id']): row['query'] for row in load_queries(args.queries)}
    runs = [parse_run(text, args.per_run) for text in args.runs]
    extras = [parse_extra(text, args.per_run) for text in args.extra]
    names = [Path(path).name for path, _q in runs] + [name for _p, name, _q in extras]
    if len(set(names)) != len(names):
        raise ValueError(f'Tên nguồn bị trùng: {names}')

    force = None
    if args.force_from:
        force = {}
        for row in read_rows(args.force_from):
            force[int(row['id'])] = {int(d) for d in row['relevant_docs']}
        emit(f'--force-from: {sum(map(len, force.values())) / max(1, len(force)):.1f} tài liệu mỗi câu')
    rows = []  # (qid, query, doc_id, run, chunk_order, old_score, rank, passage_rank, text)
    by_source = {}
    for path, quota in runs:
        name = Path(path).name
        selected = run_pool(path, quota, queries, args.passages, args.passage_docs, force)
        wanted = {(doc_id, order) for _q, _r, doc_id, _s, order, _p in selected}
        emit(f'  Lấy văn bản {len(wanted)} đoạn từ {name}')
        texts = load_passages(path, wanted)
        main_lost = {(d, o) for _q, _r, d, _s, o, p in selected if p == 0} - set(texts)
        if main_lost:
            raise ValueError(f'{name}: {len(main_lost)} đoạn không có trong chunks.parquet, ví dụ {sorted(main_lost)[:3]}')
        kept = 0
        for qid, rank, doc_id, score, order, p_rank in selected:
            text = texts.get((doc_id, order))
            if text is None:  # a neighbour past the end of the document
                continue
            rows.append((qid, queries[qid], doc_id, name, order, score, rank, p_rank, text))
            kept += 1
        by_source[name] = kept
    for path, name, quota in extras:
        selected = extra_pool(path, quota, queries, force)
        for qid, rank, doc_id, index, text in selected:
            rows.append((qid, queries[qid], doc_id, name, index, math.nan, rank, 0, text))
        by_source[name] = len(selected)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = list(zip(*rows))
    table = pa.Table.from_arrays([pa.array(col, type=field.type) for col, field in zip(columns, PAIR_SCHEMA)],
                                 schema=PAIR_SCHEMA)
    pq.write_table(table, out, compression='zstd')
    docs_per_query = {}
    for qid, _query, doc_id, *_rest in rows:
        docs_per_query.setdefault(qid, set()).add(doc_id)
    summary = {
        'runs': {Path(p).name: {'path': p, 'quota': q} for p, q in runs},
        'extra': {n: {'path': p, 'quota': q} for p, n, q in extras},
        'pairs': table.num_rows, 'pairs_by_source': by_source,
        'unique_docs_per_query': round(sum(map(len, docs_per_query.values())) / max(1, len(queries)), 1),
        'file_mb': round(out.stat().st_size / 1e6, 1),
    }
    storage.write_json(out.with_name('pairs_manifest.json'), summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nUpload lên Kaggle: {out}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
