"""C2: rank each channel separately, then merge the rankings with Reciprocal Rank Fusion.

RRF merges by rank, not by score, so a BM25 score and a cosine similarity never have to be put on
one scale. Each channel is one (query variant, index) pair: the Vietnamese query against BM25, the
same query against the dense index, a translated query against BM25, and so on. A channel that
cannot see part of the corpus — BM25 against Chinese text, for one — simply contributes nothing
there instead of dragging the fused ranking down.

Document scores are aggregated from chunk ranks. A document whose several chunks all rank well is
more likely relevant than one with a single lucky chunk, so the default sums the RRF weight of its
best few chunks rather than taking the single maximum.
"""
import numpy as np

RRF_K = 60


def rrf_fuse(rankings, weights=None, top_k=200, rrf_k=RRF_K):
    """Merge ranked lists into [(row, fused score, [channel names])] sorted by score."""
    weights = weights or {}
    fused = {}
    sources = {}
    for name, (rows, _scores) in rankings.items():
        weight = float(weights.get(name, weights.get(name.split(':', 1)[0], 1.0)))
        if weight == 0:
            continue
        for rank, row in enumerate(rows):
            fused[row] = fused.get(row, 0.0) + weight / (rrf_k + rank + 1)
            sources.setdefault(row, []).append(name)
    order = sorted(fused, key=lambda row: (-fused[row], row))[:top_k]
    return [(row, fused[row], sources[row]) for row in order]


def aggregate_documents(scored, doc_ids, top_chunks_per_doc=3):
    """-> [(doc_id, score, [rows])] ranked. Score sums a document's best chunk scores.

    `scored` is [(row, score)] using the strongest score available for each chunk: the
    reranker's probability when it ran, the fused RRF score otherwise. Ranking documents by RRF
    while chunks were reranked would discard the best signal at exactly the document level.
    """
    grouped = {}
    for row, score in scored:
        doc_id = int(doc_ids[row])
        grouped.setdefault(doc_id, []).append((row, score))
    result = []
    for doc_id, items in grouped.items():
        items.sort(key=lambda pair: -pair[1])
        kept = items[:top_chunks_per_doc]
        result.append((doc_id, float(sum(score for _row, score in kept)),
                       [row for row, _score in items]))
    result.sort(key=lambda item: (-item[1], item[0]))
    return result


def make_dense_search(embeddings_path, faiss_index=None, nprobe=32):
    """Return a search(vectors, k) -> (rows, scores) closure over the vector index."""
    if faiss_index is not None:
        import faiss

        index = faiss.read_index(str(faiss_index))
        if hasattr(index, 'nprobe'):
            index.nprobe = min(nprobe, index.nlist)

        def search(vectors, k):
            scores, rows = index.search(np.asarray(vectors, dtype=np.float32), k)
            # faiss pads short result lists with row -1; used as an index that would silently
            # pick the last chunk, so those slots are dropped per query.
            kept = [(row[row >= 0], score[row >= 0]) for row, score in zip(rows, scores)]
            return [row for row, _ in kept], [score for _, score in kept]

        return search

    from ..index.embedding import search as numpy_search

    def search(vectors, k):
        return numpy_search(embeddings_path, vectors, k)

    return search
