"""Read/write helpers for JSON, JSONL and Parquet, plus hashing and run manifests."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def atomic_write_bytes(path, data):
    """Write through a temporary file in the same directory so a crash cannot leave a half file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(handle, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_json(path, obj):
    atomic_write_bytes(path, (json.dumps(obj, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_jsonl(path, rows):
    body = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows)
    atomic_write_bytes(path, body.encode('utf-8'))


def read_jsonl(path):
    return list(iter_jsonl(path))


def iter_jsonl(path):
    # Iterate file lines: str.splitlines() also splits U+2028/U+0085 inside valid JSON strings.
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def read_parquet(path, columns=None, filters=None):
    return pq.read_table(path, columns=columns, filters=filters).to_pylist()


def read_rows(path, wanted=None):
    """Rows of a .parquet, .json (one array) or .jsonl file, whichever the crawler wrote.

    `wanted(column_names)` may narrow a Parquet read to the columns the caller needs.
    """
    path = Path(path)
    if path.suffix == '.parquet':
        columns = wanted(pq.ParquetFile(path).schema_arrow.names) if wanted else None
        return read_parquet(path, columns=columns)
    if path.suffix == '.json':
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, list):
            raise ValueError(f'{path} must hold a JSON array of records.')
        return data
    return read_jsonl(path)


def write_parquet(path, rows, schema=None, compression='zstd'):
    """Write rows and verify the file reads back identical before returning."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows, schema=schema)
    pq.write_table(table, path, compression=compression)
    if pq.read_table(path).to_pylist() != rows:
        raise ValueError(f'Parquet round-trip mismatch: {path}')
    return path


def write_manifest(path, payload, files=()):
    """Record what a stage produced, with sizes and hashes of its output files."""
    record = dict(payload)
    record['files'] = {}
    for name in files:
        target = Path(name)
        record['files'][target.name] = {'bytes': target.stat().st_size, 'sha256': sha256_file(target)}
    write_json(path, record)
    return record
