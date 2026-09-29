"""A Front A run end to end: training data with its exclusion applied, the §9.3 curves, the final evaluation.

Every evaluation cohort is reached through its sealed-aware loader, and only the free or selection parts are
read here: R1-dev (`splits.load_part`), S2 (`cohorts.access`), S3-dev (interviewed cases cached by
`dxt s3 interviews`). Every Δ is against E0's per-case ranks on the same cases, from its own experiment.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.gnn import data
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest, output_path
from diagnostic_ar_training.lineage.registry import LineageError, load_sources

DATASET = "ds-sim0.3.1-A-n100-s1001"
EXCLUSION = "ds-sim0.3.1-A-n100-s1001-excl-v1"
E0_R1_DEV = {view: RESULTS_DIR / "EXP-000" / f"r1-v1-dev__genphenia-v3.0__{view}.ranks.jsonl" for view in
             ("present", "all")}  # fmt: skip
E0_S2 = RESULTS_DIR / "EXP-000" / "s2__genphenia-v3.0__all.ranks.jsonl"
E0_S3_DEV = RESULTS_DIR / "EXP-S3-001" / "s3-v1-dev__E0+answers__interviewed.ranks.jsonl"
E0_S2_MRR = 0.8117
S2_FORGETTING_MARGIN = 0.02
NO_REGRESSION_MARGIN = -0.01


@dataclass
class TrainingData:
    splits: dict[str, list[data.SimCase]]
    counts: dict
    lineage: list[dict]


def load_training_data(dataset_id: str = DATASET, exclusion_id: str = EXCLUSION) -> TrainingData:
    """The dataset via its manifest (sha-verified), minus the exclusion artifact's case ids."""
    dataset = load_manifest(dataset_id)
    path = next(p for p in fetch_outputs(dataset) if p.name.endswith(".jsonl.gz"))
    exclusion = load_manifest(exclusion_id)
    if f"artifact:{dataset_id}" not in {i.id for i in exclusion.inputs}:
        raise LineageError(f"{exclusion_id} was not built from {dataset_id}")
    excl_out = exclusion.outputs[0]
    excl_path = output_path(excl_out)
    if not excl_path.is_file() or sha256_file(excl_path) != excl_out.sha256:
        raise LineageError(f"{excl_path} is missing or does not match {exclusion_id}'s manifest")
    exclude = data.read_exclusion(excl_path)
    splits, counts = data.read_export(path, exclude=exclude)
    dropped = sum(counts["excluded"].values())
    if dropped != len(exclude) or exclusion.params.get("excluded") != len(exclude):
        raise LineageError(f"exclusion dropped {dropped} cases; {exclusion_id} lists {len(exclude)}")
    if exclusion.params.get("residual_overlap") != 0:
        raise LineageError(f"{exclusion_id} does not certify a residual overlap of 0")
    lineage = [
        {"id": f"artifact:{dataset_id}", "sha256": sha256_file(path)},
        {"id": f"artifact:{exclusion_id}", "sha256": excl_out.sha256},
    ]
    return TrainingData(splits, counts, lineage)


def check_contamination(training: list[data.SimCase], cohorts: dict[str, list[Case]]) -> dict:
    """§9.7 residual check on the cohorts this run may read; the sealed ones are certified by the artifact."""
    report = {}
    for name, cases in cohorts.items():
        overlap = data.residual_overlap(training, cases)
        report[name] = {"cases": len(cases), "present_set_overlap": len(overlap), "examples": overlap[:5]}
    return report


def _with_groups(records: list[dict], groups: dict[str, str]) -> list[dict]:
    return [{**r, "group": groups[r["case_id"]]} for r in records]


@dataclass
class EvalSets:
    sim_val: data.SimGraphs
    r1_dev: list[Case]
    r1_groups: dict[str, str]
    s2: list[Case]
    s3_dev: list[Case] | None
    views: tuple[str, ...] = ("present",)

    def baselines(self) -> dict:
        out = {f"r1_dev_{v}": _with_groups(harness.read(E0_R1_DEV[v]), self.r1_groups) for v in self.views}
        out["s2"] = harness.read(E0_S2)
        if self.s3_dev is not None:
            out["s3_dev"] = harness.read(E0_S3_DEV)
        return out

    def lineage(self) -> list[dict]:
        refs = [{"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")}]
        refs.append(load_sources()["graphens_sim_20251202"].as_input())
        files = [E0_R1_DEV[v] for v in self.views] + [E0_S2] + ([E0_S3_DEV] if self.s3_dev else [])
        refs += [{"id": f"results:{p.parent.name}/{p.name}", "sha256": sha256_file(p)} for p in files]
        return refs


def versus(records: list[dict], base: list[dict]) -> dict:
    summary = harness.summarize(records)["all"]
    delta = harness.compare(base, records)
    return {
        "mrr": summary["mrr"],
        "top1": summary["top1"],
        "top10": summary["top10"],
        "n": summary["n"],
        "unrankable": summary["unrankable"],
        "e0_mrr": harness.summarize(base)["all"]["mrr"],
        "delta": delta["delta"],
        "ci95": delta["ci95"],
        "resample_unit": delta["resample_unit"],
        "harmed": delta["harmed"],
        "helped": delta["helped"],
    }


def score_cohorts(system, sets: EvalSets, base: dict, s3: bool) -> tuple[dict, dict]:
    """Metrics vs E0 and the per-case records, for R1-dev (each view), S2 and optionally S3-dev."""
    metrics, records = {}, {}
    for view in sets.views:
        recs = harness.run(system, sets.r1_dev, view=view, groups=sets.r1_groups)
        metrics[f"r1_dev_{view}"], records[f"r1_dev_{view}"] = versus(recs, base[f"r1_dev_{view}"]), recs
    recs = harness.run(system, sets.s2, view="all")
    metrics["s2"], records["s2"] = versus(recs, base["s2"]), recs
    if s3 and sets.s3_dev is not None:
        groups = {c.case_id: c.gene for c in sets.s3_dev}
        recs = harness.run(system, sets.s3_dev, view="present", groups=groups)
        metrics["s3_dev_present"], records["s3_dev_present"] = versus(recs, base["s3_dev"]), recs
    return metrics, records


def flags(history: list[dict], best_epoch: int, view: str = "present") -> dict:
    """§9.3 warning signs, and the §9.4 anchor, at the checkpoint selected by sim-val."""
    key = f"r1_dev_{view}"
    diverging_epochs = [
        h["epoch"]
        for prev, h in zip(history, history[1:], strict=False)
        if h["sim_val"]["mrr"] > prev["sim_val"]["mrr"] and h[key]["mrr"] < prev[key]["mrr"]
    ]
    best = next(h for h in history if h["epoch"] == best_epoch)
    start = history[0]
    floor = E0_S2_MRR - S2_FORGETTING_MARGIN
    return {
        "simval_up_r1dev_down_epochs": diverging_epochs,
        "simval_up_r1dev_down_at_best": best["sim_val"]["mrr"] > start["sim_val"]["mrr"]
        and best[key]["mrr"] < start[key]["mrr"],
        "s2_forgetting_at_best": best["s2"]["mrr"] < floor,
        "s2_forgetting_epochs": [h["epoch"] for h in history if h["s2"]["mrr"] < floor],
        "no_regression_ci_low_at_best": best[key]["ci95"][0],
        "no_regression_pass": best[key]["ci95"][0] >= NO_REGRESSION_MARGIN,
    }


def _encode(v):
    return "inf" if isinstance(v, float) and math.isinf(v) else v


def write_compact_ranks(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for r in records:
            row = {"case_id": r["case_id"], "rank": _encode(r["rank"]), "group": r.get("group")}
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def mean_sd(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    return {"mean": float(a.mean()), "sd": float(a.std(ddof=1)) if a.size > 1 else None, "n": int(a.size)}
