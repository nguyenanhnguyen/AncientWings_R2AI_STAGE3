"""E1: build the dev labels, and be explicit about where they came from.

The organisers do not publish reference documents or passages, so there is no gold set to measure
against. Only three honest options exist, and each is marked in the label file:

    human   A sheet of top candidates is exported, a person marks which ones answer the query, and
            the marks become labels. Slow, and the only labels that mean anything. Recall is still
            bounded by what retrieval showed the annotator, so treat recall from these labels as
            an upper estimate of nothing and precision as the trustworthy half.
    pseudo  The pipeline's own top results are assumed correct. This measures the pipeline against
            itself and will look excellent while proving nothing. It exists so the flow can run
            end to end offline, and `scripts/evaluate.py` prints a warning whenever it is used.
    external  Labels from another source entirely, with provenance recorded in the file.

The leaderboard is the only unbiased signal, and submissions are rate limited, so the point of the
local dev set is to compare two configurations cheaply, not to predict a leaderboard score.
"""
import html as html_escape
from pathlib import Path

from ..common import storage

SOURCES = ('human', 'pseudo', 'external')


def load_labels(path):
    """-> ({query_id: {'docs': [...], 'chunks': [...]}}, provenance)."""
    labels, sources = {}, set()
    for row in storage.read_jsonl(path):
        query_id = int(row['id'])
        source = row.get('source') or 'unknown'
        if source not in SOURCES:
            # The report has to say where the labels came from, so an unknown tag is a mistake
            # worth stopping on rather than a line to print as-is.
            raise ValueError(f'Query {query_id} has label source {source!r}; '
                             f'expected one of {SOURCES}.')
        labels[query_id] = {'docs': [int(value) for value in row.get('docs') or []],
                            'chunks': row.get('chunks') or []}
        sources.add(source)
    if not labels:
        raise ValueError(f'No labels in {path}')
    return labels, sorted(sources)


def write_label_sheet(records, chunk_table, out_dir, per_query=10, queries=None, limit=None):
    """Export top candidates for a person to mark. Never overwrites an existing sheet."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = out_dir / 'label_sheet.jsonl'
    if sheet.exists():
        raise FileExistsError(f'{sheet} already exists; move it before exporting a new sheet.')
    wanted = set(queries) if queries else None
    rows = []
    for record in records:
        query_id = int(record['query_id'])
        if wanted is not None and query_id not in wanted:
            continue
        items = []
        for candidate in (record.get('candidates') or [])[:per_query]:
            chunk = chunk_table.get(candidate['chunk_id'], {})
            items.append({'chunk_id': candidate['chunk_id'], 'doc_id': int(candidate['doc_id']),
                          'chunk_text': chunk.get('text', ''), 'relevant': None})
        rows.append({'id': query_id, 'query': record['query'], 'annotator': None,
                     'candidates': items})
        if limit and len(rows) >= limit:
            break
    storage.write_jsonl(sheet, rows)
    page = ['<!doctype html><html lang="vi"><meta charset="utf-8"><title>Phiếu gán nhãn dev</title>',
            '<style>body{font:16px system-ui;margin:24px;line-height:1.6;max-width:60rem}'
            'details{border:1px solid #ccc;padding:12px;margin:12px 0}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px system-ui;background:#f6f6f6;padding:8px}'
            '</style>',
            f'<h1>Phiếu gán nhãn dev — {len(rows)} truy vấn</h1>',
            '<p>Đánh dấu ứng viên nào thực sự chứa thông tin trả lời câu hỏi, rồi điền '
            '<code>relevant</code> trong <code>label_sheet.jsonl</code>. Nhãn chỉ phủ các ứng '
            'viên hiển thị ở đây, nên recall đo từ phiếu này không phải recall thật.</p>']
    for row in rows:
        page.append(f"<details><summary>{row['id']} — {html_escape.escape(row['query'][:160])}"
                    '</summary>')
        for item in row['candidates']:
            page.append(f"<p><b>doc {item['doc_id']}</b> · <code>{item['chunk_id']}</code></p>"
                        f"<pre>{html_escape.escape(item['chunk_text'][:2000])}</pre>")
        page.append('</details>')
    page.append('</html>')
    (out_dir / 'label_sheet.html').write_text('\n'.join(page), encoding='utf-8')
    return sheet


def labels_from_sheet(sheet_path, out_path):
    """Turn a filled sheet into a label file. Unmarked queries are dropped, not guessed."""
    labels = []
    skipped = 0
    for row in storage.read_jsonl(sheet_path):
        marked = [item for item in row['candidates'] if item.get('relevant') is True]
        if not any(item.get('relevant') is not None for item in row['candidates']):
            skipped += 1
            continue
        labels.append({'id': int(row['id']), 'source': 'human',
                       'annotator': row.get('annotator'),
                       'docs': sorted({int(item['doc_id']) for item in marked}),
                       'chunks': [{'doc_id': int(item['doc_id']),
                                   'chunk_text': item['chunk_text']} for item in marked]})
    storage.write_jsonl(out_path, labels)
    return {'labelled_queries': len(labels), 'unmarked_queries_skipped': skipped,
            'out': str(out_path)}


def pseudo_labels(records, chunk_table, out_path, top_n=3):
    """Circular labels for smoke runs. Scores produced from these mean nothing about quality."""
    labels = []
    for record in records:
        picked = (record.get('candidates') or [])[:top_n]
        labels.append({
            'id': int(record['query_id']), 'source': 'pseudo',
            'annotator': None,
            'docs': sorted({int(candidate['doc_id']) for candidate in picked}),
            'chunks': [{'doc_id': int(candidate['doc_id']),
                        'chunk_text': chunk_table.get(candidate['chunk_id'], {}).get('text', '')}
                       for candidate in picked],
        })
    storage.write_jsonl(out_path, labels)
    return {'labelled_queries': len(labels), 'source': 'pseudo', 'out': str(out_path),
            'warning': 'Pseudo labels come from the pipeline itself; the score is circular.'}
