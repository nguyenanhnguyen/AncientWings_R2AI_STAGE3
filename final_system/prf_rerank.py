"""Xếp hạng lại TÀI LIỆU bằng phản hồi giả (pseudo-relevance feedback): đẩy lên tài liệu cùng chủ đề với các
tài liệu 4B chấm cao nhất. Ra bài nộp CHỈ CÓ TÀI LIỆU để thử nhanh docs F2.

Mỗi câu: lấy --seeds tài liệu đầu theo điểm trộn 4B (như build_rerank_submission) làm "chủ đề"; vector chủ đề =
trung bình embedding (bge-m3, có sẵn trong index của từng run) của đoạn tốt nhất mỗi tài liệu đó. Mỗi tài liệu
ứng viên được chấm độ giống chủ đề = cosine cao nhất trong các chunk của nó. Điểm cuối = điểm 4B chuẩn hoá trong câu
+ --weight × độ giống chuẩn hoá trong câu. --weight 0 = đúng thứ tự 4B (dùng làm mốc so sánh).

Ý tưởng: đáp án của BTC có khoảng 65 tài liệu mỗi câu, tức nhiều tài liệu cùng chủ đề; 4B chỉ xét "đoạn này có
trả lời câu hỏi không" nên có thể xếp thấp tài liệu đúng chủ đề mà không có câu trả lời trực tiếp.
Không cần GPU. Tài liệu của nguồn không có index (--text-runs, vd. lo_004) giữ điểm chủ đề trung tính.

--adaptive: số tài liệu MỖI CÂU thay đổi theo điểm 4B thay vì cố định, kẹp trong [--min-docs, --max-docs];
trung bình vẫn bằng --docs (so sánh công bằng với bản cố định). Lý do: F2 của một câu = 5·đúng/(4·số đáp án +
số nộp), nên câu ít đáp án nên nộp ít, câu nhiều đáp án nên nộp nhiều. Hai cách (--adaptive-rule):
  count (mặc định): nộp các tài liệu có điểm 4B (trộn) >= T; T tự tìm cho đủ trung bình.
  f2   : coi điểm 4B ≈ xác suất đúng (nhân hệ số c), ước lượng số đáp án của câu = c·tổng điểm / --pool-recall, rồi
         chọn số tài liệu (theo thứ tự PRF) cho F2 kỳ vọng lớn nhất; c tự tìm cho đủ trung bình. Khác count ở
         câu "khó" (điểm đều thấp): count nộp ít, f2 nộp sâu hơn vì ở câu F2 thấp thì tài liệu xác suất thấp
         vẫn có lời.

--chunk-docs K: nộp thêm chunk cho các tài liệu đầu mỗi câu THEO THỨ TỰ PRF (một cửa sổ --window-tokens quanh
đoạn 4B tốt nhất, cắt nguyên văn như build_rerank_submission), trung bình K tài liệu có chunk mỗi câu. Với
--adaptive (số tài liệu khác nhau giữa các câu), --chunk-mode chọn cách chia K:
  cap  (mặc định): câu có ít tài liệu được chunk HẾT tài liệu của nó; câu nhiều tài liệu bị cắt ở mức trần
       chung (tự tìm để trung bình = K). Một chunk ở câu ít đáp án đáng giá hơn nhiều (F2 = 5·đúng/(4·đáp án +
       số nộp): mẫu số nhỏ), nên khi thiếu dung lượng thì bớt chunk ở câu nhiều đáp án trước.
  prop : số tài liệu có chunk tỉ lệ với số tài liệu của câu.
0 = chỉ nộp tài liệu.

--second-weight w: thứ tự tài liệu dùng điểm đoạn 4B tốt nhất + w × đoạn tốt thứ hai (tài liệu có nhiều đoạn được
chấm cao thì nhiều khả năng đúng hơn). --extra-windows M: M tài liệu đầu mỗi câu được thêm cửa sổ thứ hai quanh
đoạn 4B tốt thứ hai (mỗi tài liệu đúng có trung bình ~1,15 đoạn đáp án); dung lượng được trừ trước khi chọn trần.

Không ghi --pairs/--scores/--runs/--text-runs thì dùng bộ mặc định của đội (rerank_pool4, pool5, h_arch, arch2, arch3;
14 run; lo_004), nên lệnh chỉ cần các tuỳ chọn thử nghiệm, vd.:
  .\\env\\Scripts\\python.exe prf_rerank.py --docs 190 --adaptive --out work/prf/ad

Ví dụ (ở thư mục gốc repo; --pairs/--scores/--runs như lệnh build_rerank_submission):
  .\\env\\Scripts\\python.exe prf_rerank.py --pairs ... --scores ... --runs ... --text-runs lo_004 --docs 190 --weight 0 --out work/prf/w0
  .\\env\\Scripts\\python.exe prf_rerank.py --pairs ... --scores ... --runs ... --text-runs lo_004 --docs 190 --weight 0.5 --out work/prf/w05
  .\\env\\Scripts\\python.exe prf_rerank.py --pairs ... --scores ... --runs ... --text-runs lo_004 --docs 190 --weight 1 --adaptive --out work/prf/w1_ad
  .\\env\\Scripts\\python.exe prf_rerank.py --pairs ... --scores ... --runs ... --text-runs lo_004 --docs 190 --weight 1 --chunk-docs 150 --out work/prf/w1_c150
"""
import argparse
import glob
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402
from build_rerank_submission import load_run_texts, load_scores, pair_key, rank_documents, read_pairs  # noqa: E402
from make_submission import chunks_for_document  # noqa: E402
from merge_submissions import write_streaming  # noqa: E402


ZH_LOW, ZH_HIGH = 766442, 4420561
DEFAULT_POOLS = ('rerank_pool4', 'rerank_pool5', 'rerank_h_arch', 'rerank_arch2', 'rerank_arch3')
DEFAULT_RUNS = ('run_vi', 'run_b', 'run_c', 'run_d', 'run_e', 'run_f', 'run_g', 'run_zh_a', 'run_zh_b', 'run_zh_c',
                'run_h', 'run_archive', 'run_archive2', 'run_archive3')


class RunIndex:
    """Chunk embeddings of one run, with rows grouped by document."""

    def __init__(self, run, encoder):
        folder = Path(run) / 'index' / encoder
        self.emb = np.load(folder / 'embeddings.npy', mmap_mode='r')
        doc_ids = np.load(folder / 'doc_ids.npy')
        self.doc_ids = doc_ids
        orders = pq.read_table(Path(run) / 'chunks' / 'chunks.parquet', columns=['chunk_order'])['chunk_order']
        self.orders = orders.to_numpy()
        if len(doc_ids) != len(self.emb) or len(self.orders) != len(self.emb):
            raise ValueError(f'{run}: số dòng embeddings / doc_ids / chunks.parquet không khớp.')
        sort = np.argsort(doc_ids, kind='stable')
        ids, starts = np.unique(doc_ids[sort], return_index=True)
        ends = np.append(starts[1:], len(sort))
        self.rows = {int(d): sort[s:e] for d, s, e in zip(ids, starts, ends)}

    def row_of(self, doc_id, order):
        rows = self.rows.get(int(doc_id))
        if rows is None:
            return None
        hit = rows[self.orders[rows] == order]
        return int(hit[0]) if len(hit) else int(rows[0])

    def best_cosine(self, doc_id, centroid):
        rows = self.rows.get(int(doc_id))
        if rows is None:
            return None
        return float(np.max(np.asarray(self.emb[np.sort(rows)], dtype=np.float32) @ centroid))


def expand_run(index, matrix, per_query, block=32768):
    """Scan every chunk of a run against all topic vectors; per query keep the `per_query` best documents.

    -> [ {doc_id: (best_cosine, chunk_order)} for each row of `matrix` ]."""
    found = [dict() for _ in range(len(matrix))]
    keep_rows = per_query * 3
    for start in range(0, len(index.emb), block):
        part = np.asarray(index.emb[start:start + block], dtype=np.float32)
        sims = part @ matrix.T                      # (rows, queries)
        k = min(keep_rows, len(part))
        top = np.argpartition(-sims, k - 1, axis=0)[:k]
        for q in range(len(matrix)):
            rows = top[:, q]
            best = found[q]
            for row, value in zip(rows.tolist(), sims[rows, q].tolist()):
                doc_id = int(index.doc_ids[start + row])
                if doc_id not in best or value > best[doc_id][0]:
                    best[doc_id] = (value, int(index.orders[start + row]))
            if len(best) > per_query * 4:
                kept = sorted(best.items(), key=lambda item: -item[1][0])[:per_query * 2]
                found[q] = dict(kept)
    return [dict(sorted(b.items(), key=lambda item: -item[1][0])[:per_query]) for b in found]


def zscore(values):
    array = np.asarray(values, dtype=np.float64)
    std = array.std()
    return (array - array.mean()) / std if std > 0 else np.zeros_like(array)


def adaptive_counts(pools, target, low, high):
    """Per-query document counts: #docs with 4B value >= T, clipped to [low, high] (and to the pool size),
    with T chosen so that the mean count is `target`. -> ({qid: count}, T)."""
    arrays = {q: np.sort(np.asarray([v for v, _d, _r, _o in pool], dtype=np.float64))
              for q, pool in pools.items() if pool}
    if not arrays:
        return {}, None

    def counts(threshold):
        return {q: int(min(len(a), max(low, min(high, len(a) - np.searchsorted(a, threshold, side='left')))))
                for q, a in arrays.items()}

    floor = min(float(a[0]) for a in arrays.values())
    ceiling = max(float(a[-1]) for a in arrays.values()) + 1e-9
    for _ in range(60):
        middle = (floor + ceiling) / 2
        if np.mean(list(counts(middle).values())) > target:
            floor = middle
        else:
            ceiling = middle
    return counts(ceiling), ceiling


def f2_counts(ranked_values, totals, target, low, high, pool_recall):
    """Expected-F2 document counts. ranked_values: {qid: 4B values in submission (PRF) order};
    totals: {qid: sum of 4B values over the whole pool}. With P(relevant) = c·v and expected answers
    G = c·total/pool_recall, F2(N) = 5·c·S_N / (4·G + N) = 5·S_N / (4·total/pool_recall + N/c).
    c is chosen so that the mean count is `target`. -> ({qid: count}, c)."""
    prepared = {}
    for q, values in ranked_values.items():
        if not len(values):
            continue
        sums = np.cumsum(np.asarray(values, dtype=np.float64))
        lo = min(low, len(sums))
        hi = max(lo, min(high, len(sums)))
        prepared[q] = (sums, np.arange(1, len(sums) + 1, dtype=np.float64), totals[q] / pool_recall, lo, hi)
    if not prepared:
        return {}, None

    def counts(c):
        out = {}
        for q, (sums, ns, mass, lo, hi) in prepared.items():
            f2 = sums[lo - 1:hi] / (4 * mass + ns[lo - 1:hi] / c)
            out[q] = lo + int(np.argmax(f2))
        return out

    left, right = -12.0, 12.0  # log(c)
    for _ in range(50):
        middle = (left + right) / 2
        if np.mean(list(counts(np.exp(middle)).values())) > target:
            right = middle
        else:
            left = middle
    c = float(np.exp(left))
    return counts(c), c


def pool_passages(pairs, scores, mix, pools):
    """{(qid, doc_id): [(value, run, chunk_order), ...] best first}: every 4B-scored passage of the pool documents
    (PASSAGE_RANKS = 3 on Kaggle, so up to 3 per document and run)."""
    wanted = {(qid, int(d)) for qid, pool in pools.items() for _v, d, _r, _o in pool}
    out = {}
    for qid, doc_id, run, order, old in pairs:
        key = (int(qid), int(doc_id))
        if key not in wanted:
            continue
        new = scores.get(pair_key(qid, doc_id, run, order))
        if new is None:
            continue
        value = new if old is None or not np.isfinite(old) else mix * new + (1 - mix) * old
        out.setdefault(key, {})[(run, int(order))] = max(value, out.get(key, {}).get((run, int(order)), -1.0))
    return {key: sorted(((v, r, o) for (r, o), v in items.items()), key=lambda x: -x[0]) for key, items in out.items()}


def export_extra(args, query_ids, pools, orders, limits, passages, old_best, centroids, runs, out_dir):
    """Write pairs.parquet of NOT-yet-scored passages for the documents near each query's cut-off, for one more
    4B pass on Kaggle (same notebook, same columns). Per document: the --extra-per-doc unscored chunks most
    similar to the query's topic vector."""
    import pyarrow as pa
    import pyarrow.compute as pc
    queries = {int(row['id']): row['query'] for row in load_queries(args.queries)}
    low, high = args.band
    targets = {}  # run -> [(qid, doc_id, rank)]
    for qid in query_ids:
        order = orders.get(qid)
        if not order or qid not in centroids:
            continue
        limit = limits.get(qid, args.docs) if args.adaptive else args.docs
        first, last = int(low * limit), int(np.ceil(high * limit))
        for rank in range(first, min(last, len(order))):
            _v, doc_id, run, _o = pools[qid][order[rank]]
            if run in runs:
                targets.setdefault(run, []).append((qid, int(doc_id), rank))
    rows = []
    for run, wanted in targets.items():
        index = RunIndex(runs[run], args.encoder)
        picks = []
        for qid, doc_id, rank in wanted:
            rows_of_doc = index.rows.get(doc_id)
            if rows_of_doc is None:
                continue
            scored = {o for _v, r, o in passages.get((qid, doc_id), []) if r == run}
            free = [int(r) for r in rows_of_doc if int(index.orders[r]) not in scored]
            if not free:
                continue
            free.sort()
            sims = np.asarray(index.emb[free], dtype=np.float32) @ centroids[qid]
            for position in np.argsort(-sims)[:args.extra_per_doc]:
                picks.append((qid, doc_id, int(index.orders[free[position]]), rank))
        del index
        if not picks:
            continue
        wanted_docs = pa.array(sorted({d for _q, d, _o, _r in picks}), type=pa.int64())
        table = pq.read_table(Path(runs[run]) / 'chunks' / 'chunks.parquet', columns=['doc_id', 'chunk_order', 'text'])
        table = table.filter(pc.is_in(table['doc_id'], value_set=wanted_docs))
        texts = {(int(d), int(o)): t for d, o, t in zip(*(table[c].to_pylist() for c in table.column_names))}
        del table
        for qid, doc_id, order, rank in picks:
            text = texts.get((doc_id, order))
            if text and text.strip():
                rows.append({'qid': qid, 'query': queries[qid], 'doc_id': doc_id, 'run': run, 'chunk_order': order,
                             'old_score': old_best.get((qid, doc_id, run)), 'old_doc_rank': 0, 'passage_rank': 0,
                             'text': text})
        emit(f'  {run}: {len(picks):,} đoạn mới')
    schema = pq.read_schema(args.pairs[0])
    schema = pa.schema([schema.field(name) for name in
                        ('qid', 'query', 'doc_id', 'run', 'chunk_order', 'old_score', 'old_doc_rank', 'passage_rank', 'text')])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), out_dir / 'pairs.parquet')
    hours = len(rows) / 6.5 / 3600
    summary = {'pairs': len(rows), 'per_query': round(len(rows) / max(1, len(query_ids)), 1), 'band': args.band,
               'extra_per_doc': args.extra_per_doc, 'hours_one_session_at_6_5_per_s': round(hours, 1)}
    storage.write_json(out_dir / 'extra_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nUpload {out_dir / "pairs.parquet"} lên Kaggle (rerank_kaggle.ipynb, PASSAGE_RANKS và TOP_K giữ như cũ; '
         f'chia cho N tài khoản: SHARD_COUNT = N, tài khoản i đặt SHARD_INDEX = i).')


def cut_chunks(plan, runs, text_runs, pair_paths, window_tokens, extra=None):
    """plan: {qid: [(doc_id, run, chunk_order), ...]} -> {qid: [{'doc_id', 'chunk_text'}, ...]} in plan order.

    One window of up to `window_tokens` tokens around the given passage, cut verbatim from the run's corpus
    (as build_rerank_submission does); for --text-runs sources the scored passage itself. Runs are read one
    at a time so only one run's texts are in memory."""
    pieces = {}
    window = argparse.Namespace(window_tokens=window_tokens, windows='covering', max_windows_per_doc=1)
    pair_window = argparse.Namespace(window_tokens=window_tokens, windows='covering', max_windows_per_doc=2)
    extra = extra or {}
    second = {}  # (qid, doc_id, first order) -> second window text
    by_run = {}
    for qid, items in plan.items():
        for doc_id, run, order in items:
            by_run.setdefault(run, []).append((qid, doc_id, order))
    lost = 0
    for run, wanted in by_run.items():
        if run in text_runs:
            keys = {(q, d, o) for q, d, o in wanted}
            for path in pair_paths:
                table = pq.read_table(path, columns=['qid', 'doc_id', 'run', 'chunk_order', 'text'],
                                      filters=[('run', '=', run)])
                for qid, doc_id, _r, order, text in zip(*(table[c].to_pylist() for c in table.column_names)):
                    key = (int(qid), int(doc_id), int(order))
                    if key in keys and text and text.strip():
                        pieces[key] = text
                del table
            emit(f'  chunk từ {run} (đoạn đã chấm): {sum(1 for k in keys if k in pieces):,}/{len(keys):,}')
            continue
        if run not in runs:
            lost += len(wanted)
            continue
        doc_ids = {d for _q, d, _o in wanted}
        spans, texts = load_run_texts(runs[run], doc_ids)
        for qid, doc_id, order in wanted:
            other = extra.get((qid, doc_id))
            if other is None or doc_id not in spans or doc_id not in texts:
                continue
            windows = chunks_for_document(texts[doc_id], spans[doc_id], [order, other], pair_window)
            if len(windows) > 1:
                piece = texts[doc_id][windows[1][0]:windows[1][1]]
                if piece.strip():
                    second[(qid, doc_id, order)] = piece
        made, cache = 0, {}
        for qid, doc_id, order in wanted:
            if doc_id not in spans or doc_id not in texts:
                lost += 1
                continue
            if (doc_id, order) not in cache:
                text, piece = texts[doc_id], ''
                for start, end in chunks_for_document(text, spans[doc_id], [order], window):
                    piece = text[start:end]
                    break
                cache[(doc_id, order)] = piece if piece.strip() else ''
            if cache[(doc_id, order)]:
                pieces[(qid, doc_id, order)] = cache[(doc_id, order)]
                made += 1
        emit(f'  chunk từ {run}: {made:,} cửa sổ ({len(doc_ids):,} tài liệu)')
        del spans, texts, cache
    out = {}
    for qid, items in plan.items():
        # Aligned with the plan (None where no window could be cut), so "the first k documents" stays exact.
        out[qid] = [{'doc_id': int(doc_id), 'chunk_text': pieces[(qid, doc_id, order)]}
                    if pieces.get((qid, doc_id, order)) else None for doc_id, _run, order in items]
    seconds = {}
    for qid, items in plan.items():
        seconds[qid] = [{'doc_id': int(doc_id), 'chunk_text': second[(qid, doc_id, order)]}
                        for doc_id, _run, order in items if (qid, doc_id, order) in second]
    return out, lost, seconds


def allocate(sizes, mode, mean_target, adaptive, docs):
    """Per-query number of documents that get a chunk, mean about `mean_target`.

    sizes: {qid: number of documents submitted}. Fixed lists: min(size, target) everywhere. Adaptive lists:
    'cap' gives small queries all their documents and cuts the big ones at a common cap; 'prop' scales every
    query by the same factor. -> ({qid: count}, cap or None)."""
    if not adaptive:
        return {q: min(s, int(mean_target)) for q, s in sizes.items()}, None
    if mode == 'prop':
        return {q: min(s, round(s * mean_target / docs)) for q, s in sizes.items()}, None
    values = np.array(list(sizes.values()))
    cap = 0
    for candidate in range(1, int(values.max()) + 1 if len(values) else 1):
        if np.minimum(values, candidate).mean() > mean_target:
            break
        cap = candidate
    return {q: min(s, cap) for q, s in sizes.items()}, cap


def fit_bytes(cut, takes, mode, target_bytes, base_bytes):
    """Shrink the per-query chunk counts (same rule as `mode`) until the JSON fits in `target_bytes`.

    -> ({qid: count}, cap or share used, total bytes)."""
    qids = list(takes)
    longest = max([takes[q] for q in qids] + [1])
    cum = np.zeros((len(qids), longest + 1), dtype=np.int64)
    for row, q in enumerate(qids):
        sizes = [len(json.dumps(c, ensure_ascii=False).encode('utf-8')) + 2 if c else 0 for c in cut[q][:takes[q]]]
        line = np.concatenate([[0], np.cumsum(sizes, dtype=np.int64)])
        cum[row, :len(line)] = line
        cum[row, len(line):] = line[-1]
    limit = np.array([takes[q] for q in qids])
    index = np.arange(len(qids))

    def total(counts):
        return base_bytes + int(cum[index, counts].sum())

    if mode == 'prop':
        low, high = 0.0, 1.0
        if total(limit) <= target_bytes:
            return dict(zip(qids, limit.tolist())), 1.0, total(limit)
        for _ in range(40):
            middle = (low + high) / 2
            if total(np.round(limit * middle).astype(int)) <= target_bytes:
                low = middle
            else:
                high = middle
        counts = np.round(limit * low).astype(int)
        return dict(zip(qids, counts.tolist())), round(low, 4), total(counts)
    best = 0
    for cap in range(0, longest + 1):
        if total(np.minimum(limit, cap)) > target_bytes:
            break
        best = cap
    counts = np.minimum(limit, best)
    return dict(zip(qids, counts.tolist())), best, total(counts)


def main():
    # Chấp nhận cờ bị dán sai gạch (---out, —out, –out, -out) do lỗi khi copy lệnh: đưa về --out.
    sys.argv = [sys.argv[0]] + [re.sub(r'^[-\u2010-\u2015\u2212]+(?=[A-Za-z]{2})', '--', arg)
                                for arg in sys.argv[1:]]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Bỏ trống (hoặc biến PowerShell rỗng) thì dùng bộ mặc định của đội: 5 lượt chấm 4B, 14 run, lo_004.
    parser.add_argument('--pairs', nargs='*', default=[])
    parser.add_argument('--scores', nargs='*', default=[])
    parser.add_argument('--runs', nargs='*', default=[])
    parser.add_argument('--text-runs', nargs='*', default=None)
    parser.add_argument('--mix', type=float, default=0.5)
    parser.add_argument('--encoder', default='bge-m3', help='Thư mục index/<encoder> dùng để lấy embedding.')
    parser.add_argument('--seeds', type=int, default=10, help='Số tài liệu đầu dùng làm chủ đề.')
    parser.add_argument('--pool', type=int, default=600, help='Chỉ xếp lại ngần này tài liệu đầu theo 4B mỗi câu.')
    parser.add_argument('--weight', type=float, default=1.0, help='Trọng số độ giống chủ đề (0 = thứ tự 4B).')
    parser.add_argument('--docs', type=int, default=190, help='Số tài liệu nộp mỗi câu.')
    parser.add_argument('--expand', type=int, default=0,
                        help='Tìm thêm ngần này tài liệu MỚI mỗi câu (chưa có trong danh sách 4B) bằng cách quét toàn bộ '
                             'chunk của các run theo vector chủ đề. Tài liệu mới chưa có điểm 4B nên được gán điểm 4B '
                             'bằng tài liệu ở hạng --docs, chỉ lọt vào danh sách khi rất giống chủ đề. 0 = tắt.')
    parser.add_argument('--adaptive', action='store_true',
                        help='Số tài liệu mỗi câu theo điểm 4B (trung bình vẫn = --docs), kẹp trong [--min-docs, --max-docs].')
    parser.add_argument('--adaptive-rule', choices=['count', 'f2'], default='count',
                        help='Cách chọn số tài liệu mỗi câu khi --adaptive (xem đầu file).')
    parser.add_argument('--pool-recall', type=float, default=0.73,
                        help='Tỉ lệ đáp án nằm trong pool (đo được 0,73), dùng cho --adaptive-rule f2.')
    parser.add_argument('--min-docs', type=int, default=60)
    parser.add_argument('--max-docs', type=int, default=400)
    parser.add_argument('--chunk-docs', type=int, default=0,
                        help='Trung bình số tài liệu có chunk mỗi câu, theo thứ tự PRF (0 = chỉ tài liệu).')
    parser.add_argument('--chunk-mode', choices=['cap', 'prop'], default='cap',
                        help='Cách chia chunk giữa các câu khi --adaptive (xem đầu file).')
    parser.add_argument('--chunk-mb', type=float, default=0,
                        help='Tự chọn số chunk để file JSON (chưa nén) khoảng ngần này MB, theo đúng cách chia '
                             '--chunk-mode; vd. hệ số nén 10,5 và muốn file nén ~97 MB thì --chunk-mb 1020. '
                             'Dùng cùng --chunk-docs thì --chunk-docs là mức tối đa.')
    parser.add_argument('--window-tokens', type=int, default=1000)
    parser.add_argument('--second-weight', type=float, default=0.0,
                        help='Điểm tài liệu = điểm đoạn tốt nhất + ngần này × điểm đoạn tốt thứ hai (chỉ ảnh hưởng thứ tự; '
                             'tài liệu có nhiều đoạn 4B chấm cao được đẩy lên). 0 = tắt.')
    parser.add_argument('--extra-windows', type=int, default=0,
                        help='Thêm cửa sổ thứ hai (quanh đoạn 4B tốt thứ hai, nếu nằm ngoài cửa sổ đầu) cho ngần này '
                             'tài liệu đầu mỗi câu. Dung lượng của chúng được trừ trước khi --chunk-mb chọn số tài liệu có chunk.')
    parser.add_argument('--zh-scale', type=float, default=1.0,
                        help='Nhân điểm 4B của tài liệu tiếng Trung (id 766442–4420561) với hệ số này trước khi xếp hạng và '
                             'chọn số tài liệu (đo được: tài liệu zh đúng ~11%% so với ~19%% của tiếng Việt -> thử 0.6).')
    parser.add_argument('--export-extra', default='',
                        help='Thư mục: KHÔNG tạo bài nộp, mà xuất pairs.parquet các đoạn CHƯA chấm của tài liệu gần hạng cắt '
                             'để chấm 4B thêm trên Kaggle. Điểm trả về đặt ở work/rerank_extra/ sẽ được tự dùng.')
    parser.add_argument('--band', type=float, nargs=2, default=[0.6, 1.6],
                        help='Vùng hạng (nhân với số tài liệu của câu) được chấm thêm, mặc định 0.6 1.6.')
    parser.add_argument('--extra-per-doc', type=int, default=1, help='Số đoạn mới mỗi tài liệu (--export-extra).')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--out')
    args = parser.parse_args()
    if not args.out and not args.export_extra:
        parser.error('Cần --out (hoặc --export-extra)')
    if not args.pairs and not args.scores and glob.glob('work/rerank_extra/scores*.parquet') \
            and Path('work/rerank_extra/pairs.parquet').exists():
        # Extra 4B pass (--export-extra) already scored: use it automatically.
        args.pairs = [f'work/{name}/pairs.parquet' for name in DEFAULT_POOLS] + ['work/rerank_extra/pairs.parquet']
        args.scores = [f'work/{name}/scores.parquet' for name in DEFAULT_POOLS] + ['work/rerank_extra/scores*.parquet']
    args.pairs = args.pairs or [f'work/{name}/pairs.parquet' for name in DEFAULT_POOLS]
    args.scores = args.scores or [f'work/{name}/scores.parquet' for name in DEFAULT_POOLS]
    args.runs = args.runs or [f'work/{name}' for name in DEFAULT_RUNS]
    args.text_runs = ['lo_004'] if args.text_runs is None else args.text_runs
    missing = [path for path in args.pairs + args.scores + args.runs if not glob.glob(path)]
    if missing:
        parser.error(f'Không thấy: {missing[:5]} — chạy lệnh ở thư mục gốc repo.')
    if args.adaptive and not args.min_docs <= args.docs <= args.max_docs:
        parser.error('Cần --min-docs <= --docs <= --max-docs')
    started = time.time()

    runs = {Path(run).name: run for run in args.runs}
    table = read_pairs(args.pairs, ['qid', 'doc_id', 'run', 'chunk_order', 'old_score'])
    pairs = list(zip(*(table[c].to_pylist() for c in table.column_names)))
    all_scores = load_scores(args.scores)
    ranked, scored = rank_documents(pairs, all_scores, args.mix)
    del table
    emit(f'Cặp có điểm 4B: {scored:,} | câu có xếp hạng: {len(ranked)}')
    query_ids = [int(row['id']) for row in load_queries(args.queries)]
    if args.zh_scale != 1.0:
        for qid, items in ranked.items():
            items = [((v * args.zh_scale) if ZH_LOW <= int(d) <= ZH_HIGH else v, d, r, o) for v, d, r, o in items]
            ranked[qid] = sorted(items, key=lambda item: (-item[0], item[1]))
    pools = {qid: ranked.get(qid, [])[:args.pool] for qid in query_ids}
    need_passages = args.second_weight or args.extra_windows or args.export_extra
    passages = pool_passages(pairs, all_scores, args.mix, pools) if need_passages else {}
    old_best = {}
    if args.export_extra:
        in_pool = {(qid, int(d)) for qid, pool in pools.items() for _v, d, _r, _o in pool}
        for qid, doc_id, run, _order, old in pairs:
            if (int(qid), int(doc_id)) in in_pool and old is not None and np.isfinite(old):
                key = (int(qid), int(doc_id), run)
                old_best[key] = max(old, old_best.get(key, float('-inf')))
    del pairs, all_scores
    limits, threshold = {}, None
    pool_totals = {qid: float(sum(v for v, _d, _r, _o in pool)) for qid, pool in pools.items()}
    if args.adaptive and args.adaptive_rule == 'count':
        # Counted on the 4B pool only (before --expand appends documents with an imputed value).
        limits, threshold = adaptive_counts(pools, args.docs, args.min_docs, args.max_docs)

    sims, new_docs = {}, {}
    if args.weight:
        # Pass 1: seed vectors (best passage of the top documents) -> one topic vector per query.
        seeds = {qid: [(d, r, o) for _v, d, r, o in pool if r in runs][:args.seeds] for qid, pool in pools.items()}
        sums = {}
        for name, run in runs.items():
            wanted = [(qid, d, o) for qid, items in seeds.items() for d, r, o in items if r == name]
            if not wanted:
                continue
            index = RunIndex(run, args.encoder)
            for qid, doc_id, order in wanted:
                row = index.row_of(doc_id, order)
                if row is not None:
                    vector = np.asarray(index.emb[row], dtype=np.float32)
                    total, count = sums.get(qid, (0, 0))
                    sums[qid] = (total + vector, count + 1)
            del index
        centroids = {}
        for qid, (total, count) in sums.items():
            norm = np.linalg.norm(total)
            if count and norm > 0:
                centroids[qid] = (total / norm).astype(np.float32)
        emit(f'Vector chủ đề: {len(centroids)}/{len(query_ids)} câu (pass 1 xong sau {time.time() - started:.0f} giây)')
        if args.expand and centroids:
            # Expansion: documents anywhere in the runs that are close to the topic but missing from the 4B pool.
            order_q = sorted(centroids)
            matrix = np.stack([centroids[q] for q in order_q])
            in_pool = {q: {int(d) for _v, d, _r, _o in pools[q]} for q in order_q}
            fresh = {q: {} for q in order_q}
            for name, run in runs.items():
                index = RunIndex(run, args.encoder)
                for q, best in zip(order_q, expand_run(index, matrix, args.expand)):
                    for doc_id, (value, order) in best.items():
                        if doc_id not in in_pool[q] and (doc_id not in fresh[q] or value > fresh[q][doc_id][0]):
                            fresh[q][doc_id] = (value, name, order)
                emit(f'  quét {name}: {len(index.emb):,} chunk')
                del index
            added_total = 0
            for q in order_q:
                pool = pools[q]
                cut = pool[min(args.docs, len(pool)) - 1][0] if pool else 0.0
                extra = sorted(fresh[q].items(), key=lambda item: -item[1][0])[:args.expand]
                for doc_id, (value, name, order) in extra:
                    pool.append((cut, doc_id, name, order))
                    sims[(q, doc_id)] = value
                added_total += len(extra)
                new_docs[q] = {doc_id for doc_id, _x in extra}
            emit(f'Ứng viên mới từ quét chủ đề: {added_total / max(1, len(order_q)):.1f} tài liệu/câu')
        # Pass 2: topic similarity of every candidate document, run by run.
        for name, run in runs.items():
            wanted = [(qid, d) for qid, pool in pools.items() if qid in centroids
                      for _v, d, r, _o in pool if r == name and (qid, d) not in sims]
            if not wanted:
                continue
            index = RunIndex(run, args.encoder)
            for qid, doc_id in wanted:
                value = index.best_cosine(doc_id, centroids[qid])
                if value is not None:
                    sims[(qid, doc_id)] = value
            emit(f'  {name}: {len(wanted):,} tài liệu ứng viên')
            del index

    want_chunks = bool(args.chunk_docs or args.chunk_mb)
    orders = {}
    for qid in query_ids:
        pool = pools[qid]
        if not pool:
            continue
        if args.second_weight:
            # Second-best scored passage of the same document (any run), 0 when there is none.
            seconds = [passages.get((qid, int(d)), [])[1:2] for _v, d, _r, _o in pool]
            base = zscore([v + args.second_weight * (s[0][0] if s else 0.0)
                           for (v, _d, _r, _o), s in zip(pool, seconds)])
        else:
            base = zscore([v for v, _d, _r, _o in pool])
        if args.weight and any((qid, d) in sims for _v, d, _r, _o in pool):
            raw = [sims.get((qid, d)) for _v, d, _r, _o in pool]
            known = [x for x in raw if x is not None]
            mean = float(np.mean(known))
            topic = zscore([mean if x is None else x for x in raw])
            final = base + args.weight * topic
        else:
            final = base
        orders[qid] = sorted(range(len(pool)), key=lambda i: (-final[i], pool[i][1]))

    if args.adaptive and args.adaptive_rule == 'f2':
        ranked_values = {q: [pools[q][i][0] for i in order] for q, order in orders.items()}
        limits, threshold = f2_counts(ranked_values, pool_totals, args.docs, args.min_docs, args.max_docs,
                                      args.pool_recall)
    if args.adaptive and limits:
        values = np.array(sorted(limits.values()))
        label = f'ngưỡng điểm 4B T = {threshold:.4f}' if args.adaptive_rule == 'count' else f'hệ số c = {threshold:.4g}'
        emit(f'--adaptive ({args.adaptive_rule}): {label}; số tài liệu/câu: trung bình {values.mean():.1f}, '
             f'p10 {np.percentile(values, 10):.0f}, p25 {np.percentile(values, 25):.0f}, '
             f'trung vị {np.median(values):.0f}, p75 {np.percentile(values, 75):.0f}, p90 {np.percentile(values, 90):.0f}; '
             f'chạm --min-docs: {int((values <= args.min_docs).sum())} câu, chạm --max-docs: '
             f'{int((values >= args.max_docs).sum())} câu')

    if args.export_extra:
        if not args.weight:
            raise SystemExit('--export-extra cần vector chủ đề (--weight > 0).')
        export_extra(args, query_ids, pools, orders, limits, passages, old_best, centroids, runs, args.export_extra)
        return

    rows, moved, chosen_new, ordered = [], [], [], {}
    for qid in query_ids:
        pool = pools[qid]
        if not pool:
            rows.append({'id': qid, 'relevant_docs': [], 'relevant_chunks': []})
            continue
        order = orders[qid]
        limit = limits.get(qid, args.docs) if args.adaptive else args.docs
        chosen = [int(pool[i][1]) for i in order[:limit]]
        moved.append(len(set(chosen) - {int(p[1]) for p in pool[:limit]}))
        chosen_new.append(len(set(chosen) & new_docs.get(qid, set())))
        if want_chunks:
            ordered[qid] = [(int(pool[i][1]), pool[i][2], int(pool[i][3])) for i in order[:limit]]
        rows.append({'id': qid, 'relevant_docs': chosen, 'relevant_chunks': []})

    chunk_tokens, lost, chunk_cap, chunk_share = [], 0, None, None
    if want_chunks:
        sizes = {q: len(items) for q, items in ordered.items()}
        if args.chunk_docs:
            takes, chunk_cap = allocate(sizes, args.chunk_mode, args.chunk_docs, args.adaptive, args.docs)
        else:
            takes = dict(sizes)  # every submitted document, trimmed to --chunk-mb below
        plan = {q: ordered[q][:takes[q]] for q in ordered}
        emit(f'Cắt chunk cho {sum(map(len, plan.values())) / max(1, len(plan)):.1f} tài liệu/câu '
             f'(cửa sổ {args.window_tokens} token)')
        extra = {}
        if args.extra_windows:
            # Best other scored passage of the same document in the same run as its first window.
            for q, items in plan.items():
                for doc_id, run, order in items[:args.extra_windows]:
                    if run in args.text_runs:
                        continue
                    for _v, other_run, other in passages.get((q, doc_id), []):
                        if other_run == run and other != order:
                            extra[(q, doc_id)] = other
                            break
        cut, lost, seconds = cut_chunks(plan, runs, set(args.text_runs), args.pairs, args.window_tokens, extra)
        if args.extra_windows:
            emit(f'Cửa sổ thứ hai: {sum(map(len, seconds.values())) / max(1, len(plan)):.2f} mỗi câu '
                 f'({len(extra) / max(1, len(plan)):.2f} tài liệu/câu có đoạn 4B thứ hai; đoạn nào nằm trong cửa sổ đầu thì bỏ)')
        if args.chunk_mb:
            base_bytes = sum(len(json.dumps(r, ensure_ascii=False).encode('utf-8')) + 2 for r in rows) + 4
            base_bytes += sum(len(json.dumps(c, ensure_ascii=False).encode('utf-8')) + 2
                              for items in seconds.values() for c in items)
            mode = args.chunk_mode if args.adaptive else 'cap'
            takes, used, total = fit_bytes(cut, takes, mode, int(args.chunk_mb * 1e6), base_bytes)
            if mode == 'cap':
                chunk_cap = used
            else:
                chunk_share = used
            emit(f'--chunk-mb {args.chunk_mb:g}: '
                 + (f'trần {used} tài liệu có chunk mỗi câu' if mode == 'cap' else f'mỗi câu chunk {100 * used:.1f}% số tài liệu')
                 + f', JSON dự kiến {total / 1e6:.0f} MB')
        if args.adaptive and chunk_cap is not None:
            emit(f'  {sum(1 for q in takes if takes[q] < sizes[q])} câu bị cắt ở trần {chunk_cap}')
        for row in rows:
            q = row['id']
            row['relevant_chunks'] = [c for c in cut.get(q, [])[:takes.get(q, 0)] if c]
            with_first = {c['doc_id'] for c in row['relevant_chunks']}
            row['relevant_chunks'] += [c for c in seconds.get(q, []) if c['doc_id'] in with_first]
            chunk_tokens.extend(schema.count_tokens(c['chunk_text']) for c in row['relevant_chunks'])
        del cut
        chunk_tokens.sort()

    problems = schema.validate_submission_shape(rows, query_ids)
    if problems:
        raise ValueError('; '.join(problems[:5]))
    official = set(pq.read_table(args.links, columns=['id'])['id'].to_pylist())
    outside = {d for r in rows for d in r['relevant_docs']} - official
    if outside:
        raise ValueError(f'{len(outside)} id không có trong links_corpus, ví dụ {sorted(outside)[:5]}')
    # With chunks the file is always re-compressed by rezip_lzma.py afterwards, so a fast zip is enough here
    # (LZMA would cost several minutes for nothing).
    json_path, zip_path = write_streaming(rows, args.out, lzma=not want_chunks)
    n = max(1, len(rows))
    counts = np.array([len(r['relevant_docs']) for r in rows]) if rows else np.zeros(1)
    spread = {'p10': int(np.percentile(counts, 10)), 'p25': int(np.percentile(counts, 25)),
              'median': int(np.median(counts)), 'p75': int(np.percentile(counts, 75)),
              'p90': int(np.percentile(counts, 90)), 'min': int(counts.min()), 'max': int(counts.max())}
    if args.adaptive:
        spread['queries_at_min_docs'] = int((counts <= args.min_docs).sum())
        spread['queries_at_max_docs'] = int((counts >= args.max_docs).sum())
    summary = {'weight': args.weight, 'seeds': args.seeds, 'pool': args.pool, 'docs': args.docs, 'mix': args.mix,
               'encoder': args.encoder, 'queries_with_topic': len({q for q, _d in sims}),
               'docs_changed_vs_4b_per_query': round(float(np.mean(moved)), 1) if moved else 0,
               'expand': args.expand,
               'expanded_docs_chosen_per_query': round(float(np.mean(chosen_new)), 1) if chosen_new else 0,
               'adaptive': args.adaptive,
               'adaptive_rule': args.adaptive_rule if args.adaptive else None,
               'adaptive_threshold': round(threshold, 6) if threshold is not None else None,
               'min_docs': args.min_docs if args.adaptive else None,
               'max_docs': args.max_docs if args.adaptive else None,
               'docs_per_query': round(sum(len(r['relevant_docs']) for r in rows) / n, 1),
               'docs_per_query_spread': spread,
               'chunk_docs': args.chunk_docs, 'chunk_mb': args.chunk_mb,
               'window_tokens': args.window_tokens if want_chunks else None,
               'chunk_mode': (args.chunk_mode if args.adaptive else 'fixed') if want_chunks else None,
               'chunk_cap': chunk_cap, 'chunk_share': chunk_share,
               'chunks_per_query': round(sum(len(r['relevant_chunks']) for r in rows) / n, 1),
               'zh_scale': args.zh_scale,
               'chunks_lost': lost, 'second_weight': args.second_weight, 'extra_windows': args.extra_windows,
               'chunk_tokens_median': chunk_tokens[len(chunk_tokens) // 2] if chunk_tokens else 0,
               'json_mb': round(json_path.stat().st_size / 1e6, 1),
               'zip_mb': round(zip_path.stat().st_size / 1e6, 2), 'minutes': round((time.time() - started) / 60, 1)}
    storage.write_json(Path(args.out) / 'prf_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    if want_chunks:
        emit(f'\nCó chunk: file zip này CHƯA nén kỹ. Nén bằng: rezip_lzma.py {zip_path} '
             f'{Path(args.out).as_posix()}_small/submission.zip --dict-mb 512 (phải < 100 MB) rồi nộp bản _small.')
    else:
        emit(f'\nNộp file (chỉ có tài liệu, đọc DOCS_F2MACRO): {zip_path}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
