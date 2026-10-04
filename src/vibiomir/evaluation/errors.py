"""E2: attribute each miss to the block that caused it, so effort goes where the loss is.

A missed document fails at exactly one of four places, and the fix is different each time:

    not_crawled      The reference document is not in the corpus. No retrieval change can recover
                     it; this is Block A coverage, and it caps recall no matter what follows.
    not_retrieved    It is in the corpus but no chunk of it reached the candidate list. Block B/C:
                     the encoder, the channels or top_k.
    not_selected     A chunk of it was a candidate but the document did not survive the cut.
                     Block D1 thresholds, the cheapest thing to change.
    chunk_too_narrow The document was submitted and a chunk with it, but no submitted chunk
                     reached 40% overlap with a reference passage. Block A4 chunk sizing.

False positives are counted too, since F2 still pays for precision: a document returned that is
not in the reference set is a reranking or threshold problem, not a crawl problem.
"""
from collections import Counter

from ..common.schema import tokenize_for_match
from .metrics import THRESHOLD, overlap

CAUSES = ('not_crawled', 'not_retrieved', 'not_selected', 'chunk_too_narrow')


def classify(labels, records, rows, corpus_doc_ids):
    """-> (summary, cases). `records` is Block C output, `rows` the submission entries."""
    by_query_candidates = {int(record['query_id']): record for record in records}
    by_query_submitted = {int(row['id']): row for row in rows}
    counts = Counter()
    cases = []
    false_positive_docs = 0
    submitted_docs = 0
    for query_id, label in sorted(labels.items()):
        reference_docs = {int(value) for value in label.get('docs') or []}
        record = by_query_candidates.get(query_id, {})
        submission = by_query_submitted.get(query_id, {})
        candidate_docs = {int(item['doc_id']) for item in record.get('candidates') or []}
        chosen_docs = {int(value) for value in submission.get('relevant_docs') or []}
        submitted_docs += len(chosen_docs)
        false_positive_docs += len(chosen_docs - reference_docs)
        reference_chunks = label.get('chunks') or []
        submitted_chunks = submission.get('relevant_chunks') or []
        for doc_id in sorted(reference_docs):
            if doc_id not in corpus_doc_ids:
                cause = 'not_crawled'
            elif doc_id not in candidate_docs:
                cause = 'not_retrieved'
            elif doc_id not in chosen_docs:
                cause = 'not_selected'
            else:
                cause = _chunk_cause(doc_id, reference_chunks, submitted_chunks)
            if cause:
                counts[cause] += 1
                cases.append({'query_id': query_id, 'doc_id': doc_id, 'cause': cause})
            else:
                counts['hit'] += 1
    total = sum(counts[cause] for cause in CAUSES) + counts['hit']
    summary = {
        'reference_documents': total,
        'documents_found': counts['hit'],
        'losses': {cause: counts[cause] for cause in CAUSES},
        'loss_share': {cause: round(counts[cause] / total, 4) if total else None
                       for cause in CAUSES},
        'submitted_documents': submitted_docs,
        'false_positive_documents': false_positive_docs,
        # Only name a worst cause when something was actually lost; max() over all-zero counts
        # would otherwise point at whichever cause happens to be listed first.
        'biggest_loss': (max(CAUSES, key=lambda cause: counts[cause])
                         if any(counts[cause] for cause in CAUSES) else None),
    }
    return summary, cases


def _chunk_cause(doc_id, reference_chunks, submitted_chunks):
    """None when a submitted chunk of this document reaches the overlap threshold."""
    references = [tokenize_for_match(item['chunk_text']) for item in reference_chunks
                  if int(item['doc_id']) == doc_id]
    if not references:
        return None
    for item in submitted_chunks:
        if int(item['doc_id']) != doc_id:
            continue
        tokens = tokenize_for_match(item['chunk_text'])
        if any(overlap(tokens, reference) >= THRESHOLD for reference in references):
            return None
    return 'chunk_too_narrow'


ADVICE = {
    'not_crawled': 'Mở rộng độ phủ crawl (Block A); đổi retrieval không lấy lại được tài liệu này.',
    'not_retrieved': 'Xem lại encoder, số kênh và top_k (Block B/C).',
    'not_selected': 'Nới ngưỡng chọn trong Block D1; đây là thay đổi rẻ nhất.',
    'chunk_too_narrow': 'Tăng kích thước hoặc overlap của chunk (Block A4).',
}


def report_markdown(summary, metric_summary, label_sources):
    lines = ['# Phân tích lỗi theo block', '',
             f"Nguồn nhãn: {', '.join(label_sources)}.",
             '']
    if 'pseudo' in label_sources:
        lines += ['> Nhãn `pseudo` sinh từ chính pipeline. Điểm dưới đây là vòng tròn và '
                  'không nói gì về chất lượng thật.', '']
    lines += ['| Cấp | Precision | Recall | F2 |', '| --- | ---: | ---: | ---: |']
    for level, name in (('document', 'Tài liệu'), ('chunk', 'Đoạn')):
        values = [metric_summary.get(f'{level}_{metric}') for metric in
                  ('precision', 'recall', 'f2')]
        cells = ' | '.join('—' if value is None else f'{value:.4f}' for value in values)
        lines.append(f'| {name} | {cells} |')
    lines += ['', f"Truy vấn được chấm: {metric_summary.get('queries_scored')}.", '',
              '| Nguyên nhân mất tài liệu | Số lượng | Tỷ lệ | Hướng xử lý |',
              '| --- | ---: | ---: | --- |']
    for cause in CAUSES:
        count = summary['losses'][cause]
        share = summary['loss_share'][cause]
        lines.append(f"| {cause} | {count} | "
                     f"{'—' if share is None else f'{share:.1%}'} | {ADVICE[cause]} |")
    lines += ['', f"Tài liệu tham chiếu tìm được: {summary['documents_found']}"
                  f"/{summary['reference_documents']}.",
              f"Tài liệu nộp sai: {summary['false_positive_documents']}"
              f"/{summary['submitted_documents']}.", '']
    if summary['biggest_loss']:
        lines.append(f"Mất nhiều nhất ở **{summary['biggest_loss']}**: "
                     f"{ADVICE[summary['biggest_loss']]}")
    return '\n'.join(lines) + '\n'
