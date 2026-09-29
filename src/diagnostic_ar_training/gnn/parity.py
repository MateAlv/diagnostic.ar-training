"""Logit parity of the torch re-implementation against production ONNX (EXP-A-000)."""

import copy
import math
import random
import time

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval.metrics import rank_of
from diagnostic_ar_training.gnn.graphs import case_graph
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3, softmax64
from diagnostic_ar_training.systems.ginv3_torch import GinV3Torch


def sample_scorable(cases: list[Case], e0: GenPheniaV3, n: int, seed: int) -> list[Case]:
    """`n` cases with at least one known present term, drawn by a seeded RNG from the case-id order."""
    scorable = sorted((c for c in cases if e0.inputs.known_present(c)[0]), key=lambda c: c.case_id)
    return random.Random(seed).sample(scorable, min(n, len(scorable)))


def _pct(values: list[float]) -> dict:
    a = np.asarray(values)
    return {"p50": float(np.percentile(a, 50)), "p95": float(np.percentile(a, 95)), "mean": float(a.mean())}


def _sync(system: GinV3Torch) -> None:
    if system.device.type == "cuda":
        system.torch.cuda.synchronize()


def run(
    e0: GenPheniaV3,
    system: GinV3Torch,
    cases: list[Case],
    batch_size: int = 128,
    float64: bool = True,
    reexport=None,
) -> tuple[dict, list[dict]]:
    """Per case: ONNX vs torch logits (single and batched), top-10 order, true-gene rank, timings.

    `float64` also scores each case with a float64 copy of the weights, to show how far each float32
    runtime is from exact arithmetic. `reexport` is an onnxruntime session of `export.export_v3(model)`.
    """
    torch = system.torch
    exact = copy.deepcopy(system.model).cpu().double() if float64 else None
    lookup = {g.upper(): i for i, g in enumerate(e0.genes)}
    graphs = [case_graph(system.inputs, c)[0] for c in cases]
    for g in graphs[:10]:
        system.logits(g)
    rows, onnx_ms, torch_ms = [], [], []
    for case, graph in zip(cases, graphs, strict=True):
        node_ids, x, edge_index = e0.graph(e0.inputs.known_present(case)[0])
        if node_ids != graph.node_ids or not np.array_equal(edge_index, graph.edge_index):
            raise AssertionError(f"{case.case_id}: graphs differ")
        feeds = {"x": x, "edge_index": edge_index}
        start = time.perf_counter()
        a = e0.session.run(None, feeds)[0].reshape(-1)
        onnx_ms.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        b = system.logits(graph)
        _sync(system)
        torch_ms.append((time.perf_counter() - start) * 1000)
        d = np.abs(a.astype(np.float64) - b)
        idx = lookup.get(case.gene.upper())
        pa, pb = softmax64(a), softmax64(b)
        row = {
            "case_id": case.case_id,
            "n_nodes": len(node_ids),
            "max_abs_dlogit": float(d.max()),
            "max_rel_dlogit": float((d / np.maximum(np.abs(a), 1.0)).max()),
            "max_abs_dprob": float(np.abs(pa - pb).max()),
            "top10_same_order": bool(
                np.array_equal(np.argsort(-a, kind="stable")[:10], np.argsort(-b, kind="stable")[:10])
            ),
            "top10_same_set": set(np.argsort(-a)[:10]) == set(np.argsort(-b)[:10]),
            "rank_onnx": math.inf if idx is None else rank_of(e0.genes[idx], e0.genes, pa),
            "rank_torch": math.inf if idx is None else rank_of(e0.genes[idx], e0.genes, pb),
        }
        if exact is not None:
            with torch.inference_mode():
                t = exact(torch.from_numpy(x).double(), torch.from_numpy(edge_index)).numpy().reshape(-1)
            row["onnx_vs_float64"] = float(np.abs(a - t).max())
            row["torch_vs_float64"] = float(np.abs(b - t).max())
        if reexport is not None:
            row["reexport_vs_onnx"] = float(np.abs(reexport.run(None, feeds)[0].reshape(-1) - a).max())
        rows.append(row)

    batched_ms, batched_diff = [], 0.0
    for i in range(0, len(graphs), batch_size):
        chunk = graphs[i : i + batch_size]
        start = time.perf_counter()
        out = system.logits_many(chunk)
        _sync(system)
        batched_ms.append((time.perf_counter() - start) * 1000)
        for j, g in enumerate(chunk):
            batched_diff = max(batched_diff, float(np.abs(out[j] - system.logits(g)).max()))

    n = len(rows)
    summary = {
        "n": n,
        "device": str(system.device),
        "max_abs_dlogit": max(r["max_abs_dlogit"] for r in rows),
        "max_rel_dlogit": max(r["max_rel_dlogit"] for r in rows),
        "max_abs_dprob": max(r["max_abs_dprob"] for r in rows),
        "cases_over_1e-4": sum(r["max_abs_dlogit"] > 1e-4 for r in rows),
        "cases_over_1e-5": sum(r["max_abs_dlogit"] > 1e-5 for r in rows),
        "top10_same_order": sum(r["top10_same_order"] for r in rows),
        "top10_same_set": sum(r["top10_same_set"] for r in rows),
        "rank_identical": sum(r["rank_onnx"] == r["rank_torch"] for r in rows),
        "batched_vs_single_max_abs_dlogit": batched_diff,
        "network_ms_per_case": {"onnx_cpu_1thread": _pct(onnx_ms), "torch": _pct(torch_ms)},
        "batch": {
            "size": batch_size,
            "cases_per_s": n / (sum(batched_ms) / 1000),
            "ms_per_batch": _pct(batched_ms),
        },
    }
    if reexport is not None:
        summary["reexport_vs_onnx_max_abs_dlogit"] = max(r["reexport_vs_onnx"] for r in rows)
    if exact is not None:
        summary["cases_torch_closer_to_float64_than_onnx"] = sum(
            r["torch_vs_float64"] <= r["onnx_vs_float64"] for r in rows
        )
        summary["max_onnx_vs_float64"] = max(r["onnx_vs_float64"] for r in rows)
        summary["max_torch_vs_float64"] = max(r["torch_vs_float64"] for r in rows)
    return summary, rows
