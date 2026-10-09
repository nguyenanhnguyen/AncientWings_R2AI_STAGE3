"""T2 and T4: the 32B teacher writes queries and judges (query, passage) pairs.

Both stages run on Kaggle T4x2 and are sharded by account: `--shard k --shards n` processes only
the seeds or groups hashed to shard k, so several accounts work on disjoint parts at once. Each
finished batch is appended to a shard log and mirrored to a private Hugging Face dataset.

The judge uses the Qwen3-Reranker prompt and reads P(yes) from the next-token distribution, the
same quantity the reranker student is trained to produce, so teacher and student scores line up.
T4 has no bfloat16, so the teacher runs in float16.
"""
import argparse
import json
import math
import os
from pathlib import Path

from ..common import storage
from ..common.console import emit
from ..common.runtime import Progress
from .models import TEACHERS, generate_messages, judge_messages, parse_generation
from .store import Deadline, open_log


class VllmTeacher:
    def __init__(self, config, max_model_len, gpu_memory=0.92):
        import torch
        from vllm import LLM

        self.llm = LLM(model=config['hf_id'], quantization=config.get('quantization'),
                       dtype='half', tensor_parallel_size=max(1, torch.cuda.device_count()),
                       max_model_len=max_model_len, gpu_memory_utilization=gpu_memory,
                       enable_prefix_caching=True, seed=0)
        self.tokenizer = self.llm.get_tokenizer()
        self.max_model_len = max_model_len

    def generate(self, prompts, max_tokens, temperature):
        from vllm import SamplingParams

        params = SamplingParams(max_tokens=max_tokens, temperature=temperature, top_p=0.8,
                                top_k=20, seed=0)
        return [output.outputs[0].text for output in self.llm.generate(prompts, params,
                                                                        use_tqdm=False)]

    def yes_prob(self, prompts, yes_id, no_id):
        from vllm import SamplingParams

        params = SamplingParams(max_tokens=1, temperature=0.0, logprobs=20)
        result = []
        for output in self.llm.generate(prompts, params, use_tqdm=False):
            top = output.outputs[0].logprobs[0]
            floor = min(item.logprob for item in top.values()) - 1.0
            yes = top[yes_id].logprob if yes_id in top else floor
            no = top[no_id].logprob if no_id in top else floor
            result.append(1.0 / (1.0 + math.exp(no - yes)))
        return result


class HfTeacher:
    """bitsandbytes 4-bit over every visible GPU. Use only when vLLM cannot start."""

    def __init__(self, config, max_model_len, batch=2, reserve_gib=3.0):
        # Must be set before the first CUDA allocation; reduces fragmentation OOMs.
        os.environ.setdefault('PYTORCH_CUDA_ALLOC_CONF', 'expandable_segments:True')
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        self.torch, self.batch, self.max_model_len = torch, batch, max_model_len
        self.tokenizer = AutoTokenizer.from_pretrained(config['hf_id'])
        self.tokenizer.padding_side = 'left'
        # device_map='auto' alone fills a card to the brim with weights and leaves nothing for
        # activations or for bitsandbytes' dequantise fallback on T4, so cap each GPU.
        max_memory = {i: f'{torch.cuda.get_device_properties(i).total_memory / 2**30 - reserve_gib:.1f}GiB'
                      for i in range(torch.cuda.device_count())}
        self.model = AutoModelForCausalLM.from_pretrained(
            config['hf_id'], device_map='auto', max_memory=max_memory, torch_dtype=torch.float16,
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                                                   bnb_4bit_use_double_quant=True,
                                                   bnb_4bit_compute_dtype=torch.float16)).eval()

    def _batches(self, prompts):
        for start in range(0, len(prompts), self.batch):
            part = prompts[start:start + self.batch]
            yield self.tokenizer(part, return_tensors='pt', padding=True,
                                 add_special_tokens=False).to(self.model.device)

    def generate(self, prompts, max_tokens, temperature):
        texts = []
        for inputs in self._batches(prompts):
            with self.torch.inference_mode():
                output = self.model.generate(**inputs, max_new_tokens=max_tokens,
                                             do_sample=temperature > 0, temperature=temperature,
                                             top_p=0.8, top_k=20,
                                             pad_token_id=self.tokenizer.eos_token_id)
            new = output[:, inputs['input_ids'].shape[1]:]
            texts.extend(self.tokenizer.batch_decode(new, skip_special_tokens=True))
        return texts

    def yes_prob(self, prompts, yes_id, no_id):
        result = []
        for inputs in self._batches(prompts):
            with self.torch.inference_mode():
                last = self.model(**inputs, logits_to_keep=1).logits[:, -1, :].float()
            pair = self.torch.stack([last[:, no_id], last[:, yes_id]], dim=1)
            result.extend(self.torch.softmax(pair, dim=1)[:, 1].cpu().tolist())
        return result


def load_teacher(name, max_model_len, backend=None):
    config = TEACHERS[name]
    if (backend or config['backend']) == 'vllm':
        return VllmTeacher(config, max_model_len)
    if config.get('quantization') == 'awq':
        raise ValueError('The hf backend loads full weights in 4-bit; pick --teacher qwen3-32b.')
    return HfTeacher(config, max_model_len)


def _save_every(teacher, requested, hf_cap):
    """The hf backend is far slower than vLLM; save after fewer items so a session that dies
    early still leaves progress on the Hub."""
    return min(requested, hf_cap) if isinstance(teacher, HfTeacher) else requested


def _prompt(tokenizer, messages):
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=False)
    except TypeError:  # templates without the thinking switch (Qwen2.5)
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def _fits(tokenizer, prompt, room, limit):
    return len(tokenizer(prompt, add_special_tokens=False)['input_ids']) + room <= limit


def run_generate(args):
    seeds = [row for row in storage.iter_jsonl(args.seeds) if row['shard'] == args.shard]
    log = open_log(args.out, 'generated', args.shard, args.shards, 'chunk_id', args.hub_repo,
                   args.sync_minutes)
    todo = [row for row in seeds if row['chunk_id'] not in log.done]
    emit(f'shard {args.shard}: {len(seeds)} seed, đã xong {len(seeds) - len(todo)}, '
         f'còn {len(todo)}')
    if not todo:
        return log.close()
    teacher = load_teacher(args.teacher, args.max_model_len, args.backend)
    step = _save_every(teacher, args.batch, 16)
    deadline, progress = Deadline(args.hours), Progress('generate')
    accepted = done = 0
    for start in range(0, len(todo), step):
        part = todo[start:start + step]
        prompts = [_prompt(teacher.tokenizer, generate_messages(row['passage'], row['style']))
                   for row in part]
        fits = [_fits(teacher.tokenizer, p, args.max_tokens, args.max_model_len) for p in prompts]
        outputs = iter(teacher.generate([p for p, ok in zip(prompts, fits) if ok],
                                        args.max_tokens, args.temperature))
        rows = []
        for row, ok in zip(part, fits):
            raw = next(outputs) if ok else ''
            record, reason = parse_generation(raw, row['passage']) if ok else (None, 'too_long')
            rows.append({'chunk_id': row['chunk_id'], 'doc_id': row['doc_id'],
                         'split': row['split'], 'teacher': args.teacher,
                         'error': reason, **(record or {}),
                         **({'raw': raw[:2000]} if reason not in (None, 'not_usable') else {})})
            accepted += reason is None
        log.append(rows)
        done += len(part)
        progress(done, len(todo))
        if deadline.passed():
            emit('Hết thời gian của session; dừng sau batch đã lưu.')
            break
    log.close()
    emit(json.dumps({'shard': args.shard, 'processed': done, 'accepted': accepted}))


def run_judge(args):
    groups = [row for row in storage.iter_jsonl(args.groups) if row['shard'] == args.shard]
    log = open_log(args.out, 'judged', args.shard, args.shards, 'qid', args.hub_repo,
                   args.sync_minutes)
    todo = [row for row in groups if row['qid'] not in log.done]
    emit(f'shard {args.shard}: {len(groups)} nhóm, còn {len(todo)}')
    if not todo:
        return log.close()
    needed = {cid for row in todo for cid in [row['positive'], *row['negatives']]}
    texts = {}
    for chunk in storage.read_parquet(args.chunks, columns=['chunk_id', 'title', 'text']):
        if chunk['chunk_id'] in needed:
            texts[chunk['chunk_id']] = (f"{chunk['title']}\n{chunk['text']}"
                                        if chunk.get('title') else chunk['text'])
    missing = needed - texts.keys()
    if missing:
        raise ValueError(f'{len(missing)} chunk của nhóm không có trong {args.chunks}; '
                         'dùng đúng file chunks đã dùng ở bước mine.')
    teacher = load_teacher(args.teacher, args.max_model_len, args.backend)
    tokenizer = teacher.tokenizer
    yes_id, no_id = tokenizer.convert_tokens_to_ids('yes'), tokenizer.convert_tokens_to_ids('no')
    step = _save_every(teacher, args.batch, 4)
    deadline, progress = Deadline(args.hours), Progress('judge')
    done = 0
    for start in range(0, len(todo), step):
        part = todo[start:start + step]
        pairs = [(row['qid'], cid) for row in part for cid in [row['positive'], *row['negatives']]]
        queries = {row['qid']: row['query'] for row in part}
        prompts = []
        for qid, cid in pairs:
            query, passage = queries[qid], texts[cid]
            prompt = _prompt(tokenizer, judge_messages(query, passage))
            while not _fits(tokenizer, prompt, 1, args.max_model_len) and len(passage) > 200:
                passage = passage[:int(len(passage) * 0.8)]
                prompt = _prompt(tokenizer, judge_messages(query, passage))
            prompts.append(prompt)
        scores = teacher.yes_prob(prompts, yes_id, no_id)
        by_query = {}
        for (qid, cid), score in zip(pairs, scores):
            by_query.setdefault(qid, {})[cid] = round(float(score), 5)
        log.append([{'qid': qid, 'teacher': args.teacher, 'scores': value}
                    for qid, value in by_query.items()])
        done += len(part)
        progress(done, len(todo))
        if deadline.passed():
            emit('Hết thời gian của session; dừng sau batch đã lưu.')
            break
    log.close()


def add_common(parser):
    parser.add_argument('--out', default='work/teach')
    parser.add_argument('--shard', type=int, required=True)
    parser.add_argument('--shards', type=int, required=True)
    parser.add_argument('--teacher', choices=sorted(TEACHERS), default='qwen3-32b-awq')
    parser.add_argument('--backend', choices=['vllm', 'hf'], default=None)
    parser.add_argument('--hub-repo', default=None,
                        help='Private HF dataset, e.g. <user>/vibiomir-teach. Strongly advised.')
    parser.add_argument('--sync-minutes', type=int, default=10)
    parser.add_argument('--hours', type=float, default=11.0,
                        help='Stop before the 12h Kaggle limit; 0 disables.')


def add_generate_arguments(parser):
    add_common(parser)
    parser.add_argument('--seeds', required=True)
    parser.add_argument('--batch', type=int, default=256)
    parser.add_argument('--max-model-len', type=int, default=3072)
    parser.add_argument('--max-tokens', type=int, default=512)
    parser.add_argument('--temperature', type=float, default=0.7)


def add_judge_arguments(parser):
    add_common(parser)
    parser.add_argument('--groups', required=True)
    parser.add_argument('--chunks', required=True)
    parser.add_argument('--batch', type=int, default=64, help='Groups per call.')
    parser.add_argument('--max-model-len', type=int, default=1536)


def main_generate(argv=None):
    parser = argparse.ArgumentParser(description='T2: teacher writes queries.')
    add_generate_arguments(parser)
    run_generate(parser.parse_args(argv))


def main_judge(argv=None):
    parser = argparse.ArgumentParser(description='T4: teacher judges pairs.')
    add_judge_arguments(parser)
    run_judge(parser.parse_args(argv))


if __name__ == '__main__':
    main_generate()
