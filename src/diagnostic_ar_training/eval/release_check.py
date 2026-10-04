"""EXP-B-006: the R1 no-regression check of the release candidate rr-v1[neg=0.5] + onset 0.25.

One pass over a cohort, scored three ways from the same GNN output per case:
- E0: the GNN alone;
- rr-v1: the production re-ranker (`Weights(neg=0.5)`, the form EXP-B-003 gated);
- the candidate: rr-v1 plus `onset` at 0.25.

Views of each case: "given" (excluded terms and onset as the cohort records them), "no_onset" (onset removed)
and "present" (excluded terms and onset removed). The gate is `verdict`; its numbers are pre-registered in
docs/experiments/EXP-B-006.md and are constants here so that the test suite pins them.
"""

from collections.abc import Sequence

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.rerank import grid
from diagnostic_ar_training.rerank.features import GeneKnowledge, case_onset_years
from diagnostic_ar_training.rerank.model import FeatureTable, Weights, feature_table
from diagnostic_ar_training.systems import System

EXPERIMENT = "EXP-B-006"
KB_ID = "kb-v3"
TOP_K = 200
REFERENCE = Weights(neg=0.5)
CANDIDATE = Weights(neg=0.5, onset=0.25)
E0 = Weights()

N2_FLOOR = -0.02
"""EXP-B-003 N2: the point estimate of candidate vs E0 on the cases as given must be at least this."""
MARGIN = -0.01
"""EVAL_PROTOCOL §6 no-regression margin: the candidate vs rr-v1 CI lower bound must be at least this."""

SEALED_COHORTS = {"r1-v1/test"}
ALLOWED_COHORTS = {"r1-v1/dev", "r1-v1/test"}


def check_request(exp: str, cohort: str, reason: str) -> None:
    """The sealed cohort is read only by this experiment's one pre-registered read, with a reason."""
    if exp != EXPERIMENT:
        raise ValueError(f"this check belongs to {EXPERIMENT}, not {exp!r}")
    if cohort not in ALLOWED_COHORTS:
        raise ValueError(f"cohort must be one of {sorted(ALLOWED_COHORTS)}, got {cohort!r}")
    if cohort in SEALED_COHORTS and not reason.strip():
        raise ValueError(f"{cohort} is sealed: a reason is required")


def has_onset(case: Case) -> bool:
    return case_onset_years(case) is not None


def without_onset(case: Case) -> Case:
    return case.model_copy(update={"onset_years": None, "onset_term": None})


def make_views(cases: Sequence[Case]) -> dict[str, list[Case]]:
    return {
        "given": list(cases),
        "no_onset": [without_onset(c) for c in cases],
        "present": [without_onset(c).model_copy(update={"excluded": ()}) for c in cases],
    }


def mismatches(a: Sequence[FeatureTable], wa: Weights, b: Sequence[FeatureTable], wb: Weights) -> int:
    """Cases whose output distribution differs at all, bit for bit, between two weight settings."""
    count = 0
    for ta, tb in zip(a, b, strict=True):
        pa, pb = ta.combine(wa), tb.combine(wb)
        if (pa is None) != (pb is None) or (pa is not None and not np.array_equal(pa, pb)):
            count += 1
    return count


def _subset(records: list[dict], keep: set[str]) -> list[dict]:
    return [r for r in records if r["case_id"] in keep]


def _compare(base: list[dict], new: list[dict]) -> dict:
    return harness.compare(base, new) if base else {"n": 0}


def evaluate(
    base: System,
    knowledge: GeneKnowledge,
    cases: Sequence[Case],
    groups: dict[str, str] | None,
    top_k: int = TOP_K,
) -> tuple[dict, dict[str, list[dict]]]:
    """The report and the per-case records (system -> records) of the cases as given."""
    views = make_views(cases)
    tables = {v: [feature_table(base, knowledge, c, top_k) for c in vc] for v, vc in views.items()}
    given = tables["given"]
    records = {
        "E0": grid._records(views["given"], given, base.genes, E0, groups),
        "rr-v1": grid._records(views["given"], given, base.genes, REFERENCE, groups),
        "candidate": grid._records(views["given"], given, base.genes, CANDIDATE, groups),
    }
    with_onset = {c.case_id for c in cases if has_onset(c)}
    without = {c.case_id for c in cases} - with_onset
    no_usable_idx = [i for i, c in enumerate(cases) if c.case_id in without]
    pick = [given[i] for i in no_usable_idx]
    report: dict = {
        "cases": len(cases),
        "cases_with_usable_onset": len(with_onset),
        "cases_with_excluded": sum(bool(c.excluded) for c in cases),
        "identity": {
            "no_onset_view_candidate_vs_rr_v1": {
                "cases": len(cases),
                "mismatches": mismatches(tables["no_onset"], CANDIDATE, tables["no_onset"], REFERENCE),
            },
            "present_view_candidate_vs_e0": {
                "cases": len(cases),
                "mismatches": mismatches(tables["present"], CANDIDATE, tables["present"], E0),
            },
            "given_view_cases_without_usable_onset_candidate_vs_rr_v1": {
                "cases": len(pick),
                "mismatches": mismatches(pick, CANDIDATE, pick, REFERENCE),
            },
        },
        "given": {
            "rr_v1_vs_e0": _compare(records["E0"], records["rr-v1"]),
            "candidate_vs_e0": _compare(records["E0"], records["candidate"]),
            "candidate_vs_rr_v1": _compare(records["rr-v1"], records["candidate"]),
        },
        "descriptive": {},
    }
    for label, keep in (("with_usable_onset", with_onset), ("without_usable_onset", without)):
        r_ref, r_cand = _subset(records["rr-v1"], keep), _subset(records["candidate"], keep)
        report["descriptive"][label] = {
            "cases": len(keep),
            "candidate_vs_rr_v1": _compare(r_ref, r_cand),
            "candidate_vs_e0": _compare(_subset(records["E0"], keep), r_cand),
        }
    return report, records


def verdict(report: dict) -> dict:
    """The pre-registered gate. Every check must hold for a PASS."""
    ident = report["identity"]
    d_e0 = report["given"]["candidate_vs_e0"]
    d_rr = report["given"]["candidate_vs_rr_v1"]
    checks = {
        "ID1_no_onset_identical_to_rr_v1": ident["no_onset_view_candidate_vs_rr_v1"]["mismatches"] == 0,
        "ID2_present_identical_to_e0": ident["present_view_candidate_vs_e0"]["mismatches"] == 0,
        "ID3_cases_without_usable_onset_identical_to_rr_v1": ident[
            "given_view_cases_without_usable_onset_candidate_vs_rr_v1"
        ]["mismatches"]
        == 0,
        "N2_candidate_vs_e0": bool(d_e0["ci95"][1] >= 0 and d_e0["delta"] >= N2_FLOOR),
        "N3_candidate_vs_rr_v1": bool(d_rr["ci95"][0] >= MARGIN),
    }
    return {"checks": checks, "pass": all(checks.values())}
