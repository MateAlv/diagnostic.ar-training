from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from diagnostic_ar_training.lineage.hashing import sha256_json


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class Case(BaseModel):
    """One patient, whatever the cohort. Absent inputs stay None/empty, never guessed."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    cohort: str
    gene: str
    present: tuple[str, ...]
    excluded: tuple[str, ...] = ()
    sex: Sex = Sex.UNKNOWN
    age_years: float | None = None
    onset_years: float | None = None
    onset_term: str | None = None
    disease_ids: tuple[str, ...] = ()
    pmids: tuple[str, ...] = ()

    def signature(self) -> str:
        """Content identity used to detect the same patient on both sides of a split."""
        return sha256_json(
            {"gene": self.gene, "present": sorted(self.present), "excluded": sorted(self.excluded)}
        )
