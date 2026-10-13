"""v4 graph construction equals E0's (toy DAG, and E0's DAG when the bundle is there); IC from annotations."""

import json

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.systems.genphenia_v3 import HpoDag, V3Inputs
from diagnostic_ar_training.v4 import graphs, knowledge

# child -> parents; G has two parents; H's parents are listed out of id order.
PARENTS = {
    "A": [],
    "B": ["A"],
    "C": ["B"],
    "D": ["B"],
    "E": ["A"],
    "F": ["E"],
    "G": ["E", "C"],
    "H": ["G", "D"],
}


@pytest.fixture
def inputs(tmp_path):
    ids = ["H", "A", "C", "B", "G", "E", "D", "F"]
    index = {n: i for i, n in enumerate(ids)}
    offsets, parents = [0], []
    for n in ids:
        parents += [index[p] for p in PARENTS[n]]
        offsets.append(len(parents))
    np.savez(tmp_path / "dag.npz", node_ids=np.array(ids), parent_offsets=offsets, parent_indices=parents)
    (tmp_path / "index.json").write_text(json.dumps(index))
    built = object.__new__(V3Inputs)
    built.dag = HpoDag(tmp_path / "dag.npz", tmp_path / "index.json")
    built.dim = 2
    built.emb_index = {n: i for i, n in enumerate(sorted(ids)) if n != "F"}
    built.vectors = np.arange(2 * len(ids), dtype=np.float32).reshape(-1, 2) + 1
    return built


def e0_graph(inputs, present):
    known, _ = inputs.known_present(Case(case_id="c", cohort="t", gene="X", present=tuple(present)))
    return inputs.graph(known), len(known)


@pytest.mark.parametrize(
    "present", [["C"], ["H"], ["H", "F", "Z", "H"], ["G", "D"], ["A"], ["F", "C", "B"], ["Z", "H", "A"]]
)
def test_builder_gives_e0s_graph(inputs, present):
    builder = graphs.GraphBuilder(inputs.dag)
    (node_ids, _, edge_index), n_known = e0_graph(inputs, present)
    g = builder.build(present)
    assert tuple(inputs.dag.node_ids[i] for i in g.nodes) == node_ids
    assert np.array_equal(g.edge_index, edge_index) and g.n_observed == n_known


def test_unknown_only_case_has_no_graph(inputs):
    assert graphs.GraphBuilder(inputs.dag).build(["Z"]) is None


def test_node_tables_gather_e0s_embeddings(inputs):
    tables = graphs.node_tables(inputs)
    builder = graphs.GraphBuilder(inputs.dag)
    (node_ids, x, _), _ = e0_graph(inputs, ["H", "F"])
    assert np.array_equal(tables["embedding"][builder.build(["H", "F"]).nodes], x)


def test_information_content_drops_negations_and_propagates(inputs):
    rows = [
        {"database_id": "D1", "hpo_id": "C", "qualifier": "", "frequency": "HP:0040281"},
        {"database_id": "D2", "hpo_id": "F", "qualifier": "", "frequency": "3/4"},
        {"database_id": "D2", "hpo_id": "D", "qualifier": "NOT", "frequency": ""},
        {"database_id": "D3", "hpo_id": "D", "qualifier": "", "frequency": "0/5"},
        {"database_id": "D3", "hpo_id": "G", "qualifier": "", "frequency": "0%"},
        {"database_id": "D3", "hpo_id": "B", "qualifier": "", "frequency": "10%"},
    ]
    ann = knowledge.disease_terms(rows)
    assert ann == {"D1": {"C"}, "D2": {"F"}, "D3": {"B"}}
    ic = knowledge.information_content(ann, inputs.dag)
    at = {n: ic[inputs.dag.index[n]] for n in PARENTS}
    assert at["A"] == pytest.approx(0.0)
    assert at["B"] == pytest.approx(np.log(4 / 3) / np.log(4))
    assert at["D"] == at["H"] == pytest.approx(1.0)
    assert at["C"] > at["B"] > at["A"]


bundle = pytest.mark.skipif(
    not registry.verify(registry.load_sources()["genphenia_v3"]), reason="genphenia_v3 bundle not fetched"
)


@bundle
def test_builder_matches_e0_on_its_dag():
    from diagnostic_ar_training.systems.genphenia_v3 import unpack_bundle

    e0 = V3Inputs(unpack_bundle())
    builder = graphs.GraphBuilder(e0.dag)
    rng = np.random.default_rng(0)
    ids = e0.dag.node_ids
    for _ in range(300):
        present = [ids[i] for i in rng.integers(0, len(ids), rng.integers(1, 15))] + ["HP:9999999"]
        (node_ids, _, edge_index), n_known = e0_graph(e0, present)
        g = builder.build(present)
        assert tuple(ids[i] for i in g.nodes) == node_ids and np.array_equal(g.edge_index, edge_index)
