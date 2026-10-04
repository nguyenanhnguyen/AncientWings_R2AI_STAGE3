"""D2: rebuild every chunk_text from the corpus and check the file before it is written.

The rules require chunk_text to be content extracted from the source document, not rewritten or
generated. The only way to be sure is to stop trusting the copy carried through Blocks B and C:
each selected chunk is re-sliced from the document text using its recorded char offsets, and the
result must equal the indexed text. A mismatch means the corpus or the chunk file changed under
the index, and that is a hard error rather than a warning.

Checks that run here: offsets re-slice exactly, the chunk belongs to the document it claims, the
document id exists in the corpus (and in links_corpus.parquet when it is given), every query has
an entry, and no chunk is far past the ~1024 token size the organisers advise.
"""
from ..common import schema, storage

TOKEN_ADVICE = 1024


def load_chunk_table(path):
    rows = storage.read_parquet(path)
    return {row['chunk_id']: row for row in rows}


def load_document_texts(paths, text_field=None):
    """-> {doc_id: text}. Uses the same `document_text` as chunking; first id wins across shards."""
    documents = {}
    for path in paths:
        rows = storage.read_rows(path, lambda names: schema.document_columns(names, text_field))
        for row in rows:
            doc_id = int(row['id'])
            if doc_id not in documents:
                documents[doc_id] = schema.document_text(row, text_field)
    return documents


def build_rows(chosen, chunk_table, documents, query_ids, doc_id_as_string=False,
               allowed_doc_ids=None):
    """-> (submission rows, report). Raises ValueError on any provenance failure."""
    rows = []
    report = {'queries': len(query_ids), 'chunks_checked': 0, 'resliced_from_offsets': 0,
              'warnings': [], 'dropped_chunks': 0, 'dropped_docs': 0}
    for query_id in query_ids:
        doc_ids, chunks = chosen.get(query_id, ([], []))
        kept_docs = []
        for doc_id in doc_ids:
            if doc_id not in documents:
                report['dropped_docs'] += 1
                report['warnings'].append(f'query {query_id}: doc {doc_id} not in the corpus')
                continue
            if allowed_doc_ids is not None and doc_id not in allowed_doc_ids:
                report['dropped_docs'] += 1
                report['warnings'].append(f'query {query_id}: doc {doc_id} not in links_corpus')
                continue
            if doc_id not in kept_docs:
                kept_docs.append(doc_id)
        kept_chunks = []
        for chunk in chunks:
            record = chunk_table.get(chunk['chunk_id'])
            if record is None:
                raise ValueError(f"query {query_id}: chunk {chunk['chunk_id']} is not in the "
                                 'chunk file; Block C ran against a different chunking.')
            if int(record['doc_id']) != int(chunk['doc_id']):
                raise ValueError(f"query {query_id}: chunk {chunk['chunk_id']} claims doc "
                                 f"{chunk['doc_id']} but belongs to {record['doc_id']}.")
            text = documents.get(int(record['doc_id']))
            if text is None:
                report['dropped_chunks'] += 1
                report['warnings'].append(
                    f"query {query_id}: doc {record['doc_id']} missing, chunk dropped")
                continue
            span = text[record['char_start']:record['char_end']]
            if span != record['text']:
                raise ValueError(
                    f"query {query_id}: chunk {chunk['chunk_id']} does not re-slice from the "
                    'corpus; the corpus or the chunk file changed after indexing.')
            report['resliced_from_offsets'] += 1
            report['chunks_checked'] += 1
            if schema.count_tokens(span) > TOKEN_ADVICE:
                report['warnings'].append(
                    f"query {query_id}: chunk {chunk['chunk_id']} is over {TOKEN_ADVICE} tokens")
            kept_chunks.append({'doc_id': int(record['doc_id']), 'chunk_text': span,
                                'chunk_order': int(record['chunk_order'])})
            # A chunk's document joins relevant_docs, but only if it would have passed the same
            # filters on its own; otherwise this path would smuggle in an id the rules exclude.
            doc_id = int(record['doc_id'])
            if doc_id not in kept_docs and (allowed_doc_ids is None or doc_id in allowed_doc_ids):
                kept_docs.append(doc_id)
        rows.append(schema.submission_row(query_id, kept_docs, kept_chunks,
                                          doc_id_as_string=doc_id_as_string))
    problems = schema.validate_submission_shape(rows, query_ids)
    if problems:
        raise ValueError('Submission shape invalid: ' + '; '.join(problems))
    report['empty_doc_lists'] = sum(1 for row in rows if not row['relevant_docs'])
    report['empty_chunk_lists'] = sum(1 for row in rows if not row['relevant_chunks'])
    report['warnings'] = report['warnings'][:50]
    return rows, report


def load_allowed_doc_ids(path):
    """Ids from links_corpus.parquet. Anything outside this list can never be a positive label."""
    return {int(row['id']) for row in storage.read_parquet(path, columns=['id'])}
