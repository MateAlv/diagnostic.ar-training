"""`FtV1`: E0 (production ONNX) on the present terms, then the ft-v1 residual of a bundle (ft/bundle.py)."""

from collections.abc import Callable

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.ft.bundle import FtResidual, softmax64
from diagnostic_ar_training.systems import Scored

NAME = "ft-v1"


def case_inputs(case: Case) -> dict:
    return {
        "sex": case.sex.value,
        "age_years": case.age_years,
        "onset_years": case.onset_years,
        "present": list(case.present),
        "excluded": list(case.excluded),
    }


class E0Logits:
    """E0's logits for a case's present terms, memoised by (case id, present terms)."""

    def __init__(self, base) -> None:
        self.base = base
        self.genes = base.genes
        self._cache: dict[tuple[str, tuple[str, ...]], tuple[np.ndarray | None, dict]] = {}

    def lineage_inputs(self) -> list[dict]:
        return self.base.lineage_inputs()

    def __call__(self, case: Case) -> tuple[np.ndarray | None, dict]:
        key = (case.case_id, case.present)
        if key not in self._cache:
            known, info = self.base.inputs.known_present(case)
            logits = None
            if known:
                logits, node_ids = self.base.logits(known)
                info.update(
                    n_nodes=len(node_ids),
                    n_zero_embedded_nodes=sum(n not in self.base.inputs.emb_index for n in node_ids),
                )
            self._cache[key] = (logits, info)
        logits, info = self._cache[key]
        return logits, dict(info)


class E0System:
    """E0 through the same logits as FtV1: softmax of the production logits, as `GenPheniaV3.score`."""

    name = "E0"

    def __init__(self, e0: E0Logits) -> None:
        self.e0, self.genes = e0, e0.genes

    def lineage_inputs(self) -> list[dict]:
        return self.e0.lineage_inputs()

    def score(self, case: Case) -> Scored:
        logits, info = self.e0(case)
        return Scored(None if logits is None else softmax64(logits), info)


class FtV1:
    def __init__(
        self,
        e0: E0Logits,
        residual: FtResidual,
        name: str = NAME,
        pooler: Callable[[Case], np.ndarray] | None = None,
        lineage: list[dict] | None = None,
    ) -> None:
        if residual.needs_pooled and pooler is None:
            raise ValueError("this bundle has classifier deltas: pass a pooler")
        self.e0, self.residual, self.name, self.pooler = e0, residual, name, pooler
        self.genes = e0.genes
        if tuple(residual.knowledge.genes) != tuple(self.genes):
            raise ValueError("the knowledge arrays are over another gene vocabulary")
        self._lineage = lineage or []

    def lineage_inputs(self) -> list[dict]:
        return self.e0.lineage_inputs() + self._lineage

    def score(self, case: Case) -> Scored:
        logits, info = self.e0(case)
        if logits is None:
            return Scored(None, info)
        pooled = self.pooler(case) if self.residual.needs_pooled else None
        r = self.residual.residual(case_inputs(case), pooled)
        info.update(ft_lowered=int((r < 0).sum()), ft_min=float(r.min()) if r.size else 0.0)
        if not r.any():
            return Scored(softmax64(logits), info)
        return Scored(softmax64(np.asarray(logits, dtype=np.float64) + r), info)
