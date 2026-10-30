"""Translate queries with an open local model; cache outputs, never generate submission chunks."""
import argparse
from collections import Counter
import json
from pathlib import Path
import re

from ..common import storage
from ..common.cache import Cache, cache_key
from ..common.console import emit
from ..common.runtime import environment, release_model, Progress
from .query import load_queries

MODELS = {'qwen3-4b': 'Qwen/Qwen3-4B', 'qwen3-1.7b': 'Qwen/Qwen3-1.7B',
          'qwen3-0.6b': 'Qwen/Qwen3-0.6B'}
PROMPT = ('Translate the Vietnamese medical question into {language} for document retrieval. '
          'Preserve every symptom, negation, duration, age, number, unit and drug name. '
          'Do not answer the question or add facts. Output only the translation.')


def check_translation(source, text, lang):
    """Cheap rejection checks; semantic correctness still requires human review."""
    if not text.strip() or text.strip().casefold() == source.strip().casefold():
        return 'empty_or_unchanged'
    if '<think>' in text or '</think>' in text:
        return 'unexpected_reasoning'
    if Counter(re.findall(r'\d+', source)) != Counter(re.findall(r'\d+', text)):
        return 'numbers_changed'
    if lang == 'zh' and not re.search(r'[\u3400-\u9fff]', text):
        return 'missing_chinese'
    if lang == 'en' and not re.search(r'[a-zA-Z]', text):
        return 'missing_english'
    return None


def build(args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if str(args.device).startswith('cuda') and not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable. Install a CUDA build of torch before translation.')
    queries = load_queries(args.queries)
    if args.limit:
        queries = queries[:args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    hf_id = MODELS[args.model]
    tokenizer = AutoTokenizer.from_pretrained(hf_id, revision=args.revision)
    kwargs = dict(revision=args.revision, attn_implementation='sdpa',
                  torch_dtype=torch.float16 if args.device.startswith('cuda') else torch.float32)
    if args.quantize == '4bit':
        if not args.device.startswith('cuda'):
            raise ValueError('This 4-bit profile requires CUDA.')
        kwargs.update(quantization_config=BitsAndBytesConfig(load_in_4bit=True,
                      bnb_4bit_quant_type='nf4', bnb_4bit_use_double_quant=True,
                      bnb_4bit_compute_dtype=torch.float16), device_map={'': args.device})
    model = AutoModelForCausalLM.from_pretrained(hf_id, **kwargs).eval()
    if args.quantize == 'none':
        model.to(args.device)
    info = {'hf_id': hf_id, 'revision': getattr(model.config, '_commit_hash', None),
            'quantize': args.quantize, 'max_input': args.max_input,
            'max_new_tokens': args.max_new_tokens, 'prompt': PROMPT, 'version': 1}
    rows, failures = [], []
    progress = Progress('translate')
    total = len(queries) * len(args.languages)
    done = 0
    try:
        with Cache(out / 'translations.sqlite') as cache:
            for query in queries:
                for lang in args.languages:
                    key = cache_key({'model': info, 'query': query['query'], 'lang': lang})
                    cached = cache.get(key)
                    if cached is None:
                        messages = [{'role': 'system', 'content': PROMPT.format(
                            language={'en': 'English', 'zh': 'Simplified Chinese'}[lang])},
                            {'role': 'user', 'content': query['query']}]
                        prompt = tokenizer.apply_chat_template(messages, tokenize=False,
                                        add_generation_prompt=True, enable_thinking=False)
                        inputs = tokenizer(prompt, return_tensors='pt').to(args.device)
                        if inputs.input_ids.shape[1] > args.max_input:
                            cached = {'text': '', 'error': 'input_too_long'}
                        else:
                            with torch.inference_mode():
                                output = model.generate(**inputs, do_sample=False,
                                        max_new_tokens=args.max_new_tokens, use_cache=True,
                                        pad_token_id=tokenizer.eos_token_id)
                            new = output[0, inputs.input_ids.shape[1]:]
                            text = tokenizer.decode(new, skip_special_tokens=True).strip()
                            error = ('output_truncated' if len(new) >= args.max_new_tokens
                                     and int(new[-1]) != tokenizer.eos_token_id
                                     else check_translation(query['query'], text, lang))
                            cached = {'text': text, 'error': error}
                            del output, new
                        del inputs
                        cache.put_many([(key, cached)])
                    if cached['error']:
                        failures.append({'id': query['id'], 'lang': lang, **cached})
                    else:
                        rows.append({'id': query['id'], 'lang': lang, 'text': cached['text'],
                                     'query_sha256': storage.sha256_text(query['query'])})
                    done += 1
                    progress(done, total)
    finally:
        del model
        release_model(tokenizer)
    target = out / 'translations.jsonl'
    storage.write_jsonl(target, rows)
    storage.write_jsonl(out / 'rejected.jsonl', failures)
    summary = {'model': info, 'environment': environment(), 'accepted': len(rows),
               'rejected': len(failures), 'requested': total,
               'queries_sha256': storage.sha256_file(args.queries)}
    storage.write_manifest(out / 'translation_manifest.json', summary, files=[target])
    emit(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures and not args.allow_partial:
        raise ValueError('Some translations failed checks; inspect rejected.jsonl. '
                         'Use --allow-partial to retain original queries and valid translations.')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queries', default='data/query.parquet')
    parser.add_argument('--out', default='work/translations')
    parser.add_argument('--model', choices=MODELS, default='qwen3-4b')
    parser.add_argument('--revision', default=None)
    parser.add_argument('--quantize', choices=['4bit', 'none'], default='4bit')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--languages', nargs='+', choices=['en', 'zh'], default=['en', 'zh'])
    parser.add_argument('--max-input', type=int, default=1024)
    parser.add_argument('--max-new-tokens', type=int, default=512)
    parser.add_argument('--limit', type=int, default=None, help='Pilot only; omit for all queries.')
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    build(args)


if __name__ == '__main__':
    main()
