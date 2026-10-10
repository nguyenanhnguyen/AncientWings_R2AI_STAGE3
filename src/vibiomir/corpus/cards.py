"""Document cards and candidate subsets: the two ends of the cascaded retrieval.

Why a cascade. The crawl grows towards millions of documents and several million chunks, while
only 1.200 queries are ever asked, all known in advance. Encoding every chunk costs tens of GPU
hours; encoding one short card per document costs a fraction of that. So retrieval runs twice:

1. `build`  writes one card per document: the title plus the opening segments (`lead_span`). On
   health articles the opening states the topic; on Q&A pages it is the patient's question, and
   matching question to question is far easier than question to answer. Cards use the chunk
   schema, so the BM25/dense index builders and the retrieval CLI work on them unchanged.
2. Retrieval over the cards gives each query its top documents.
3. `subset` keeps the chunks of those documents only (the union over all queries) and writes, per
   query, its ranked document list. Chunk-level indexing, retrieval and reranking then run on this
   much smaller set, and the document ranking returns as its own fusion channel ("card").

Chunk ids, offsets and text in the subset are the rows of the full chunk file, untouched, so the
submission re-slice check still proves every chunk is source text.
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
from .chunk import lead_span

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
    ranked = ranked_documents(args.candidates, args.docs_per_query)
    if not ranked:
        raise ValueError('No card candidates; run card retrieval first.')
    wanted = sorted({doc_id for docs in ranked.values() for doc_id in docs})
    table = pq.read_table(args.chunks)
    mask = pc.is_in(table['doc_id'], value_set=pa.array(wanted, type=pa.int64()))
    picked = table.filter(mask)
    if picked.num_rows == 0:
        raise ValueError('No chunk belongs to a candidate document; cards and chunks differ.')
    out = Path(args.out)
    path = storage.write_table(out / 'chunks.parquet', picked)
    doc_path = out / 'doc_candidates.jsonl'
    storage.write_jsonl(doc_path, [{'query_id': query_id, 'doc_ids': docs}
                                   for query_id, docs in sorted(ranked.items())])
    summary = {'stage': 'subset', 'queries': len(ranked), 'documents': len(wanted),
               'documents_per_query': args.docs_per_query, 'chunks': picked.num_rows,
               'chunks_in_full_file': table.num_rows,
               'chunks_file': str(args.chunks), 'chunks_sha256': storage.sha256_file(args.chunks),
               'candidates': [str(path) for path in args.candidates]}
    # A chunk_manifest next to the subset lets Block D recover the text field used by chunking.
    source_manifest = Path(args.chunks).with_name('chunk_manifest.json')
    text_field = storage.read_json(source_manifest).get('text_field') if source_manifest.exists() else None
    storage.write_manifest(out / 'chunk_manifest.json', {**summary, 'text_field': text_field},
                           files=[path, doc_path])
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
    step = sub.add_parser('subset', help='Chunks of the documents found through the cards.')
    step.add_argument('--candidates', nargs='+', required=True,
                      help='candidates.jsonl from retrieval over the cards (one or more shards).')
    step.add_argument('--chunks', default='work/chunks/chunks.parquet')
    step.add_argument('--out', default='work/subset')
    step.add_argument('--docs-per-query', type=int, default=200)
    step.set_defaults(func=subset)
    args = parser.parse_args()
    if getattr(args, 'lead_tokens', 16) < 16 or getattr(args, 'docs_per_query', 1) < 1:
        parser.error('--lead-tokens must be >= 16 and --docs-per-query positive.')
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
