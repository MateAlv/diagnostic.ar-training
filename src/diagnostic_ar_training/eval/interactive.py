"""S3's questioner and answerer (EVAL_PROTOCOL §8).

The questioner only ever receives a PublicCase, which has no field for the gene,
the disease or the true phenotype, so it cannot use them. Answers come only from
the truth. The same questions and answers are given to every system.
"""

from dataclasses import dataclass

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import GeneKnowledge

P_FLOOR = 0.02


@dataclass(frozen=True)
class PublicCase:
    """What a clinician knows before the interview: no gene, no disease, no truth."""

    case_id: str
    present: tuple[str, ...]
    sex: Sex = Sex.UNKNOWN
    age_years: float | None = None
    onset_years: float | None = None

    @classmethod
    def of(cls, case: Case) -> "PublicCase":
        return cls(case.case_id, case.present, case.sex, case.age_years, case.onset_years)


def _entropy(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def choose_questions(
    public: PublicCase,
    e0_probs: np.ndarray,
    genes: tuple[str, ...],
    knowledge: GeneKnowledge,
    ontology: Ontology,
    n_candidates: int = 10,
    n_questions: int = 7,
) -> list[str]:
    """Terms with the highest expected information gain over E0's top candidates (non-adaptive)."""
    order = [i for i in np.argsort(e0_probs)[::-1] if knowledge.diseases(genes[i])][:n_candidates]
    if len(order) < 2:
        return []
    prior = e0_probs[order] / e0_probs[order].sum()
    reported = set(public.present)
    related = set(reported)
    for t in reported:
        related |= ontology.ancestors(t) | ontology.descendants(t)
    terms = set()
    for i in order:
        for disease in knowledge.diseases(genes[i]):
            terms.update(knowledge.kb["diseases"][disease]["phenotypes"])
    terms -= related
    h0 = _entropy(prior)
    scored = []
    for t in sorted(terms):
        p = np.clip([knowledge.term_probability(genes[i], t) for i in order], P_FLOOR, 1 - P_FLOOR)
        p_yes = float(prior @ p)
        post_yes, post_no = prior * p / p_yes, prior * (1 - p) / (1 - p_yes)
        gain = h0 - p_yes * _entropy(post_yes) - (1 - p_yes) * _entropy(post_no)
        if gain > 1e-9:
            scored.append((gain, t))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [t for _, t in scored[:n_questions]]


def answer(term: str, true_present: frozenset[str], ontology: Ontology) -> bool:
    """Yes when the term is true, or is an ancestor of a true term (having the child means having it)."""
    return term in true_present or any(term in ontology.ancestors(t) for t in true_present)


def interview(case: Case, true_present: frozenset[str], questions: list[str], ontology: Ontology) -> Case:
    """The case as systems receive it after the interview: yes answers added, no answers excluded."""
    yes = [q for q in questions if answer(q, true_present, ontology)]
    no = [q for q in questions if q not in yes]
    return case.model_copy(
        update={
            "present": tuple(sorted(set(case.present) | set(yes))),
            "excluded": tuple(sorted(set(case.excluded) | set(no))),
        }
    )
