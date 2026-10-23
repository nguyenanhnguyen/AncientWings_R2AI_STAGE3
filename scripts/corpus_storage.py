"""Bound disk usage without deleting raw data, engine records or user files."""
import json
from pathlib import Path
import shutil

RESERVE_BYTES = 1024 ** 3
REPORTS = {'documents.jsonl', 'corpus.accepted.jsonl', 'quarantine.jsonl',
           'source_decisions.jsonl'}
EXPORT_FIELDS = ('id', 'url', 'final_url', 'title', 'text', 'domain', 'extractor', 'published_at',
                 'raw_path', 'raw_sha256', 'text_sha256', 'duplicate_doc_ids', 'author',
                 'reviewed_by', 'updated_at')


class StoragePressure(RuntimeError):
    pass


def compact_row(name, row):
    if name == 'corpus.accepted.jsonl':
        return {k: row[k] for k in (*EXPORT_FIELDS, 'quality_status') if k in row}
    if name in REPORTS:
        return {k: v for k, v in row.items() if k not in (
            'text', 'requests', 'redirects', 'medical_blocks', 'source_html', 'html',
            'article_pages', 'answers', 'question', 'source_document', 'clean_html',
            'network_requests', 'paragraphs', 'blocks', 'body_text', 'body_html', 'full_text')}
    return row


def prepare_reports(out):
    """Remove only reproducible report copies before rebuilding them (never checkpoints)."""
    out = Path(out).resolve()
    for name in REPORTS:
        target = out / name
        if target.is_file() and not target.is_symlink():
            target.unlink()
        for temporary in out.glob(name + '.*.tmp'):
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()


def free_bytes(path):
    return shutil.disk_usage(path).free


def archive_fits(paths, destination):
    # Conservative upper bound: compression may be ineffective for raw .gz files.
    return free_bytes(Path(destination).parent) >= RESERVE_BYTES + sum(
        p.stat().st_size + 1024 for p in paths)


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.storage.tmp')
    try:
        with temporary.open('w', encoding='utf-8', newline='\n') as stream:
            for row in rows:
                stream.write(json.dumps(compact_row(path.name, row), ensure_ascii=False) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    # Run a saved crawler unchanged, including legacy runs with full JSONL reports.
    import argparse
    import importlib.util
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['report'])
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out)
    spec = importlib.util.spec_from_file_location('storage_report_core', out/'crawler_snapshot.py')
    crawler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crawler)
    crawler.jsonl = write_jsonl
    prepare_reports(out)
    crawler.report(args)


if __name__ == '__main__':
    main()
