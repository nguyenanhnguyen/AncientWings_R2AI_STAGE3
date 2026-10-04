"""Block D CLI: turn retrieval candidates into a validated submission.zip."""
import argparse
import json
from pathlib import Path
import sys

from ..common import storage
from ..common.console import emit
from ..retrieval.query import load_queries
from . import choose, export, validate


def build(args):
    records = storage.read_jsonl(args.candidates)
    if not records:
        raise ValueError(f'No candidates in {args.candidates}')
    queries = load_queries(args.queries)
    query_ids = [row['id'] for row in queries]
    settings = choose.policy(
        profile=args.profile, adaptive=args.adaptive, sync_docs=not args.no_sync_docs,
        doc_min=args.doc_min, doc_max=args.doc_max, doc_ratio=args.doc_ratio,
        chunk_min=args.chunk_min, chunk_max=args.chunk_max, chunk_ratio=args.chunk_ratio,
        chunk_per_doc=args.chunk_per_doc)
    chosen, selection = choose.select(records, settings)
    missing = [query_id for query_id in query_ids if query_id not in chosen]
    if missing:
        # Required by the rules: a missing query means the whole submission is not scored. The
        # entry is still written, with empty lists, so the file stays valid.
        emit(f'{len(missing)} truy vấn không có ứng viên; ghi danh sách rỗng cho chúng.')

    chunk_table = validate.load_chunk_table(args.chunks)
    text_field = args.text_field
    manifest = Path(args.chunks).with_name('chunk_manifest.json')
    if text_field is None and manifest.exists():
        # Chunk spans were cut from text derived with this field; re-slicing must derive it alike.
        text_field = storage.read_json(manifest).get('text_field')
    documents = validate.load_document_texts(args.corpus, text_field)
    allowed = validate.load_allowed_doc_ids(args.links) if args.links else None
    rows, report = validate.build_rows(chosen, chunk_table, documents, query_ids,
                                       doc_id_as_string=args.doc_id_as_string,
                                       allowed_doc_ids=allowed)
    json_path, zip_path = export.write_submission(rows, args.out, name=args.name)
    summary = {'selection': selection, 'validation': report, 'submission': export.summarise(rows),
               'queries_without_candidates': len(missing),
               'doc_id_type': 'string' if args.doc_id_as_string else 'integer',
               'candidates_file': str(args.candidates),
               'chunks_sha256': storage.sha256_file(args.chunks)}
    storage.write_manifest(Path(args.out) / 'submission_manifest.json', summary,
                           files=[json_path, zip_path])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    emit(f'\nNộp file: {zip_path}')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--candidates', default='work/retrieval/candidates.jsonl')
    parser.add_argument('--chunks', default='work/chunks/chunks.parquet')
    parser.add_argument('--corpus', nargs='+', required=True,
                        help='The same corpus files chunking used; chunk_text is re-sliced here.')
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--links', default=None,
                        help='links_corpus.parquet; drops any doc id outside the official list.')
    parser.add_argument('--out', default='work/submission')
    parser.add_argument('--name', default='submission.json')
    parser.add_argument('--text-field', default=None,
                        help='Default: the one recorded in chunk_manifest.json.')
    parser.add_argument('--profile', default='balanced', choices=sorted(choose.PROFILES))
    parser.add_argument('--adaptive', action='store_true',
                        help='Cut the chunk list at the largest reranker score gap.')
    parser.add_argument('--no-sync-docs', action='store_true',
                        help='Do not add the documents of selected chunks to relevant_docs.')
    parser.add_argument('--doc-min', type=int, default=None)
    parser.add_argument('--doc-max', type=int, default=None)
    parser.add_argument('--doc-ratio', type=float, default=None)
    parser.add_argument('--chunk-min', type=int, default=None)
    parser.add_argument('--chunk-max', type=int, default=None)
    parser.add_argument('--chunk-ratio', type=float, default=None)
    parser.add_argument('--chunk-per-doc', type=int, default=None)
    parser.add_argument('--doc-id-as-string', action='store_true',
                        help='Emit doc ids as JSON strings. The rules name the integer id field, '
                             'so integers are the default.')
    args = parser.parse_args()
    build(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
