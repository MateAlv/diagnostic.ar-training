"""GinV4: GinV3 (E0) with the Phase 3 encoding and architecture options, in one model class.

With the defaults (`edges="up"`, no node features, attention pooling, no covariates, no `"-"` masking) and a
warm start, `GinV4.from_e0(load_v3(...))` computes exactly what GinV3 computes: same modules, same key
names (`convK.nn.*`, `bnK.module.*`, `attention_pool.gate_nn.*`, `classifier.*`), same operations.

Every option adds parameters that start at an exact zero, so a warm start is E0 at step 0 whatever the
options (eval mode); `drop_dash` is the exception by design (E0 without its `"-"` class):
- node features (`observed_flag`, `ic`): a [N, k] matrix goes through layer 1's GIN combination like x, then
  `extra_proj` (k -> hidden, no bias), added to `conv1.nn[0]`'s output. Same as widening that Linear by k
  zero columns.
- `edges="both"`: each layer also sums messages parent -> child and maps them with its own `down_proj[l]`
  (no bias), added to `convL.nn[0]`'s output: a typed GIN where down messages have their own first weights.
- `pooling="attention_mean"`: a mean pool read by `mean_classifier` (no bias).
- `covariates` [G, 7] (`gnn.graphs.covariates`) -> `cov_mlp` -> `cov_classifier` (no bias).
- `drop_dash`: the logit of class 0 (`"-"`) is -inf, so it is never a target nor ranked.
"""

import torch
import torch.nn.functional as F
from torch import nn

from diagnostic_ar_training.gnn.graphs import N_COVARIATES
from diagnostic_ar_training.gnn.model import (
    AttentionalAggregation,
    BatchNorm,
    GinConv,
    GinV3,
    _mlp,
    _num_graphs,
)
from diagnostic_ar_training.v4.config import ArchConfig, EncodingConfig

NEW_PARAMETER_PREFIXES = ("extra_proj.", "down_proj.", "mean_classifier.", "cov_mlp.", "cov_classifier.")
DASH = 0


def is_new_parameter(name: str) -> bool:
    return name.startswith(NEW_PARAMETER_PREFIXES)


def n_node_features(encoding: EncodingConfig) -> int:
    return int(encoding.observed_flag) + int(encoding.ic_feature)


class GinV4(nn.Module):
    def __init__(
        self,
        in_channels: int = 768,
        out_channels: int = 5229,
        arch: ArchConfig = ArchConfig(),
        encoding: EncodingConfig = EncodingConfig(),
        cov_hidden: int = 32,
    ) -> None:
        super().__init__()
        self.in_channels, self.out_channels = in_channels, out_channels
        self.arch, self.encoding = arch, encoding
        hidden = arch.hidden
        self.hidden_channels = hidden
        widths = [in_channels] + [hidden] * (arch.layers - 1)
        for k, width in enumerate(widths, start=1):
            setattr(self, f"conv{k}", GinConv(_mlp(width, hidden, hidden)))
            setattr(self, f"bn{k}", BatchNorm(hidden))
        self.dropout = nn.Dropout(p=arch.dropout)
        self.attention_pool = AttentionalAggregation(_mlp(hidden, hidden // 2, 1))
        self.classifier = nn.Linear(hidden, out_channels)

        k_extra = n_node_features(encoding)
        self.extra_proj = nn.Linear(k_extra, hidden, bias=False) if k_extra else None
        self.down_proj = None
        if encoding.edges == "both":
            self.down_proj = nn.ModuleList(nn.Linear(w, hidden, bias=False) for w in widths)
        self.mean_classifier = None
        if arch.pooling == "attention_mean":
            self.mean_classifier = nn.Linear(hidden, out_channels, bias=False)
        self.cov_mlp = self.cov_classifier = None
        if encoding.covariates:
            self.cov_mlp = nn.Sequential(_mlp(N_COVARIATES, cov_hidden, cov_hidden), nn.ReLU())
            self.cov_classifier = nn.Linear(cov_hidden, out_channels, bias=False)
        self.zero_new_outputs()

    def zero_new_outputs(self) -> None:
        """The tensors that make every option start at an exact zero contribution."""
        for module in (self.extra_proj, self.mean_classifier, self.cov_classifier):
            if module is not None:
                nn.init.zeros_(module.weight)
        if self.down_proj is not None:
            for module in self.down_proj:
                nn.init.zeros_(module.weight)

    @classmethod
    def from_e0(
        cls, base: GinV3, encoding: EncodingConfig = EncodingConfig(), arch: ArchConfig | None = None
    ):
        """Warm start: every E0 tensor copied, every new one at its step-0 value."""
        arch = arch or ArchConfig(init="e0")
        if (arch.hidden, arch.layers) != (base.hidden_channels, 3):
            raise ValueError("a warm start keeps E0's hidden size and 3 layers")
        model = cls(base.in_channels, base.out_channels, arch, encoding)
        result = model.load_state_dict(base.state_dict(), strict=False)
        new = {k for k in model.state_dict() if is_new_parameter(k)}
        if result.unexpected_keys or set(result.missing_keys) != new:
            raise RuntimeError(f"warm start mismatch: {result}")
        return model.to(next(base.parameters()).device).train(base.training)

    def convs(self) -> list[tuple[GinConv, BatchNorm]]:
        return [(getattr(self, f"conv{k}"), getattr(self, f"bn{k}")) for k in range(1, self.arch.layers + 1)]

    @staticmethod
    def _down(h: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        return torch.zeros_like(h).index_add(0, edge_index[0], h.index_select(0, edge_index[1]))

    def forward(
        self,
        x: torch.Tensor,
        edge_index: torch.Tensor,
        batch: torch.Tensor | None = None,
        num_graphs: int | None = None,
        node_features: torch.Tensor | None = None,
        covariates: torch.Tensor | None = None,
    ) -> torch.Tensor:
        n_graphs = _num_graphs(batch, num_graphs)
        h = x
        for layer, (conv, bn) in enumerate(self.convs()):
            pre = conv.combine(h, edge_index)
            extra = layer == 0 and self.extra_proj is not None
            if not extra and self.down_proj is None:
                z = conv.nn(pre)
            else:
                z = conv.nn[0](pre)
                if extra:
                    if node_features is None:
                        raise ValueError("this model reads node features (observed flag / IC)")
                    z = z + self.extra_proj(conv.combine(node_features.to(z.dtype), edge_index))
                if self.down_proj is not None:
                    z = z + self.down_proj[layer](self._down(h, edge_index))
                z = conv.nn[2](conv.nn[1](z))
            h = self.dropout(F.relu(bn(z)))
        pooled = self.attention_pool(h, batch, n_graphs)
        logits = self.classifier(self.dropout(pooled))
        if self.mean_classifier is not None:
            logits = logits + self.mean_classifier(self.dropout(self._mean(h, batch, n_graphs)))
        if self.cov_mlp is not None:
            if covariates is None:
                raise ValueError("this model reads covariates; pass gnn.graphs.NEUTRAL_COVARIATES rows")
            logits = logits + self.cov_classifier(self.cov_mlp(covariates.to(logits.dtype)))
        logits = logits.float()
        if self.encoding.drop_dash:
            logits = logits.index_fill(1, torch.tensor([DASH], device=logits.device), float("-inf"))
        return logits

    @staticmethod
    def _mean(h: torch.Tensor, batch: torch.Tensor | None, n_graphs: int) -> torch.Tensor:
        if batch is None:
            return h.mean(dim=0, keepdim=True)
        total = h.new_zeros(n_graphs, h.size(1)).index_add(0, batch, h)
        count = torch.bincount(batch, minlength=n_graphs).clamp(min=1).to(h.dtype)
        return total / count.unsqueeze(1)


def load_run_weights(model: GinV4, state_dict: dict) -> GinV4:
    """Warm start from one of our runs: every tensor copied; options the run did not have start at zero."""
    result = model.load_state_dict(state_dict, strict=False)
    if result.unexpected_keys or not all(is_new_parameter(k) for k in result.missing_keys):
        raise RuntimeError(f"warm start mismatch: {result}")
    return model


def build(
    arch: ArchConfig,
    encoding: EncodingConfig,
    e0: GinV3 | None,
    n_genes: int,
    in_channels: int,
    run_weights: dict | None = None,
):
    """The run's model: a warm start from `e0` (init 'e0') or from `run_weights` (init 'run:…', the source
    run's model state), or default initialisation (init 'scratch')."""
    if arch.init == "e0":
        if e0 is None:
            raise ValueError("init 'e0' needs E0's weights")
        return GinV4.from_e0(e0, encoding, arch)
    model = GinV4(in_channels, n_genes, arch, encoding)
    if arch.init_run is not None:
        if run_weights is None:
            raise ValueError(f"init {arch.init!r} needs that run's weights")
        load_run_weights(model, run_weights)
    return model
