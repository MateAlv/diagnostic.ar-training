"""`LtrV1`: E0 run on the present terms, then the ltr-v1 re-ranker of a bundle (ltr/bundle.py)."""

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.ltr.bundle import LtrModel
from diagnostic_ar_training.safe.system import case_inputs as safe_inputs
from diagnostic_ar_training.systems import Scored, System

NAME = "ltr-v1"


def case_inputs(case: Case) -> dict:
    return {**safe_inputs(case), "present": list(case.present)}


class LtrV1:
    def __init__(
        self, base: System, model: LtrModel, name: str = NAME, lineage: list[dict] | None = None
    ) -> None:
        self.base = base
        self.model = model
        self.name = name
        self.genes = base.genes
        self._lineage = lineage or []

    def lineage_inputs(self) -> list[dict]:
        return self.base.lineage_inputs() + self._lineage

    def score(self, case: Case) -> Scored:
        scored = self.base.score(case.model_copy(update={"excluded": ()}))
        if scored.probs is None:
            return scored
        probs = self.model.apply(scored.probs, self.genes, case_inputs(case))
        return Scored(probs, {**scored.info, "ltr_changed": probs is not scored.probs})
