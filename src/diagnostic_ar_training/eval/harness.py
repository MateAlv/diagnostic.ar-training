"""Run a system over a cohort, one record per case, and compare runs case by case."""

import json
import math
import time
from pathlib import Path

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import metrics
from diagnostic_ar_training.systems import System

# Inputs each view keeps beyond the present terms (EVAL_PROTOCOL §6).
VIEWS = {
    "present": set(),
    "excluded": {"excluded"},
    "sex": {"sex"},
    "age": {"age"},
    "all": {"excluded", "sex", "age"},
}


def apply_view(case: Case, view: str) -> Case:
    keep = VIEWS[view]
    return case.model_copy(
        update={
            "excluded": case.excluded if "excluded" in keep else (),
            "sex": case.sex if "sex" in keep else Sex.UNKNOWN,
            "age_years": case.age_years if "age" in keep else None,
            "onset_years": case.onset_years if "age" in keep else None,
            "onset_term": case.onset_term if "age" in keep else None,
        }
    )


def run(system: System, cases: list[Case], view: str = "all") -> list[dict]:
    lookup = {g.upper(): i for i, g in enumerate(system.genes)}
    records = []
    for case in cases:
        viewed = apply_view(case, view)
        start = time.perf_counter()
        scored = system.score(viewed)
        latency_ms = (time.perf_counter() - start) * 1000
        idx = lookup.get(case.gene.upper())
        if scored.probs is None or idx is None:
            rank = math.inf
        else:
            rank = metrics.rank_of(system.genes[idx], system.genes, scored.probs)
        records.append(
            {
                "case_id": case.case_id,
                "gene": case.gene,
                "gene_in_vocab": idx is not None,
                "scorable": scored.probs is not None,
                "rank": rank,
                "true_prob": None if scored.probs is None or idx is None else float(scored.probs[idx]),
                "has_excluded": bool(case.excluded),
                "has_sex": case.sex != Sex.UNKNOWN,
                "has_age": case.age_years is not None,
                "latency_ms": round(latency_ms, 3),
                **scored.info,
            }
        )
    return records


def summarize(records: list[dict]) -> dict:
    ranks = [r["rank"] for r in records]
    out = {"all": metrics.summarize(ranks)}
    subsets = {
        "gene_in_vocab": [r for r in records if r["gene_in_vocab"]],
        "with_excluded": [r for r in records if r["has_excluded"]],
        "with_sex": [r for r in records if r["has_sex"]],
        "with_age": [r for r in records if r["has_age"]],
    }
    for name, subset in subsets.items():
        if subset:
            out[name] = metrics.summarize([r["rank"] for r in subset])
    n_present = sum(r.get("n_present", 0) for r in records)
    lat = np.array([r["latency_ms"] for r in records])
    out["coverage"] = {
        "cases": len(records),
        "gene_not_in_vocab": sum(not r["gene_in_vocab"] for r in records),
        "unscorable": sum(not r["scorable"] for r in records),
        "present_terms": n_present,
        "unknown_terms": sum(r.get("n_unknown", 0) for r in records),
        "zero_embedded_observed_terms": sum(r.get("n_zero_embedded_observed", 0) for r in records),
        "genes_not_in_vocab": sorted({r["gene"] for r in records if not r["gene_in_vocab"]}),
    }
    out["latency_ms"] = {"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95))}
    return out


def compare(base: list[dict], new: list[dict], metric: str = "mrr") -> dict:
    """Paired Δ new − base; both runs must cover the same cases."""
    new_by_id = {r["case_id"]: r["rank"] for r in new}
    if set(new_by_id) != {r["case_id"] for r in base}:
        raise ValueError("runs cover different cases")
    a = [r["rank"] for r in base]
    b = [new_by_id[r["case_id"]] for r in base]
    return {**metrics.paired_bootstrap(a, b, metric), **metrics.harmed_helped(a, b)}


def _encode(value):
    return "inf" if isinstance(value, float) and math.isinf(value) else value


def write(exp_id: str, cohort: str, system_name: str, view: str, records: list[dict]) -> tuple[Path, Path]:
    out_dir = RESULTS_DIR / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{cohort.replace('/', '-')}__{system_name}__{view}"
    ranks_path = out_dir / f"{stem}.ranks.jsonl"
    with ranks_path.open("w") as handle:
        for r in records:
            handle.write(json.dumps({k: _encode(v) for k, v in r.items()}, sort_keys=True) + "\n")
    summary_path = out_dir / f"{stem}.summary.json"
    summary_path.write_text(json.dumps(summarize(records), indent=1, sort_keys=True) + "\n")
    return ranks_path, summary_path


def read(path: Path) -> list[dict]:
    records = []
    for line in Path(path).read_text().splitlines():
        r = json.loads(line)
        r["rank"] = math.inf if r["rank"] == "inf" else r["rank"]
        records.append(r)
    return records
