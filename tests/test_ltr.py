import json
import math

import numpy as np
import pytest
import typer
from typer.testing import CliRunner

from diagnostic_ar_training import cli_ltr, splits
from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import harness, ltr_eval, safe_eval
from diagnostic_ar_training.lineage import gitinfo, ledger, manifest
from diagnostic_ar_training.ltr import bundle, knowledge, train
from diagnostic_ar_training.ltr.system import LtrV1, case_inputs
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.systems import Scored

# Toy ontology: HP:3 is_a HP:2 is_a HP:1 is_a HP:0000118; HP:4 is_a HP:1; HP:9 is_a HP:0000118. HP:99 -> HP:3.
PARENTS = {
    "HP:0000001": (),
    "HP:0000118": ("HP:0000001",),
    "HP:1": ("HP:0000118",),
    "HP:2": ("HP:1",),
    "HP:3": ("HP:2",),
    "HP:4": ("HP:1",),
    "HP:9": ("HP:0000118",),
}
ONTOLOGY = Ontology(PARENTS, {}, {"HP:99": "HP:3"}, {}, frozenset())
AD = "HP:0000006"


def disease(phenotypes, inheritance=(), onset=()):
    return {
        "phenotypes": {t: {"freq": f, "onset": [], "sex": None} for t, f in phenotypes.items()},
        "inheritance": list(inheritance),
        "onset_years": [list(iv) for iv in onset],
    }


RERANK_KB = {
    "schema": 2,
    "diseases": {
        "D1": disease({"HP:3": 1.0, "HP:9": 0.5}, [bundle.XLR], [(16, 100)]),
        "D2": disease({"HP:4": 0.9, "HP:9": None}, [AD], [(0, 1)]),
        "D3": disease({"HP:2": 0.1}, [bundle.XLD]),
    },
    "genes": {"G1": {"D1": 1.0}, "G2": {"D2": 1.0}, "G3": {"D3": 1.0}, "G4": {"D1": 0.5, "D2": 0.5}},
    "vocabulary": {},
}
SAFE = {
    "format": "safe-v1-bundle/1",
    "kb_id": "toy-safe",
    "negation_factor": 0.1,
    "onset_factor": 0.01,
    "genes": {"G1": {"earliest_onset_years": 16}, "G3": {"sex": "male"}},
    "obligate": {"G1": {"D1": ["HP:3"]}},
    "ancestors_or_self": {"HP:3": ["HP:0000118", "HP:1", "HP:2", "HP:3"]},
}
VOCAB = ("G1", "G2", "G3", "G4", "G5")


@pytest.fixture(scope="module")
def built():
    return knowledge.build(RERANK_KB, SAFE, ONTOLOGY, VOCAB)


@pytest.fixture(scope="module")
def know(built):
    return bundle.Knowledge(built[0])


def feats(know, inputs):
    top = np.arange(len(VOCAB))
    x = know.features(VOCAB, top, inputs, np.log(np.full(len(VOCAB), 0.2)))
    return {name: dict(zip(VOCAB, x[:, i], strict=True)) for i, name in enumerate(bundle.NAMES)}


# Knowledge


def test_knowledge_records_onset_inheritance_and_statistics(built):
    kb, stats = built
    g = kb["genes"]
    assert g["G1"]["lenient_onset_years"] == 16 and g["G1"]["xlr_only"]
    assert g["G4"]["lenient_onset_years"] == 0 and "xlr_only" not in g["G4"]
    assert g["G3"]["xld_only"] and g["G5"] == {"diseases": {}}
    assert kb["resolve"] == {"HP:99": "HP:3"}
    assert kb["diseases"]["D2"] == [["HP:4", 0.9], ["HP:9", None]]
    # IC over the three diseases: HP:1 is reached by all of them, HP:3 by D1 only.
    assert kb["ic"]["HP:1"] == 0 and kb["ic"]["HP:3"] == pytest.approx(math.log(3), abs=1e-6)
    assert stats["genes_with_knowledge"] == 4 and stats["safe_sex_limited"] == 1


def test_new_input_features_are_zero_without_new_inputs(know):
    f = feats(know, {"present": ["HP:3"], "excluded": [], "sex": "unknown"})
    for name in bundle.NEW:
        assert set(f[name].values()) == {0.0}, name
    assert f["present_explained"]["G1"] == 1 and f["present_explained"]["G3"] == 0
    assert f["present_resnik_bma"]["G3"] == pytest.approx(know.ic["HP:2"])
    assert f["present_llr_sum"]["G5"] < 0 < f["present_llr_sum"]["G1"]
    assert f["richness_diseases"]["G4"] == 2 and f["richness_terms"]["G4"] == pytest.approx(math.log1p(3))
    assert feats(know, {"present": ["HP:99"]})["present_explained"]["G1"] == 1  # alternative id resolved


def test_excluded_terms_count_by_the_gene_s_best_frequency_band(know):
    f = feats(know, {"present": ["HP:4"], "excluded": ["HP:2"]})
    assert f["excl_obligate"] == {"G1": 1, "G2": 0, "G3": 0, "G4": 1, "G5": 0}
    assert f["excl_occasional"]["G3"] == 1
    assert f["negation_contradicted"] == {"G1": 1, "G2": 0, "G3": 0, "G4": 0, "G5": 0}
    f = feats(know, {"present": ["HP:4"], "excluded": ["HP:9"]})
    assert f["excl_unknown_frequency"]["G2"] == 1 and f["excl_frequent"]["G1"] == 1
    assert f["excl_frequent"]["G4"] == 1 and f["excl_unknown_frequency"]["G4"] == 0  # a known band wins


def test_sex_and_onset_features(know):
    f = feats(know, {"present": ["HP:4"], "sex": "female", "age_years": 5.0})
    assert f["sex_mismatch"] == {"G1": 0, "G2": 0, "G3": 1, "G4": 0, "G5": 0}
    assert f["xlr_female"]["G1"] == 1 and f["xlr_female"]["G4"] == 0 and f["xld_male"]["G3"] == 0
    assert f["onset_late"]["G1"] == 1 and f["onset_gap_strict"]["G1"] == 11
    assert f["onset_gap_lenient"] == {"G1": 11, "G2": 0, "G3": 0, "G4": 0, "G5": 0}
    f = feats(know, {"present": ["HP:4"], "sex": "male", "age_years": 5.0, "onset_years": 20.0})
    assert f["onset_late"]["G1"] == 0 and f["onset_gap_strict"]["G1"] == 0 and f["xld_male"]["G3"] == 1
    f = feats(know, {"present": ["HP:4"], "onset_years": -0.5})
    assert f["onset_gap_strict"]["G1"] == 16  # prenatal onset counts as 0


def test_every_new_input_feature_may_only_lower_a_score():
    assert all(bundle.MONOTONE[n] == -1 for n in bundle.NEW)
    assert {bundle.GROUP[n] for n in bundle.NEW} == {"new"}
    assert {n[:4] for n in bundle.NEW} == {"sex_", "xlr_", "xld_", "onse", "nega", "excl"}
    for family in bundle.FAMILIES:
        assert not set(bundle.family_features(family, ablation=True)) & set(bundle.NEW)
    assert set(bundle.family_features("residual_new")) == {
        "e0_logp",
        "e0_logrank",
        "e0_gap_top1",
        *bundle.NEW,
    }


# Trees and apply

TEXT = """tree
version=v4
feature_names=a b
Tree=0
num_leaves=3
num_cat=0
split_feature=1 0
split_gain=1 1
threshold=0.5 -1
decision_type=2 0
left_child=1 -1
right_child=-3 -2
leaf_value=0.1 0.2 -0.3
shrinkage=1

Tree=1
num_leaves=1
leaf_value=0.05

end of trees
"""


def test_tree_ensemble_follows_lightgbm_text_semantics():
    trees = bundle.TreeEnsemble(TEXT)
    assert trees.feature_names == ["a", "b"]
    x = np.array([[-2.0, 0.0], [0.0, 0.0], [0.0, 1.0], [0.0, np.nan]])
    # b <= 0.5 goes to node 1 (a <= -1: leaf 0, else leaf 1); NaN without a missing type counts as 0.
    assert np.allclose(trees.predict(x), [0.15, 0.25, -0.25, 0.25])


def test_tree_ensemble_matches_lightgbm_on_a_monotone_ranker():
    lgb = pytest.importorskip("lightgbm")
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2000, 4))
    x[rng.random(x.shape) < 0.1] = 0.0
    y = (x[:, 0] - x[:, 1] + rng.normal(size=2000) > 1).astype(int)
    params = {"objective": "lambdarank", "num_leaves": 7, "min_data_in_leaf": 5, "verbosity": -1}
    params["monotone_constraints"] = [1, -1, 0, 0]
    booster = lgb.train(params, lgb.Dataset(x, y, group=[20] * 100), num_boost_round=30)
    ours = bundle.TreeEnsemble(booster.model_to_string()).predict(x)
    assert np.allclose(ours, booster.predict(x, raw_score=True), atol=1e-12)


def test_reorder_keeps_the_candidates_on_top_in_score_order():
    rng = np.random.default_rng(1)
    probs = rng.dirichlet(np.ones(300))
    top = np.argsort(-probs, kind="stable")[:100]
    scores = rng.normal(size=100)
    out = bundle.reorder(probs, top, scores)
    ranking = np.argsort(-out, kind="stable")
    assert list(ranking[:100]) == list(top[np.argsort(-scores, kind="stable")])
    rest = [g for g in np.argsort(-probs, kind="stable") if g not in set(top)]
    assert list(ranking[100:]) == rest
    assert out.sum() == pytest.approx(1.0) and len(set(out[top])) == 100
    tied = bundle.reorder(probs, top, np.zeros(100))
    assert list(np.argsort(-tied, kind="stable")[:100]) == list(top)  # ties keep E0's order


def residual_new_model(know, text=None):
    cfg = train.Config("toy", "residual_new", 3, 1)
    spec = train.spec(cfg, "toy", "0")
    col = spec["features"].index("sex_mismatch")
    text = text or TEXT.replace("feature_names=a b", "feature_names=" + " ".join(spec["features"])).replace(
        "split_feature=1 0", f"split_feature={col} 0"
    ).replace("leaf_value=0.1 0.2 -0.3", "leaf_value=0.1 0.2 -5")
    return bundle.LtrModel(know, spec, text)


def test_residual_new_is_e0_bit_for_bit_without_new_inputs(know):
    model = residual_new_model(know)
    probs = np.array([0.4, 0.3, 0.2, 0.06, 0.04])
    assert model.apply(probs, VOCAB, {"present": ["HP:3"], "excluded": []}) is probs
    out = model.apply(probs, VOCAB, {"present": ["HP:3"], "sex": "female"})
    assert out is not probs and np.argsort(-out)[-1] == 2  # G3, limited to males, goes last


def test_scores_never_rise_with_a_new_input_feature():
    lgb = pytest.importorskip("lightgbm")
    rng = np.random.default_rng(2)
    rows = []
    for i in range(300):
        x = np.zeros((20, len(bundle.NAMES)))
        x[:, 0] = np.sort(rng.normal(size=20))[::-1]
        x[:, 1] = np.log(np.arange(1, 21))
        x[:, 3:9] = rng.normal(size=(20, 6))
        x[:, 9:] = rng.random((20, len(bundle.NEW))) < 0.2
        pos = int(rng.integers(20))
        x[pos, 9:] = rng.random(len(bundle.NEW)) < 0.6  # the true gene often has a new input set
        rows.append(train.Table(f"c{i}", f"g{i % 50}", float(pos + 1), np.arange(20), x, pos))
    del lgb
    cfg = train.Config("toy", "residual", 7, 5, max_rounds=40, early_stopping=40)
    text, info = train.fit(cfg, rows)
    trees = bundle.TreeEnsemble(text)
    feats_ = info["features"]
    x = np.concatenate([t.x for t in rows])[:, [bundle.NAMES.index(f) for f in feats_]]
    base = trees.predict(x)
    for f in bundle.NEW:
        bumped = x.copy()
        bumped[:, feats_.index(f)] += 1.0
        assert (trees.predict(bumped) <= base + 1e-12).all(), f


def test_grid_and_config_rules():
    configs = train.grid()
    assert len(configs) <= 20 and len({c.name for c in configs}) == len(configs)
    with pytest.raises(ValueError):
        train.Config("x", "free", 3, 1, shrink=0.5)
    with pytest.raises(ValueError):
        train.Config("x", "nope", 3, 1)
    assert train.fit(train.Config("x", "residual_new", 3, 1), [], ablation=True)[0] is None


def test_ranks_follow_scores_inside_the_top_and_e0_outside():
    x = np.zeros((3, len(bundle.NAMES)))
    rows = [
        train.Table("a", "g", 3.0, np.arange(3), x, 2),
        train.Table("b", "g", 250.0, np.arange(3), x, None),
        train.Table("c", "g", math.inf, np.zeros(0, int), np.zeros((0, len(bundle.NAMES))), None),
    ]
    out = train.ranks(rows, [np.array([0.0, 0.0, 1.0]), np.zeros(3), np.zeros(0)])
    assert [r["rank"] for r in out] == [1.0, 250.0, math.inf]
    assert [r["rank"] for r in train.ranks(rows, None)] == [3.0, 250.0, math.inf]


# The System and the sealed read


class FakeBase:
    name = "fake-e0"
    genes = VOCAB

    def lineage_inputs(self):
        return [{"id": "fake", "sha256": "0" * 64}]

    def score(self, case):
        assert case.excluded == ()
        if not case.present:
            return Scored(None, {"n_present": 0})
        rng = np.random.default_rng(sum(map(ord, case.case_id)))
        return Scored(rng.dirichlet(np.ones(len(self.genes))), {"n_present": len(case.present)})


def make_cases():
    cases = []
    for i in range(30):
        kw = {"sex": Sex.FEMALE} if i % 3 == 0 else {}
        if i % 2 == 0:
            kw["excluded"] = ("HP:2",)
        cases.append(Case(case_id=f"c{i}", cohort="t", gene=VOCAB[i % 5], present=("HP:4",), **kw))
    return cases


GROUPS = {f"c{i}": f"g{i // 3}" for i in range(30)}


def test_system_reports_against_e0_with_subsets(know):
    model = residual_new_model(know)
    base = safe_eval.Memo(FakeBase())
    cases = make_cases()
    report, records = ltr_eval.evaluate(
        base, {"ltr": LtrV1(base, model)}, cases, GROUPS, {"few": {"c0", "c1"}}
    )
    assert report["cases"] == 30 and report["publications"] == 10
    ltr = report["systems"]["ltr"]
    assert ltr["subsets"]["few"]["n"] == 2 and ltr["vs_e0"]["n"] == 30
    unchanged = [r for r in records["ltr-v1"] if not r["ltr_changed"]]
    assert unchanged and all(
        not c.excluded and c.sex == Sex.UNKNOWN
        for c in cases
        if c.case_id in {r["case_id"] for r in unchanged}
    )
    assert case_inputs(cases[0])["present"] == ["HP:4"]


ARGS = ["ltr", "confirm", "--exp", "EXP-P-002", "--split", "p2-v1", "--part", "test", "--model", "ltr-x"]
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
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-002")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)


def run(args):
    return CliRunner().invoke(app, args, env={"COLUMNS": "400"})


def refused(result, text):
    return result.exit_code != 0 and not isinstance(result.exception, Touched) and text in result.output


def test_tripwires_are_live_once_every_check_passes(tripwires, good):
    assert isinstance(run(ARGS + REASON).exception, Touched)


def test_refusals_come_in_the_safe_order_and_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.delenv("DXT_SEALED_READ")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: False)
    monkeypatch.setattr(safe_eval, "code_state", lambda: DIRTY)
    assert refused(run(ARGS), "DXT_SEALED_READ=EXP-P-002")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-001")
    assert refused(run(ARGS), "DXT_SEALED_READ=EXP-P-002")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-P-002")
    assert refused(run(ARGS), "committed")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    assert refused(run(ARGS), "uncommitted")
    monkeypatch.setattr(safe_eval, "code_state", lambda: CLEAN)
    assert refused(run(ARGS), "reason is required")


def test_malformed_requests_are_refused_before_any_load(tripwires, good):
    base = ["ltr", "confirm", "--exp", "EXP-P-002", "--model", "m", *REASON]
    for args in (
        [*base, "--split", "p2-v1", "--part", "dev"],
        [*base, "--split", "r1-v1", "--part", "test"],
        [*base, "--split", "p2-v1", "--part", "vault"],
        [
            "ltr",
            "confirm",
            "--exp",
            "EXP-X-001",
            "--model",
            "m",
            "--split",
            "p2-v1",
            "--part",
            "test",
            *REASON,
        ],
    ):
        result = run(args)
        assert result.exit_code != 0 and not isinstance(result.exception, Touched)


def test_vault_opens_once(tripwires, good):
    args = ["ltr", "confirm", "--exp", "EXP-P-002", "--split", "p2-v1", "--split", "p2-fresh-v1"]
    args += ["--part", "vault", "--model", "m", *REASON]
    assert isinstance(run(args).exception, Touched)
    ledger.LEDGER.write_text("| 2026-10-20T00:00:00+00:00 | p2-v1/vault | EXP-P-001 | abc | r |\n")
    assert refused(run(args), "already opened")


def test_final_check_runs_end_to_end_on_mocked_vaults(good, know, monkeypatch, tmp_path):
    from diagnostic_ar_training.systems import genphenia_v3

    cases = make_cases()
    loads = []

    def load_part(split_id, part, purpose, exp_id=None, reason=""):
        loads.append((split_id, part, exp_id, reason))
        return cases[:15] if split_id == "p2-v1" else cases[15:]

    for name in ("p2-v1", "p2-fresh-v1"):
        (tmp_path / f"{name}.json").write_text("{}")
    model = residual_new_model(know)
    monkeypatch.setattr(splits, "load_part", load_part)
    monkeypatch.setattr(splits, "publication_groups", lambda split_id: GROUPS)
    monkeypatch.setattr(
        cli_ltr, "_load_model", lambda model_id: (model, None, [{"id": "m", "sha256": "f" * 64}])
    )
    monkeypatch.setattr(genphenia_v3, "GenPheniaV3", FakeBase)
    monkeypatch.setattr(gitinfo, "code_state", lambda *a, **k: CLEAN)
    monkeypatch.setattr(cli_ltr, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(cli_ltr, "SPLITS_DIR", tmp_path)
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path / "manifests")
    args = ["ltr", "confirm", "--exp", "EXP-P-002", "--split", "p2-v1", "--split", "p2-fresh-v1"]
    result = run([*args, "--part", "vault", "--model", "ltr-x", *REASON])
    assert result.exit_code == 0, result.output
    assert loads == [(s, "vault", "EXP-P-002", REASON[1]) for s in ("p2-v1", "p2-fresh-v1")]
    report = json.loads(
        (tmp_path / "results" / "EXP-P-002" / "p2-v1+p2-fresh-v1-vault-ltr-x__report.json").read_text()
    )
    assert report["cases"] == 30 and set(report["components"]) == {"p2-v1", "p2-fresh-v1"}
    assert (tmp_path / "manifests" / "results-EXP-P-002-p2-v1+p2-fresh-v1-vault-ltr-x.json").exists()


def test_knowledge_and_select_refuse_knowledge_not_masked_on_every_part(monkeypatch):
    m = manifest.Manifest(
        artifact_id="k",
        kind="kb",
        created_at="t",
        code={},
        inputs=[],
        params={"mask_split": "r1-v1", "mask_scope": "heldout"},
        params_hash="h",
        outputs=[],
    )
    monkeypatch.setattr(manifest, "load_manifest", lambda artifact_id: m)
    monkeypatch.setattr(manifest, "ensure_new", lambda artifact_id: None)
    result = run(["ltr", "kb", "--id", "ltr-kb-x", "--rerank-kb", "kb-v5", "--safe-kb", "safe-kb-v1"])
    assert result.exit_code != 0 and "mask scope 'all'" in result.output


def test_safe_build_refuses_an_unknown_mask_scope():
    result = run(["safe", "build", "--id", "safe-kb-x", "--mask-scope", "dev"])
    assert result.exit_code != 0 and "--mask-scope" in result.output


def test_load_model_refuses_other_kinds(monkeypatch):
    m = manifest.Manifest(
        artifact_id="x",
        kind="safe-kb",
        created_at="t",
        code={},
        inputs=[],
        params={},
        params_hash="h",
        outputs=[],
    )
    monkeypatch.setattr(manifest, "load_manifest", lambda artifact_id: m)
    with pytest.raises(typer.BadParameter, match="not an ltr-model"):
        cli_ltr._load_model("x")


def test_select_runs_end_to_end_on_mocked_parts(built, monkeypatch, tmp_path):
    pytest.importorskip("lightgbm")
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.systems import genphenia_v3

    kb_path = tmp_path / "ltr-kb.json.gz"
    kb_io.write(built[0], kb_path)
    cases = make_cases() + [c.model_copy(update={"case_id": f"d{c.case_id}"}) for c in make_cases()]
    groups = {c.case_id: f"g{i // 3}" for i, c in enumerate(cases)}
    loads = []

    def load_part(split_id, part, purpose, exp_id=None, reason=""):
        loads.append((split_id, part, exp_id))
        return cases[:30] if part == "train" else cases[30:]

    (tmp_path / "r1-v1.json").write_text("{}")
    monkeypatch.setattr(splits, "load_part", load_part)
    monkeypatch.setattr(splits, "publication_groups", lambda split_id: groups)
    monkeypatch.setattr(ltr_eval, "post_e0_cases", lambda cs, g: {cs[0].case_id})
    monkeypatch.setattr(cli_ltr, "_output", lambda artifact_id, kind, name: (kb_path, "e" * 64))
    monkeypatch.setattr(train, "grid", lambda: [train.Config("tiny", "residual", 3, 1, max_rounds=5)])
    monkeypatch.setattr(genphenia_v3, "GenPheniaV3", FakeBase)
    monkeypatch.setattr(gitinfo, "code_state", lambda *a, **k: CLEAN)
    monkeypatch.setattr(manifest, "code_state", lambda *a, **k: CLEAN)
    monkeypatch.setattr(cli_ltr, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(cli_ltr, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(cli_ltr, "SPLITS_DIR", tmp_path)
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path / "manifests")
    result = run(["ltr", "select", "--kb", "ltr-kb-x", "--id", "ltr-x", "--exp", "EXP-P-002"])
    assert result.exit_code == 0, result.output
    assert [p for _, p, _ in loads] == ["train", "dev"] and {e for *_, e in loads} == {None}
    report = json.loads((tmp_path / "results" / "EXP-P-002" / "r1-v1-ltr-x__selection.json").read_text())
    assert report["winner"] == "tiny" and len(report["configurations"]) == 1
    for part in ("train", "dev"):
        assert report["reports"][part]["system_vs_selection_rank_mismatches"] == 0
    assert report["reports"]["dev"]["subset_sizes"]["post_e0"] == 1
    assert "ltr_vs_ablation" in report["reports"]["dev"]
    model_dir = tmp_path / "data" / "ltr" / "ltr-x"
    assert bundle.read_spec(model_dir / "spec.json")["family"] == "residual"
    assert (model_dir / "ablation" / "model.txt").is_file()
    for artifact in ("results-EXP-P-002-r1-v1-ltr-x", "ltr-x"):
        assert (tmp_path / "manifests" / f"{artifact}.json").exists()
