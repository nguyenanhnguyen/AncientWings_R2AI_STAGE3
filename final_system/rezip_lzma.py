"""Nén lại một submission.zip có sẵn bằng LZMA với TỪ ĐIỂN LỚN (mặc định 256 MB): file nhỏ hơn khoảng 30%.

Bài nộp lặp lại rất nhiều đoạn văn giống nhau ở các câu khác nhau (cùng một tài liệu được nộp cho nhiều
câu), nhưng LZMA mặc định chỉ "nhớ" 8 MB gần nhất nên không tận dụng được. Từ điển 256 MB nhớ được
phần lặp ở xa. Thử trên một bài nộp thật (600 MB JSON): 8 MB -> 72,0 MB; 64 MB -> 61,3 MB; 256 MB -> 51,2 MB.
Nội dung giữ nguyên từng byte (script tự kiểm tra lại). Nén mất khoảng 10-15 phút và cần khoảng 3 GB RAM.

Ví dụ (ở thư mục gốc repo):
  .\\env\\Scripts\\python.exe rezip_lzma.py work/final_w1500/submission.zip work/final_w1500_small/submission.zip
  .\\env\\Scripts\\python.exe rezip_lzma.py vào.zip ra.zip --dict-mb 128
"""
import argparse
import lzma
import struct
import re
import sys
import time
import zipfile
from pathlib import Path


class BigDictCompressor:
    """Drop-in for zipfile.LZMACompressor with a chosen dictionary size (standard LZMA, any reader opens it)."""

    dict_size = 256 << 20

    def __init__(self):
        self._props = lzma._encode_filter_properties(
            {'id': lzma.FILTER_LZMA1, 'preset': 6, 'dict_size': self.dict_size})
        self._comp = lzma.LZMACompressor(lzma.FORMAT_RAW, filters=[
            lzma._decode_filter_properties(lzma.FILTER_LZMA1, self._props)])
        self._header = struct.pack('<BBH', 9, 4, len(self._props)) + self._props

    def _with_header(self, data):
        if self._header is not None:
            data, self._header = self._header + data, None
        return data

    def compress(self, data):
        return self._with_header(self._comp.compress(data))

    def flush(self):
        return self._with_header(self._comp.flush())


def same_content(a_path, b_path, name):
    with zipfile.ZipFile(a_path) as a, zipfile.ZipFile(b_path) as b, a.open(name) as x, b.open(name) as y:
        while True:
            left, right = x.read(1 << 22), y.read(1 << 22)
            if left != right:
                return False
            if not left:
                return True


def main():
    # Chấp nhận cờ bị dán sai gạch (---out, —out, –out, -out) do lỗi khi copy lệnh: đưa về --out.
    sys.argv = [sys.argv[0]] + [re.sub(r'^[-\u2010-\u2015\u2212]+(?=[A-Za-z]{2})', '--', arg)
                                for arg in sys.argv[1:]]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('source')
    parser.add_argument('target')
    parser.add_argument('--dict-mb', type=int, default=256, help='Kích thước từ điển LZMA (MB). 8 = như mặc định.')
    args = parser.parse_args()
    source, target = Path(args.source), Path(args.target)
    if source.resolve() == target.resolve():
        sys.exit('File ra phải khác file vào.')
    with zipfile.ZipFile(source) as archive:
        names = archive.namelist()
        if len(names) != 1:
            sys.exit(f'{source} phải chứa đúng một file, đang có {names}')
    name = names[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    BigDictCompressor.dict_size = args.dict_mb << 20
    original, zipfile.LZMACompressor = zipfile.LZMACompressor, BigDictCompressor
    started = time.time()
    try:
        info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_LZMA
        with zipfile.ZipFile(source) as archive, zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_LZMA) as out, \
                archive.open(name) as reader, out.open(info, 'w', force_zip64=True) as writer:
            while block := reader.read(1 << 22):
                writer.write(block)
    finally:
        zipfile.LZMACompressor = original
    if not same_content(source, target, name):
        sys.exit('Nội dung sau khi nén lại không khớp!')
    print(f'{source} ({source.stat().st_size / 1e6:.1f} MB) -> {target} ({target.stat().st_size / 1e6:.1f} MB), '
          f'từ điển {args.dict_mb} MB, {(time.time() - started) / 60:.1f} phút, nội dung giống hệt.')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
