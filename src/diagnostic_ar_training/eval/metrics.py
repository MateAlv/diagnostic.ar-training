"""Ranking metrics. A rank is 1-based; math.inf means the true gene is not rankable."""

import math
from collections.abc import Callable, Sequence

import numpy as np

KS = (1, 3, 5, 10, 20, 50)


def rank_of(true_gene: str, genes: Sequence[str], scores: np.ndarray) -> float:
    """Pessimistic rank: ties with the true gene count against it."""
    try:
        idx = list(genes).index(true_gene)
    except ValueError:
        return math.inf
    target = scores[idx]
    return float(1 + np.sum(scores > target) + (np.sum(scores == target) - 1))


def summarize(ranks: Sequence[float], ks: Sequence[int] = KS) -> dict:
    r = np.asarray(ranks, dtype=float)
    out = {"n": int(r.size), "unrankable": int(np.isinf(r).sum()), "mrr": float(np.mean(1.0 / r))}
    for k in ks:
        out[f"top{k}"] = float(np.mean(r <= k))
    return out


def _metric(name: str) -> Callable[[np.ndarray], float]:
    if name == "mrr":
        return lambda r: float(np.mean(1.0 / r))
    if name.startswith("top"):
        k = int(name[3:])
        return lambda r: float(np.mean(r <= k))
    raise ValueError(name)


def paired_bootstrap(
    base: Sequence[float],
    new: Sequence[float],
    metric: str = "mrr",
    n_resamples: int = 2000,
    seed: int = 0,
) -> dict:
    """Delta new - base on the same cases, with a percentile 95% CI."""
    a, b = np.asarray(base, dtype=float), np.asarray(new, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired bootstrap needs the same cases in the same order")
    fn = _metric(metric)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, a.size, size=(n_resamples, a.size))
    deltas = np.array([fn(b[i]) - fn(a[i]) for i in idx])
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return {"metric": metric, "delta": fn(b) - fn(a), "ci95": [float(lo), float(hi)], "n": int(a.size)}


def harmed_helped(base: Sequence[float], new: Sequence[float]) -> dict:
    a, b = np.asarray(base, dtype=float), np.asarray(new, dtype=float)
    return {"harmed": float(np.mean(b > a)), "helped": float(np.mean(b < a))}
