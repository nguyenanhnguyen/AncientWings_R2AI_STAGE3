"""Turn reranker scores into relevance probabilities, separately per document language.

The F2-optimal cut in `choose.py` compares a candidate's probability of being relevant with the
current expected F2 divided by five. Reranker outputs in [0, 1] are not such probabilities, and a
Vietnamese question against a Chinese passage is scored on a shifted scale. Platt scaling fits
p = sigmoid(a * logit(score) + b) on human dev labels, one (a, b) per language, with a shared
fallback. Without a calibration file the identity map (a=1, b=0) is used.

A candidate counts as positive when its document is a labelled relevant document of that query;
document labels are what a person can judge reliably from the label sheet.
"""
import math

import numpy as np

from ..common import storage

IDENTITY = {'default': [1.0, 0.0]}
_EPS = 1e-6


def _logit(score):
    score = min(max(float(score), _EPS), 1 - _EPS)
    return math.log(score / (1 - score))


def apply(score, lang, calibration=None):
    a, b = (calibration or IDENTITY).get(lang) or (calibration or IDENTITY).get('default', [1.0, 0.0])
    if a == 1.0 and b == 0.0:
        return float(min(max(score, 0.0), 1.0))
    return 1.0 / (1.0 + math.exp(-(a * _logit(score) + b)))


def fit_platt(scores, labels, iterations=200, l2=1e-3):
    """(a, b) by Newton's method on the log-loss, lightly regularised towards (1, 0)."""
    x = np.array([_logit(s) for s in scores], dtype=np.float64)
    y = np.array(labels, dtype=np.float64)
    if len(x) < 10 or y.min() == y.max():
        return [1.0, 0.0]
    w = np.array([1.0, 0.0])
    design = np.stack([x, np.ones_like(x)], axis=1)
    prior = np.array([1.0, 0.0])
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-(design @ w)))
        gradient = design.T @ (p - y) + l2 * (w - prior)
        hessian = design.T @ (design * (p * (1 - p))[:, None]) + l2 * np.eye(2)
        step = np.linalg.solve(hessian, gradient)
        w = w - step
        if np.abs(step).max() < 1e-8:
            break
    return [float(w[0]), float(w[1])]


def fit(records, labels, min_per_language=30):
    """-> calibration dict {'default': [a, b], '<lang>': [a, b], ...} plus counts."""
    pairs = {}
    for record in records:
        query_id = int(record['query_id'])
        if query_id not in labels:
            continue
        relevant = set(labels[query_id]['docs'])
        for candidate in record.get('candidates') or []:
            if candidate.get('ce_score') is None:
                continue
            target = 1 if int(candidate['doc_id']) in relevant else 0
            pairs.setdefault(candidate.get('lang') or 'unknown', []).append(
                (candidate['ce_score'], target))
    everything = [pair for items in pairs.values() for pair in items]
    if not everything:
        raise ValueError('No labelled query has reranked candidates; nothing to calibrate.')
    result = {'default': fit_platt(*zip(*everything))}
    counts = {'default': len(everything)}
    for lang, items in pairs.items():
        if len(items) >= min_per_language and len({target for _s, target in items}) == 2:
            result[lang] = fit_platt(*zip(*items))
            counts[lang] = len(items)
    return result, counts


def load(path):
    if not path:
        return None
    data = storage.read_json(path)
    return data.get('calibration', data)
