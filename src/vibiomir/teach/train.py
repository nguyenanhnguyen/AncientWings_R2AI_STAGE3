"""T5: train a 4B, 8B or 14B student for one pipeline role from the teacher's data.

    reranker    Qwen3-Reranker-4B/8B or Qwen3-14B, yes/no head. Listwise distillation of the
                teacher's P(yes) over each group, plus a pointwise term so scores stay calibrated
                enough for Block D's ratio threshold.
    embedding   Qwen3-Embedding-4B/8B or Qwen3-14B, last-token pooling. InfoNCE over the group's
                hard negatives and the other queries in the batch, with the teacher's group
                distribution as a second target. Candidates the teacher calls relevant are masked
                out of the negatives instead of being pushed away.
    translator  Qwen3-4B/8B/14B. Supervised on the teacher's vi->en/zh translations of its own
                queries, with the exact prompt Block C's translate step uses.

Every student is QLoRA (or plain LoRA for 4B) in float16 because the T4 has no bfloat16. Run one
student per GPU (CUDA_VISIBLE_DEVICES=0 / =1) to use both T4s. A checkpoint is written every
`--save-every` steps and when `--hours` runs out; `--resume` continues from it in a new session.
"""
import argparse
import json
import math
from pathlib import Path
import random
import time

from ..common import storage
from ..common.console import emit
from ..common.runtime import environment
from .models import STUDENT_FILE, STUDENT_QUANTIZE, STUDENTS
from .store import Deadline, hf_token, read_stage

EMBED_QUERY_PREFIX = ('Instruct: Given a Vietnamese medical question, retrieve passages that '
                      'answer it\nQuery: ')
LORA_TARGETS = ['q_proj', 'k_proj', 'v_proj', 'o_proj', 'gate_proj', 'up_proj', 'down_proj']


# --- data ---------------------------------------------------------------------------------------

def load_groups(teach, chunks_path, pos_min=0.5, extra_pos=0.8):
    """Groups joined with teacher scores. A query the teacher rejects for its own chunk is dropped:
    the generation was wrong, and training on it would teach noise."""
    judged = {}
    for row in read_stage(teach, 'judged'):
        judged[row['qid']] = row['scores']
    groups, dropped = [], 0
    for group in storage.iter_jsonl(Path(teach) / 'groups.jsonl'):
        scores = judged.get(group['qid'])
        if not scores or scores.get(group['positive'], 0.0) < pos_min:
            dropped += 1
            continue
        items = [{'chunk_id': cid, 'teacher': float(scores[cid]),
                  'label': cid == group['positive'] or scores[cid] >= extra_pos}
                 for cid in [group['positive'], *group['negatives']] if cid in scores]
        groups.append({**group, 'items': items})
    needed = {item['chunk_id'] for group in groups for item in group['items']}
    texts = {}
    for chunk in storage.read_parquet(chunks_path, columns=['chunk_id', 'title', 'text']):
        if chunk['chunk_id'] in needed:
            texts[chunk['chunk_id']] = (f"{chunk['title']}\n{chunk['text']}"
                                        if chunk.get('title') else chunk['text'])
    for group in groups:
        group['items'] = [item for item in group['items'] if item['chunk_id'] in texts]
    return groups, texts, dropped


def pick_items(group, size, rng):
    """The positive, then half the slots for the negatives the teacher finds most confusing and
    half random, so the group has both hard and easy contrasts."""
    positive = group['items'][0]
    rest = group['items'][1:]
    hard = sorted(rest, key=lambda item: -item['teacher'])[:(size - 1) // 2 + (size - 1) % 2]
    left = [item for item in rest if item not in hard]
    return [positive, *hard, *rng.sample(left, min(len(left), size - 1 - len(hard)))]


def translation_pairs(teach):
    pairs = []
    for row in read_stage(teach, 'generated'):
        if row.get('error') is not None:
            continue
        for lang in ('en', 'zh'):
            if row.get(f'query_{lang}'):
                pairs.append({'key': row['chunk_id'], 'split': row['split'], 'lang': lang,
                              'source': row['query'], 'target': row[f'query_{lang}']})
    return pairs


# --- losses (pure torch, unit tested on CPU) ------------------------------------------------------

def teacher_logits(probs, eps=1e-4):
    import torch

    probs = probs.clamp(eps, 1 - eps)
    return torch.log(probs) - torch.log1p(-probs)


def reranker_loss(student, teacher_probs, temperature=1.0, pointwise=0.5):
    """student: [groups, size] yes-minus-no logits. teacher_probs: same shape, P(yes)."""
    import torch.nn.functional as F

    target = F.softmax(teacher_logits(teacher_probs) / temperature, dim=-1)
    listwise = -(target * F.log_softmax(student / temperature, dim=-1)).sum(-1).mean()
    return listwise + pointwise * F.binary_cross_entropy_with_logits(student, teacher_probs)


def embedding_loss(queries, passages, group_size, labels, teacher_probs, temperature=0.05,
                   distill=1.0):
    """queries [B, d], passages [B*G, d] grouped by query, all L2-normalised.

    Column 0 of each group is the positive. Other teacher-labelled positives in the query's own
    group are masked out, never treated as negatives."""
    import torch
    import torch.nn.functional as F

    batch = queries.shape[0]
    sims = queries @ passages.T / temperature
    own = torch.arange(batch, device=sims.device) * group_size
    mask = torch.zeros_like(sims, dtype=torch.bool)
    for row in range(batch):
        start = row * group_size
        extra = labels[row].clone()
        extra[0] = False
        mask[row, start:start + group_size] = extra
    contrastive = F.cross_entropy(sims.masked_fill(mask, float('-inf')), own)
    if not distill:
        return contrastive
    group_sims = torch.stack([sims[row, row * group_size:(row + 1) * group_size]
                              for row in range(batch)])
    target = F.softmax(teacher_logits(teacher_probs), dim=-1)
    return contrastive + distill * -(target * F.log_softmax(group_sims, -1)).sum(-1).mean()


# --- model -------------------------------------------------------------------------------------

class Student:
    def __init__(self, args):
        import torch
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import (AutoModel, AutoModelForCausalLM, AutoTokenizer,
                                  BitsAndBytesConfig)

        self.torch, self.args = torch, args
        self.base = STUDENTS[args.task][args.size]
        self.quantize = args.quantize or STUDENT_QUANTIZE[args.size]
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        self.tokenizer = AutoTokenizer.from_pretrained(self.base)
        self.tokenizer.padding_side = 'left' if args.task != 'translator' else 'right'
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
        kwargs = dict(torch_dtype=torch.float16, attn_implementation='sdpa')
        if self.quantize == '4bit':
            kwargs.update(device_map={'': self.device.index or 0},
                          quantization_config=BitsAndBytesConfig(
                              load_in_4bit=True, bnb_4bit_quant_type='nf4',
                              bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16))
        model_class = AutoModel if args.task == 'embedding' else AutoModelForCausalLM
        model = model_class.from_pretrained(self.base, **kwargs)
        if self.quantize == '4bit':
            model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        else:
            model.to(self.device)
            model.gradient_checkpointing_enable()
            model.enable_input_require_grads()
        model.config.use_cache = False
        self.model = get_peft_model(model, LoraConfig(
            r=args.lora_r, lora_alpha=2 * args.lora_r, lora_dropout=0.05,
            target_modules=LORA_TARGETS, bias='none',
            task_type='FEATURE_EXTRACTION' if args.task == 'embedding' else 'CAUSAL_LM'))
        for parameter in self.model.parameters():
            # fp16 master weights would make GradScaler refuse to unscale; keep LoRA in fp32.
            if parameter.requires_grad:
                parameter.data = parameter.data.float()
        if args.task == 'reranker':
            from ..retrieval.rerank import QWEN_PREFIX, QWEN_SUFFIX

            self.prefix = self.tokenizer.encode(QWEN_PREFIX, add_special_tokens=False)
            self.suffix = self.tokenizer.encode(QWEN_SUFFIX, add_special_tokens=False)
            self.yes = self.tokenizer.convert_tokens_to_ids('yes')
            self.no = self.tokenizer.convert_tokens_to_ids('no')

    def _left_pad(self, sequences):
        torch = self.torch
        width = max(map(len, sequences))
        pad = self.tokenizer.pad_token_id
        ids = torch.full((len(sequences), width), pad, dtype=torch.long)
        mask = torch.zeros((len(sequences), width), dtype=torch.long)
        for row, sequence in enumerate(sequences):
            ids[row, width - len(sequence):] = torch.tensor(sequence)
            mask[row, width - len(sequence):] = 1
        return ids.to(self.device), mask.to(self.device)

    def rerank_logits(self, query, passages):
        from ..retrieval.rerank import qwen_pair_text

        room = self.args.max_length - len(self.prefix) - len(self.suffix)
        bodies = self.tokenizer([qwen_pair_text(query, p) for p in passages],
                                add_special_tokens=False, truncation=True, max_length=room)
        ids, mask = self._left_pad([self.prefix + body + self.suffix
                                    for body in bodies['input_ids']])
        last = self.model(input_ids=ids, attention_mask=mask, logits_to_keep=1).logits[:, -1, :]
        return (last[:, self.yes] - last[:, self.no]).float()

    def embed(self, texts):
        inputs = self.tokenizer(texts, padding=True, truncation=True,
                                max_length=self.args.max_length, return_tensors='pt').to(self.device)
        states = self.model(**inputs).last_hidden_state[:, -1]
        return self.torch.nn.functional.normalize(states.float(), p=2, dim=-1)

    def translation_loss(self, pairs):
        from ..retrieval.translate import PROMPT

        torch = self.torch
        sequences, labels = [], []
        for pair in pairs:
            language = {'en': 'English', 'zh': 'Simplified Chinese'}[pair['lang']]
            messages = [{'role': 'system', 'content': PROMPT.format(language=language)},
                        {'role': 'user', 'content': pair['source']}]
            prompt = self.tokenizer.apply_chat_template(messages, tokenize=True,
                                                        add_generation_prompt=True,
                                                        enable_thinking=False)
            target = self.tokenizer.encode(pair['target'] + '<|im_end|>', add_special_tokens=False)
            sequence = (prompt + target)[:self.args.max_length]
            sequences.append(sequence)
            labels.append(([-100] * len(prompt) + target)[:self.args.max_length])
        width = max(map(len, sequences))
        ids = torch.full((len(pairs), width), self.tokenizer.pad_token_id, dtype=torch.long)
        mask = torch.zeros_like(ids)
        target_ids = torch.full_like(ids, -100)
        for row, (sequence, label) in enumerate(zip(sequences, labels)):
            ids[row, :len(sequence)] = torch.tensor(sequence)
            mask[row, :len(sequence)] = 1
            target_ids[row, :len(label)] = torch.tensor(label)
        return self.model(input_ids=ids.to(self.device), attention_mask=mask.to(self.device),
                          labels=target_ids.to(self.device)).loss


# --- one step per task -----------------------------------------------------------------------

def make_step(task, student, texts, args):
    torch = student.torch

    def reranker_step(batch, rng):
        losses = []
        for group in batch:
            items = pick_items(group, args.group_size, rng)
            logits = student.rerank_logits(group['query'], [texts[i['chunk_id']] for i in items])
            probs = torch.tensor([i['teacher'] for i in items], device=logits.device)
            losses.append(reranker_loss(logits[None], probs[None], pointwise=args.pointwise))
        return torch.stack(losses).mean()

    def embedding_step(batch, rng):
        picked = [pick_items(group, args.group_size, rng) for group in batch]
        if len({len(items) for items in picked}) != 1:
            size = min(map(len, picked))
            picked = [items[:size] for items in picked]
        size = len(picked[0])
        queries = student.embed([EMBED_QUERY_PREFIX + group['query'] for group in batch])
        passages = student.embed([texts[i['chunk_id']] for items in picked for i in items])
        labels = torch.tensor([[i['label'] for i in items] for items in picked],
                              device=queries.device)
        probs = torch.tensor([[i['teacher'] for i in items] for items in picked],
                             device=queries.device)
        return embedding_loss(queries, passages, size, labels, probs,
                              temperature=args.temperature, distill=args.distill)

    def translator_step(batch, rng):
        return student.translation_loss(batch)

    return {'reranker': reranker_step, 'embedding': embedding_step,
            'translator': translator_step}[task]


def evaluate(task, student, dev, texts, args):
    """Dev metrics on held-out synthetic queries: MRR of the seed chunk inside its group for the
    retrieval students, mean target loss for the translator."""
    torch = student.torch
    student.model.eval()
    reciprocal, top1, losses = [], [], []
    with torch.inference_mode(), torch.autocast('cuda', dtype=torch.float16,
                                                enabled=student.device.type == 'cuda'):
        for start in range(0, len(dev), args.batch):
            batch = dev[start:start + args.batch]
            if task == 'translator':
                losses.append(float(student.translation_loss(batch)))
                continue
            for group in batch:
                passages = [texts[i['chunk_id']] for i in group['items']]
                if task == 'reranker':
                    scores = student.rerank_logits(group['query'], passages)
                else:
                    query = student.embed([EMBED_QUERY_PREFIX + group['query']])
                    scores = (query @ student.embed(passages).T)[0]
                rank = int((scores > scores[0]).sum())
                reciprocal.append(1.0 / (rank + 1))
                top1.append(rank == 0)
    student.model.train()
    if task == 'translator':
        return {'dev_loss': round(sum(losses) / max(1, len(losses)), 4), 'dev_batches': len(losses)}
    return {'dev_mrr': round(sum(reciprocal) / max(1, len(reciprocal)), 4),
            'dev_top1': round(sum(top1) / max(1, len(top1)), 4), 'dev_groups': len(reciprocal)}


# --- loop ------------------------------------------------------------------------------------

def _checkpoint(student, optimizer, scaler, state, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    student.model.save_pretrained(folder)
    student.torch.save({'optimizer': optimizer.state_dict(), 'scaler': scaler.state_dict(),
                        **state}, folder / 'trainer_state.pt')


def _push(folder, repo, path_in_repo):
    if not repo:
        return
    from huggingface_hub import HfApi

    api = HfApi(token=hf_token())
    api.create_repo(repo, private=True, exist_ok=True)
    try:
        api.upload_folder(folder_path=str(folder), path_in_repo=path_in_repo, repo_id=repo,
                          commit_message=f'sync {path_in_repo}')
    except Exception as error:
        emit(f'Hub upload lỗi: {error}')


def run(args):
    import torch

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    out = Path(args.out) / f'{args.task}-{args.size}' if not args.name else Path(args.out) / args.name
    out.mkdir(parents=True, exist_ok=True)
    if args.task == 'translator':
        examples = translation_pairs(args.teach)
        texts, dropped = {}, 0
    else:
        examples, texts, dropped = load_groups(args.teach, args.chunks, args.pos_min, args.extra_pos)
    train = [row for row in examples if row['split'] == 'train']
    dev = [row for row in examples if row['split'] == 'dev'][:args.dev_limit]
    if args.limit:
        train = train[:args.limit]
    if not train:
        raise ValueError('No training examples; run T2-T4 first (or check --teach).')
    emit(f'{args.task}-{args.size}: train {len(train)}, dev {len(dev)}, '
         f'bỏ {dropped} nhóm teacher không xác nhận positive')

    student = Student(args)
    trainable = [p for p in student.model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(trainable, lr=args.lr, weight_decay=0.0)
    use_amp = student.device.type == 'cuda'
    scaler = torch.amp.GradScaler('cuda', enabled=use_amp)
    per_update = args.batch * args.accum
    total_updates = max(1, math.ceil(len(train) * args.epochs / per_update))
    warmup = max(1, int(0.05 * total_updates))

    def lr_at(update):
        if update < warmup:
            return args.lr * (update + 1) / warmup
        return args.lr * max(0.0, (total_updates - update) / max(1, total_updates - warmup))

    state = {'update': 0, 'seen': 0, 'history': []}
    checkpoint = out / 'checkpoint'
    if args.resume and args.hub_repo and not (checkpoint / 'trainer_state.pt').exists():
        # A new Kaggle session starts with an empty /kaggle/working; the Hub has the last save.
        from huggingface_hub import snapshot_download

        try:
            snapshot_download(args.hub_repo, local_dir=Path(args.out).parent / '_hub',
                              allow_patterns=[f'students/{out.name}/checkpoint/*'],
                              token=hf_token())
            pulled = Path(args.out).parent / '_hub' / 'students' / out.name / 'checkpoint'
            if (pulled / 'trainer_state.pt').exists():
                import shutil

                shutil.copytree(pulled, checkpoint, dirs_exist_ok=True)
                emit('Đã tải checkpoint từ Hub.')
        except Exception as error:  # no repo yet means a first run
            emit(f'Không tải được checkpoint từ Hub ({error}); train từ đầu.')
    if args.resume and (checkpoint / 'trainer_state.pt').exists():
        from peft import set_peft_model_state_dict
        from safetensors.torch import load_file

        set_peft_model_state_dict(student.model, load_file(checkpoint / 'adapter_model.safetensors'))
        saved = torch.load(checkpoint / 'trainer_state.pt', weights_only=False)
        optimizer.load_state_dict(saved.pop('optimizer'))
        scaler.load_state_dict(saved.pop('scaler'))
        state = saved
        emit(f"Tiếp tục từ update {state['update']}/{total_updates}")

    metrics = {'before': state.get('before') or evaluate(args.task, student, dev, texts, args)}
    state['before'] = metrics['before']
    emit(f"Trước khi train: {metrics['before']}")
    step = make_step(args.task, student, texts, args)
    deadline = Deadline(args.hours)
    rng = random.Random(args.seed + state['update'])
    started, start_update, finished = time.monotonic(), state['update'], False
    student.model.train()
    while state['update'] < total_updates:
        epoch, offset = divmod(state['seen'], len(train))
        order = list(range(len(train)))
        random.Random(args.seed + epoch).shuffle(order)
        for group in optimizer.param_groups:
            group['lr'] = lr_at(state['update'])
        total = 0.0
        for micro in range(args.accum):
            start = offset + micro * args.batch
            batch = [train[order[i % len(train)]] for i in range(start, start + args.batch)]
            with torch.autocast('cuda', dtype=torch.float16, enabled=use_amp):
                loss = step(batch, rng) / args.accum
            scaler.scale(loss).backward()
            total += float(loss.detach())
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad(set_to_none=True)
        state['update'] += 1
        state['seen'] += per_update
        if state['update'] % args.log_every == 0 or state['update'] == total_updates:
            rate = (state['update'] - start_update) / max(1e-6, time.monotonic() - started)
            state['history'].append({'update': state['update'], 'loss': round(total, 5)})
            emit(f"update {state['update']}/{total_updates} loss {total:.4f} "
                 f"lr {lr_at(state['update']):.2e} | {rate * 60:.1f} update/phút")
        if state['update'] % args.save_every == 0:
            _checkpoint(student, optimizer, scaler, state, checkpoint)
            _push(checkpoint, args.hub_repo, f'students/{out.name}/checkpoint')
        if deadline.passed():
            _checkpoint(student, optimizer, scaler, state, checkpoint)
            _push(checkpoint, args.hub_repo, f'students/{out.name}/checkpoint')
            emit('Hết thời gian session: đã lưu checkpoint, chạy lại với --resume.')
            break
    else:
        finished = True
    if not finished:
        return {'finished': False, 'update': state['update']}

    metrics['after'] = evaluate(args.task, student, dev, texts, args)
    emit(f"Sau khi train: {metrics['after']}")
    student.model.save_pretrained(out)
    student.tokenizer.save_pretrained(out)
    config = {'reranker': {'kind': 'causal-yes-no', 'max_length': args.max_length},
              'embedding': {'pooling': 'last', 'max_length': args.max_length,
                            'query_prefix': EMBED_QUERY_PREFIX, 'doc_prefix': '',
                            'dim': student.model.config.hidden_size},
              'translator': {}}[args.task]
    storage.write_json(out / STUDENT_FILE, {
        'task': args.task, 'size': args.size, 'base': student.base, 'quantize': student.quantize,
        'config': config, 'metrics': metrics, 'teach_dir': str(args.teach),
        'environment': environment(), 'history': state['history'],
        'options': {k: v for k, v in vars(args).items() if not callable(v)}})
    _push(out, args.hub_repo, f'students/{out.name}')
    emit(json.dumps(metrics, ensure_ascii=False))
    return metrics


def add_arguments(parser):
    parser.add_argument('--task', choices=sorted(STUDENTS), required=True)
    parser.add_argument('--size', choices=['0.6b', '4b', '8b', '14b'], required=True,
                        help='0.6b is a laptop smoke run of the same loop.')
    parser.add_argument('--teach', default='work/teach')
    parser.add_argument('--chunks', default=None, help='Required for reranker and embedding.')
    parser.add_argument('--out', default='work/students')
    parser.add_argument('--name', default=None, help='Folder name; default <task>-<size>.')
    parser.add_argument('--quantize', choices=['4bit', 'none'], default=None)
    parser.add_argument('--epochs', type=float, default=1.0)
    parser.add_argument('--batch', type=int, default=None)
    parser.add_argument('--accum', type=int, default=None)
    parser.add_argument('--group-size', type=int, default=8)
    parser.add_argument('--max-length', type=int, default=None)
    parser.add_argument('--lr', type=float, default=None)
    parser.add_argument('--lora-r', type=int, default=16)
    parser.add_argument('--pos-min', type=float, default=0.5)
    parser.add_argument('--extra-pos', type=float, default=0.8)
    parser.add_argument('--pointwise', type=float, default=0.5)
    parser.add_argument('--temperature', type=float, default=0.05)
    parser.add_argument('--distill', type=float, default=1.0)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--dev-limit', type=int, default=500)
    parser.add_argument('--log-every', type=int, default=10)
    parser.add_argument('--save-every', type=int, default=200)
    parser.add_argument('--hours', type=float, default=11.0)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--hub-repo', default=None, help='Private HF model repo for adapters.')
    parser.add_argument('--seed', type=int, default=13)


# Per task and size: (batch, accum, max_length, lr). Sized for one 16GB T4.
DEFAULTS = {
    'reranker': {'0.6b': (1, 2, 384, 1e-4), '4b': (2, 8, 640, 1e-4), '8b': (1, 16, 640, 1e-4),
                 '14b': (1, 16, 512, 8e-5)},
    'embedding': {'0.6b': (2, 2, 256, 1e-4), '4b': (4, 4, 512, 1e-4), '8b': (2, 8, 512, 1e-4),
                  '14b': (2, 8, 384, 8e-5)},
    'translator': {'0.6b': (2, 2, 256, 2e-4), '4b': (8, 2, 384, 2e-4), '8b': (4, 4, 384, 2e-4),
                   '14b': (2, 8, 384, 1e-4)},
}


def finalise(args):
    batch, accum, length, lr = DEFAULTS[args.task][args.size]
    args.batch = args.batch or batch
    args.accum = args.accum or accum
    args.max_length = args.max_length or length
    args.lr = args.lr or lr
    if args.task != 'translator' and not args.chunks:
        raise SystemExit('--chunks is required for the reranker and embedding students.')
    return args


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_arguments(parser)
    run(finalise(parser.parse_args(argv)))
