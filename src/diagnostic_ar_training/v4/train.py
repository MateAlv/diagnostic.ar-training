"""Train a GinV4 on the simulator stream under a time / sample budget; select on the SELECT fold.

- Cross-entropy over E0's genes, AdamW (E0's: lr 5e-4, weight decay 5e-4), gradient clipping, bf16 autocast
  on CUDA. Two parameter groups: the GinV3-shaped tensors at `lr`, the options' zero-initialised ones at
  `lr_new`.
- Schedule: linear warmup, then cosine decay over the budget (progress = the larger of time and sample
  fractions), a plateau rule on the selection metric, or constant.
- Every `eval_every_steps` (and at step 0, before any update, and at the end): the SELECT fold's metrics.
  The selection metric is MRR on uncited patients; `best.pt` keeps the best state, `last.pt` everything
  needed to resume. A resumed run continues its budget with a new data stream.
- The budget is wall-clock time of the whole run, evaluations included, summed across resumes.
"""

import json
import math
import time
from collections.abc import Callable
from pathlib import Path

import torch
import torch.nn.functional as F

from diagnostic_ar_training.v4 import data, evaluate, report
from diagnostic_ar_training.v4.config import RunConfig
from diagnostic_ar_training.v4.model import GinV4, is_new_parameter

SELECTION = ("uncited", "mrr")


def param_groups(model: GinV4, cfg: RunConfig) -> list[dict]:
    t = cfg.train
    base = [p for n, p in model.named_parameters() if not is_new_parameter(n)]
    new = [p for n, p in model.named_parameters() if is_new_parameter(n)]
    groups = [{"params": base, "lr": t.lr, "name": "base"}]
    if new:
        groups.append({"params": new, "lr": t.lr if t.lr_new is None else t.lr_new, "name": "new"})
    return groups


def progress(cfg: RunConfig, elapsed: float, samples: int) -> float:
    t = cfg.train
    parts = []
    if t.max_minutes > 0:
        parts.append(elapsed / (t.max_minutes * 60))
    if t.max_samples is not None:
        parts.append(samples / max(t.max_samples, 1))
    return min(1.0, max(parts))


def lr_factor(cfg: RunConfig, step: int, prog: float, plateau_scale: float) -> float:
    t = cfg.train
    warm = min(1.0, (step + 1) / t.warmup_steps) if t.warmup_steps else 1.0
    if t.schedule == "cosine":
        return warm * (t.min_lr_ratio + (1 - t.min_lr_ratio) * 0.5 * (1 + math.cos(math.pi * prog)))
    if t.schedule == "plateau":
        return warm * plateau_scale
    return warm


def budget_spent(cfg: RunConfig, elapsed: float, samples: int) -> bool:
    t = cfg.train
    if t.max_samples is not None and samples >= t.max_samples:
        return True
    return t.max_minutes > 0 and elapsed >= t.max_minutes * 60


def _save(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    torch.save(state, tmp)
    tmp.replace(path)


def _append(path: Path, row: dict) -> None:
    with path.open("a") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=float) + "\n")


def select_metrics(model, select: evaluate.PatientSet, tables, cfg: RunConfig) -> dict:
    return report.selection_metrics(evaluate.model_records(model, select, tables, cfg.encoding))


def selection_value(metrics: dict) -> float:
    stratum, metric = SELECTION
    return metrics[stratum][metric]


def train(
    cfg: RunConfig,
    model: GinV4,
    stream: data.TrainStream,
    tables: data.NodeTables,
    select: evaluate.PatientSet,
    run_dir: Path,
    device: torch.device,
    log: Callable[[str], None] = print,
) -> dict:
    t = cfg.train
    run_dir.mkdir(parents=True, exist_ok=True)
    history_path = run_dir / "history.jsonl"
    torch.manual_seed(cfg.seed)
    optimizer = torch.optim.AdamW(param_groups(model, cfg), weight_decay=t.weight_decay)
    base_lrs = [g["lr"] for g in optimizer.param_groups]
    use_amp = t.amp and device.type == "cuda"

    state = {
        "step": 0,
        "samples": 0,
        "elapsed": 0.0,
        "best": -math.inf,
        "best_step": 0,
        "stale": 0,
        "plateau_stale": 0,
        "plateau_scale": 1.0,
        "stream": 0,
        "real_samples": 0,
    }
    last = run_dir / "last.pt"
    if last.is_file():
        saved = torch.load(last, map_location=device, weights_only=False)
        model.load_state_dict(saved["model"])
        optimizer.load_state_dict(saved["optimizer"])
        state.update(saved["state"])
        state["stream"] += 1
        log(f"resumed at step {state['step']} ({state['elapsed'] / 60:.1f} min spent)")

    def checkpoint(name: str, full: bool) -> None:
        body = {
            "model": model.state_dict(),
            "config": cfg.as_dict(),
            "run_id": cfg.run_id,
            "state": dict(state),
        }
        if full:
            body["optimizer"] = optimizer.state_dict()
        _save(run_dir / name, body)

    def evaluation(train_stats: dict) -> bool:
        """Records one evaluation; True when the run should stop early."""
        start = time.perf_counter()
        metrics = select_metrics(model, select, tables, cfg)
        value = selection_value(metrics)
        improved = value > state["best"] + t.min_delta
        if improved:
            state.update(best=value, best_step=state["step"], stale=0, plateau_stale=0)
        else:
            state["stale"] += 1
            state["plateau_stale"] += 1
            if t.schedule == "plateau" and state["plateau_stale"] >= t.plateau_patience:
                state["plateau_scale"] *= t.plateau_factor
                state["plateau_stale"] = 0
        state["elapsed"] += time.perf_counter() - start
        row = {
            "step": state["step"],
            "samples": state["samples"],
            "minutes": state["elapsed"] / 60,
            "lr": [g["lr"] for g in optimizer.param_groups],
            "select": metrics,
            "selection": value,
            "best": state["best"],
            "train": train_stats,
            "eval_seconds": time.perf_counter() - start,
        }
        _append(history_path, row)
        if improved:
            checkpoint("best.pt", full=False)
        checkpoint("last.pt", full=True)
        log(
            f"step {state['step']:>7} samples {state['samples']:>9} {state['elapsed'] / 60:6.1f} min "
            f"select uncited MRR {value:.4f} all {metrics['all']['mrr']:.4f} best {state['best']:.4f}"
        )
        return t.patience_evals is not None and state["stale"] >= t.patience_evals

    if state["step"] == 0 and not last.is_file():
        evaluation({})
    stopped_early = False
    model.train()
    stream.stream = state["stream"]
    batches = None
    window = {"loss": 0.0, "n": 0, "real": 0, "wait": 0.0, "start": time.perf_counter(), "steps": 0}
    tick = time.perf_counter()
    try:
        while not budget_spent(cfg, state["elapsed"] + time.perf_counter() - tick, state["samples"]):
            if batches is None:
                batches = iter(data.loader(stream, t.num_workers, device.type == "cuda"))
            fetch = time.perf_counter()
            batch = next(batches)
            window["wait"] += time.perf_counter() - fetch
            factor = lr_factor(
                cfg,
                state["step"],
                progress(cfg, state["elapsed"] + time.perf_counter() - tick, state["samples"]),
                state["plateau_scale"],
            )
            for group, lr in zip(optimizer.param_groups, base_lrs, strict=True):
                group["lr"] = lr * factor
            inputs = data.to_device(batch, tables, cfg.encoding)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_amp):
                logits = model(**data.model_inputs(inputs))
            loss = F.cross_entropy(logits.float(), inputs["target"])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), t.clip_norm)
            optimizer.step()
            k = int(inputs["target"].numel())
            state["step"] += 1
            state["samples"] += k
            n_real = int(batch["real"].sum())
            state["real_samples"] += n_real
            window["loss"] += loss.detach() * k
            window["n"] += k
            window["real"] += n_real
            window["steps"] += 1
            if state["step"] % t.eval_every_steps == 0:
                now = time.perf_counter()
                state["elapsed"] += now - tick
                seconds = now - window["start"]
                stats = {
                    "loss": float(window["loss"]) / max(window["n"], 1),
                    "graphs_per_s": window["n"] / seconds,
                    "data_wait_share": window["wait"] / seconds,
                    "real_share": window["real"] / max(window["n"], 1),
                    "steps": window["steps"],
                }
                stop = evaluation(stats)
                model.train()
                window = {
                    "loss": 0.0,
                    "n": 0,
                    "real": 0,
                    "wait": 0.0,
                    "start": time.perf_counter(),
                    "steps": 0,
                }
                tick = time.perf_counter()
                if stop:
                    stopped_early = True
                    break
        else:
            state["elapsed"] += time.perf_counter() - tick
            if window["steps"]:
                seconds = time.perf_counter() - window["start"]
                evaluation(
                    {
                        "loss": float(window["loss"]) / max(window["n"], 1),
                        "graphs_per_s": window["n"] / seconds,
                        "data_wait_share": window["wait"] / seconds,
                        "real_share": window["real"] / max(window["n"], 1),
                        "steps": window["steps"],
                    }
                )
    finally:
        del batches
    return {
        "steps": state["step"],
        "samples": state["samples"],
        "real_samples": state["real_samples"],
        "minutes": state["elapsed"] / 60,
        "best_step": state["best_step"],
        "best_selection": state["best"],
        "stopped_early": stopped_early,
        "resumes": state["stream"],
    }


def load_weights(model: GinV4, path: Path, device) -> dict:
    saved = torch.load(path, map_location=device, weights_only=False)
    model.load_state_dict(saved["model"])
    return saved["state"]


def history(run_dir: Path) -> list[dict]:
    path = run_dir / "history.jsonl"
    return [json.loads(x) for x in path.read_text().splitlines()] if path.is_file() else []


def step0(run_dir: Path) -> dict | None:
    rows = [r for r in history(run_dir) if r["step"] == 0]
    return rows[0]["select"] if rows else None
