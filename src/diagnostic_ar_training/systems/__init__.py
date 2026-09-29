"""Systems under test. Each maps a Case to a probability over the same gene vocabulary."""

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case


@dataclass
class Scored:
    probs: np.ndarray | None
    """Distribution over `System.genes`; None when the case cannot be scored at all."""
    info: dict = field(default_factory=dict)


class System(Protocol):
    name: str
    genes: tuple[str, ...]

    def lineage_inputs(self) -> list[dict]:
        """Sources and artifacts this system depends on, for result manifests."""
        ...

    def score(self, case: Case) -> Scored: ...
