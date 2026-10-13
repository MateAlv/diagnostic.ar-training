import json
import math

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.sim4 import PRESETS, FittedParams, Sampler, fit, folds
from diagnostic_ar_training.sim4.config import (
    CATEGORIES,
    E0_COUNT_HISTOGRAM,
    E0_DISTANCE_HISTOGRAM,
    VARIANTS,
    SimConfig,
    e0_category_shares,
)
from diagnostic_ar_training.sim4.fit import COUNT_BINS, Profiler, budget_scale
from diagnostic_ar_training.sim4.frequency import is_zero_frequency, pooled_frequency
from diagnostic_ar_training.sim4.knowledge import build
from diagnostic_ar_training.sim4.moves import RelatedTerms, generalize, related_noise_term, specialize
from diagnostic_ar_training.sim4.sampler import budget_scaled_probabilities
from diagnostic_ar_training.sim4.validate import EXPLAINED_BINS, _bin_w1, explained_bin

A, A1, A2, A11, A12, A111 = "HP:1000001", "HP:1000011", "HP:1000012", "HP:1000111", "HP:1000112", "HP:1001111"
B, B1, B2 = "HP:2000001", "HP:2000011", "HP:2000012"
PA, AD, ONSET, CONGENITAL = "HP:0000118", "HP:0000006", "HP:0003674", "HP:0003577"
OLD = "HP:9999999"
PARENTS = {
    "HP:0000001": (),
    PA: ("HP:0000001",),
    "HP:0000005": ("HP:0000001",),
    AD: ("HP:0000005",),
    ONSET: ("HP:0000001",),
    CONGENITAL: (ONSET,),
    A: (PA,),
    A1: (A,),
    A2: (A,),
    A11: (A1,),
    A12: (A1,),
    A111: (A11,),
    B: (PA,),
    B1: (B,),
    B2: (B,),
}


def _ontology() -> Ontology:
    return Ontology(PARENTS, {t: t for t in PARENTS}, {OLD: A11}, {}, frozenset())


def _hpoa(disease, name, term, freq="", qualifier="", aspect="P"):
    return {
        "database_id": disease,
        "disease_name": name,
        "qualifier": qualifier,
        "hpo_id": term,
        "frequency": freq,
        "aspect": aspect,
    }


def _g2p(gene, term, disease="", freq=""):
    return {"gene_symbol": gene, "hpo_id": term, "disease_id": disease, "frequency": freq}


HPOA = [
    _hpoa("OMIM:1", "Foo syndrome", A11, "HP:0040281"),
    _hpoa("OMIM:1", "Foo syndrome", A12, "3/4"),
    _hpoa("OMIM:1", "Foo syndrome", A12, "1/4"),
    _hpoa("OMIM:1", "Foo syndrome", B1),
    _hpoa("OMIM:1", "Foo syndrome", B2, "0/5"),
    _hpoa("OMIM:1", "Foo syndrome", A2, qualifier="NOT"),
    _hpoa("OMIM:1", "Foo syndrome", AD, aspect="I"),
    _hpoa("OMIM:1", "Foo syndrome", CONGENITAL, aspect="C"),
    _hpoa("ORPHA:10", "Foo  Syndrome", A11, "HP:0040282"),
    _hpoa("ORPHA:20", "A group", B1),
]
G2P = [
    _g2p("G1", A11, "OMIM:1", "HP:0040281"),
    _g2p("G1", A12, "OMIM:1", "3/4"),
    _g2p("G1", A12, "OMIM:1", "1/4"),
    _g2p("G1", B1, "OMIM:1"),
    _g2p("G1", B2, "OMIM:1", "0/5"),
    _g2p("G1", A2, "OMIM:1"),
    _g2p("G1", AD, "OMIM:1"),
    _g2p("G1", A11, "ORPHA:10", "HP:0040282"),
    _g2p("G1", B1, "ORPHA:20"),
    _g2p("G1", A111),
    _g2p("G1", A111),
    _g2p("G1", B2),
    *(_g2p(f"G{i}", B1, "ORPHA:20") for i in range(2, 6)),
    _g2p("-", A1),
    _g2p("G6", B1),
    _g2p("G6", OLD),
    _g2p("G7", AD),
]


@pytest.fixture(scope="module")
def kb():
    return build(_ontology(), HPOA, G2P)


def _params(**kw) -> FittedParams:
    p = FittedParams(gamma=1.0, f0=0.3, off_vocabulary={B2: 0.5, A2: 0.5})
    p.count_bins = [[lo, hi, 1.0 if lo == 3 else 0.0] for lo, hi in COUNT_BINS]
    p.count_bins_flat = p.count_bins
    p.category_shares = {c: (0.5 if c == "exact" else 0.5 / (len(CATEGORIES) - 1)) for c in CATEGORIES}
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_frequency_drops_zero_rows_before_pooling():
    assert all(is_zero_frequency(v) for v in ("0/7", "0%", "0.0%", "HP:0040285"))
    assert not any(is_zero_frequency(v) for v in ("1/7", "5%", "HP:0040283", "", None))
    assert pooled_frequency(["HP:0040281"]) == 0.895
    assert pooled_frequency(["3/4", "1/4"]) == pytest.approx(4.5 / 9)
    assert pooled_frequency(["0/10", "2/2"]) == pytest.approx(2.5 / 3)
    assert pooled_frequency(["1/2", "HP:0040280"]) == pytest.approx(1.5 / 3)
    assert pooled_frequency(["0/5"]) is None and pooled_frequency([""]) is None


def test_knowledge_keeps_e0_index_and_drops_negations(kb):
    assert kb.genes == ("-", "G1", "G2", "G3", "G4", "G5", "G6", "G7")
    assert "-" not in kb.simulable_genes and "G7" not in kb.simulable_genes
    s = kb.stats["genes_to_phenotype"]
    assert s["dropped_zero_frequency"] == 1
    assert s["dropped_not_only_in_hpoa"] == 1
    assert s["dropped_not_phenotypic_abnormality"] == 2
    assert s["dropped_dash_gene"] == 1
    assert kb.stats["hpoa"]["dropped_not_aspect_P"] == 1
    assert kb.stats["hpoa"]["pairs_pooled_multi_row"] == 1
    every = {t for ents in kb.entities.values() for e in ents for t in e.terms}
    assert A2 not in every and AD not in every
    assert all(kb.is_finding(t) for t in every)
    assert all(A2 not in rows for rows in kb.e0_rows.values())


def test_entities_kinds_weights_and_frequencies(kb):
    ents = {e.id: e for e in kb.entities["G1"]}
    assert set(ents) == {"OMIM:1", "ORPHA:10", "ORPHA:20", "NODISEASE:G1"}
    omim = ents["OMIM:1"]
    assert B2 not in omim.terms
    freq = dict(zip(omim.terms, omim.frequencies, strict=True))
    assert freq == {A11: 0.895, A12: 0.5, B1: None}
    assert ents["ORPHA:20"].kind == "group" and ents["NODISEASE:G1"].kind == "nodisease"
    assert ents["OMIM:1"].duplicate and ents["ORPHA:10"].duplicate
    assert ents["NODISEASE:G1"].terms == (A111, B2)
    weights = dict(zip(ents, kb.entity_weights("G1", 0.2), strict=True))
    assert weights == {"NODISEASE:G1": 0.2, "OMIM:1": 0.5, "ORPHA:10": 0.5, "ORPHA:20": 0.2}
    assert kb.entity_weights("G2", 0.2) == [1.0]
    assert kb.entities["G6"][0].terms == (A11, B1)
    assert kb.e0_rows["G1"].count(A12) == 2 and kb.e0_rows["G1"].count(A111) == 2
    assert kb.onsets["OMIM:1"] == (CONGENITAL,) and AD in kb.inheritance["OMIM:1"]


def test_budget_scale_matches_the_ported_bisection():
    rng = np.random.default_rng(0)
    for _ in range(50):
        q = rng.random(int(rng.integers(1, 30))) ** 3
        target = int(rng.integers(1, len(q) + 3))
        ported, _ = budget_scaled_probabilities(list(q), target)
        exact = budget_scale(q, target)
        assert np.allclose(exact, ported, atol=1e-5)
        assert math.isclose(exact.sum(), min(target, len(q)), abs_tol=1e-6)
        assert exact.max() <= 1.0


@pytest.mark.parametrize("name", [*PRESETS, *VARIANTS])
def test_cases_are_antichains_of_findings(kb, name):
    cfg = PRESETS.get(name) or VARIANTS[name]
    sampler = Sampler(kb, _params(), cfg)
    rng = np.random.default_rng(1)
    onto = kb.ontology
    for gi in sampler.simulable_gene_indices:
        for _ in range(30):
            terms = sampler.sample(gi, rng)
            assert terms and len(terms) == len(set(terms))
            assert all(kb.is_finding(t) for t in terms)
            assert not any(a in terms for t in terms for a in onto.ancestors(t))
            if cfg.off_profile == "none":
                assert A2 not in terms


def test_sampler_interface(kb):
    sampler = Sampler(kb, _params(), PRESETS["real"])
    assert sampler.genes == kb.genes and sampler.n_genes == len(kb.genes)
    assert sampler.simulable_gene_indices == (1, 2, 3, 4, 5, 6)
    with pytest.raises(ValueError):
        sampler.sample(0, np.random.default_rng(0))
    with pytest.raises(ValueError):
        sampler.sample(kb.gene_index["G7"], np.random.default_rng(0))
    a = [sampler.sample(1, np.random.default_rng(7)) for _ in range(3)]
    b = [sampler.sample(1, np.random.default_rng(7)) for _ in range(3)]
    assert a == b


def test_small_profile_fills_without_duplicates(kb):
    p = _params()
    p.count_bins = [[lo, hi, 1.0 if lo == 6 else 0.0] for lo, hi in COUNT_BINS]
    p.count_slope = 0.0
    sampler = Sampler(kb, p, PRESETS["real"])
    rng = np.random.default_rng(3)
    sizes = [len(sampler.sample(kb.gene_index["G6"], rng)) for _ in range(50)]
    assert set(sizes) <= {1, 2} and 2 in sizes


def test_ontology_moves(kb):
    rng = np.random.default_rng(0)
    assert generalize(kb, A111, 2, rng) == A1
    assert generalize(kb, A, 3, rng) == A
    assert specialize(kb, A1, 2, rng, blocked={A11}) == A12
    assert specialize(kb, A1, 2, rng, blocked={A11, A12}) is None
    shown = RelatedTerms(kb)
    shown.add(A11)
    assert shown.related(A1) and shown.related(A111) and not shown.related(A12)
    for _ in range(20):
        t = related_noise_term(kb, [A11], rng, frozenset({A11}), frozenset({A1, A, PA, "HP:0000001"}), shown)
        assert t in (None, A12, A2)


def test_off_profile_needs_a_vocabulary(kb):
    with pytest.raises(ValueError):
        Sampler(kb, _params(off_vocabulary={}), PRESETS["real_noise"])
    assert Sampler(kb, _params(off_vocabulary={}), VARIANTS["real_noise_nbhd"])


def test_covariates(kb):
    cfg = SimConfig("cov", covariates=True)
    sampler = Sampler(kb, _params(), cfg)
    rng = np.random.default_rng(0)
    cases = [sampler.sample_case(1, rng) for _ in range(40)]
    assert {c.sex for c in cases} <= {"male", "female"}
    assert any(c.onset_term == CONGENITAL for c in cases if c.entity == "OMIM:1")


def test_profiler_prepares_and_places(kb):
    prof = Profiler(kb)
    assert prof.prepare([OLD, A1, AD, "HP:0000000"]) == (A11,)
    assert prof.place("G1", A11)[0] == "exact"
    assert prof.place("G1", A1)[0] == "anc1"
    assert prof.place("G1", A)[0] == "anc2"
    assert prof.place("G2", B2)[0] == "off"
    cat, hits = prof.place("G6", A111)
    assert cat == "desc1" and hits == {A11}
    assert prof.explained_share("G1", (A11, A2)) == 0.5


def _case(cid, gene, present, sex=Sex.UNKNOWN):
    return Case(case_id=cid, cohort="t", gene=gene, present=present, excluded=(A2,), sex=sex)


def test_fit_is_global_and_publication_weighted(kb):
    cases = [
        _case("a1", "G1", (A11, A12)),
        _case("a2", "G1", (A11, B2)),
        _case("a3", "G1", (A111,)),
        _case("b1", "G6", (A1, B1), Sex.MALE),
        _case("c1", "G2", (B1, A12, A2)),
        _case("d1", "G1", (A12,)),
    ]
    groups = {"a1": "P1", "a2": "P1", "a3": "P1", "b1": "P2", "c1": "P3", "d1": "P4"}
    status = {"P1": "uncited_e0_knowledge", "P2": "uncited_e0_knowledge", "P3": "uncited_e0_knowledge"}
    status["P4"] = "cited_e0_knowledge"
    p = fit(cases, kb, groups=groups, group_status=status)
    assert p.meta["cases_used"] == 5 and p.meta["publications"] == 3
    assert math.isclose(sum(p.category_shares.values()), 1.0)
    assert math.isclose(sum(b[2] for b in p.count_bins), 1.0)
    assert 0 <= p.gamma <= 4 and 0 < p.f0 <= 1
    assert p.off_alpha > 0 and p.off_beta > 0
    assert p.off_vocabulary == {}
    restored = FittedParams.from_dict(json.loads(json.dumps(p.to_dict())))
    assert restored.params_hash() == p.params_hash()
    everyone = fit(cases, kb, groups=groups, group_status=status, uncited_only=False)
    assert everyone.meta["cases_used"] == 6
    assert everyone.meta["data_hash"] != p.meta["data_hash"]


def test_folds_contract(monkeypatch, tmp_path):
    import hashlib

    group = "PMID:123"
    expected = int(hashlib.sha256(f"diagnostic.ar-training/p3-v1-cv:{group}".encode()).hexdigest(), 16) % 5
    assert folds.fold_of(group) == expected
    assert (folds.FIT_FOLDS, folds.SELECT_FOLD, folds.CONFIRM_FOLD) == ((0, 1, 2), 3, 4)
    monkeypatch.delenv(folds.CONFIRM_ENV, raising=False)
    with pytest.raises(LineageError):
        folds.cases_in([folds.CONFIRM_FOLD], reason="x")
    ledger = tmp_path / "CONFIRM_LEDGER.md"
    monkeypatch.setattr(folds, "CONFIRM_LEDGER", ledger)
    monkeypatch.setenv(folds.CONFIRM_ENV, "1")
    with pytest.raises(LineageError):
        folds.require_confirm("  ")
    folds.require_confirm("final check")
    assert "final check" in ledger.read_text().splitlines()[-1]


def test_presets_are_hashable_and_distinct():
    hashes = {c.config_hash() for c in [*PRESETS.values(), *VARIANTS.values()]}
    assert len(hashes) == len(PRESETS) + len(VARIANTS)
    assert hash(PRESETS["real"]) == hash(SimConfig("real"))
    with pytest.raises(ValueError):
        SimConfig("bad", off_profile="everything")
    assert sum(E0_COUNT_HISTOGRAM.values()) == 1000 and sum(E0_DISTANCE_HISTOGRAM.values()) == 5000
    assert math.isclose(sum(e0_category_shares().values()), 1.0)


def test_explained_bins():
    assert [explained_bin(x) for x in (0.0, 0.25, 0.6, 1.0)] == [0, 1, 2, 3]
    assert _bin_w1([1, 0, 0, 0], [0, 0, 0, 1]) == pytest.approx(0.75)
    assert len(EXPLAINED_BINS) == 4


def test_cli_registered():
    from typer.testing import CliRunner

    from diagnostic_ar_training.cli import app

    out = CliRunner().invoke(app, ["sim4", "--help"])
    assert out.exit_code == 0
    for command in ("knowledge", "fit", "validate", "sample"):
        assert command in out.output
