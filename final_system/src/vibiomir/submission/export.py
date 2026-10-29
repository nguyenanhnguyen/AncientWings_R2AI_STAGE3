"""D3: write the JSON, pack the ZIP, then read it back out and compare.

The upload must be a ZIP holding exactly one file, at the root, with no subdirectory. A submission
that is short a query or malformed is not scored, so the archive is re-opened and re-parsed here
rather than trusted. ZIP entries are written with a fixed timestamp so the same results give the
same bytes.
"""
import json
from pathlib import Path
import zipfile

from ..common import storage

FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def write_submission(rows, out_dir, name='submission.json'):
    """-> (json path, zip path). Verifies the archive contains exactly the rows given."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = json.dumps(rows, ensure_ascii=False, indent=1) + '\n'
    json_path = out_dir / name
    storage.atomic_write_bytes(json_path, body.encode('utf-8'))

    zip_path = out_dir / (Path(name).stem + '.zip')
    buffer = zip_path.with_suffix('.zip.tmp')
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, body)
    buffer.replace(zip_path)

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if names != [name]:
            raise ValueError(f'The archive must hold exactly one file at its root, got {names}')
        if json.loads(archive.read(name).decode('utf-8')) != rows:
            raise ValueError('The archive does not read back as the rows that were written.')
    return json_path, zip_path


def summarise(rows):
    doc_counts = [len(row['relevant_docs']) for row in rows]
    chunk_counts = [len(row['relevant_chunks']) for row in rows]
    characters = sum(len(item['chunk_text']) for row in rows for item in row['relevant_chunks'])
    return {
        'queries': len(rows),
        'docs_total': sum(doc_counts),
        'docs_mean': round(sum(doc_counts) / max(1, len(rows)), 2),
        'chunks_total': sum(chunk_counts),
        'chunks_mean': round(sum(chunk_counts) / max(1, len(rows)), 2),
        'chunk_characters': characters,
        'queries_with_empty_docs': sum(1 for count in doc_counts if count == 0),
        'queries_with_empty_chunks': sum(1 for count in chunk_counts if count == 0),
    }
