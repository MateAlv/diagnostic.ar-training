"""Fit the ft-v1 residual on R1-train patients; early stopping on held-out train publication groups.

- Inputs are precomputed once per process (`Part`): E0's logits (the production ONNX), the features c_k and
  the covariates, and, for the classifier configuration, v3.0's pooled vectors. E0 is frozen, so nothing else
  changes.
- Loss: cross-entropy over all genes of logits_E0 + r. The classifier configuration adds L2-SP on the
  classifier delta (an anchor to v3.0's weights) and, with `replay_weight`, the cross-entropy of
  annotation-sampled pseudo-patients (`ft/replay.py`), which keeps every gene's coverage.
- Adam; θ at `lr`, the MLP at `lr_mlp` with weight decay, the classifier delta at `lr_classifier`. θ is
  projected onto θ ≥ 0 after each step.
- Epoch 0 is the untrained model, which is E0 exactly. After each epoch the held-out groups' MRR decides the
  best state; training stops after `patience` epochs without an improvement above `min_delta`.
"""

import copy
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import torch
import torch.nn.functional as F

from diagnostic_ar_training.ft.bundle import COVARIATES, FEATURES
from diagnostic_ar_training.ft.model import ResidualNet


@dataclass(frozen=True)
class FitConfig:
    hidden: int = 0
    features: tuple[str, ...] = FEATURES
    covariates: tuple[str, ...] = COVARIATES
    lr: float = 0.05
    lr_mlp: float = 0.01
    weight_decay_mlp: float = 1e-4
    batch_size: int = 128
    max_epochs: int = 200
    patience: int = 20
    min_delta: float = 1e-5
    seed: int = 0
    classifier: bool = False
    lr_classifier: float = 1e-4
    l2sp: float = 0.0
    replay_weight: float = 0.0
    replay_batch: int = 512

    def __post_init__(self) -> None:
        if self.classifier and self.lr_classifier > 5e-4:
            raise ValueError("v3.0's classifier weights train at ≤ 5e-4 (EVAL_PROTOCOL §9.6)")
        if (self.l2sp or self.replay_weight) and not self.classifier:
            raise ValueError("l2sp and replay apply to the classifier configuration only")

    def as_dict(self) -> dict:
        d = asdict(self)
        d["features"], d["covariates"] = list(self.features), list(self.covariates)
        return d


@dataclass
class Part:
    """One part's precomputed inputs, on a device. Rows are cases whose gene E0 can rank."""

    case_ids: list[str]
    logits: torch.Tensor
    feats: torch.Tensor
    z: torch.Tensor
    target: torch.Tensor
    pooled: torch.Tensor | None = None

    def __len__(self) -> int:
        return len(self.case_ids)

    def rows(self, keep: set[str]) -> "Part":
        idx = [i for i, c in enumerate(self.case_ids) if c in keep]
        t = torch.tensor(idx, dtype=torch.int64, device=self.logits.device)
        return Part(
            [self.case_ids[i] for i in idx],
            self.logits.index_select(0, t),
            self.feats.index_select(0, t),
            self.z.index_select(0, t),
            self.target.index_select(0, t),
            None if self.pooled is None else self.pooled.index_select(0, t),
        )


@dataclass
class Replay:
    """Pseudo-patients: v3.0's pooled vectors and target genes; logits come from v3.0's classifier."""

    pooled: torch.Tensor
    target: torch.Tensor
    weight: torch.Tensor
    bias: torch.Tensor


@dataclass
class FitResult:
    model: ResidualNet
    history: list[dict] = field(default_factory=list)
    best_epoch: int = 0
    epochs_run: int = 0
    stopped_early: bool = False
    seconds: float = 0.0


def ranks(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Pessimistic ranks, as `metrics.rank_of`: ties with the true gene count against it."""
    true = logits.gather(1, target.unsqueeze(1))
    return (logits >= true).sum(dim=1).double()


@torch.no_grad()
def evaluate(model: ResidualNet, part: Part, chunk: int = 256) -> dict:
    model.eval()
    loss, rr = 0.0, []
    for start in range(0, len(part), chunk):
        sl = slice(start, start + chunk)
        pooled = None if part.pooled is None else part.pooled[sl]
        out = part.logits[sl] + model(part.feats[sl], part.z[sl], pooled)
        loss += float(F.cross_entropy(out, part.target[sl], reduction="sum"))
        rr.append(1.0 / ranks(out, part.target[sl]))
    rr = torch.cat(rr) if rr else torch.zeros(0)
    n = max(len(part), 1)
    return {"n": len(part), "loss": loss / n, "mrr": float(rr.sum()) / n}


def _replay_loss(model: ResidualNet, replay: Replay, idx: torch.Tensor) -> torch.Tensor:
    pooled = replay.pooled.index_select(0, idx)
    logits = pooled @ (replay.weight + model.delta_weight).T + replay.bias + model.delta_bias
    return F.cross_entropy(logits, replay.target.index_select(0, idx))


def fit(cfg: FitConfig, train: Part, val: Part, replay: Replay | None = None, log=print) -> FitResult:
    device = train.logits.device
    torch.manual_seed(cfg.seed)
    shape = None
    if cfg.classifier:
        if train.pooled is None or replay is None and cfg.replay_weight:
            raise ValueError(
                "the classifier configuration needs pooled vectors (and replay data when weighted)"
            )
        shape = (train.logits.size(1), train.pooled.size(1))
    model = ResidualNet(cfg.hidden, cfg.features, cfg.covariates, shape).to(device)
    groups = [{"params": [model.theta], "lr": cfg.lr, "weight_decay": 0.0}]
    if model.mlp is not None:
        groups.append(
            {"params": list(model.mlp.parameters()), "lr": cfg.lr_mlp, "weight_decay": cfg.weight_decay_mlp}
        )
    if model.delta_weight is not None:
        groups.append(
            {"params": [model.delta_weight, model.delta_bias], "lr": cfg.lr_classifier, "weight_decay": 0.0}
        )
    # Adam's weight_decay is an L2 term in the gradient; AdamW would decay toward 0 differently per group.
    optimizer = torch.optim.Adam(groups)
    order = torch.Generator(device="cpu").manual_seed(cfg.seed)
    replay_gen = torch.Generator(device="cpu").manual_seed(cfg.seed + 1)
    start = time.perf_counter()
    result = FitResult(model)
    epoch0 = {"epoch": 0, "val": evaluate(model, val)}
    result.history.append(epoch0)
    best_mrr, best_state, since = epoch0["val"]["mrr"], copy.deepcopy(model.state_dict()), 0
    for epoch in range(1, cfg.max_epochs + 1):
        model.train()
        perm = torch.randperm(len(train), generator=order).to(device)
        total, steps = 0.0, 0
        for b in range(0, len(train), cfg.batch_size):
            idx = perm[b : b + cfg.batch_size]
            pooled = None if train.pooled is None else train.pooled.index_select(0, idx)
            out = train.logits.index_select(0, idx) + model(
                train.feats.index_select(0, idx), train.z.index_select(0, idx), pooled
            )
            loss = F.cross_entropy(out, train.target.index_select(0, idx))
            if cfg.classifier:
                if cfg.l2sp:
                    loss = loss + cfg.l2sp * (model.delta_weight.pow(2).sum() + model.delta_bias.pow(2).sum())
                if cfg.replay_weight:
                    ridx = torch.randint(len(replay.target), (cfg.replay_batch,), generator=replay_gen).to(
                        device
                    )
                    loss = loss + cfg.replay_weight * _replay_loss(model, replay, ridx)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            model.project()
            total += float(loss.detach())
            steps += 1
        row = {"epoch": epoch, "train_loss": total / max(steps, 1), "val": evaluate(model, val)}
        row["theta"] = model.theta.detach().cpu().tolist()
        result.history.append(row)
        if row["val"]["mrr"] > best_mrr + cfg.min_delta:
            best_mrr, best_state, since, result.best_epoch = (
                row["val"]["mrr"],
                copy.deepcopy(model.state_dict()),
                0,
                epoch,
            )
        else:
            since += 1
        result.epochs_run = epoch
        if epoch % 10 == 0 or epoch == 1:
            log(
                f"  epoch {epoch}: train loss {row['train_loss']:.4f} val mrr {row['val']['mrr']:.5f} "
                f"(best {best_mrr:.5f} @ {result.best_epoch})"
            )
        if since >= cfg.patience:
            result.stopped_early = True
            break
    model.load_state_dict(best_state)
    model.eval()
    result.seconds = time.perf_counter() - start
    return result


def arrays(cases, e0, knowledge) -> dict:
    """Inputs of the cases E0 can score whose gene is in E0's vocabulary (the only ones a loss can use)."""
    from diagnostic_ar_training.ft.bundle import covariates
    from diagnostic_ar_training.ft.system import case_inputs

    lookup = {g.upper(): i for i, g in enumerate(e0.genes)}
    ids, logits, feats, z, target, skipped = [], [], [], [], [], {"gene_not_in_vocab": 0, "unscorable": 0}
    for case in cases:
        idx = lookup.get(case.gene.upper())
        if idx is None:
            skipped["gene_not_in_vocab"] += 1
            continue
        lg, _ = e0(case)
        if lg is None:
            skipped["unscorable"] += 1
            continue
        inputs = case_inputs(case)
        ids.append(case.case_id)
        logits.append(np.asarray(lg, dtype=np.float32))
        feats.append(knowledge.features(inputs))
        z.append(covariates(inputs))
        target.append(idx)
    n_genes, n_feats = len(e0.genes), len(FEATURES)
    return {
        "case_ids": ids,
        "logits": np.stack(logits) if logits else np.zeros((0, n_genes), np.float32),
        "feats": np.stack(feats) if feats else np.zeros((0, n_feats, n_genes), np.float32),
        "z": np.stack(z) if z else np.zeros((0, len(COVARIATES)), np.float32),
        "target": np.asarray(target, dtype=np.int64),
        "skipped": skipped,
    }


def to_part(
    case_ids: list[str],
    logits: np.ndarray,
    feats: np.ndarray,
    z: np.ndarray,
    target: np.ndarray,
    device,
    pooled: np.ndarray | None = None,
) -> Part:
    return Part(
        list(case_ids),
        torch.from_numpy(np.ascontiguousarray(logits, dtype=np.float32)).to(device),
        torch.from_numpy(np.ascontiguousarray(feats, dtype=np.float32)).to(device),
        torch.from_numpy(np.ascontiguousarray(z, dtype=np.float32)).to(device),
        torch.from_numpy(np.asarray(target, dtype=np.int64)).to(device),
        None
        if pooled is None
        else torch.from_numpy(np.ascontiguousarray(pooled, dtype=np.float32)).to(device),
    )
