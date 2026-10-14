"""Training batches built on the fly: simulated cases, optionally mixed with real FIT-fold patients.

- Each DataLoader worker owns `np.random.default_rng([seed, stream, worker])` and yields whole batches
  (`batch_size=None` in the DataLoader), so per-item overhead stays in the worker. `stream` changes on each
  resume, so a resumed run never replays its own samples.
- Each item, `real_draw: patient`: with probability `real_ratio` a real patient drawn uniformly (graphs
  precomputed in the parent and shared by fork), otherwise a gene from the pool (uniform) and
  `sampler.sample(gene, rng)`. A simulated case with no term in E0's DAG is redrawn and counted.
- `real_draw: gene`: the simulated case is drawn first, so its gene follows the simulator's draw (redraws
  included). When that gene has real patients, with probability `real_ratio` the item is one of them instead:
  a publication uniform among the gene's, then a patient uniform within it. The label marginal is the
  simulator's, whatever the number of real patients or publications per gene (no cohort gene prior).
- Workers send DAG indices; `to_device` gathers E0's embedding (and the IC) from DAG-indexed tables on the
  device, so a batch carries ints only.
"""

import math
from dataclasses import dataclass

import numpy as np
import torch

from diagnostic_ar_training.cohorts.schema import Sex
from diagnostic_ar_training.gnn.graphs import N_COVARIATES, NEUTRAL_COVARIATES, SEX_ORDER
from diagnostic_ar_training.v4 import samplers
from diagnostic_ar_training.v4.graphs import CompactGraph, GraphBuilder

MAX_REDRAWS = 100


@dataclass(frozen=True)
class Item:
    graph: CompactGraph
    target: int
    covariates: np.ndarray
    real: bool
    group: str | None = None
    """Publication group of a real patient."""


def covariate_vector(sex: str, age_years: float | None, onset_years: float | None) -> np.ndarray:
    """`gnn.graphs.covariates` of a simulated patient."""
    v = np.zeros(N_COVARIATES, dtype=np.float32)
    v[SEX_ORDER.index(Sex(sex))] = 1
    if age_years is not None:
        v[3], v[4] = math.log1p(max(age_years, 0.0)), 1
    if onset_years is not None:
        v[5], v[6] = math.log1p(max(onset_years, 0.0)), 1
    return v


def collate(items: list[Item]) -> dict:
    graphs = [it.graph for it in items]
    sizes = np.array([len(g.nodes) for g in graphs], dtype=np.int64)
    offsets = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    edges = [g.edge_index + o for g, o in zip(graphs, offsets, strict=True)]
    observed = np.zeros(int(sizes.sum()), dtype=bool)
    for g, o in zip(graphs, offsets, strict=True):
        observed[o : o + g.n_observed] = True
    return {
        "nodes": torch.from_numpy(np.concatenate([g.nodes for g in graphs])),
        "edge_index": torch.from_numpy(
            np.concatenate(edges, axis=1) if edges else np.zeros((2, 0), np.int64)
        ),
        "batch": torch.from_numpy(np.repeat(np.arange(len(graphs), dtype=np.int64), sizes)),
        "observed": torch.from_numpy(observed),
        "covariates": torch.from_numpy(
            np.stack([it.covariates for it in items]) if items else np.zeros((0, N_COVARIATES), np.float32)
        ),
        "target": torch.tensor([it.target for it in items], dtype=torch.int64),
        "real": torch.tensor([it.real for it in items], dtype=torch.bool),
    }


class TrainStream(torch.utils.data.IterableDataset):
    def __init__(
        self,
        sampler,
        builder: GraphBuilder,
        gene_pool: np.ndarray,
        batch_size: int,
        seed: int,
        stream: int = 0,
        real: list[Item] | None = None,
        real_ratio: float = 0.0,
        with_covariates: bool = False,
        real_draw: str = "patient",
    ) -> None:
        super().__init__()
        if real_ratio > 0 and not real:
            raise ValueError("real_ratio > 0 needs real patients")
        self.sampler, self.builder, self.pool = sampler, builder, np.asarray(gene_pool, dtype=np.int64)
        self.batch_size, self.seed, self.stream = batch_size, seed, stream
        self.real, self.real_ratio, self.with_covariates = real or [], real_ratio, with_covariates
        self.real_draw = real_draw
        self.real_by_gene: dict[int, list[list[Item]]] = {}
        if real_draw == "gene":
            in_pool = set(self.pool.tolist())
            self.real_by_gene = {g: p for g, p in by_gene(self.real).items() if g in in_pool}
            if real_ratio > 0 and not self.real_by_gene:
                raise ValueError("no real patient has a gene of the simulator's pool")
        elif real_draw != "patient":
            raise ValueError(f"unknown real_draw {real_draw!r}")
        self.redraws = 0

    def _simulated(self, rng: np.random.Generator) -> Item:
        for _ in range(MAX_REDRAWS):
            gene = int(self.pool[rng.integers(self.pool.size)])
            graph = self.builder.build(self.sampler.sample(gene, rng))
            if graph is not None:
                cov = NEUTRAL_COVARIATES
                if self.with_covariates:
                    cov = covariate_vector(*samplers.sample_covariates(self.sampler, gene, rng))
                return Item(graph, gene, cov, False)
            self.redraws += 1
        raise RuntimeError(f"{MAX_REDRAWS} simulated cases in a row had no term in E0's DAG")

    def item(self, rng: np.random.Generator) -> Item:
        if self.real_draw == "gene":
            return self._gene_balanced(rng)
        if self.real_ratio and rng.random() < self.real_ratio:
            return self.real[int(rng.integers(len(self.real)))]
        return self._simulated(rng)

    def _gene_balanced(self, rng: np.random.Generator) -> Item:
        simulated = self._simulated(rng)
        publications = self.real_by_gene.get(simulated.target)
        if not publications or rng.random() >= self.real_ratio:
            return simulated
        publication = publications[int(rng.integers(len(publications)))]
        return publication[int(rng.integers(len(publication)))]

    def __iter__(self):
        info = torch.utils.data.get_worker_info()
        worker = info.id if info is not None else 0
        rng = np.random.default_rng([self.seed, self.stream, worker])
        while True:
            yield collate([self.item(rng) for _ in range(self.batch_size)])


def by_gene(items: list[Item]) -> dict[int, list[list[Item]]]:
    """Real items per target gene, then per publication group (groups in sorted order)."""
    grouped: dict[int, dict[str, list[Item]]] = {}
    for it in items:
        if it.group is None:
            raise ValueError("a gene-balanced draw needs each real item's publication group")
        grouped.setdefault(it.target, {}).setdefault(it.group, []).append(it)
    return {g: [pubs[k] for k in sorted(pubs)] for g, pubs in sorted(grouped.items())}


def loader(stream: TrainStream, num_workers: int, pin_memory: bool) -> torch.utils.data.DataLoader:
    return torch.utils.data.DataLoader(
        stream,
        batch_size=None,
        num_workers=num_workers,
        pin_memory=pin_memory,
        prefetch_factor=4 if num_workers else None,
        persistent_workers=False,
    )


class NodeTables:
    """DAG-indexed feature tables on the device."""

    def __init__(self, tables: dict[str, np.ndarray], device: torch.device) -> None:
        self.embedding = torch.from_numpy(tables["embedding"]).to(device)
        self.ic = torch.from_numpy(tables["ic"]).to(device) if "ic" in tables else None
        self.device = device

    def node_features(self, nodes: torch.Tensor, observed: torch.Tensor, observed_flag: bool, ic: bool):
        columns = []
        if observed_flag:
            columns.append(observed.to(torch.float32))
        if ic:
            if self.ic is None:
                raise ValueError("this model reads the IC; build the tables with it")
            columns.append(self.ic.index_select(0, nodes))
        return torch.stack(columns, dim=1) if columns else None


def to_device(batch: dict, tables: NodeTables, encoding) -> dict:
    device = tables.device
    nodes = batch["nodes"].to(device, non_blocking=True)
    observed = batch["observed"].to(device, non_blocking=True)
    return {
        "x": tables.embedding.index_select(0, nodes),
        "edge_index": batch["edge_index"].to(device, non_blocking=True),
        "batch": batch["batch"].to(device, non_blocking=True),
        "num_graphs": int(batch["target"].numel()),
        "node_features": tables.node_features(nodes, observed, encoding.observed_flag, encoding.ic_feature),
        "covariates": batch["covariates"].to(device, non_blocking=True) if encoding.covariates else None,
        "target": batch["target"].to(device, non_blocking=True),
    }


def model_inputs(inputs: dict) -> dict:
    return {k: v for k, v in inputs.items() if k != "target"}
