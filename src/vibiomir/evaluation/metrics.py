"""E2: the contest's document and chunk scores, implemented as published.

Document level, per query, over the retrieved set D and the reference set G:

    P = |D ∩ G| / |D|,  R = |D ∩ G| / |G|

Chunk level: both sides are normalised (NFKC, HTML entities decoded, lowercased, whitespace
collapsed), then a submitted chunk c is compared with each reference g of the same query and the
same doc_id by the longest common token subsequence:

    overlap(c, g) = LCS_tokens(c, g) / |g|

A submitted chunk counts as correct when its overlap with at least one reference reaches 0.40.
Chunk precision divides correct submitted chunks by submitted chunks; chunk recall divides the
references that were found by all references. Both levels then use

    F2 = 5PR / (4P + R)

and every figure is the plain mean across queries.

Two details the published rules leave open, fixed here and stated rather than hidden. The token
basis for the LCS is not specified, so `tokenize_for_match` is used: Latin and digit runs are
tokens and each CJK character is its own token, which is the only split that behaves sensibly for
Chinese. And a query with no references at all is excluded from the mean and reported separately,
because precision and recall are both undefined for it.
"""
from ..common.schema import tokenize_for_match

THRESHOLD = 0.40


def lcs_length(left, right):
    """Longest common subsequence length over two token lists.

    Bit-parallel formulation of Crochemore, Iliopoulos, Pinzon and Reid (2001): one machine word
    per 64 tokens instead of a full dynamic-programming table, which keeps whole-dev-set scoring
    in seconds rather than minutes. `tests/test_pipeline.py` checks it against a plain DP.
    """
    if not left or not right:
        return 0
    if len(left) > len(right):
        left, right = right, left
    width = len(left)
    masks = {}
    for position, token in enumerate(left):
        masks[token] = masks.get(token, 0) | (1 << position)
    full = (1 << width) - 1
    state = full
    for token in right:
        match = masks.get(token)
        if not match:
            continue
        carry = state & match
        state = ((state + carry) | (state - carry)) & full
    return width - bin(state).count('1')


def overlap(candidate_tokens, reference_tokens):
    if not reference_tokens:
        return 0.0
    common = set(candidate_tokens)
    # Cheap upper bound first: if the tokens they share cannot reach the threshold, skip the LCS.
    shared = sum(1 for token in reference_tokens if token in common)
    if shared / len(reference_tokens) < THRESHOLD:
        return 0.0
    return lcs_length(candidate_tokens, reference_tokens) / len(reference_tokens)


def f2(precision, recall):
    if precision + recall <= 0:
        return 0.0
    return 5 * precision * recall / (4 * precision + recall)


def score_documents(retrieved, reference):
    retrieved, reference = list(dict.fromkeys(retrieved)), set(reference)
    hits = sum(1 for doc_id in retrieved if doc_id in reference)
    precision = hits / len(retrieved) if retrieved else 0.0
    recall = hits / len(reference) if reference else 0.0
    return {'precision': precision, 'recall': recall, 'f2': f2(precision, recall),
            'retrieved': len(retrieved), 'reference': len(reference), 'hits': hits}


def score_chunks(submitted, reference):
    """`submitted` and `reference` are [{'doc_id': int, 'chunk_text': str}] for one query."""
    by_doc = {}
    for position, item in enumerate(reference):
        by_doc.setdefault(int(item['doc_id']), []).append(
            (position, tokenize_for_match(item['chunk_text'])))
    correct = 0
    found = set()
    for item in submitted:
        tokens = tokenize_for_match(item['chunk_text'])
        matched = False
        for position, reference_tokens in by_doc.get(int(item['doc_id']), ()):
            if overlap(tokens, reference_tokens) >= THRESHOLD:
                matched = True
                found.add(position)
        correct += matched
    precision = correct / len(submitted) if submitted else 0.0
    recall = len(found) / len(reference) if reference else 0.0
    return {'precision': precision, 'recall': recall, 'f2': f2(precision, recall),
            'submitted': len(submitted), 'reference': len(reference),
            'correct': correct, 'references_found': len(found)}


def score_all(rows, labels):
    """`rows` are submission entries; `labels` is {query_id: {'docs': [...], 'chunks': [...]}}.

    -> (summary, per-query rows). Only queries present in `labels` are scored.
    """
    per_query = []
    for row in rows:
        label = labels.get(row['id'])
        if label is None:
            continue
        documents = [int(value) for value in label.get('docs') or []]
        chunks = label.get('chunks') or []
        per_query.append({
            'query_id': row['id'],
            'document': score_documents([int(value) for value in row['relevant_docs']], documents),
            'chunk': score_chunks(row['relevant_chunks'], chunks),
            'scored': bool(documents or chunks),
        })
    scored = [item for item in per_query if item['scored']]
    summary = {'queries_in_labels': len(labels), 'queries_scored': len(scored),
               'queries_without_reference': len(per_query) - len(scored),
               'queries_in_labels_not_submitted': len(labels) - len(per_query)}
    for level in ('document', 'chunk'):
        for metric in ('precision', 'recall', 'f2'):
            values = [item[level][metric] for item in scored]
            summary[f'{level}_{metric}'] = round(sum(values) / len(values), 6) if values else None
    return summary, per_query
