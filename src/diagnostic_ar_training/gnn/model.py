"""GenPhenia v3.0 in plain PyTorch (no torch_geometric), and its zero-initialised extension.

Provenance:
- Architecture: GenPhenAI GraPhens@7d861ff training/models/models.py:241-323 (`GenePhenAIv3_0`, PyG
  GINConv + BatchNorm + AttentionalAggregation). Read-only upstream; nothing imported from it.
- PyG-free layers: diagnostic.ar-model@654736f vendor/genphenia_inference_engine/adapter_models.py:56-95
  and 195-250 (`GINLayer`, `AttentionPool`, `GenePhenAIv3_0Adapter`). Copied and restructured; the maths
  is unchanged.
- Aggregation under ONNX export: GenPhenAI genphenia_inference/src/inference_engine/adapter_models.py:10-17
  and 70-77 (`_edge_one_hot`; not under git, file sha256 d321baee...). Production's `model.onnx` has
  this structure (OneHot -> MatMul).

Checkpoint keys: submodules carry PyG's names (`convK.nn.*`, `convK.eps`, `bnK.module.*`,
`attention_pool.gate_nn.*`, `classifier.*`), so `best_model.pt` loads with `strict=True` and no renaming.
The production adapter renames `.nn.` to `.mlp.` and drops `.module.` instead; the tensors are the same.
"""

import copy
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn

from diagnostic_ar_training.gnn.graphs import N_COVARIATES, N_NODE_TYPES, NODE_NEGATED
from diagnostic_ar_training.systems.genphenia_v3 import CHECKPOINT


def _mlp(*sizes: int) -> nn.Sequential:
    layers: list[nn.Module] = []
    for i in range(len(sizes) - 1):
        if i:
            layers.append(nn.ReLU())
        layers.append(nn.Linear(sizes[i], sizes[i + 1]))
    return nn.Sequential(*layers)


class GinConv(nn.Module):
    """PyG `GINConv(train_eps=True)`: MLP((1 + eps) x_i + sum over edges j -> i of x_j)."""

    def __init__(self, mlp: nn.Sequential) -> None:
        super().__init__()
        self.nn = mlp
        self.eps = nn.Parameter(torch.zeros(1))

    def combine(
        self, x: torch.Tensor, edge_index: torch.Tensor, message_scale: torch.Tensor | None = None
    ) -> torch.Tensor:
        messages = x.index_select(0, edge_index[0])
        if message_scale is not None:
            messages = messages * message_scale
        if torch.onnx.is_in_onnx_export():
            # The TorchScript exporter turns index_add into a ScatterElements without reduction (last write
            # wins). The production export sums through a dense [N, E] incidence matmul instead.
            incidence = F.one_hot(edge_index[1], num_classes=x.size(0)).to(x.dtype).transpose(0, 1)
            aggregated = incidence @ messages
        else:
            aggregated = torch.zeros_like(x).index_add(0, edge_index[1], messages)
        return (1 + self.eps) * x + aggregated

    def forward(
        self, x: torch.Tensor, edge_index: torch.Tensor, message_scale: torch.Tensor | None = None
    ) -> torch.Tensor:
        return self.nn(self.combine(x, edge_index, message_scale))


class BatchNorm(nn.Module):
    """PyG's `BatchNorm` wrapper, kept so the checkpoint's `bnK.module.*` keys load unchanged."""

    def __init__(self, channels: int) -> None:
        super().__init__()
        self.module = nn.BatchNorm1d(channels)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.module(x)


class AttentionalAggregation(nn.Module):
    """Softmax-gated sum of node vectors per graph."""

    def __init__(self, gate_nn: nn.Sequential) -> None:
        super().__init__()
        self.gate_nn = gate_nn

    def forward(
        self, x: torch.Tensor, batch: torch.Tensor | None = None, num_graphs: int = 1
    ) -> torch.Tensor:
        score = self.gate_nn(x).squeeze(-1)
        if batch is None:
            # The exported production graph: one softmax over all nodes.
            weights = torch.softmax(score, dim=0).unsqueeze(-1)
            return (weights * x).sum(dim=0, keepdim=True)
        peak = score.new_full((num_graphs,), float("-inf")).scatter_reduce(0, batch, score, "amax")
        exp = (score - peak[batch]).exp()
        total = exp.new_zeros(num_graphs).index_add(0, batch, exp)
        weights = (exp / total[batch]).unsqueeze(-1)
        return x.new_zeros(num_graphs, x.size(1)).index_add(0, batch, weights * x)


def _num_graphs(batch: torch.Tensor | None, num_graphs: int | None) -> int:
    if batch is None:
        return 1
    return num_graphs if num_graphs is not None else int(batch.max()) + 1


class GinV3(nn.Module):
    """3 x (GIN -> BatchNorm -> ReLU -> Dropout), attentional pooling, linear classifier over genes.

    `batch=None` is one graph (the production ONNX signature); otherwise `batch[i]` is node i's graph.
    """

    def __init__(
        self,
        in_channels: int = 768,
        hidden_channels: int = 512,
        out_channels: int = 5229,
        dropout: float = 0.3,
    ) -> None:
        super().__init__()
        self.in_channels, self.hidden_channels, self.out_channels = in_channels, hidden_channels, out_channels
        self.conv1 = GinConv(_mlp(in_channels, hidden_channels, hidden_channels))
        self.bn1 = BatchNorm(hidden_channels)
        self.conv2 = GinConv(_mlp(hidden_channels, hidden_channels, hidden_channels))
        self.bn2 = BatchNorm(hidden_channels)
        self.conv3 = GinConv(_mlp(hidden_channels, hidden_channels, hidden_channels))
        self.bn3 = BatchNorm(hidden_channels)
        self.dropout = nn.Dropout(p=dropout)
        self.attention_pool = AttentionalAggregation(_mlp(hidden_channels, hidden_channels // 2, 1))
        self.classifier = nn.Linear(hidden_channels, out_channels)

    def _post(self, h: torch.Tensor, bn: BatchNorm) -> torch.Tensor:
        return self.dropout(F.relu(bn(h)))

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch: torch.Tensor | None = None,
        num_graphs: int | None = None,
    ) -> torch.Tensor:
        h = self._post(self.conv1(x, edge_index), self.bn1)
        h = self._post(self.conv2(h, edge_index), self.bn2)
        h = self._post(self.conv3(h, edge_index), self.bn3)
        pooled = self.attention_pool(h, batch, _num_graphs(batch, num_graphs))
        return self.classifier(self.dropout(pooled))


def load_v3(bundle_dir: Path, map_location: str | torch.device = "cpu") -> GinV3:
    """Production `best_model.pt` (key `model_state_dict` per spec.json), loaded strictly, in eval mode."""
    ckpt_dir = bundle_dir / "checkpoints" / CHECKPOINT
    spec = json.loads((ckpt_dir / "spec.json").read_text())
    if spec["model_version"] != "3.0":
        raise ValueError(f"expected a v3.0 bundle, got model_version {spec['model_version']!r}")
    genes = json.loads((ckpt_dir / spec["genes_path"]).read_text())
    checkpoint = torch.load(ckpt_dir / spec["checkpoint_path"], map_location=map_location, weights_only=True)
    model = GinV3(spec["in_channels"], spec["hidden_channels"], len(genes))
    model.load_state_dict(checkpoint[spec["checkpoint_key"]], strict=True)
    return model.to(map_location).eval()


class GinV3Extended(GinV3):
    """v3.0 plus node types, negated terms and patient covariates; equal to v3.0 until trained.

    Design and why each new parameter starts at zero: docs/decisions/0009-step-zero-identity.md.
    - `node_type` [N] (graphs.NODE_*): its one-hot goes through the first GIN layer like x, then
      `type_proj`, added to `conv1.nn[0]`'s output. Same as widening that Linear by 3 zero columns, but
      adding an exact 0.0 keeps step 0 bit-identical.
    - Negated nodes send messages scaled per channel by `neg_gates[k]` (start at 0). They are never pooled
      by the v3.0 readout. With `neg_readout` (A-neg2) they get their own pool, read by
      `neg_classifier` (starts at 0, no bias, so a case without negated terms adds exactly 0).
    - `covariates` [G, 7] (graphs.covariates) -> `cov_mlp` -> `cov_classifier` (starts at 0). Same as
      concatenating the covariate features to the pooled vector with zero classifier columns.

    Identity holds in eval mode. In train mode BatchNorm batch statistics also see negated nodes.
    """

    def __init__(
        self,
        in_channels: int = 768,
        hidden_channels: int = 512,
        out_channels: int = 5229,
        dropout: float = 0.3,
        covariates: bool = True,
        neg_readout: bool = False,
        cov_hidden: int = 32,
    ) -> None:
        super().__init__(in_channels, hidden_channels, out_channels, dropout)
        self.type_proj = nn.Linear(N_NODE_TYPES, hidden_channels, bias=False)
        nn.init.zeros_(self.type_proj.weight)
        widths = (in_channels + N_NODE_TYPES, hidden_channels, hidden_channels)
        self.neg_gates = nn.ParameterList([nn.Parameter(torch.zeros(w)) for w in widths])
        self.cov_mlp = self.cov_classifier = None
        if covariates:
            self.cov_mlp = nn.Sequential(_mlp(N_COVARIATES, cov_hidden, cov_hidden), nn.ReLU())
            self.cov_classifier = nn.Linear(cov_hidden, out_channels, bias=False)
            nn.init.zeros_(self.cov_classifier.weight)
        self.neg_pool = self.neg_classifier = None
        if neg_readout:
            self.neg_pool = copy.deepcopy(self.attention_pool)
            self.neg_classifier = nn.Linear(hidden_channels, out_channels, bias=False)
            nn.init.zeros_(self.neg_classifier.weight)

    @classmethod
    def from_v3(cls, base: GinV3, **options) -> "GinV3Extended":
        """Warm start: every v3.0 tensor copied, every new one at its step-0 value."""
        model = cls(base.in_channels, base.hidden_channels, base.out_channels, base.dropout.p, **options)
        result = model.load_state_dict(base.state_dict(), strict=False)
        new = {k for k in model.state_dict() if k.startswith(("type_proj.", "neg_gates.", "cov_", "neg_"))}
        if result.unexpected_keys or set(result.missing_keys) != new:
            raise RuntimeError(f"warm start mismatch: {result}")
        if model.neg_pool is not None:
            model.neg_pool.load_state_dict(base.attention_pool.state_dict())
        return model.to(next(base.parameters()).device).train(base.training)

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        node_type: torch.Tensor,
        covariates: torch.Tensor | None = None,
        batch: torch.Tensor | None = None,
        num_graphs: int | None = None,
    ) -> torch.Tensor:
        n_graphs = _num_graphs(batch, num_graphs)
        negated = node_type == NODE_NEGATED
        from_negated = negated.index_select(0, edge_index[0]).unsqueeze(-1)
        scales = [torch.where(from_negated, gate, torch.ones_like(gate)) for gate in self.neg_gates]

        types = F.one_hot(node_type, N_NODE_TYPES).to(x.dtype)
        dim = x.size(1)
        pre = self.conv1.combine(x, edge_index, scales[0][:, :dim])
        pre_types = self.conv1.combine(types, edge_index, scales[0][:, dim:])
        mlp = self.conv1.nn
        h = mlp[2](mlp[1](mlp[0](pre) + self.type_proj(pre_types)))
        h = self._post(h, self.bn1)
        h = self._post(self.conv2(h, edge_index, scales[1]), self.bn2)
        h = self._post(self.conv3(h, edge_index, scales[2]), self.bn3)

        keep = ~negated
        pos_batch = None if batch is None else batch[keep]
        logits = self.classifier(self.dropout(self.attention_pool(h[keep], pos_batch, n_graphs)))
        if self.neg_pool is not None:
            neg_batch = None if batch is None else batch[negated]
            pooled_neg = self.neg_pool(h[negated], neg_batch, n_graphs)
            logits = logits + self.neg_classifier(self.dropout(pooled_neg))
        if self.cov_mlp is not None:
            if covariates is None:
                raise ValueError("this model was built with covariates; pass graphs.NEUTRAL_COVARIATES")
            logits = logits + self.cov_classifier(self.cov_mlp(covariates))
        return logits
