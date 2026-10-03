import ast
import builtins
import gzip
import math
from pathlib import Path

import numpy as np
import pytest

import diagnostic_ar_training.rerank as rerank_pkg
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import s3_run
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.config import RerankConfig, rr_v1_reference
from diagnostic_ar_training.rerank.features import (
    COMPONENTS,
    MALE_SHARE,
    FeatureParams,
    GeneKnowledge,
    components,
)
from diagnostic_ar_training.rerank.learned import table
from diagnostic_ar_training.systems import Scored

PARENTS = {
    "HP:0000001": (),
    "HP:0000118": ("HP:0000001",),
    "HP:0000707": ("HP:0000118",),
    "HP:0001250": ("HP:0000707",),  # seizure
    "HP:0002373": ("HP:0001250",),  # febrile seizure
    "HP:0001263": ("HP:0000707",),  # developmental delay
    "HP:0000028": ("HP:0000118",),  # cryptorchidism
}
ONTO = Ontology(PARENTS, {}, {}, {}, frozenset())


def disease(phenotypes, onset=(), inheritance=()):
    return {
        "phenotypes": {t: {"freq": f, "onset": [], "sex": s} for t, (f, s) in phenotypes.items()},
        "excluded": [],
        "onset_years": [list(iv) for iv in onset],
        "inheritance": list(inheritance),
    }


KB = {
    "schema": 2,
    "diseases": {
        "D:FEB": disease({"HP:0002373": (0.8, None), "HP:0001263": (0.9, None)}),
        "D:SEIZ": disease({"HP:0001250": (0.1, None), "HP:0001263": (0.9, None)}),
        "D:DD": disease({"HP:0001263": (0.9, None)}),
        "D:NONE": disease({"HP:0000028": (0.5, None)}),
    },
    "genes": {"FEB": {"D:FEB": 1.0}, "SEIZ": {"D:SEIZ": 1.0}, "DD": {"D:DD": 1.0}, "NONE": {"D:NONE": 1.0}},
}


def knowledge(**kw):
    return GeneKnowledge(KB, ONTO, FeatureParams(**kw))


def case(**kw):
    return Case(case_id="c", cohort="t", gene="FEB", present=("HP:0000028",), **kw)


def neg(k, c, gene):
    return components(k, c, gene)["neg_llr"]


def legacy_neg(k, c, gene):
    """The rr-v1 negation loop as it was before the forms were added."""
    out = 0.0
    for term in c.excluded:
        out += math.log(1.0 - k.params.neg_strength * k.term_probability(gene, term))
    return out


EXCLUDED_SETS = [
    (),
    ("HP:0001250",),
    ("HP:0001263",),
    ("HP:0001250", "HP:0001263"),
    ("HP:0001250", "HP:0002373", "HP:0001250"),
    ("HP:0000707", "HP:0000028"),
]


def test_llr_with_default_params_is_byte_identical_to_the_legacy_loop():
    k = knowledge()
    for excluded in EXCLUDED_SETS:
        for gene in ("FEB", "SEIZ", "DD", "NONE", "ABSENT"):
            c = case(excluded=excluded, sex=Sex.MALE, age_years=3.0)
            comp = components(k, c, gene)
            assert comp["neg_llr"] == (legacy_neg(k, c, gene) if k.diseases(gene) else 0.0)


def test_rr_v1_reference_config_reproduces_the_current_code_path():
    ref = rr_v1_reference()
    assert np.array_equal(ref.beta(), s3_run.rr_v1_beta(neg=0.5))
    assert ref.feature_params() == FeatureParams()

    class Base:
        genes = ("FEB", "SEIZ", "DD", "NONE")

        def score(self, c):
            return Scored(np.array([0.4, 0.3, 0.2, 0.1]), {})

    k_ref, k_old = ref.knowledge(KB, ONTO), GeneKnowledge(KB, ONTO)
    for excluded in EXCLUDED_SETS:
        c = case(excluded=excluded)
        a, b = table(Base(), k_ref, c, 4), table(Base(), k_old, c, 4)
        assert np.array_equal(a.x, b.x)
        old = b.combine(s3_run.rr_v1_beta(neg=0.5))
        assert a.combine(ref.beta()).tobytes() == old.tobytes()


def test_gated_drops_terms_below_tau():
    c = case(excluded=("HP:0001250", "HP:0001263"))  # SEIZ: P = 0.1 and 0.9
    full = neg(knowledge(), c, "SEIZ")
    gated = neg(knowledge(neg_form="gated", neg_tau=0.4), c, "SEIZ")
    assert full == pytest.approx(math.log(1 - 0.05) + math.log(1 - 0.45))
    assert gated == pytest.approx(math.log(1 - 0.45))
    p_low = knowledge().term_probability("SEIZ", "HP:0001250")
    assert neg(knowledge(neg_form="gated", neg_tau=p_low), c, "SEIZ") == pytest.approx(full)
    assert neg(knowledge(neg_form="gated", neg_tau=0.95), c, "SEIZ") == 0.0
    assert neg(knowledge(neg_form="gated", neg_tau=0.0), c, "SEIZ") == pytest.approx(full)


def test_capped_floors_the_total_in_log_units():
    c = case(excluded=("HP:0001250", "HP:0001263"))  # FEB: P = 0.8 and 0.9
    total = math.log(1 - 0.4) + math.log(1 - 0.45)
    assert neg(knowledge(), c, "FEB") == pytest.approx(total)
    assert neg(knowledge(neg_form="capped", neg_cap=0.7), c, "FEB") == pytest.approx(-0.7)
    assert neg(knowledge(neg_form="capped", neg_cap=5.0), c, "FEB") == pytest.approx(total)
    assert neg(knowledge(neg_form="capped", neg_cap=0.7), c, "NONE") == 0.0


def test_propagated_reaches_descendants_without_double_counting():
    k = knowledge(neg_form="propagated")
    one = math.log(1 - 0.5 * 0.8)
    parent_only = case(excluded=("HP:0001250",))
    # FEB annotates only febrile seizure; "no seizure" reaches it through P(t or any descendant).
    assert k.term_probability("FEB", "HP:0001250") == pytest.approx(0.8)
    assert neg(k, parent_only, "FEB") == pytest.approx(one)
    assert neg(k, parent_only, "NONE") == 0.0
    # Parent, its excluded child and a repeat are one "no": the child adds nothing.
    both = case(excluded=("HP:0001250", "HP:0002373", "HP:0001250"))
    assert neg(k, both, "FEB") == pytest.approx(one)
    assert neg(knowledge(), both, "FEB") == pytest.approx(3 * one)
    # A "no" to the child alone says nothing about a gene annotating only the parent.
    child_only = case(excluded=("HP:0002373",))
    assert neg(k, child_only, "FEB") == pytest.approx(one)
    assert neg(k, child_only, "SEIZ") == 0.0
    # Unrelated terms still add up; only ancestor-descendant pairs collapse.
    mixed = case(excluded=("HP:0001250", "HP:0001263", "HP:0002373"))
    assert neg(k, mixed, "FEB") == pytest.approx(one + math.log(1 - 0.5 * 0.9))


def test_annotated_share_is_the_same_in_every_form():
    c = case(excluded=("HP:0001250", "HP:0000028"))
    shares = {
        components(knowledge(**kw), c, "FEB")["neg_annotated_share"]
        for kw in (
            {},
            {"neg_form": "gated", "neg_tau": 0.5},
            {"neg_form": "capped", "neg_cap": 1.0},
            {"neg_form": "propagated"},
        )
    }
    assert shares == {0.5}


def test_invalid_parameters_are_rejected():
    for kw in (
        {"neg_form": "bogus"},
        {"neg_form": "gated"},
        {"neg_form": "gated", "neg_tau": 1.5},
        {"neg_form": "capped"},
        {"neg_form": "capped", "neg_cap": 0.0},
        {"neg_form": "llr", "neg_tau": 0.2},
        {"neg_form": "gated", "neg_tau": 0.2, "neg_cap": 1.0},
        {"neg_strength": 1.0},
    ):
        with pytest.raises(ValueError):
            FeatureParams(**kw)


def test_config_round_trip_and_hash_are_stable():
    cfg = RerankConfig(
        "kb-v6", neg_form="gated", neg_strength=0.8, neg_tau=0.2, weights={"neg_llr": 1.5, "sex_prior": 0.5}
    )
    again = RerankConfig.from_json(cfg.to_json())
    assert again == cfg and again.config_hash == cfg.config_hash
    assert list(cfg.weights) == list(COMPONENTS)
    reordered = RerankConfig(
        "kb-v6", neg_form="gated", neg_strength=0.8, neg_tau=0.2, weights={"sex_prior": 0.5, "neg_llr": 1.5}
    )
    assert reordered.config_hash == cfg.config_hash
    assert RerankConfig("kb-v6", weights={"neg_llr": 1.5}).config_hash != cfg.config_hash
    assert rr_v1_reference().config_hash == "8488e32fc7c2"
    with pytest.raises(ValueError):
        RerankConfig("kb-v6", weights={"neg": 1.0})
    with pytest.raises(ValueError):
        RerankConfig("kb-v6", neg_form="capped")


def test_l3_sex_prior_follows_male_share_by_inheritance():
    for term, share in MALE_SHARE:
        kb = {
            **KB,
            "diseases": {"D:X": disease({"HP:0001263": (0.9, None)}, inheritance=[term])},
            "genes": {"X": {"D:X": 1.0}},
        }
        k = GeneKnowledge(kb, ONTO, FeatureParams())
        male = components(k, case(sex=Sex.MALE), "X")["sex_prior"]
        female = components(k, case(sex=Sex.FEMALE), "X")["sex_prior"]
        assert male == pytest.approx(math.log(max(0.01, share) / 0.5))
        assert female == pytest.approx(math.log(max(0.01, 1 - share) / 0.5))
    assert components(knowledge(), case(sex=Sex.MALE), "FEB")["sex_prior"] == 0.0


def test_l3_age_components_read_only_kb_onset_years():
    kb = {
        **KB,
        "diseases": {"D:X": disease({"HP:0001263": (0.9, None)}, onset=[(2.0, 11.0), (18.0, 65.0)])},
        "genes": {"X": {"D:X": 1.0}},
    }
    k = GeneKnowledge(kb, ONTO, FeatureParams())
    comp = components(k, case(age_years=11.0), "X")
    assert comp["age_mean"] == pytest.approx(math.log(0.5))
    assert comp["age_any"] == pytest.approx(0.0)
    assert components(k, case(age_years=1.0), "X")["age_any"] == pytest.approx(math.log(0.01))


FORBIDDEN_STRINGS = ("onset-ages", "onset_ages", "presentation-ages", "presentation_ages")
FORBIDDEN_IMPORTS = ("lit_build", "lit_extract", "cli_lit_extract", "simulator", "knowledge.sex_prior")


def rerank_sources():
    return sorted(Path(rerank_pkg.__file__).parent.glob("*.py"))


def test_no_rerank_module_names_or_imports_an_onset_ages_artifact():
    assert len(rerank_sources()) >= 6
    for path in rerank_sources():
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not any(s in node.value.lower() for s in FORBIDDEN_STRINGS), (path.name, node.value)
            if isinstance(node, ast.Name | ast.Attribute):
                name = node.id if isinstance(node, ast.Name) else node.attr
                assert not any(s in name.lower() for s in FORBIDDEN_STRINGS), (path.name, name)
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [f"{node.module}.{a.name}" for a in node.names]
            else:
                continue
            assert not any(f in n for n in names for f in FORBIDDEN_IMPORTS), (path.name, names)


def test_scoring_never_opens_an_onset_ages_file(monkeypatch):
    opened = []
    real_open, real_gzip, real_path_open = builtins.open, gzip.open, Path.open

    def guard(real):
        def wrapper(file, *a, **kw):
            opened.append(str(file))
            if "onset-ages" in str(file) or "onset_ages" in str(file):
                raise AssertionError(f"onset-ages artifact opened: {file}")
            return real(file, *a, **kw)

        return wrapper

    monkeypatch.setattr(builtins, "open", guard(real_open))
    monkeypatch.setattr(gzip, "open", guard(real_gzip))
    monkeypatch.setattr(Path, "open", lambda self, *a, **kw: guard(real_path_open)(self, *a, **kw))
    k = knowledge(neg_form="propagated")
    c = case(excluded=("HP:0001250",), sex=Sex.MALE, age_years=3.0, onset_years=0.0)
    for gene in ("FEB", "SEIZ", "DD", "NONE"):
        components(k, c, gene)
    assert not any("onset-ages" in f or "onset_ages" in f for f in opened)
