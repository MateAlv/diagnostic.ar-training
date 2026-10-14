"""v4 data stream, training loop and runs on a toy DAG, a fake sampler and toy patients (CPU, no bundle)."""

import json
import types

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from diagnostic_ar_training.cohorts.schema import Case, Sex  # noqa: E402
from diagnostic_ar_training.gnn.graphs import covariates  # noqa: E402
from diagnostic_ar_training.lineage.registry import LineageError  # noqa: E402
from diagnostic_ar_training.systems.genphenia_v3 import HpoDag, V3Inputs  # noqa: E402
from diagnostic_ar_training.v4 import (  # noqa: E402
    config,
    data,
    evaluate,
    model,
    patients,
    report,
    runs,
    samplers,
    train,
)
from diagnostic_ar_training.v4.graphs import GraphBuilder, node_tables  # noqa: E402
from diagnostic_ar_training.v4.model import GinV4  # noqa: E402
from diagnostic_ar_training.v4.patients import UNCITED, Patient  # noqa: E402

PARENTS = {"A": [], "B": ["A"], "C": ["B"], "D": ["B"], "E": ["A"], "F": ["E"], "G": ["C", "E"]}
GENES = ("-", "g1", "g2", "g3")


class FakeSampler:
    genes = GENES
    simulable_gene_indices = np.array([0, 1, 2, 3])
    profiles = {0: ["A"], 1: ["C", "D"], 2: ["F", "G"], 3: ["D", "Z"]}

    def sample(self, gene_index, rng):
        terms = self.profiles[gene_index]
        if rng.random() < 0.1:
            return ["Z"]
        return [terms[i] for i in rng.permutation(len(terms))[: rng.integers(1, len(terms) + 1)]]


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
    built.emb_index = {n: i for i, n in enumerate(ids)}
    built.vectors = np.random.default_rng(0).normal(size=(len(ids), 4)).astype(np.float32)
    return built


def stream(inputs, **kw):
    s = FakeSampler()
    return data.TrainStream(s, GraphBuilder(inputs.dag), samplers.gene_pool(s, True), 8, seed=0, **kw)


def test_stream_is_seeded_and_never_draws_the_dash(inputs):
    a, b = next(iter(stream(inputs))), next(iter(stream(inputs)))
    assert all(torch.equal(a[k], b[k]) for k in a)
    assert (a["target"] != 0).all() and a["batch"].max() == 7
    assert a["observed"].sum() >= 8 and a["edge_index"].max() < a["nodes"].numel()
    other = stream(inputs)
    other.stream = 1
    assert not torch.equal(next(iter(other))["target"], a["target"])


def test_real_patients_are_mixed_at_the_ratio(inputs):
    builder = GraphBuilder(inputs.dag)
    real = [data.Item(builder.build(["C"]), 3, covariates(case(["C"])), True)]
    s = stream(inputs, real=real, real_ratio=0.5)
    it = iter(s)
    share = np.mean([next(it)["real"].float().mean().item() for _ in range(50)])
    assert 0.4 < share < 0.6
    with pytest.raises(ValueError):
        stream(inputs, real_ratio=0.5)


def test_simulated_covariates_match_the_case_encoding():
    got = data.covariate_vector("female", 4.0, None)
    want = covariates(Case(case_id="c", cohort="t", gene="g", present=("A",), sex=Sex.FEMALE, age_years=4.0))
    assert np.array_equal(got, want)


def case(present, gene="g1", cid="c"):
    return Case(case_id=cid, cohort="t", gene=gene, present=tuple(present))


def select_set(inputs):
    patients = [
        Patient(case(["C", "D"], "g1", "s1"), "p1", UNCITED, 3),
        Patient(case(["G"], "g2", "s2"), "p2", UNCITED, 3),
        Patient(case(["Z"], "g2", "s3"), "p3", UNCITED, 3),
        Patient(case(["D"], "unknown", "s4"), "p3", UNCITED, 3),
    ]
    return evaluate.PatientSet.build(patients, GraphBuilder(inputs.dag), GENES)


def test_training_runs_checkpoints_and_resumes(inputs, tmp_path):
    cfg = config.from_dict(
        {
            "label": "toy",
            "encoding": {"observed_flag": True, "edges": "both", "drop_dash": True},
            "arch": {"hidden": 8, "layers": 2},
            "train": {
                "batch_size": 8,
                "max_samples": 32,
                "eval_every_steps": 2,
                "num_workers": 0,
                "amp": False,
                "warmup_steps": 2,
            },
        }
    )
    tables = data.NodeTables(node_tables(inputs), torch.device("cpu"))
    pset = select_set(inputs)
    model = GinV4(4, len(GENES), cfg.arch, cfg.encoding)
    out = train.train(
        cfg, model, stream(inputs), tables, pset, tmp_path, torch.device("cpu"), log=lambda s: None
    )
    assert out["steps"] == 4 and out["samples"] == 32
    hist = train.history(tmp_path)
    assert [h["step"] for h in hist] == [0, 2, 4] and train.step0(tmp_path) is not None
    assert (tmp_path / "best.pt").is_file() and (tmp_path / "last.pt").is_file()

    longer = config.override(cfg, {"train.max_samples": 64})
    out = train.train(
        longer, model, stream(inputs), tables, pset, tmp_path, torch.device("cpu"), log=lambda s: None
    )
    assert out["steps"] == 8 and out["resumes"] == 1
    assert [h["step"] for h in train.history(tmp_path)] == [0, 2, 4, 6, 8]

    records = evaluate.model_records(model, pset, tables, cfg.encoding)
    assert [r["scorable"] for r in records] == [True, True, False, True]
    assert np.isinf(records[2]["rank"]) and np.isinf(records[3]["rank"]) and not records[3]["gene_in_vocab"]
    assert all(1 <= r["rank"] <= len(GENES) - 1 for r in records[:2])
    assert report.summarize(records)["strata"]["uncited"]["n"] == 4


def test_cosine_schedule_and_budgets():
    cfg = config.from_dict({"train": {"max_minutes": 10, "max_samples": 1000, "warmup_steps": 10}})
    assert train.lr_factor(cfg, 0, 0.0, 1.0) == pytest.approx(0.1)
    assert train.lr_factor(cfg, 100, 1.0, 1.0) == pytest.approx(cfg.train.min_lr_ratio)
    assert train.progress(cfg, 300, 100) == pytest.approx(0.5)
    assert (
        train.budget_spent(cfg, 0, 1000)
        and train.budget_spent(cfg, 600, 0)
        and not train.budget_spent(cfg, 1, 1)
    )


def real_item(builder, gene, group, terms=("C",)):
    return data.Item(builder.build(list(terms)), gene, covariates(case(terms)), True, group)


def gene_shares(s, n, seed=0):
    rng = np.random.default_rng(seed)
    items = [s.item(rng) for _ in range(n)]
    targets = np.array([it.target for it in items])
    return np.array([np.mean(targets == g) for g in (1, 2, 3)]), items


def test_gene_balanced_draw_keeps_the_simulators_label_marginal(inputs):
    builder = GraphBuilder(inputs.dag)
    real = [real_item(builder, 1, f"P{k % 3}") for k in range(30)] + [real_item(builder, 2, "Q")]
    sim, _ = gene_shares(stream(inputs), 6000, seed=1)
    balanced, items = gene_shares(stream(inputs, real=real, real_ratio=0.5, real_draw="gene"), 6000, seed=2)
    by_patient, _ = gene_shares(stream(inputs, real=real, real_ratio=0.5), 6000, seed=3)
    assert np.abs(balanced - sim).max() < 0.03
    assert by_patient[0] > sim[0] + 0.2
    share = {g: np.mean([it.real for it in items if it.target == g]) for g in (1, 2, 3)}
    assert 0.4 < share[1] < 0.6 and 0.4 < share[2] < 0.6 and share[3] == 0


def test_gene_balanced_draw_is_uniform_over_the_genes_publications(inputs):
    builder = GraphBuilder(inputs.dag)
    real = [real_item(builder, 1, "big") for _ in range(99)] + [real_item(builder, 1, "small")]
    s = stream(inputs, real=real, real_ratio=0.9, real_draw="gene")
    assert [len(p) for p in s.real_by_gene[1]] == [99, 1]
    _, items = gene_shares(s, 4000)
    groups = [it.group for it in items if it.real]
    assert 0.45 < groups.count("small") / len(groups) < 0.55
    with pytest.raises(ValueError, match="publication group"):
        stream(
            inputs, real=[data.Item(builder.build(["C"]), 1, covariates(case(["C"])), True)], real_draw="gene"
        )
    with pytest.raises(ValueError, match="pool"):
        stream(inputs, real=[real_item(builder, 0, "dash")], real_ratio=0.5, real_draw="gene")


TERMS = {"g1": ("C", "D"), "g2": ("F", "G"), "g3": ("D",)}
FOLDS = types.SimpleNamespace(FIT_FOLDS=(0, 1, 2), SELECT_FOLD=3, CONFIRM_FOLD=4, fold_of=None)


def toy_patients():
    out = []
    for fold in range(5):
        for k, gene in enumerate(("g1", "g2", "g3")):
            for j in range(1 + k):
                terms = TERMS[gene][: 1 + (j % len(TERMS[gene]))]
                out.append(Patient(case(terms, gene, f"f{fold}-{gene}-{j}"), f"P{fold}-{k}", UNCITED, fold))
    return out


@pytest.fixture
def ctx(inputs, tmp_path, monkeypatch, clean_tree):
    monkeypatch.setattr(runs, "V4_DIR", tmp_path / "v4")
    monkeypatch.setattr(runs, "P3_RESULTS", tmp_path / "P3")
    monkeypatch.setattr(patients, "_folds", lambda: FOLDS)
    monkeypatch.setattr(patients, "load_train", lambda keep_covariates=False: toy_patients())
    monkeypatch.setattr(samplers, "build", lambda sim: FakeSampler())
    monkeypatch.setattr(
        evaluate,
        "e0_records",
        lambda ps, e0=None: [report.record(p, True, True, float(len(p.case.present))) for p in ps],
    )
    c = object.__new__(runs.Context)
    c.device, c.inputs, c.genes = torch.device("cpu"), inputs, GENES
    c.builder = GraphBuilder(inputs.dag)
    c._tables, c._sets, c._e0 = {}, {}, {}
    return c


def toy_config(**sim):
    return config.from_dict(
        {
            "label": "toy",
            "sim": sim,
            "arch": {"hidden": 8, "layers": 2},
            "train": {
                "batch_size": 8,
                "max_samples": 32,
                "eval_every_steps": 2,
                "num_workers": 0,
                "amp": False,
                "warmup_steps": 2,
            },
        }
    )


def test_real_items_come_from_fit_folds_only(ctx):
    items = ctx.patient_set("fit").items()
    assert {it.group.split("-")[0] for it in items} == {"P0", "P1", "P2"}
    s = data.TrainStream(
        FakeSampler(), ctx.builder, np.array([1, 2, 3]), 8, 0, real=items, real_ratio=0.9, real_draw="gene"
    )
    _, drawn = gene_shares(s, 2000)
    assert {it.group.split("-")[0] for it in drawn if it.real} == {"P0", "P1", "P2"}


def test_real_patients_come_from_the_runs_real_folds(ctx):
    assert ctx.patient_set((0, 1, 2)) is ctx.patient_set("fit")
    cfg = toy_config(real_ratio=0.5, real_draw="gene", real_folds=[1, 2, 3])
    row = runs.train_run(cfg, ctx, require_clean=False, log=lambda s: None)
    pool = ctx.patient_set((1, 2, 3))
    assert {p.fold for p in pool.patients} == {1, 2, 3} and row["n_real_fit_items"] == len(pool.patients)
    assert row["real_folds"] == [1, 2, 3] and row["real_by_gene"]["patients"] == len(pool.patients)
    for swap in (False, True):
        for fold_set in runs.FOLD_SETS:
            assert (runs.ranks_dir(cfg.run_id, "last", swap) / f"{fold_set}.ranks.jsonl").is_file()
    with pytest.raises(LineageError, match="CONFIRM"):
        ctx.patient_set((3, 4))


def test_phenotype_swap_sets_pair_identically_for_every_run(ctx):
    plain, swapped = ctx.patient_set("select"), ctx.patient_set("select", swap=True)
    again = ctx.patient_set("select", keep_covariates=True, swap=True)
    assert swapped.swap_from == again.swap_from and plain.swap_from is None
    by_id = {p.case_id: p for p in plain.patients}
    for p, q, source in zip(plain.patients, swapped.patients, swapped.swap_from, strict=True):
        assert q.case_id == p.case_id and q.case.gene == p.case.gene and q.group == p.group
        assert source != p.case_id and q.case.present == by_id[source].case.present


def test_train_run_reads_best_final_and_swap_then_warm_starts(ctx):
    cfg = toy_config(real_ratio=0.5, real_draw="gene")
    row = runs.train_run(cfg, ctx, require_clean=False, log=lambda s: None)
    assert row["status"] == runs.COMPLETE and row["real_by_gene"]["genes"] == 3
    assert {"select", "fit", "final", "swap", "final_swap"} <= set(row)
    summary = json.loads((runs.run_dir(cfg.run_id) / "summary.json").read_text())
    assert (
        summary["final"]["step"] == 4 and summary["final_swap"]["swap"] and summary["best_step"] in (0, 2, 4)
    )
    for checkpoint in runs.CHECKPOINTS:
        for swap in (False, True):
            assert (runs.ranks_dir(cfg.run_id, checkpoint, swap) / "fit.ranks.jsonl").is_file()
    swapped = report.read_ranks(runs.ranks_dir(cfg.run_id, swap=True) / "select.ranks.jsonl")
    e0 = report.read_ranks(runs.ranks_dir(runs.E0_RUN, swap=True) / "select.ranks.jsonl")
    assert [r["swap_from"] for r in swapped] == [r["swap_from"] for r in e0]
    present = {p.case_id: p.case.present for p in toy_patients()}
    assert all(r["rank"] == len(present[r["swap_from"]]) for r in e0)

    runs.evaluate_run(cfg.run_id, ctx, lambda s: None)
    again = json.loads((runs.run_dir(cfg.run_id) / "summary.json").read_text())
    assert again["final"] == summary["final"] and "final" in runs.read_row(cfg.run_id)

    warm = config.override(
        cfg, {"label": "warm", "arch.init": f"run:{cfg.run_id}@best", "sim.real_ratio": 0.0}
    )
    weights, source = runs.run_weights(warm.arch)
    best = torch.load(runs.run_dir(cfg.run_id) / "best.pt", weights_only=False)
    assert source == {"run_id": cfg.run_id, "checkpoint": "best", "step": best["state"]["step"]}
    net = model.build(warm.arch, warm.encoding, None, len(GENES), 4, weights)
    assert all(torch.equal(v, best["model"][k]) for k, v in net.state_dict().items())
    row = runs.train_run(warm, ctx, require_clean=False, log=lambda s: None)
    assert row["init"] == source and "swap" not in row and "final" in row
    at_best = [h["select"] for h in train.history(runs.run_dir(cfg.run_id)) if h["step"] == source["step"]]
    assert train.step0(runs.run_dir(warm.run_id)) == at_best[-1]

    wider = config.override(warm, {"arch.hidden": 16})
    with pytest.raises(RuntimeError):
        model.build(wider.arch, wider.encoding, None, len(GENES), 4, weights)
    with pytest.raises(ValueError, match="weights"):
        model.build(warm.arch, warm.encoding, None, len(GENES), 4)
    with pytest.raises(FileNotFoundError):
        runs.run_weights(config.ArchConfig(init="run:missing-0"))
