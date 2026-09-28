"""Eval-only benchmark TSVs (ID, Gene, comma-separated HPO ids)."""

import csv
from pathlib import Path

from diagnostic_ar_training.cohorts.schema import Case


def load_tsv(path: Path, cohort: str) -> list[Case]:
    cases = []
    with Path(path).open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            terms = tuple(sorted({t.strip() for t in row["Phenotype"].split(",") if t.strip()}))
            if row["Gene"].strip() and terms:
                cases.append(Case(case_id=row["ID"], cohort=cohort, gene=row["Gene"].strip(), present=terms))
    return cases
