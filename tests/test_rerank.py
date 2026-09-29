import math

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import FeatureParams, GeneKnowledge, features, onset_bin
from diagnostic_ar_training.rerank.model import ReRanker, Weights, feature_table
from diagnostic_ar_training.systems import Scored

PARENTS = {
    "HP:0000001": (),
    "HP:0000118": ("HP:0000001",),
    "HP:0000707": ("HP:0000118",),
    "HP:0001250": ("HP:0000707",),  # seizure
    "HP:0002373": ("HP:0001250",),  # febrile seizure
    "HP:0000028": ("HP:0000118",),  # cryptorchidism
    "HP:0001263": ("HP:0000707",),  # developmental delay
}
ONTO = Ontology(PARENTS, {}, {}, {}, frozenset())


def disease(phenotypes, onset=(), inheritance=(), excluded=()):
    return {
        "phenotypes": {t: {"freq": f, "onset": [], "sex": s} for t, (f, s) in phenotypes.items()},
        "excluded": list(excluded),
        "onset_years": [list(iv) for iv in onset],
        "inheritance": list(inheritance),
    }


KB = {
    "schema": 2,
    "diseases": {
        "OMIM:1": disease({"HP:0002373": (0.8, None), "HP:0000028": (0.5, "male")}, onset=[(0.0, 0.0)],
                          inheritance=["HP:0001419"]),
        "OMIM:2": disease({"HP:0001263": (None, None)}, onset=[(16.0, 100.0)]),
        "OMIM:3": disease({"HP:0001263": (0.9, None)}),
    },
    "genes": {"XLR": {"OMIM:1": 1.0}, "ADULT": {"OMIM:2": 1.0}, "NOONSET": {"OMIM:3": 1.0}},
    "vocabulary": {"OLDNAME": "XLR"},
}  # fmt: skip
K = GeneKnowledge(KB, ONTO, FeatureParams())


def case(**kw):
    return Case(case_id="c", cohort="t", gene="XLR", present=kw.pop("present", ("HP:0001263",)), **kw)


def test_no_new_inputs_means_every_feature_is_zero():
    for gene in ("XLR", "ADULT", "NOONSET", "NOT_IN_KB"):
        assert features(K, case(), gene) == {"neg": 0.0, "sex": 0.0, "age": 0.0, "onset": 0.0}


def test_negation_uses_propagated_frequency_and_is_neutral_for_unannotated_terms():
    # Excluding "seizure" counts against a gene annotating "febrile seizure" (a descendant).
    f = features(K, case(excluded=("HP:0001250",)), "XLR")
    assert f["neg"] == pytest.approx(math.log(1 - 0.5 * 0.8))
    assert features(K, case(excluded=("HP:0001250",)), "ADULT")["neg"] == 0.0
    # Excluding a broader term the gene annotates only through a child never helps the gene.
    assert features(K, case(excluded=("HP:0000707",)), "XLR")["neg"] < 0


def test_sex_prior_from_inheritance_and_restricted_findings():
    assert features(K, case(sex=Sex.MALE), "XLR")["sex"] == pytest.approx(math.log(0.9 / 0.5))
    female = features(K, case(sex=Sex.FEMALE), "XLR")["sex"]
    assert female == pytest.approx(math.log(0.1 / 0.5))
    restricted = features(K, case(sex=Sex.FEMALE, present=("HP:0000028",)), "XLR")["sex"]
    assert restricted == pytest.approx(math.log(0.1 / 0.5) + math.log(0.01))
    assert features(K, case(sex=Sex.FEMALE), "NOONSET")["sex"] == 0.0


def test_age_penalises_genes_whose_onset_is_later_than_the_patient():
    assert features(K, case(age_years=2.0), "ADULT")["age"] == pytest.approx(math.log(0.01))
    assert features(K, case(age_years=30.0), "ADULT")["age"] == pytest.approx(math.log(14 / 84))
    assert features(K, case(age_years=2.0), "XLR")["age"] == 0.0  # congenital: already started
    assert features(K, case(age_years=2.0), "NOONSET")["age"] == 0.0  # no onset knowledge


def test_onset_likelihood_ratio_prefers_matching_onset():
    congenital = features(K, case(onset_years=0.0), "XLR")["onset"]
    adult = features(K, case(onset_years=30.0), "XLR")["onset"]
    assert congenital > 0 > adult
    assert features(K, case(onset_term="HP:0003577"), "XLR")["onset"] == pytest.approx(congenital)
    assert onset_bin(-0.5) == 0 and onset_bin(0.0) == 1 and onset_bin(70) == 7


def test_renamed_vocabulary_symbols_find_their_gene():
    assert features(K, case(sex=Sex.MALE), "OLDNAME") == features(K, case(sex=Sex.MALE), "XLR")


class Base:
    name = "base"
    genes = ("XLR", "ADULT", "NOONSET", "NOT_IN_KB")

    def lineage_inputs(self):
        return []

    def score(self, c):
        return Scored(np.array([0.4, 0.3, 0.2, 0.1]), {})


def test_reranker_is_the_identity_without_new_inputs_and_moves_genes_with_them():
    rr = ReRanker(Base(), K, Weights(neg=1, sex=1, age=1, onset=1), top_k=3)
    assert np.array_equal(rr.score(case()).probs, Base().score(None).probs)
    child = rr.score(case(age_years=2.0)).probs
    assert child[1] < 0.3 and np.argmax(child) == 0
    assert child[3] == pytest.approx(0.1 / (0.4 + 0.3 * 0.01 + 0.2 + 0.1), rel=1e-6)


def test_feature_table_combines_many_weights_from_one_base_call():
    table = feature_table(Base(), K, case(age_years=2.0, sex=Sex.FEMALE), top_k=4)
    assert np.array_equal(table.combine(Weights()), Base().score(None).probs)
    assert table.combine(Weights(age=1)).tolist() != table.combine(Weights(sex=1)).tolist()


def test_rr_v1_features_are_unchanged_sums_of_components():
    from diagnostic_ar_training.rerank.features import components

    c = case(
        sex=Sex.FEMALE, present=("HP:0000028",), excluded=("HP:0001250",), age_years=2.0, onset_years=0.0
    )
    comp, feat = components(K, c, "XLR"), features(K, c, "XLR")
    assert feat["sex"] == pytest.approx(comp["sex_prior"] + comp["sex_restricted"])
    assert feat["neg"] == comp["neg_llr"] and comp["neg_annotated_share"] == 1.0


def test_age_any_accepts_a_disease_if_one_listed_onset_fits():
    kb = dict(KB, diseases=dict(KB["diseases"], **{"OMIM:9": disease({"HP:0001263": (0.5, None)},
                                                                     onset=[(2.0, 11.0), (18.0, 65.0)])}),
              genes=dict(KB["genes"], MIXED={"OMIM:9": 1.0}))  # fmt: skip
    k = GeneKnowledge(kb, ONTO, FeatureParams())
    assert k.onset_before("MIXED", 11.0) == pytest.approx(0.5)
    assert k.onset_before_any("MIXED", 11.0) == pytest.approx(1.0)


def test_learned_reranker_recovers_a_planted_weight_and_is_the_identity_without_inputs():
    from diagnostic_ar_training.rerank.features import COMPONENTS
    from diagnostic_ar_training.rerank.learned import Table, fit

    rng = np.random.default_rng(0)
    true_beta = np.zeros(len(COMPONENTS))
    true_beta[COMPONENTS.index("age_any")] = 2.0
    tables = []
    for _ in range(400):
        probs = rng.dirichlet(np.ones(20))
        x = np.zeros((20, len(COMPONENTS)))
        x[:, COMPONENTS.index("age_any")] = rng.normal(size=20)
        s = np.log(probs) + x @ true_beta
        p = np.exp(s - s.max())
        p /= p.sum()
        tables.append(Table(probs, np.arange(20), x, int(rng.choice(20, p=p)), {}))
    beta, info = fit(tables, l2=1e-3)
    assert info["converged"] and info["loss"] < info["loss_at_zero"]
    assert beta[COMPONENTS.index("age_any")] == pytest.approx(2.0, abs=0.4)
    assert np.abs(np.delete(beta, COMPONENTS.index("age_any"))).max() < 0.3
    no_input = Table(tables[0].probs, np.arange(20), np.zeros((20, len(COMPONENTS))), 0, {})
    assert no_input.combine(beta) is tables[0].probs


def test_calibration_counts_real_patient_structure_against_the_kb():
    from diagnostic_ar_training.knowledge.calibration import measure

    cases = [
        case(present=("HP:0002373", "HP:0001263"), excluded=("HP:0000028", "HP:0001263"), sex=Sex.MALE),
        case(present=("HP:0001263",), age_years=3.0),
        Case(case_id="x", cohort="t", gene="NOT_IN_KB", present=("HP:0001263",)),
    ]
    targets, rows = measure(cases, K, min_noise_count=1)
    # XLR annotates febrile seizure and cryptorchidism, not developmental delay.
    assert targets["excluded_annotated_to_own_gene_share"] == pytest.approx(0.5)
    assert targets["unexplained_present_per_case"]["mean"] == pytest.approx(1.0)
    assert rows == [("HP:0001263", 2, 1.0)]
    assert targets["missing"]["sex"] == pytest.approx(2 / 3) and targets["missing"][
        "excluded"
    ] == pytest.approx(2 / 3)
    assert measure(cases, K, min_noise_count=3)[1] == []
