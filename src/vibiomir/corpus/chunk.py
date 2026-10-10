"""A4: split accepted documents into chunks, keeping doc_id and the exact source span.

Every chunk is a contiguous span of the document text, recorded as char_start/char_end. D2
re-slices the span from the corpus before export, so a submitted chunk_text is provably source
text and never a rewrite. The title is kept in its own field: prepending it to chunk_text would
break that guarantee, so retrieval may use it but the submission never does.

Sizing. The organisers advise staying near or below ~1024 tokens per chunk, and a submitted chunk
counts as correct when the longest common token subsequence with a reference chunk reaches 40% of
that reference. A chunk much smaller than a reference cannot reach 40%; a chunk much larger loses
precision. Defaults aim at mid-size windows with overlap so a reference paragraph tends to sit
inside at least one window. The real sizes are unknown, so target/overlap stay tunable.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

from ..common import storage
from ..common.console import emit
from ..common.schema import (CHUNK_SCHEMA, chunk_id, count_tokens, detect_language,
                             document_columns, document_text)

# Sentence ends: Latin punctuation followed by a space, or CJK full-width punctuation.
_SENTENCE_END = re.compile(r'(?<=[.!?…])\s+|(?<=[。！？；])')


def paragraph_spans(text):
    """Spans of the text split at line breaks, each span including its trailing separator."""
    spans = []
    start = 0
    for match in re.finditer(r'\n+', text):
        if match.start() > start:
            spans.append((start, match.start()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return spans or ([(0, len(text))] if text else [])


def _subdivide(text, start, end, max_tokens):
    """Break one oversized span into sentence spans, then hard-split what is still too long."""
    pieces = []
    cursor = start
    for match in _SENTENCE_END.finditer(text, start, end):
        if match.end() > cursor:
            pieces.append((cursor, match.end()))
            cursor = match.end()
    if cursor < end:
        pieces.append((cursor, end))
    result = []
    for piece_start, piece_end in pieces:
        if count_tokens(text[piece_start:piece_end]) <= max_tokens:
            result.append((piece_start, piece_end))
            continue
        # No sentence boundary to use: cut on character budget rather than drop the content.
        step = max(80, max_tokens * 3)
        for offset in range(piece_start, piece_end, step):
            result.append((offset, min(offset + step, piece_end)))
    return result


def segment_spans(text, max_tokens):
    """Paragraphs, with any paragraph over `max_tokens` split at sentences (then characters)."""
    segments = []
    for start, end in paragraph_spans(text):
        if count_tokens(text[start:end]) > max_tokens:
            segments.extend(_subdivide(text, start, end, max_tokens))
        else:
            segments.append((start, end))
    return segments


def lead_span(text, lead_tokens=160):
    """(start, end) of the document opening: whole segments up to `lead_tokens`, at least one.

    The opening carries the title-level topic of most health articles and, on Q&A pages, the
    patient's question; it is what the document-level index (cards) embeds.
    """
    segments = segment_spans(text, lead_tokens) if text else []
    if not segments:
        return 0, 0
    total, end = 0, segments[0][1]
    for start, stop in segments:
        size = count_tokens(text[start:stop])
        if total and total + size > lead_tokens:
            break
        total += size
        end = stop
    return segments[0][0], end


def expand_window(text, start, end, budget):
    """Grow [start, end) by whole neighbouring segments while the span stays within `budget`.

    The contest scores a submitted chunk by the share of the *reference* chunk it covers (LCS /
    reference length) and counts precision per chunk, not per token. A wider window around the
    passage the reranker liked can therefore only keep or raise its overlap, at no precision cost,
    up to the ~1024 token advice. Growth alternates right then left so the passage stays near the
    middle; the result is always an exact slice of `text` that contains [start, end).
    """
    if budget <= 0 or count_tokens(text[start:end]) >= budget:
        return start, end
    segments = segment_spans(text, budget)
    if not segments:
        return start, end
    left = next((i for i, (_s, e) in enumerate(segments) if e > start), len(segments) - 1)
    right = max((i for i, (s, _e) in enumerate(segments) if s < end), default=left)
    left = min(left, right)
    ws, we = min(start, segments[left][0]), max(end, segments[right][1])
    if count_tokens(text[ws:we]) > budget:
        ws, we = start, end
    grow_right, grow_left = True, True
    while grow_right or grow_left:
        if grow_right:
            if right + 1 < len(segments) and count_tokens(text[ws:segments[right + 1][1]]) <= budget:
                right += 1
                we = segments[right][1]
            else:
                grow_right = False
        if grow_left:
            if left - 1 >= 0 and count_tokens(text[segments[left - 1][0]:we]) <= budget:
                left -= 1
                ws = segments[left][0]
            else:
                grow_left = False
    return ws, we


def plan_spans(text, target_tokens=320, overlap_tokens=64, max_tokens=1024, min_tokens=24):
    """Pack contiguous segments into overlapping windows and return (start, end) spans."""
    if not text:
        return []
    segments = segment_spans(text, max_tokens)
    sizes = [count_tokens(text[start:end]) for start, end in segments]
    spans = []
    index = 0
    while index < len(segments):
        total = 0
        last = index
        while last < len(segments) and (total == 0 or total + sizes[last] <= target_tokens):
            total += sizes[last]
            last += 1
        spans.append((segments[index][0], segments[last - 1][1]))
        if last >= len(segments):
            break
        # Step back over roughly `overlap_tokens` so a reference paragraph straddling a boundary
        # still lands whole inside the following window.
        back = last - 1
        carried = 0
        while back > index and carried + sizes[back] <= overlap_tokens:
            carried += sizes[back]
            back -= 1
        index = max(index + 1, back + 1 if carried else last)
    merged = []
    for start, end in spans:
        if merged and count_tokens(text[start:end]) < min_tokens:
            # A trailing scrap is appended to the previous window instead of becoming its own
            # chunk: a few tokens can never reach 40% overlap but would still cost precision.
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def chunk_document(document, text_field=None, **options):
    """Chunks for one corpus row. The text is whatever `document_text` derives from the row."""
    text = document_text(document, text_field)
    if not text.strip():
        return []
    title = (document.get('title') or '').strip()
    rows = []
    for order, (start, end) in enumerate(plan_spans(text, **options)):
        span = text[start:end]
        if not span.strip():
            continue
        rows.append({
            'chunk_id': chunk_id(document['id'], order),
            'doc_id': int(document['id']),
            'chunk_order': order,
            'char_start': start,
            'char_end': end,
            'text': span,
            'title': title,
            'lang': detect_language(span if len(span) > 200 else span + ' ' + title),
            'n_tokens': count_tokens(span),
            'domain': document.get('domain') or '',
        })
    return rows


def retrieval_text(chunk):
    """What the indexes embed: title gives a short chunk its topic. Not what D2 submits."""
    title = chunk.get('title') or ''
    return f"{title}\n{chunk['text']}" if title else chunk['text']


def build(args):
    sources = [Path(path) for path in args.corpus]
    documents = []
    seen = set()
    skipped_status = 0
    for source in sources:
        rows = storage.read_rows(source, lambda names: document_columns(names, args.text_field))
        for row in rows:
            if args.status and row.get('status', args.status) != args.status:
                # A crawler may export failed fetches next to good ones; they carry no text.
                skipped_status += 1
                continue
            doc_id = int(row['id'])
            if doc_id in seen:
                # Several crawl shards may export the same id; keep the first and report it.
                continue
            seen.add(doc_id)
            documents.append({**row, 'id': doc_id})
    if not documents:
        raise ValueError('No documents found in the given corpus files.')
    options = {'target_tokens': args.target_tokens, 'overlap_tokens': args.overlap_tokens,
               'max_tokens': args.max_tokens, 'min_tokens': args.min_tokens}
    chunks = []
    empty = []
    for document in sorted(documents, key=lambda row: row['id']):
        rows = chunk_document(document, text_field=args.text_field, **options)
        if not rows:
            empty.append(int(document['id']))
        chunks.extend(rows)
    if not chunks:
        raise ValueError('Every document produced zero chunks; check the corpus text column.')
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = storage.write_parquet(out / 'chunks.parquet', chunks, schema=CHUNK_SCHEMA)
    sizes = sorted(row['n_tokens'] for row in chunks)
    languages = Counter(row['lang'] for row in chunks)
    summary = {
        'documents_in': len(documents),
        'documents_with_chunks': len(documents) - len(empty),
        'documents_without_text': len(empty),
        'documents_without_text_ids': empty[:50],
        'chunks': len(chunks),
        'chunks_per_document': round(len(chunks) / max(1, len(documents) - len(empty)), 2),
        'tokens_median': sizes[len(sizes) // 2],
        'tokens_p95': sizes[int(len(sizes) * 0.95)],
        'tokens_max': sizes[-1],
        'chunks_over_1024_tokens': sum(size > 1024 for size in sizes),
        'languages': dict(languages),
        'options': options,
        'text_field': args.text_field,
        'status_filter': args.status,
        'rows_skipped_by_status': skipped_status,
        'sources': [str(path) for path in sources],
        'span_exactness': 'char_start/char_end verified against normalised document text',
    }
    storage.write_manifest(out / 'chunk_manifest.json', summary, files=[path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--corpus', nargs='+', default=['work/corpus/corpus.parquet'],
                        help='Corpus files written by scripts/prepare.py.')
    parser.add_argument('--out', default='work/chunks')
    parser.add_argument('--status', default='ok',
                        help="Keep only rows whose `status` equals this when the column exists; "
                             "'' disables the filter.")
    parser.add_argument('--text-field', default=None,
                        help='Column holding the body. Default: text, content or body, else a '
                             'question plus answers.')
    parser.add_argument('--target-tokens', type=int, default=320)
    parser.add_argument('--overlap-tokens', type=int, default=64)
    parser.add_argument('--max-tokens', type=int, default=1024,
                        help='Hard ceiling; the organisers advise staying near 1024.')
    parser.add_argument('--min-tokens', type=int, default=24)
    args = parser.parse_args()
    if args.overlap_tokens >= args.target_tokens:
        parser.error('--overlap-tokens must be smaller than --target-tokens')
    if args.target_tokens > args.max_tokens:
        parser.error('--target-tokens cannot exceed --max-tokens')
    build(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
