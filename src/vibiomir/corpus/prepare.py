"""A2→A3 bridge: turn whatever a crawler wrote into the one corpus file the pipeline reads.

Crawlers in this project write different shapes: the per-id run directory (`records/<id>.json`
plus raw gzip) and the team crawler's JSON/Parquet exports with a `status` column. This step reads
any of them, keeps one row per source id, removes rows that are not the article the id points to,
and writes `work/corpus/corpus.parquet` with a fixed schema. Every later block reads only that file.

What is removed, and why each is not just a quality nuisance:

    fetch_failed       No page was fetched; there is no text to search.
    empty_text         Fetched, but extraction produced nothing.
    homepage_redirect  The URL redirected to the site's root. The stored text is the homepage, not
                       the article. In the first crawl batch this was 2.236 ids, 2.230 of them the
                       same "Trang chủ" text; left in, they would match many queries and crowd out
                       real articles in every submission.
    template_text      More than `--max-duplicates` ids share one text. A real article republished
                       a few times is kept; hundreds of ids with identical text are an error page or
                       a template.
    quality_rejected   The crawler's own QC rejected it (error page, anti-bot challenge).

Rows the crawler only marked `review` are kept, with their flags. F2 weights recall four times
precision, so a short or slightly noisy article is still worth having in the index.

Nothing here rewrites text beyond the light normalisation every block already applies, so the
chunk spans cut from this corpus are still spans of the source.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import pyarrow as pa

from ..common import storage
from ..common.console import emit
from ..common.schema import detect_language, document_text

CORPUS_SCHEMA = pa.schema([
    ('id', pa.int64()),
    ('url', pa.string()),
    ('final_url', pa.string()),
    ('domain', pa.string()),
    ('title', pa.string()),
    ('text', pa.string()),
    ('lang', pa.string()),
    ('status', pa.string()),
    ('quality_status', pa.string()),
    ('quality_flags', pa.list_(pa.string())),
    ('published_at', pa.string()),
    ('extractor', pa.string()),
    ('char_count', pa.int64()),
    ('text_sha256', pa.string()),
    ('raw_path', pa.string()),
    ('raw_sha256', pa.string()),
    ('duplicate_doc_ids', pa.list_(pa.int64())),
    ('source', pa.string()),
])

OK_STATUSES = {'ok', 'extracted'}
_LANG_HINTS = {'vi_hint': 'vi', 'zh_hint': 'zh', 'vi': 'vi', 'zh': 'zh', 'en': 'en'}


# --- Reading each crawler's shape ---

def in_id_range(value, id_start=None, id_end=None):
    value = int(value)
    return (id_start is None or value >= id_start) and (id_end is None or value <= id_end)


def add_id_arguments(parser):
    parser.add_argument('--id-start', type=int, default=None, help='First source ID (inclusive).')
    parser.add_argument('--id-end', type=int, default=None, help='Last source ID (inclusive).')


def validate_id_range(id_start, id_end):
    if any(x is not None and x < 0 for x in (id_start, id_end)):
        raise ValueError('ID bounds must be nonnegative.')
    if id_start is not None and id_end is not None and id_start > id_end:
        raise ValueError('--id-start must be <= --id-end.')


def _run_directory_rows(path, limit=None, id_start=None, id_end=None):
    """The per-id run layout: <run>/records/<id>.json, raw paths relative to <run>."""
    files = sorted((item for item in (path / 'records').glob('*.json') if item.stem.isdigit()
                    and in_id_range(item.stem, id_start, id_end)),
                   key=lambda item: int(item.stem))
    if limit:
        files = files[:limit]
    for file in files:
        try:
            row = json.loads(file.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            yield {'id': int(file.stem), '_unreadable': str(error)[:200]}
            continue
        if int(row['id']) != int(file.stem):
            raise ValueError(f'Record ID disagrees with filename: {file}')
        if row.get('raw_path'):
            row['raw_path'] = str((path / row['raw_path']).as_posix())
        yield row


_SKIP_DIRS = {'records', 'raw', 'requests_records', 'browser_records', 'robots', 'logs',
              '__pycache__', '.git'}


def discover_sources(path):
    """Expand one --source into concrete sources: run directories or data files.

    A run directory (has records/) is used as is. A directory of Parquet files, such as the
    `corpus/` folder of the team's Hugging Face dataset, contributes each file. Any other directory
    is walked for run directories, e.g. `nguyen/` holds `output/runs/<run>` and
    `shards/<shard>/runs/<run>`. The walk stops at a run root and never descends into records/ or
    raw/, which hold hundreds of thousands of files.
    """
    path = Path(path)
    if not path.is_dir():
        return [path]
    if (path / 'records').is_dir():
        return [path]
    runs, files = [], []
    for folder, directories, names in os.walk(path):
        here = Path(folder)
        if 'records' in directories:
            runs.append(here)
            directories[:] = []
            continue
        directories[:] = sorted(d for d in directories if d not in _SKIP_DIRS)
        files.extend(here / name for name in sorted(names) if name.endswith('.parquet'))
    if runs:
        return sorted(runs)
    if files:
        return sorted(files)
    raise ValueError(f'{path} holds no crawl run (a folder with records/) and no .parquet file.')


def read_source(path, limit=None, id_start=None, id_end=None):
    """Rows from a run directory or an exported file, in increasing id order when known."""
    path = Path(path)
    if path.is_dir():
        if not (path / 'records').is_dir():
            raise ValueError(f'{path} is a directory without records/; pass the run directory '
                             'or an exported .parquet/.json/.jsonl file.')
        yield from _run_directory_rows(path, limit, id_start, id_end)
        return
    if path.suffix == '.parquet' and (id_start is not None or id_end is not None):
        import pyarrow.parquet as pq
        import pyarrow.compute as pc
        rows = []
        for batch in pq.ParquetFile(path).iter_batches(batch_size=4096):
            ids = pc.cast(batch.column('id'), pa.int64())
            mask = pa.array([True] * batch.num_rows)
            if id_start is not None:
                mask = pc.and_(mask, pc.greater_equal(ids, id_start))
            if id_end is not None:
                mask = pc.and_(mask, pc.less_equal(ids, id_end))
            rows.extend(batch.filter(mask).to_pylist())
    else:
        rows = [row for row in storage.read_rows(path)
                if in_id_range(row['id'], id_start, id_end)]
    rows.sort(key=lambda row: int(row['id']))
    yield from (rows[:limit] if limit else rows)


# --- Turning one source row into one corpus row, or a reason it is dropped ---

def _is_homepage_redirect(url, final_url):
    if not url or not final_url:
        return False
    try:
        source, final = urlsplit(url), urlsplit(final_url)
    except ValueError:
        return False
    return final.path in ('', '/') and source.path not in ('', '/') and not final.query


def _language(row, text):
    for key in ('lang', 'language_hint'):
        mapped = _LANG_HINTS.get(row.get(key) or '')
        if mapped:
            return mapped
    return detect_language(text)


def normalise_row(row, source, text_field=None):
    """-> (corpus row, None) when kept, or (None, drop reason)."""
    if row.get('_unreadable'):
        return None, 'unreadable_record'
    status = row.get('status') or 'ok'
    if status not in OK_STATUSES:
        return None, f'fetch_failed:{status}'
    if row.get('quality_status') == 'rejected':
        return None, 'quality_rejected'
    url = row.get('url') or ''
    final_url = row.get('final_url') or url
    if _is_homepage_redirect(url, final_url):
        return None, 'homepage_redirect'
    text = document_text(row, text_field)
    if not text.strip():
        return None, 'empty_text'
    flags = [flag for flag in (row.get('quality_flags') or []) if flag != 'redirect_review']
    return {
        'id': int(row['id']),
        'url': url,
        'final_url': final_url,
        'domain': row.get('domain') or (urlsplit(url).hostname or ''),
        'title': (row.get('title') or '').strip(),
        'text': text,
        'lang': _language(row, text),
        'status': 'ok',
        'quality_status': row.get('quality_status') or 'accepted',
        'quality_flags': flags,
        'published_at': None if row.get('published_at') is None else str(row['published_at']),
        'extractor': row.get('extractor') or '',
        'char_count': len(text),
        'text_sha256': storage.sha256_text(text),
        'raw_path': row.get('raw_path') or '',
        'raw_sha256': row.get('raw_sha256') or '',
        'duplicate_doc_ids': [],
        'source': str(source),
    }, None


def source_size(path, id_start=None, id_end=None):
    """Rows a source can give: record files of a run, Parquet row count, else rows of the file."""
    path = Path(path)
    if path.is_dir():
        with os.scandir(path / 'records') as entries:
            return sum(1 for entry in entries
                       if entry.name.endswith('.json') and entry.name[:-5].isdigit()
                       and in_id_range(entry.name[:-5], id_start, id_end))
    if path.suffix == '.parquet':
        import pyarrow.parquet as pq
        parquet = pq.ParquetFile(path)
        if id_start is None and id_end is None:
            return parquet.metadata.num_rows
        return sum(in_id_range(value, id_start, id_end)
                   for batch in parquet.iter_batches(columns=['id'])
                   for value in batch.column('id').to_pylist())
    return sum(in_id_range(row['id'], id_start, id_end) for row in storage.read_rows(path))


def proportional_quotas(sizes, limit):
    """Split `limit` over sources in proportion to their sizes (largest remainder), capped by size.

    `--limit 100000` over batch01 and two shards then reads from all three, lowest ids first in
    each, instead of filling the whole budget from the first run.
    """
    total = sum(sizes)
    if total <= limit:
        return list(sizes)
    exact = [limit * size / total for size in sizes]
    quotas = [int(value) for value in exact]
    order = sorted(range(len(sizes)), key=lambda i: exact[i] - quotas[i], reverse=True)
    for i in order[:limit - sum(quotas)]:
        quotas[i] += 1
    return [min(q, s) for q, s in zip(quotas, sizes)]


def build(args):
    id_start, id_end = getattr(args, 'id_start', None), getattr(args, 'id_end', None)
    validate_id_range(id_start, id_end)
    kept, dropped = {}, []
    seen = set()
    sources = [found for given in args.source for found in discover_sources(given)]
    emit(f'prepare: {len(sources)} nguồn: ' + ', '.join(str(source) for source in sources[:20])
         + (' ...' if len(sources) > 20 else ''))
    split = getattr(args, 'split', 'proportional')
    quotas = None
    if args.limit and split == 'proportional' and len(sources) > 1:
        sizes = [source_size(source, id_start, id_end) for source in sources]
        quotas = proportional_quotas(sizes, args.limit)
        emit('prepare: chia giới hạn theo tỷ lệ: ' + ', '.join(
            f'{Path(s).name}={q}/{n}' for s, q, n in zip(sources, quotas, sizes)))
    read_per_source = {}
    for position, source in enumerate(sources):
        if quotas is not None:
            remaining = quotas[position]
            if remaining == 0:
                read_per_source[str(source)] = 0
                continue
        else:
            remaining = args.limit - len(seen) if args.limit else None
            if args.limit and remaining <= 0:
                break
        before = len(seen)
        for row in read_source(source, limit=remaining, id_start=id_start, id_end=id_end):
            doc_id = int(row['id'])
            if doc_id in seen:
                # Several shards may carry the same id; the first source given wins.
                continue
            seen.add(doc_id)
            record, reason = normalise_row(row, source, args.text_field)
            if record is None:
                dropped.append({'id': doc_id, 'reason': reason, 'url': row.get('url')})
            elif args.drop_review and record['quality_status'] == 'review':
                dropped.append({'id': doc_id, 'reason': 'quality_review', 'url': record['url']})
            elif record['char_count'] < args.min_chars:
                dropped.append({'id': doc_id, 'reason': 'below_min_chars', 'url': record['url']})
            else:
                kept[doc_id] = record
        read_per_source[str(source)] = len(seen) - before

    groups = {}
    for doc_id, record in kept.items():
        groups.setdefault(record['text_sha256'], []).append(doc_id)
    for members in groups.values():
        if len(members) > args.max_duplicates:
            for doc_id in members:
                record = kept.pop(doc_id)
                dropped.append({'id': doc_id, 'reason': 'template_text', 'url': record['url']})
        elif len(members) > 1:
            # Every id stays: any of them may be the labelled one. The group is only noted.
            for doc_id in members:
                kept[doc_id]['duplicate_doc_ids'] = [other for other in members if other != doc_id]

    rows = [kept[doc_id] for doc_id in sorted(kept)]
    if not rows:
        raise ValueError('No usable documents; see the drop reasons above.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    corpus = storage.write_parquet(out / 'corpus.parquet', rows, schema=CORPUS_SCHEMA)
    storage.write_jsonl(out / 'dropped.jsonl', sorted(dropped, key=lambda item: item['id']))
    lengths = sorted(row['char_count'] for row in rows)
    summary = {
        'rows_read': len(seen),
        'documents_kept': len(rows),
        'documents_dropped': len(dropped),
        'drop_reasons': dict(Counter(item['reason'] for item in dropped).most_common()),
        'quality_status': dict(Counter(row['quality_status'] for row in rows)),
        'languages': dict(Counter(row['lang'] for row in rows)),
        'domains': dict(Counter(row['domain'] for row in rows).most_common()),
        'duplicate_groups_kept': sum(1 for members in groups.values()
                                     if 1 < len(members) <= args.max_duplicates),
        'chars_median': lengths[len(lengths) // 2],
        'chars_p95': lengths[int(len(lengths) * 0.95)],
        'id_min': rows[0]['id'], 'id_max': rows[-1]['id'],
        'options': {'limit': args.limit, 'split': split, 'max_duplicates': args.max_duplicates,
                    'min_chars': args.min_chars, 'drop_review': args.drop_review,
                    'text_field': args.text_field, 'id_start': id_start, 'id_end': id_end},
        'sources': [str(source) for source in sources],
        'rows_read_per_source': read_per_source,
        'split': split if quotas is not None else 'sequential',
        'source_arguments': [str(source) for source in args.source],
    }
    storage.write_manifest(out / 'prepare_manifest.json', summary, files=[corpus])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--source', nargs='+', required=True,
                        help='Crawl run directories (with records/), folders that contain them '
                             '(e.g. nguyen), folders of .parquet files (the HF corpus/), or '
                             'exported .parquet/.json/.jsonl files. Earlier sources win on shared '
                             'ids.')
    parser.add_argument('--out', default='work/corpus')
    add_id_arguments(parser)
    parser.add_argument('--limit', type=int, default=None,
                        help='Read at most this many source rows, lowest ids first.')
    parser.add_argument('--split', choices=['proportional', 'sequential'], default='proportional',
                        help='With --limit over several sources: share it by source size '
                             '(default) or fill from the first source on.')
    parser.add_argument('--max-duplicates', type=int, default=20,
                        help='More ids than this sharing one text are treated as a template.')
    parser.add_argument('--min-chars', type=int, default=0,
                        help='Drop documents shorter than this. Default keeps every non-empty one.')
    parser.add_argument('--drop-review', action='store_true',
                        help='Also drop rows the crawler marked for review.')
    parser.add_argument('--text-field', default=None,
                        help='Column holding the body. Default: text, content or body, else a '
                             'question plus answers.')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    build(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
