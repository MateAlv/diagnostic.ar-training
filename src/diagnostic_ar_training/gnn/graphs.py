"""Cases -> graph arrays for the torch models, batched PyG-style (concatenate nodes, offset edges, `batch`).

The positive graph is `V3Inputs.graph`, the production construction: observed terms first, then their
ancestors sorted, edges child -> parent, zero vectors for terms without an embedding.

Negated terms (`Case.excluded`, only when asked for; docs/decisions/0009-step-zero-identity.md) are
appended after the positive graph, so positive node and edge order never changes:
- one node per negated term the DAG knows, deduplicated in first-seen order, with its embedding. A term
  that is also in the positive graph still gets its own negated node;
- negated terms are not expanded to their ancestors;
- each negated node gets edges negated -> its nearest positive ancestors: walk up the DAG from the term
  and stop at the first nodes already in the positive graph. That graph is closed under ancestors, so
  these are the most specific positive terms subsuming the negated one (its parents, when they are in).
"""

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.systems.genphenia_v3 import HpoDag, V3Inputs

NODE_OBSERVED, NODE_ANCESTOR, NODE_NEGATED = 0, 1, 2
N_NODE_TYPES = 3

SEX_ORDER = (Sex.MALE, Sex.FEMALE, Sex.UNKNOWN)
COVARIATE_NAMES = ("male", "female", "sex_unknown", "log1p_age", "age_known", "log1p_onset", "onset_known")
N_COVARIATES = len(COVARIATE_NAMES)
NEUTRAL_COVARIATES = np.array([0, 0, 1, 0, 0, 0, 0], dtype=np.float32)


@dataclass(frozen=True)
class CaseGraph:
    node_ids: tuple[str, ...]
    x: np.ndarray
    """[N, 768] float32."""
    edge_index: np.ndarray
    """[2, E] int64, source -> target."""
    node_type: np.ndarray
    """[N] int64, NODE_*."""
    covariates: np.ndarray
    """[N_COVARIATES] float32."""


@dataclass(frozen=True)
class GraphBatch:
    x: np.ndarray
    edge_index: np.ndarray
    node_type: np.ndarray
    batch: np.ndarray
    """[N] int64: the graph each node belongs to."""
    covariates: np.ndarray
    """[G, N_COVARIATES] float32."""

    @property
    def num_graphs(self) -> int:
        return len(self.covariates)

    def to_torch(self, device="cpu") -> dict:
        import torch

        tensors = {k: torch.from_numpy(getattr(self, k)).to(device) for k in self.__dataclass_fields__}
        return {**tensors, "num_graphs": self.num_graphs}


def covariates(case: Case) -> np.ndarray:
    """Sex one-hot (male, female, unknown), log1p(age), age known, log1p(onset), onset known.

    Unknown values are 0 with their flag 0. Prenatal onsets (negative years) count as 0.
    `onset_term` is not used.
    """
    v = np.zeros(N_COVARIATES, dtype=np.float32)
    v[SEX_ORDER.index(case.sex)] = 1
    if case.age_years is not None:
        v[3], v[4] = math.log1p(max(case.age_years, 0.0)), 1
    if case.onset_years is not None:
        v[5], v[6] = math.log1p(max(case.onset_years, 0.0)), 1
    return v


def nearest_members(dag: HpoDag, term: str, members: set[str]) -> set[str]:
    found, seen, queue = set(), {term}, deque(dag.parents(term))
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        if node in members:
            found.add(node)
        else:
            queue.extend(dag.parents(node))
    return found


def case_graph(inputs: V3Inputs, case: Case, negated: bool = False) -> tuple[CaseGraph | None, dict]:
    """The case's graph (None when no present term is known, as for E0) and the per-case coverage info.

    Without `negated`, nodes, features and edges are exactly `V3Inputs.graph`'s.
    """
    known, info = inputs.known_present(case)
    if not known:
        return None, info
    node_ids, x, edge_index = inputs.graph(known)
    info.update(n_nodes=len(node_ids), n_zero_embedded_nodes=sum(n not in inputs.emb_index for n in node_ids))
    node_type = np.full(len(node_ids), NODE_ANCESTOR, dtype=np.int64)
    node_type[: len(known)] = NODE_OBSERVED
    if negated:
        excluded = list(dict.fromkeys(case.excluded))
        neg_ids = tuple(t for t in excluded if t in inputs.dag.index)
        info.update(n_excluded=len(excluded), n_excluded_unknown=len(excluded) - len(neg_ids))
        if neg_ids:
            position = {n: i for i, n in enumerate(node_ids)}
            members = set(node_ids)
            neg_edges = [
                (len(node_ids) + k, j)
                for k, term in enumerate(neg_ids)
                for j in sorted(position[p] for p in nearest_members(inputs.dag, term, members))
            ]
            node_ids = node_ids + neg_ids
            x = np.concatenate([x, inputs.embed(neg_ids)])
            if neg_edges:
                edge_index = np.concatenate([edge_index, np.asarray(neg_edges, dtype=np.int64).T], axis=1)
            node_type = np.concatenate([node_type, np.full(len(neg_ids), NODE_NEGATED, dtype=np.int64)])
    graph = CaseGraph(node_ids, x, edge_index, node_type, covariates(case))
    return graph, info


def collate(graphs: list[CaseGraph]) -> GraphBatch:
    offsets = np.cumsum([0] + [len(g.node_ids) for g in graphs[:-1]])
    return GraphBatch(
        x=np.concatenate([g.x for g in graphs]),
        edge_index=np.concatenate([g.edge_index + o for g, o in zip(graphs, offsets, strict=True)], axis=1),
        node_type=np.concatenate([g.node_type for g in graphs]),
        batch=np.concatenate([np.full(len(g.node_ids), i, dtype=np.int64) for i, g in enumerate(graphs)]),
        covariates=np.stack([g.covariates for g in graphs]),
    )
