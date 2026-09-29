import math

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.systems import Scored

FULL = Case(
    case_id="c",
    cohort="t",
    gene="B",
    present=("HP:1",),
    excluded=("HP:2",),
    sex=Sex.FEMALE,
    age_years=3.0,
    onset_years=1.0,
)


class Fixed:
    name = "fixed"
    genes = ("A", "B", "c1orf1")

    def lineage_inputs(self):
        return []

    def score(self, case):
        if case.present == ("HP:none",):
            return Scored(None, {"n_present": 1, "n_unknown": 1})
        # Uses the excluded input, so views change its answer.
        probs = np.array([0.2, 0.7, 0.1]) if case.excluded else np.array([0.7, 0.2, 0.1])
        return Scored(probs, {"n_present": len(case.present), "n_unknown": 0})


@pytest.mark.parametrize(
    "view,kept",
    [
        ("present", set()),
        ("excluded", {"excluded"}),
        ("sex", {"sex"}),
        ("age", {"age"}),
        ("all", {"excluded", "sex", "age"}),
    ],
)
def test_views_strip_every_input_they_do_not_name(view, kept):
    v = harness.apply_view(FULL, view)
    assert v.present == FULL.present
    assert (v.excluded == FULL.excluded) == ("excluded" in kept)
    assert (v.sex == FULL.sex) == ("sex" in kept)
    assert (v.age_years == FULL.age_years) == ("age" in kept)
    assert (v.onset_years == FULL.onset_years) == ("age" in kept)


def test_run_ranks_per_view_and_matches_genes_case_insensitively():
    cases = [FULL, FULL.model_copy(update={"case_id": "d", "gene": "C1ORF1"})]
    present = harness.run(Fixed(), cases, view="present")
    allv = harness.run(Fixed(), cases, view="all")
    assert [r["rank"] for r in present] == [2, 3]
    assert [r["rank"] for r in allv] == [1, 3]
    assert all(r["gene_in_vocab"] for r in present)


def test_unknown_genes_and_unscorable_cases_are_misses_not_dropped():
    cases = [
        FULL.model_copy(update={"case_id": "x", "gene": "NOTAGENE"}),
        FULL.model_copy(update={"case_id": "y", "present": ("HP:none",)}),
    ]
    records = harness.run(Fixed(), cases)
    assert [r["rank"] for r in records] == [math.inf, math.inf]
    cov = harness.summarize(records)["coverage"]
    assert (
        cov["gene_not_in_vocab"] == 1 and cov["unscorable"] == 1 and cov["genes_not_in_vocab"] == ["NOTAGENE"]
    )


def test_compare_is_paired_and_refuses_different_cases():
    base = harness.run(Fixed(), [FULL], view="present")
    new = harness.run(Fixed(), [FULL], view="all")
    out = harness.compare(base, new)
    assert out["delta"] == pytest.approx(0.5) and out["helped"] == 1.0
    with pytest.raises(ValueError):
        harness.compare(base, harness.run(Fixed(), [FULL.model_copy(update={"case_id": "z"})]))


def test_written_records_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    records = harness.run(Fixed(), [FULL, FULL.model_copy(update={"case_id": "x", "gene": "Q"})])
    ranks_path, _ = harness.write("EXP-000", "r1-v1/dev", "fixed", "all", records)
    assert [r["rank"] for r in harness.read(ranks_path)] == [1, math.inf]
