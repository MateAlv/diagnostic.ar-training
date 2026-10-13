"""E0's patient graph on integer DAG indices, fast enough to build simulated cases on the fly.

`GraphBuilder.build(present)` gives the nodes and edges of `V3Inputs.graph(known_present)` exactly (same
node order: observed terms in first-seen order, then the other ancestors sorted by HPO id; same edge order:
for each node, its DAG parents in DAG order, child -> parent), as DAG indices. Unknown terms are left out;
a case with no known term has no graph (E0's unscorable rule). Node features are gathered on the device
from DAG-indexed tables (`node_tables`): E0's embedding (zero for terms without one) and the IC.
`tests/test_v4_graphs.py` checks the equivalence on a toy DAG and, with the bundle, on E0's.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CompactGraph:
    nodes: np.ndarray
    """[N] int64 DAG indices; the first `n_observed` are the observed terms."""
    edge_index: np.ndarray
    """[2, E] int64, child -> parent, local node positions."""
    n_observed: int


class GraphBuilder:
    def __init__(self, dag) -> None:
        self.node_ids = dag.node_ids
        self.index = dag.index
        n = len(dag.node_ids)
        self.offsets = np.asarray(dag.offsets, dtype=np.int64)
        self.parent_idx = np.asarray(dag.parent_idx, dtype=np.int64)
        order = sorted(range(n), key=lambda i: dag.node_ids[i])
        self.id_rank = np.empty(n, dtype=np.int64)
        self.id_rank[order] = np.arange(n)
        self.ancestors = self._closure(n)
        self._position = np.full(n, -1, dtype=np.int64)

    def _parents(self, i: int) -> np.ndarray:
        return self.parent_idx[self.offsets[i] : self.offsets[i + 1]]

    def _closure(self, n: int) -> list[np.ndarray]:
        """Strict ancestors of every node (iterative DFS with memoisation)."""
        done: list[np.ndarray | None] = [None] * n
        for root in range(n):
            if done[root] is not None:
                continue
            stack = [root]
            while stack:
                i = stack[-1]
                pending = [int(p) for p in self._parents(i) if done[int(p)] is None]
                if pending:
                    stack.extend(pending)
                    continue
                stack.pop()
                if done[i] is not None:
                    continue
                parents = self._parents(i)
                parts = [parents] + [done[int(p)] for p in parents]
                done[i] = np.unique(np.concatenate(parts)) if len(parents) else parents.copy()
        return done  # type: ignore[return-value]

    def known(self, present: Iterable[str]) -> list[int]:
        """Known present terms, deduplicated in first-seen order, as DAG indices."""
        out, seen = [], set()
        for t in present:
            i = self.index.get(t)
            if i is not None and i not in seen:
                seen.add(i)
                out.append(i)
        return out

    def build(self, present: Iterable[str]) -> CompactGraph | None:
        return self.build_indices(self.known(present))

    def build_indices(self, observed: Sequence[int]) -> CompactGraph | None:
        if not observed:
            return None
        obs = np.asarray(observed, dtype=np.int64)
        expanded = np.unique(np.concatenate([obs] + [self.ancestors[i] for i in observed]))
        rest = expanded[~np.isin(expanded, obs)]
        rest = rest[np.argsort(self.id_rank[rest], kind="stable")]
        nodes = np.concatenate([obs, rest])
        position = self._position
        position[nodes] = np.arange(len(nodes))
        try:
            counts = self.offsets[nodes + 1] - self.offsets[nodes]
            parents = (
                np.concatenate([self._parents(int(i)) for i in nodes])
                if counts.sum()
                else np.zeros(0, np.int64)
            )
            src = np.repeat(np.arange(len(nodes), dtype=np.int64), counts)
            dst = position[parents]
            keep = dst >= 0
            edge_index = np.stack([src[keep], dst[keep]]).astype(np.int64)
        finally:
            position[nodes] = -1
        return CompactGraph(nodes, edge_index, len(obs))


def node_tables(inputs, ic: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """DAG-indexed node features: E0's embedding (a zero row without one) and, when given, the IC."""
    ids = inputs.dag.node_ids
    emb = np.zeros((len(ids), inputs.dim), dtype=np.float32)
    for i, n in enumerate(ids):
        row = inputs.emb_index.get(n)
        if row is not None:
            emb[i] = inputs.vectors[row]
    tables = {"embedding": emb}
    if ic is not None:
        if ic.shape != (len(ids),):
            raise ValueError("the IC table must be aligned with the DAG")
        tables["ic"] = ic.astype(np.float32)
    return tables
