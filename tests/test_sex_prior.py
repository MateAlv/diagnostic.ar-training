import pytest
from test_rerank import ONTO

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.knowledge import sex_prior


def test_jeffreys_share_is_smoothed_towards_one_half():
    assert sex_prior.jeffreys_male_share(0, 0) == 0.5
    assert sex_prior.jeffreys_male_share(10, 10) == pytest.approx(10.5 / 11)


def test_sex_key_follows_the_simulator_rules():
    assert sex_prior.sex_key({"HP:0001475"}, "male") == "male_limited"
    assert sex_prior.sex_key({"HP:0001450"}, "unknown") == "male_limited"
    assert sex_prior.sex_key({"HP:0034344"}, "female") == "female_limited"
    assert sex_prior.sex_key({"HP:0001419"}, "male") == "male_biased"
    assert sex_prior.sex_key({"HP:0001423"}, "unknown") == "x_linked_dominant"
    assert sex_prior.sex_key({"HP:0000006"}, "none") == "unbiased"


def test_a_patient_stands_for_the_entity_of_their_diagnosis_else_the_weighted_ones():
    a = {"ids": ["OMIM:1"], "sim_weight": 0.25, "simulable": True}
    b = {"ids": ["OMIM:2"], "sim_weight": 0.75, "simulable": True}
    diagnosed = Case(case_id="c", cohort="r", gene="G", present=(), sex=Sex.MALE, disease_ids=("OMIM:1",))
    assert sex_prior.patient_entities(diagnosed, [a, b]) == [(a, 1.0)]
    undiagnosed = diagnosed.model_copy(update={"disease_ids": ()})
    assert [w for _, w in sex_prior.patient_entities(undiagnosed, [a, b])] == [0.25, 0.75]


def test_measure_counts_known_sex_only(monkeypatch):
    monkeypatch.setattr(sex_prior, "entity_sex_key", lambda *_: "unbiased")
    gene = {
        "entities": [
            {"ids": ["OMIM:1"], "sim_weight": 1.0, "simulable": True, "inheritance": [], "profile_ids": []}
        ]
    }
    cases = [
        Case(case_id=str(i), cohort="r", gene="G", present=(), sex=s)
        for i, s in enumerate([Sex.MALE, Sex.MALE, Sex.FEMALE, Sex.UNKNOWN])
    ]
    out = sex_prior.measure(cases, {"G": gene}, {}, ONTO)
    assert out["mass"]["unbiased"] == {"male": 2.0, "female": 1.0}
    assert out["patients"]["sex_unknown"] == 1
