"""So sánh hai bài nộp: số tài liệu/chunk mỗi câu, bao nhiêu tài liệu/chunk khác nhau, độ dài chunk.

Ví dụ (ở thư mục gốc repo):
  .\\env\\Scripts\\python.exe compare_submissions.py work/final_p4_w2000_small/submission.zip work/final_base2000_small/submission.zip
"""
import hashlib
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import schema  # noqa: E402
from merge_submissions import read_rows  # noqa: E402


def summary(path):
    rows = {int(r['id']): r for r in read_rows(path)}
    docs = {q: set(map(int, r['relevant_docs'])) for q, r in rows.items()}
    chunks = {q: {(int(c['doc_id']), hashlib.md5(c['chunk_text'].encode('utf-8')).hexdigest())
                  for c in r['relevant_chunks']} for q, r in rows.items()}
    tokens = [schema.count_tokens(c['chunk_text']) for r in list(rows.values())[:300] for c in r['relevant_chunks']]
    return {'path': path, 'size_mb': Path(path).stat().st_size / 1e6, 'docs': docs, 'chunks': chunks,
            'tokens_median': statistics.median(tokens) if tokens else 0}


def main():
    if len(sys.argv) != 3:
        sys.exit('Cách dùng: compare_submissions.py <bài A> <bài B>')
    a, b = summary(sys.argv[1]), summary(sys.argv[2])
    n = len(a['docs'])
    for s in (a, b):
        print(f"{s['path']}: {s['size_mb']:.1f} MB | tài liệu/câu {sum(map(len, s['docs'].values())) / n:.1f} | "
              f"chunk/câu {sum(map(len, s['chunks'].values())) / n:.1f} | độ dài chunk (trung vị, token) {s['tokens_median']:.0f}")
    same_docs = sum(len(a['docs'][q] & b['docs'].get(q, set())) for q in a['docs'])
    same_chunks = sum(len(a['chunks'][q] & b['chunks'].get(q, set())) for q in a['chunks'])
    print(f"Tài liệu giống nhau: {same_docs / n:.1f}/câu | chunk giống hệt (cùng tài liệu, cùng nội dung): {same_chunks / n:.1f}/câu")
    if a['docs'] == b['docs'] and a['chunks'] == b['chunks']:
        print('=> HAI BÀI GIỐNG HỆT NHAU.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
