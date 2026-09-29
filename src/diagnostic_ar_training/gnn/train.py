"""Fine-tune GinV3Extended from v3.0 on simulated cases (EVAL_PROTOCOL §9).

- Gradients: the simulated training split only. Early stopping: sim-val MRR, never R1.
- AdamW with two parameter groups: v3.0's tensors at `lr_base` (≤ 5e-4, §9.6) and the new zero-initialised
  ones at `lr_new`. With `lr_new == 0` the new tensors are frozen, so the model stays a GinV3.
- Warmup then cosine decay to `min_lr_ratio`, gradient clipping, optional bf16 autocast on CUDA.
- BatchNorm `train` (batch statistics, running stats updated) or `frozen` (v3.0's running stats kept;
  affine parameters still trained).
- `frozen_base` (ADR-0010): every v3.0 tensor is frozen and the whole model runs in eval mode (BatchNorm
  running statistics, no dropout); only the new inputs' parameters train, at `lr_new`. `type_proj` keeps
  its observed/ancestor columns at 0 and the covariate path is exactly 0 when nothing is known
  (`cov_neutral_zero`), so the "present only" view stays bit-identical to v3.0 after training.
  Checkpoints then hold the new tensors only; the v3.0 ones come from the pinned bundle.
- Epoch 0 is evaluated before any step: it is v3.0, so every curve starts at E0.
- After each epoch: `evaluate(model, epoch)` (the §9.3 curves), `last.pt`, and `best.pt` when sim-val
  MRR improved by more than `min_delta`. Stops after `patience` epochs without improvement.
"""

import json
import math
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from diagnostic_ar_training.gnn import data
from diagnostic_ar_training.gnn.graphs import NODE_NEGATED
from diagnostic_ar_training.gnn.model import GinV3Extended, is_new_parameter

MAX_LR_BASE = 5e-4


@dataclass(frozen=True)
class TrainConfig:
    lr_base: float = 5e-5
    lr_new: float = 0.0
    weight_decay: float = 5e-4
    batch_size: int = 256
    max_epochs: int = 6
    patience: int = 2
    min_delta: float = 1e-4
    warmup_steps: int = 200
    min_lr_ratio: float = 0.1
    clip_norm: float = 1.0
    bn: str = "train"
    amp: bool = False
    seed: int = 0
    negated: bool = False
    covariates: bool = False
    neg_readout: bool = False
    cov_hidden: int = 32
    frozen_base: bool = False
    num_workers: int = 10
    eval_batch_size: int = 1024
    max_train_cases: int | None = None

    def __post_init__(self) -> None:
        if self.frozen_base:
            if self.lr_base != 0 or self.lr_new <= 0:
                raise ValueError("a frozen base trains only the new parameters: lr_base = 0 and lr_new > 0")
            if not (self.negated or self.covariates):
                raise ValueError("a frozen base needs a new input to train (negated terms or covariates)")
        elif not 0 < self.lr_base <= MAX_LR_BASE:
            raise ValueError(f"lr_base must be in (0, {MAX_LR_BASE}] for v3.0 weights (EVAL_PROTOCOL §9.6)")
        if self.bn not in ("train", "frozen"):
            raise ValueError("bn must be 'train' or 'frozen'")


def build_model(base, cfg: TrainConfig) -> GinV3Extended:
    if cfg.frozen_base:
        return _frozen_base_model(base, cfg)
    model = GinV3Extended.from_v3(
        base, covariates=cfg.covariates, neg_readout=cfg.neg_readout, cov_hidden=cfg.cov_hidden
    )
    for name, p in model.named_parameters():
        if is_new_parameter(name) and cfg.lr_new == 0:
            p.requires_grad_(False)
    return model


def _positive_type_mask(weight: torch.Tensor) -> torch.Tensor:
    mask = torch.zeros_like(weight)
    mask[:, NODE_NEGATED] = 1
    return mask


def _frozen_base_model(base, cfg: TrainConfig) -> GinV3Extended:
    """ADR-0010: v3.0 frozen; only the parameters of the inputs this design uses can train."""
    model = GinV3Extended.from_v3(
        base,
        covariates=cfg.covariates,
        neg_readout=cfg.neg_readout,
        cov_hidden=cfg.cov_hidden,
        cov_neutral_zero=True,
    )
    for name, p in model.named_parameters():
        negation_part = name.startswith(("type_proj.", "neg_gates.", "neg_"))
        p.requires_grad_(is_new_parameter(name) and (cfg.negated or not negation_part))
    if cfg.negated:
        # Only the negated column of type_proj may move: the observed/ancestor columns would be a new input
        # of the "present only" view.
        mask = _positive_type_mask(model.type_proj.weight)
        model.type_proj.weight.register_hook(lambda grad: grad * mask)
    return model


def base_unchanged(model: GinV3Extended, base) -> bool:
    """Every v3.0 tensor (weights and BatchNorm statistics) still equals the bundle's, bit for bit."""
    state = model.state_dict()
    return all(torch.equal(state[k], v.to(state[k].device)) for k, v in base.state_dict().items())


def positive_types_closed(model: GinV3Extended) -> bool:
    w = model.type_proj.weight
    return not (w * (1 - _positive_type_mask(w))).any()


def param_groups(model: torch.nn.Module, cfg: TrainConfig) -> list[dict]:
    base = [p for n, p in model.named_parameters() if not is_new_parameter(n) and p.requires_grad]
    new = [p for n, p in model.named_parameters() if is_new_parameter(n) and p.requires_grad]
    groups = [] if cfg.frozen_base else [{"params": base, "lr": cfg.lr_base, "name": "v3"}]
    if new:
        groups.append({"params": new, "lr": cfg.lr_new, "name": "new"})
    return groups


def set_train_mode(model: torch.nn.Module, bn: str) -> None:
    model.train()
    if bn == "frozen":
        for m in model.modules():
            if isinstance(m, torch.nn.BatchNorm1d):
                m.eval()


def lr_factor(step: int, warmup: int, total: int, floor: float) -> float:
    if step < warmup:
        return (step + 1) / warmup
    progress = min(1.0, (step - warmup) / max(1, total - warmup))
    return floor + (1 - floor) * 0.5 * (1 + math.cos(math.pi * progress))


def forward(model: GinV3Extended, inputs: dict) -> torch.Tensor:
    return model(
        inputs["x"],
        inputs["edge_index"],
        inputs["node_type"],
        inputs["covariates"] if model.cov_mlp is not None else None,
        inputs["batch"],
        inputs["num_graphs"],
    )


def ranks_from_logits(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Pessimistic 1-based rank of the target (ties count against it), as metrics.rank_of."""
    t = logits.gather(1, target.unsqueeze(1))
    return (logits > t).sum(1) + (logits == t).sum(1)


@torch.no_grad()
def evaluate_sim(
    model: GinV3Extended, dataset: data.SimGraphs, table: torch.Tensor, device, cfg: TrainConfig
) -> dict:
    """Cross-entropy and MRR on simulated cases, eval mode; unscorable cases count with MRR 0."""
    model.eval()
    loss_sum, rr_sum, n, unscorable = 0.0, 0.0, 0, 0
    ranks = np.full(len(dataset), np.inf)
    for batch in data.loader(dataset, cfg.eval_batch_size, None, cfg.num_workers):
        unscorable += batch["n_unscorable"]
        if batch["target"].numel() == 0:
            continue
        inputs = data.to_device(batch, table, device)
        logits = forward(model, inputs).float()
        loss_sum += F.cross_entropy(logits, inputs["target"], reduction="sum").item()
        r = ranks_from_logits(logits, inputs["target"]).double()
        rr_sum += (1.0 / r).sum().item()
        ranks[batch["index"].numpy()] = r.cpu().numpy()
        n += int(inputs["target"].numel())
    total = n + unscorable
    return {
        "loss": loss_sum / max(n, 1),
        "mrr": rr_sum / max(total, 1),
        "top1": float(np.mean(ranks <= 1)),
        "top10": float(np.mean(ranks <= 10)),
        "n": total,
        "unscorable": unscorable,
    }


def _save(path: Path, **state) -> None:
    tmp = path.with_suffix(".tmp")
    torch.save(state, tmp)
    tmp.replace(path)


def train(
    model: GinV3Extended,
    cfg: TrainConfig,
    train_set: data.SimGraphs,
    table: torch.Tensor,
    device: torch.device,
    evaluate: Callable[[GinV3Extended, int], dict],
    ckpt_dir: Path,
    on_epoch: Callable[[list[dict]], None] = lambda history: None,
) -> dict:
    """`evaluate` must return a dict with `sim_val.mrr`; it runs in eval mode after each epoch."""
    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    optimizer = torch.optim.AdamW(param_groups(model, cfg), weight_decay=cfg.weight_decay)
    steps_per_epoch = len(train_set) // cfg.batch_size
    total_steps = steps_per_epoch * cfg.max_epochs
    base_lrs = [g["lr"] for g in optimizer.param_groups]
    use_amp = cfg.amp and device.type == "cuda"
    trainable = [p for g in optimizer.param_groups for p in g["params"]]

    def checkpoint(name: str, epoch: int, with_optimizer: bool) -> None:
        weights = model.state_dict()
        if cfg.frozen_base:
            weights = {k: v for k, v in weights.items() if is_new_parameter(k)}
        state = {"model": weights, "epoch": epoch, "config": asdict(cfg)}
        if with_optimizer:
            state |= {"optimizer": optimizer.state_dict(), "step": step}
        _save(ckpt_dir / name, **state)

    step = 0
    model.eval()
    history = [{"epoch": 0, "step": 0, **evaluate(model, 0)}]
    best_mrr, best_epoch, stale = history[0]["sim_val"]["mrr"], 0, 0
    checkpoint("best.pt", 0, with_optimizer=False)
    on_epoch(history)
    stopped_early = False
    for epoch in range(1, cfg.max_epochs + 1):
        if cfg.frozen_base:
            model.eval()
        else:
            set_train_mode(model, cfg.bn)
        start = time.perf_counter()
        loss_sum, n_cases, n_unscorable, grad_norms, data_wait = 0.0, 0, 0, [], 0.0
        tick = time.perf_counter()
        batches = data.loader(
            train_set, cfg.batch_size, cfg.seed * 1000 + epoch, cfg.num_workers, device.type == "cuda"
        )
        for batch in batches:
            data_wait += time.perf_counter() - tick
            n_unscorable += batch["n_unscorable"]
            if batch["target"].numel() < 2:
                tick = time.perf_counter()
                continue
            factor = lr_factor(step, cfg.warmup_steps, total_steps, cfg.min_lr_ratio)
            for group, lr in zip(optimizer.param_groups, base_lrs, strict=True):
                group["lr"] = lr * factor
            inputs = data.to_device(batch, table, device)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_amp):
                logits = forward(model, inputs)
            loss = F.cross_entropy(logits.float(), inputs["target"])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            grad_norms.append(torch.nn.utils.clip_grad_norm_(trainable, cfg.clip_norm).item())
            optimizer.step()
            step += 1
            k = int(inputs["target"].numel())
            loss_sum += loss.item() * k
            n_cases += k
            tick = time.perf_counter()
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        seconds = time.perf_counter() - start
        model.eval()
        eval_start = time.perf_counter()
        metrics = evaluate(model, epoch)
        record = {
            "epoch": epoch,
            "step": step,
            "train": {
                "loss": loss_sum / max(n_cases, 1),
                "cases": n_cases,
                "unscorable": n_unscorable,
                "seconds": seconds,
                "cases_per_s": n_cases / seconds,
                "data_wait_s": data_wait,
                "grad_norm_mean": float(np.mean(grad_norms)) if grad_norms else None,
                "grad_norm_max": float(np.max(grad_norms)) if grad_norms else None,
                "clipped_share": float(np.mean(np.array(grad_norms) > cfg.clip_norm)) if grad_norms else None,
                "lr_end": {g["name"]: g["lr"] for g in optimizer.param_groups},
            },
            "eval_seconds": time.perf_counter() - eval_start,
            **metrics,
        }
        history.append(record)
        checkpoint("last.pt", epoch, with_optimizer=True)
        mrr = record["sim_val"]["mrr"]
        if mrr > best_mrr + cfg.min_delta:
            best_mrr, best_epoch, stale = mrr, epoch, 0
            checkpoint("best.pt", epoch, with_optimizer=False)
        else:
            stale += 1
        on_epoch(history)
        if stale >= cfg.patience:
            stopped_early = epoch < cfg.max_epochs
            break
    return {
        "history": history,
        "best_epoch": best_epoch,
        "best_sim_val_mrr": best_mrr,
        "epochs_run": history[-1]["epoch"],
        "stopped_early": stopped_early,
        "steps": step,
    }


def load_checkpoint(model: GinV3Extended, path: Path) -> int:
    """A frozen-base checkpoint holds the new tensors only; the model must already carry v3.0's."""
    state = torch.load(path, map_location=next(model.parameters()).device, weights_only=True)
    if state["config"].get("frozen_base"):
        result = model.load_state_dict(state["model"], strict=False)
        if result.unexpected_keys or any(is_new_parameter(k) for k in result.missing_keys):
            raise RuntimeError(f"frozen-base checkpoint mismatch: {result}")
    else:
        model.load_state_dict(state["model"])
    return int(state["epoch"])


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")
