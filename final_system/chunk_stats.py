"""Thống kê nhanh một hay nhiều bài nộp: mã nội dung, số tài liệu/chunk mỗi câu, độ dài chunk.

- "Mã nội dung" tính trên file JSON bên trong zip, nên hai file cùng nội dung nhưng nén khác nhau
  (vd. bản gốc và bản _small sau rezip_lzma.py) có cùng mã.
- Độ dài chunk (token, cùng cách đếm với --window-tokens) cho biết cửa sổ dài bao nhiêu: bản dựng với
  --window-tokens 2500 có chunk dài nhất khoảng 2500 và gần như không có chunk > 2600; bản 3000 thì có.

Ví dụ (ở thư mục gốc repo; dấu * được script tự mở rộng):
  .\\env\\Scripts\\python.exe chunk_stats.py "work/final_p4_w*/submission.zip" "work/final_p4_w*_small/submission.zip"
"""
import glob
import gc
import hashlib
import statistics
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT))

from vibiomir.common import schema  # noqa: E402
from merge_submissions import read_rows  # noqa: E402


def content_md5(path):
    digest = hashlib.md5()
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive, archive.open(archive.namelist()[0]) as handle:
            while block := handle.read(1 << 22):
                digest.update(block)
    else:
        with open(path, 'rb') as handle:
            while block := handle.read(1 << 22):
                digest.update(block)
    return digest.hexdigest()[:10]


def percentile(values, share):
    return values[min(len(values) - 1, int(share * len(values)))] if values else 0


def stats(path):
    rows = read_rows(path)
    n = max(1, len(rows))
    docs = sum(len(r['relevant_docs']) for r in rows) / n
    chunks = sum(len(r['relevant_chunks']) for r in rows) / n
    # Every 4th query is plenty to see the window size, and keeps this fast.
    lengths = sorted(schema.count_tokens(c['chunk_text']) for r in rows[::4] for c in r['relevant_chunks'])
    del rows
    gc.collect()
    total = max(1, len(lengths))
    return {'docs': docs, 'chunks': chunks, 'p50': percentile(lengths, 0.5), 'p90': percentile(lengths, 0.9),
            'max': lengths[-1] if lengths else 0,
            'over1024': 100 * sum(1 for x in lengths if x > 1024) / total,
            'over2600': 100 * sum(1 for x in lengths if x > 2600) / total}


def main():
    if len(sys.argv) < 2:
        sys.exit('Cách dùng: chunk_stats.py <bài nộp hoặc mẫu có dấu *> ...')
    paths = []
    for pattern in sys.argv[1:]:
        found = sorted(glob.glob(pattern, recursive=True)) or ([pattern] if Path(pattern).exists() else [])
        if not found:
            print(f'(không thấy file nào khớp {pattern})')
        paths += [p for p in found if p not in paths]
    print(f"{'file':<58} {'MB':>6} {'mã nội dung':>11} {'tl/câu':>7} {'chunk/câu':>9} "
          f"{'token: trung vị':>15} {'p90':>5} {'max':>5} {'%>1024':>7} {'%>2600':>7}")
    for path in paths:
        try:
            s = stats(path)
            md5 = content_md5(path)
        except Exception as error:  # noqa: BLE001 - report and continue with the next file
            print(f'{path:<58} lỗi: {error}')
            continue
        size = Path(path).stat().st_size / 1e6
        print(f"{path:<58} {size:6.1f} {md5:>11} {s['docs']:7.1f} {s['chunks']:9.1f} {s['p50']:15d} "
              f"{s['p90']:5d} {s['max']:5d} {s['over1024']:6.1f}% {s['over2600']:6.1f}%")
    print('\nCùng "mã nội dung" = cùng nội dung (dù dung lượng khác do cách nén).')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
