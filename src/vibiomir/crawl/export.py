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
    args = parser.parse_args()
    out = Path(args.out)
    source = read_jsonl(out / 'corpus.accepted.jsonl')
    expected = {r['id']: r for r in source}
    if not source or len(expected) != len(source):
        raise ValueError('Empty corpus or duplicate IDs')
    fields = ('id', 'url', 'final_url', 'title', 'text', 'domain', 'extractor', 'published_at',
              'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids')
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
    pq.write_table(table, out / 'corpus.parquet', compression='zstd')
    (out / 'corpus.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
    reread = pq.read_table(out / 'corpus.parquet').to_pylist()
    if reread != rows:
        raise ValueError('Parquet round-trip mismatch')
    if read_jsonl(out / 'corpus.jsonl') != rows:
        raise ValueError('JSONL round-trip mismatch')
    result = {'documents': len(rows), 'id_type': 'int64', 'accepted_source_ids_preserved': True,
              'parquet_round_trip_verified': True, 'jsonl_round_trip_verified': True, 'files': {}}
    for name in ('corpus.jsonl', 'corpus.parquet'):
        data = (out / name).read_bytes()
        result['files'][name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    (out / 'export_manifest.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
