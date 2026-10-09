"""ft-v1 (Phase 2 Track 3): knowledge, features, the numpy residual, the grid rules, the sealed-read refusals.

Everything here runs without torch or data; the torch tests skip without torch.
"""

import json
import math

import numpy as np
import pytest
from typer.testing import CliRunner

from diagnostic_ar_training import splits
from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import safe_eval
from diagnostic_ar_training.ft import configs
from diagnostic_ar_training.ft import knowledge as ft_knowledge
from diagnostic_ar_training.ft.bundle import (
    COVARIATES,
    FEATURES,
    FORMAT,
    FtResidual,
    Knowledge,
    covariates,
    member_weights,
    softmax64,
)
from diagnostic_ar_training.ft.system import E0Logits, E0System, FtV1, case_inputs
from diagnostic_ar_training.lineage import gitinfo, ledger, manifest
from diagnostic_ar_training.safe import knowledge as safe_knowledge
from diagnostic_ar_training.safe import overrides as curation

K = len(FEATURES)
PARENTS = {"HP:3": {"HP:2"}, "HP:2": {"HP:1"}, "HP:1": set(), "HP:9": set(), "HP:7": set()}


def ancestors(term):
    out, stack = set(), [term]
    while stack:
        for p in PARENTS.get(stack.pop(), ()):
            if p not in out:
                out.add(p)
                stack.append(p)
    return out


def annotations():
    ann = safe_knowledge.Annotations()
    ann.names.update(
        {
            "OMIM:1": "Spermatogenic failure 1",
            "OMIM:2": "Premature ovarian failure 2",
            "OMIM:4": "Adult-onset ataxia",
            "OMIM:5": "Childhood epilepsy",
            "OMIM:6": "X-linked thing",
            "OMIM:7": "X-linked dominant thing",
            "OMIM:8": "Generic X-linked thing",
        }
    )
    ann.inheritance.update(
        {
            "OMIM:6": {"HP:0001419"},
            "OMIM:7": {"HP:0001423"},
            "OMIM:8": {"HP:0001417"},
            "OMIM:10": {"HP:0001417", "HP:0001419"},
        }
    )
    ann.onset_terms.update({"OMIM:4": {"HP:0003581"}, "OMIM:5": {"HP:0011463"}})
    ann.phenotypes.update(
        {
            "OMIM:4": [("HP:3", "HP:0040280"), ("HP:9", "1/2")],
            "OMIM:5": [("HP:3", "5/5")],
            "OMIM:6": [("HP:7", "1/3")],
        }
    )
    return ann


G2D = {
    "MALE1": {"OMIM:1"},
    "FEMALE1": {"OMIM:2"},
    "ADULT": {"OMIM:4"},
    "CHILD": {"OMIM:5"},
    "XLR": {"OMIM:6"},
    "XLD": {"OMIM:7"},
    "XLGEN": {"OMIM:8"},
    "XLGEN_XLR": {"OMIM:6", "OMIM:10"},
    "MIXED": {"OMIM:4", "OMIM:99"},
}
GENES = (*G2D, "NOTHING")
# Toy embeddings: HP:3 and HP:7 point the same way; HP:9 is orthogonal; HP:2 has no row.
EMB_INDEX = {"HP:3": 0, "HP:7": 1, "HP:9": 2, "HP:1": 3}
VECTORS = np.array([[1, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float32)


def override(gene, rule="sex", action="remove", value=None):
    return curation.Override(gene, rule, action, value, "quote", "file", "tester")


@pytest.fixture(scope="module")
def built():
    rows = [override("FEMALE1"), override("ADULT")]  # the second has no sex rule: skipped
    return ft_knowledge.build(GENES, G2D, annotations(), {}, {}, ancestors, rows)


@pytest.fixture(scope="module")
def know(built):
    return Knowledge(built[0], GENES, (EMB_INDEX, VECTORS), "ft-kb-x")


def idx(gene):
    return GENES.index(gene)


def test_knowledge_extras_and_overrides(built):
    kb, stats = built
    g = kb["genes"]
    assert kb["schema"] == "ft-kb/2"
    # X-linked recessive only means HP:0001419 alone; generic X-linked (HP:0001417) does not count.
    assert [x for x in GENES if g[x].get("xlr_only")] == ["XLR"]
    assert not any("xld_only" in r for r in g.values())
    assert stats["xlr_only"] == 1 and stats["xl_generic_not_xlr_only"] == 2
    assert g["ADULT"]["lenient_onset_years"] == 16 and g["MIXED"]["lenient_onset_years"] == 16
    assert "onset" not in kb["safe"]["genes"]["MIXED"]  # OMIM:99 has no onset: not strict
    assert g["ADULT"]["profile"] == ["HP:3", "HP:9"] and g["NOTHING"]["profile"] == []
    assert (
        "sex" not in kb["safe"]["genes"]["FEMALE1"] and kb["safe"]["genes"]["MALE1"]["sex"]["limit"] == "male"
    )
    assert kb["overrides_skipped"] == [
        {"gene": "ADULT", "rule": "sex", "action": "remove", "why": "rule absent"}
    ]
    assert stats["overrides_applied"] == 1 and stats["overrides_skipped"] == 1


def test_features_follow_each_known_input(know):
    f = know.features({"sex": "female", "onset_years": 2.0, "age_years": 30.0, "excluded": ["HP:3"]})
    i = {k: FEATURES.index(k) for k in FEATURES}
    assert (
        f[i["sex_mismatch"], idx("MALE1")] == 1 and f[i["sex_mismatch"], idx("FEMALE1")] == 0
    )  # curated away
    assert f[i["xlr_female"], idx("XLR")] == 1 and f[i["xlr_female"]].sum() == 1
    assert f[i["xlr_female"], idx("XLGEN")] == 0 and f[i["xlr_female"], idx("XLGEN_XLR")] == 0
    # Onset 2 y (not the age 30): ADULT starts at 16 -> late by 14; CHILD at 1 -> not late.
    assert f[i["onset_strict_late"], idx("ADULT")] == 1 and f[i["onset_strict_late"], idx("CHILD")] == 0
    assert math.isclose(f[i["onset_strict_gap"], idx("ADULT")], math.log1p(14), rel_tol=1e-6)
    assert f[i["onset_strict_gap"], idx("MIXED")] == 0 and f[i["onset_lenient_gap"], idx("MIXED")] > 0
    # HP:3 is obligate in every annotated disease of ADULT and CHILD.
    assert f[i["neg_obligate"], idx("ADULT")] == 1 and f[i["neg_obligate"], idx("CHILD")] == 1
    assert f[i["neg_obligate"], idx("XLR")] == 0
    # neg_embed: HP:3 vs XLR's HP:7 (same direction) = 1; ADULT annotates HP:3 itself; NOTHING has no profile.
    assert math.isclose(f[i["neg_embed"], idx("XLR")], 1.0, rel_tol=1e-6)
    assert f[i["neg_embed"], idx("NOTHING")] == 0 and (f >= 0).all()


def test_unknown_inputs_give_zero_features(know):
    assert not know.features({"sex": "unknown", "present": ["HP:3"]}).any()
    assert not know.features({}).any()
    male = know.features({"sex": "male"})
    assert male[FEATURES.index("sex_mismatch")].sum() == 0  # FEMALE1 was curated out
    assert not male[:, idx("XLD")].any() and not male[FEATURES.index("xlr_female")].any()
    assert "xld_male" not in FEATURES and len(FEATURES) == 7


def test_negative_ages_count_as_zero(know):
    f = know.features({"onset_years": -0.5})
    assert f[FEATURES.index("onset_strict_late"), idx("CHILD")] == 1  # starts at 1 y > 0


def member(theta, mlp=None, features=FEATURES, covs=COVARIATES):
    return {
        "active_features": list(features),
        "active_covariates": list(covs),
        "theta": list(theta),
        "mlp": mlp,
    }


def bundle_of(*members):
    return {
        "format": FORMAT,
        "kb_id": "k",
        "features": list(FEATURES),
        "covariates": list(COVARIATES),
        "members": list(members),
    }


def test_untrained_residual_is_exactly_e0(know):
    logits = np.linspace(-50, 300, len(GENES)).astype(np.float32)
    inputs = {"sex": "female", "onset_years": 2.0, "excluded": ["HP:3"], "present": ["HP:9"]}
    res = FtResidual(bundle_of(member([0.0] * len(FEATURES))), know)
    out = res.apply(logits, inputs)
    assert np.array_equal(out, softmax64(logits)) and not res.residual(inputs).any()


def test_residual_only_lowers_and_ignores_negative_theta(know):
    theta = [1.0, 2.0, 0.5, 0.5, 1.0, 3.0, -5.0]  # a negative θ counts as 0
    res = FtResidual(bundle_of(member(theta)), know)
    inputs = {"sex": "female", "onset_years": 2.0, "excluded": ["HP:3"]}
    r = res.residual(inputs)
    assert (r <= 0).all() and r[idx("NOTHING")] == 0
    w = member_weights(member(theta), covariates(inputs))
    assert (w <= 0).all() and w[FEATURES.index("neg_embed")] == 0
    assert math.isclose(r[idx("MALE1")], -1.0)
    # Present-only input: no feature fires, whatever the weights.
    assert not res.residual({"present": ["HP:9"]}).any()


def test_mlp_modulation_starts_at_one_and_ensemble_averages(know):
    k, c, h = len(FEATURES), len(COVARIATES), 4
    rng = np.random.default_rng(0)
    mlp = {"w1": rng.normal(size=(h, c)).tolist(), "b1": [0.1] * h, "w2": [[0.0] * h] * k, "b2": [0.0] * k}
    theta = [1.0] * k
    z = covariates({"sex": "male", "age_years": 3.0})
    assert np.allclose(member_weights(member(theta, mlp), z), -1.0)
    inactive = member(theta, features=("sex_mismatch",))
    assert np.count_nonzero(member_weights(inactive, z)) == 1
    two = FtResidual(bundle_of(member(theta), member([0.0] * k)), know)
    one = FtResidual(bundle_of(member(theta)), know)
    inputs = {"sex": "female"}
    assert np.allclose(two.residual(inputs), one.residual(inputs) / 2)


def test_bundle_guards(know, built):
    with pytest.raises(ValueError, match="bundle"):
        FtResidual({**bundle_of(member([0.0] * K)), "format": "x"}, know)
    with pytest.raises(ValueError, match="bundle"):
        FtResidual({**bundle_of(member([0.0] * K)), "format": "ft-v1-bundle/1"}, know)
    with pytest.raises(ValueError, match="features"):
        FtResidual({**bundle_of(member([0.0] * K)), "features": [*FEATURES, "xld_male"]}, know)
    with pytest.raises(ValueError, match="embeddings"):
        FtResidual(bundle_of(member([0.0] * (K - 1) + [1.0])), Knowledge(built[0], GENES, None))
    with pytest.raises(ValueError, match="classifier"):
        FtResidual(bundle_of({**member([0.0] * K), "classifier_delta": "x.npz"}), know)
    with pytest.raises(ValueError, match="ft-kb/2"):
        Knowledge({**built[0], "schema": "ft-kb/1"}, GENES)


def test_covariates_layout():
    z = covariates({"sex": "female", "age_years": -1.0, "present": ["a", "a", "b"], "excluded": ["c"]})
    assert z.tolist() == pytest.approx([0, 1, 0, 1, 0, 0, math.log1p(2), math.log1p(1)])


class FakeBase:
    """E0 stand-in: logits from the number of present terms, over the toy vocabulary."""

    genes = GENES

    class inputs:  # noqa: N801
        emb_index = EMB_INDEX

        @staticmethod
        def known_present(case):
            known = [t for t in case.present if t.startswith("HP:")]
            return known, {"n_present": len(case.present)}

    def logits(self, known):
        base = np.arange(len(GENES), dtype=np.float32)[::-1].copy()
        base[GENES.index("MALE1")] = 100 + len(known)
        return base, tuple(known)

    def lineage_inputs(self):
        return []


def test_system_matches_apply_and_e0(know):
    e0 = E0Logits(FakeBase())
    theta = [200.0] + [0.0] * (K - 1)
    system = FtV1(e0, FtResidual(bundle_of(member(theta)), know), "ft")
    woman = Case(case_id="a", cohort="c", gene="ADULT", present=("HP:9",), sex=Sex.FEMALE)
    nobody = Case(case_id="b", cohort="c", gene="ADULT", present=("x",))
    scored = system.score(woman)
    logits, _ = e0(woman)
    assert np.array_equal(scored.probs, system.residual.apply(logits, case_inputs(woman)))
    assert scored.probs.argmax() != GENES.index("MALE1") and scored.info["ft_lowered"] == 1
    assert np.array_equal(
        system.score(woman.model_copy(update={"sex": Sex.UNKNOWN})).probs, softmax64(logits)
    )
    assert system.score(nobody).probs is None and E0System(e0).score(nobody).probs is None


# Grid rules


def test_ablation_keeps_negation_only():
    abl = configs.config("c1-lin-all-nosexage")
    assert abl["features"] == ("neg_obligate", "neg_embed")
    assert abl["covariates"] == ("log1p_n_present", "log1p_n_excluded")
    assert configs.config("c2-lin-safe3-nosexage")["features"] == ("neg_obligate",)
    with pytest.raises(ValueError):
        configs.config("c9-nope")


def test_grid_is_the_preregistered_budget():
    assert len(configs.CONFIGS) == 8
    assert set(configs.SELECTABLE) == set(configs.CONFIGS) - {"c7-cls-l2sp1e-2", "c8-cls-l2sp1e-4"}
    assert configs.n_parameters("c1-lin-all") == 7
    assert configs.n_parameters("c3-lin-noxl") == 6 and "xlr_female" not in configs.NO_XL
    assert configs.n_parameters("c4-mlp16") == 7 + 8 * 16 + 16 + 16 * 7 + 7
    assert configs.n_parameters("c7-cls-l2sp1e-2") > 5229 * 512


def agg(delta, harmed=0.001, seeds=(0, 1, 2)):
    return {"seeds": list(seeds), "dev_delta": {"mean": delta}, "dev_harmed": {"mean": harmed}, "valid": True}


def test_selection_prefers_fewer_parameters_within_the_margin():
    out = configs.select({"c4-mlp16": agg(0.0030), "c1-lin-all": agg(0.0027), "c2-lin-safe3": agg(0.0020)})
    assert out["selected"] == "c1-lin-all"  # c2 is 0.001 below the best, outside the margin
    out = configs.select({"c4-mlp16": agg(0.0030), "c2-lin-safe3": agg(0.0026)})
    assert out["selected"] == "c2-lin-safe3"


def test_selection_excludes_classifier_harm_and_missing_seeds():
    out = configs.select(
        {
            "c7-cls-l2sp1e-2": agg(0.05),
            "c1-lin-all": agg(0.002, harmed=0.06),
            "c4-mlp16": agg(0.003, seeds=(0, 1)),
            "c2-lin-safe3": agg(0.001),
        }
    )
    assert out["selected"] == "c2-lin-safe3"
    assert configs.select({"c1-lin-all": agg(-0.001)})["selected"] is None
    assert configs.select({"c7-cls-l2sp1e-2": agg(0.05)})["selected"] is None


# Torch


def test_torch_residual_matches_numpy_and_starts_at_zero(know):
    torch = pytest.importorskip("torch")
    from diagnostic_ar_training.ft.model import ResidualNet

    torch.manual_seed(0)
    model = ResidualNet(hidden=4)
    inputs = [{"sex": "female", "onset_years": 2.0, "excluded": ["HP:3"]}, {"sex": "male", "age_years": 40.0}]
    feats = torch.from_numpy(np.stack([know.features(i) for i in inputs]))
    z = torch.from_numpy(np.stack([covariates(i) for i in inputs]))
    assert torch.count_nonzero(model(feats, z)) == 0
    target = torch.tensor([GENES.index("ADULT"), GENES.index("MALE1")])
    torch.nn.functional.cross_entropy(model(feats, z), target).backward()
    assert model.theta.grad.abs().sum() > 0  # θ learns from the first step
    with torch.no_grad():
        model.theta.copy_(torch.tensor([1.0, 2.0, 0.5, 0.5, 1.0, 3.0, -1.0]))
        model.mlp[2].weight.normal_()
    model.project()
    assert model.theta[-1] == 0
    res = FtResidual(bundle_of(model.member()), know)
    with torch.no_grad():
        torch_r = model(feats, z).double().numpy()
    numpy_r = np.stack([res.residual(i) for i in inputs])
    assert np.abs(torch_r - numpy_r).max() < 1e-5 and (numpy_r <= 0).all()


def test_fit_runs_and_epoch_zero_is_e0(know):
    pytest.importorskip("torch")
    from diagnostic_ar_training.ft import train as ft_train

    rng = np.random.default_rng(1)
    inputs = [{"sex": ["male", "female"][i % 2], "onset_years": float(i % 20)} for i in range(40)]
    feats = np.stack([know.features(i) for i in inputs])
    z = np.stack([covariates(i) for i in inputs])
    logits = rng.normal(size=(40, len(GENES))).astype(np.float32)
    target = np.array([GENES.index("CHILD")] * 40)
    part = ft_train.to_part([str(i) for i in range(40)], logits, feats, z, target, "cpu")
    trn, val = part.rows({str(i) for i in range(30)}), part.rows({str(i) for i in range(30, 40)})
    cfg = ft_train.FitConfig(hidden=4, max_epochs=5, patience=2, batch_size=8)
    result = ft_train.fit(cfg, trn, val, log=lambda *_: None)
    e0_val = ft_train.evaluate(ft_train.ResidualNet().to("cpu"), val)
    assert result.history[0]["val"] == e0_val and (result.model.theta >= 0).all()
    with pytest.raises(ValueError):
        ft_train.FitConfig(classifier=True, lr_classifier=1e-3)
    with pytest.raises(ValueError):
        ft_train.FitConfig(l2sp=0.1)


def test_inner_split_is_by_group_and_stable():
    from diagnostic_ar_training.ft.configs import inner_split

    groups = {f"c{i}": f"g{i // 3}" for i in range(300)}
    held = inner_split(groups, list(groups))
    assert held == inner_split(groups, list(groups)[::-1])
    assert all({f"c{3 * (int(c[1:]) // 3) + k}" for k in range(3)} <= held for c in held)
    assert 0.1 < len(held) / 300 < 0.3


def test_pseudo_patients_drop_r1_overlaps():
    from diagnostic_ar_training.ft.replay import pseudo_patients

    kb = {"genes": {"A": {"profile": ["HP:1", "HP:2", "HP:3"]}, "B": {"profile": []}}}
    out, stats = pseudo_patients(kb, ("A", "B"), {"HP:1", "HP:2", "HP:3"}, set(), per_gene=50, max_terms=12)
    assert stats["genes"] == 1 and all(g == 0 and 1 <= len(t) <= 3 for g, t in out)
    exclude = {("A", frozenset({t})) for t in ("HP:1", "HP:2", "HP:3")}
    out2, stats2 = pseudo_patients(kb, ("A", "B"), {"HP:1", "HP:2", "HP:3"}, exclude, per_gene=50)
    assert stats2["dropped_overlapping_r1"] > 0 and all(len(t) > 1 for _, t in out2)


# The sealed read

ARGS = ["ft", "confirm", "--exp", "EXP-P-003", "--split", "p2-v1", "--part", "test", "--bundle", "b"]
REASON = ["--reason", "pre-registered confirmation"]
CLEAN = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=False)
DIRTY = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=True)


class Touched(Exception):
    pass


@pytest.fixture
def tripwires(monkeypatch):
    def boom(*a, **k):
        raise Touched

    monkeypatch.setattr(splits, "load_part", boom)
    monkeypatch.setattr(splits, "publication_groups", boom)
    monkeypatch.setattr(manifest, "load_manifest", boom)
    monkeypatch.setattr(manifest, "fetch_outputs", boom)
    monkeypatch.setattr(manifest, "ensure_new", boom)
    monkeypatch.setattr(ledger, "record_access", boom)


@pytest.fixture
def good(monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-003")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)


def run(args):
    return CliRunner().invoke(app, args, env={"COLUMNS": "400"})


def refused(result, text):
    return result.exit_code != 0 and not isinstance(result.exception, Touched) and text in result.output


def test_confirm_tripwires_are_live_once_every_check_passes(tripwires, good):
    assert isinstance(run(ARGS + REASON).exception, Touched)


def test_confirm_refusals_come_in_order_and_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.delenv("DXT_SEALED_READ")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: False)
    monkeypatch.setattr(safe_eval, "code_state", lambda: DIRTY)
    assert refused(run(ARGS), "DXT_SEALED_READ=EXP-P-003")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-001")
    assert refused(run(ARGS), "DXT_SEALED_READ=EXP-P-003")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-003")
    assert refused(run(ARGS), "committed")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    assert refused(run(ARGS), "uncommitted")
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)
    assert refused(run(ARGS), "reason is required")


def test_confirm_refuses_malformed_requests_and_reopened_vaults(tripwires, good):
    base = ["ft", "confirm", "--exp", "EXP-P-003", "--bundle", "b", *REASON]
    for args in (
        [*base, "--split", "p2-v1", "--part", "dev"],
        [*base, "--split", "r1-v1", "--part", "test"],
        [*base, "--split", "p2-v1", "--part", "vault"],
        [
            "ft",
            "confirm",
            "--exp",
            "EXP-Z-001",
            "--bundle",
            "b",
            "--split",
            "p2-v1",
            "--part",
            "test",
            *REASON,
        ],
    ):
        result = run(args)
        assert result.exit_code != 0 and not isinstance(result.exception, Touched)
    vault = [*base, "--split", "p2-v1", "--split", "p2-fresh-v1", "--part", "vault"]
    assert isinstance(run(vault).exception, Touched)
    ledger.LEDGER.write_text("| 2026-10-20T00:00:00+00:00 | p2-v1/vault | EXP-P-003 | abc | r |\n")
    assert refused(run(vault), "already opened")


def test_grid_refuses_unknown_configurations_before_loading(tripwires):
    result = run(["ft", "grid", "--config", "c9-nope"])
    assert result.exit_code != 0 and not isinstance(result.exception, Touched)


def test_bundle_json_round_trip(tmp_path, know):
    from diagnostic_ar_training.ft.bundle import load

    path = tmp_path / "b.json"
    path.write_text(json.dumps(bundle_of(member([0.5] * K))))
    assert FtResidual(load(path), know).residual({"sex": "female"}).min() < 0
    path.write_text(json.dumps({"format": "other"}))
    with pytest.raises(ValueError):
        load(path)


def test_kb_mask_scope_must_be_all_or_none(tripwires):
    result = run(["ft", "kb", "--id", "ft-kb-x", "--mask-scope", "heldout"])
    assert refused(result, "must be one of")


def test_kb_with_no_mask_keeps_every_row(tmp_path):
    header = "database_id\tdisease_name\tqualifier\thpo_id\treference\tevidence\tonset\tfrequency\tsex\t"
    header += "modifier\taspect\tbiocuration\n"
    rows = [
        "OMIM:1\tD\t\tHP:0001419\tPMID:1\tPCS\t\t\t\t\tI\tx\n",
        "OMIM:1\tD\t\tHP:0001423\tPMID:2\tPCS\t\t\t\t\tI\tx\n",
    ]
    path = tmp_path / "phenotype.hpoa"
    path.write_text("#comment\n" + header + "".join(rows))
    masked = safe_knowledge.read_annotations(path, ["PMID:2"])
    unmasked = safe_knowledge.read_annotations(path, [])
    assert masked.inheritance["OMIM:1"] == {"HP:0001419"}
    assert unmasked.inheritance["OMIM:1"] == {"HP:0001419", "HP:0001423"}
    assert ft_knowledge.xlr_only(masked.inheritance["OMIM:1"])
    assert not ft_knowledge.xlr_only(unmasked.inheritance["OMIM:1"])
    assert unmasked.stats["rows_masked_heldout_pmid"] == 0


def test_prod_bundle_refuses_its_own_fitting_knowledge(tripwires):
    args = ["ft", "prod-bundle", "--id", "x", "--from", "b", "--kb", "ft-kb-all-v2"]
    assert refused(run(args), "use the source bundle itself")


def test_prod_package_refuses_a_directory_without_the_module(tripwires, tmp_path):
    assert refused(run(["ft", "prod-package", "--out", str(tmp_path)]), "no committed")
