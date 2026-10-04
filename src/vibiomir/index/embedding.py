"""B3: encode chunks and build the vector index.

Cross-lingual retrieval is the point of this task: queries are Vietnamese, documents are also
Chinese and English, so the dense channel carries the matches BM25 cannot make. The registry below
only lists open multilingual encoders published before 2026-08-01 and at or under 15B parameters,
which is what the rules allow. Sizes are the published parameter counts.

    bge-m3                  BAAI/bge-m3, 568M, 2024-01, 8192 ctx, CLS pooling. Default: strong
                            multilingual retrieval at a size that fits a 4GB laptop GPU.
    multilingual-e5-large   intfloat/multilingual-e5-large, 560M, 2024-02, needs query:/passage:.
    gte-multilingual-base   Alibaba-NLP/gte-multilingual-base, 305M, 2024-07, cheapest option.
    qwen3-embedding-0.6b    Qwen/Qwen3-Embedding-0.6B, 0.6B, 2025-06, last-token pooling.
    qwen3-embedding-4b      Qwen/Qwen3-Embedding-4B, 4B, 2025-06. Top of the MTEB multilingual
                            board in its family; needs a 16GB GPU for comfortable encoding.

`hash` is not a model. It is a deterministic feature-hashing encoder used to run the whole flow
offline, in tests and on a machine with no GPU. It proves the plumbing, never retrieval quality.
"""
from pathlib import Path

import numpy as np

from .bm25 import tokenize

ENCODERS = {
    'bge-m3': {'hf_id': 'BAAI/bge-m3', 'pooling': 'cls', 'max_length': 1024,
               'query_prefix': '', 'doc_prefix': '', 'dim': 1024},
    'multilingual-e5-large': {'hf_id': 'intfloat/multilingual-e5-large', 'pooling': 'mean',
                              'max_length': 512, 'query_prefix': 'query: ',
                              'doc_prefix': 'passage: ', 'dim': 1024},
    'gte-multilingual-base': {'hf_id': 'Alibaba-NLP/gte-multilingual-base', 'pooling': 'cls',
                              'max_length': 1024, 'query_prefix': '', 'doc_prefix': '',
                              'dim': 768, 'trust_remote_code': True},
    'qwen3-embedding-0.6b': {'hf_id': 'Qwen/Qwen3-Embedding-0.6B', 'pooling': 'last',
                             'max_length': 1024, 'doc_prefix': '', 'dim': 1024,
                             'query_prefix': 'Instruct: Given a Vietnamese medical question, '
                                             'retrieve passages that answer it\nQuery: '},
    'qwen3-embedding-4b': {'hf_id': 'Qwen/Qwen3-Embedding-4B', 'pooling': 'last',
                           'max_length': 1024, 'doc_prefix': '', 'dim': 2560,
                           'query_prefix': 'Instruct: Given a Vietnamese medical question, '
                                           'retrieve passages that answer it\nQuery: '},
    'hash': {'hf_id': None, 'pooling': 'hash', 'max_length': 0,
             'query_prefix': '', 'doc_prefix': '', 'dim': 256},
}


class HashEncoder:
    """Offline stand-in: hashes tokens into a fixed vector. For plumbing tests only."""

    name = 'hash'

    def __init__(self, dim=256):
        self.dim = dim

    def encode(self, texts, kind='doc', batch_size=None, progress=None):
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                slot = hash((token, 'vibiomir')) % self.dim
                result[row, slot] += 1.0
        norms = np.linalg.norm(result, axis=1, keepdims=True)
        return result / np.maximum(norms, 1e-9)


class TransformerEncoder:
    """Hugging Face encoder with the pooling and prefixes each model family expects."""

    def __init__(self, name, device=None, fp16=True):
        if name not in ENCODERS:
            raise ValueError(f'Unknown encoder {name!r}; choose from {sorted(ENCODERS)}')
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.name = name
        self.config = ENCODERS[name]
        self.torch = torch
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        kwargs = {'trust_remote_code': True} if self.config.get('trust_remote_code') else {}
        self.tokenizer = AutoTokenizer.from_pretrained(self.config['hf_id'], **kwargs)
        if self.config['pooling'] == 'last':
            # Last-token pooling needs the real final token at a known position.
            self.tokenizer.padding_side = 'left'
        self.model = AutoModel.from_pretrained(
            self.config['hf_id'],
            dtype=torch.float16 if (fp16 and self.device == 'cuda') else torch.float32,
            **kwargs).to(self.device).eval()
        self.dim = int(getattr(self.model.config, 'hidden_size', self.config['dim']))

    def _pool(self, output, mask):
        states = output.last_hidden_state
        how = self.config['pooling']
        if how == 'cls':
            return states[:, 0]
        if how == 'last':
            lengths = mask.sum(dim=1) - 1
            return states[self.torch.arange(states.size(0), device=states.device), lengths]
        weights = mask.unsqueeze(-1).to(states.dtype)
        return (states * weights).sum(dim=1) / weights.sum(dim=1).clamp(min=1e-9)

    def encode(self, texts, kind='doc', batch_size=16, progress=None):
        prefix = self.config['query_prefix'] if kind == 'query' else self.config['doc_prefix']
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        size = max(1, batch_size)
        position = 0
        while position < len(texts):
            batch = [prefix + text for text in texts[position:position + size]]
            try:
                with self.torch.no_grad():
                    inputs = self.tokenizer(batch, padding=True, truncation=True,
                                            max_length=self.config['max_length'],
                                            return_tensors='pt').to(self.device)
                    pooled = self._pool(self.model(**inputs), inputs['attention_mask'])
                    pooled = self.torch.nn.functional.normalize(pooled, p=2, dim=1)
                result[position:position + len(batch)] = pooled.float().cpu().numpy()
            except RuntimeError as error:
                if 'out of memory' not in str(error).lower() or size == 1:
                    raise
                self.torch.cuda.empty_cache()
                size = max(1, size // 2)
                continue
            position += len(batch)
            if progress:
                progress(position, len(texts))
        return result


def load_encoder(name, device=None, fp16=True):
    if name == 'hash':
        return HashEncoder(ENCODERS['hash']['dim'])
    return TransformerEncoder(name, device=device, fp16=fp16)


def encode_to_memmap(encoder, texts, path, batch_size=16, shard=20000, progress=None):
    """Encode in shards straight into a float16 .npy on disk, so RAM holds one shard at a time."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = np.lib.format.open_memmap(path, mode='w+', dtype=np.float16,
                                      shape=(len(texts), encoder.dim))
    try:
        for start in range(0, len(texts), shard):
            part = texts[start:start + shard]
            store[start:start + len(part)] = encoder.encode(
                part, kind='doc', batch_size=batch_size).astype(np.float16)
            if progress:
                progress(min(start + shard, len(texts)), len(texts))
        store.flush()
    finally:
        del store
    return path


def search(embeddings_path, queries, k, block=100000):
    """Top-k by inner product. Normalised vectors make this cosine similarity.

    Reads the matrix in blocks and keeps a running top-k, so a corpus larger than RAM still works.
    """
    store = np.load(embeddings_path, mmap_mode='r')
    queries = np.asarray(queries, dtype=np.float32)
    total = store.shape[0]
    k = min(k, total)
    if k <= 0:
        return np.zeros((len(queries), 0), dtype=np.int64), np.zeros((len(queries), 0), np.float32)
    best_scores = np.full((len(queries), k), -np.inf, dtype=np.float32)
    best_index = np.zeros((len(queries), k), dtype=np.int64)
    for start in range(0, total, block):
        part = np.asarray(store[start:start + block], dtype=np.float32)
        scores = queries @ part.T
        width = min(k, scores.shape[1])
        local = np.argpartition(-scores, width - 1, axis=1)[:, :width]
        merged_scores = np.concatenate([best_scores, np.take_along_axis(scores, local, axis=1)], 1)
        merged_index = np.concatenate([best_index, local.astype(np.int64) + start], 1)
        order = np.argsort(-merged_scores, axis=1, kind='stable')[:, :k]
        best_scores = np.take_along_axis(merged_scores, order, axis=1)
        best_index = np.take_along_axis(merged_index, order, axis=1)
    return best_index, best_scores


def try_faiss(embeddings_path, index_path, n_list=0):
    """Optional accelerator. Returns the written path, or None when faiss is not installed."""
    try:
        import faiss
    except ImportError:
        return None
    store = np.load(embeddings_path, mmap_mode='r')
    vectors = np.asarray(store, dtype=np.float32)
    dim = vectors.shape[1]
    if n_list and len(vectors) > 50 * n_list:
        quantiser = faiss.IndexFlatIP(dim)
        index = faiss.IndexIVFFlat(quantiser, dim, n_list, faiss.METRIC_INNER_PRODUCT)
        index.train(vectors)
    else:
        index = faiss.IndexFlatIP(dim)
    index.add(vectors)
    faiss.write_index(index, str(index_path))
    return index_path


def encoder_report(name, encoder, count):
    return {'encoder': name, 'hf_id': ENCODERS[name]['hf_id'], 'dim': getattr(encoder, 'dim', None),
            'pooling': ENCODERS[name]['pooling'], 'vectors': count,
            'note': 'hash is a test stand-in, not a model' if name == 'hash' else ''}
