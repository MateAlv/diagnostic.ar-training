"""The trainable ft-v1 residual (torch), with the same maths as `ft/bundle.py` and an export to its members.

- `theta` [K] starts at 0 and is projected onto θ ≥ 0 (and onto 0 for inactive features) after every step; the
  forward pass reads it as it is, so its gradient at 0 is not cut.
- `mlp` (optional) maps the covariates to a per-feature modulation softplus(m(z)) / ln 2; its last layer
  starts at 0, so the modulation starts at 1 for every patient.
- `delta_weight`, `delta_bias` (optional configuration): a change to v3.0's classifier, starting at 0, applied
  to v3.0's pooled vector. They are the only per-gene parameters, and only that configuration has them.
"""

import math
from collections.abc import Sequence

import torch
import torch.nn.functional as F
from torch import nn

from diagnostic_ar_training.ft.bundle import COVARIATES, FEATURES

LN2 = math.log(2.0)


class ResidualNet(nn.Module):
    def __init__(
        self,
        hidden: int = 0,
        features: Sequence[str] = FEATURES,
        covariates: Sequence[str] = COVARIATES,
        classifier_shape: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        unknown = (set(features) - set(FEATURES)) | (set(covariates) - set(COVARIATES))
        if unknown:
            raise ValueError(f"unknown features or covariates {sorted(unknown)}")
        self.active_features = tuple(f for f in FEATURES if f in set(features))
        self.active_covariates = tuple(c for c in COVARIATES if c in set(covariates))
        self.register_buffer(
            "feature_mask", torch.tensor([f in self.active_features for f in FEATURES]).float()
        )
        self.register_buffer(
            "cov_mask", torch.tensor([c in self.active_covariates for c in COVARIATES]).float()
        )
        self.theta = nn.Parameter(torch.zeros(len(FEATURES)))
        self.mlp = None
        if hidden:
            self.mlp = nn.Sequential(
                nn.Linear(len(COVARIATES), hidden), nn.ReLU(), nn.Linear(hidden, len(FEATURES))
            )
            nn.init.zeros_(self.mlp[2].weight)
            nn.init.zeros_(self.mlp[2].bias)
        self.delta_weight = self.delta_bias = None
        if classifier_shape is not None:
            self.delta_weight = nn.Parameter(torch.zeros(classifier_shape))
            self.delta_bias = nn.Parameter(torch.zeros(classifier_shape[0]))

    def weights(self, z: torch.Tensor) -> torch.Tensor:
        """w [B, K], every entry ≤ 0 once projected."""
        theta = (self.theta * self.feature_mask).unsqueeze(0)
        if self.mlp is None:
            return -theta.expand(z.size(0), -1)
        return -theta * F.softplus(self.mlp(z * self.cov_mask)) / LN2

    def forward(
        self, feats: torch.Tensor, z: torch.Tensor, pooled: torch.Tensor | None = None
    ) -> torch.Tensor:
        """Δ logits [B, genes] from features [B, K, genes] and covariates [B, C]."""
        r = torch.einsum("bk,bkg->bg", self.weights(z), feats)
        if self.delta_weight is not None:
            if pooled is None:
                raise ValueError("the classifier delta needs v3.0's pooled vectors")
            r = r + pooled @ self.delta_weight.T + self.delta_bias
        return r

    @torch.no_grad()
    def project(self) -> None:
        self.theta.clamp_(min=0).mul_(self.feature_mask)

    def member(self, classifier_delta: str | None = None) -> dict:
        """This model as a member of an `ft-v1-bundle/1`."""
        mlp = None
        if self.mlp is not None:
            mlp = {
                "w1": self.mlp[0].weight.detach().cpu().double().tolist(),
                "b1": self.mlp[0].bias.detach().cpu().double().tolist(),
                "w2": self.mlp[2].weight.detach().cpu().double().tolist(),
                "b2": self.mlp[2].bias.detach().cpu().double().tolist(),
            }
        out = {
            "active_features": list(self.active_features),
            "active_covariates": list(self.active_covariates),
            "theta": self.theta.detach().cpu().double().tolist(),
            "mlp": mlp,
        }
        if classifier_delta:
            out["classifier_delta"] = classifier_delta
        return out
