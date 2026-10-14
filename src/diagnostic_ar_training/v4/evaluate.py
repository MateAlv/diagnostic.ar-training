"""Ranks of real `p3-v1` train patients (present terms only) under a v4 model, and under E0 as released.

- A model is scored in eval mode, float32, batched on the device. Rank = pessimistic 1-based rank of the true
  gene's logit (ties count against it), as `gnn.train.ranks_from_logits`.
- E0 (R0) is the production ONNX through `GenPheniaV3`, ranked from its softmax as `eval.harness` does.
- Unscorable patients (no present term in E0's DAG) and genes outside E0's vocabulary get rank inf.
"""

import math
from dataclasses import dataclass

import numpy as np
import torch

from diagnostic_ar_training.eval.metrics import rank_of
from diagnostic_ar_training.gnn.graphs import covariates
from diagnostic_ar_training.v4 import data, report
from diagnostic_ar_training.v4.graphs import CompactGraph, GraphBuilder
from diagnostic_ar_training.v4.patients import Patient


@dataclass
class PatientSet:
    patients: list[Patient]
    graphs: list[CompactGraph | None]
    targets: list[int | None]
    covariates: list[np.ndarray]
    swap_from: list[str] | None = None
    """Case id whose phenotype each patient carries, in a phenotype-swapped set."""

    @classmethod
    def build(
        cls,
        patients: list[Patient],
        builder: GraphBuilder,
        genes: tuple[str, ...],
        swap_from: list[str] | None = None,
    ) -> "PatientSet":
        lookup = {g.upper(): i for i, g in enumerate(genes)}
        return cls(
            list(patients),
            [builder.build(p.case.present) for p in patients],
            [lookup.get(p.case.gene.upper()) for p in patients],
            [covariates(p.case) for p in patients],
            swap_from,
        )

    def items(self) -> list[data.Item]:
        """Training items: scorable patients whose gene E0 can output."""
        return [
            data.Item(g, t, c, True, p.group)
            for p, g, t, c in zip(self.patients, self.graphs, self.targets, self.covariates, strict=True)
            if g is not None and t is not None
        ]


@torch.no_grad()
def model_ranks(
    model, pset: PatientSet, tables: data.NodeTables, encoding, batch_size: int = 512
) -> np.ndarray:
    was_training = model.training
    model.eval()
    ranks = np.full(len(pset.patients), math.inf)
    rows = [
        i
        for i, (g, t) in enumerate(zip(pset.graphs, pset.targets, strict=True))
        if g is not None and t is not None
    ]
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        items = [data.Item(pset.graphs[i], pset.targets[i], pset.covariates[i], True) for i in chunk]
        inputs = data.to_device(data.collate(items), tables, encoding)
        logits = model(**data.model_inputs(inputs)).float()
        t = logits.gather(1, inputs["target"].unsqueeze(1))
        r = ((logits > t).sum(1) + (logits == t).sum(1)).cpu().numpy()
        ranks[chunk] = r
    model.train(was_training)
    return ranks


def tag_swap(records: list[dict], swap_from: list[str] | None) -> list[dict]:
    if swap_from is not None:
        for r, source in zip(records, swap_from, strict=True):
            r["swap_from"] = source
    return records


def model_records(model, pset: PatientSet, tables, encoding) -> list[dict]:
    ranks = model_ranks(model, pset, tables, encoding)
    records = [
        report.record(p, t is not None, g is not None, float(r))
        for p, g, t, r in zip(pset.patients, pset.graphs, pset.targets, ranks, strict=True)
    ]
    return tag_swap(records, pset.swap_from)


def e0_records(patients: list[Patient], e0=None) -> list[dict]:
    """E0 as released (production ONNX), present terms only."""
    if e0 is None:
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        e0 = GenPheniaV3()
    lookup = {g.upper(): i for i, g in enumerate(e0.genes)}
    out = []
    for p in patients:
        scored = e0.score(p.case)
        idx = lookup.get(p.case.gene.upper())
        rank = math.inf
        if scored.probs is not None and idx is not None:
            rank = rank_of(e0.genes[idx], e0.genes, scored.probs)
        out.append(report.record(p, idx is not None, scored.probs is not None, rank))
    return out
