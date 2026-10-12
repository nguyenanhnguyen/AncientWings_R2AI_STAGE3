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
import json
import os
import zlib

import numpy as np

from .bm25 import tokenize
from ..common import storage
from ..common.runtime import model_info
from ..teach.models import discover_students, load_backbone

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
    'qwen3-embedding-8b': {'hf_id': 'Qwen/Qwen3-Embedding-8B', 'pooling': 'last',
                           'max_length': 1024, 'doc_prefix': '', 'dim': 4096, 'quantize': '4bit',
                           'query_prefix': 'Instruct: Given a Vietnamese medical question, '
                                           'retrieve passages that answer it\nQuery: '},
    'hash': {'hf_id': None, 'pooling': 'hash', 'max_length': 0,
             'query_prefix': '', 'doc_prefix': '', 'dim': 256},
}
# Trained students (teach/train) appear as 'student:<folder>' under $VIBIOMIR_STUDENTS.
ENCODERS.update(discover_students('embedding'))


class HashEncoder:
    """Offline stand-in: hashes tokens into a fixed vector. For plumbing tests only."""

    name = 'hash'

    def __init__(self, dim=256):
        self.dim = dim

    def encode(self, texts, kind='doc', batch_size=None, progress=None):
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                # crc32, not hash(): Python salts hash() per process, so an index built by one
                # command and queried by another would put the same token in different slots.
                slot = zlib.crc32(token.encode('utf-8')) % self.dim
                result[row, slot] += 1.0
        norms = np.linalg.norm(result, axis=1, keepdims=True)
        return result / np.maximum(norms, 1e-9)


class TransformerEncoder:
    """Hugging Face encoder with the pooling and prefixes each model family expects."""

    def __init__(self, name, device=None, fp16=True, max_length=None, revision=None):
        if name not in ENCODERS:
            raise ValueError(f'Unknown encoder {name!r}; choose from {sorted(ENCODERS)}')
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.name = name
        self.config = dict(ENCODERS[name])
        if max_length is not None:
            if max_length < 32:
                raise ValueError('max_length must be at least 32')
            self.config['max_length'] = max_length
        self.torch = torch
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        kwargs = {'revision': revision}
        if self.config.get('trust_remote_code'):
            kwargs['trust_remote_code'] = True
        else:
            kwargs['attn_implementation'] = 'sdpa'
        self.tokenizer = AutoTokenizer.from_pretrained(
            self.config['hf_id'], **{k: v for k, v in kwargs.items() if k != 'attn_implementation'})
        if self.config['pooling'] == 'last':
            # Last-token pooling needs the real final token at a known position.
            self.tokenizer.padding_side = 'left'
        # torch_dtype is accepted by every transformers release this project allows; the newer
        # `dtype` name is silently ignored by older ones, which would load fp32 at twice the VRAM.
        dtype = torch.float16 if (fp16 and str(self.device).startswith('cuda')) else torch.float32
        self.model = load_backbone(AutoModel, self.config, self.device, dtype, **kwargs)
        if hasattr(self.model.config, 'use_cache'):
            self.model.config.use_cache = False
        self.dim = int(getattr(self.model.config, 'hidden_size', self.config['dim']))

    def _pool(self, output, mask):
        states = output.last_hidden_state
        how = self.config['pooling']
        if how == 'cls':
            return states[:, 0]
        if how == 'last':
            # The tokenizer pads on the left for this pooling, so the last real token of every
            # row sits at the final position. Indexing by mask.sum()-1 would land in the padding.
            return states[:, -1]
        weights = mask.unsqueeze(-1).to(states.dtype)
        return (states * weights).sum(dim=1) / weights.sum(dim=1).clamp(min=1e-9)

    def encode(self, texts, kind='doc', batch_size=16, progress=None):
        prefix = self.config['query_prefix'] if kind == 'query' else self.config['doc_prefix']
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        size = min(max(1, batch_size), getattr(self, 'safe_batch', batch_size))
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        position = 0
        while position < len(texts):
            indices = order[position:position + size]
            batch = [prefix + texts[i] for i in indices]
            inputs = pooled = None
            oom = False
            try:
                with self.torch.inference_mode():
                    inputs = self.tokenizer(batch, padding=True, truncation=True,
                                            max_length=self.config['max_length'],
                                            return_tensors='pt').to(self.device)
                    pooled = self._pool(self.model(**inputs), inputs['attention_mask'])
                    pooled = self.torch.nn.functional.normalize(pooled.float(), p=2, dim=1)
                result[indices] = pooled.cpu().numpy()
                if not np.isfinite(result[indices]).all():
                    raise ValueError('Non-finite embeddings; retry with --fp32 or inspect the model.')
            except RuntimeError as error:
                if 'out of memory' not in str(error).lower() or size == 1:
                    raise
                # Release tensors and the traceback outside the except block before retrying.
                inputs = pooled = None
                size = max(1, size // 2)
                self.safe_batch = size
                oom = True
            else:
                position += len(batch)
            inputs = pooled = None
            if oom:
                self.torch.cuda.empty_cache()
            if progress:
                progress(position, len(texts))
        return result


def load_encoder(name, device=None, fp16=True, max_length=None, revision=None):
    if name == 'hash':
        return HashEncoder(ENCODERS['hash']['dim'])
    return TransformerEncoder(name, device=device, fp16=fp16, max_length=max_length, revision=revision)


def encode_to_memmap(encoder, texts, path, batch_size=16, shard=20000, progress=None,
                     resume=False, fingerprint=None):
    """Flush each shard before its atomic checkpoint; publish only a complete matrix."""
    if shard < 1 or batch_size < 1:
        raise ValueError('shard and batch_size must be positive')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix('.partial.npy')
    checkpoint = path.with_suffix('.checkpoint.json')
    key = {'input': fingerprint or storage.sha256_text(json.dumps(texts, ensure_ascii=False)),
           'model': model_info(encoder), 'shape': [len(texts), encoder.dim], 'version': 2}
    start_row = 0
    if resume and checkpoint.exists():
        state = storage.read_json(checkpoint)
        if state['key'] != key:
            raise ValueError('Embedding checkpoint differs; use a new --out directory.')
        start_row = state['done']
        if start_row == len(texts) and path.exists() and not partial.exists():
            if state.get('sha256') != storage.sha256_file(path):
                raise ValueError('Completed embedding file failed checksum validation.')
            return path
        if not partial.exists():
            raise ValueError('Missing partial embeddings; use a new --out directory.')
    store = np.lib.format.open_memmap(partial, mode='r+' if start_row else 'w+',
                                      dtype=np.float16, shape=(len(texts), encoder.dim))
    try:
        for start in range(start_row, len(texts), shard):
            part = texts[start:start + shard]
            store[start:start + len(part)] = encoder.encode(
                part, kind='doc', batch_size=batch_size).astype(np.float16)
            store.flush()
            storage.write_json(checkpoint, {'key': key, 'done': start + len(part)})
            if progress:
                progress(min(start + shard, len(texts)), len(texts))
        store.flush()
    finally:
        del store
    os.replace(partial, path)
    storage.write_json(checkpoint, {'key': key, 'done': len(texts),
                                    'sha256': storage.sha256_file(path)})
    return path


def search(embeddings_path, queries, k, block=16384, query_block=128, device='cpu'):
    """Top-k by inner product. Normalised vectors make this cosine similarity.

    Reads the matrix in blocks and keeps a running top-k, so a corpus larger than RAM still works.
    """
    store = np.load(embeddings_path, mmap_mode='r')
    queries = np.asarray(queries, dtype=np.float32)
    if block < 1 or query_block < 1 or k < 1:
        raise ValueError('Search block sizes and k must be positive')
    if queries.ndim != 2 or queries.shape[1] != store.shape[1]:
        raise ValueError('Query and index dimensions differ')
    use_cuda = str(device).startswith('cuda')
    if use_cuda:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError('CUDA requested but unavailable; install a CUDA PyTorch wheel.')
    total = store.shape[0]
    k = min(k, total)
    if k <= 0:
        return np.zeros((len(queries), 0), dtype=np.int64), np.zeros((len(queries), 0), np.float32)
    best_scores = np.full((len(queries), k), -np.inf, dtype=np.float32)
    best_index = np.zeros((len(queries), k), dtype=np.int64)
    for start in range(0, total, block):
        part = np.asarray(store[start:start + block], dtype=np.float32)
        gpu_part = torch.as_tensor(part, device=device, dtype=torch.float16) if use_cuda else None
        for qstart in range(0, len(queries), query_block):
            sl = slice(qstart, qstart + query_block)
            width = min(k, len(part))
            if use_cuda:
                with torch.inference_mode():
                    q = torch.as_tensor(queries[sl], device=device, dtype=torch.float16)
                    scores = q @ gpu_part.T
                    values, indices = scores.topk(width, dim=1)
                    local, local_scores = indices.cpu().numpy(), values.float().cpu().numpy()
                    del q, scores, values, indices
            else:
                scores = queries[sl] @ part.T
                local = np.argpartition(-scores, width - 1, axis=1)[:, :width]
                local_scores = np.take_along_axis(scores, local, axis=1)
            merged_scores = np.concatenate([best_scores[sl], local_scores], 1)
            merged_index = np.concatenate([best_index[sl], local.astype(np.int64) + start], 1)
            order = np.argsort(-merged_scores, axis=1, kind='stable')[:, :k]
            best_scores[sl] = np.take_along_axis(merged_scores, order, axis=1)
            best_index[sl] = np.take_along_axis(merged_index, order, axis=1)
        del gpu_part
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
