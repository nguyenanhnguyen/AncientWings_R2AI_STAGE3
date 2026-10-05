"""Small GPU runtime helpers; no CUDA import for CPU-only pipeline stages."""
import gc
import importlib.metadata
import sys
import time


def release_model(owner):
    """Drop the weights before the next model is loaded on a 4 GB card."""
    if hasattr(owner, 'model'):
        del owner.model
    gc.collect()
    torch = sys.modules.get('torch')
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()


def model_info(owner):
    config = getattr(owner, 'config', {})
    model = getattr(owner, 'model', None)
    return {'name': owner.name, 'hf_id': config.get('hf_id'),
            'revision': getattr(getattr(model, 'config', None), '_commit_hash', None),
            'max_length': config.get('max_length'),
            'parameters': sum(p.numel() for p in model.parameters()) if model else 0,
            'dtype': str(getattr(model, 'dtype', None)),
            'device': str(getattr(owner, 'device', 'cpu')),
            'config': config}


def environment():
    versions = {}
    for name in ('torch', 'transformers', 'numpy', 'pyarrow', 'bitsandbytes', 'accelerate'):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            pass
    return {'python': sys.version, 'packages': versions}


class Progress:
    def __init__(self, label):
        self.label, self.started, self.last = label, time.monotonic(), 0.0

    def __call__(self, done, total):
        now = time.monotonic()
        if now - self.last < 15 and done != total:
            return
        from .console import emit
        elapsed = now - self.started
        rate = done / max(elapsed, 1e-6)
        emit(f'{self.label}: {done}/{total} | {rate:.2f}/s | '
             f'ETA {(total-done)/max(rate, 1e-6)/60:.1f} min')
        self.last = now
