"""Curation overrides (data/curation/safe-v1-overrides.csv).

An override may only make a rule more conservative (ADR-0017 decision 8): remove a gene from the sex or onset
rule, or lower its onset bound. Anything else (a new limitation, a higher bound, an override of a rule the
gene does not have) is rejected, and so is a row without its evidence.
"""

import copy
import csv
import math
from dataclasses import asdict, dataclass
from pathlib import Path

COLUMNS = ("gene", "rule", "action", "value_years", "evidence_quote", "source_file", "curator")
RULES = ("sex", "onset")
ACTIONS = ("remove", "lower_onset")


class OverrideError(ValueError):
    pass


@dataclass(frozen=True)
class Override:
    gene: str
    rule: str
    action: str
    value_years: float | None
    evidence_quote: str
    source_file: str
    curator: str


def read(path: Path) -> list[Override]:
    with Path(path).open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise OverrideError(f"{path}: header must be {','.join(COLUMNS)}, got {reader.fieldnames}")
        return [parse_row(row, line) for line, row in enumerate(reader, start=2)]


def parse_row(row: dict, line: int = 0) -> Override:
    where = f"line {line}" if line else "override"
    values = {k: (row.get(k) or "").strip() for k in COLUMNS}
    if not values["gene"]:
        raise OverrideError(f"{where}: gene is required")
    if values["rule"] not in RULES:
        raise OverrideError(f"{where}: rule must be one of {RULES}, got {values['rule']!r}")
    if values["action"] not in ACTIONS:
        raise OverrideError(f"{where}: action must be one of {ACTIONS}, got {values['action']!r}")
    for k in ("evidence_quote", "source_file", "curator"):
        if not values[k]:
            raise OverrideError(f"{where}: {k} is required")
    value = None
    if values["action"] == "lower_onset":
        if values["rule"] != "onset":
            raise OverrideError(f"{where}: lower_onset applies to the onset rule only")
        try:
            value = float(values["value_years"])
        except ValueError as e:
            raise OverrideError(f"{where}: lower_onset needs a number in value_years") from e
        if not math.isfinite(value):
            raise OverrideError(f"{where}: value_years must be finite")
    elif values["value_years"]:
        raise OverrideError(f"{where}: remove takes no value_years")
    return Override(**{**values, "value_years": value})


def apply(kb: dict, overrides: list[Override]) -> dict:
    """A curated copy of `kb`. Raises OverrideError on anything that would make a rule stricter."""
    out = copy.deepcopy(kb)
    seen = set()
    for o in overrides:
        if (o.gene, o.rule) in seen:
            raise OverrideError(f"{o.gene}: more than one {o.rule} override")
        seen.add((o.gene, o.rule))
        record = out["genes"].get(o.gene)
        if record is None:
            raise OverrideError(f"{o.gene}: not a gene of the knowledge artifact")
        if o.rule not in record:
            raise OverrideError(
                f"{o.gene}: has no {o.rule} limitation to override; overrides cannot add a limitation"
            )
        if o.action == "remove":
            record.setdefault("curated", {})[o.rule] = {"removed": record.pop(o.rule)}
        else:
            current = record["onset"]["earliest_years"]
            if o.value_years >= current:
                raise OverrideError(
                    f"{o.gene}: lower_onset to {o.value_years} y is not below the current bound {current} y; "
                    "overrides may only lower it"
                )
            record.setdefault("curated", {})["onset"] = {"uncurated_earliest_years": current}
            record["onset"]["earliest_years"] = o.value_years
        out["overrides"].append(asdict(o))
    return out
