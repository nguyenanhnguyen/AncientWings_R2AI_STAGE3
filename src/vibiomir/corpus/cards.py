"""Document cards and candidate subsets: the two ends of the cascaded retrieval.

Why a cascade. The crawl grows towards millions of documents and several million chunks, while
only 1.200 queries are ever asked, all known in advance. Encoding every chunk costs tens of GPU
hours; encoding one short card per document costs a fraction of that. So retrieval runs twice:

1. `build`  writes one card per document: the title plus the opening segments (`lead_span`). On
   health articles the opening states the topic; on Q&A pages it is the patient's question, and
   matching question to question is far easier than question to answer. Cards use the chunk
   schema, so the BM25/dense index builders and the retrieval CLI work on them unchanged.
2. Retrieval over the cards gives each query its top documents.
3. `subset` chunks those documents only (the union over all queries) and writes, per query, its
   ranked document list. Chunk-level indexing, retrieval and reranking then run on this much
   smaller set, and the document ranking returns as its own fusion channel ("card").

Chunks carry exact char offsets into the corpus text, so the submission re-slice check still
proves every chunk is source text.
"""
import argparse
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ..common import storage
from ..common.console import emit
from ..common.schema import (CHUNK_SCHEMA, count_tokens, detect_language, document_columns,
                             document_text)
from .chunk import chunk_document, lead_span

CARD_SUFFIX = 'card'


def card_for(document, lead_tokens=160, text_field=None):
    text = document_text(document, text_field)
    if not text.strip():
        return None
    start, end = lead_span(text, lead_tokens)
    span = text[start:end]
    if not span.strip():
        return None
    title = (document.get('title') or '').strip()
    return {
        'chunk_id': f"{int(document['id'])}:{CARD_SUFFIX}",
        'doc_id': int(document['id']),
        'chunk_order': 0,
        'char_start': start,
        'char_end': end,
        'text': span,
        'title': title,
        # Language of the document body, not of the lead: the reranker later matches the query
        # language to the document, and a Chinese page can open with an English drug name.
        'lang': document.get('lang') or detect_language(text[:4000]),
        'n_tokens': count_tokens(span),
        'domain': document.get('domain') or '',
    }


def build(args):
    cards, seen, empty = [], set(), 0
    for source in args.corpus:
        for path in storage.parquet_files(source):
            rows = storage.read_rows(path, lambda names: document_columns(names, args.text_field)
                                     + [name for name in ('lang',) if name in names])
            for row in rows:
                doc_id = int(row['id'])
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                card = card_for(row, args.lead_tokens, args.text_field)
                if card is None:
                    empty += 1
                else:
                    cards.append(card)
    if not cards:
        raise ValueError('No document produced a card; check the corpus text column.')
    cards.sort(key=lambda row: row['doc_id'])
    out = Path(args.out)
    path = storage.write_parquet(out / 'cards.parquet', cards, schema=CHUNK_SCHEMA)
    sizes = sorted(row['n_tokens'] for row in cards)
    summary = {'stage': 'cards', 'cards': len(cards), 'documents_without_text': empty,
               'lead_tokens': args.lead_tokens, 'tokens_median': sizes[len(sizes) // 2],
               'tokens_p95': sizes[int(len(sizes) * 0.95)],
               'sources': [str(source) for source in args.corpus]}
    storage.write_manifest(out / 'cards_manifest.json', summary, files=[path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def ranked_documents(candidate_files, limit=None):
    """{query_id: [doc_id, ...]} in card-retrieval order, from one or more candidates.jsonl."""
    ranked = {}
    for path in candidate_files:
        for record in storage.iter_jsonl(path):
            query_id = int(record['query_id'])
            if query_id in ranked:
                raise ValueError(f'Query {query_id} appears in more than one candidates file.')
            order = []
            for candidate in record.get('candidates') or []:
                doc_id = int(candidate['doc_id'])
                if doc_id not in order:
                    order.append(doc_id)
            ranked[query_id] = order[:limit] if limit else order
    return ranked


def subset(args):
    """Chunk only the documents some query found through the cards (the union over queries).

    Chunking the whole corpus would spend most of its time on documents no query ever reaches;
    here only candidates are read (a Parquet filter on id) and cut, with the same chunker and the
    same span guarantees as `chunk.py`.
    """
    ranked = ranked_documents(args.candidates, args.docs_per_query)
    if not ranked:
        raise ValueError('No card candidates; run card retrieval first.')
    wanted = sorted({doc_id for docs in ranked.values() for doc_id in docs})
    options = {'target_tokens': args.target_tokens, 'overlap_tokens': args.overlap_tokens,
               'max_tokens': args.max_tokens, 'min_tokens': args.min_tokens}
    rows, seen = [], set()
    id_filter = pa.array(wanted, type=pa.int64())
    for source in args.corpus:
        for path in storage.parquet_files(source):
            table = pq.read_table(path, columns=None)
            table = table.filter(pc.is_in(table['id'], value_set=id_filter))
            for document in table.to_pylist():
                doc_id = int(document['id'])
                if doc_id in seen:
                    continue
                seen.add(doc_id)
                rows.extend(chunk_document(document, text_field=args.text_field, **options))
    if not rows:
        raise ValueError('No chunk from the candidate documents; cards and corpus differ.')
    rows.sort(key=lambda row: (row['doc_id'], row['chunk_order']))
    out = Path(args.out)
    path = storage.write_parquet(out / 'chunks.parquet', rows, schema=CHUNK_SCHEMA)
    doc_path = out / 'doc_candidates.jsonl'
    storage.write_jsonl(doc_path, [{'query_id': query_id, 'doc_ids': docs}
                                   for query_id, docs in sorted(ranked.items())])
    summary = {'stage': 'subset', 'queries': len(ranked), 'documents': len(wanted),
               'documents_chunked': len(seen), 'documents_per_query': args.docs_per_query,
               'chunks': len(rows), 'chunks_per_document': round(len(rows) / max(1, len(seen)), 2),
               'options': options, 'text_field': args.text_field,
               'corpus': [str(source) for source in args.corpus],
               'candidates': [str(path) for path in args.candidates],
               'span_exactness': 'char_start/char_end verified against normalised document text'}
    # Named like chunk.py's manifest: Block D reads the text field used for chunking from it.
    storage.write_manifest(out / 'chunk_manifest.json', summary, files=[path, doc_path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    step = sub.add_parser('build', help='One card per document.')
    step.add_argument('--corpus', nargs='+', default=['work/corpus/corpus.parquet'])
    step.add_argument('--out', default='work/cards')
    step.add_argument('--lead-tokens', type=int, default=160)
    step.add_argument('--text-field', default=None)
    step.set_defaults(func=build)
    step = sub.add_parser('subset', help='Chunk the documents found through the cards.')
    step.add_argument('--candidates', nargs='+', required=True,
                      help='candidates.jsonl from retrieval over the cards (one or more shards).')
    step.add_argument('--corpus', nargs='+', default=['work/corpus/corpus.parquet'])
    step.add_argument('--out', default='work/subset')
    step.add_argument('--docs-per-query', type=int, default=200)
    step.add_argument('--target-tokens', type=int, default=384)
    step.add_argument('--overlap-tokens', type=int, default=32)
    step.add_argument('--max-tokens', type=int, default=768)
    step.add_argument('--min-tokens', type=int, default=24)
    step.add_argument('--text-field', default=None)
    step.set_defaults(func=subset)
    args = parser.parse_args()
    if getattr(args, 'lead_tokens', 16) < 16 or getattr(args, 'docs_per_query', 1) < 1:
        parser.error('--lead-tokens must be >= 16 and --docs-per-query positive.')
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
