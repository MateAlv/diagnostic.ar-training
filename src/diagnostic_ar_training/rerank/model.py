"""rr-v1: re-score the GNN's top genes with weighted B2 features.

score(g) = log p_gnn(g) + sum_f w_f * feature_f(case, g), for the top-K genes by
p_gnn; the rest keep log p_gnn. The distribution returned is the softmax of the
scores, so with no new inputs (all features 0) it is exactly the GNN's.
"""

from dataclasses import dataclass, field

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.rerank.features import GeneKnowledge, features
from diagnostic_ar_training.systems import Scored, System

FEATURES = ("neg", "sex", "age", "onset")


@dataclass(frozen=True)
class Weights:
    neg: float = 0.0
    sex: float = 0.0
    age: float = 0.0
    onset: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {f: getattr(self, f) for f in FEATURES}


@dataclass
class FeatureTable:
    """Everything rr-v1 needs for one case, so that many weight settings cost one GNN call."""

    probs: np.ndarray | None
    top: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))
    values: np.ndarray = field(default_factory=lambda: np.zeros((0, len(FEATURES))))
    info: dict = field(default_factory=dict)

    def combine(self, weights: Weights) -> np.ndarray | None:
        if self.probs is None:
            return None
        delta = self.values @ np.array([getattr(weights, f) for f in FEATURES]) if self.top.size else None
        if delta is None or not np.any(delta):
            return self.probs
        scores = np.log(np.clip(self.probs, 1e-300, None))
        scores[self.top] += delta
        scores -= scores.max()
        exp = np.exp(scores)
        return exp / exp.sum()


def feature_table(base: System, knowledge: GeneKnowledge, case: Case, top_k: int) -> FeatureTable:
    scored = base.score(case)
    if scored.probs is None:
        return FeatureTable(None, info=scored.info)
    top = np.argsort(scored.probs)[::-1][:top_k]
    values = np.array(
        [[features(knowledge, case, base.genes[i])[f] for f in FEATURES] for i in top], dtype=float
    )
    return FeatureTable(scored.probs, top, values, scored.info)


class ReRanker:
    def __init__(
        self, base: System, knowledge: GeneKnowledge, weights: Weights, top_k: int = 200, name="rr-v1"
    ):
        self.base = base
        self.knowledge = knowledge
        self.weights = weights
        self.top_k = top_k
        self.name = name
        self.genes = base.genes

    def lineage_inputs(self) -> list[dict]:
        return self.base.lineage_inputs()

    def score(self, case: Case) -> Scored:
        table = feature_table(self.base, self.knowledge, case, self.top_k)
        return Scored(table.combine(self.weights), table.info)
