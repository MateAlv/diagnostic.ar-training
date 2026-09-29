"""Simulated training data (simulator export v2) -> batches for GinV3Extended.

- `read_export` streams the gzip JSONL once and keeps compact records of the wanted simulator splits,
  dropping the case ids of a training-exclusion artifact (EVAL_PROTOCOL §9.7).
- Graphs are `graphs.case_graph`'s, the production construction. Workers send each node's embedding row
  instead of its 768 floats; the model side gathers `x = table[rows]` from `embedding_table`, which is
  exactly `V3Inputs.embed` (a zero vector for terms without an embedding). `tests/test_gnn_data.py`
  checks the equivalence against `graphs.collate`.
- A-001 feeds positives only; `negated` and the covariates are ready for A-002+.
"""

import gzip
import json
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import numpy as np
import torch

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.gnn.graphs import N_COVARIATES, case_graph
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs

SIM_SPLITS = ("train", "val", "test")


class SimCase(NamedTuple):
    case_id: str
    gene: str
    gene_index: int
    present: tuple[str, ...]
    excluded: tuple[str, ...]
    sex: str
    age_years: float | None
    onset_years: float | None

    def to_case(self, cohort: str = "sim") -> Case:
        return Case(
            case_id=self.case_id,
            cohort=cohort,
            gene=self.gene,
            present=self.present,
            excluded=self.excluded,
            sex=Sex(self.sex),
            age_years=self.age_years,
            onset_years=self.onset_years,
        )


def read_exclusion(path: Path) -> frozenset[str]:
    return frozenset(line.strip() for line in Path(path).read_text().splitlines() if line.strip())


def read_export(
    path: Path, splits: Iterable[str] = SIM_SPLITS, exclude: frozenset[str] = frozenset()
) -> tuple[dict[str, list[SimCase]], dict]:
    """Cases per simulator split, excluded ids dropped; counts of what was read and dropped."""
    wanted = set(splits)
    unknown = wanted - set(SIM_SPLITS)
    if unknown:
        raise ValueError(f"unknown simulator splits {sorted(unknown)}")
    out: dict[str, list[SimCase]] = {s: [] for s in sorted(wanted)}
    read, dropped = Counter(), Counter()
    intern = sys.intern
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            split = r["split"]
            read[split] += 1
            if r["case_id"] in exclude:
                dropped[split] += 1
                continue
            if split not in wanted:
                continue
            out[split].append(
                SimCase(
                    r["case_id"],
                    intern(r["gene"]),
                    int(r["gene_index"]),
                    tuple(intern(t) for t in r["present"]),
                    tuple(intern(t) for t in r["excluded"]),
                    intern(r["sex"]),
                    r["age_years"],
                    r["onset_years"],
                )
            )
    counts = {"read": dict(read), "excluded": dict(dropped), "kept": {s: len(v) for s, v in out.items()}}
    return out, counts


def overlap_key(gene: str, present: Iterable[str]) -> tuple[str, frozenset[str]]:
    """The exclusion artifact's key: gene (case-insensitive) and present-term set."""
    return gene.upper(), frozenset(present)


def residual_overlap(train: Iterable[SimCase], evaluation: Iterable[Case]) -> list[str]:
    """Evaluation case ids that still share (gene, present set) with a training case."""
    seen = {overlap_key(c.gene, c.present) for c in train}
    return [c.case_id for c in evaluation if overlap_key(c.gene, c.present) in seen]


def embedding_table(inputs: V3Inputs) -> np.ndarray:
    """[rows + 1, dim]: v3.0's embeddings, and a last all-zero row for terms without one."""
    table = np.zeros((inputs.vectors.shape[0] + 1, inputs.dim), dtype=np.float32)
    table[:-1] = inputs.vectors
    return table


@dataclass(frozen=True)
class CompactGraph:
    rows: np.ndarray
    """[N] int64: each node's row in `embedding_table`."""
    edge_index: np.ndarray
    node_type: np.ndarray
    covariates: np.ndarray


def compact_graph(inputs: V3Inputs, case: Case, negated: bool) -> CompactGraph | None:
    graph, _ = case_graph(inputs, case, negated=negated)
    if graph is None:
        return None
    zero_row = inputs.vectors.shape[0]
    rows = np.fromiter(
        (inputs.emb_index.get(n, zero_row) for n in graph.node_ids), dtype=np.int64, count=len(graph.node_ids)
    )
    return CompactGraph(rows, graph.edge_index, graph.node_type, graph.covariates)


class SimGraphs(torch.utils.data.Dataset):
    """Item i: (index, compact graph or None when no present term is known, target class)."""

    def __init__(self, inputs: V3Inputs, cases: Sequence[SimCase], negated: bool = False) -> None:
        self.inputs, self.cases, self.negated = inputs, cases, negated

    def __len__(self) -> int:
        return len(self.cases)

    def __getitem__(self, i: int) -> tuple[int, CompactGraph | None, int]:
        sim = self.cases[i]
        case = sim.to_case()
        if not self.negated:
            case = case.model_copy(update={"excluded": ()})
        return i, compact_graph(self.inputs, case, self.negated), sim.gene_index


def collate(items: list[tuple[int, CompactGraph | None, int]]) -> dict:
    """PyG-style batch of the scorable items (as graphs.collate), plus their dataset indices and targets."""
    kept = [(i, g, y) for i, g, y in items if g is not None]
    graphs = [g for _, g, _ in kept]
    sizes = [len(g.rows) for g in graphs]
    offsets = np.cumsum([0] + sizes[:-1])
    edges = [g.edge_index + o for g, o in zip(graphs, offsets, strict=True)]

    def cat(arrays: list[np.ndarray], empty: np.ndarray, axis: int = 0) -> torch.Tensor:
        return torch.from_numpy(np.concatenate(arrays, axis=axis) if arrays else empty)

    return {
        "rows": cat([g.rows for g in graphs], np.zeros(0, np.int64)),
        "edge_index": cat(edges, np.zeros((2, 0), np.int64), axis=1),
        "node_type": cat([g.node_type for g in graphs], np.zeros(0, np.int64)),
        "batch": torch.from_numpy(np.repeat(np.arange(len(graphs), dtype=np.int64), sizes)),
        "covariates": torch.from_numpy(
            np.stack([g.covariates for g in graphs]) if graphs else np.zeros((0, N_COVARIATES), np.float32)
        ),
        "target": torch.tensor([y for _, _, y in kept], dtype=torch.int64),
        "index": torch.tensor([i for i, _, _ in kept], dtype=torch.int64),
        "n_unscorable": len(items) - len(kept),
    }


def _seed_worker(worker_id: int) -> None:
    seed = torch.initial_seed() % 2**32
    np.random.seed(seed)


def loader(
    dataset: SimGraphs,
    batch_size: int,
    shuffle_seed: int | None,
    num_workers: int,
    pin_memory: bool = False,
) -> torch.utils.data.DataLoader:
    """Deterministic order: a seeded permutation (or the dataset order when `shuffle_seed` is None)."""
    generator = None
    if shuffle_seed is not None:
        generator = torch.Generator().manual_seed(shuffle_seed)
    return torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle_seed is not None,
        generator=generator,
        num_workers=num_workers,
        collate_fn=collate,
        pin_memory=pin_memory,
        worker_init_fn=_seed_worker,
        persistent_workers=False,
        prefetch_factor=4 if num_workers else None,
    )


def to_device(batch: dict, table: torch.Tensor, device: torch.device) -> dict:
    """Model inputs on `device`, with node features gathered from the embedding table there."""
    moved = {k: v.to(device, non_blocking=True) for k, v in batch.items() if isinstance(v, torch.Tensor)}
    moved["x"] = table.index_select(0, moved.pop("rows"))
    moved["num_graphs"] = int(batch["target"].numel())
    return moved
