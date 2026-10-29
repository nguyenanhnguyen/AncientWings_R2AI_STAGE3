"""Chấm lại các cặp (câu hỏi, đoạn) bằng Qwen3-Reranker trên MỘT GPU (bước A2, chạy trên Kaggle).

Đọc một file parquet các cặp (qid, query, doc_id, run, chunk_order, text), ghi từng dòng JSON
{"key": ..., "score": ...} vào --out và flush sau mỗi batch, nên dừng giữa chừng không mất gì; chạy
lại với cùng --out thì bỏ qua các cặp đã chấm. Prompt và cách tính điểm giống hệt reranker Qwen3 của
pipeline (src/vibiomir/retrieval/rerank.py): xác suất "yes" so với "no" ở token cuối.
"""
import argparse
import json
import math
import os
import re
import sys
import time

import pyarrow.parquet as pq

INSTRUCTION = ('Given a Vietnamese medical question, judge whether the document passage '
               'contains information that answers it.')
PREFIX = ('<|im_start|>system\nJudge whether the Document meets the requirements based on the Query '
          'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
          '<|im_start|>user\n')
SUFFIX = '<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n'


def pair_key(qid, doc_id, run, order):
    return f'{int(qid)}:{int(doc_id)}:{run}:{int(order)}'


def done_keys(path):
    keys = set()
    if os.path.exists(path):
        with open(path, encoding='utf-8') as stream:
            for line in stream:
                try:
                    keys.add(json.loads(line)['key'])
                except (ValueError, KeyError):
                    pass  # A line cut by a crash; that pair is simply scored again.
    return keys


class DummyScorer:
    """Word overlap, for testing the plumbing without a GPU or a model download."""

    def score(self, queries, passages):
        out = []
        for query, passage in zip(queries, passages):
            q = set(re.findall(r'\w+', query.lower()))
            p = set(re.findall(r'\w+', passage.lower()))
            out.append(len(q & p) / max(1, len(q)))
        return out


class QwenScorer:
    def __init__(self, model_id, max_length):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_id, padding_side='left')
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=torch.float16, attn_implementation='sdpa').to('cuda').eval()
        self.yes_id = self.tokenizer.convert_tokens_to_ids('yes')
        self.no_id = self.tokenizer.convert_tokens_to_ids('no')
        self.prefix_ids = self.tokenizer.encode(PREFIX, add_special_tokens=False)
        self.suffix_ids = self.tokenizer.encode(SUFFIX, add_special_tokens=False)
        self.budget = max_length - len(self.prefix_ids) - len(self.suffix_ids)

    def score(self, queries, passages):
        prompts = [f'<Instruct>: {INSTRUCTION}\n<Query>: {q}\n<Document>: {p}'
                   for q, p in zip(queries, passages)]
        encoded = self.tokenizer(prompts, padding=False, truncation=True, add_special_tokens=False,
                                 return_attention_mask=False, max_length=self.budget)
        encoded['input_ids'] = [self.prefix_ids + ids + self.suffix_ids for ids in encoded['input_ids']]
        inputs = self.tokenizer.pad(encoded, padding=True, return_tensors='pt').to('cuda')
        with self.torch.inference_mode():
            last = self.model(**inputs, use_cache=False, logits_to_keep=1).logits[:, -1, :]
            pair = self.torch.stack([last[:, self.no_id], last[:, self.yes_id]], dim=1).float()
            return self.torch.softmax(pair, dim=1)[:, 1].cpu().tolist()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pairs', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--model', default='Qwen/Qwen3-Reranker-4B')
    parser.add_argument('--max-length', type=int, default=768)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--deadline', type=float, default=0, help='Unix time to stop at; 0 = none.')
    parser.add_argument('--tag', default='')
    parser.add_argument('--dummy', action='store_true')
    args = parser.parse_args()

    table = pq.read_table(args.pairs, columns=['qid', 'query', 'doc_id', 'run', 'chunk_order', 'text'])
    rows = list(zip(*(table[name].to_pylist() for name in table.column_names)))
    done = done_keys(args.out)
    todo = [row for row in rows if pair_key(row[0], row[2], row[3], row[4]) not in done]
    # Longest first: an out-of-memory batch shows up at the start and the batch size settles there.
    todo.sort(key=lambda row: -(len(row[1]) + len(row[5])))
    print(f'{args.tag} cặp: {len(rows)}, đã chấm: {len(rows) - len(todo)}, còn: {len(todo)}', flush=True)
    if not todo:
        return
    scorer = DummyScorer() if args.dummy else QwenScorer(args.model, args.max_length)
    size, position, written, bad = args.batch_size, 0, 0, 0
    started = last_report = time.time()
    with open(args.out, 'a', encoding='utf-8') as out:
        while position < len(todo):
            if args.deadline and time.time() > args.deadline:
                print(f'{args.tag} hết giờ, dừng ở {position}/{len(todo)}; chạy lại để làm tiếp.', flush=True)
                break
            batch = todo[position:position + size]
            try:
                scores = scorer.score([r[1] for r in batch], [r[5] for r in batch])
            except RuntimeError as error:
                if 'out of memory' not in str(error).lower() or size == 1:
                    raise
                size = max(1, size // 2)
                scorer.torch.cuda.empty_cache()
                print(f'{args.tag} hết VRAM, giảm batch còn {size}', flush=True)
                continue
            for row, score in zip(batch, scores):
                if score is None or not math.isfinite(score):
                    bad += 1
                    score = None
                out.write(json.dumps({'key': pair_key(row[0], row[2], row[3], row[4]), 'score': score}) + '\n')
            out.flush()
            position += len(batch)
            written += len(batch)
            if written >= 200 and bad > written // 2:
                raise RuntimeError(f'{bad}/{written} điểm không hợp lệ (NaN/inf) với fp16. '
                                   'Mô hình này không chạy được fp16 trên GPU hiện tại; đổi MODEL_ID.')
            now = time.time()
            if now - last_report > 60 or position >= len(todo):
                rate = written / max(1e-9, now - started)
                eta = (len(todo) - position) / max(rate, 1e-9) / 60
                print(f'{args.tag} {position}/{len(todo)} cặp, {rate:.1f} cặp/s, còn ~{eta:.0f} phút, '
                      f'batch {size}, điểm lỗi {bad}', flush=True)
                last_report = now
    print(f'{args.tag} xong {written} cặp trong {(time.time() - started) / 60:.1f} phút, điểm lỗi {bad}', flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
