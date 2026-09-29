"""Run S3 (EVAL_PROTOCOL §8): interview each simulated patient, then score every system.

Per case: E0 ranks the initial presentation; the questioner picks questions from
E0's candidates and the half-A KB; the truth answers them; every system then sees the
same interviewed case. One feature table per interviewed case serves all re-rankers.
"""

import math
from dataclasses import dataclass

import numpy as np

from diagnostic_ar_training.eval import interactive
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge
from diagnostic_ar_training.rerank.learned import table


@dataclass
class Interviewed:
    case_id: str
    gene: str
    initial_probs: np.ndarray | None
    table: object
    questions: list[str]
    yes: int
    no: int


def interview_all(
    pairs, e0, knowledge: GeneKnowledge, ontology: Ontology, n_candidates: int, n_questions: int, top_k: int
):
    out = []
    for case, truth in pairs:
        initial = e0.score(case).probs
        questions = []
        if initial is not None:
            public = interactive.PublicCase.of(case)
            questions = interactive.choose_questions(
                public, initial, e0.genes, knowledge, ontology, n_candidates, n_questions
            )
        after = interactive.interview(case, truth, questions, ontology)
        yes = len(set(after.present) - set(case.present))
        out.append(
            Interviewed(
                case.case_id,
                case.gene,
                initial,
                table(e0, knowledge, after, top_k),
                questions,
                yes,
                len(after.excluded),
            )
        )
    return out


def rank(probs: np.ndarray | None, genes: tuple[str, ...], gene: str) -> float:
    lookup = {g.upper(): i for i, g in enumerate(genes)}
    idx = lookup.get(gene.upper())
    if probs is None or idx is None:
        return math.inf
    t = probs[idx]
    return float(1 + (probs > t).sum() + ((probs == t).sum() - 1))


def rr_v1_beta(neg=0.0, sex=0.0, age=0.0, onset=0.0) -> np.ndarray:
    """rr-v1's four weights expressed on the component vector (features.features sums them this way)."""
    w = dict.fromkeys(COMPONENTS, 0.0)
    w.update(neg_llr=neg, sex_prior=sex, sex_restricted=sex, age_mean=age, onset=onset)
    return np.array([w[c] for c in COMPONENTS])
