"""Global, low-dimensional statistics of real training patients for sim4 (ADR-0019 §5).

Nothing here is per gene or per term: the frequency exponent and default frequency, a term-count
histogram with one slope on log(profile size), nine category shares, a Beta of the off-profile share,
the male share of X-linked recessive patients, and one pooled, gene-agnostic off-profile vocabulary.
Every patient is weighted 1 / (patients of its publication group). Excluded terms are never read.
"""

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.lineage.hashing import sha256_json
from diagnostic_ar_training.sim4.config import CATEGORIES, MAX_DISTANCE
from diagnostic_ar_training.sim4.knowledge import Knowledge

COUNT_BINS = (*((k, k) for k in range(1, 21)), (21, 25), (26, 30), (31, 40), (41, 60), (61, 100))
VOCAB_MIN_PUBLICATIONS = 3
UNCITED = "uncited_e0_knowledge"
XLR, XL, AD, AR = "HP:0001419", "HP:0001417", "HP:0000006", "HP:0000007"
LIKELIHOOD_EPS = 1e-3


@dataclass
class FittedParams:
    gamma: float = 1.0
    f0: float = 0.5
    count_bins: list = field(
        default_factory=lambda: [[lo, hi, 1.0 / len(COUNT_BINS)] for lo, hi in COUNT_BINS]
    )
    count_slope: float = 0.0
    log_size_mean: float = 0.0
    count_bins_flat: list = field(default_factory=list)
    """The histogram of raw term counts, used when the sampler does not scale with profile size."""
    category_shares: dict = field(default_factory=lambda: {c: float(c == "exact") for c in CATEGORIES})
    off_alpha: float = 1.0
    off_beta: float = 9.0
    off_vocabulary: dict = field(default_factory=dict)
    xlr_male_share: float = 0.9
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FittedParams":
        return cls(**d)

    def params_hash(self) -> str:
        return sha256_json(self.to_dict())

    def n_parameters(self) -> dict:
        return {
            "scalars": 2 + 2 + 2 + 1,
            "count_histogram_bins": len(self.count_bins),
            "category_shares": len(self.category_shares),
            "vocabulary_terms": len(self.off_vocabulary),
        }

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: Path) -> "FittedParams":
        return cls.from_dict(json.loads(Path(path).read_text()))


def budget_scale(q: np.ndarray, target: float) -> np.ndarray:
    """min(1, c * q) summing to `target` (cut to the number of q > 0), solved exactly by sorting.

    Same result as `budget_scaled_probabilities` (sampler.py), without the bisection.
    """
    q = np.asarray(q, dtype=float)
    out = np.zeros_like(q)
    pos = np.flatnonzero(q > 0)
    if not len(pos):
        return out
    target = min(float(target), len(pos))
    if target <= 0:
        return out
    s = np.sort(q[pos])[::-1]
    tail = np.cumsum(s[::-1])[::-1]
    j = np.arange(len(s))
    c = (target - j) / tail
    prev = np.r_[np.inf, s[:-1]]
    ok = (c * s <= 1 + 1e-12) & (c * prev >= 1 - 1e-12)
    scale = c[np.argmax(ok)]
    out[pos] = np.minimum(1.0, scale * q[pos])
    return out


class Profiler:
    """Prepares a patient's terms and places each one relative to its gene's annotated profile."""

    def __init__(self, kb: Knowledge) -> None:
        self.kb = kb
        self._anc: dict[str, dict[str, int]] = {}

    def prepare(self, present) -> tuple[str, ...]:
        """Mapped to HPO 2025-03-03, findings only, deduplicated, ancestors of other terms dropped."""
        terms = {r for t in present if (r := self.kb.ontology.resolve(t)) and self.kb.is_finding(r)}
        covered = set()
        for t in terms:
            covered |= self.kb.ontology.ancestors(t)
        return tuple(sorted(terms - covered))

    def ancestor_distance(self, gene: str) -> dict[str, int]:
        """Every finding ancestor of the profile -> shortest distance from a profile term."""
        if gene not in self._anc:
            profile = self.kb.profile(gene)
            dist: dict[str, int] = {}
            frontier, d, seen = set(profile), 0, set(profile)
            while frontier:
                d += 1
                nxt = {
                    p
                    for t in frontier
                    for p in self.kb.ontology.parents(t)
                    if p not in seen and self.kb.is_finding(p)
                }
                seen |= nxt
                for p in nxt:
                    dist[p] = d
                frontier = nxt
            self._anc[gene] = {t: v for t, v in dist.items() if t not in profile}
        return self._anc[gene]

    def place(self, gene: str, term: str) -> tuple[str, frozenset[str]]:
        """(category or "off", the profile terms it descends from at the shortest depth)."""
        profile = self.kb.profile(gene)
        if term in profile:
            return "exact", frozenset({term})
        anc = self.ancestor_distance(gene)
        if term in anc:
            return f"anc{min(anc[term], MAX_DISTANCE)}", frozenset()
        for d, level in enumerate(self.kb.up_levels(term), 1):
            hit = profile.intersection(level)
            if hit:
                return f"desc{min(d, MAX_DISTANCE)}", frozenset(hit)
        return "off", frozenset()

    def explained_share(self, gene: str, terms) -> float:
        """P3-AUDIT-v1's explained share: terms in the profile or ancestors of it."""
        if not terms:
            return float("nan")
        profile, anc = self.kb.profile(gene), self.ancestor_distance(gene)
        return sum(t in profile or t in anc for t in terms) / len(terms)


@dataclass
class _Prepared:
    case: Case
    group: str
    weight: float
    terms: tuple[str, ...]
    categories: list[str]
    hits: frozenset[str]


def _publication_weights(groups: list[str]) -> list[float]:
    n = Counter(groups)
    return [1.0 / n[g] for g in groups]


def _entities_for(kb: Knowledge, case: Case, group_weight: float):
    ents = kb.entities[case.gene]
    weights = kb.entity_weights(case.gene, group_weight)
    own = [i for i, e in enumerate(ents) if e.id in set(case.disease_ids)]
    if own:
        return [ents[i] for i in own], [1.0] * len(own)
    return list(ents), weights


def _frequency_loglik(kb: Knowledge, prepared: list[_Prepared], group_weight: float):
    """Composite Bernoulli log-likelihood of which profile terms a patient reports (exactly or by a
    descendant), under sim4's own budget-scaled inclusion probabilities, as a function of (gamma, f0)."""
    blocks = []
    for p in prepared:
        if not p.hits:
            continue
        ents, w = _entities_for(kb, p.case, group_weight)
        profile = sorted({t for e in ents for t in e.terms})
        index = {t: i for i, t in enumerate(profile)}
        w = np.asarray(w) / sum(w)
        parts = [
            (
                wi,
                np.asarray([index[t] for t in e.terms]),
                np.asarray([np.nan if f is None else f for f in e.frequencies]),
            )
            for wi, e in zip(w, ents, strict=True)
        ]
        hit = np.zeros(len(profile), dtype=bool)
        hit[[index[t] for t in p.hits if t in index]] = True
        if hit.any():
            blocks.append((p.weight, parts, len(profile), hit, int(hit.sum())))

    def loglik(gamma: float, f0: float) -> float:
        total = 0.0
        for weight, parts, n, hit, k in blocks:
            pi = np.zeros(n)
            for wi, idx, f in parts:
                q = np.where(np.isnan(f), f0, f) ** gamma
                pi[idx] += wi * budget_scale(q, k)
            pi = np.clip(pi, LIKELIHOOD_EPS, 1 - LIKELIHOOD_EPS)
            total += weight * (np.log(pi[hit]).sum() + np.log1p(-pi[~hit]).sum())
        return total

    return loglik, len(blocks)


def _fit_frequency(loglik) -> dict:
    from scipy.optimize import minimize

    grid = [(g, f) for g in np.arange(0.0, 3.01, 0.25) for f in (0.05, 0.1, 0.2, 0.35, 0.5, 0.7, 0.9)]
    scores = {(float(g), f): loglik(g, f) for g, f in grid}
    g0, f0 = max(scores, key=scores.get)
    res = minimize(
        lambda x: -loglik(x[0], x[1]),
        x0=[g0, f0],
        method="L-BFGS-B",
        bounds=[(0.0, 4.0), (0.01, 1.0)],
        options={"eps": 1e-3},
    )
    gamma, f = (float(v) for v in res.x)
    return {
        "gamma": gamma,
        "f0": f,
        "loglik": float(-res.fun),
        "loglik_uniform": scores[(0.0, 0.5)],
        "loglik_proportional_f0_0.5": scores[(1.0, 0.5)],
    }


def _beta_binomial_fit(ks: np.ndarray, xs: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    from scipy.optimize import minimize
    from scipy.special import betaln

    def nll(theta):
        a, b = np.exp(theta)
        return -float(np.sum(w * (betaln(xs + a, ks - xs + b) - betaln(a, b))))

    m = float(np.sum(w * xs / ks) / np.sum(w))
    m = min(max(m, 1e-3), 1 - 1e-3)
    res = minimize(nll, x0=np.log([m * 2, (1 - m) * 2]), method="Nelder-Mead")
    a, b = np.exp(res.x)
    return float(a), float(b)


def _count_fit(ks: np.ndarray, sizes: np.ndarray, w: np.ndarray, slope: bool) -> tuple[list, float, float]:
    x, y = np.log(sizes), np.log(ks)
    m = float(np.sum(w * x) / np.sum(w))
    b = 0.0
    if slope:
        ybar = np.sum(w * y) / np.sum(w)
        b = float(np.sum(w * (x - m) * (y - ybar)) / np.sum(w * (x - m) ** 2))
    k0 = np.maximum(1, np.rint(ks * np.exp(-b * (x - m)))).astype(int)
    hist = []
    for lo, hi in COUNT_BINS:
        upper = np.inf if hi == COUNT_BINS[-1][1] else hi
        hist.append([lo, hi, float(np.sum(w[(k0 >= lo) & (k0 <= upper)]))])
    total = sum(h[2] for h in hist)
    return [[lo, hi, v / total] for lo, hi, v in hist], b, m


def _xlr_only(kb: Knowledge, gene: str) -> bool:
    modes = set()
    for e in kb.entities.get(gene, ()):
        if e.kind == "disease":
            modes |= kb.inheritance.get(e.id, frozenset())
    return bool(modes & {XLR, XL}) and not modes & {AD, AR}


def data_hash(cases: list[Case]) -> str:
    return sha256_json(sorted([c.case_id, c.gene, sorted(c.present)] for c in cases))


def fit(
    cases: list[Case],
    kb: Knowledge,
    *,
    groups: dict[str, str] | None = None,
    group_status: dict[str, str] | None = None,
    uncited_only: bool = True,
    count_slope: bool = True,
    group_weight: float = 0.2,
    label: str = "",
) -> FittedParams:
    """Fit sim4's global statistics on the caller's fitting folds (never the evaluation fold)."""
    if groups is None or (uncited_only and group_status is None):
        from diagnostic_ar_training import splits
        from diagnostic_ar_training.sim4 import folds

        groups = groups or folds.train_groups()
        group_status = group_status or splits.load_frozen(folds.SPLIT)["group_status"]
    used = [c for c in cases if not uncited_only or group_status[groups[c.case_id]] == UNCITED]
    profiler = Profiler(kb)
    simulable = set(kb.simulable_genes)
    sim_cases = []
    for c in used:
        terms = profiler.prepare(c.present)
        if c.gene in simulable and terms:
            sim_cases.append((c, terms))
    weights = _publication_weights([groups[c.case_id] for c, _ in sim_cases])
    prepared = []
    for (c, terms), w in zip(sim_cases, weights, strict=True):
        placed = [profiler.place(c.gene, t) for t in terms]
        hits = frozenset().union(*(h for _, h in placed))
        prepared.append(_Prepared(c, groups[c.case_id], w, terms, [cat for cat, _ in placed], hits))
    if not prepared:
        raise ValueError("no fitting case with a simulable gene and a finding")

    w = np.asarray([p.weight for p in prepared])
    ks = np.asarray([len(p.terms) for p in prepared], dtype=float)
    sizes = np.asarray([len(kb.profile(p.case.gene)) for p in prepared], dtype=float)
    bins, slope, log_mean = _count_fit(ks, sizes, w, count_slope)
    flat, _, _ = _count_fit(ks, sizes, w, False)

    shares = dict.fromkeys(CATEGORIES, 0.0)
    off = np.zeros(len(prepared))
    for i, p in enumerate(prepared):
        for cat in p.categories:
            if cat == "off":
                off[i] += 1
            else:
                shares[cat] += p.weight
    total = sum(shares.values())
    shares = {k: v / total for k, v in shares.items()}
    alpha, beta = _beta_binomial_fit(ks, off, w)

    loglik, n_freq = _frequency_loglik(kb, prepared, group_weight)
    freq = _fit_frequency(loglik)

    by_group: dict[str, Counter] = defaultdict(Counter)
    group_n: Counter = Counter()
    for p in prepared:
        group_n[p.group] += 1
        by_group[p.group].update({t for t, cat in zip(p.terms, p.categories, strict=True) if cat == "off"})
    vocab: Counter = Counter()
    pubs: Counter = Counter()
    for g, counter in by_group.items():
        for t, n in counter.items():
            vocab[t] += n / group_n[g]
            pubs[t] += 1
    vocab = {t: v for t, v in vocab.items() if pubs[t] >= VOCAB_MIN_PUBLICATIONS}
    vtotal = sum(vocab.values())
    vocab = {t: vocab[t] / vtotal for t in sorted(vocab)}

    male = xlr = 0.0
    for c, wc in zip(used, _publication_weights([groups[c.case_id] for c in used]), strict=True):
        if c.sex in (Sex.MALE, Sex.FEMALE) and _xlr_only(kb, c.gene):
            xlr += wc
            male += wc * (c.sex == Sex.MALE)

    explained = [profiler.explained_share(p.case.gene, p.terms) for p in prepared]
    return FittedParams(
        gamma=freq["gamma"],
        f0=freq["f0"],
        count_bins=bins,
        count_slope=slope,
        log_size_mean=log_mean,
        count_bins_flat=flat,
        category_shares=shares,
        off_alpha=alpha,
        off_beta=beta,
        off_vocabulary=vocab,
        xlr_male_share=male / xlr if xlr else 0.9,
        meta={
            "label": label,
            "uncited_only": uncited_only,
            "cases_given": len(cases),
            "cases_used": len(used),
            "cases_simulable_with_findings": len(prepared),
            "publications": len({p.group for p in prepared}),
            "cases_in_frequency_fit": n_freq,
            "data_hash": data_hash(used),
            "knowledge_genes": len(kb.genes),
            "frequency_fit": freq,
            "mean_terms": float(np.sum(w * ks) / np.sum(w)),
            "mean_off_share": float(np.sum(w * off / ks) / np.sum(w)),
            "mean_explained_share": float(np.sum(w * np.asarray(explained)) / np.sum(w)),
            "xlr_patients_weight": xlr,
            "vocabulary_min_publications": VOCAB_MIN_PUBLICATIONS,
            "group_weight": group_weight,
            "likelihood_eps": LIKELIHOOD_EPS,
        },
    )
