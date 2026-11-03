"""Bài B bỏ những tài liệu nào của bài A, và chúng nằm ở đâu trong danh sách của A.

relevant_docs của bài nộp giữ đúng thứ tự xếp hạng (PRF), nên hạng tương đối của một tài liệu trong câu =
hạng / số tài liệu của câu (0 = đầu danh sách, 1 = ngưỡng cắt). Script in, theo từng khoảng hạng tương đối của
A, tỉ lệ tài liệu bị B bỏ ra. Dùng để xem mô hình thứ hai (8B) có làm rơi tài liệu ở top hay chỉ đổi quanh ngưỡng
cắt: nếu tỉ lệ bị bỏ giảm nhanh khi đi lên top thì chấm lại phần top bằng 8B gần như không đổi được gì.

Ví dụ (ở thư mục gốc repo):
  .\\env\\Scripts\\python.exe rank_drop.py work/prf/f2_x50_rx_small/submission.zip work/prf/f2_x50_rx_8b_small/submission.zip
"""
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from merge_submissions import read_rows  # noqa: E402

EDGES = (0.0, 0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def doc_lists(path):
    """{query_id: [doc_id, ...] in submission order}; chunks are dropped right away to save memory."""
    rows = read_rows(path)
    out = {int(row['id']): [int(d) for d in row['relevant_docs']] for row in rows}
    del rows
    return out


def main():
    sys.argv = [sys.argv[0]] + [re.sub(r'^[-‐-―−]+(?=[A-Za-z]{2})', '--', arg)
                                for arg in sys.argv[1:]]
    if len(sys.argv) != 3:
        sys.exit('Cách dùng: rank_drop.py <bài A (gốc)> <bài B (mới)>')
    a, b = doc_lists(sys.argv[1]), doc_lists(sys.argv[2])
    total = np.zeros(len(EDGES) - 1, dtype=np.int64)
    dropped = np.zeros(len(EDGES) - 1, dtype=np.int64)
    added_pos = []  # relative rank in B of documents B added
    n_change, n_drop, n_add = [], [], []
    for qid, docs_a in a.items():
        docs_b = b.get(qid, [])
        set_b, set_a = set(docs_b), set(docs_a)
        size = max(1, len(docs_a))
        for rank, doc_id in enumerate(docs_a):
            bucket = min(int(np.searchsorted(EDGES, rank / size, side='right')) - 1, len(total) - 1)
            total[bucket] += 1
            if doc_id not in set_b:
                dropped[bucket] += 1
        added_pos.extend(rank / max(1, len(docs_b)) for rank, d in enumerate(docs_b) if d not in set_a)
        n_change.append(len(docs_b) - len(docs_a))
        n_drop.append(len(set_a - set_b))
        n_add.append(len(set_b - set_a))
    n = max(1, len(a))
    print(f'A: {sys.argv[1]}\nB: {sys.argv[2]}')
    print(f'Mỗi câu: B bỏ {np.mean(n_drop):.1f} tài liệu của A, thêm {np.mean(n_add):.1f} tài liệu mới; '
          f'số tài liệu B − A: trung bình {np.mean(n_change):+.1f}, câu có số tài liệu thay đổi: '
          f'{sum(1 for x in n_change if x)}/{n}')
    print(f"\n{'hạng tương đối trong A':<24} {'tài liệu/câu':>12} {'bị B bỏ/câu':>12} {'% bị bỏ':>8}")
    for i in range(len(total)):
        label = f'{EDGES[i]:.1f}–{EDGES[i + 1]:.1f} × N'
        share = 100 * dropped[i] / max(1, total[i])
        print(f'{label:<24} {total[i] / n:12.1f} {dropped[i] / n:12.2f} {share:7.1f}%')
    if added_pos:
        pos = np.array(added_pos)
        print(f'\nTài liệu mới của B nằm ở hạng tương đối (trong B): trung vị {np.median(pos):.2f}, '
              f'p10 {np.percentile(pos, 10):.2f}, p90 {np.percentile(pos, 90):.2f}; '
              f'trong nửa trên (< 0,5 × N): {100 * np.mean(pos < 0.5):.1f}%')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
