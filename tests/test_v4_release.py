"""F3's release: the standalone layer (dist/v4-layer/v4_layer.py), its export, the committed package, and the
GinV4 -> GinV3 weight mapping behind genphenia-v4.0's model.onnx.

The toy tests need no data; the torch and ONNX tests skip without torch, onnx or onnxruntime.
"""

import ast
import gzip
import hashlib
import json

import numpy as np
import pytest
from test_ft import EMB_INDEX, G2D, GENES, VECTORS, ancestors, annotations

from diagnostic_ar_training.ft import knowledge as ft_knowledge
from diagnostic_ar_training.ft.bundle import COVARIATES, FEATURES, Knowledge, softmax64
from diagnostic_ar_training.v4 import addon, release, sexrule

v4_layer = release.load_standalone()
STDLIB = {"gzip", "hashlib", "json", "math", "collections.abc", "pathlib"}
THETA = (
    [1.8, 2.2, 2.0, 0.4, 2.8, 0.0, 0.0],
    [2.3, 0.0, 0.0, 0.0, 2.6, 0.0, 0.0],
    [0.5, 0.1, 0.2, 0.0, 1.0, 0, 0],
)
SEX_KB = {
    "schema": sexrule.SCHEMA,
    "genes": {"MALE1": {"limit": "male"}, "FEMALE1": {"limit": "female"}, "ABSENT": {"limit": "male"}},
}
CASES = (
    {},
    {"sex": "unknown"},
    {"sex": "male"},
    {"sex": "FEMALE", "age_years": 3.0},
    {"sex": "female", "age_years": -2.0},
    {"age_years": 30.0, "onset_years": 0.5},
    {"age_years": 30.0, "onset_years": -1.0},
    {"excluded": ["HP:1"]},
    {"sex": "male", "excluded": ["HP:3", "HP:404"], "present": ["HP:9"]},
    {"sex": "female", "age_years": 0.2, "onset_years": 0.1, "excluded": ["HP:2", "HP:9"]},
)


def member(theta):
    return {"active_features": list(FEATURES), "active_covariates": [], "theta": list(theta), "mlp": None}


def bundle_of(members):
    return {
        "format": "ft-v1-bundle/2",
        "kb_id": "ft-kb-toy",
        "features": list(FEATURES),
        "covariates": list(COVARIATES),
        "members": members,
    }


@pytest.fixture(scope="module")
def toy():
    kb = ft_knowledge.build(GENES, G2D, annotations(), {}, {}, ancestors, ())[0]
    bundle = bundle_of([member(t) for t in THETA])
    exported = release.export_layer(bundle, kb, SEX_KB, GENES, {"model": "toy"}, v4_layer.FEATURES)
    full = addon.Addon(bundle, Knowledge(kb, GENES, (EMB_INDEX, VECTORS), "ft-kb-toy"))
    rule = sexrule.SexRule(sexrule.limits(SEX_KB), GENES)
    return v4_layer.V4Layer(exported), full, rule, exported, kb, bundle


def logits(seed=0, n=len(GENES)):
    return np.random.default_rng(seed).normal(size=n).astype(np.float32)


def test_standalone_imports_only_numpy_and_the_standard_library():
    tree = ast.parse(release.STANDALONE.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module)
    assert names <= STDLIB | {"numpy"}


def test_zero_theta_features_are_dropped_and_change_nothing(toy):
    layer, full, rule, exported, kb, bundle = toy
    assert release.zero_features(bundle) == ["neg_obligate", "neg_embed"]
    assert exported["addon"]["features"] == list(v4_layer.FEATURES)
    assert np.array(exported["addon"]["theta"]).shape == (len(THETA), len(v4_layer.FEATURES))
    no_zero = addon.Addon(
        {**bundle, "members": [{**m, "active_features": list(v4_layer.FEATURES)} for m in bundle["members"]]},
        Knowledge(kb, GENES, None, "ft-kb-toy"),
    )
    for i, inputs in enumerate(CASES):
        z = logits(i)
        expected = release.research_f3(full, rule, z, inputs)
        assert np.array_equal(release.research_f3(no_zero, rule, z, inputs), expected)
        assert np.array_equal(layer.scores(z, inputs), expected)
        assert np.array_equal(layer.apply(z, inputs), softmax64(expected))


def test_no_new_input_is_the_network_exactly(toy):
    layer = toy[0]
    z = logits()
    for inputs in (
        {},
        {"sex": "unknown", "excluded": []},
        {"sex": None, "age_years": None, "onset_years": None},
        {"excluded": ["HP:1", "HP:404"], "present": ["HP:3"]},
        {"age_years": float("nan")},
    ):
        assert not layer.residual(inputs).any()
        assert not layer.blocked(inputs.get("sex")).any()
        assert layer.scores(z, inputs).tobytes() == z.astype(np.float64).tobytes()
        assert layer.apply(z, inputs).tobytes() == softmax64(z).tobytes()


def test_the_addon_only_lowers(toy):
    layer = toy[0]
    for i, inputs in enumerate(CASES):
        z = logits(i)
        r = layer.residual(inputs)
        assert (r <= 0).all()
        unknown_sex = {**inputs, "sex": None}
        assert (layer.scores(z, unknown_sex) <= z.astype(np.float64)).all()
    i = GENES.index
    r = layer.residual({"sex": "female", "age_years": 0.0})
    assert r[i("MALE1")] < 0 and r[i("XLR")] < 0 and r[i("NOTHING")] == 0


def test_sex_block_moves_impossible_genes_below_all_others(toy):
    layer = toy[0]
    i = GENES.index
    z = np.arange(len(GENES), dtype=np.float32)[::-1].copy()
    z[i("MALE1")], z[i("FEMALE1")] = 100.0, 99.0
    for sex, gone in (("male", "FEMALE1"), ("female", "MALE1")):
        s = layer.scores(z, {"sex": sex})
        others = np.delete(s, i(gone))
        assert s[i(gone)] < others.min()
        assert np.argsort(-s, kind="stable")[-1] == i(gone)
        assert layer.blocked(sex).sum() == 1
    s = layer.scores(z, {"sex": "unknown"})
    assert np.argmax(s) == i("MALE1")
    assert "ABSENT" not in v4_layer.V4Layer(toy[3]).genes


def test_block_keeps_order_among_blocked_genes():
    s = v4_layer.block(np.array([5.0, 4.0, 3.0, 2.0]), np.array([True, True, False, False]))
    assert list(np.argsort(-s, kind="stable")) == [2, 3, 0, 1]
    assert np.array_equal(v4_layer.block(np.array([1.0, 2.0]), np.array([True, True])), [1.0, 2.0])


def test_only_linear_members_with_the_standalone_features_export(toy):
    _, _, _, _, kb, bundle = toy
    with pytest.raises(ValueError, match="linear"):
        release.export_layer(
            bundle_of([{**member([1] * 7), "mlp": {"w1": []}}]), kb, SEX_KB, GENES, {}, v4_layer.FEATURES
        )
    with pytest.raises(ValueError, match="standalone"):
        release.export_layer(bundle_of([member([1] * 7)]), kb, SEX_KB, GENES, {}, v4_layer.FEATURES)


def test_load_refuses_a_wrong_hash_or_format(toy, tmp_path):
    path = tmp_path / "b.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(toy[3], handle)
    assert v4_layer.load(path, sha256=v4_layer.sha256_file(path)) == toy[3]
    with pytest.raises(ValueError, match="sha256"):
        v4_layer.load(path, sha256="0" * 64)
    with pytest.raises(ValueError, match="bundle"):
        v4_layer.V4Layer({**toy[3], "format": "other"})


COMMITTED = release.LAYER_DIST / release.LAYER_FILE


@pytest.mark.skipif(not COMMITTED.exists(), reason="dist/v4-layer has no exported bundle yet")
def test_committed_package_matches_its_sums_and_fixture():
    sums = dict(
        reversed(line.split("  ")) for line in (release.LAYER_DIST / "SHA256SUMS").read_text().splitlines()
    )
    for name, sha in sums.items():
        assert hashlib.sha256((release.LAYER_DIST / name).read_bytes()).hexdigest() == sha
    layer = v4_layer.V4Layer(v4_layer.load(COMMITTED, sha256=sums[release.LAYER_FILE]))
    assert layer.theta.shape == (3, len(v4_layer.FEATURES)) and len(layer.genes) == 5229
    assert (layer.only["male"].sum(), layer.only["female"].sum()) == (101, 36)
    assert layer.bundle["provenance"]["addon"]["sha256"] == release.FROZEN_SHA256[release.ADDON]
    fixture = json.loads((release.LAYER_DIST / release.FIXTURE_FILE).read_text())
    assert fixture["layer"]["sha256"] == sums[release.LAYER_FILE]
    index = {g: i for i, g in enumerate(layer.genes)}
    for case in fixture["cases"]:
        f3 = [g for g, _ in case["f3_top"]]
        if case["kind"] == "no-inputs":
            assert case["f3_top"] == case["network_top"]
        assert not layer.blocked(case["inputs"]["sex"])[[index[g] for g in f3]].any()
        if case["kind"] == "sex-rule":
            net = [index[g] for g, _ in case["network_top"]]
            assert layer.blocked(case["inputs"]["sex"])[net].any()


def _toy_net(**options):
    from diagnostic_ar_training.v4.config import ArchConfig, EncodingConfig
    from diagnostic_ar_training.v4.model import GinV4

    torch = pytest.importorskip("torch")
    torch.manual_seed(0)
    arch = ArchConfig(hidden=8, **options.pop("arch", {}))
    net = GinV4(6, 5, arch, EncodingConfig(**options))
    for module in net.modules():
        if isinstance(module, torch.nn.BatchNorm1d):
            module.running_mean.uniform_(-1, 1)
            module.running_var.uniform_(0.5, 2)
    return net.eval()


def _graph(torch, n=5):
    edges = torch.tensor([[0, 1, 2, 3], [4, 4, 3, 4]], dtype=torch.int64)
    return torch.randn(n, 6), edges


def test_ginv4_maps_onto_ginv3_bit_for_bit():
    torch = pytest.importorskip("torch")
    net = _toy_net()
    v3 = release.to_ginv3(net)
    assert set(v3.state_dict()) == set(net.state_dict())
    x, edges = _graph(torch)
    with torch.inference_mode():
        assert torch.equal(net(x, edges), v3(x, edges))
        xb = torch.cat([x, x[:3]])
        eb = torch.cat([edges, torch.tensor([[5, 6], [7, 7]])], dim=1)
        batch = torch.tensor([0] * 5 + [1] * 3)
        assert torch.equal(net(xb, eb, batch, 2), v3(xb, eb, batch, 2))


@pytest.mark.parametrize(
    "options",
    [
        {"edges": "both"},
        {"covariates": True},
        {"observed_flag": True},
        {"arch": {"pooling": "attention_mean"}},
    ],
)
def test_only_e0_layout_maps(options):
    pytest.importorskip("torch")
    from diagnostic_ar_training.lineage.registry import LineageError

    with pytest.raises(LineageError, match="E0"):
        release.to_ginv3(_toy_net(**options))


def test_mapped_export_round_trips(tmp_path):
    torch = pytest.importorskip("torch")
    ort = pytest.importorskip("onnxruntime")
    pytest.importorskip("onnx")
    from diagnostic_ar_training.gnn import export

    net = _toy_net()
    session = ort.InferenceSession(str(export.export_v3(release.to_ginv3(net), tmp_path / "v4.onnx")))
    assert [i.name for i in session.get_inputs()] == ["x", "edge_index"]
    x, edges = _graph(torch, 5)
    got = session.run(None, {"x": x.numpy(), "edge_index": edges.numpy()})[0]
    with torch.inference_mode():
        assert np.abs(got - net(x, edges).numpy()).max() < 1e-5
