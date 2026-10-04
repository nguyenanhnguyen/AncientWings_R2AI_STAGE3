"""C3: rerank the fused candidates with a cross-encoder.

Fusion decides which few hundred chunks are worth a careful look; the reranker reads the query and
one chunk together and is far better at judging relevance than either channel alone. Only open
rerankers published before 2026-08-01 and at or under 15B are listed.

    bge-reranker-v2-m3      BAAI/bge-reranker-v2-m3, 568M, 2024-06. Multilingual, scores a pair
                            directly from a classification head. Default.
    bge-reranker-base       BAAI/bge-reranker-base, 278M, 2023-09. Cheaper, weaker on Chinese.
    qwen3-reranker-0.6b     Qwen/Qwen3-Reranker-0.6B, 0.6B, 2025-06. Scores by comparing the
                            yes/no token logits of a causal model, so it needs its own prompt.
    qwen3-reranker-4b       Qwen/Qwen3-Reranker-4B, 4B, 2025-06. Needs a 16GB GPU.
    identity                No model: keeps the fused order. For offline runs and tests.
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
    def __init__(self, name, device=None, fp16=True):
        if name not in RERANKERS:
            raise ValueError(f'Unknown reranker {name!r}; choose from {sorted(RERANKERS)}')
        import torch
        from transformers import AutoTokenizer

        self.name = name
        self.config = RERANKERS[name]
        self.torch = torch
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        dtype = torch.float16 if (fp16 and self.device == 'cuda') else torch.float32
        self.tokenizer = AutoTokenizer.from_pretrained(self.config['hf_id'])
        if self.config['kind'] == 'causal-yes-no':
            from transformers import AutoModelForCausalLM

            self.tokenizer.padding_side = 'left'
            self.model = AutoModelForCausalLM.from_pretrained(
                self.config['hf_id'], dtype=dtype).to(self.device).eval()
            self.yes_id = self.tokenizer.convert_tokens_to_ids('yes')
            self.no_id = self.tokenizer.convert_tokens_to_ids('no')
            self.prefix = ('<|im_start|>system\nJudge whether the Document meets the requirements '
                           'based on the Query and the Instruct provided. Note that the answer '
                           'can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n')
            self.suffix = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'
        else:
            from transformers import AutoModelForSequenceClassification

            self.model = AutoModelForSequenceClassification.from_pretrained(
                self.config['hf_id'], dtype=dtype).to(self.device).eval()

    def _inputs(self, query, batch):
        if self.config['kind'] == 'causal-yes-no':
            prompts = [f'{self.prefix}<Instruct>: {INSTRUCTION}\n<Query>: {query}\n'
                       f'<Document>: {passage}{self.suffix}' for passage in batch]
            return self.tokenizer(prompts, padding=True, truncation=True, return_tensors='pt',
                                  max_length=self.config['max_length'])
        return self.tokenizer([[query, passage] for passage in batch], padding=True,
                              truncation=True, return_tensors='pt',
                              max_length=self.config['max_length'])

    def _logits(self, inputs):
        output = self.model(**inputs)
        if self.config['kind'] == 'causal-yes-no':
            # Last position of a left-padded batch holds the answer token distribution.
            last = output.logits[:, -1, :]
            pair = self.torch.stack([last[:, self.no_id], last[:, self.yes_id]], dim=1)
            return self.torch.log_softmax(pair.float(), dim=1)[:, 1]
        return output.logits.view(-1)

    def score(self, query, passages, batch_size=16):
        if not passages:
            return np.zeros(0, dtype=np.float32)
        result = np.zeros(len(passages), dtype=np.float32)
        size = max(1, batch_size)
        position = 0
        while position < len(passages):
            batch = passages[position:position + size]
            try:
                with self.torch.no_grad():
                    inputs = self._inputs(query, batch).to(self.device)
                    scores = self._logits(inputs).float().cpu().numpy()
                result[position:position + len(batch)] = scores
            except RuntimeError as error:
                if 'out of memory' not in str(error).lower() or size == 1:
                    raise
                self.torch.cuda.empty_cache()
                size = max(1, size // 2)
                continue
            position += len(batch)
        return result


def load_reranker(name, device=None, fp16=True):
    if name == 'identity':
        return IdentityReranker()
    return CrossEncoderReranker(name, device=device, fp16=fp16)


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
