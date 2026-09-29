"""v3.0 through our PyTorch re-implementation (gnn.model.GinV3), with E0's graphs and coverage rules.

Same inputs, vocabulary, unscorable rule and softmax as `GenPheniaV3`; only the network runtime differs
(PyTorch instead of ONNX Runtime). EXP-A-000 checks that the two agree.
"""

from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.gnn.graphs import CaseGraph, case_graph, collate
from diagnostic_ar_training.lineage.registry import load_sources
from diagnostic_ar_training.systems import Scored
from diagnostic_ar_training.systems.genphenia_v3 import SOURCE, V3Inputs, softmax64, unpack_bundle


class GinV3Torch:
    def __init__(self, bundle_dir: Path | None = None, device: str = "cpu", threads: int | None = 1) -> None:
        import torch

        from diagnostic_ar_training.gnn.model import load_v3

        if threads is not None and device == "cpu":
            torch.set_num_threads(threads)
        self.torch = torch
        root = bundle_dir or unpack_bundle()
        self.inputs = V3Inputs(root)
        self.genes = self.inputs.genes
        self.device = torch.device(device)
        self.model = load_v3(root, map_location=self.device)
        self.name = "ginv3-torch" if self.device.type == "cpu" else f"ginv3-torch-{self.device.type}"

    def lineage_inputs(self) -> list[dict]:
        return [load_sources()[SOURCE].as_input()]

    def logits(self, graph: CaseGraph) -> np.ndarray:
        t = self.torch
        with t.inference_mode():
            out = self.model(
                t.from_numpy(graph.x).to(self.device), t.from_numpy(graph.edge_index).to(self.device)
            )
        return out.cpu().numpy().reshape(-1)

    def logits_many(self, graphs: list[CaseGraph]) -> np.ndarray:
        """[G, genes] for a batch of graphs in one forward pass."""
        tensors = collate(graphs).to_torch(self.device)
        with self.torch.inference_mode():
            out = self.model(
                tensors["x"], tensors["edge_index"], tensors["batch"], num_graphs=tensors["num_graphs"]
            )
        return out.cpu().numpy()

    def score(self, case: Case) -> Scored:
        graph, info = case_graph(self.inputs, case)
        if graph is None:
            return Scored(None, info)
        return Scored(softmax64(self.logits(graph)), info)


class GinModelSystem:
    """A (fine-tuned) GinV3Extended as a System: E0's graphs and coverage rules, one case per forward.

    Negated terms and covariates reach the model only when it was trained to use them.
    """

    def __init__(self, model, inputs: V3Inputs, name: str, negated: bool = False) -> None:
        import torch

        self.torch = torch
        self.model, self.inputs, self.name, self.negated = model, inputs, name, negated
        self.genes = inputs.genes
        self.device = next(model.parameters()).device

    def lineage_inputs(self) -> list[dict]:
        return [load_sources()[SOURCE].as_input()]

    def score(self, case: Case) -> Scored:
        graph, info = case_graph(self.inputs, case, negated=self.negated)
        if graph is None:
            return Scored(None, info)
        t = self.torch
        covariates = None
        if self.model.cov_mlp is not None:
            covariates = t.from_numpy(graph.covariates).unsqueeze(0).to(self.device)
        with t.inference_mode():
            out = self.model(
                t.from_numpy(graph.x).to(self.device),
                t.from_numpy(graph.edge_index).to(self.device),
                t.from_numpy(graph.node_type).to(self.device),
                covariates,
            )
        return Scored(softmax64(out.cpu().numpy().reshape(-1)), info)
