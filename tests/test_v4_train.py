"""v4 data stream and training loop on a toy DAG with a fake sampler (CPU, no bundle, no patients)."""

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from diagnostic_ar_training.cohorts.schema import Case, Sex  # noqa: E402
from diagnostic_ar_training.gnn.graphs import covariates  # noqa: E402
from diagnostic_ar_training.systems.genphenia_v3 import HpoDag, V3Inputs  # noqa: E402
from diagnostic_ar_training.v4 import config, data, evaluate, report, samplers, train  # noqa: E402
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
