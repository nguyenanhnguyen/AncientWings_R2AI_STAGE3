"""Measure batch throughput on real chunk lengths before committing hours of GPU time."""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from .common import storage
from .common.console import emit
from .common.runtime import environment, model_info, release_model
from .corpus.chunk import retrieval_text
from .index.embedding import load_encoder
from .retrieval.rerank import load_reranker
from .retrieval.query import load_queries


def preflight(device='cuda', quantized=False):
    import torch
    result = environment()
    if device.startswith('cuda'):
        if not torch.cuda.is_available():
            raise RuntimeError(f'PyTorch {torch.__version__} cannot use CUDA. '
                               'Install the CUDA wheel in run_guide.md; no CPU fallback.')
        props = torch.cuda.get_device_properties(device)
        result.update(gpu=props.name, vram_gib=props.total_memory / 2**30,
                      capability=torch.cuda.get_device_capability(device), cuda=torch.version.cuda)
        with torch.inference_mode():
            a = torch.ones((64, 64), dtype=torch.float16, device=device)
            if not torch.isfinite(a @ a).all():
                raise RuntimeError('CUDA fp16 matmul failed.')
        del a
    if quantized:
        import bitsandbytes  # Fail before crawling/indexing if the optional runtime is absent.
        import accelerate
        result['quantization_runtime'] = [bitsandbytes.__version__, accelerate.__version__]
        if device.startswith('cuda'):
            layer = output = None
            try:
                layer = bitsandbytes.nn.Linear4bit(
                    16, 8, bias=False, compute_dtype=torch.float16, quant_type='nf4'
                ).to(device)
                with torch.inference_mode():
                    output = layer(torch.ones((1, 16), dtype=torch.float16, device=device))
                    torch.cuda.synchronize(device)
                    if not torch.isfinite(output).all():
                        raise RuntimeError('NF4 produced non-finite values.')
                result['nf4_gpu_test'] = 'ok'
            except Exception as exc:
                raise RuntimeError('bitsandbytes NF4 GPU test failed; quantized translation cannot run.') from exc
            finally:
                del layer, output
                torch.cuda.empty_cache()
    emit(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def run(args):
    import torch
    env = preflight(args.device)
    chunks = storage.read_parquet(args.chunks)
    # Stratify by length and include the longest passages to expose padding/OOM/truncation.
    chunks.sort(key=lambda c: len(c['text']))
    positions = np.linspace(0, len(chunks)-1, min(args.samples, len(chunks)), dtype=int)
    texts = [retrieval_text(chunks[i]) for i in positions]
    if not texts:
        raise ValueError('No pilot chunks')
    query = max(load_queries(args.queries), key=lambda q: len(q['query']))['query']
    results = []
    cuda = args.device.startswith('cuda')
    for kind, names in [('encoder', args.encoders), ('reranker', args.rerankers)]:
        for name in names:
            factory = load_encoder if kind == 'encoder' else load_reranker
            model = factory(name, device=args.device, max_length=args.max_length)
            info = model_info(model)
            trials = []
            def compute(batch):
                if kind == 'encoder':
                    return model.encode(texts, batch_size=batch)
                return model.score(query, texts, batch_size=batch)
            try:
                compute(1)  # Warm-up; excluded from throughput measurements.
                for batch in args.batches:
                    if hasattr(model, 'safe_batch'):
                        del model.safe_batch
                    if cuda:
                        torch.cuda.synchronize()
                        torch.cuda.reset_peak_memory_stats()
                    started = time.monotonic()
                    compute(batch)
                    if cuda:
                        torch.cuda.synchronize()
                    elapsed = time.monotonic() - started
                    trials.append({'requested_batch': batch,
                                   'effective_batch': getattr(model, 'safe_batch', batch),
                                   'items_per_second': len(texts)/elapsed,
                                   'seconds': elapsed,
                                   'peak_vram_mib': torch.cuda.max_memory_allocated()/2**20 if cuda else 0})
                    emit(f'{kind} {name}: {trials[-1]}')
                best = max(trials, key=lambda t: t['items_per_second'])
                token_lengths = []
                if hasattr(model, 'tokenizer'):
                    token_lengths = [len(ids) for ids in model.tokenizer(texts, truncation=False)['input_ids']]
                results.append({'kind': kind, 'name': name, 'model': info, 'trials': trials,
                                'batch_size': best['effective_batch'],
                                'raw_passages_over_max_length': sum(n > args.max_length for n in token_lengths),
                                'note': 'Native token lengths exclude query/prompt; truncation may be greater.'})
            finally:
                release_model(model)
    storage.write_json(args.out, {'environment': env, 'samples': len(texts), 'models': results,
                                  'chunks_sha256': storage.sha256_file(args.chunks)})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check-only', action='store_true')
    p.add_argument('--quantized', action='store_true')
    p.add_argument('--device', default='cuda')
    p.add_argument('--chunks', default='work/chunks/chunks.parquet')
    p.add_argument('--queries', default='data/query.parquet')
    p.add_argument('--out', default='work/pilot.json')
    p.add_argument('--encoders', nargs='+', default=['bge-m3', 'qwen3-embedding-0.6b'])
    p.add_argument('--rerankers', nargs='+', default=['bge-reranker-v2-m3', 'qwen3-reranker-0.6b'])
    p.add_argument('--max-length', type=int, default=1024)
    p.add_argument('--samples', type=int, default=48)
    p.add_argument('--batches', nargs='+', type=int, default=[2, 4, 8, 16])
    args = p.parse_args()
    if args.check_only:
        preflight(args.device, args.quantized)
    else:
        run(args)


if __name__ == '__main__':
    main()
