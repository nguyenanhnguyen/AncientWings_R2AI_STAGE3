"""Tìm tài liệu tiếng Việt CHƯA crawl được bằng chữ trong URL (slug), không cần tải trang. Không cần GPU.

Khoảng 210 nghìn id tiếng Việt (nhathuoclongchau, laodong, vov, youmed...) bị chặn nên chưa từng vào
pipeline, nhưng URL của chúng thường chứa nguyên tiêu đề bài viết, ví dụ
  nhathuoclongchau.com.vn/bai-viet/xet-nghiem-beta-hcg-la-gi-co-can-thiet-khong-63326.html
Script bỏ dấu câu hỏi và slug, chấm BM25 trên từ đơn + cặp từ liền nhau, rồi ghi bài nộp CHỈ GỒM TÀI
LIỆU (không chunk, vì không có văn bản) để nộp riêng đo DOCS_PRECISION hoặc gộp vào bài chính bằng "=0:0".

Id coi là "đã crawl" (bị bỏ qua) = mọi id trong corpus/corpus.parquet của các --runs và mọi tài liệu
của các bài nộp --crawled-submissions (vd. lô 0,04 không còn thư mục run).

Ví dụ (PowerShell, ở thư mục gốc repo):

  # 1) Xem phân bố điểm, chưa ghi file
  .\\env\\Scripts\\python.exe slug_retrieval.py --runs "work/run_*" --crawled-submissions lo_004_win1000/submission.zip --report

  # 2) Bài nộp 10 tài liệu mỗi câu
  .\\env\\Scripts\\python.exe slug_retrieval.py --runs "work/run_*" --crawled-submissions lo_004_win1000/submission.zip --top 10 --out work/slug_top10
"""
import argparse
import collections
import glob
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import scipy.sparse as sp

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402
from merge_submissions import read_rows, write_streaming  # noqa: E402

VI_MAX_ID = 766443  # id tiếng Việt của kho rút gọn: 0..766441
URL_NOISE = {'html', 'htm', 'ldo', 'vov', 'aspx', 'php', 'amp', 'www', 'https', 'http', 'bai', 'viet',
             'tin', 'tuc', 'post', 'news', 'chi', 'tiet'}
STOP = set('va la co cho khi nhung cac mot duoc trong voi khong de nay thi bi o ve tai tu nhu hay nao gi '
           'sao lam cua the em toi minh a a ah oi xin hoi bac si nhe vay roi da dang se'.split())


def fold(text):
    text = text.lower().replace('đ', 'd')
    return ''.join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')


def words_of(text):
    return [w for w in re.split(r'[^a-z0-9]+', fold(text)) if w]


def slug_words(url):
    path = re.sub(r'^https?://[^/]+', '', url)
    return [w for w in words_of(path)
            if w not in URL_NOISE and not w.isdigit() and not re.fullmatch(r'[a-z]{0,2}\d+[a-z0-9]*', w)]


def features(words):
    unigrams = [w for w in words if w not in STOP and not w.isdigit()]
    bigrams = [f'{a}_{b}' for a, b in zip(words, words[1:])]
    return unigrams + bigrams


def crawled_ids(run_patterns, submissions):
    ids = set()
    runs = sorted({p for pattern in run_patterns for p in (glob.glob(pattern) or [pattern])})
    for run in runs:
        path = Path(run) / 'corpus' / 'corpus.parquet'
        if path.exists():
            found = pq.read_table(path, columns=['id'])['id'].to_pylist()
            ids.update(found)
            emit(f'  {run}: {len(found):,} id đã crawl')
    for path in submissions:
        found = {int(d) for row in read_rows(path) for d in row['relevant_docs']}
        ids.update(found)
        emit(f'  {path}: {len(found):,} id có trong bài nộp')
    return ids


def build_index(doc_words):
    vocab, rows, cols, vals = {}, [], [], []
    for j, words in enumerate(doc_words):
        for term, count in collections.Counter(features(words)).items():
            rows.append(j)
            cols.append(vocab.setdefault(term, len(vocab)))
            vals.append(count)
    n = len(doc_words)
    tf = sp.coo_matrix((np.array(vals, np.float32), (rows, cols)), shape=(n, len(vocab)))
    df = np.bincount(tf.col, minlength=len(vocab))
    idf = np.log1p((n - df + 0.5) / (df + 0.5)).astype(np.float32)
    lengths = np.asarray(tf.tocsr().sum(1)).ravel()
    k1, b = 1.2, 0.75
    weight = tf.data * (k1 + 1) / (tf.data + k1 * (1 - b + b * lengths[tf.row] / max(1e-9, lengths.mean())))
    matrix = sp.csr_matrix((weight * idf[tf.col], (tf.col, tf.row)), shape=(len(vocab), n))
    return vocab, matrix


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--links', default='data/links_corpus_vi_en_zh.parquet')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--runs', nargs='*', default=['work/run_*'], help='Thư mục run (nhận cả mẫu "work/run_*").')
    parser.add_argument('--crawled-submissions', nargs='*', default=[])
    parser.add_argument('--top', type=int, default=10, help='Số tài liệu tối đa mỗi câu.')
    parser.add_argument('--pool', type=int, default=100,
                        help='Số ứng viên mỗi câu ghi vào slug_scores.jsonl (cho slug_rerank.py export).')
    parser.add_argument('--min-score', type=float, default=0.0)
    parser.add_argument('--out')
    parser.add_argument('--report', action='store_true')
    args = parser.parse_args()
    if not args.report and not args.out:
        parser.error('Cần --out (hoặc --report).')

    links = pq.read_table(args.links, columns=['id', 'url'])
    emit('Đọc các id đã crawl:')
    done = crawled_ids(args.runs, args.crawled_submissions)
    doc_ids, doc_words = [], []
    for doc_id, url in zip(links['id'].to_pylist(), links['url'].to_pylist()):
        if doc_id <= VI_MAX_ID and doc_id not in done:
            words = slug_words(url or '')
            if len(words) >= 3:
                doc_ids.append(doc_id)
                doc_words.append(words)
    emit(f'Tài liệu tiếng Việt chưa crawl có slug dùng được: {len(doc_ids):,}')
    vocab, matrix = build_index(doc_words)

    queries = load_queries(args.queries)
    results = {}
    for row in queries:
        terms = [vocab[t] for t in set(features(words_of(row['query']))) if t in vocab]
        if not terms:
            results[int(row['id'])] = []
            continue
        scores = np.asarray(matrix[terms].sum(0)).ravel()
        depth = max(200, args.pool)
        top = np.argpartition(-scores, min(len(scores) - 1, depth))[:depth]
        top = top[np.argsort(-scores[top])]
        results[int(row['id'])] = [(float(scores[i]), doc_ids[i]) for i in top if scores[i] > 0]

    if args.report:
        emit('\nĐiểm BM25 của tài liệu hạng N (trung vị qua các câu):')
        for n in (1, 3, 5, 10, 20, 30, 50):
            values = [r[n - 1][0] for r in results.values() if len(r) >= n]
            emit(f'  hạng {n:3d}: {np.median(values):.1f}' if values else f'  hạng {n:3d}: -')
        emit('\nSố tài liệu mỗi câu nếu cắt theo ngưỡng (tối đa --top):')
        for floor in (20, 30, 40, 50, 60, 80):
            counts = [sum(1 for s, _d in r[:args.top] if s >= floor) for r in results.values()]
            emit(f'  >= {floor:3d}: trung bình {np.mean(counts):5.1f}, câu có 0: {sum(1 for c in counts if c == 0)}')
        return

    rows = [{'id': qid, 'relevant_docs': [d for s, d in found[:args.top] if s >= args.min_score],
             'relevant_chunks': []} for qid, found in results.items()]
    problems = schema.validate_submission_shape(rows, [int(r['id']) for r in queries])
    if problems:
        raise ValueError('; '.join(problems[:5]))
    _json, zip_path = write_streaming(rows, args.out, lzma=True)
    storage.write_jsonl(Path(args.out) / 'slug_scores.jsonl',
                        [{'query_id': qid, 'docs': [[d, round(s, 3)] for s, d in found[:args.pool]]}
                         for qid, found in results.items()])
    counts = [len(r['relevant_docs']) for r in rows]
    summary = {'uncrawled_vi_docs': len(doc_ids), 'top': args.top, 'min_score': args.min_score,
               'docs_mean': round(float(np.mean(counts)), 2), 'queries_without_docs': sum(1 for c in counts if not c)}
    storage.write_json(Path(args.out) / 'slug_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nNộp file: {zip_path}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
