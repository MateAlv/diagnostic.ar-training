"""Graphs per second of simulated training batches: the loader alone, and full training steps on the GPU."""

import time

import torch
import torch.nn.functional as F

from diagnostic_ar_training.v4 import data
from diagnostic_ar_training.v4.config import RunConfig


def loader_rate(stream: data.TrainStream, num_workers: int, seconds: float, warmup_batches: int = 20) -> dict:
    batches = iter(data.loader(stream, num_workers, pin_memory=False))
    try:
        for _ in range(warmup_batches):
            next(batches)
        start, graphs, nodes = time.perf_counter(), 0, 0
        while time.perf_counter() - start < seconds:
            b = next(batches)
            graphs += int(b["target"].numel())
            nodes += int(b["nodes"].numel())
        elapsed = time.perf_counter() - start
    finally:
        del batches
    return {
        "workers": num_workers,
        "graphs_per_s": graphs / elapsed,
        "nodes_per_graph": nodes / max(graphs, 1),
    }


def train_rate(
    cfg: RunConfig, model, stream: data.TrainStream, tables, device, seconds: float, warmup_steps: int = 30
) -> dict:
    """Full steps (forward, backward, AdamW) at the configuration's batch size, workers and AMP."""
    t = cfg.train
    optimizer = torch.optim.AdamW(model.parameters(), lr=t.lr, weight_decay=t.weight_decay)
    use_amp = t.amp and device.type == "cuda"
    model.train()
    batches = iter(data.loader(stream, t.num_workers, device.type == "cuda"))
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)

    def step(batches) -> int:
        batch = next(batches)
        inputs = data.to_device(batch, tables, cfg.encoding)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_amp):
            logits = model(**data.model_inputs(inputs))
        loss = F.cross_entropy(logits.float(), inputs["target"])
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), t.clip_norm)
        optimizer.step()
        return int(inputs["target"].numel())

    try:
        for _ in range(warmup_steps):
            step(batches)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        start, graphs, steps = time.perf_counter(), 0, 0
        while time.perf_counter() - start < seconds:
            graphs += step(batches)
            steps += 1
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        elapsed = time.perf_counter() - start
    finally:
        del batches
    rate = graphs / elapsed
    out = {
        "batch_size": t.batch_size,
        "workers": t.num_workers,
        "amp": use_amp,
        "graphs_per_s": rate,
        "steps_per_s": steps / elapsed,
        "samples_per_hour": rate * 3600,
    }
    if device.type == "cuda":
        out["peak_memory_gb"] = torch.cuda.max_memory_allocated(device) / 2**30
    return out
