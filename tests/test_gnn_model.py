"""GinV3 must be production v3.0; GinV3Extended must be v3.0 until trained; exports must round-trip."""

import json
from pathlib import Path

import numpy as np
import pytest

from diagnostic_ar_training.lineage import registry

torch = pytest.importorskip("torch")
ort = pytest.importorskip("onnxruntime")
pytest.importorskip("onnx")
if not registry.verify(registry.load_sources()["genphenia_v3"]):
    pytest.skip("genphenia_v3 bundle not fetched (dxt sources fetch genphenia_v3)", allow_module_level=True)

from diagnostic_ar_training.cohorts.schema import Case, Sex  # noqa: E402
from diagnostic_ar_training.gnn import export, graphs  # noqa: E402
from diagnostic_ar_training.gnn.model import GinV3, GinV3Extended, load_v3  # noqa: E402
from diagnostic_ar_training.systems.genphenia_v3 import CHECKPOINT, GenPheniaV3  # noqa: E402
from diagnostic_ar_training.systems.ginv3_torch import GinV3Torch  # noqa: E402

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures" / "production_reference_rankings.json").read_text()
)
# A few ancestor-rich extras so batches mix graph sizes.
EXTRA = [["HP:0001250"], ["HP:0000252", "HP:0001249", "HP:0001263", "HP:0000486"], ["HP:0000365"]]
NEGATED = ("HP:0001250", "HP:0000365", "HP:0001263", "HP:0000957")


@pytest.fixture(scope="module")
def e0():
    return GenPheniaV3()


@pytest.fixture(scope="module")
def system():
    return GinV3Torch()


def cases(**kw) -> list[Case]:
    terms = [r["hpo_ids"] for r in REFERENCE.values()] + EXTRA
    return [Case(case_id=str(i), cohort="t", gene="X", present=tuple(t), **kw) for i, t in enumerate(terms)]


def as_torch(graph: graphs.CaseGraph) -> dict:
    return {k: torch.from_numpy(getattr(graph, k)) for k in ("x", "edge_index", "node_type")}


def test_checkpoint_keys_are_pygs_and_load_strictly(system):
    root = system.inputs.root
    raw = torch.load(root / "checkpoints" / "best_model.pt", map_location="cpu", weights_only=True)
    raw = raw["model_state_dict"]
    assert set(GinV3(768, 512, 5229).state_dict()) == set(raw)
    loaded = load_v3(root).state_dict()
    assert all(torch.equal(loaded[k], raw[k]) for k in raw)
    assert not system.model.training
    assert (root / "checkpoints" / CHECKPOINT / "spec.json").exists()


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_matches_production_onnx_and_rankings(e0, system, name):
    expected = REFERENCE[name]
    onnx_logits, _ = e0.logits(expected["hpo_ids"])
    scored = system.score(Case(case_id=name, cohort="t", gene="X", present=tuple(expected["hpo_ids"])))
    graph, _ = graphs.case_graph(
        system.inputs, Case(case_id=name, cohort="t", gene="X", present=tuple(expected["hpo_ids"]))
    )
    np.testing.assert_allclose(system.logits(graph), onnx_logits, rtol=2e-6, atol=1e-5)
    top = np.argsort(scored.probs)[::-1][:10]
    assert [system.genes[i].upper() for i in top] == [g for g, _ in expected["top_genes"]]
    for i, (_, score) in zip(top, expected["top_genes"], strict=True):
        assert scored.probs[i] == pytest.approx(score, abs=1e-4)


def test_score_reports_the_same_coverage_as_e0(e0, system):
    case = Case(case_id="u", cohort="t", gene="NF1", present=("HP:0000957", "HP:9999999", "HP:0000957"))
    assert system.score(case).info == e0.score(case).info
    assert system.score(case.model_copy(update={"present": ("HP:9999999",)})).probs is None


def test_a_batch_equals_one_call_per_case(system):
    built = [graphs.case_graph(system.inputs, c)[0] for c in cases()]
    batched = system.logits_many(built)
    single = np.stack([system.logits(g) for g in built])
    np.testing.assert_allclose(batched, single, rtol=1e-6, atol=1e-4)
    assert np.array_equal(batched.argmax(1), single.argmax(1))


@pytest.fixture(scope="module")
def extended(system):
    return GinV3Extended.from_v3(system.model, covariates=True, neg_readout=True).eval()


def test_warm_start_copies_v3_and_zeroes_every_new_output_path(system, extended):
    base = system.model.state_dict()
    ext = extended.state_dict()
    assert all(torch.equal(ext[k], v) for k, v in base.items())
    for name in ("type_proj.weight", "cov_classifier.weight", "neg_classifier.weight"):
        assert not ext[name].any()
    assert not any(g.any() for g in extended.neg_gates)


@pytest.mark.parametrize("with_negated", [False, True])
def test_extended_equals_v3_at_step_zero(system, extended, with_negated):
    for c in cases(excluded=NEGATED, sex=Sex.FEMALE, age_years=7.0, onset_years=1.5):
        graph, _ = graphs.case_graph(system.inputs, c, negated=with_negated)
        base = system.logits(graphs.case_graph(system.inputs, c)[0])
        with torch.inference_mode():
            out = extended(**as_torch(graph), covariates=torch.from_numpy(graph.covariates)[None])
        assert np.abs(out.numpy().reshape(-1) - base).max() <= 1e-6


def test_extended_batch_equals_v3_batch_at_step_zero(system, extended):
    built = [graphs.case_graph(system.inputs, c, negated=True)[0] for c in cases(excluded=NEGATED)]
    base = system.logits_many([graphs.case_graph(system.inputs, c)[0] for c in cases()])
    t = graphs.collate(built).to_torch()
    with torch.inference_mode():
        out = extended(t["x"], t["edge_index"], t["node_type"], t["covariates"], t["batch"], t["num_graphs"])
    assert np.abs(out.numpy() - base).max() <= 1e-6


def test_new_parameters_get_gradients_at_step_zero(system, extended):
    model = GinV3Extended.from_v3(system.model, covariates=True, neg_readout=True).eval()
    graph, _ = graphs.case_graph(system.inputs, cases(excluded=NEGATED, age_years=3.0)[1], negated=True)
    logits = model(**as_torch(graph), covariates=torch.from_numpy(graph.covariates)[None])
    torch.nn.functional.cross_entropy(logits, torch.tensor([0])).backward()
    for name in ("type_proj.weight", "cov_classifier.weight", "neg_classifier.weight", "neg_gates.0"):
        assert model.get_parameter(name).grad.abs().sum() > 0, name


def test_negated_nodes_only_matter_once_their_gates_open(system):
    model = GinV3Extended.from_v3(system.model, covariates=False).eval()
    with torch.no_grad():
        for gate in model.neg_gates:
            gate.fill_(0.5)
    c = cases(excluded=NEGATED)[0]
    plain = system.logits(graphs.case_graph(system.inputs, c)[0])
    with torch.inference_mode():
        without = model(**as_torch(graphs.case_graph(system.inputs, c)[0])).numpy().reshape(-1)
        with_neg = model(**as_torch(graphs.case_graph(system.inputs, c, negated=True)[0])).numpy().reshape(-1)
    assert np.abs(without - plain).max() <= 1e-6
    assert np.abs(with_neg - plain).max() > 1e-3


def test_frozen_base_present_only_is_v3_bit_for_bit_whatever_the_new_weights(system):
    from diagnostic_ar_training.gnn import train as training

    cfg = training.TrainConfig(
        lr_base=0.0, lr_new=1e-3, frozen_base=True, negated=True, neg_readout=True, covariates=True
    )
    model = training.build_model(system.model, cfg).eval()
    generator = torch.Generator().manual_seed(0)
    with torch.no_grad():
        for p in (p for p in model.parameters() if p.requires_grad):
            p.copy_(torch.randn(p.shape, generator=generator) * 0.1)
        model.type_proj.weight[:, : graphs.NODE_NEGATED] = 0
    for c in cases(excluded=NEGATED, sex=Sex.FEMALE, age_years=7.0):
        plain, _ = graphs.case_graph(system.inputs, c.model_copy(update={"excluded": (), "sex": Sex.UNKNOWN,
                                                                         "age_years": None}))  # fmt: skip
        full, _ = graphs.case_graph(system.inputs, c, negated=True)
        with torch.inference_mode():
            reference = system.model(torch.from_numpy(plain.x), torch.from_numpy(plain.edge_index))
            out = model(**as_torch(plain), covariates=torch.from_numpy(plain.covariates)[None])
            moved = model(**as_torch(full), covariates=torch.from_numpy(full.covariates)[None])
        assert torch.equal(out, reference)
        assert not torch.equal(moved, reference)


def test_exported_v3_is_the_production_onnx(e0, system, tmp_path):
    session = ort.InferenceSession(str(export.export_v3(system.model, tmp_path / "v3.onnx")))
    assert [i.name for i in session.get_inputs()] == ["x", "edge_index"]
    for c in cases():
        node_ids, x, edge_index = e0.graph(list(c.present))
        ours = session.run(None, {"x": x, "edge_index": edge_index})[0]
        production, _ = e0.logits(list(c.present))
        assert np.abs(ours.reshape(-1) - production).max() <= 1e-6


def test_exported_extended_round_trips(system, tmp_path):
    model = GinV3Extended.from_v3(system.model, covariates=True, neg_readout=True).eval()
    with torch.no_grad():
        for p in (
            *model.neg_gates,
            model.type_proj.weight,
            model.cov_classifier.weight,
            model.neg_classifier.weight,
        ):
            p.normal_(std=0.1)
    session = ort.InferenceSession(str(export.export_extended(model, tmp_path / "ext.onnx")))
    assert [i.name for i in session.get_inputs()] == ["x", "edge_index", "node_type", "covariates"]
    for negated in (False, True):
        c = cases(excluded=NEGATED, sex=Sex.MALE, age_years=30.0)[1]
        graph, _ = graphs.case_graph(system.inputs, c, negated=negated)
        feeds = {k: v.numpy() for k, v in as_torch(graph).items()} | {"covariates": graph.covariates[None]}
        with torch.inference_mode():
            expected = model(**as_torch(graph), covariates=torch.from_numpy(graph.covariates)[None]).numpy()
        np.testing.assert_allclose(session.run(None, feeds)[0], expected, rtol=2e-6, atol=1e-5)


def test_untrained_extended_export_fed_neutral_inputs_is_production(e0, extended, tmp_path):
    session = ort.InferenceSession(str(export.export_extended(extended, tmp_path / "ext0.onnx")))
    for c in cases():
        graph, _ = graphs.case_graph(e0.inputs, c)
        feeds = {k: v.numpy() for k, v in as_torch(graph).items()}
        ours = session.run(None, feeds | {"covariates": graphs.NEUTRAL_COVARIATES[None]})[0]
        production, _ = e0.logits(list(c.present))
        assert np.abs(ours.reshape(-1) - production).max() <= 1e-6


def test_parity_report_on_the_reference_cases(e0, system):
    from diagnostic_ar_training.gnn import parity

    report, rows = parity.run(e0, system, cases(), batch_size=4)
    assert report["n"] == len(rows) == len(cases())
    assert report["top10_same_order"] == report["rank_identical"] == report["n"]
    assert report["max_abs_dlogit"] < 1e-3 and report["batched_vs_single_max_abs_dlogit"] < 1e-3
