"""ONNX export with the production runtime's conventions: one graph per call, opset 17, TorchScript exporter.

`export_v3` keeps v3.0's signature (x [N, 768] float32, edge_index [2, E] int64 -> logits [1, genes]), so the
file is a drop-in for the production `model.onnx`. `export_extended` adds `node_type` [N] int64 and, when the
model has them, `covariates` [1, 7] float32. A caller without those inputs feeds observed/ancestor types and
`graphs.NEUTRAL_COVARIATES`; an untrained extended model then returns v3.0's logits.
"""

import copy
import warnings
from pathlib import Path

import torch
from torch import nn

from diagnostic_ar_training.gnn.graphs import N_COVARIATES, NODE_ANCESTOR, NODE_NEGATED, NODE_OBSERVED
from diagnostic_ar_training.gnn.model import GinV3, GinV3Extended

OPSET = 17


class _Single(nn.Module):
    def __init__(self, model: nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(self, *inputs: torch.Tensor) -> torch.Tensor:
        return self.model(*inputs)


def _example(model: GinV3, n_nodes: int = 4) -> tuple[torch.Tensor, torch.Tensor]:
    edges = [[i, n_nodes - 1] for i in range(n_nodes - 1)]
    return torch.randn(n_nodes, model.in_channels), torch.tensor(edges, dtype=torch.int64).T


def _export(model: nn.Module, args: tuple, names: list[str], dynamic: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The legacy exporter is deliberate: its output matches production's model.onnx bit for bit
    # (tests/test_gnn_model.py) and needs no onnxscript.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        torch.onnx.export(
            _Single(copy.deepcopy(model).cpu().eval()),
            args,
            str(path),
            input_names=names,
            output_names=["logits"],
            dynamic_axes=dynamic,
            opset_version=OPSET,
            dynamo=False,
        )
    return path


def export_v3(model: GinV3, path: Path) -> Path:
    dynamic = {"x": {0: "num_nodes"}, "edge_index": {1: "num_edges"}}
    return _export(model, _example(model), ["x", "edge_index"], dynamic, path)


def export_extended(model: GinV3Extended, path: Path) -> Path:
    x, edge_index = _example(model, 5)
    node_type = torch.tensor([NODE_OBSERVED, NODE_OBSERVED, NODE_ANCESTOR, NODE_NEGATED, NODE_ANCESTOR])
    args = (x, edge_index, node_type)
    names = ["x", "edge_index", "node_type"]
    dynamic = {"x": {0: "num_nodes"}, "edge_index": {1: "num_edges"}, "node_type": {0: "num_nodes"}}
    if model.cov_mlp is not None:
        args += (torch.zeros(1, N_COVARIATES),)
        names.append("covariates")
    return _export(model, args, names, dynamic, path)
