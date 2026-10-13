"""How a reported term moves on the ontology: imprecision, over-specification and related noise.

Provenance: adapted from rare-disease-simulator, src/rare_disease_simulator/simulation/simulator.py, commit
cfc20da78df229a92c14d7f414c3451c91673444 (`_RelatedTerms`, `_maybe_generalize`, `_specialize`,
`_related_noise_term`). Changes for sim4: how far a term moves comes from the fitted category shares instead
of pilot-tuned rates (`ontology_smoothing_rate`, the 0.5 grandchild coin); a descendant step is weighted by
HPOA 2025-03-03 annotation counts instead of uniform; sex-specific terms, negatives and the IC cap are not
used; the ontology is this repo's `Ontology` restricted to findings (below HP:0000118).
"""

from collections.abc import Sequence

import numpy as np

from diagnostic_ar_training.sim4.knowledge import Knowledge


class RelatedTerms:
    """Terms plus their ancestors, to test "equal, ancestor or descendant" quickly; `terms` keeps the order
    terms were added, so a case built through `add` is an antichain."""

    def __init__(self, kb: Knowledge) -> None:
        self.kb = kb
        self.terms: list[str] = []
        self.ids: set[str] = set()
        self._ancestors: set[str] = set()

    def add(self, hpo_id: str) -> None:
        self.terms.append(hpo_id)
        self.ids.add(hpo_id)
        self._ancestors |= self.kb.ontology.ancestors(hpo_id)

    def related(self, hpo_id: str) -> bool:
        if hpo_id in self.ids or hpo_id in self._ancestors:
            return True
        return not self.kb.ontology.ancestors(hpo_id).isdisjoint(self.ids)

    def fits(self, hpo_id: str) -> bool:
        return not self.related(hpo_id)


def _weighted(kb: Knowledge, pool: Sequence[str], rng: np.random.Generator) -> str:
    w = np.asarray([kb.disease_counts.get(t, 0) + 1 for t in pool], dtype=float)
    return pool[int(rng.choice(len(pool), p=w / w.sum()))]


def generalize(kb: Knowledge, hpo_id: str, steps: int, rng: np.random.Generator) -> str:
    """`steps` times, a uniformly chosen parent that is a finding; stops early at the top of the subtree."""
    term = hpo_id
    for _ in range(steps):
        parents = [p for p in kb.ontology.parents(term) if kb.is_finding(p)]
        if not parents:
            break
        term = parents[int(rng.integers(len(parents)))]
    return term


def specialize(
    kb: Knowledge, hpo_id: str, steps: int, rng: np.random.Generator, blocked: set[str] | frozenset[str]
) -> str | None:
    """A descendant to show instead of `hpo_id`: a child, then a child of it, up to `steps` levels.

    Candidates are findings not in `blocked` (the gene's annotated terms and their ancestors, so the pick is
    more specific than any annotation), weighted by annotation counts. None when no child qualifies; a
    descendant without a qualifying child is kept.
    """

    def eligible(ids: Sequence[str]) -> list[str]:
        return [t for t in ids if kb.is_finding(t) and t not in blocked]

    children = eligible(kb.ontology.children(hpo_id))
    if not children:
        return None
    term = _weighted(kb, children, rng)
    for _ in range(steps - 1):
        children = eligible(kb.ontology.children(term))
        if not children:
            break
        term = _weighted(kb, children, rng)
    return term


def related_noise_term(
    kb: Knowledge,
    seeds: Sequence[str],
    rng: np.random.Generator,
    profile: frozenset[str],
    profile_ancestors: frozenset[str],
    shown: RelatedTerms,
    up_levels: int = 2,
    down_levels: int = 2,
) -> str | None:
    """An off-profile term near the patient's phenotype.

    From a uniformly chosen seed, go up to a parent, then one more level with probability 0.5 per level, at
    most `up_levels` levels; then pick uniformly among the anchor's descendants at most `down_levels` levels
    down. The pick is never the anchor, an annotated term, an ancestor or descendant of one, or related to a
    shown term. None when nothing qualifies.
    """
    seed = seeds[int(rng.integers(len(seeds)))]
    parents = [p for p in kb.ontology.parents(seed) if kb.is_finding(p)]
    if not parents:
        return None
    anchor = parents[int(rng.integers(len(parents)))]
    for _ in range(up_levels - 1):
        if rng.random() >= 0.5:
            break
        grandparents = [p for p in kb.ontology.parents(anchor) if kb.is_finding(p)]
        if not grandparents:
            break
        anchor = grandparents[int(rng.integers(len(grandparents)))]
    candidates: set[str] = set()
    level = [anchor]
    for _ in range(down_levels):
        level = [child for term in level for child in kb.ontology.children(term)]
        candidates.update(level)
    eligible = [
        t
        for t in sorted(candidates)
        if t != anchor
        and kb.is_finding(t)
        and t not in profile
        and t not in profile_ancestors
        and kb.ontology.ancestors(t).isdisjoint(profile)
        and shown.fits(t)
    ]
    if not eligible:
        return None
    return eligible[int(rng.integers(len(eligible)))]
