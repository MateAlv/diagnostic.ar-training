"""One entry point for every evaluation cohort, with the sealing rules applied.

Cohort names:
  r1-v1/<part>   phenopacket-store through the frozen split (splits.load_part)
  mcrd, ddd      external benchmarks; sealed, each read ledgered
  s2             upstream-style simulated patients, one per gene (sanity only)
"""

import json
import random

from diagnostic_ar_training.cohorts.benchmarks import load_tsv
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, load_sources, open_source

S2_SOURCE = "graphens_sim_20251202"
S2_SALT = "diagnostic.ar-training/s2-v1"
BENCHMARKS = {"mcrd", "ddd"}


def _s2() -> list[Case]:
    """One patient per gene, chosen by a salted per-gene RNG so the pick never shifts."""
    data = json.loads(open_source(S2_SOURCE, Purpose.EVAL).read_text())
    cases = []
    for gene in sorted(data):
        if gene == "-":
            continue
        valid = [p for p in data[gene] if p and all(t.startswith("HP:") for t in p)]
        if not valid:
            continue
        pick = random.Random(f"{S2_SALT}:{gene}").randrange(len(valid))
        cases.append(
            Case(
                case_id=f"s2:{gene}:{pick}",
                cohort="s2",
                gene=gene,
                present=tuple(sorted(set(valid[pick]))),
            )
        )
    return cases


def load(cohort: str, exp_id: str | None = None, reason: str = "") -> list[Case]:
    if cohort.startswith("r1-v1/"):
        from diagnostic_ar_training import splits

        return splits.load_part("r1-v1", cohort.split("/", 1)[1], Purpose.EVAL, exp_id, reason)
    if cohort == "s2":
        return _s2()
    if cohort in BENCHMARKS:
        source = load_sources()[cohort]
        if source.sealed:
            if exp_id is None:
                raise LineageError(f"{cohort} is sealed: pass exp_id and reason")
            ledger.record_access(cohort, "all", exp_id, reason)
        return load_tsv(open_source(cohort, Purpose.EVAL), cohort)
    raise LineageError(f"unknown cohort {cohort!r}")
