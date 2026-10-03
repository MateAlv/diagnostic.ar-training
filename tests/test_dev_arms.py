import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import dev_arms, dev_run, dev_search


def fake_rows(arms, deltas, harmed=0.03, ci_lo=0.002, r1=1):
    return [
        {"arm_id": a.arm_id, "delta": d, "harmed": harmed, "ci_lo": ci_lo, "r1_pass": r1}
        for a, d in zip(arms, deltas, strict=True)
    ]


def test_the_three_l1_stages_fill_exactly_the_48_budget_with_unique_configurations():
    a = dev_arms.l1_stage_a()
    assert len(a) == 24 and {x.config.neg_form for x in a} == set(dev_arms.FORMS)
    by_id = {x.arm_id: x for x in a}
    rows = fake_rows(a, [0.01 + 0.001 * i for i in range(24)])
    b = dev_arms.l1_stage_b(rows, by_id)
    c = dev_arms.l1_stage_c()
    assert len(b) == 12 and len(c) == 12 and {x.config.neg_strength for x in b} == {0.8}
    everything = a + b + c
    assert len(everything) == dev_arms.BUDGET["L1"]
    assert len({x.config.config_hash for x in everything}) == 48
    assert len({x.arm_id for x in everything}) == 48
    assert {x.config.neg_tau for x in everything if x.config.neg_form == "gated"} == {0.2, 0.4}
    assert {x.config.neg_cap for x in everything if x.config.neg_form == "capped"} == {1.0, 2.0, 3.0}
    assert {x.config.kb_id for x in everything} == {"kb-v6"}


def test_stage_b_takes_the_two_best_forms_and_a_feasible_form_beats_a_higher_infeasible_one():
    a = dev_arms.l1_stage_a()
    by_id = {x.arm_id: x for x in a}
    rows = fake_rows(a, [0.001] * 24)
    for r in rows:
        form = by_id[r["arm_id"]].config.neg_form
        if form == "capped":
            r["delta"] = 0.03
        if form == "gated":
            r["delta"] = 0.02
        if form == "propagated":
            r["delta"] = 0.05
            r["harmed"] = 0.2  # higher delta, but never feasible
    forms = [form for form, _ in dev_arms.form_scores(rows, by_id)]
    assert forms[:2] == ["capped", "gated"] and forms[-1] == "propagated"
    assert {x.config.neg_form for x in dev_arms.l1_stage_b(rows, by_id)} == {"capped", "gated"}


def test_l2_pairs_the_winner_and_the_best_other_form_with_the_three_kbs():
    a = dev_arms.l1_stage_a()
    by_id = {x.arm_id: x for x in a}
    rows = fake_rows(a, [0.001] * 24)
    rows[5]["delta"] = 0.02  # llr, one weight
    rows[13]["delta"] = 0.015  # gated
    arms = dev_arms.l2_arms(rows, by_id)
    assert len(arms) == 6 and [x.config.kb_id for x in arms[:3]] == ["kb-v6", "kb-v8", "kb-v7"]
    assert {x.config.neg_form for x in arms} == {a[5].config.neg_form, a[13].config.neg_form}
    assert arms[0].config.weights == a[5].config.weights and len({x.config.config_hash for x in arms}) == 6


def test_l3_adds_one_feature_group_at_three_weights_to_the_base_and_keeps_the_base_as_a_reference():
    base = dev_arms.neg_arm("llr", 0.5, 1.0, kb="kb-v8").config
    arms = dev_arms.l3_arms(base)
    assert arms[0].lever == "ref" and arms[0].config == base
    search = arms[1:]
    assert len(search) == 12 == dev_arms.BUDGET["L3"]
    for x in search:
        added = {k for k, v in x.config.weights.items() if v and not base.weights[k]}
        assert x.config.kb_id == "kb-v8" and x.config.weights["neg_llr"] == 1.0 and added
    sex = [x for x in search if x.arm_id.startswith("L3:sex")]
    assert all(x.config.weights["sex_prior"] == x.config.weights["sex_restricted"] > 0 for x in sex)


def test_dev_arms_need_a_winner_or_fall_back_to_the_best_forms():
    a = dev_arms.l1_stage_a()
    by_id = {x.arm_id: x for x in a}
    rows = fake_rows(a, [0.001 * i for i in range(24)], harmed=0.5)
    assert dev_search.select(rows, by_id) is None
    assert len(dev_arms.l2_arms(rows, by_id)) == 6


def case(i, present=(), excluded=(), sex=Sex.UNKNOWN, age=None):
    return Case(
        case_id=f"s3-v2:c{i}",
        cohort="s3-question",
        gene="",
        present=present,
        excluded=excluded,
        sex=sex,
        age_years=age,
    )


def test_subsets_follow_the_declared_definitions():
    rows = [
        {"case": case(0, excluded=("HP:1", "HP:2"), sex=Sex.MALE, age=3.0), "gene": "A"},
        {"case": case(1, excluded=("HP:1", "HP:3")), "gene": "A"},
        {"case": case(2, excluded=("HP:9",), age=5.0), "gene": "B"},
        {"case": case(3), "gene": "C"},
    ]
    entities = {"s3-v2:c0": "D1", "s3-v2:c1": "D1", "s3-v2:c2": "D2", "s3-v2:c3": "D2"}
    half_b = {("D1", "HP:1"), ("D1", "HP:2")}
    masks = dev_run.subset_masks(rows, entities, {"D2"}, half_b, {"D2": "hpoa"})
    assert masks["all"] == [True] * 4
    assert masks["halfB_only_excluded"] == [True, False, False, False]
    assert masks["halfB_any_excluded"] == [True, True, False, False]
    assert masks["excluded_none_halfB"] == [False, False, True, False]
    assert masks["sex_known"] == [True, False, False, False]
    assert masks["lit_onset"] == [False, False, True, True]
    assert masks["lit_onset_age_known"] == [False, False, True, False]
    assert masks["lit_onset_src_hpoa"] == [False, False, True, True]
    assert not any(masks["lit_onset_src_orphanet"])


def test_analyse_compares_every_arm_with_e0_and_with_the_named_base_on_the_same_cases():
    rows = [{"case_id": f"c{i}", "gene": f"G{i % 4}", "case": case(i)} for i in range(40)]
    base = np.array([2.0] * 40)
    ranks = np.column_stack([np.full(40, 2.0), np.full(40, 1.0), np.full(40, 4.0)])
    arms = [
        dev_search.Arm(x, "L3", dev_arms.neg_arm("llr", 0.5, 1.0).config) for x in ("base", "good", "bad")
    ]
    masks = {"all": [True] * 40, "half": [i < 20 for i in range(40)]}
    out = dev_run.analyse(rows, base, ranks, arms, masks, {"base": 0})
    assert (
        out["base"]["vs_e0_answers"]["all"]["delta"] == 0
        and out["base"]["vs_e0_answers"]["all"]["harmed"] == 0
    )
    assert out["good"]["vs_e0_answers"]["all"]["delta"] == pytest.approx(0.5)
    assert out["bad"]["vs_e0_answers"]["all"]["harmed"] == 1.0
    assert out["good"]["paired"]["base"]["half"]["n"] == 20
    assert out["good"]["paired"]["base"]["all"]["delta"] == pytest.approx(0.5)
    assert out["good"]["config_hash"] == arms[1].config.config_hash
