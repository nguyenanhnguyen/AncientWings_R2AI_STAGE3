"""B2: keyword index over chunks, with a tokenizer that does not silently drop Chinese.

Vietnamese and English split on spaces; Chinese does not. Tokenising CJK text by whitespace would
make a whole sentence one term and the index useless, so CJK runs become character unigrams plus
bigrams (the usual segmenter-free choice for Chinese IR). A Vietnamese query therefore reaches
Chinese documents only through the dense channel or a translated query variant, which is expected
and is why Block C fuses channels instead of relying on BM25 alone.

The index is an inverted list in flat numpy arrays, following the shape used in the LegalQA
notebook under docs/solution: scoring touches only the postings of query terms, so it stays fast
as the corpus grows.
"""
import math
import re

import numpy as np

from ..common.schema import normalise_for_match

_LATIN = re.compile(r'[^\W\d_]+|\d+', re.UNICODE)
_CJK_RUN = re.compile(r'[㐀-鿿぀-ヿ가-힯]+')


def tokenize(text):
    """Latin/digit words plus CJK unigrams and bigrams, over the normalised form of the text."""
    if not text:
        return []
    text = normalise_for_match(text)
    tokens = []
    cursor = 0
    for match in _CJK_RUN.finditer(text):
        tokens.extend(_LATIN.findall(text[cursor:match.start()]))
        run = match.group()
        tokens.extend(run)
        tokens.extend(run[i:i + 2] for i in range(len(run) - 1))
        cursor = match.end()
    tokens.extend(_LATIN.findall(text[cursor:]))
    return tokens


class BM25:
    """Okapi BM25 over a fixed list of tokenised documents."""

    def __init__(self, terms, postings_index, postings_freq, offsets, idf, doc_len, k1=1.5, b=0.75):
        self.terms = terms
        self.postings_index = postings_index
        self.postings_freq = postings_freq
        self.offsets = offsets
        self.idf = idf
        self.doc_len = doc_len
        self.k1, self.b = float(k1), float(b)
        self.n_docs = len(doc_len)
        self.avgdl = float(doc_len.mean()) if self.n_docs else 0.0
        self.term_ids = {term: position for position, term in enumerate(terms)}

    @classmethod
    def build(cls, tokenized_docs, k1=1.5, b=0.75):
        document_frequency = {}
        per_document = []
        for tokens in tokenized_docs:
            frequencies = {}
            for token in tokens:
                frequencies[token] = frequencies.get(token, 0) + 1
            per_document.append(frequencies)
            for token in frequencies:
                document_frequency[token] = document_frequency.get(token, 0) + 1
        terms = sorted(document_frequency)
        term_ids = {term: position for position, term in enumerate(terms)}
        lengths = np.fromiter((sum(f.values()) for f in per_document),
                              dtype=np.float32, count=len(per_document))
        sizes = np.zeros(len(terms) + 1, dtype=np.int64)
        for term, frequency in document_frequency.items():
            sizes[term_ids[term] + 1] = frequency
        offsets = np.cumsum(sizes)
        postings_index = np.zeros(int(offsets[-1]), dtype=np.int32)
        postings_freq = np.zeros(int(offsets[-1]), dtype=np.float32)
        cursor = offsets[:-1].copy()
        for position, frequencies in enumerate(per_document):
            for token, frequency in frequencies.items():
                slot = cursor[term_ids[token]]
                postings_index[slot] = position
                postings_freq[slot] = frequency
                cursor[term_ids[token]] = slot + 1
        n_docs = len(per_document)
        raw = np.array([math.log((n_docs - document_frequency[term] + 0.5)
                                 / (document_frequency[term] + 0.5) + 1) for term in terms],
                       dtype=np.float32)
        # Floor non-positive idf at a fraction of the mean, as in the reference implementation:
        # a term in almost every document should contribute little, not negatively.
        if len(raw):
            raw = np.where(raw > 0, raw, 0.25 * float(raw.mean()))
        return cls(terms, postings_index, postings_freq, offsets, raw, lengths, k1, b)

    def scores(self, query_tokens):
        result = np.zeros(self.n_docs, dtype=np.float32)
        if not self.n_docs:
            return result
        for token in set(query_tokens):
            position = self.term_ids.get(token)
            if position is None:
                continue
            start, end = int(self.offsets[position]), int(self.offsets[position + 1])
            indices = self.postings_index[start:end]
            frequencies = self.postings_freq[start:end]
            denominator = frequencies + self.k1 * (
                1 - self.b + self.b * self.doc_len[indices] / max(self.avgdl, 1e-9))
            np.add.at(result, indices,
                      self.idf[position] * frequencies * (self.k1 + 1) / denominator)
        return result

    def top_k(self, query_tokens, k):
        scores = self.scores(query_tokens)
        k = min(k, self.n_docs)
        if k <= 0:
            return [], np.zeros(0, dtype=np.float32)
        picked = np.argpartition(-scores, k - 1)[:k]
        picked = picked[np.argsort(-scores[picked], kind='stable')]
        picked = picked[scores[picked] > 0]
        return picked.tolist(), scores[picked]

    def save(self, path):
        np.savez(path, postings_index=self.postings_index, postings_freq=self.postings_freq,
                 offsets=self.offsets, idf=self.idf, doc_len=self.doc_len,
                 terms=np.array(self.terms, dtype=object), params=np.array([self.k1, self.b]))

    @classmethod
    def load(cls, path):
        data = np.load(path, allow_pickle=True)
        k1, b = data['params'].tolist()
        return cls(list(data['terms']), data['postings_index'], data['postings_freq'],
                   data['offsets'], data['idf'], data['doc_len'], k1, b)
