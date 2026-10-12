"""Conservative lexical pseudo relevance feedback from a previous reranked pass.

This is a TF-IDF expansion heuristic, not RM3 or verified relevance. Terms must
occur in two different seed documents. The original retrieval channels survive.
"""
from collections import Counter, defaultdict
import math

from ..index.bm25 import tokenize


def expand(candidates, chunks_by_id, bm25, original_tokens, documents=5, terms=8):
    seen, seeds, frequencies = set(), [], []
    for candidate in candidates:
        chunk = chunks_by_id.get(str(candidate['chunk_id']))
        if chunk is None:
            raise ValueError('Feedback candidate is absent from the current chunk snapshot.')
        doc = int(chunk['doc_id'])
        if doc in seen:
            continue
        seen.add(doc)
        seeds.append(doc)
        frequencies.append(Counter(tokenize(chunk.get('text') or chunk.get('chunk_text') or '')))
        if len(seeds) >= documents:
            break
    support, score = Counter(), defaultdict(float)
    original = set(original_tokens)
    for rank, counts in enumerate(frequencies, 1):
        length = max(sum(counts.values()), 1)
        for term, count in counts.items():
            idx = bm25.term_ids.get(term)
            if idx is None or term in original or len(term) < 2 or term.isdigit():
                continue
            df = int(bm25.offsets[idx + 1] - bm25.offsets[idx])
            if df / max(bm25.n_docs, 1) > .2:
                continue
            support[term] += 1
            score[term] += (count / length) * float(bm25.idf[idx]) / math.log2(rank + 1)
    chosen = sorted((t for t in score if support[t] >= 2), key=lambda t: (-score[t], t))[:terms]
    return chosen, {'seed_doc_ids': seeds, 'terms': chosen,
                    'term_support': {t: support[t] for t in chosen},
                    'term_scores': {t: score[t] for t in chosen}}
