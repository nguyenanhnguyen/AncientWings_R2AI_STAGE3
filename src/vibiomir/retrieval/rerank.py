"""C3: rerank the fused candidates with a cross-encoder.

Fusion decides which few hundred chunks are worth a careful look; the reranker reads the query and
one chunk together and is far better at judging relevance than either channel alone. Only open
rerankers published before 2026-08-01 and at or under 15B are listed.

    bge-reranker-v2-m3      BAAI/bge-reranker-v2-m3, 568M, 2024-06. Multilingual, scores a pair
                            directly from a classification head. Default.
    bge-reranker-base       BAAI/bge-reranker-base, 278M, 2023-09. Cheaper, weaker on Chinese.
    qwen3-reranker-0.6b     Qwen/Qwen3-Reranker-0.6B, 0.6B, 2025-06. Scores by comparing the
                            yes/no token logits of a causal model, so it needs its own prompt.
    qwen3-reranker-4b       Qwen/Qwen3-Reranker-4B, 4B, 2025-06. The local 4 GB
                            profile uses NF4 and a pilot before full reranking.
    identity                No model: keeps the fused order. For offline runs and tests.

Scores are in [0, 1] but are NOT calibrated relevance probabilities and are not comparable
across model families without validation. Submission thresholds remain tunable heuristics.
"""
import numpy as np

INSTRUCTION = ('Given a Vietnamese medical question, judge whether the document passage '
               'contains information that answers it.')

RERANKERS = {
    'bge-reranker-v2-m3': {'hf_id': 'BAAI/bge-reranker-v2-m3', 'kind': 'sequence-classification',
                           'max_length': 1024},
    'bge-reranker-base': {'hf_id': 'BAAI/bge-reranker-base', 'kind': 'sequence-classification',
                          'max_length': 512},
    'qwen3-reranker-0.6b': {'hf_id': 'Qwen/Qwen3-Reranker-0.6B', 'kind': 'causal-yes-no',
                            'max_length': 1024},
    'qwen3-reranker-4b': {'hf_id': 'Qwen/Qwen3-Reranker-4B', 'kind': 'causal-yes-no',
                          'max_length': 1024},
    'identity': {'hf_id': None, 'kind': 'identity', 'max_length': 0},
}


class IdentityReranker:
    """Keeps the incoming order and reports descending placeholder scores."""

    name = 'identity'

    def score(self, query, passages, batch_size=None):
        return np.linspace(1.0, 0.0, num=len(passages), dtype=np.float32)


class CrossEncoderReranker:
    def __init__(self, name, device=None, fp16=True, max_length=None, revision=None,
                 quantize='none'):
        if name not in RERANKERS:
            raise ValueError(f'Unknown reranker {name!r}; choose from {sorted(RERANKERS)}')
        import torch
        from transformers import AutoTokenizer

        self.name = name
        self.config = dict(RERANKERS[name])
        if max_length is not None:
            if max_length < 128:
                raise ValueError('Reranker max_length must be at least 128')
            self.config['max_length'] = max_length
        self.torch = torch
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        if quantize not in ('none', '4bit') or (quantize == '4bit' and not str(self.device).startswith('cuda')):
            raise ValueError('4-bit reranking requires CUDA; quantize must be none or 4bit')
        self.config['quantize'] = quantize
        dtype = torch.float16 if (fp16 and str(self.device).startswith('cuda')) else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.config['hf_id'], revision=revision)
        kwargs = dict(torch_dtype=dtype, revision=revision, attn_implementation='sdpa')
        if quantize == '4bit':
            from transformers import BitsAndBytesConfig
            kwargs.update(quantization_config=BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16),
                device_map={'': self.device})
        if self.config['kind'] == 'causal-yes-no':
            from transformers import AutoModelForCausalLM

            self.tokenizer.padding_side = 'left'
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config['hf_id'], **kwargs)
            self.yes_id = self.tokenizer.convert_tokens_to_ids('yes')
            self.no_id = self.tokenizer.convert_tokens_to_ids('no')
            self.prefix = ('<|im_start|>system\nJudge whether the Document meets the requirements '
                           'based on the Query and the Instruct provided. Note that the answer '
                           'can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
            self.suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
            self.prefix_ids = self.tokenizer.encode(self.prefix, add_special_tokens=False)
            self.suffix_ids = self.tokenizer.encode(self.suffix, add_special_tokens=False)
        else:
            from transformers import AutoModelForSequenceClassification

            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.config['hf_id'], **kwargs)
        if quantize == 'none':
            self.model.to(self.device)
        self.model.eval()
        if hasattr(self.model.config, 'use_cache'):
            self.model.config.use_cache = False

    def _inputs(self, query, batch):
        if self.config['kind'] == 'causal-yes-no':
            prompts = [f'<Instruct>: {INSTRUCTION}\n<Query>: {query}\n'
                       f'<Document>: {passage}' for passage in batch]
            inputs = self.tokenizer(prompts, padding=False, truncation=True,
                                    add_special_tokens=False, return_attention_mask=False,
                                    max_length=self.config['max_length'] - len(self.prefix_ids)
                                    - len(self.suffix_ids))
            inputs['input_ids'] = [self.prefix_ids + ids + self.suffix_ids
                                   for ids in inputs['input_ids']]
            return self.tokenizer.pad(inputs, padding=True, return_tensors='pt')
        return self.tokenizer([[query, passage] for passage in batch], padding=True,
                              truncation=True, return_tensors='pt',
                              max_length=self.config['max_length'])

    def _logits(self, inputs):
        if self.config['kind'] == 'causal-yes-no':
            # Avoid allocating [batch, sequence, vocabulary] logits on the 4 GB card.
            output = self.model(**inputs, use_cache=False, logits_to_keep=1)
            # Last position of a left-padded batch holds the answer token distribution.
            last = output.logits[:, -1, :]
            pair = self.torch.stack([last[:, self.no_id], last[:, self.yes_id]], dim=1)
            return self.torch.softmax(pair.float(), dim=1)[:, 1]
        # A sigmoid turns the raw logit into a 0-1 relevance probability. Block D thresholds by
        # the ratio to a query's best score, which is meaningless on raw logits that go negative.
        return self.torch.sigmoid(self.model(**inputs).logits.view(-1).float())

    def score(self, query, passages, batch_size=16):
        if not passages:
            return np.zeros(0, dtype=np.float32)
        result = np.zeros(len(passages), dtype=np.float32)
        size = min(max(1, batch_size), getattr(self, 'safe_batch', batch_size))
        order = sorted(range(len(passages)), key=lambda i: len(passages[i]))
        position = 0
        while position < len(passages):
            indices = order[position:position + size]
            batch = [passages[i] for i in indices]
            inputs = None
            oom = False
            try:
                with self.torch.inference_mode():
                    inputs = self._inputs(query, batch).to(self.device)
                    scores = self._logits(inputs).float().cpu().numpy()
                if not np.isfinite(scores).all():
                    raise ValueError('Non-finite reranker scores; retry --fp32.')
                result[indices] = scores
            except RuntimeError as error:
                if 'out of memory' not in str(error).lower() or size == 1:
                    raise
                inputs = None
                size = max(1, size // 2)
                self.safe_batch = size
                oom = True
            else:
                position += len(batch)
            inputs = None
            if oom:
                self.torch.cuda.empty_cache()
        return result


def load_reranker(name, device=None, fp16=True, max_length=None, revision=None,
                  quantize='none'):
    if name == 'identity':
        return IdentityReranker()
    return CrossEncoderReranker(name, device=device, fp16=fp16,
                               max_length=max_length, revision=revision,
                               quantize=quantize)


def rerank(query, candidates, reranker, text_of, batch_size=16, limit=None):
    """Score candidates and return them sorted best first, each with its `ce_score`.

    `candidates` are (row, fused score, channels) triples; `text_of(row)` gives the passage.
    """
    subset = candidates[:limit] if limit else candidates
    scores = reranker.score(query, [text_of(row) for row, _score, _channels in subset],
                            batch_size=batch_size)
    order = np.argsort(-scores, kind='stable')
    ranked = [(*subset[position], float(scores[position])) for position in order]
    tail = [(*item, None) for item in candidates[len(subset):]]
    return ranked + tail


def adaptive_cutoff(scores, min_k=1, max_k=20, window=15):
    """Cut where the reranker's sorted scores drop the most, instead of always at a fixed k.

    Follows the adaptive-k idea of Taguchi et al., 2025 (arXiv:2506.08479): the largest gap in the
    descending score list is a better boundary than one constant for every query.
    """
    scores = [score for score in scores if score is not None]
    if not scores:
        return min_k
    span = min(len(scores), window)
    if span <= 1:
        return min_k
    gaps = [scores[position] - scores[position + 1] for position in range(span - 1)]
    return max(min_k, min(int(np.argmax(gaps)) + 1, max_k))
