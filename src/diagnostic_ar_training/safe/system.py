"""`SafeV1`: E0 run on the present terms, then the safe-v1 rules of a bundle (safe/bundle.py)."""

from collections.abc import Iterable

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.safe.bundle import RULES, SafeRules, rescale
from diagnostic_ar_training.systems import Scored, System

NAME = "safe-v1"


def case_inputs(case: Case) -> dict:
    return {
        "sex": case.sex.value,
        "onset_years": case.onset_years,
        "age_years": case.age_years,
        "excluded": list(case.excluded),
    }


def variant_name(rules: Iterable[str]) -> str:
    rules = tuple(r for r in RULES if r in set(rules))
    return NAME if rules == RULES else f"{NAME}[{'+'.join(rules)}]"


class SafeV1:
    def __init__(
        self,
        base: System,
        rules: SafeRules,
        active: Iterable[str] = RULES,
        lineage: list[dict] | None = None,
    ) -> None:
        self.base = base
        self.rules = rules
        self.active = tuple(r for r in RULES if r in set(active))
        self.name = variant_name(self.active)
        self.genes = base.genes
        self._lineage = lineage or []

    def lineage_inputs(self) -> list[dict]:
        return self.base.lineage_inputs() + self._lineage

    def score(self, case: Case) -> Scored:
        present_only = case.model_copy(update={"excluded": ()})
        scored = self.base.score(present_only)
        if scored.probs is None:
            return scored
        inputs = case_inputs(case)
        contradicted, blocked = self.rules.masks(self.genes, inputs, self.active)
        probs = rescale(scored.probs, contradicted, blocked, self.rules.negation_factor)
        info = {
            **scored.info,
            "safe_contradicted": int(contradicted.sum()),
            "safe_blocked": int(blocked.sum()),
        }
        return Scored(probs, info)
