import numpy as np
import pytest
from test_rerank import KB, ONTO
from typer.testing import CliRunner

from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import release_check
from diagnostic_ar_training.rerank.features import FeatureParams, GeneKnowledge, case_onset_years, onset_bin
from diagnostic_ar_training.rerank.kb import HPO_ONSET_YEARS
from diagnostic_ar_training.systems import Scored

K = GeneKnowledge(KB, ONTO, FeatureParams())
GENES = ("XLR", "ADULT", "NOONSET")

# The nine onset classes the web app offers (diagnostic.ar PR #87, frontend/src/lib/onset.ts) and the
# onset bin the feature should read for each of them.
WEB_CLASSES = {
    "HP:0030674": 0,
    "HP:0003577": 1,
    "HP:0003623": 1,
    "HP:0003593": 2,
    "HP:0011463": 3,
    "HP:0003621": 4,
    "HP:0011462": 5,
    "HP:0003596": 6,
    "HP:0003584": 7,
}


class FakeBase:
    name = "fake"
    genes = GENES

    def lineage_inputs(self):
        return []

    def score(self, case):
        shift = (len(case.case_id) % 3) * 0.05
        probs = np.array([0.34 - shift, 0.33, 0.33 + shift])
        return Scored(probs / probs.sum())


def make_cases():
    cases = []
    for i in range(36):
        kw = {}
        if i % 3 == 0:
            kw["onset_years"] = 0.0 if i % 2 else 30.0
        if i % 3 == 1:
            kw["onset_term"] = "HP:0003577"
        if i % 4 != 3:
            kw["excluded"] = ("HP:0001250",)
        cases.append(
            Case(
                case_id=f"c{i}",
                cohort="t",
                gene=GENES[i % 3],
                present=("HP:0001263",),
                **kw,
            )
        )
    return cases


GROUPS = {f"c{i}": f"g{i // 4}" for i in range(36)}


def test_report_has_exact_identities_and_the_candidate_moves_only_cases_with_onset():
    cases = make_cases()
    report, records = release_check.evaluate(FakeBase(), K, cases, GROUPS)
    ident = report["identity"]
    assert ident["no_onset_view_candidate_vs_rr_v1"] == {"cases": 36, "mismatches": 0}
    assert ident["present_view_candidate_vs_e0"] == {"cases": 36, "mismatches": 0}
    assert ident["given_view_cases_without_usable_onset_candidate_vs_rr_v1"]["mismatches"] == 0
    assert report["cases_with_usable_onset"] == sum(release_check.has_onset(c) for c in cases)
    without = report["descriptive"]["without_usable_onset"]["candidate_vs_rr_v1"]
    assert without["delta"] == 0 and without["harmed"] == 0 and without["helped"] == 0
    assert report["given"]["candidate_vs_rr_v1"]["n"] == 36
    assert set(records) == {"E0", "rr-v1", "candidate"}


def test_candidate_differs_from_rr_v1_when_onset_is_given():
    cases = [c for c in make_cases() if release_check.has_onset(c)]
    views = release_check.make_views(cases)
    from diagnostic_ar_training.rerank.model import feature_table

    given = [feature_table(FakeBase(), K, c, 200) for c in views["given"]]
    assert release_check.mismatches(given, release_check.CANDIDATE, given, release_check.REFERENCE) > 0
    bare = [feature_table(FakeBase(), K, c, 200) for c in views["no_onset"]]
    assert release_check.mismatches(bare, release_check.CANDIDATE, bare, release_check.REFERENCE) == 0


def _report(mismatch=0, e0=(-0.0025, -0.007, 0.0013), rr=(0.001, -0.002, 0.004)):
    def cmp(t):
        return {"delta": t[0], "ci95": [t[1], t[2]], "harmed": 0.1, "helped": 0.1, "n": 10}

    return {
        "identity": {
            "no_onset_view_candidate_vs_rr_v1": {"mismatches": mismatch},
            "present_view_candidate_vs_e0": {"mismatches": 0},
            "given_view_cases_without_usable_onset_candidate_vs_rr_v1": {"mismatches": 0},
        },
        "given": {"candidate_vs_e0": cmp(e0), "candidate_vs_rr_v1": cmp(rr)},
    }


def test_verdict_thresholds_are_the_preregistered_numbers():
    assert release_check.N2_FLOOR == -0.02 and release_check.MARGIN == -0.01
    assert release_check.CANDIDATE.as_dict() == {"neg": 0.5, "sex": 0.0, "age": 0.0, "onset": 0.25}
    assert release_check.REFERENCE.as_dict() == {"neg": 0.5, "sex": 0.0, "age": 0.0, "onset": 0.0}
    assert release_check.verdict(_report())["pass"]
    assert not release_check.verdict(_report(mismatch=1))["pass"]
    assert not release_check.verdict(_report(e0=(-0.01, -0.02, -0.0001)))["pass"]
    assert not release_check.verdict(_report(e0=(-0.021, -0.03, 0.001)))["pass"]
    assert release_check.verdict(_report(e0=(-0.019, -0.03, 0.0)))["pass"]
    assert not release_check.verdict(_report(rr=(-0.005, -0.0101, 0.001)))["pass"]
    assert release_check.verdict(_report(rr=(-0.005, -0.01, 0.001)))["pass"]


def test_sealed_cohort_needs_this_experiment_and_a_reason():
    release_check.check_request("EXP-B-006", "r1-v1/dev", "")
    release_check.check_request("EXP-B-006", "r1-v1/test", "pre-registered abc")
    for exp, cohort, reason in (
        ("EXP-B-003", "r1-v1/test", "r"),
        ("EXP-B-006", "r1-v1/test", " "),
        ("EXP-B-006", "r1-v1/vault", "r"),
        ("EXP-B-006", "mcrd", "r"),
    ):
        with pytest.raises(ValueError):
            release_check.check_request(exp, cohort, reason)


def test_cli_refuses_a_sealed_read_without_reason_before_loading_anything():
    result = CliRunner().invoke(
        app, ["rerank", "release-check", "--cohort", "r1-v1/test"], env={"COLUMNS": "400"}
    )
    assert result.exit_code != 0
    assert "reason is required" in result.output


def test_every_web_onset_class_maps_to_the_bin_of_its_own_interval():
    for hpo_id, expected in WEB_CLASSES.items():
        assert hpo_id in HPO_ONSET_YEARS
        years = case_onset_years(
            Case(case_id="c", cohort="t", gene="G", present=("HP:1",), onset_term=hpo_id)
        )
        assert onset_bin(years) == expected, hpo_id


def test_an_exact_age_wins_over_the_class():
    case = Case(
        case_id="c", cohort="t", gene="G", present=("HP:1",), onset_years=2.0, onset_term="HP:0003584"
    )
    assert case_onset_years(case) == 2.0
