"""Front A training data and loop on a toy DAG and a tiny random GinV3 (CPU; no bundle, no real data)."""

import gzip
import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from diagnostic_ar_training.cohorts.schema import Case  # noqa: E402
from diagnostic_ar_training.gnn import data, experiment, graphs  # noqa: E402
from diagnostic_ar_training.gnn import train as training  # noqa: E402
from diagnostic_ar_training.gnn.model import GinV3, GinV3Extended, is_new_parameter  # noqa: E402
from diagnostic_ar_training.systems.genphenia_v3 import HpoDag, V3Inputs  # noqa: E402

PARENTS = {"A": [], "B": ["A"], "C": ["B"], "D": ["B"], "E": ["A"], "F": ["E"], "G": ["C", "E"]}
GENES = ("G0", "G1", "G2")
# Each gene has its own signature terms, so a few epochs can learn them.
PROFILES = {0: ["C", "D"], 1: ["F"], 2: ["G", "D"]}


@pytest.fixture
def inputs(tmp_path):
    ids = sorted(PARENTS)
    index = {n: i for i, n in enumerate(ids)}
    offsets, parents = [0], []
    for n in ids:
        parents += [index[p] for p in PARENTS[n]]
        offsets.append(len(parents))
    np.savez(tmp_path / "dag.npz", node_ids=np.array(ids), parent_offsets=offsets, parent_indices=parents)
    (tmp_path / "index.json").write_text(json.dumps(index))
    built = object.__new__(V3Inputs)
    built.dag = HpoDag(tmp_path / "dag.npz", tmp_path / "index.json")
    built.dim = 4
    built.genes = GENES
    built.emb_index = {n: i for i, n in enumerate(ids) if n != "F"}
    built.vectors = np.random.default_rng(0).normal(size=(len(ids), 4)).astype(np.float32)
    return built


def export_rows(n_per_gene=24):
    rows = []
    for g, terms in PROFILES.items():
        for k in range(n_per_gene):
            split = "val" if k % 4 == 0 else ("test" if k % 4 == 1 else "train")
            rows.append(
                {
                    "case_id": f"c-{g}-{k}",
                    "gene": GENES[g],
                    "gene_index": g,
                    "present": terms if k % 3 else terms[:1],
                    "excluded": ["E"],
                    "true_present": terms,
                    "sex": "female",
                    "age_years": 1.0,
                    "onset_years": None,
                    "split": split,
                }
            )
    return rows


@pytest.fixture
def export(tmp_path):
    path = tmp_path / "ds.jsonl.gz"
    with gzip.open(path, "wt") as handle:
        for r in export_rows():
            handle.write(json.dumps(r) + "\n")
    return path


def tiny_model(seed=0) -> GinV3:
    torch.manual_seed(seed)
    return GinV3(in_channels=4, hidden_channels=8, out_channels=len(GENES), dropout=0.0).eval()


def test_read_export_applies_the_exclusion_and_keeps_splits(export):
    splits, counts = data.read_export(export, exclude=frozenset({"c-0-2", "c-1-0", "nope"}))
    assert counts["excluded"] == {"train": 1, "val": 1}
    assert sum(counts["read"].values()) == 72
    assert {c.case_id for c in splits["train"]}.isdisjoint({"c-0-2", "c-1-0"})
    assert all(len(v) == counts["kept"][k] for k, v in splits.items())
    assert splits["train"][0].to_case().excluded == ("E",)


def test_residual_overlap_uses_gene_case_insensitively_and_the_present_set(export):
    splits, _ = data.read_export(export, splits=["train"])
    evaluation = [
        Case(case_id="hit", cohort="t", gene="g0", present=("D", "C")),
        Case(case_id="other-gene", cohort="t", gene="G1", present=("C", "D")),
        Case(case_id="subset", cohort="t", gene="G0", present=("D",)),
    ]
    assert data.residual_overlap(splits["train"], evaluation) == ["hit"]


def test_compact_batches_gather_exactly_the_collated_features(inputs, export):
    splits, _ = data.read_export(export, splits=["train"])
    dataset = data.SimGraphs(inputs, splits["train"])
    items = [dataset[i] for i in range(5)]
    batch = data.to_device(data.collate(items), torch.from_numpy(data.embedding_table(inputs)), "cpu")
    reference = graphs.collate([graphs.case_graph(inputs, splits["train"][i].to_case())[0] for i in range(5)])
    assert torch.equal(batch["x"], torch.from_numpy(reference.x))
    assert torch.equal(batch["edge_index"], torch.from_numpy(reference.edge_index))
    assert torch.equal(batch["batch"], torch.from_numpy(reference.batch))
    assert batch["target"].tolist() == [c.gene_index for c in splits["train"][:5]]
    # Positives only: the negated term E never becomes a node.
    assert (batch["node_type"] != graphs.NODE_NEGATED).all()


def test_loader_order_is_seeded(inputs, export):
    splits, _ = data.read_export(export, splits=["train"])
    dataset = data.SimGraphs(inputs, splits["train"])

    def order(seed):
        return [b["index"].tolist() for b in data.loader(dataset, 4, seed, 0)]

    assert order(1) == order(1) and order(1) != order(2)
    assert sum(order(None), []) == list(range(len(dataset)))


def test_config_refuses_learning_rates_above_the_original():
    with pytest.raises(ValueError):
        training.TrainConfig(lr_base=1e-3)


def test_new_parameters_are_frozen_without_their_own_learning_rate():
    model = training.build_model(tiny_model(), training.TrainConfig(lr_base=1e-4, lr_new=0.0))
    frozen = {n for n, p in model.named_parameters() if not p.requires_grad}
    assert frozen and all(is_new_parameter(n) for n in frozen)
    groups = training.param_groups(model, training.TrainConfig(lr_base=1e-4))
    assert [g["name"] for g in groups] == ["v3"]
    model = training.build_model(tiny_model(), training.TrainConfig(lr_base=1e-4, lr_new=1e-3))
    groups = training.param_groups(model, training.TrainConfig(lr_base=1e-4, lr_new=1e-3))
    assert [(g["name"], g["lr"]) for g in groups] == [("v3", 1e-4), ("new", 1e-3)]


def test_frozen_batchnorm_keeps_v3_running_statistics(inputs, export):
    model = training.build_model(tiny_model(), training.TrainConfig(lr_base=1e-4, bn="frozen"))
    before = model.bn1.module.running_mean.clone()
    training.set_train_mode(model, "frozen")
    assert model.training and not model.bn1.module.training
    splits, _ = data.read_export(export, splits=["train"])
    batch = data.to_device(
        data.collate([data.SimGraphs(inputs, splits["train"])[i] for i in range(6)]),
        torch.from_numpy(data.embedding_table(inputs)),
        "cpu",
    )
    training.forward(model, batch)
    assert torch.equal(model.bn1.module.running_mean, before)


def test_smoke_training_learns_checkpoints_and_stops(inputs, export, tmp_path):
    splits, _ = data.read_export(export)
    cfg = training.TrainConfig(
        lr_base=5e-4, batch_size=4, max_epochs=8, patience=8, warmup_steps=2, num_workers=0, eval_batch_size=8
    )
    table = torch.from_numpy(data.embedding_table(inputs))
    val = data.SimGraphs(inputs, splits["val"])
    model = training.build_model(tiny_model(), cfg)
    start = {k: v.clone() for k, v in model.state_dict().items()}

    def evaluate(m, epoch):
        return {"sim_val": training.evaluate_sim(m, val, table, torch.device("cpu"), cfg)}

    seen = []
    result = training.train(
        model,
        cfg,
        data.SimGraphs(inputs, splits["train"]),
        table,
        torch.device("cpu"),
        evaluate,
        tmp_path / "ckpt",
        on_epoch=lambda h: seen.append(len(h)),
    )
    history = result["history"]
    assert history[0]["epoch"] == 0 and "train" not in history[0]
    assert seen == list(range(1, len(history) + 1))
    assert all(h["train"]["loss"] > 0 and h["train"]["cases"] > 0 for h in history[1:])
    assert history[-1]["train"]["loss"] < history[1]["train"]["loss"]
    assert {p.name for p in (tmp_path / "ckpt").iterdir()} == {"best.pt", "last.pt"}
    assert result["epochs_run"] <= cfg.max_epochs
    best = max(h["sim_val"]["mrr"] for h in history)
    assert result["best_sim_val_mrr"] == pytest.approx(best) and result["epochs_run"] == 8
    reloaded = training.build_model(tiny_model(), cfg)
    assert training.load_checkpoint(reloaded, tmp_path / "ckpt" / "best.pt") == result["best_epoch"]
    # A-001 trains v3.0's tensors only; the new ones stay at their step-0 value.
    after = model.state_dict()
    assert all(torch.equal(after[k], start[k]) for k in start if is_new_parameter(k))
    assert any(not torch.equal(after[k], start[k]) for k in start if not is_new_parameter(k))


def test_early_stopping_on_sim_val_keeps_the_start_when_nothing_improves(inputs, export, tmp_path):
    splits, _ = data.read_export(export, splits=["train"])
    cfg = training.TrainConfig(lr_base=1e-4, batch_size=4, max_epochs=6, patience=2, num_workers=0)
    model = training.build_model(tiny_model(), cfg)
    table = torch.from_numpy(data.embedding_table(inputs))
    result = training.train(
        model,
        cfg,
        data.SimGraphs(inputs, splits["train"]),
        table,
        torch.device("cpu"),
        lambda m, epoch: {"sim_val": {"mrr": 0.5}},
        tmp_path / "ckpt",
    )
    assert result["epochs_run"] == 2 and result["stopped_early"] and result["best_epoch"] == 0
    fresh = training.build_model(tiny_model(), cfg)
    assert training.load_checkpoint(fresh, tmp_path / "ckpt" / "best.pt") == 0
    reference = training.build_model(tiny_model(), cfg).state_dict()
    assert all(torch.equal(v, reference[k]) for k, v in fresh.state_dict().items())


def test_lr_schedule_warms_up_then_decays_to_the_floor():
    f = [training.lr_factor(s, 10, 110, 0.1) for s in range(111)]
    assert f[0] == pytest.approx(0.1) and f[9] == pytest.approx(1.0)
    assert f[10] == pytest.approx(1.0) and f[110] == pytest.approx(0.1)
    assert all(a >= b for a, b in zip(f[10:], f[11:], strict=False))


def test_ranks_from_logits_are_pessimistic_like_rank_of():
    logits = torch.tensor([[3.0, 1.0, 3.0, 0.5], [0.0, 2.0, 1.0, 2.0]])
    assert training.ranks_from_logits(logits, torch.tensor([0, 3])).tolist() == [2, 2]


def test_flags():
    def epoch(e, sim, r1, s2, low=-0.001):
        return {"epoch": e, "sim_val": {"mrr": sim}, "r1_dev_present": {"mrr": r1, "ci95": [low, 0.0]},
                "s2": {"mrr": s2}}  # fmt: skip

    history = [epoch(0, 0.5, 0.45, 0.81), epoch(1, 0.6, 0.44, 0.80), epoch(2, 0.62, 0.43, 0.78, -0.02)]
    f = experiment.flags(history, best_epoch=2)
    assert f["simval_up_r1dev_down_epochs"] == [1, 2] and f["simval_up_r1dev_down_at_best"]
    assert f["s2_forgetting_at_best"] and f["s2_forgetting_epochs"] == [2]
    assert not f["no_regression_pass"]
    assert experiment.flags(history, best_epoch=1)["no_regression_pass"]


FROZEN_DESIGNS = [
    {"negated": True},
    {"negated": True, "neg_readout": True},
    {"covariates": True},
    {"negated": True, "neg_readout": True, "covariates": True},
]


def frozen_cfg(**design):
    return training.TrainConfig(
        lr_base=0.0,
        lr_new=5e-2,
        frozen_base=True,
        batch_size=4,
        max_epochs=4,
        patience=4,
        warmup_steps=2,
        num_workers=0,
        eval_batch_size=8,
        cov_hidden=8,
        **design,
    )


def present_only_logits(model, inputs, cases, extended: bool) -> list:
    out = []
    with torch.inference_mode():
        for case in cases:
            plain = case.model_copy(
                update={"excluded": (), "sex": "unknown", "age_years": None, "onset_years": None}
            )
            g, _ = graphs.case_graph(inputs, plain, negated=extended)
            x, e = torch.from_numpy(g.x), torch.from_numpy(g.edge_index)
            if extended:
                cov = torch.from_numpy(g.covariates)[None] if model.cov_mlp is not None else None
                out.append(model(x, e, torch.from_numpy(g.node_type), cov))
            else:
                out.append(model(x, e))
    return out


def test_frozen_base_config_trains_only_new_parameters():
    with pytest.raises(ValueError):
        training.TrainConfig(lr_base=1e-5, lr_new=1e-3, frozen_base=True, negated=True)
    with pytest.raises(ValueError):
        training.TrainConfig(lr_base=0.0, lr_new=0.0, frozen_base=True, negated=True)
    with pytest.raises(ValueError):
        training.TrainConfig(lr_base=0.0, lr_new=1e-3, frozen_base=True)
    model = training.build_model(tiny_model(), frozen_cfg(covariates=True))
    trainable = {n for n, p in model.named_parameters() if p.requires_grad}
    assert trainable and all(n.startswith("cov_") for n in trainable)
    groups = training.param_groups(model, frozen_cfg(covariates=True))
    assert [(g["name"], g["lr"]) for g in groups] == [("new", 5e-2)]


@pytest.mark.parametrize("design", FROZEN_DESIGNS)
def test_frozen_base_learns_yet_present_only_stays_bit_identical_to_v3(inputs, export, tmp_path, design):
    splits, _ = data.read_export(export)
    cfg = frozen_cfg(**design)
    base = tiny_model()
    table = torch.from_numpy(data.embedding_table(inputs))
    model = training.build_model(base, cfg)
    start = {k: v.clone() for k, v in model.state_dict().items()}
    cases = [c.to_case() for c in splits["val"]]
    reference = present_only_logits(base, inputs, cases, extended=False)
    assert all(
        torch.equal(a, b)
        for a, b in zip(present_only_logits(model, inputs, cases, True), reference, strict=True)
    )

    val = data.SimGraphs(inputs, splits["val"], negated=cfg.negated)
    result = training.train(
        model,
        cfg,
        data.SimGraphs(inputs, splits["train"], negated=cfg.negated),
        table,
        torch.device("cpu"),
        lambda m, epoch: {"sim_val": training.evaluate_sim(m, val, table, torch.device("cpu"), cfg)},
        tmp_path / "ckpt",
    )
    after = model.state_dict()
    assert any(not torch.equal(after[k], start[k]) for k in start if is_new_parameter(k))
    assert training.base_unchanged(model, base)
    assert training.positive_types_closed(model)
    assert not model.training
    # With the new inputs the model has moved; without them it is still v3.0, bit for bit.
    assert all(
        torch.equal(a, b)
        for a, b in zip(present_only_logits(model, inputs, cases, True), reference, strict=True)
    )
    assert result["history"][-1]["train"]["loss"] < result["history"][1]["train"]["loss"]

    saved = torch.load(tmp_path / "ckpt" / "last.pt", weights_only=True)
    assert saved["model"] and all(is_new_parameter(k) for k in saved["model"])
    fresh = training.build_model(tiny_model(), cfg)
    assert training.load_checkpoint(fresh, tmp_path / "ckpt" / "last.pt") == result["epochs_run"]
    assert all(torch.equal(v, after[k]) for k, v in fresh.state_dict().items())


def test_neutral_covariates_add_exactly_zero_at_any_weights():
    model = GinV3Extended.from_v3(tiny_model(), covariates=True, cov_neutral_zero=True, cov_hidden=8).eval()
    with torch.no_grad():
        model.cov_classifier.weight.normal_()
    neutral = torch.from_numpy(graphs.NEUTRAL_COVARIATES)[None]
    known = torch.tensor([[0, 1, 0, 1.0, 1, 0, 0]])
    x, e = torch.randn(2, 4), torch.tensor([[0], [1]])
    types = torch.tensor([graphs.NODE_OBSERVED, graphs.NODE_ANCESTOR])
    with torch.inference_mode():
        assert torch.equal(model(x, e, types, neutral), tiny_model()(x, e))
        assert not torch.equal(model(x, e, types, known), tiny_model()(x, e))
