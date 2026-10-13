"""sim4's sampler: one simulated patient's present HPO terms for a gene of E0's output index.

Every case is an antichain of findings (no term together with one of its ancestors), drawn only from the
phenotypic-abnormality subtree, and never contains a negation.
"""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from diagnostic_ar_training.sim4.config import (
    CATEGORIES,
    E0_COUNT_HISTOGRAM,
    E0_DISTANCE_HISTOGRAM,
    PRESETS,
    SimConfig,
    e0_category_shares,
)
from diagnostic_ar_training.sim4.fit import AD, AR, XL, XLR, FittedParams, budget_scale
from diagnostic_ar_training.sim4.knowledge import DASH, Knowledge
from diagnostic_ar_training.sim4.moves import RelatedTerms, generalize, related_noise_term, specialize

Y_LINKED = "HP:0001450"
E0_MAX_ATTEMPTS = 10


# Provenance: copied from rare-disease-simulator, src/rare_disease_simulator/simulation/simulator.py
# (budget_scaled_probabilities, line 1257), commit d7185bc64f61b5277bd92a6a8f066cada46b8fd2. Kept as the
# reference for `fit.budget_scale`, the exact sort-based solver the sampler uses.
def budget_scaled_probabilities(q: Sequence[float], target: int) -> tuple[list[float], float]:
    """Report probabilities ``min(1, c * q)`` whose sum is ``target``, and the factor ``c``.

    ``c`` is found by bisection to within 1e-6 of ``target``. Terms with q = 0
    stay at 0, so the target is cut to the number of terms with q > 0; when
    every q is 0, the terms are treated as equally likely.
    """

    if not any(value > 0.0 for value in q):
        q = [1.0] * len(q)
    positive = [value for value in q if value > 0.0]
    target = min(target, len(positive))

    def total(c: float) -> float:
        return sum(min(1.0, c * value) for value in q)

    low, high = 0.0, 1.0 / min(positive)
    if total(high) - target <= 1e-6:
        scale = high
    else:
        scale = high
        for _ in range(200):
            scale = (low + high) / 2.0
            reached = total(scale)
            if abs(reached - target) <= 1e-6:
                break
            if reached < target:
                low = scale
            else:
                high = scale
    return [min(1.0, scale * value) for value in q], scale


@dataclass(frozen=True)
class SimulatedCase:
    gene: str
    terms: tuple[str, ...]
    entity: str
    sex: str | None = None
    onset_term: str | None = None


class _Gene:
    """Per-gene arrays, built on first use."""

    def __init__(self, kb: Knowledge, gene: str, gamma: float, f0: float, group_weight: float) -> None:
        self.name = gene
        self.entities = kb.entities[gene]
        w = np.asarray(kb.entity_weights(gene, group_weight), dtype=float)
        self.entity_p = w / w.sum()
        self.q = [
            np.asarray([(f0 if f is None else f) ** gamma for f in e.frequencies], dtype=float)
            for e in self.entities
        ]
        self.profile = kb.profile(gene)
        self.profile_ancestors = frozenset().union(*(kb.ontology.ancestors(t) for t in self.profile))
        self.log_size = float(np.log(len(self.profile)))
        self._e0_pools: list[tuple[str, ...]] | None = None


class Sampler:
    def __init__(
        self, knowledge: Knowledge, params: FittedParams | None = None, config: SimConfig | None = None
    ):
        self.kb = knowledge
        self.config = config or PRESETS["real_noise"]
        self.params = params or FittedParams()
        cfg, p = self.config, self.params
        self.genes = knowledge.genes
        self.n_genes = len(self.genes)
        self.simulable_gene_indices = tuple(knowledge.gene_index[g] for g in knowledge.simulable_genes)
        if cfg.frequency == "uniform":
            self.gamma, self.f0 = 0.0, p.f0
        elif cfg.frequency == "proportional":
            self.gamma, self.f0 = 1.0, p.f0
        else:
            self.gamma, self.f0 = p.gamma, p.f0
        if cfg.counts == "e0":
            values = sorted(E0_COUNT_HISTOGRAM)
            self._count_lo = self._count_hi = np.asarray(values)
            self._count_p = np.asarray([E0_COUNT_HISTOGRAM[v] for v in values], dtype=float)
        else:
            bins = p.count_bins if cfg.count_slope or not p.count_bins_flat else p.count_bins_flat
            self._count_lo = np.asarray([b[0] for b in bins])
            self._count_hi = np.asarray([b[1] for b in bins])
            self._count_p = np.asarray([b[2] for b in bins], dtype=float)
        self._count_p = self._count_p / self._count_p.sum()
        self._slope = p.count_slope if cfg.counts == "fitted" and cfg.count_slope else 0.0
        shares = e0_category_shares() if cfg.categories == "e0" else p.category_shares
        self._cat_p = np.asarray([shares[c] for c in CATEGORIES], dtype=float)
        self._cat_p = self._cat_p / self._cat_p.sum()
        d_values = sorted(E0_DISTANCE_HISTOGRAM)
        self._e0_d = np.asarray(d_values)
        self._e0_d_p = np.asarray([E0_DISTANCE_HISTOGRAM[d] for d in d_values], dtype=float)
        self._e0_d_p /= self._e0_d_p.sum()
        vocab = sorted(p.off_vocabulary.items()) if cfg.off_profile in ("pooled", "mix") else []
        self._vocab = [t for t, _ in vocab]
        self._vocab_cum = np.cumsum([w for _, w in vocab]) if vocab else np.zeros(0)
        if cfg.off_profile in ("pooled", "mix") and not vocab:
            raise ValueError(
                f"{cfg.name}: off_profile={cfg.off_profile} needs a fitted off-profile vocabulary"
            )
        self._genes: dict[str, _Gene] = {}

    def _gene(self, gene_index: int) -> _Gene:
        gene = self.genes[gene_index]
        if gene == DASH or not self.kb.entities.get(gene):
            raise ValueError(f"gene index {gene_index} ({gene!r}) is not simulable")
        if gene not in self._genes:
            self._genes[gene] = _Gene(self.kb, gene, self.gamma, self.f0, self.config.group_weight)
        return self._genes[gene]

    def sample(self, gene_index: int, rng: np.random.Generator) -> list[str]:
        return list(self.sample_case(gene_index, rng).terms)

    def sample_case(self, gene_index: int, rng: np.random.Generator) -> SimulatedCase:
        g = self._gene(gene_index)
        gene = self.genes[gene_index]
        if self.config.recipe == "e0":
            return SimulatedCase(gene, tuple(sorted(self._e0_case(g, rng))), "gene")
        e = int(rng.choice(len(g.entities), p=g.entity_p))
        terms = self._disease_case(g, e, rng)
        sex = onset = None
        if self.config.covariates:
            sex, onset = self._covariates(gene, g.entities[e], rng)
        return SimulatedCase(gene, tuple(sorted(terms)), g.entities[e].id, sex, onset)

    # --- E0's recipe (GraPhens@7aef83d SIM/selector.py), plus sim4's hard rules --------------------------

    def _e0_pools(self, g: _Gene) -> list[tuple[str, ...]]:
        if g._e0_pools is None:
            rows = self.kb.e0_rows[g.name]
            pools, seen, level = [rows], set(rows), sorted(set(rows))
            while level:
                nxt = sorted(
                    {
                        p
                        for t in level
                        for p in self.kb.ontology.parents(t)
                        if p not in seen and self.kb.is_finding(p)
                    }
                )
                seen.update(nxt)
                if nxt:
                    pools.append(tuple(nxt))
                level = nxt
            g._e0_pools = pools
        return g._e0_pools

    def _e0_case(self, g: _Gene, rng: np.random.Generator) -> list[str]:
        pools = self._e0_pools(g)
        k = int(rng.choice(self._count_lo, p=self._count_p))
        case = RelatedTerms(self.kb)
        for d in rng.choice(self._e0_d, size=k, p=self._e0_d_p):
            candidates = self._e0_candidates(pools, int(d), case)
            attempts = 0
            while not candidates and attempts < E0_MAX_ATTEMPTS:
                attempts += 1
                alt = int(d) + (1 if attempts % 2 else -1) * (attempts // 2 + 1)
                candidates = self._e0_candidates(pools, alt, case)
            if candidates:
                case.add(candidates[int(rng.integers(len(candidates)))])
        return case.terms

    @staticmethod
    def _e0_candidates(pools, d: int, case: RelatedTerms) -> list[str]:
        if d < 0 or d >= len(pools):
            return []
        return [t for t in pools[d] if case.fits(t)]

    # --- Disease recipe -------------------------------------------------------------------------------

    def _count(self, g: _Gene, rng: np.random.Generator) -> int:
        b = int(rng.choice(len(self._count_p), p=self._count_p))
        k = int(rng.integers(self._count_lo[b], self._count_hi[b] + 1))
        if self._slope:
            k = int(np.rint(k * np.exp(self._slope * (g.log_size - self.params.log_size_mean))))
        return max(1, k)

    def _disease_case(self, g: _Gene, e: int, rng: np.random.Generator) -> list[str]:
        cfg = self.config
        terms, q = g.entities[e].terms, g.q[e]
        k = self._count(g, rng)
        k_off = 0
        if cfg.off_profile != "none":
            share = rng.beta(self.params.off_alpha, self.params.off_beta)
            k_off = int(rng.binomial(k, share))
        k_on = k - k_off
        case = RelatedTerms(self.kb)

        target = min(k_on, len(terms))
        bases: list[str] = []
        if target:
            pi = budget_scale(q, target)
            picked = np.flatnonzero(rng.random(len(terms)) < pi)
            if len(picked) > target:
                picked = rng.choice(picked, size=target, replace=False)
            elif len(picked) < target:
                rest = np.setdiff1d(np.arange(len(terms)), picked)
                keys = np.log(rng.random(len(rest))) / pi[rest]
                picked = np.r_[picked, rest[np.argsort(-keys)[: target - len(picked)]]]
            bases = [terms[i] for i in picked]
            cats = rng.choice(len(CATEGORIES), size=len(picked), p=self._cat_p)
            for i, c in zip(rng.permutation(picked), cats, strict=True):
                if (t := self._derive(terms[i], CATEGORIES[c], g, case, rng)) is not None:
                    case.add(t)

        q_p = q / q.sum()
        tries = 0
        while len(case.terms) < k_on and tries < cfg.max_tries * k_on:
            tries += 1
            base = terms[int(rng.choice(len(terms), p=q_p))]
            cat = CATEGORIES[int(rng.choice(len(CATEGORIES), p=self._cat_p))]
            if (t := self._derive(base, cat, g, case, rng)) is not None:
                case.add(t)

        for _ in range(k_off):
            for _ in range(cfg.max_tries):
                t = self._off_term(g, e, bases, case, rng)
                if t is not None and case.fits(t):
                    case.add(t)
                    break
        return case.terms

    def _derive(self, base: str, cat: str, g: _Gene, case: RelatedTerms, rng) -> str | None:
        """The term a base annotation is reported as: itself, an ancestor d steps up, or a descendant d steps
        down that is neither annotated nor an ancestor of an annotation; a term that cannot move in that
        direction is reported as itself."""
        if cat == "exact":
            moved = base
        elif cat.startswith("anc"):
            moved = generalize(self.kb, base, int(cat[-1]), rng)
        else:
            blocked = g.profile | g.profile_ancestors
            moved = specialize(self.kb, base, int(cat[-1]), rng, blocked) or base
        return moved if case.fits(moved) else None

    def _is_off(self, term: str, g: _Gene) -> bool:
        return (
            term not in g.profile
            and term not in g.profile_ancestors
            and g.profile.isdisjoint(self.kb.ontology.ancestors(term))
        )

    def _off_term(self, g: _Gene, e: int, bases: list[str], case: RelatedTerms, rng) -> str | None:
        mode = self.config.off_profile
        if mode == "mix":
            mode = "pooled" if rng.random() < self.config.off_mix else "neighbourhood"
        if mode == "pooled":
            t = self._vocab[
                int(np.searchsorted(self._vocab_cum, rng.random() * self._vocab_cum[-1], side="right"))
            ]
            return t if self._is_off(t, g) else None
        seeds = bases or list(g.entities[e].terms)
        return related_noise_term(self.kb, seeds, rng, g.profile, g.profile_ancestors, case)

    # --- Covariates (low priority; behind SimConfig.covariates) ---------------------------------------

    def _covariates(self, gene: str, entity, rng) -> tuple[str, str | None]:
        if entity.kind == "nodisease":
            modes = frozenset().union(
                *(self.kb.inheritance.get(e.id, frozenset()) for e in self.kb.entities[gene])
            )
        else:
            modes = self.kb.inheritance.get(entity.id, frozenset())
        if Y_LINKED in modes and not modes & {AD, AR, XL, XLR}:
            male = 1.0
        elif modes & {XL, XLR} and not modes & {AD, AR}:
            male = self.params.xlr_male_share
        else:
            male = 0.5
        sex = "male" if rng.random() < male else "female"
        onsets = self.kb.onsets.get(entity.id, ())
        onset = onsets[int(rng.integers(len(onsets)))] if onsets else None
        return sex, onset
