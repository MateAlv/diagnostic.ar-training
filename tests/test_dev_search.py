import itertools
import math

import numpy as np
import pytest
from test_rerank_variants import EXCLUDED_SETS, KB, ONTO, case

from diagnostic_ar_training.cohorts.schema import Sex
from diagnostic_ar_training.eval import dev_search, s3_run
from diagnostic_ar_training.rerank.config import RerankConfig, rr_v1_reference
from diagnostic_ar_training.rerank.features import COMPONENTS, FeatureParams, GeneKnowledge, components
from diagnostic_ar_training.rerank.learned import table
from diagnostic_ar_training.systems import Scored

GENES = ("FEB", "SEIZ", "DD", "NONE")


class Base:
    genes = GENES

    def score(self, c):
        return Scored(np.array([0.4, 0.3, 0.2, 0.1]), {})


FORMS = [
    ("llr", None, None),
    ("gated", 0.2, None),
    ("gated", 0.4, None),
    ("capped", None, 0.5),
    ("capped", None, 2.0),
    ("propagated", None, None),
]


@pytest.mark.parametrize("k", [0.5, 0.8])
def test_vectorised_negation_equals_the_feature_code_for_every_form(k):
    kn = GeneKnowledge(KB, ONTO)
    lookup = dev_search.gene_index(GENES)
    for (form, tau, cap), excluded in itertools.product(FORMS, EXCLUDED_SETS):
        config = RerankConfig("kb-x", form, k, tau, cap, weights={"neg_llr": 1.0, "neg_annotated_share": 1.0})
        c = case(excluded=excluded)
        p = dev_search.prepare(Base(), c, "FEB", {"kb-x": kn}, ONTO, False, 4, lookup)
        x = dev_search.design(p, config)
        reference = table(Base(), config.knowledge(KB, ONTO), c, 4).x
        np.testing.assert_allclose(x, reference, atol=1e-12)


def test_every_component_and_arm_rank_match_the_legacy_table_path():
    kn = GeneKnowledge(KB, ONTO)
    lookup = dev_search.gene_index(GENES)
    configs = [
        rr_v1_reference("kb-x"),
        RerankConfig(
            "kb-x",
            "gated",
            0.8,
            neg_tau=0.2,
            weights={
                "neg_llr": 2,
                "sex_prior": 1,
                "sex_restricted": 1,
                "age_mean": 0.5,
                "age_any": 1,
                "onset": 2,
            },
        ),  # fmt: skip
    ]
    cases = [
        case(excluded=("HP:0001250", "HP:0001263"), sex=Sex.MALE, age_years=3.0, onset_years=1.0),
        case(excluded=(), sex=Sex.FEMALE, age_years=40.0),
        case(excluded=("HP:0000028",)),
    ]
    for c, config in itertools.product(cases, configs):
        p = dev_search.prepare(Base(), c, "SEIZ", {"kb-x": kn}, ONTO, True, 4, lookup)
        legacy = table(Base(), config.knowledge(KB, ONTO), c, 4)
        np.testing.assert_allclose(
            dev_search.design(p, config) @ config.beta(), legacy.x @ config.beta(), atol=1e-12
        )
        expected = s3_run.rank(legacy.combine(config.beta()), GENES, "SEIZ")
        assert dev_search.arm_rank(p, config) == expected
    assert dev_search.rank_at(None, 1) == math.inf and dev_search.rank_at(np.ones(3), None) == math.inf


def test_a_case_whose_gene_is_not_in_the_vocabulary_ranks_at_infinity():
    kn = GeneKnowledge(KB, ONTO)
    p = dev_search.prepare(
        Base(), case(excluded=("HP:0001250",)), "ZZZ", {"kb-x": kn}, ONTO, False, 4, {"FEB": 0}
    )
    assert dev_search.arm_rank(p, rr_v1_reference("kb-x")) == math.inf


def test_arms_on_different_kbs_use_their_own_knowledge():
    other = {**KB, "genes": {**KB["genes"], "FEB": {"D:NONE": 1.0}}}
    kns = {"a": GeneKnowledge(KB, ONTO), "b": GeneKnowledge(other, ONTO)}
    p = dev_search.prepare(
        Base(), case(excluded=("HP:0001263",)), "FEB", kns, ONTO, False, 4, dev_search.gene_index(GENES)
    )
    xa = dev_search.design(p, rr_v1_reference("a"))
    xb = dev_search.design(p, rr_v1_reference("b"))
    assert not np.array_equal(xa, xb)
    assert FeatureParams() == rr_v1_reference("a").feature_params() and COMPONENTS and components


def arm(arm_id, form="llr", weights=None, kb="kb-v6", tau=None, cap=None):
    config = RerankConfig(kb, form, 0.5, tau, cap, weights=weights or {"neg_llr": 1.0})
    return dev_search.Arm(arm_id, "L1", config)


def row(arm_id, delta, harmed, ci_lo=0.001, r1_pass=1):
    return {"arm_id": arm_id, "delta": delta, "harmed": harmed, "ci_lo": ci_lo, "r1_pass": r1_pass}


def test_selection_maximises_delta_under_the_fixed_constraints():
    arms = {a.arm_id: a for a in (arm("a"), arm("b"), arm("c"), arm("d"), arm("e"))}
    rows = [
        row("a", 0.010, 0.04),
        row("b", 0.020, 0.06),  # harmed above 5%
        row("c", 0.015, 0.05, ci_lo=-0.001),  # CI includes 0
        row("d", 0.012, 0.03, r1_pass=0),  # fails the R1-dev check
        row("e", 0.0099, 0.02),
    ]
    assert dev_search.select(rows, arms)["arm_id"] == "a"
    assert dev_search.select(rows[1:4], arms) is None
    assert dev_search.select(rows, arms, max_harmed=0.075)["arm_id"] == "b"


def test_a_tie_within_0_001_goes_to_the_simpler_system():
    arms = {
        "gated": arm("gated", "gated", tau=0.2),
        "llr": arm("llr"),
        "llr2": arm("llr2", weights={"neg_llr": 2.0}),
        "sex": arm("sex", weights={"neg_llr": 1.0, "sex_prior": 1.0}),
    }
    rows = [
        row("gated", 0.0105, 0.04),
        row("llr2", 0.0100, 0.04),
        row("llr", 0.0096, 0.04),
        row("sex", 0.0102, 0.04),
    ]
    assert dev_search.select(rows, arms)["arm_id"] == "llr"
    rows = [row("gated", 0.0120, 0.04), row("llr", 0.0100, 0.04)]
    assert dev_search.select(rows, arms)["arm_id"] == "gated"


def test_complexity_orders_features_then_form_then_kb_then_weight():
    c = dev_search.complexity
    assert c(arm("x")) < c(arm("x", weights={"neg_llr": 1.0, "age_mean": 1.0}))
    assert (
        c(arm("x"))
        < c(arm("x", "propagated"))
        < c(arm("x", "capped", cap=1.0))
        < c(arm("x", "gated", tau=0.2))
    )
    assert c(arm("x", kb="kb-v6")) < c(arm("x", kb="kb-v8")) < c(arm("x", kb="kb-v7"))
    assert c(arm("x", weights={"neg_llr": 0.5})) < c(arm("x", weights={"neg_llr": 2.0}))


def test_frontier_reports_the_best_delta_at_each_harm_limit():
    rows = [row("a", 0.01, 0.04), row("b", 0.02, 0.07), row("c", 0.03, 0.09), row("d", 0.04, 0.2)]
    f = dev_search.frontier(rows)
    assert [f[x]["arm_id"] for x in dev_search.LIMITS] == ["a", "b", "c"]
    assert dev_search.frontier([row("d", 0.04, 0.2)]) == dict.fromkeys(dev_search.LIMITS)


def test_r1_no_harm_rule():
    assert dev_search.r1_no_harm(-0.0025, 0.0013)
    assert not dev_search.r1_no_harm(-0.03, 0.01)
    assert not dev_search.r1_no_harm(-0.005, -0.001)
    assert dev_search.r1_no_harm(-0.02, 0.0)


def test_log_keeps_the_header_and_round_trips_every_configuration(tmp_path):
    path = tmp_path / "dev-search.tsv"
    path.write_text("# prioritisation written before the run\n# 48 arms\n")
    a, b = arm("L1-001"), arm("L1-002", "gated", tau=0.4)
    s3 = {"delta": 0.0123456789, "ci95": [0.001, 0.02], "harmed": 0.04, "helped": 0.2, "n": 9619}
    r1 = {"delta": -0.001, "ci95": [-0.01, 0.005], "harmed": 0.03, "helped": 0.02}
    dev_search.append_log(path, [dev_search.log_row(a, s3, r1, "abc")])
    dev_search.append_log(path, [dev_search.log_row(b, s3, r1, "abc")])
    text = path.read_text().splitlines()
    assert text[0].startswith("# prioritisation") and sum(line.startswith("lever\t") for line in text) == 1
    rows = dev_search.read_log(path)
    assert [r["arm_id"] for r in rows] == ["L1-001", "L1-002"]
    assert rows[1]["tau"] == "0.4" and rows[1]["config_hash"] == b.config.config_hash
    assert rows[0]["delta"] == 0.012346 and rows[0]["r1_pass"] == 1
    assert dev_search.Arm.from_dict(b.to_dict()) == b


def test_the_shared_log_is_the_concatenation_of_the_stage_row_files(tmp_path):
    s3 = {"delta": 0.01, "ci95": [0.001, 0.02], "harmed": 0.04, "helped": 0.2, "n": 10}
    r1 = {"delta": 0.0, "ci95": [-0.01, 0.01], "harmed": 0.03, "helped": 0.02}
    stage_a = [dev_search.log_row(arm("a1"), s3, r1, "x"), dev_search.log_row(arm("a2"), s3, r1, "x")]
    stage_b = [dev_search.log_row(arm("b1"), s3, r1, "x")]
    log = tmp_path / "dev-search.tsv"
    log.write_text("# header\n")
    files = [tmp_path / "a.tsv", tmp_path / "b.tsv"]
    for f, rows in zip(files, (stage_a, stage_b), strict=True):
        dev_search.append_log(log, rows)
        dev_search.write_stage_rows(f, rows)
    assert dev_search.log_equals_stage_rows(log, files)
    assert not dev_search.log_equals_stage_rows(log, files[::-1])
    assert not dev_search.log_equals_stage_rows(log, files[:1])
