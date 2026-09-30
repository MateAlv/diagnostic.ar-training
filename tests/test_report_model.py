import json
import math
from collections import Counter

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.knowledge import report_model as R
from diagnostic_ar_training.ontology import Ontology

OBO = "http://purl.obolibrary.org/obo/HP_"
HP = {
    "0000001": [],
    "0000118": ["0000001"],
    "0001250": ["0000118"],
    "0002069": ["0001250"],
    "0000505": ["0000118"],
    "0000006": ["0000001"],
}
KB = {
    "schema": 2,
    "diseases": {
        "OMIM:1": {
            "phenotypes": {
                "HP:0001250": {"freq": 0.9, "onset": [], "sex": None},
                "HP:0000505": {"freq": None, "onset": [], "sex": None},
                "HP:0000006": {"freq": 1.0, "onset": [], "sex": None},  # not a phenotypic abnormality
            }
        },
        "ORPHA:10": {"phenotypes": {"HP:0001250": {"freq": 0.2, "onset": [], "sex": None}}},
        "OMIM:2": {"phenotypes": {"HP:0000505": {"freq": 0.5, "onset": [], "sex": None}}},
    },
    "genes": {"G": {"OMIM:1": 1.0}},
}


@pytest.fixture
def onto(tmp_path):
    nodes = [{"id": OBO + c, "lbl": c} for c in HP]
    edges = [{"sub": OBO + c, "pred": "is_a", "obj": OBO + p} for c, ps in HP.items() for p in ps]
    (tmp_path / "hp.json").write_text(json.dumps({"graphs": [{"nodes": nodes, "edges": edges}]}))
    return Ontology.from_json(tmp_path / "hp.json")


def case(i, present, disease="OMIM:1"):
    return Case(case_id=f"c{i}", cohort="t", gene="G", present=tuple(present), disease_ids=(disease,))


def test_merged_profile_prefers_omim_frequency_and_keeps_phenotypic_terms_only(onto):
    ids = R.entity_ids(["OMIM:1"], [("ORPHA:10", "OMIM:1")])
    assert ids == ["OMIM:1", "ORPHA:10"]
    assert R.profile(KB, ids, onto) == {"HP:0001250": 0.9, "HP:0000505": None}


def test_features_follow_their_definitions(onto):
    annotations, n = R.annotation_counts(KB, onto)
    assert annotations["HP:0001250"] == 2 and annotations["HP:0000118"] == 3 and n == 3
    reportability = R.reportability_counts([case(1, ["HP:0002069"]), case(2, ["HP:0000505"])], onto)
    assert reportability["HP:0001250"] == 1
    f = R.Featurizer(onto, annotations, n, reportability, 2, {("OMIM:1", "HP:0001250")})
    row = f.row("HP:0001250", 0.9, ["OMIM:1"])
    assert row[0] == 0.9 and row[1] == 0.0
    assert row[2] == pytest.approx(-math.log(3 / 4))
    assert row[3] == 2.0  # HP:0000118, HP:0000001
    assert row[4] == pytest.approx(math.log(2 / 3))
    assert row[5] == 1.0
    loo = f.row("HP:0001250", None, ["OMIM:2"], reportability_minus=1, patients_minus=1)
    assert loo[0] == 0.0 and loo[1] == 1.0 and loo[4] == pytest.approx(math.log(1 / 2)) and loo[5] == 0.0


def test_training_rows_label_descendants_as_reported(onto):
    annotations, n = R.annotation_counts(KB, onto)
    cases = [case(1, ["HP:0002069"]), case(2, ["HP:0000505"])]
    f = R.Featurizer(onto, annotations, n, R.reportability_counts(cases, onto), 2, set())
    X, y, genes, stats = R.training_rows(cases, {"c1": "a", "c2": "b"}, KB, f, [])
    assert stats == {"patients": 2, "patients_with_profile": 2, "rows": 4}
    # rows sorted by term per patient: HP:0000505 then HP:0001250
    assert y.tolist() == [0.0, 1.0, 1.0, 0.0]
    # Patient 1's own paper is left out of the reportability of what it reports.
    assert X[1, 4] == pytest.approx(math.log(1 / 2))


def test_fit_recovers_a_monotone_effect_and_auc_handles_ties():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(4000, 1))
    y = (rng.random(4000) < 1 / (1 + np.exp(-(0.5 + 2 * x[:, 0])))).astype(float)
    model = R.fit(x, y, (0,))
    assert model["coef"][0] == pytest.approx(2, abs=0.25) and model["intercept"] == pytest.approx(
        0.5, abs=0.2
    )
    assert R.auc(np.array([1, 0, 1, 0]), np.array([1.0, 1.0, 2.0, 0.0])) == pytest.approx(0.875)


def test_term_budget_histogram():
    budget = R.term_budget([case(1, ["HP:0000505"]), case(2, ["HP:0000505", "HP:0001250"])])
    assert budget["histogram"] == {"1": 1, "2": 1} and budget["mean"] == 1.5


def test_gene_frequencies_mix_by_disease_weight(onto):
    freqs = R.gene_frequencies(KB, {"OMIM:1": 0.75, "OMIM:2": 0.25}, onto)
    assert freqs["HP:0001250"] == pytest.approx(0.75 * 0.9)
    assert freqs["HP:0000505"] == pytest.approx(0.25 * 0.5)  # OMIM:1 gives it no frequency


SIMULATOR_KEYS = {
    "format", "format_version", "artifact_id", "link", "intercept", "features", "tables",
    "reportability", "term_budget", "provenance", "notes",
}  # fmt: skip


def test_simulator_format_scores_like_the_fitted_model(onto):
    annotations, n = R.annotation_counts(KB, onto)
    reportability = R.reportability_counts([case(1, ["HP:0002069"]), case(2, ["HP:0000505"])], onto)
    featurizer = R.Featurizer(onto, annotations, n, reportability, 2, set())
    model = {"intercept": -1.5, "coef": [2.0, 0.5, 0.1, -0.05, 0.4, 0.7]}
    budget = R.term_budget([case(1, ["HP:0000505"])])
    body = R.to_simulator_format("rm", model, annotations, n, reportability, 2, budget, {}, "n")
    assert set(body) == SIMULATOR_KEYS and body["format"] == "report-model"
    assert [f["kind"] for f in body["features"]] == [
        "frequency", "information_content", "ancestor_count", "log_reportability", "cardinal_flag",
    ]  # fmt: skip
    assert body["features"][0]["unknown_value"] == pytest.approx(0.25)
    internal = R.internal_scorer(featurizer, model, tuple(range(6)))
    exported = R.simulator_scorer(json.loads(json.dumps(body)), onto)
    for term in ("HP:0001250", "HP:0000505", "HP:0000118", "HP:0000006"):
        for freq in (None, 0.0, 0.7):
            for flag in (False, True):
                assert exported(term, freq, flag) == pytest.approx(internal(term, freq, flag), abs=1e-12)


def test_an_unknown_frequency_that_cannot_be_folded_is_refused(onto):
    annotations, n = R.annotation_counts(KB, onto)
    model = {"intercept": 0.0, "coef": [1.0, 2.0, 0.0, 0.0, 0.0, 0.0]}
    with pytest.raises(ValueError):
        R.to_simulator_format(
            "rm", model, annotations, n, Counter(), 1, {"histogram": {}, "definition": ""}, {}, ""
        )


def test_publications_out_rho_removes_the_scored_patients_own_reports():
    parents = {
        "HP:0000001": (),
        "HP:0000118": ("HP:0000001",),
        "HP:0001250": ("HP:0000118",),
        "HP:0000505": ("HP:0000118",),
        "HP:0000707": ("HP:0000118",),
    }
    onto = Ontology(parents, {}, {}, {}, frozenset())
    terms = ("HP:0001250", "HP:0000505", "HP:0000707")
    kb = {"diseases": {"OMIM:1": {"phenotypes": {t: {"freq": 0.5} for t in terms}}}}
    cases = [Case(case_id=f"g{i}", cohort="t", gene="G", present=("HP:0001250",)) for i in range(5)]
    cases += [Case(case_id=f"h{i}", cohort="t", gene="H", present=("HP:0000505",)) for i in range(3)]
    groups = {c.case_id: "p1" if c.gene == "G" else "p2" for c in cases}
    annotations, n = R.annotation_counts(kb, onto)
    featurizer = R.Featurizer(onto, annotations, n, R.reportability_counts(cases, onto), len(cases), set())
    model, cols = {"intercept": 0.0, "coef": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0]}, tuple(range(6))

    def diseases(gene):
        return {"OMIM:1": 1.0} if gene == "G" else {}

    scorers = {"m": R.internal_scorer(featurizer, model, cols)}
    inside = R.gene_level_rho(cases, diseases, kb, onto, set(), scorers, min_patients=5)
    out = R.gene_level_rho_publications_out(
        cases, groups, diseases, kb, onto, set(), featurizer, {"m": (model, cols)}, min_patients=5
    )
    assert inside["genes"] == out["genes"] == 1
    assert inside["mean_rho"]["m"] > 0 > out["mean_rho"]["m"]
