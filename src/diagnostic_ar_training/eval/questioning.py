"""Question-strategy harness for EXP-Q-001 (L4).

A strategy gets a PublicCase and the answers so far and returns the next batch of
HPO terms. The harness owns the answer rule (`interactive.answer`, from the truth
the strategies never see), the optional seeded answer noise and the budget.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import interactive
from diagnostic_ar_training.eval.interactive import PublicCase
from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, ROOT, Ontology
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge
from diagnostic_ar_training.rerank.learned import table
from diagnostic_ar_training.systems import System

BUDGET = 9
ROUNDS = (3, 3, 3)
YES, NO, UNKNOWN = "yes", "no", "unknown"


def case_of(public: PublicCase, answers: Mapping[str, str] | None = None) -> Case:
    """The case a system receives: reported present, plus "yes" as present and "no" as excluded."""
    answers = answers or {}
    yes = {t for t, a in answers.items() if a == YES}
    no = {t for t, a in answers.items() if a == NO}
    return Case(
        case_id=public.case_id,
        cohort="s3-question",
        gene="",
        present=tuple(sorted(set(public.present) | yes)),
        excluded=tuple(sorted(no)),
        sex=public.sex,
        age_years=public.age_years,
        onset_years=public.onset_years,
    )


@dataclass
class Context:
    """Everything a strategy may use besides the PublicCase: E0, the half-A knowledge, the re-ranker."""

    e0: System
    knowledge: GeneKnowledge
    ontology: Ontology
    beta: np.ndarray
    top_k: int = 200

    def e0_probs(self, case: Case) -> np.ndarray | None:
        return self.e0.score(case).probs

    def posterior(self, case: Case, rerank: bool) -> np.ndarray | None:
        beta = self.beta if rerank else np.zeros(len(COMPONENTS))
        return table(self.e0, self.knowledge, case, self.top_k).combine(beta)


class Strategy(Protocol):
    name: str
    schedule: tuple[int, ...]
    """Batch sizes, one per round; the harness calls `next_batch` once per round."""

    def next_batch(
        self, ctx: Context, public: PublicCase, answers: Mapping[str, str], n: int
    ) -> list[str]: ...


def _implied_blocked(ontology: Ontology, public: PublicCase, answers: Mapping[str, str]) -> set[str]:
    """Reported or "yes" terms block ancestors and descendants; "no" and "unknown" block descendants."""
    blocked = set(public.present) | set(answers)
    for t in set(public.present) | {t for t, a in answers.items() if a == YES}:
        blocked |= ontology.ancestors(t) | ontology.descendants(t)
    for t, a in answers.items():
        if a != YES:
            blocked |= ontology.descendants(t)
    return blocked


@dataclass
class Q0:
    """The S3 v1 questioner behind the interface: E0's top candidates, non-adaptive."""

    n_questions: int = BUDGET
    n_candidates: int = 10
    name: str = "Q0"

    @property
    def schedule(self) -> tuple[int, ...]:
        return (self.n_questions,)

    def next_batch(self, ctx, public, answers, n):
        probs = ctx.e0_probs(case_of(public))
        if probs is None:
            return []
        return interactive.choose_questions(
            public, probs, ctx.e0.genes, ctx.knowledge, ctx.ontology, self.n_candidates, n
        )


@dataclass
class Q2:
    """Re-ranker-aware adaptive: gain under E0 on present+yes, the re-ranker applied to "no" answers."""

    n_candidates: int = 10
    name: str = "Q2"
    schedule: tuple[int, ...] = ROUNDS

    def posterior(self, ctx, public, answers):
        return ctx.posterior(case_of(public, answers), rerank=True)

    def next_batch(self, ctx, public, answers, n):
        probs = self.posterior(ctx, public, answers)
        if probs is None:
            return []
        blocked = _implied_blocked(ctx.ontology, public, answers)
        scored = interactive.information_gains(probs, ctx.e0.genes, ctx.knowledge, blocked, self.n_candidates)
        return self.pick(ctx, scored, answers, n)

    def pick(self, ctx, scored, answers, n):
        return [t for _, t in scored[:n]]


def _organ_level(ontology: Ontology) -> set[str]:
    return {ROOT, PHENOTYPIC_ABNORMALITY, *ontology.children(PHENOTYPIC_ABNORMALITY)}


@dataclass
class Q2b(Q2):
    """Q2 with an MMR penalty: gain * (1 - lam) for a term sharing a sub-organ-system ancestor with a pick."""

    lam: float = 0.5
    name: str = "Q2b"

    def pick(self, ctx, scored, answers, n):
        coarse = _organ_level(ctx.ontology)

        def lineage(t):
            return (ctx.ontology.ancestors(t) | {t}) - coarse

        chosen: list[str] = []
        taken = [lineage(t) for t in answers]
        pool = list(scored)
        while pool and len(chosen) < n:

            def adjusted(item):
                gain, t = item
                shared = any(lineage(t) & other for other in taken)
                return (gain * (1 - self.lam) if shared else gain, -ord_key(t))

            best = max(pool, key=adjusted)
            pool.remove(best)
            chosen.append(best[1])
            taken.append(lineage(best[1]))
        return chosen


def ord_key(term: str) -> int:
    """Deterministic tie-break matching the (-gain, term) order: smaller term id wins."""
    return int(term.split(":")[1])


def _rng(seed: int, case_id: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{case_id}:noise".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def noisy(truth: bool, rate: float, rng: np.random.Generator) -> str:
    """With probability `rate` the answer is corrupted: flipped or "unknown", half each."""
    if rate > 0 and rng.random() < rate:
        return UNKNOWN if rng.random() < 0.5 else (NO if truth else YES)
    return YES if truth else NO


@dataclass
class Interviewed:
    public: PublicCase
    questions: list[str]
    answers: dict[str, str]
    after: Case


def interview(
    case: Case,
    true_present: frozenset[str],
    strategy: Strategy,
    ctx: Context,
    noise: float = 0.0,
    seed: int = 0,
    budget: int = BUDGET,
) -> Interviewed:
    public = PublicCase.of(case)
    rng = _rng(seed, case.case_id)
    answers: dict[str, str] = {}
    questions: list[str] = []
    for size in strategy.schedule:
        n = min(size, budget - len(questions))
        if n <= 0:
            break
        batch = [
            t for t in dict.fromkeys(strategy.next_batch(ctx, public, dict(answers), n)) if t not in answers
        ]
        batch = batch[:n]
        if not batch:
            break
        for t in batch:
            questions.append(t)
            answers[t] = noisy(interactive.answer(t, true_present, ctx.ontology), noise, rng)
    return Interviewed(public, questions, answers, case_of(public, answers))
