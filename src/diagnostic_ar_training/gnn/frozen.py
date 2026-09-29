"""Frozen-base Front A runs (ADR-0010): designs, evaluation views, the identity checks and the report.

v3.0 stays frozen, so a run can only move what its new inputs reach:
- R1-dev is scored on every ablation view (EVAL_PROTOCOL §6). E0 sees present terms only, so its ranks are
  the same on every view (EXP-000's present-view ranks).
- S3-dev is scored on the interviewed cases of EXP-S3-001: "present" (reported + "yes") must be E0+answers,
  "all" adds the "no" answers as excluded terms and sex/age/onset as reported.
- The "present only" input must give logits bit-identical to v3.0, before and after training, and R1-dev
  present-view ranks must equal EXP-000's. Each run checks both at the end, on its selected checkpoint.
"""

import json
import math
import re
from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.gnn import experiment, graphs
from diagnostic_ar_training.gnn.train import TrainConfig

DESIGNS = {
    "neg": {"negated": True},
    "neg2": {"negated": True, "neg_readout": True},
    "cov": {"covariates": True},
    "neg+cov": {"negated": True, "covariates": True},
    "neg2+cov": {"negated": True, "neg_readout": True, "covariates": True},
}
ALL_VIEWS = ("present", "excluded", "sex", "age", "all")
S3_VIEWS = ("present", "all")


def epoch_views(cfg: TrainConfig) -> tuple[str, ...]:
    """The R1-dev views that can differ from E0 for this design, plus "present" (the identity anchor)."""
    views = ["present"]
    if cfg.negated:
        views.append("excluded")
    if cfg.covariates:
        views += ["sex", "age"]
    if cfg.covariates or not cfg.negated:
        views.append("all")
    return tuple(views)


def primary_r1_view(cfg: TrainConfig) -> str:
    return "all" if cfg.covariates else "excluded"


def e0_baselines(r1_groups: dict[str, str], s3: bool) -> dict:
    present = experiment._with_groups(harness.read(experiment.E0_R1_DEV["present"]), r1_groups)
    out = {f"r1_dev_{v}": present for v in ALL_VIEWS}
    out["s2"] = harness.read(experiment.E0_S2)
    if s3:
        s3_base = harness.read(experiment.E0_S3_DEV)
        out |= {f"s3_dev_{v}": s3_base for v in S3_VIEWS}
    return out


def score(system, r1_dev, r1_groups, s2, s3_dev, base: dict, r1_views, s3_views=()) -> tuple[dict, dict]:
    """Metrics vs E0 and the per-case records, per R1-dev view, S2 and the S3-dev views asked for."""
    metrics, records = {}, {}
    for view in r1_views:
        recs = harness.run(system, r1_dev, view=view, groups=r1_groups)
        key = f"r1_dev_{view}"
        metrics[key], records[key] = experiment.versus(recs, base[key]), recs
    recs = harness.run(system, s2, view="all")
    metrics["s2"], records["s2"] = experiment.versus(recs, base["s2"]), recs
    if s3_dev is not None:
        groups = {c.case_id: c.gene for c in s3_dev}
        for view in s3_views:
            recs = harness.run(system, s3_dev, view=view, groups=groups)
            key = f"s3_dev_{view}"
            metrics[key], records[key] = experiment.versus(recs, base[key]), recs
    return metrics, records


def present_only_identity(model, v3, inputs, cases: list[Case]) -> dict:
    """Case by case, as served (one graph, no batch): present-only logits of the model vs v3.0's."""
    import torch

    device = next(model.parameters()).device
    identical, scorable, max_diff = 0, 0, 0.0
    with torch.inference_mode():
        for case in cases:
            plain = harness.apply_view(case, "present")
            graph, _ = graphs.case_graph(inputs, plain, negated=True)
            if graph is None:
                continue
            scorable += 1
            x = torch.from_numpy(graph.x).to(device)
            edges = torch.from_numpy(graph.edge_index).to(device)
            covariates = None
            if model.cov_mlp is not None:
                covariates = torch.from_numpy(graph.covariates)[None].to(device)
            out = model(x, edges, torch.from_numpy(graph.node_type).to(device), covariates)
            ref = v3(x, edges)
            identical += bool(torch.equal(out, ref))
            max_diff = max(max_diff, float((out - ref).abs().max()))
    return {"cases": len(cases), "scorable": scorable, "identical": identical, "max_abs_diff": max_diff}


def same_ranks(a: list[dict], b: list[dict]) -> int:
    """Cases whose rank differs between two runs over the same cases."""
    rb = {r["case_id"]: r["rank"] for r in b}
    return sum(r["rank"] != rb[r["case_id"]] for r in a)


def flags(history: list[dict], best_epoch: int, view: str) -> dict:
    """§9.3 warning sign on the design's primary R1 view (the anchor holds by construction here)."""
    key = f"r1_dev_{view}"
    best = next(h for h in history if h["epoch"] == best_epoch)
    start = history[0]
    return {
        "view": view,
        "simval_up_r1dev_down_epochs": [
            h["epoch"]
            for prev, h in zip(history, history[1:], strict=False)
            if h["sim_val"]["mrr"] > prev["sim_val"]["mrr"] and h[key]["mrr"] < prev[key]["mrr"]
        ],
        "simval_up_r1dev_down_at_best": best["sim_val"]["mrr"] > start["sim_val"]["mrr"]
        and best[key]["mrr"] < start[key]["mrr"],
    }


def write_ranks(out_dir: Path, records: dict[str, list[dict]]) -> list[Path]:
    """Compact per-case ranks (case_id, rank, group) of every scored cohort and view."""
    names = {"s2": "s2.ranks.jsonl"}
    paths = []
    for key, recs in sorted(records.items()):
        if key in names:
            name = names[key]
        else:
            cohort, view = key.rsplit("_", 1)
            name = f"{'r1-v1-dev' if cohort == 'r1_dev' else 's3-v1-dev'}.{view}.ranks.jsonl"
        paths.append(experiment.write_compact_ranks(out_dir / name, recs))
    return paths


def _pick(metric: dict | None) -> dict | None:
    if metric is None:
        return None
    keys = ("mrr", "e0_mrr", "delta", "ci95", "harmed", "helped", "n", "top1", "top10")
    return {k: metric[k] for k in keys}


def run_row(run_dir: Path) -> dict:
    run = json.loads((run_dir / "run.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    history = json.loads((run_dir / "curves.json").read_text())
    cfg = run["config"]
    at = summary["at_best"]
    views = summary["epoch_views"]
    return {
        "run_id": run["run_id"],
        "design": run["design"],
        "lr_new": cfg["lr_new"],
        "cov_hidden": cfg["cov_hidden"] if cfg["covariates"] else None,
        "seed": cfg["seed"],
        "train_cases": run["train_cases"],
        "best_epoch": summary["best_epoch"],
        "epochs_run": summary["epochs_run"],
        "stopped_early": summary["stopped_early"],
        "sim_val": {"epoch0": history[0]["sim_val"], "best": summary["sim_val_at_best"]},
        "r1_dev": {v: _pick(at.get(f"r1_dev_{v}")) for v in ALL_VIEWS},
        "s3_dev": {v: _pick(at.get(f"s3_dev_{v}")) for v in S3_VIEWS},
        "s2": _pick(at["s2"]),
        "checks": summary["checks"],
        "flags": summary["flags"],
        "curves": [
            {
                "epoch": h["epoch"],
                "train_loss": h.get("train", {}).get("loss"),
                "sim_val_loss": h["sim_val"]["loss"],
                "sim_val_mrr": h["sim_val"]["mrr"],
                **{f"r1_dev_{v}_mrr": h[f"r1_dev_{v}"]["mrr"] for v in views},
                "s2_mrr": h["s2"]["mrr"],
            }
            for h in history
        ],
        "wall_minutes": summary["wall_seconds"] / 60,
        "train_cases_per_s": float(np.mean([h["train"]["cases_per_s"] for h in history[1:]])),
        "checkpoint_bytes": sum(summary["checkpoints"].values()),
    }


def _mean_sd(values: list[float]) -> dict:
    return experiment.mean_sd([v for v in values if v is not None and not math.isnan(v)])


def seed_aggregate(rows: list[dict]) -> dict:
    """Mean ± sd over the seeds of one configuration (never its best seed)."""
    out = {"seeds": [r["seed"] for r in rows]}
    for v in ALL_VIEWS:
        if all(r["r1_dev"][v] for r in rows):
            out[f"r1_dev_{v}_delta"] = _mean_sd([r["r1_dev"][v]["delta"] for r in rows])
            out[f"r1_dev_{v}_ci_low"] = _mean_sd([r["r1_dev"][v]["ci95"][0] for r in rows])
            out[f"r1_dev_{v}_harmed"] = _mean_sd([r["r1_dev"][v]["harmed"] for r in rows])
    for v in S3_VIEWS:
        if all(r["s3_dev"][v] for r in rows):
            out[f"s3_dev_{v}_delta"] = _mean_sd([r["s3_dev"][v]["delta"] for r in rows])
            out[f"s3_dev_{v}_ci_low"] = _mean_sd([r["s3_dev"][v]["ci95"][0] for r in rows])
            out[f"s3_dev_{v}_harmed"] = _mean_sd([r["s3_dev"][v]["harmed"] for r in rows])
    out["sim_val_mrr"] = _mean_sd([r["sim_val"]["best"]["mrr"] for r in rows])
    out["best_epoch"] = _mean_sd([r["best_epoch"] for r in rows])
    return out


def report(exp_dir: Path) -> dict:
    run_dirs = sorted(p for p in exp_dir.iterdir() if (p / "summary.json").is_file())
    rows = [run_row(p) for p in run_dirs]
    by_config: dict[str, list[dict]] = {}
    for row in rows:
        by_config.setdefault(re.sub(r"-s\d+$", "", row["run_id"]), []).append(row)
    return {"runs": rows, "configurations": {k: seed_aggregate(v) for k, v in by_config.items()}}
