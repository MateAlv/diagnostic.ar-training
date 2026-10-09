"""EXP-P-007's leave-genes-out standards test (docs/experiments/EXP-P-007.md), numpy only.

- `choose_genes`: the relearned set, by the rule registered before any run.
- `Relearned`: E0 (production ONNX logits) with the relearned genes' logits replaced by new rows applied to
  v3.0's pooled vector. Every other gene keeps E0's logit bit for bit.
- `report`: (a) the patients whose gene was relearned, relearned rows vs E0's rows (MRR ratio with a
  publication-cluster bootstrap CI, Δ MRR with its CI, top-1 and top-10); (b) every other patient, Δ MRR vs
  E0.
- `criterion`, `CONFIGS`, `select`: the pass rule and the train-only configuration choice.
"""

import random
from collections.abc import Callable, Iterable, Mapping, Sequence

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import metrics
from diagnostic_ar_training.eval.safe_eval import contrast
from diagnostic_ar_training.ft.bundle import softmax64
from diagnostic_ar_training.systems import Scored

EXP = "EXP-P-007"
MAX_GENES = 200
GENE_SEED = 20261008
MIN_RATIO = 0.90
MIN_OTHERS_DELTA = -0.001
RATIO_TIE = 0.01
SEEDS = (0, 1, 2)
N_RESAMPLES = 2000

# At most 6 configurations (EXP-P-007): pseudo-patients per relearned gene, replay pseudo-patients per other
# gene, Adam learning rate. Everything else is `rows.RowConfig`'s default.
CONFIGS: dict[str, dict] = {
    "c1-n128-r8": {"new_per_gene": 128, "replay_per_gene": 8, "lr": 0.01},
    "c2-n512-r32": {"new_per_gene": 512, "replay_per_gene": 32, "lr": 0.01},
    "c3-n512-r128": {"new_per_gene": 512, "replay_per_gene": 128, "lr": 0.01},
    "c4-n512-r128-lr3e-3": {"new_per_gene": 512, "replay_per_gene": 128, "lr": 0.003},
    "c5-n2048-r128": {"new_per_gene": 2048, "replay_per_gene": 128, "lr": 0.01},
    "c6-n512-r256": {"new_per_gene": 512, "replay_per_gene": 256, "lr": 0.01},
}


def config(name: str) -> dict:
    if name not in CONFIGS:
        raise ValueError(f"unknown configuration {name!r}; one of {sorted(CONFIGS)}")
    return dict(CONFIGS[name])


def choose_genes(
    cases: Iterable[Case],
    vocabulary: Sequence[str],
    has_profile: Callable[[str], bool],
    max_genes: int = MAX_GENES,
    seed: int = GENE_SEED,
) -> tuple[list[str], dict]:
    """(relearned genes in vocabulary order, counts).

    Eligible: a vocabulary gene with at least one of the cases and a non-empty masked profile (a row cannot be
    learned from no annotation). All of them when there are at most `max_genes`, else a seeded sample.
    """
    by_upper = {g.upper(): g for g in vocabulary}
    with_cases = {c.gene.upper() for c in cases}
    in_vocab = sorted(g for g in with_cases if g in by_upper)
    eligible = [g for g in in_vocab if has_profile(by_upper[g])]
    chosen = eligible if len(eligible) <= max_genes else random.Random(seed).sample(eligible, max_genes)
    chosen = set(chosen)
    order = [g for g in vocabulary if g.upper() in chosen]
    counts = {
        "genes_with_cases": len(with_cases),
        "in_vocabulary": len(in_vocab),
        "eligible_with_profile": len(eligible),
        "excluded_no_profile": sorted(by_upper[g] for g in in_vocab if not has_profile(by_upper[g])),
        "chosen": len(order),
        "max_genes": max_genes,
        "seed": seed,
    }
    return order, counts


class Relearned:
    """E0's logits with the relearned genes' entries replaced by weight @ pooled + bias."""

    def __init__(
        self,
        e0,
        index: Sequence[int],
        weight: np.ndarray,
        bias: np.ndarray,
        pooled: Mapping[str, np.ndarray],
        name: str = "relearned",
    ) -> None:
        if len(index) != len(weight) or len(index) != len(bias):
            raise ValueError("one row per relearned index")
        self.e0, self.genes, self.name = e0, e0.genes, name
        self.index = np.asarray(index, dtype=np.int64)
        self.weight = np.asarray(weight, dtype=np.float64)
        self.bias = np.asarray(bias, dtype=np.float64)
        self.pooled = pooled

    def lineage_inputs(self) -> list[dict]:
        return self.e0.lineage_inputs()

    def logits(self, case: Case) -> tuple[np.ndarray | None, dict]:
        logits, info = self.e0(case)
        if logits is None:
            return None, info
        out = np.asarray(logits, dtype=np.float64).copy()
        out[self.index] = self.weight @ np.asarray(self.pooled[case.case_id], dtype=np.float64) + self.bias
        return out, info

    def score(self, case: Case) -> Scored:
        logits, info = self.logits(case)
        return Scored(None if logits is None else softmax64(logits), info)


def ratio_bootstrap(
    base: Sequence[float],
    new: Sequence[float],
    groups: Sequence[str],
    n_resamples: int = N_RESAMPLES,
    seed: int = 0,
) -> dict:
    """MRR(new) / MRR(base) on the same cases, with a percentile 95% CI over resampled publication groups."""
    a, b = 1.0 / np.asarray(base, dtype=float), 1.0 / np.asarray(new, dtype=float)
    if a.shape != b.shape or a.size != len(groups):
        raise ValueError("ratio bootstrap needs the same cases in the same order, with their groups")
    _, inv = np.unique(np.asarray(groups), return_inverse=True)
    sa, sb = np.bincount(inv, weights=a), np.bincount(inv, weights=b)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, sa.size, size=(n_resamples, sa.size))
    num, den = sb[picks].sum(axis=1), sa[picks].sum(axis=1)
    ratios = np.divide(num, den, out=np.full(n_resamples, np.nan), where=den > 0)
    lo, hi = np.nanpercentile(ratios, [2.5, 97.5])
    return {
        "ratio": float(b.sum() / a.sum()) if a.sum() > 0 else float("nan"),
        "ci95": [float(lo), float(hi)],
        "n": int(a.size),
        "n_units": int(sa.size),
        "resample_unit": "group",
        "n_resamples": n_resamples,
        "seed": seed,
    }


def _subset(records: list[dict], keep: set[str]) -> list[dict]:
    return [r for r in records if r["case_id"] in keep]


def _summary(records: list[dict]) -> dict:
    s = metrics.summarize([r["rank"] for r in records]) if records else {"n": 0}
    return {k: s[k] for k in ("n", "mrr", "top1", "top10") if k in s}


def block(e0: list[dict], new: list[dict]) -> dict:
    """E0 vs new on one subset: both summaries, the paired contrast, and the MRR ratio."""
    out = {"e0": _summary(e0), "new": _summary(new), "vs_e0": contrast(e0, new)}
    if e0:
        out["ratio"] = ratio_bootstrap(
            [r["rank"] for r in e0], [r["rank"] for r in new], [r["group"] for r in e0]
        )
    return out


def report(
    e0: list[dict],
    new: list[dict],
    relearned: Iterable[str],
    extra: Mapping[str, set[str]] | None = None,
) -> dict:
    """(a) patients whose gene is relearned; (b) every other patient. `extra` subsets are reported in (a)."""
    genes = {g.upper() for g in relearned}
    if [r["case_id"] for r in e0] != [r["case_id"] for r in new]:
        raise ValueError("records must cover the same cases in the same order")
    a_ids = {r["case_id"] for r in e0 if r["gene"].upper() in genes}
    b_ids = {r["case_id"] for r in e0} - a_ids
    out = {
        "relearned": block(_subset(e0, a_ids), _subset(new, a_ids)),
        "others": block(_subset(e0, b_ids), _subset(new, b_ids)),
        "all": block(e0, new),
        "relearned_subsets": {},
    }
    for name, keep in (extra or {}).items():
        ids = a_ids & keep
        out["relearned_subsets"][name] = block(_subset(e0, ids), _subset(new, ids))
    out["criterion"] = criterion(out)
    return out


def criterion(rep: Mapping) -> dict:
    """PASS: (a) MRR ratio ≥ 0.90 (point estimate) and (b) Δ MRR ≥ −0.001 (point estimate)."""
    ratio = rep["relearned"]["ratio"]["ratio"]
    delta = rep["others"]["vs_e0"]["delta"]
    a_ok, b_ok = bool(ratio >= MIN_RATIO), bool(delta >= MIN_OTHERS_DELTA)
    return {
        "relearned_ratio": ratio,
        "min_ratio": MIN_RATIO,
        "others_delta": delta,
        "min_others_delta": MIN_OTHERS_DELTA,
        "a_met": a_ok,
        "b_met": b_ok,
        "pass": a_ok and b_ok,
    }


def per_gene(e0: list[dict], new: list[dict], relearned: Iterable[str]) -> list[dict]:
    """Per relearned gene with patients: n, E0 MRR, relearned MRR."""
    genes = {g.upper() for g in relearned}
    rows: dict[str, dict] = {}
    for a, b in zip(e0, new, strict=True):
        g = a["gene"].upper()
        if g not in genes:
            continue
        r = rows.setdefault(g, {"gene": a["gene"], "n": 0, "e0_rr": 0.0, "new_rr": 0.0})
        r["n"] += 1
        r["e0_rr"] += 1.0 / a["rank"]
        r["new_rr"] += 1.0 / b["rank"]
    out = []
    for r in rows.values():
        out.append(
            {"gene": r["gene"], "n": r["n"], "e0_mrr": r["e0_rr"] / r["n"], "new_mrr": r["new_rr"] / r["n"]}
        )
    return sorted(out, key=lambda r: r["gene"])


def select(rows: Sequence[Mapping], seeds: Sequence[int] = SEEDS) -> dict:
    """EXP-P-007's configuration rule, on train only.

    `rows`: one per (configuration, seed) with `config`, `seed`, `ratio` (inner held-out train groups, (a))
    and `others_delta` (train, (b)).
    1. Feasible: every seed ran and the seed-mean (b) Δ ≥ −0.001.
    2. The highest seed-mean (a) ratio; a configuration within 0.01 of it with fewer pseudo-patients per gene
       (new + replay) is preferred, then the lower learning rate.
    3. If none is feasible, the highest seed-mean (b) Δ.
    """
    by: dict[str, list[Mapping]] = {}
    for r in rows:
        by.setdefault(r["config"], []).append(r)
    agg = {}
    for name, rs in by.items():
        if sorted(r["seed"] for r in rs) != sorted(seeds):
            continue
        agg[name] = {
            "ratio": float(np.mean([r["ratio"] for r in rs])),
            "ratio_sd": float(np.std([r["ratio"] for r in rs], ddof=1)) if len(rs) > 1 else None,
            "others_delta": float(np.mean([r["others_delta"] for r in rs])),
            "others_delta_sd": float(np.std([r["others_delta"] for r in rs], ddof=1))
            if len(rs) > 1
            else None,
        }
    if not agg:
        return {"selected": None, "why": "no configuration ran every seed", "by_config": {}}
    feasible = {n: a for n, a in agg.items() if a["others_delta"] >= MIN_OTHERS_DELTA}
    if not feasible:
        chosen = max(agg, key=lambda n: agg[n]["others_delta"])
        return {"selected": chosen, "feasible": [], "why": "none feasible: highest (b) Δ", "by_config": agg}
    best = max(a["ratio"] for a in feasible.values())
    close = [n for n, a in feasible.items() if a["ratio"] >= best - RATIO_TIE]

    def cost(n: str) -> tuple:
        c = CONFIGS[n]
        return (c["new_per_gene"] + c["replay_per_gene"], c["lr"], -feasible[n]["ratio"])

    chosen = min(close, key=cost)
    return {
        "selected": chosen,
        "feasible": sorted(feasible),
        "best_ratio": best,
        "within_tie": sorted(close),
        "by_config": agg,
    }
