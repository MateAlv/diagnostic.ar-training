"""ft-v1.1's production package: the standalone module (dist/ft-v1.1-prod/ft_prod.py), its export and fixture.

The toy tests need no data. The fixture tests read the committed export and parity fixture in dist/.
"""

import ast
import gzip
import hashlib
import json

import numpy as np
import pytest
from test_ft import EMB_INDEX, G2D, GENES, VECTORS, ancestors, annotations, override

from diagnostic_ar_training.ft import knowledge as ft_knowledge
from diagnostic_ar_training.ft import prod
from diagnostic_ar_training.ft.bundle import COVARIATES, FEATURES, FtResidual, Knowledge, softmax64

ft_prod = prod.load_standalone()
STDLIB = {"gzip", "hashlib", "json", "math", "collections.abc", "pathlib"}
LINEAR_THETA = (
    [1.8, 2.2, 2.0, 0.0, 2.8, 2.9, 0.0],
    [2.3, 2.4, 2.2, 0.0, 2.8, 3.0, 0.0],
    [2.2, 2.7, 2.4, 0, 2.7, 3, 0],
)
CASES = (
    {},
    {"sex": "unknown"},
    {"sex": None, "excluded": []},
    {"sex": "male"},
    {"sex": "FEMALE", "age_years": 3.0},
    {"sex": "female", "age_years": -2.0},
    {"age_years": 30.0, "onset_years": 0.5},
    {"age_years": 30.0, "onset_years": -1.0},
    {"excluded": ["HP:1"]},
    {"excluded": ["HP:3", "HP:404"]},
    {"sex": "female", "age_years": 0.2, "onset_years": 0.1, "excluded": ["HP:2", "HP:9"]},
)


def member(theta):
    return {"active_features": list(FEATURES), "active_covariates": [], "theta": list(theta), "mlp": None}


def bundle_of(members, kb_id="ft-kb-toy"):
    return {
        "format": "ft-v1-bundle/2",
        "kb_id": kb_id,
        "features": list(FEATURES),
        "covariates": list(COVARIATES),
        "members": members,
    }


@pytest.fixture(scope="module")
def kb():
    return ft_knowledge.build(GENES, G2D, annotations(), {}, {}, ancestors, [override("FEMALE1")])[0]


@pytest.fixture(scope="module")
def toy(kb):
    bundle = bundle_of([member(t) for t in LINEAR_THETA])
    exported = prod.export(bundle, kb, GENES, {"model": "toy"}, ft_prod.FEATURES)
    reference = FtResidual(bundle, Knowledge(kb, GENES, (EMB_INDEX, VECTORS), "ft-kb-toy"))
    return ft_prod.FtProd(exported), reference, exported


def logits(seed=0, n=len(GENES)):
    return np.random.default_rng(seed).normal(size=n).astype(np.float32)


def test_standalone_imports_only_numpy_and_the_standard_library():
    tree = ast.parse(prod.STANDALONE.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names <= STDLIB | {"numpy"}


def test_toy_export_matches_the_training_residual(toy):
    model, reference, exported = toy
    assert exported["features"] == list(ft_prod.FEATURES)
    assert set(exported["members"]["dropped_features"]) == {"onset_lenient_gap", "neg_embed"}
    for i, inputs in enumerate(CASES):
        z = logits(i)
        expected = reference.apply(z, inputs)
        assert np.abs(model.apply(z, inputs) - expected).max() <= 1e-12
        assert np.abs(model.apply(np.log(softmax64(z)), inputs) - expected).max() <= 1e-12
        assert np.abs(model.apply_probs(softmax64(z), inputs) - expected).max() <= 1e-12


def test_mean_theta_is_the_ensemble(toy):
    model, reference, _ = toy
    for inputs in CASES:
        assert np.abs(model.residual(inputs) - reference.residual(inputs)).max() <= 1e-12
    _, dropped, theta = prod.split_features(bundle_of([member(t) for t in LINEAR_THETA]))
    assert dropped == ["onset_lenient_gap", "neg_embed"]
    assert theta.tolist() == pytest.approx(np.mean(LINEAR_THETA, axis=0)[[0, 1, 2, 4, 5]].tolist())


def test_only_linear_members_export():
    with pytest.raises(ValueError, match="linear"):
        prod.split_features(bundle_of([{**member([1] * 7), "mlp": {"w1": []}}]))
    with pytest.raises(ValueError, match="linear"):
        prod.split_features(bundle_of([{**member([1] * 7), "classifier_delta": "x.npz"}]))


def test_no_new_input_is_e0_exactly(toy):
    model, _, _ = toy
    z = logits()
    p = softmax64(z)
    for inputs in (
        {},
        {"sex": "unknown", "excluded": []},
        {"sex": None, "age_years": None},
        {"excluded": ["HP:404"]},
    ):
        assert not model.residual(inputs).any()
        assert model.apply(z, inputs).tobytes() == p.tobytes()
        assert model.apply_probs(p, inputs) is p


def test_inputs_edge_cases(toy):
    model, _, _ = toy
    i = GENES.index
    f = model.features({"sex": "female", "age_years": -2.0})
    assert f[0, i("MALE1")] == 1 and f[3, i("XLR")] == 1
    assert f[1, i("CHILD")] == 1 and f[2, i("CHILD")] == np.float32(np.log1p(1.0))
    assert f[1, i("ADULT")] == 1 and f[2, i("ADULT")] == np.float32(np.log1p(16.0))
    assert (
        model.features({"onset_years": -0.5, "age_years": 40.0}) == model.features({"age_years": 0})
    ).all()
    assert not model.features({"sex": "unknown", "age_years": float("nan")}).any()
    assert not model.features({"age_years": float("inf")}).any()
    contradicted = model.features({"excluded": ["HP:1"]})[4]
    assert contradicted[i("ADULT")] == 1 and contradicted[i("CHILD")] == 1
    assert not model.features({"excluded": ["HP:9"]})[4].any()


def test_bundle_guards(tmp_path, toy):
    _, _, exported = toy
    path = tmp_path / "b.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(exported, handle)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert ft_prod.load(path, sha)["genes"] == list(GENES)
    with pytest.raises(ValueError, match="sha256"):
        ft_prod.load(path, "0" * 64)
    with pytest.raises(ValueError):
        ft_prod.FtProd({**exported, "format": "other"})
    with pytest.raises(ValueError):
        ft_prod.FtProd({**exported, "theta": [-1.0] * len(ft_prod.FEATURES)})
    with pytest.raises(ValueError):
        ft_prod.FtProd(exported).apply(np.zeros(3), {})


def test_theta_source_is_recorded_or_the_bundle_itself():
    own = bundle_of([member(t) for t in LINEAR_THETA], kb_id="ft-kb-all-v2")
    assert prod.theta_source(own, "ens", "abc", "EXP-P-003") == {
        "bundle": "ens",
        "sha256": "abc",
        "fitted_on_kb": "ft-kb-all-v2",
        "exp": "EXP-P-003",
        "refit": False,
    }
    rebased = {
        **own,
        "kb_id": "ft-kb-prod-v1",
        "theta_source": {"bundle": "ens", "fitted_on_kb": "ft-kb-all-v2"},
    }
    assert prod.theta_source(rebased, "prod", "def", None) == {
        "bundle": "ens",
        "fitted_on_kb": "ft-kb-all-v2",
    }


def test_package_paths_follow_the_directory_name():
    paths = prod.package_paths(prod.REPO_ROOT / "dist" / "ft-v1.1-confirmed")
    assert paths["bundle"].name == "ft-v1.1-confirmed-bundle.json.gz"
    assert paths["report"] == prod.DATA_DIR / "ft" / "ft-v1.1-confirmed" / "package-report.json"
    assert prod.package_paths(prod.DIST_DIR)["bundle"].name == prod.BUNDLE_FILE


def test_kb_diff_counts_each_field(kb):
    ann = annotations()
    ann.inheritance["OMIM:6"] = {"HP:0001419", "HP:0001423"}
    newer = ft_knowledge.build(GENES, G2D, ann, {}, {}, ancestors, [override("FEMALE1")])[0]
    diff = prod.kb_diff(kb, newer, GENES, named=("XLR", "ADULT"))
    assert diff["xlr_only"] == {"changed": 1, "gained": 0, "lost": 1, "genes": {"XLR": [True, False]}}
    assert diff["sex_limit"]["changed"] == 0 and diff["strict_onset_years"]["changed"] == 0
    assert diff["named"]["XLR"]["xlr_only"] == [True, False]


# The committed export and parity fixture


@pytest.fixture(scope="module", params=prod.PACKAGES)
def shipped(request):
    out_dir = prod.REPO_ROOT / "dist" / request.param
    fixture = json.loads(gzip.decompress((out_dir / prod.FIXTURE_FILE).read_bytes()))
    bundle_path = out_dir / fixture["bundle"]["file"]
    bundle = ft_prod.load(bundle_path, fixture["bundle"]["sha256"])
    return ft_prod.FtProd(bundle), fixture, out_dir


def case_logits(case):
    return prod.decode_f32(case["e0_logits_f32_b64"])


def test_shipped_files_match_their_hashes(shipped):
    _, fixture, out_dir = shipped
    module = out_dir / fixture["module"]["file"]
    assert module.read_bytes() == prod.STANDALONE.read_bytes()
    assert fixture["module"]["sha256"] == hashlib.sha256(module.read_bytes()).hexdigest()
    for line in (out_dir / "SHA256SUMS").read_text().splitlines():
        sha, name = line.split()
        assert hashlib.sha256((out_dir / name).read_bytes()).hexdigest() == sha


def test_the_confirmed_package_is_the_confirmed_artifact():
    out_dir = prod.REPO_ROOT / "dist" / "ft-v1.1-confirmed"
    bundle = ft_prod.load(prod.package_paths(out_dir)["bundle"])
    source = bundle["provenance"]["theta"]
    assert bundle["provenance"]["knowledge"]["id"] == "ft-kb-all-v2"
    assert bundle["provenance"]["knowledge"]["mask_scope"] == "all"
    assert source["bundle"] == "ft-v1.1-c1-lin-all-ens" and source["fitted_on_kb"] == "ft-kb-all-v2"
    assert source["sha256"] == "89e3ea09c1e491de29b2d7c6f7955bba7ab6bbb575c47fc17756336c601db340"


def test_parity_with_the_training_code(shipped):
    model, fixture, _ = shipped
    assert len(model.genes) == 5229 and len(fixture["cases"]) >= 200
    worst = 0.0
    for case in fixture["cases"]:
        z = case_logits(case)
        idx = case["indices"]
        p = model.apply(z, case["inputs"])
        assert np.abs(softmax64(z)[idx] - case["e0_probs"]).max() <= 1e-15
        worst = max(worst, float(np.abs(p[idx] - case["expected_probs"]).max()))
        assert prod.rank(p, case["gene_index"]) == case["rank_expected"]
        assert int((model.residual(case["inputs"]) < 0).sum()) == case["genes_lowered"]
    assert worst <= fixture["tolerance"]


def test_identity_without_new_inputs(shipped):
    model, fixture, _ = shipped
    for case in fixture["cases"]:
        z = case_logits(case)
        p = softmax64(z)
        assert model.apply(z, {}).tobytes() == p.tobytes()
        assert model.apply_probs(p, {"sex": "unknown", "excluded": []}) is p
    (empty,) = [c for c in fixture["cases"] if c["case_id"] == "synthetic:no-inputs"]
    assert empty["expected_probs"] == empty["e0_probs"] and empty["genes_lowered"] == 0


def test_no_gene_rises_above_renormalisation(shipped):
    model, fixture, _ = shipped
    for case in fixture["cases"]:
        z = case_logits(case)
        p, r = softmax64(z), model.residual(case["inputs"])
        out = model.apply(z, case["inputs"])
        ceiling = p / np.sum(p * np.exp(r))
        assert np.all(out <= ceiling * (1 + 1e-12))
        assert np.all(out[r < 0] < ceiling[r < 0])
        assert np.all(r <= 0)


def test_determinism(shipped):
    model, fixture, out_dir = shipped
    again = ft_prod.FtProd(ft_prod.load(out_dir / fixture["bundle"]["file"]))
    for case in fixture["cases"][:25] + fixture["cases"][-7:]:
        z = case_logits(case)
        first = model.apply(z, case["inputs"]).tobytes()
        assert model.apply(z, case["inputs"]).tobytes() == first
        assert again.apply(z, case["inputs"]).tobytes() == first
