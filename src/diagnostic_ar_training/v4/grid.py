"""Sequential grids of v4 runs under a total time budget; resumable; every configuration and seed logged.

Spec (YAML):
    grid_id: R8                      # becomes each run's label
    base: configs/p3/R7.yaml         # or `config:` with an inline configuration
    total_minutes: 600
    seeds: [0, 1]
    axes:                            # Cartesian product, in the spec's order
      arch.hidden: [512, 768]
      arch.init: [e0, scratch]
    points:                          # optional explicit override sets, run after the product
      - {train.lr: 1.0e-4}

Every (point, seed) gets lines in `results/P3/GRID_LOG.jsonl`, each with its full configuration: `started`,
then `completed` (with the SELECT primary metric), `failed` or `interrupted`; or `skipped_complete` (already
done: the grid resumes) or `skipped_budget` (its `max_minutes` exceeds what is left of this invocation's
budget). Each invocation adds `grid_started` and `grid_finished` / `grid_interrupted`. A budget of many hours
is the normal case; re-running the same command continues where it stopped (an interrupted run resumes from
its `last.pt`). The grid table goes to `results/P3/grids/<grid_id>.json`.
"""

import itertools
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from diagnostic_ar_training.v4 import config as v4config
from diagnostic_ar_training.v4 import runs
from diagnostic_ar_training.v4.config import RunConfig

SPEC_KEYS = {"grid_id", "base", "config", "total_minutes", "seeds", "axes", "points"}


@dataclass(frozen=True)
class Point:
    overrides: dict
    seed: int
    cfg: RunConfig


def load_spec(path: str | Path) -> dict:
    spec = yaml.safe_load(v4config.resolve(path).read_text())
    unknown = set(spec) - SPEC_KEYS
    if unknown:
        raise ValueError(f"grid spec: unknown keys {sorted(unknown)}")
    if ("base" in spec) == ("config" in spec):
        raise ValueError("grid spec: give exactly one of `base` and `config`")
    return spec


def expand(spec: dict) -> list[Point]:
    base = v4config.load(spec["base"]) if "base" in spec else v4config.from_dict(spec["config"])
    base = v4config.override(base, {"label": spec["grid_id"]})
    axes = spec.get("axes") or {}
    combos = [dict(zip(axes, values, strict=True)) for values in itertools.product(*axes.values())]
    if not axes:
        combos = []
    combos += [dict(p) for p in spec.get("points") or []]
    if not combos:
        combos = [{}]
    out = []
    for overrides in combos:
        for seed in spec.get("seeds") or [base.seed]:
            cfg = v4config.override(base, {**overrides, "seed": seed})
            out.append(Point(overrides, seed, cfg))
    ids = [p.cfg.run_id for p in out]
    if len(ids) != len(set(ids)):
        raise ValueError("grid spec: two points give the same configuration")
    return out


def log_path() -> Path:
    return runs.P3_RESULTS / "GRID_LOG.jsonl"


def append_log(entry: dict, path: Path | None = None) -> None:
    path = path or log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def read_log(path: Path | None = None) -> list[dict]:
    path = path or log_path()
    return [json.loads(x) for x in path.read_text().splitlines()] if path.is_file() else []


def _primary(row: dict | None) -> dict | None:
    return None if not row or "select" not in row else row["select"]["primary"]


def run_grid(
    spec: dict,
    run: Callable[[RunConfig], dict],
    total_minutes: float | None = None,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
    after_run: Callable[[], None] = lambda: None,
) -> list[dict]:
    """Run the grid's points in order until the budget is spent; returns the grid table.

    A point is started only when its `max_minutes` plus `EVAL_MINUTES` (final evaluation) fit in what is left.
    An interrupted point keeps its `last.pt`: the next invocation resumes it. Ctrl-C is logged.
    """
    budget = float(total_minutes if total_minutes is not None else spec["total_minutes"])
    points = expand(spec)
    start = clock()
    table = []
    invocation = {"grid_id": spec["grid_id"], "budget_minutes": budget, "points": len(points)}
    append_log({"time": _now(), "event": "grid_started", **invocation})
    try:
        for point in points:
            table.append(_run_point(spec, point, run, budget - (clock() - start) / 60, log))
            after_run()
    except KeyboardInterrupt:
        append_log({"time": _now(), "event": "grid_interrupted", **invocation})
        raise
    finally:
        runs.write_json(
            runs.P3_RESULTS / "grids" / f"{spec['grid_id']}.json", {"grid_id": spec["grid_id"], "runs": table}
        )
    append_log({"time": _now(), "event": "grid_finished", **invocation, "minutes": (clock() - start) / 60})
    return table


EVAL_MINUTES = 3.0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _run_point(spec: dict, point: Point, run: Callable[[RunConfig], dict], left: float, log) -> dict:
    cfg = point.cfg
    base = {
        "grid_id": spec["grid_id"],
        "run_id": cfg.run_id,
        "config_hash": cfg.config_hash,
        "seed": point.seed,
        "overrides": point.overrides,
        "config": cfg.as_dict(),
    }

    def event(name: str, **extra) -> None:
        append_log({"time": _now(), "event": name, **base, **extra})

    row = {k: v for k, v in base.items() if k != "config"}
    if runs.is_complete(cfg.run_id):
        primary = _primary(runs.read_row(cfg.run_id))
        event("skipped_complete", primary=primary)
        return {**row, "status": "complete", "primary": primary}
    if cfg.train.max_minutes + EVAL_MINUTES > left:
        event("skipped_budget", minutes_left=round(left, 2), needs=cfg.train.max_minutes + EVAL_MINUTES)
        return {**row, "status": "skipped_budget"}
    event("started", resuming=(runs.run_dir(cfg.run_id) / "last.pt").is_file())
    log(f"[grid {spec['grid_id']}] {cfg.run_id} seed {point.seed} {point.overrides}")
    try:
        result = run(cfg)
    except KeyboardInterrupt:
        event("interrupted")
        raise
    except Exception as error:
        event("failed", error=f"{type(error).__name__}: {error}")
        return {**row, "status": "failed"}
    primary = _primary(result)
    event("completed", primary=primary, minutes=(result.get("training") or {}).get("minutes"))
    return {**row, "status": "complete", "primary": primary}
