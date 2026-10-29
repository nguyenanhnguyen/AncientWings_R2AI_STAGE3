"""D1: pick the documents and chunks to submit, with thresholds aimed at F2.

How many to return is not a matter of taste here; F2 settles it. For one query, with g relevant
documents, N returned and k of them correct:

    P = k/N,  R = k/g,  F2 = 5PR/(4P+R) = 5k / (4g + N)

Adding one more document raises N by one and raises k only if it is correct, so the expected score
improves exactly when that document's probability of being relevant exceeds k/(4g+N). With a
handful of relevant documents and ten or twenty returned, that break-even probability sits around
0.1-0.2: a candidate we are only 20% sure about is still worth submitting. The same reasoning
applies to chunks. Hence the generous defaults, and hence `--profile precision` exists but is not
the default.

Two limits pull the other way. Several overlapping windows of one document tend to match the same
reference chunk, so they add nothing to recall while each one costs precision — that is what
`chunk_per_doc` caps. And the submission has to stay a reasonable file size.
"""
from ..retrieval.rerank import adaptive_cutoff

PROFILES = {
    # doc_min/doc_max bound the document list; *_ratio keeps a candidate whose score is at least
    # that fraction of the query's best score.
    'recall': {'doc_min': 5, 'doc_max': 25, 'doc_ratio': 0.25,
               'chunk_min': 5, 'chunk_max': 30, 'chunk_ratio': 0.25, 'chunk_per_doc': 2},
    'balanced': {'doc_min': 3, 'doc_max': 15, 'doc_ratio': 0.45,
                 'chunk_min': 3, 'chunk_max': 15, 'chunk_ratio': 0.45, 'chunk_per_doc': 2},
    'precision': {'doc_min': 1, 'doc_max': 7, 'doc_ratio': 0.65,
                  'chunk_min': 1, 'chunk_max': 7, 'chunk_ratio': 0.65, 'chunk_per_doc': 1},
}


def policy(profile='balanced', adaptive=False, sync_docs=True, **overrides):
    if profile not in PROFILES:
        raise ValueError(f'Unknown profile {profile!r}; choose from {sorted(PROFILES)}')
    settings = dict(PROFILES[profile])
    settings.update({key: value for key, value in overrides.items() if value is not None})
    settings['profile'] = profile
    settings['adaptive'] = adaptive
    settings['sync_docs'] = sync_docs
    return settings


def _keep_by_ratio(scores, minimum, maximum, ratio):
    """Indices to keep: always the first `minimum`, then while the score holds up, capped."""
    if not scores:
        return 0
    best = scores[0]
    if best <= 0:
        return min(minimum, maximum, len(scores))
    floor = best * ratio
    kept = 0
    for score in scores[:maximum]:
        if kept < minimum or score >= floor:
            kept += 1
        else:
            break
    return max(1, kept)


def _candidate_score(candidate):
    """Cross-encoder score when the reranker ran, otherwise the fused rank score."""
    return candidate['ce_score'] if candidate.get('ce_score') is not None else candidate['rrf_score']


def select_for_query(record, settings):
    """-> (doc_ids, chunks) for one retrieval record. Chunks keep doc_id and chunk_order."""
    candidates = sorted(record.get('candidates') or [], key=_candidate_score, reverse=True)
    chunk_scores = [_candidate_score(candidate) for candidate in candidates]
    limit = settings['chunk_max']
    if settings['adaptive'] and chunk_scores:
        limit = min(limit, max(settings['chunk_min'],
                               adaptive_cutoff(chunk_scores, min_k=settings['chunk_min'],
                                               max_k=settings['chunk_max'])))
    chunks = []
    per_doc = {}
    for candidate in candidates:
        if len(chunks) >= limit:
            break
        if len(chunks) >= settings['chunk_min'] and (
                chunk_scores[0] <= 0 or _candidate_score(candidate) < chunk_scores[0]*settings['chunk_ratio']):
            break
        doc_id = int(candidate['doc_id'])
        if per_doc.get(doc_id, 0) >= settings['chunk_per_doc']:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        chunks.append({'doc_id': doc_id, 'chunk_id': candidate['chunk_id'],
                       'chunk_order': int(candidate['chunk_order']),
                       'score': round(float(_candidate_score(candidate)), 6)})

    documents = record.get('documents') or []
    doc_scores = [float(item['score']) for item in documents]
    keep_docs = _keep_by_ratio(doc_scores, settings['doc_min'], settings['doc_max'],
                               settings['doc_ratio'])
    doc_ids = [int(item['doc_id']) for item in documents[:keep_docs]]
    if settings['sync_docs']:
        # A chunk we are confident enough to submit implies its document is relevant; listing the
        # document costs one slot and can only help document recall.
        for chunk in chunks:
            if chunk['doc_id'] not in doc_ids:
                doc_ids.append(chunk['doc_id'])
    return doc_ids, chunks


def select(records, settings):
    """-> {query_id: (doc_ids, chunks)} plus a summary of how much was selected."""
    chosen = {}
    doc_counts, chunk_counts = [], []
    for record in records:
        doc_ids, chunks = select_for_query(record, settings)
        chosen[int(record['query_id'])] = (doc_ids, chunks)
        doc_counts.append(len(doc_ids))
        chunk_counts.append(len(chunks))
    summary = {
        'queries': len(chosen),
        'settings': settings,
        'docs_total': sum(doc_counts),
        'docs_mean': round(sum(doc_counts) / max(1, len(doc_counts)), 2),
        'docs_max': max(doc_counts, default=0),
        'queries_without_docs': sum(1 for count in doc_counts if count == 0),
        'chunks_total': sum(chunk_counts),
        'chunks_mean': round(sum(chunk_counts) / max(1, len(chunk_counts)), 2),
        'chunks_max': max(chunk_counts, default=0),
        'queries_without_chunks': sum(1 for count in chunk_counts if count == 0),
    }
    return chosen, summary
