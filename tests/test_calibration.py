"""R1-train calibration targets: populations, ANALYSIS-002 term categories, noise vocabulary rules."""

import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.knowledge import calibration
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import FeatureParams, GeneKnowledge

PARENTS = {
    "HP:0000001": (),
    "HP:0000118": ("HP:0000001",),
    "HP:0000707": ("HP:0000118",),  # nervous system
    "HP:0001250": ("HP:0000707",),  # seizure
    "HP:0002373": ("HP:0001250",),  # febrile seizure: the gene's annotation
    "HP:0011169": ("HP:0002373",),  # a child of it: more specific
    "HP:0020219": ("HP:0001250",),  # a sibling under seizure: related
    "HP:0000028": ("HP:0000118",),  # another system: weak
}
ONTO = Ontology(PARENTS, {}, {}, {}, frozenset())


def disease(term):
    return {"phenotypes": {term: {"freq": 0.8, "onset": [], "sex": None}}, "excluded": [], "onset_years": [],
            "inheritance": []}  # fmt: skip


KB = {
    "schema": 2,
    "diseases": {
        "OMIM:1": disease("HP:0002373"),
        **{f"OMIM:{i}": disease("HP:0000028") for i in range(2, 11)},
    },
    "genes": {"G": {"OMIM:1": 1.0}, "H": {f"OMIM:{i}": 1.0 for i in range(2, 11)}},
}
KNOW = GeneKnowledge(KB, ONTO, FeatureParams())
CATS = calibration.TermCategories(KB, KNOW, ONTO)


def case(case_id, present, pmids=()):
    return Case(case_id=case_id, cohort="t", gene="G", present=present, pmids=pmids)


def test_term_categories_follow_analysis_002():
    assert CATS.classify("G", "HP:0001250") == "explained"
    assert CATS.classify("G", "HP:0011169") == "more_specific"
    assert CATS.ic("HP:0001250") == pytest.approx(2.302585, rel=1e-5)
    assert CATS.classify("G", "HP:0020219") == "related_ic_ge_2"
    assert CATS.classify("G", "HP:0000028") == "weak_ic_lt_2"


def test_uncited_population_drops_patients_whose_paper_hpoa_cites(tmp_path):
    hpoa = tmp_path / "phenotype.hpoa"
    hpoa.write_text("#header PMID:9\nOMIM:1\tx\t\tHP:0002373\tPMID:11;PMID:12\tPCS\n")
    cited = calibration.cited_pmids(hpoa)
    assert cited == {"11", "12"}
    cases = [
        case("a", ("HP:0001250",), ("PMID:12",)),
        case("b", ("HP:0001250",), ("PMID:13",)),
        case("c", ()),
    ]
    assert [c.case_id for c in calibration.select_population(cases, "uncited", cited)] == ["b", "c"]
    assert len(calibration.select_population(cases, "all")) == 3
    with pytest.raises(ValueError):
        calibration.select_population(cases, "uncited")


def test_related_or_weak_vocabulary_leaves_more_specific_terms_out():
    cases = [
        case("a", ("HP:0001250", "HP:0011169", "HP:0020219", "HP:0000028")),
        case("b", ("HP:0011169", "HP:0020219")),
    ]
    targets, rows = calibration.measure(cases, KNOW, 2, CATS, "related_or_weak")
    assert [r[0] for r in rows] == ["HP:0020219"]  # in 2 patients; the more specific term is not noise
    cat = targets["categories"]
    assert cat["terms"] == 6 and cat["explained"] == pytest.approx(1 / 6)
    assert cat["more_specific"] == pytest.approx(2 / 6) and cat["related_ic_ge_2"] == pytest.approx(2 / 6)
    assert targets["noise_share"] == pytest.approx(3 / 6)
    assert targets["related_share_of_noise"] == pytest.approx(2 / 3)
    assert targets["unexplained_present_share"] == pytest.approx(5 / 6)  # calib-v1's definition, unchanged

    _, rows_v1 = calibration.measure(cases, KNOW, 2)
    assert [r[0] for r in rows_v1] == ["HP:0011169", "HP:0020219"]
    with pytest.raises(ValueError):
        calibration.measure(cases, KNOW, 2, None, "related_or_weak")


def test_onset_category_takes_the_narrowest_window():
    assert calibration.onset_category(0.0) == "antenatal"
    assert calibration.onset_category(0.05) == "neonatal"
    assert calibration.onset_category(1.0) == "infantile"  # both infantile and childhood hold 1.0
    assert calibration.onset_category(10.0) == "juvenile"
    assert calibration.onset_category(30.0) == "adult"
    assert calibration.onset_category(70.0) is None


def test_duration_means_fall_back_to_the_overall_mean_for_small_categories():
    def aged(i, age, onset):
        return Case(case_id=f"c{i}", cohort="t", gene="G", present=(), age_years=age, onset_years=onset)

    cases = [aged(i, 30.0, 20.0) for i in range(3)]
    cases += [aged(9, 2.0, 1.5), aged(10, 1.0, 5.0), aged(11, 3.0, None)]
    out = calibration.duration_means(cases, min_patients=3)
    assert out["per_category"]["adult"]["used"] == pytest.approx(10.0)
    assert out["per_category"]["childhood"]["patients"] == 1
    assert out["per_category"]["childhood"]["used"] == pytest.approx(out["overall_mean_duration"])
    assert out["overall_mean_duration"] == pytest.approx((30.0 + 0.5) / 4)
    assert out["skipped"] == {"age_below_onset": 1, "age_or_onset_missing": 1}
    assert out["keys"]["age.duration_mean_by_onset.adult"] == 10.0
