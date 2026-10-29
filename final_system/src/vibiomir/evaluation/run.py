"""Block E CLI: score a submission against dev labels, or prepare the labels themselves.

    sheet   Export the top candidates of chosen queries for a person to mark.
    collect Turn a filled sheet into a label file.
    pseudo  Write circular labels from the pipeline's own output, for offline smoke runs.
    score   Score a submission with a label file and attribute every miss to a block.
"""
import argparse
import json
from pathlib import Path
import sys

from ..common import storage
from ..common.console import emit
from ..submission.validate import load_chunk_table
from . import errors, labels as label_tools, metrics


def _records(path):
    rows = storage.read_jsonl(path)
    if not rows:
        raise ValueError(f'No retrieval records in {path}')
    return rows


def sheet(args):
    chunk_table = load_chunk_table(args.chunks)
    queries = [int(value) for value in args.query_ids.split(',')] if args.query_ids else None
    path = label_tools.write_label_sheet(_records(args.candidates), chunk_table, args.out,
                                         per_query=args.per_query, queries=queries,
                                         limit=args.limit)
    emit(json.dumps({'sheet': str(path), 'html': str(Path(args.out) / 'label_sheet.html'),
                     'note': 'Điền trường relevant rồi chạy: evaluate.py collect'},
                    ensure_ascii=False, indent=2))


def collect(args):
    summary = label_tools.labels_from_sheet(args.sheet, Path(args.out) / 'labels.jsonl')
    emit(json.dumps(summary, ensure_ascii=False, indent=2))


def pseudo(args):
    chunk_table = load_chunk_table(args.chunks)
    summary = label_tools.pseudo_labels(_records(args.candidates), chunk_table,
                                        Path(args.out) / 'labels.jsonl', top_n=args.top_n)
    emit(json.dumps(summary, ensure_ascii=False, indent=2))


def score(args):
    rows = storage.read_json(args.submission)
    table, sources = label_tools.load_labels(args.labels)
    metric_summary, per_query = metrics.score_all(rows, table)
    corpus_ids = set()
    for path in args.corpus:
        source = storage.read_rows(path, lambda names: [n for n in names if n == 'id'])
        corpus_ids.update(int(row['id']) for row in source)
    loss_summary, cases = errors.classify(table, _records(args.candidates), rows, corpus_ids)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    storage.write_json(out / 'metrics.json', {'metrics': metric_summary, 'losses': loss_summary,
                                              'label_sources': sources})
    storage.write_jsonl(out / 'per_query.jsonl', per_query)
    storage.write_jsonl(out / 'loss_cases.jsonl', cases)
    report = errors.report_markdown(loss_summary, metric_summary, sources)
    (out / 'EVAL_REPORT.md').write_text(report, encoding='utf-8')
    if 'pseudo' in sources:
        emit('CẢNH BÁO: nhãn pseudo sinh từ chính pipeline; điểm là vòng tròn.')
    emit(report)
    return metric_summary


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)

    step = sub.add_parser('sheet', help='Export candidates for human labelling.')
    step.add_argument('--candidates', default='work/retrieval/candidates.jsonl')
    step.add_argument('--chunks', default='work/chunks/chunks.parquet')
    step.add_argument('--out', default='work/eval')
    step.add_argument('--per-query', type=int, default=10)
    step.add_argument('--limit', type=int, default=100, help='Number of queries in the sheet.')
    step.add_argument('--query-ids', default=None, help='Comma-separated ids instead of --limit.')
    step.set_defaults(func=sheet)

    step = sub.add_parser('collect', help='Build labels.jsonl from a filled sheet.')
    step.add_argument('--sheet', default='work/eval/label_sheet.jsonl')
    step.add_argument('--out', default='work/eval')
    step.set_defaults(func=collect)

    step = sub.add_parser('pseudo', help='Circular labels for an offline smoke run.')
    step.add_argument('--candidates', default='work/retrieval/candidates.jsonl')
    step.add_argument('--chunks', default='work/chunks/chunks.parquet')
    step.add_argument('--out', default='work/eval')
    step.add_argument('--top-n', type=int, default=3)
    step.set_defaults(func=pseudo)

    step = sub.add_parser('score', help='Score a submission and attribute the misses.')
    step.add_argument('--submission', default='work/submission/submission.json')
    step.add_argument('--labels', default='work/eval/labels.jsonl')
    step.add_argument('--candidates', default='work/retrieval/candidates.jsonl')
    step.add_argument('--corpus', nargs='+', default=['work/corpus/corpus.parquet'])
    step.add_argument('--out', default='work/eval')
    step.set_defaults(func=score)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
