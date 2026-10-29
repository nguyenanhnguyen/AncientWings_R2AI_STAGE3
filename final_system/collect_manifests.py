"""Gom mọi manifest (tham số + số liệu của từng bước) vào một thư mục để nộp hệ thống / viết working notes.

Chép (không sửa, không xoá) các file *manifest*.json, stages/*.json, provenance*.csv và targets.parquet trong
work/ (kể cả work/run_*/... nhưng KHÔNG chép dữ liệu lớn), giữ nguyên đường dẫn tương đối, rồi ghi
INDEX.md liệt kê từng file với vài số chính (số tài liệu, số cặp, cấu hình bài cuối).

Ví dụ (ở thư mục gốc repo):
  .\\env\\Scripts\\python.exe collect_manifests.py --out system_submission/manifests
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

PATTERNS = ('**/*manifest*.json', '**/stages/*.json', '**/provenance*.csv', '**/targets.parquet',
            '**/translations/translation_manifest.json')
KEYS = ('documents_kept', 'chunks', 'pairs', 'pairs_total', 'pairs_scored', 'docs_per_query', 'chunks_per_query',
        'adaptive_rule', 'chunk_mb', 'extra_windows', 'json_mb', 'zip_mb', 'hf_id', 'encoder', 'model')


def summary_of(path):
    if path.suffix != '.json':
        return f'{path.stat().st_size / 1e6:.2f} MB'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeDecodeError):
        return '(không đọc được JSON)'
    if not isinstance(data, dict):
        return ''
    found = {k: data[k] for k in KEYS if k in data and not isinstance(data[k], (dict, list))}
    return ', '.join(f'{k}={v}' for k, v in found.items())


def main():
    # Chấp nhận cờ bị dán sai gạch (---out, —out, –out, -out) do lỗi khi copy lệnh: đưa về --out.
    sys.argv = [sys.argv[0]] + [re.sub(r'^[-‐-―−]+(?=[A-Za-z]{2})', '--', arg)
                                for arg in sys.argv[1:]]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--work', default='work')
    parser.add_argument('--out', default='system_submission/manifests')
    args = parser.parse_args()
    work, out = Path(args.work), Path(args.out)
    if not work.is_dir():
        parser.error(f'Không thấy {work}: chạy ở thư mục gốc repo.')
    files = sorted({p for pattern in PATTERNS for p in work.glob(pattern) if p.is_file()})
    lines = ['# Manifest của các bước', '', f'{len(files)} file, chép từ `{work}/`.', '',
             '| File | Số chính |', '|---|---|']
    for path in files:
        target = out / path.relative_to(work)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        lines.append(f'| `{path.relative_to(work).as_posix()}` | {summary_of(path)} |')
    out.mkdir(parents=True, exist_ok=True)
    (out / 'INDEX.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Đã chép {len(files)} file vào {out}; danh sách ở {out / "INDEX.md"}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
