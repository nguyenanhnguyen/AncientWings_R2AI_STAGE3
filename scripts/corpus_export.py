"""Export a compact, ID-preserving corpus; keep request traces in records/ separately."""
import argparse
import hashlib
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
def read_jsonl(path):
    # str.splitlines() also splits U+2028/U+0085 inside valid JSON string values.
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--jsonl', action='store_true', help='Optional duplicate JSONL export')
    parser.add_argument('--partial', action='store_true', help='Provisional snapshot; not an audited final corpus')
    args = parser.parse_args()
    out = Path(args.out)
    parquet_name = 'corpus.partial.parquet' if args.partial else 'corpus.parquet'
    jsonl_name = 'corpus.partial.jsonl' if args.partial else 'corpus.jsonl'
    source = read_jsonl(out / 'corpus.accepted.jsonl')
    expected = {r['id']: r for r in source}
    if not source or len(expected) != len(source):
        raise ValueError('Empty corpus or duplicate IDs')
    fields = ('id', 'url', 'final_url', 'title', 'text', 'domain', 'extractor', 'published_at',
              'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids', 'author', 'reviewed_by', 'updated_at')
    rows = [{key: r.get(key) for key in fields} for r in sorted(source, key=lambda r: r['id'])]
    for r in source:
        if r['quality_status'] != 'accepted' or not r['text'].strip():
            raise ValueError('Non-accepted or empty record')
        if hashlib.sha256(r['text'].encode()).hexdigest() != r['text_sha256']:
            raise ValueError('Text hash mismatch')
    schema = pa.schema([
        (key, pa.int64() if key == 'id' else pa.list_(pa.int64()) if key == 'duplicate_doc_ids' else pa.string())
        for key in fields
    ])
    table = pa.Table.from_pylist(rows, schema=schema)
    temporary = out / (parquet_name + '.tmp')
    try:
        pq.write_table(table, temporary, compression='zstd')
        if pq.read_table(temporary).to_pylist() != rows:
            raise ValueError('Parquet round-trip mismatch')
        temporary.replace(out / parquet_name)
    finally:
        temporary.unlink(missing_ok=True)
    if args.jsonl:
        with (out / jsonl_name).open('w', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
    if args.jsonl and read_jsonl(out / jsonl_name) != rows:
        raise ValueError('JSONL round-trip mismatch')
    if not args.jsonl:
        (out / jsonl_name).unlink(missing_ok=True)
    result = {'documents': len(rows), 'id_type': 'int64', 'accepted_source_ids_preserved': True,
              'parquet_round_trip_verified': True, 'jsonl_round_trip_verified': args.jsonl, 'files': {}}
    result.update(complete=not args.partial, provisional=args.partial)
    for name in ((parquet_name, jsonl_name) if args.jsonl else (parquet_name,)):
        target = out / name
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        result['files'][name] = {'bytes': target.stat().st_size, 'sha256': digest}
    manifest_name = 'partial_export_manifest.json' if args.partial else 'export_manifest.json'
    (out / manifest_name).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
if __name__ == '__main__':
    main()
