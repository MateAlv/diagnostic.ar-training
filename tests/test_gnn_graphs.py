"""Graph construction for the torch models, on a toy DAG (no bundle, no torch)."""

import json

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.gnn import graphs
from diagnostic_ar_training.systems.genphenia_v3 import HpoDag, V3Inputs

# child -> parents; G has two parents.
PARENTS = {"A": [], "B": ["A"], "C": ["B"], "D": ["B"], "E": ["A"], "F": ["E"], "G": ["C", "E"]}


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
    built.dim = 2
    built.emb_index = {n: i for i, n in enumerate(ids) if n != "F"}
    built.vectors = np.arange(2 * len(ids), dtype=np.float32).reshape(-1, 2) + 1
    return built


def case(present, excluded=(), **kw):
    return Case(case_id="c", cohort="t", gene="X", present=tuple(present), excluded=tuple(excluded), **kw)


def test_without_negated_the_graph_is_the_production_graph(inputs):
    graph, info = graphs.case_graph(inputs, case(["C", "Z"], excluded=["D"]))
    node_ids, x, edge_index = inputs.graph(["C"])
    assert graph.node_ids == node_ids == ("C", "A", "B")
    assert np.array_equal(graph.x, x) and np.array_equal(graph.edge_index, edge_index)
    assert graph.node_type.tolist() == [graphs.NODE_OBSERVED, graphs.NODE_ANCESTOR, graphs.NODE_ANCESTOR]
    assert info["n_unknown"] == 1 and info["n_nodes"] == 3


def test_negated_nodes_are_appended_and_linked_to_their_nearest_positive_ancestors(inputs):
    graph, info = graphs.case_graph(
        inputs, case(["C"], excluded=["G", "D", "F", "C", "Z", "D"]), negated=True
    )
    positive, _, positive_edges = inputs.graph(["C"])
    assert graph.node_ids == positive + ("G", "D", "F", "C")
    assert np.array_equal(graph.edge_index[:, : positive_edges.shape[1]], positive_edges)
    assert graph.node_type.tolist()[3:] == [graphs.NODE_NEGATED] * 4
    neg = {(graph.node_ids[s], graph.node_ids[t]) for s, t in graph.edge_index.T if s >= 3}
    # G: parent C is positive; through E (not positive) it reaches A. F has no embedding.
    assert neg == {("G", "C"), ("G", "A"), ("D", "B"), ("F", "A"), ("C", "B")}
    assert not any(t >= 3 for t in graph.edge_index[1])
    assert np.array_equal(graph.x[3], inputs.vectors[inputs.emb_index["G"]])
    assert not graph.x[5].any()
    assert info["n_excluded"] == 5 and info["n_excluded_unknown"] == 1


def test_unscorable_case_has_no_graph(inputs):
    graph, info = graphs.case_graph(inputs, case(["Z"], excluded=["C"]), negated=True)
    assert graph is None and info["n_unknown"] == 1


def test_collate_offsets_edges_and_marks_graphs(inputs):
    a = graphs.case_graph(inputs, case(["C"]))[0]
    b = graphs.case_graph(inputs, case(["F"], excluded=["D"]), negated=True)[0]
    batch = graphs.collate([a, b])
    assert batch.num_graphs == 2
    assert batch.batch.tolist() == [0] * len(a.node_ids) + [1] * len(b.node_ids)
    assert np.array_equal(batch.edge_index[:, : a.edge_index.shape[1]], a.edge_index)
    assert np.array_equal(batch.edge_index[:, a.edge_index.shape[1] :], b.edge_index + len(a.node_ids))
    assert np.array_equal(batch.x, np.concatenate([a.x, b.x]))


def test_covariates():
    assert graphs.covariates(case(["C"])).tolist() == graphs.NEUTRAL_COVARIATES.tolist()
    v = graphs.covariates(case(["C"], sex=Sex.FEMALE, age_years=9.0, onset_years=-0.2))
    assert v[:3].tolist() == [0, 1, 0]
    assert v[3] == pytest.approx(np.log1p(9.0)) and v[4] == 1
    assert v[5] == 0 and v[6] == 1
