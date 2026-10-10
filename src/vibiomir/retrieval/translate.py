"""Query-side generation with one open local LLM: translations and HyDE passages, cached.

83% of the corpus URLs are Chinese, every query is Vietnamese. BM25 cannot cross that gap, and
dense cross-lingual matching is weaker than matching within one language. Only 1.200 queries
exist, so generating text on the query side is cheap, where translating millions of documents
is not. Two kinds of output:

    translate  The question in Chinese (and English when the corpus has English documents). Feeds
               BM25, the dense index, and the reranker for documents in that language.
    hyde       A short passage written like the article or doctor's answer that would answer the
               question (Gao et al., 2022, "HyDE"). Searched with, never submitted: the submission
               only ever carries spans cut from the crawled documents.

Generation is batched (left padding), because one-at-a-time decoding of 1.200 x 3 outputs takes
hours on a T4. Every output is cached by model, prompt and query text, and checked cheaply.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from ..common import storage
from ..common.cache import Cache, cache_key
from ..common.console import emit
from ..common.runtime import environment, release_model, Progress
from ..teach.models import discover_students, load_backbone
from .query import load_queries

# One translator: Qwen3-4B (2025-04, open, 4B), 4-bit on a 4 GB laptop GPU, fp16 on a T4.
MODELS = {'qwen3-4b': 'Qwen/Qwen3-4B'}
# Translator students (teach/train): base model plus LoRA adapter, trained on PROMPT below.
MODELS.update(discover_students('translator'))
LANGUAGE_NAMES = {'en': 'English', 'zh': 'Simplified Chinese', 'vi': 'Vietnamese'}
PROMPT = ('Translate the Vietnamese medical question into {language} for document retrieval. '
          'Preserve every symptom, negation, duration, age, number, unit and drug name. '
          'Do not answer the question or add facts. Output only the translation.')
HYDE_PROMPT = ('Write a short passage in {language}, 3 to 5 sentences, as it would appear in a '
               'medical article or a doctor\'s reply that answers the Vietnamese patient question. '
               'Use standard medical terminology for the condition, its causes, tests and '
               'treatment. Output only the passage.')
KINDS = {'translate': PROMPT, 'hyde': HYDE_PROMPT}
_VIETNAMESE = re.compile(r'[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]',
                         re.IGNORECASE)


def check_translation(source, text, lang):
    """Cheap rejection checks; semantic correctness still requires human review."""
    if not text.strip() or text.strip().casefold() == source.strip().casefold():
        return 'empty_or_unchanged'
    if '<think>' in text or '</think>' in text:
        return 'unexpected_reasoning'
    if Counter(re.findall(r'\d+', source)) != Counter(re.findall(r'\d+', text)):
        return 'numbers_changed'
    if lang == 'zh' and not re.search(r'[㐀-鿿]', text):
        return 'missing_chinese'
    if lang == 'en' and not re.search(r'[a-zA-Z]', text):
        return 'missing_english'
    return None


def check_hyde(text, lang):
    if len(text.strip()) < 20:
        return 'too_short'
    if '<think>' in text or '</think>' in text:
        return 'unexpected_reasoning'
    if lang == 'zh' and not re.search(r'[㐀-鿿]', text):
        return 'missing_chinese'
    if lang == 'vi' and not _VIETNAMESE.search(text):
        return 'missing_vietnamese'
    return None


def _tasks(args):
    tasks = [('translate', lang) for lang in args.languages]
    tasks += [('hyde', lang) for lang in getattr(args, 'hyde', None) or []]
    if not tasks:
        raise ValueError('Nothing to generate: give --languages and/or --hyde.')
    return tasks


def build(args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if str(args.device).startswith('cuda') and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable. Install a CUDA build of torch before translation.')
    queries = load_queries(args.queries)
    if args.limit:
        queries = queries[:args.limit]
    tasks = _tasks(args)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.quantize == '4bit' and not args.device.startswith('cuda'):
        raise ValueError('This 4-bit profile requires CUDA.')
    entry = MODELS[args.model]
    config = dict(entry) if isinstance(entry, dict) else {'hf_id': entry}
    config['quantize'] = args.quantize
    hf_id = config['hf_id']
    tokenizer = AutoTokenizer.from_pretrained(hf_id, revision=args.revision)
    tokenizer.padding_side = 'left'
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    dtype = torch.float16 if args.device.startswith('cuda') else torch.float32
    model = load_backbone(AutoModelForCausalLM, config, args.device, dtype, args.revision,
                          attn_implementation='sdpa')
    base_info = {'hf_id': hf_id, 'revision': getattr(model.config, '_commit_hash', None),
                 **({'adapter_sha': config['adapter_sha']} if config.get('adapter_sha') else {}),
                 'quantize': args.quantize, 'max_input': args.max_input, 'version': 1}
    max_new = {'translate': args.max_new_tokens, 'hyde': getattr(args, 'hyde_tokens', 256)}

    def info_for(kind):
        # The translation key matches the earlier one-at-a-time version, so its cache is reused.
        return {**base_info, 'max_new_tokens': max_new[kind], 'prompt': KINDS[kind],
                **({'kind': kind} if kind != 'translate' else {})}

    results = {}
    pending = []
    with Cache(out / 'translations.sqlite') as cache:
        for query in queries:
            for kind, lang in tasks:
                key = cache_key({'model': info_for(kind), 'query': query['query'], 'lang': lang})
                cached = cache.get(key)
                if cached is None:
                    messages = [{'role': 'system', 'content': KINDS[kind].format(
                        language=LANGUAGE_NAMES[lang])}, {'role': 'user', 'content': query['query']}]
                    prompt = tokenizer.apply_chat_template(messages, tokenize=False,
                                                           add_generation_prompt=True,
                                                           enable_thinking=False)
                    pending.append((query, kind, lang, key, prompt))
                else:
                    results[(query['id'], kind, lang)] = cached
        emit(f'generate: {len(results)} từ cache, {len(pending)} cần sinh')
        progress = Progress('generate')
        size = max(1, args.batch_size)
        # Same kind together (same max_new_tokens), then by prompt length to limit padding.
        pending.sort(key=lambda item: (item[1], len(item[4])))
        position = 0
        try:
            while position < len(pending):
                batch = pending[position:position + size]
                kind = batch[0][1]
                batch = [item for item in batch if item[1] == kind]
                try:
                    fresh = _generate(torch, tokenizer, model, [item[4] for item in batch],
                                      args.device, args.max_input, max_new[kind])
                except RuntimeError as error:
                    if 'out of memory' not in str(error).lower() or size == 1:
                        raise
                    size = max(1, size // 2)
                    torch.cuda.empty_cache()
                    emit(f'generate: hết VRAM, giảm batch xuống {size}')
                    continue
                writes = []
                for (query, kind_, lang, key, _prompt), (text, error) in zip(batch, fresh):
                    if error is None:
                        error = (check_translation(query['query'], text, lang)
                                 if kind_ == 'translate' else check_hyde(text, lang))
                    value = {'text': text, 'error': error}
                    results[(query['id'], kind_, lang)] = value
                    writes.append((key, value))
                cache.put_many(writes)
                position += len(batch)
                progress(position, len(pending))
        finally:
            del model
            release_model(tokenizer)

    rows, failures = [], []
    for query in queries:
        for kind, lang in tasks:
            value = results[(query['id'], kind, lang)]
            if value['error']:
                failures.append({'id': query['id'], 'lang': lang, 'kind': kind, **value})
            else:
                rows.append({'id': query['id'], 'lang': lang, 'kind': kind, 'text': value['text'],
                             'query_sha256': storage.sha256_text(query['query'])})
    target = out / 'translations.jsonl'
    storage.write_jsonl(target, rows)
    storage.write_jsonl(out / 'rejected.jsonl', failures)
    total = len(queries) * len(tasks)
    summary = {'model': {**base_info, 'prompts': KINDS, 'max_new_tokens': max_new},
               'environment': environment(), 'tasks': [f'{k}:{l}' for k, l in tasks],
               'accepted': len(rows), 'rejected': len(failures), 'requested': total,
               'rejected_by_reason': dict(Counter(item['error'] for item in failures)),
               'queries_sha256': storage.sha256_file(args.queries)}
    storage.write_manifest(out / 'translation_manifest.json', summary, files=[target])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures and not args.allow_partial:
        raise ValueError('Some outputs failed checks; inspect rejected.jsonl. '
                         'Use --allow-partial to retain original queries and valid outputs.')
    return summary


def _generate(torch, tokenizer, model, prompts, device, max_input, max_new_tokens):
    """-> [(text, error)] for a batch of chat prompts, greedy decoding."""
    encoded = tokenizer(prompts, add_special_tokens=False)
    too_long = [len(ids) > max_input for ids in encoded['input_ids']]
    keep = [i for i, flag in enumerate(too_long) if not flag]
    outputs = [('', 'input_too_long') if flag else None for flag in too_long]
    if keep:
        inputs = tokenizer([prompts[i] for i in keep], add_special_tokens=False, padding=True,
                           return_tensors='pt').to(device)
        with torch.inference_mode():
            generated = model.generate(**inputs, do_sample=False, max_new_tokens=max_new_tokens,
                                       use_cache=True, pad_token_id=tokenizer.pad_token_id)
        width = inputs['input_ids'].shape[1]
        eos = {tokenizer.eos_token_id, tokenizer.pad_token_id}
        configured = getattr(model.generation_config, 'eos_token_id', None)
        if isinstance(configured, int):
            eos.add(configured)
        elif configured:
            eos.update(configured)
        for row, index in enumerate(keep):
            new = generated[row, width:].tolist()
            finished = any(token in eos for token in new)
            text = tokenizer.decode(new, skip_special_tokens=True).strip()
            truncated = not finished and len(new) >= max_new_tokens
            outputs[index] = (text, 'output_truncated' if truncated else None)
        del inputs, generated
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--out', default='work/translations')
    parser.add_argument('--model', choices=MODELS, default='qwen3-4b')
    parser.add_argument('--revision', default=None)
    parser.add_argument('--quantize', choices=['4bit', 'none'], default='4bit')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--languages', nargs='*', choices=['en', 'zh'], default=['en', 'zh'],
                        help='Translation targets.')
    parser.add_argument('--hyde', nargs='*', choices=['zh', 'vi', 'en'], default=[],
                        help='Languages of the HyDE passages; empty disables them.')
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--max-input', type=int, default=1024)
    parser.add_argument('--max-new-tokens', type=int, default=512, help='For translations.')
    parser.add_argument('--hyde-tokens', type=int, default=256, help='For HyDE passages.')
    parser.add_argument('--limit', type=int, default=None, help='Pilot only; omit for all queries.')
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    build(args)


if __name__ == '__main__':
    main()
