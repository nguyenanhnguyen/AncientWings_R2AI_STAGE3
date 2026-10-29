"""Gộp nhiều bài nộp thành một: mỗi câu hỏi lấy hợp các tài liệu và các chunk của mọi bài.

Dùng khi các bài nộp được tạo từ những kho dữ liệu khác nhau, để tài liệu đúng của các bên cộng dồn.
Đặt file này ở thư mục gốc repo (cạnh `scripts/` và `src/`).

Mỗi đầu vào là file .zip hoặc .json đúng định dạng bài nộp. Có thể giới hạn riêng từng đầu vào bằng cách
viết thêm "=CHUNK:TAILIEU" sau đường dẫn: lấy CHUNK chunk đầu và TAILIEU tài liệu đầu của bài đó cho mỗi câu
(0 = lấy hết). Danh sách trong mỗi bài được coi là đã xếp tốt nhất trước.

Ví dụ (PowerShell, ở thư mục gốc repo):

  .\\env\\Scripts\\python.exe merge_submissions.py work/run_d/win1000/submission.zip=12:0 work/run_e/win1000/submission.zip=2:8 --out work/merged

  # Chỉ thêm TÀI LIỆU của bài sau, giữ nguyên chunk (và thứ tự chunk) của bài đầu:
  .\\env\\Scripts\\python.exe merge_submissions.py work/final_p4_w2500/submission.zip "work/run_archive/win2500/submission.zip=0:0" --chunks-from-first --out work/final_arch_docs --lzma

  # Như trên nhưng bỏ các chunk dài hơn 1000 token:
  .\\env\\Scripts\\python.exe merge_submissions.py work/final_p4_w2500/submission.zip "work/run_archive/win2500/submission.zip=0:0" --chunks-from-first --max-chunk-tokens 1000 --out work/final_arch_short --lzma

  # Như trên, và đưa các tài liệu có chunk lên đầu relevant_docs (tập tài liệu không đổi):
  .\\env\\Scripts\\python.exe merge_submissions.py work/final_p4_w2500_small/submission.zip "work/run_archive/win2500/submission.zip=0:0" --chunks-from-first --chunk-docs-first --out work/final_arch_cdf --lzma

Bản này tiết kiệm bộ nhớ: đọc từng bài một và chỉ giữ phần được lấy, ghi file kết quả từng câu một
(mỗi câu một dòng) thay vì dựng cả file JSON trong RAM. Trường chunk_order không được ghi ra.
Mọi chunk đều giữ nguyên văn như trong bài nộp gốc.
"""
import argparse
import gc
import json
import re
import shutil
import sys
import zipfile
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from vibiomir.common import schema, storage  # noqa: E402
from vibiomir.common.console import emit  # noqa: E402
from vibiomir.retrieval.query import load_queries  # noqa: E402

CAPS = re.compile(r'^(.*)=(\d+):(\d+)$')
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
NAME = 'submission.json'


def parse_input(text):
    """'path' or 'path=CHUNKS:DOCS' -> (path, chunk_cap, doc_cap); 0 means no cap."""
    match = CAPS.match(text)
    if match:
        return match.group(1), int(match.group(2)), int(match.group(3))
    return text, 0, 0


def read_rows(path):
    path = Path(path)
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
            if len(names) != 1:
                raise ValueError(f'{path} phải chứa đúng một file, đang có {names}.')
            raw = archive.read(names[0])
    else:
        raw = path.read_bytes()
    rows = json.loads(raw.decode('utf-8-sig'))
    del raw
    if not isinstance(rows, list):
        raise ValueError(f'{path} không phải một mảng JSON.')
    return rows


def load_trimmed(path, chunk_cap, doc_cap, query_ids, keep_chunks=True):
    """Read one submission and keep only the capped heads: {query_id: (docs, [(doc_id, text), ...])}.

    keep_chunks=False keeps the documents only (the chunk list is left empty)."""
    rows = read_rows(path)
    kept = {}
    for row in rows:
        docs = [int(value) for value in row['relevant_docs']]
        if keep_chunks:
            chunks = [(int(item['doc_id']), item['chunk_text']) for item in row['relevant_chunks']]
            chunks = chunks[:chunk_cap] if chunk_cap else chunks
        else:
            chunks = []
        kept[int(row['id'])] = (docs[:doc_cap] if doc_cap else docs, chunks)
    del rows
    gc.collect()
    missing = [query_id for query_id in query_ids if query_id not in kept]
    if missing:
        raise ValueError(f'{path} thiếu {len(missing)} câu hỏi, ví dụ {missing[:5]}.')
    return kept


def interleave(lists):
    """a1, b1, a2, b2, ... so that every input keeps its best items when a cap is applied."""
    for group in zip_longest(*lists):
        for item in group:
            if item is not None:
                yield item


def write_streaming(rows, out_dir, lzma=False):
    """Write submission.json one query per line, zip it from disk, then re-read it line by line."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path, zip_path = out_dir / NAME, out_dir / 'submission.zip'
    tmp_json = json_path.with_suffix('.json.tmp')
    with open(tmp_json, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('[\n')
        for position, row in enumerate(rows):
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write(',\n' if position + 1 < len(rows) else '\n')
        handle.write(']\n')
    tmp_json.replace(json_path)

    tmp_zip = zip_path.with_suffix('.zip.tmp')
    method = zipfile.ZIP_LZMA if lzma else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(tmp_zip, 'w', compression=method) as archive:
        info = zipfile.ZipInfo(NAME, date_time=FIXED_TIME)
        info.compress_type = method
        with open(json_path, 'rb') as source, archive.open(info, 'w', force_zip64=True) as target:
            shutil.copyfileobj(source, target, 1 << 20)
    tmp_zip.replace(zip_path)

    # Read back from the archive, one line per query, and compare with what was meant to be written.
    with zipfile.ZipFile(zip_path) as archive:
        if archive.namelist() != [NAME]:
            raise ValueError(f'File zip phải chứa đúng một file {NAME}, đang có {archive.namelist()}.')
        if archive.testzip() is not None:
            raise ValueError('File zip bị lỗi khi đọc lại.')
        with archive.open(NAME) as handle:
            lines = (line.decode('utf-8').rstrip('\n') for line in handle)
            if next(lines) != '[':
                raise ValueError('File JSON phải bắt đầu bằng "[".')
            for row in rows:
                line = next(lines)
                if json.loads(line.rstrip(',')) != row:
                    raise ValueError(f'Câu {row["id"]} đọc lại không khớp với dữ liệu đã ghi.')
            if next(lines) != ']' or next(lines, None) is not None:
                raise ValueError('File JSON phải kết thúc bằng "]".')
    return json_path, zip_path


def build(args):
    query_ids = [row['id'] for row in load_queries(args.queries)]
    specs = [parse_input(text) for text in args.inputs]
    inputs = []
    for position, (path, chunk_cap, doc_cap) in enumerate(specs):
        keep_chunks = position == 0 or not args.chunks_from_first
        chunk_note = (chunk_cap or 'tất cả') if keep_chunks else 'không lấy'
        emit(f'Đọc {path} (chunk {chunk_note}, tài liệu {doc_cap or "tất cả"})')
        inputs.append(load_trimmed(path, chunk_cap, doc_cap, query_ids, keep_chunks=keep_chunks))

    rows, shared_docs, total_docs, too_long = [], 0, 0, 0
    for query_id in query_ids:
        doc_lists = [table[query_id][0] for table in inputs]
        docs = list(dict.fromkeys(interleave(doc_lists)))
        total_docs += sum(len(set(values)) for values in doc_lists)
        shared_docs += sum(len(set(values)) for values in doc_lists) - len(docs)
        if args.max_docs:
            docs = docs[:args.max_docs]

        chunks, seen = [], set()
        for doc_id, text in interleave([table[query_id][1] for table in inputs]):
            if (doc_id, text) in seen or not text.strip():
                continue
            seen.add((doc_id, text))
            if args.max_chunk_tokens and schema.count_tokens(text) > args.max_chunk_tokens:
                too_long += 1
                continue
            chunks.append({'doc_id': doc_id, 'chunk_text': text})
        if args.max_chunks:
            chunks = chunks[:args.max_chunks]
        listed = set(docs)
        for item in chunks:
            # Every submitted chunk's document stays listed, as in the pipeline's own output.
            if item['doc_id'] not in listed:
                docs.append(item['doc_id'])
                listed.add(item['doc_id'])
        if args.chunk_docs_first:
            # Same set of documents; those that have chunks go first, in the order their first chunk appears.
            first = list(dict.fromkeys(item['doc_id'] for item in chunks))
            has_chunk = set(first)
            docs = first + [doc_id for doc_id in docs if doc_id not in has_chunk]
        rows.append({'id': int(query_id), 'relevant_docs': docs, 'relevant_chunks': chunks})
    del inputs
    gc.collect()

    problems = schema.validate_submission_shape(rows, query_ids)
    if problems:
        raise ValueError('Bài nộp sai cấu trúc: ' + '; '.join(problems[:5]))
    json_path, zip_path = write_streaming(rows, args.out, lzma=args.lzma)
    doc_counts = [len(row['relevant_docs']) for row in rows]
    chunk_counts = [len(row['relevant_chunks']) for row in rows]
    zip_bytes = zip_path.stat().st_size
    summary = {
        'inputs': [{'path': str(path), 'chunk_cap': chunk_cap, 'doc_cap': doc_cap} for path, chunk_cap, doc_cap in specs],
        'queries': len(rows),
        'docs_mean': round(sum(doc_counts) / len(rows), 2), 'docs_max': max(doc_counts),
        'chunks_mean': round(sum(chunk_counts) / len(rows), 2), 'chunks_max': max(chunk_counts),
        'docs_listed_by_more_than_one_input_pct': round(100 * shared_docs / max(1, total_docs), 2),
        'max_docs': args.max_docs, 'max_chunks': args.max_chunks, 'chunks_from_first': args.chunks_from_first,
        'chunk_docs_first': args.chunk_docs_first, 'max_chunk_tokens': args.max_chunk_tokens,
        'dropped_too_long_per_query': round(too_long / len(rows), 2),
        'json_mb': round(json_path.stat().st_size / 1e6, 1), 'zip_mb': round(zip_bytes / 1e6, 1),
        'zip_mib': round(zip_bytes / 2 ** 20, 2),
    }
    storage.write_json(Path(args.out) / 'merge_manifest.json', summary)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nNộp file: {zip_path}')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('inputs', nargs='+',
                        help='Hai hay nhiều bài nộp (.zip hoặc .json), mỗi cái có thể kèm "=CHUNK:TAILIEU".')
    parser.add_argument('--out', required=True, help='Thư mục ghi bài nộp đã gộp.')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--max-docs', type=int, default=0,
                        help='Giới hạn tổng số tài liệu mỗi câu sau khi gộp (tài liệu của các chunk được nộp luôn được '
                             'giữ thêm). 0 = không giới hạn.')
    parser.add_argument('--max-chunks', type=int, default=0,
                        help='Giới hạn tổng số chunk mỗi câu sau khi gộp. 0 = không giới hạn.')
    parser.add_argument('--chunks-from-first', action='store_true',
                        help='Chỉ lấy chunk của bài ĐẦU TIÊN (giữ nguyên thứ tự); các bài sau chỉ góp tài liệu.')
    parser.add_argument('--chunk-docs-first', action='store_true',
                        help='Xếp lại relevant_docs: tài liệu có chunk lên đầu (theo thứ tự chunk đầu tiên của nó), '
                             'các tài liệu còn lại theo sau. Không thêm, không bớt tài liệu nào.')
    parser.add_argument('--max-chunk-tokens', type=int, default=0,
                        help='Bỏ các chunk dài hơn số token này (đếm như --window-tokens); tài liệu vẫn giữ. '
                             '0 = không giới hạn.')
    parser.add_argument('--lzma', action='store_true',
                        help='Nén zip bằng LZMA (nhỏ hơn khoảng 40%%). Chỉ dùng khi đã thử trang nộp nhận được.')
    args = parser.parse_args()
    if len(args.inputs) < 2:
        parser.error('Cần ít nhất hai bài nộp để gộp.')
    if min(args.max_docs, args.max_chunks) < 0:
        parser.error('Giới hạn phải không âm.')
    build(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
