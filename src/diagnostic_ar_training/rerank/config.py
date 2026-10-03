"""A re-ranker system as data: knowledge id, negation form and its parameters, component weights.

The dev search and the sealed read name systems by `config_hash`, so a result can always be
traced to the exact penalty form, parameters and weights that produced it. Weights are over
the `COMPONENTS` of rr-v2, the same vector `eval.s3_run.rr_v1_beta` builds.
"""

import hashlib
import json
from dataclasses import dataclass, field

import numpy as np

from diagnostic_ar_training.lineage.hashing import canonical_json
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import COMPONENTS, FeatureParams, GeneKnowledge

RR_V1_KB = "kb-v5"
RR_V1_NEG = 0.5


@dataclass(frozen=True)
class RerankConfig:
    kb_id: str
    neg_form: str = "llr"
    neg_strength: float = 0.5
    neg_tau: float | None = None
    neg_cap: float | None = None
    top_k: int = 200
    weights: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        unknown = set(self.weights) - set(COMPONENTS)
        if unknown:
            raise ValueError(f"unknown component weights {sorted(unknown)}; known: {COMPONENTS}")
        object.__setattr__(self, "weights", {c: float(self.weights.get(c, 0.0)) for c in COMPONENTS})
        self.feature_params()

    def feature_params(self, base: FeatureParams = FeatureParams()) -> FeatureParams:
        return FeatureParams(
            neg_strength=self.neg_strength,
            unknown_frequency=base.unknown_frequency,
            epsilon=base.epsilon,
            onset_smoothing=base.onset_smoothing,
            neg_form=self.neg_form,
            neg_tau=self.neg_tau,
            neg_cap=self.neg_cap,
        )

    def beta(self) -> np.ndarray:
        return np.array([self.weights[c] for c in COMPONENTS])

    def knowledge(self, kb: dict, ontology: Ontology) -> GeneKnowledge:
        return GeneKnowledge(kb, ontology, self.feature_params())

    def to_dict(self) -> dict:
        return {
            "kb_id": self.kb_id,
            "neg_form": self.neg_form,
            "neg_strength": self.neg_strength,
            "neg_tau": self.neg_tau,
            "neg_cap": self.neg_cap,
            "top_k": self.top_k,
            "weights": dict(self.weights),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RerankConfig":
        return cls(**data)

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> "RerankConfig":
        return cls.from_dict(json.loads(text))

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()[:12]


def rr_v1_reference(kb_id: str = RR_V1_KB, neg_weight: float = RR_V1_NEG) -> RerankConfig:
    """rr-v1[neg=0.5]: log(1 - 0.5 P) penalty at weight 0.5, no sex, age or onset terms."""
    return RerankConfig(kb_id=kb_id, neg_form="llr", neg_strength=0.5, weights={"neg_llr": neg_weight})
