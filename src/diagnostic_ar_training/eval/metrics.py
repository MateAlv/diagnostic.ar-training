"""Ranking metrics. A rank is 1-based; math.inf means the true gene is not rankable."""

import math
from collections.abc import Sequence

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


def _per_case(metric: str, ranks: np.ndarray) -> np.ndarray:
    if metric == "mrr":
        return 1.0 / ranks
    if metric.startswith("top"):
        return (ranks <= int(metric[3:])).astype(float)
    raise ValueError(metric)


def paired_bootstrap(
    base: Sequence[float],
    new: Sequence[float],
    metric: str = "mrr",
    n_resamples: int = 2000,
    seed: int = 0,
    groups: Sequence[str] | None = None,
    level: float | None = None,
) -> dict:
    """Delta new - base on the same cases, with a percentile 95% CI (and a `level` CI when given).

    With `groups`, whole groups are resampled (cluster bootstrap). R1 must pass
    its publication groups: patients of one paper are not independent, and
    case-level CIs there come out 3-7x too narrow (EXP-000).
    """
    a, b = np.asarray(base, dtype=float), np.asarray(new, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired bootstrap needs the same cases in the same order")
    diff = _per_case(metric, b) - _per_case(metric, a)
    rng = np.random.default_rng(seed)
    if groups is None:
        idx = rng.integers(0, a.size, size=(n_resamples, a.size))
        deltas = diff[idx].mean(axis=1)
        unit, n_units = "case", a.size
    else:
        _, inv = np.unique(np.asarray(groups), return_inverse=True)
        sums, sizes = np.bincount(inv, weights=diff), np.bincount(inv)
        picks = rng.integers(0, sizes.size, size=(n_resamples, sizes.size))
        deltas = sums[picks].sum(axis=1) / sizes[picks].sum(axis=1)
        unit, n_units = "group", int(sizes.size)
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    out = {
        "metric": metric,
        "delta": float(diff.mean()),
        "ci95": [float(lo), float(hi)],
        "n": int(a.size),
        "resample_unit": unit,
        "n_units": n_units,
    }
    if level is not None:
        tail = 100 * (1 - level) / 2
        out["ci_level"] = level
        out["ci"] = [float(x) for x in np.percentile(deltas, [tail, 100 - tail])]
    return out


def bootstrap_ci(
    ranks: Sequence[float], metric: str = "mrr", groups: Sequence[str] | None = None, seed: int = 0
) -> list[float]:
    """CI of one system's metric; same resampling rules as paired_bootstrap."""
    r = np.asarray(ranks, dtype=float)
    out = paired_bootstrap(np.full_like(r, np.inf), r, metric, seed=seed, groups=groups)
    return out["ci95"]


def harmed_helped(base: Sequence[float], new: Sequence[float]) -> dict:
    a, b = np.asarray(base, dtype=float), np.asarray(new, dtype=float)
    return {"harmed": float(np.mean(b > a)), "helped": float(np.mean(b < a))}
