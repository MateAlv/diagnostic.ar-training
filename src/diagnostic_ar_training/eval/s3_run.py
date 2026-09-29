"""Run S3 (EVAL_PROTOCOL §8): interview each simulated patient, then score every system.

Per case: E0 ranks the initial presentation; the questioner picks questions from
E0's candidates and the half-A KB; the truth answers them; every system then sees the
same interviewed case. One feature table per interviewed case serves all re-rankers.
"""

import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import interactive
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge
from diagnostic_ar_training.rerank.learned import table


@dataclass
class Interview:
    initial: Case
    initial_probs: np.ndarray | None
    questions: list[str]
    after: Case
    """What every system receives: reported present + "yes" as present, "no" as excluded."""

    @property
    def yes(self) -> int:
        return len(set(self.after.present) - set(self.initial.present))


@dataclass
class Interviewed:
    case_id: str
    gene: str
    initial_probs: np.ndarray | None
    table: object
    questions: list[str]
    yes: int
    no: int
    after: Case


def interview_cases(
    pairs, e0, knowledge: GeneKnowledge, ontology: Ontology, n_candidates: int, n_questions: int
) -> list[Interview]:
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
        out.append(Interview(case, initial, questions, after))
    return out


def interview_all(
    pairs, e0, knowledge: GeneKnowledge, ontology: Ontology, n_candidates: int, n_questions: int, top_k: int
):
    return [
        Interviewed(
            i.initial.case_id,
            i.initial.gene,
            i.initial_probs,
            table(e0, knowledge, i.after, top_k),
            i.questions,
            i.yes,
            len(i.after.excluded),
            i.after,
        )
        for i in interview_cases(pairs, e0, knowledge, ontology, n_candidates, n_questions)
    ]


def write_interviews(path: Path, interviews: list[Interview]) -> None:
    """The interviewed cases systems receive (after), with their questions; no truth, no probabilities."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for i in interviews:
            row = {"questions": i.questions, "case": i.after.model_dump(mode="json")}
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def read_interviews(path: Path) -> list[Case]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [Case.model_validate(json.loads(line)["case"]) for line in handle]


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
