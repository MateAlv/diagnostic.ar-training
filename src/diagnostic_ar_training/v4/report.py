"""Ranks records and summaries for v4: strata, MRR / top-k, Δ vs E0 with the publication-cluster bootstrap.

A record is one patient: case_id, group, status (E0-knowledge citation), fold, gene, gene_in_vocab, scorable,
rank (math.inf when the gene is out of E0's vocabulary or no present term is known: reciprocal rank 0).
Strata (`patients.strata`): all; cited / uncited / no_pmid; in_vocab / oov; and their crossings. The primary
metric is Δ MRR on uncited patients (ADR-0019 §6).
"""

import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training.eval import metrics
from diagnostic_ar_training.v4.patients import strata

PRIMARY = ("uncited", "mrr")
STRATA_ORDER = (
    "all",
    "uncited",
    "cited",
    "no_pmid",
    "in_vocab",
    "oov",
    "uncited_in_vocab",
    "cited_in_vocab",
    "no_pmid_in_vocab",
    "uncited_oov",
    "cited_oov",
    "no_pmid_oov",
)
BOOTSTRAP = {"n_resamples": 2000, "seed": 0}


def record(patient, gene_in_vocab: bool, scorable: bool, rank: float, **extra) -> dict:
    return {
        "case_id": patient.case_id,
        "group": patient.group,
        "status": patient.status,
        "fold": patient.fold,
        "gene": patient.case.gene,
        "gene_in_vocab": gene_in_vocab,
        "scorable": scorable,
        "rank": rank,
        "strata": strata(patient.status, gene_in_vocab),
        **extra,
    }


def by_stratum(records: Sequence[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in records:
        for s in r["strata"]:
            out.setdefault(s, []).append(r)
    return {s: out[s] for s in STRATA_ORDER if s in out}


def _stats(ranks: np.ndarray) -> dict:
    return {
        "mrr": float(np.mean(1.0 / ranks)),
        "top1": float(np.mean(ranks <= 1)),
        "top10": float(np.mean(ranks <= 10)),
    }


def stratum_summary(records: Sequence[dict], e0: Sequence[dict] | None = None) -> dict:
    ranks = np.array([r["rank"] for r in records], dtype=float)
    out = {"n": len(records), "n_groups": len({r["group"] for r in records}), **_stats(ranks)}
    if e0 is None:
        return out
    base = {r["case_id"]: r["rank"] for r in e0}
    if set(base) != {r["case_id"] for r in records}:
        raise ValueError("E0 and the model cover different cases")
    a = np.array([base[r["case_id"]] for r in records], dtype=float)
    groups = [r["group"] for r in records]
    out["e0"] = _stats(a)
    out["delta"] = {k: out[k] - out["e0"][k] for k in ("mrr", "top1", "top10")}
    boot = metrics.paired_bootstrap(a, ranks, "mrr", groups=groups, **BOOTSTRAP)
    out["delta_mrr_ci95"] = boot["ci95"]
    out["helped"], out["harmed"] = int(np.sum(ranks < a)), int(np.sum(ranks > a))
    out["unchanged"] = len(records) - out["helped"] - out["harmed"]
    return out


def summarize(records: Sequence[dict], e0: Sequence[dict] | None = None) -> dict:
    """Per stratum; with `e0` (records of the same cases) also Δ vs E0 with a 95% cluster-bootstrap CI."""
    e0_by_id = None if e0 is None else {r["case_id"]: r for r in e0}
    out = {}
    for name, recs in by_stratum(records).items():
        base = None if e0_by_id is None else [e0_by_id[r["case_id"]] for r in recs]
        out[name] = stratum_summary(recs, base)
    stratum, metric = PRIMARY
    primary = {"stratum": stratum, "metric": metric, "value": out.get(stratum, {}).get(metric)}
    if e0 is not None and stratum in out:
        primary |= {"delta": out[stratum]["delta"][metric], "ci95": out[stratum]["delta_mrr_ci95"]}
    return {"primary": primary, "strata": out, "bootstrap": {**BOOTSTRAP, "unit": "publication group"}}


def selection_metrics(records: Sequence[dict]) -> dict:
    """The few numbers tracked during training (no bootstrap)."""
    groups = by_stratum(records)
    return {
        s: _stats(np.array([r["rank"] for r in groups[s]], dtype=float))
        for s in ("all", "uncited", "cited", "uncited_in_vocab")
        if s in groups
    }


def _encode(value):
    return "inf" if isinstance(value, float) and math.isinf(value) else value


def write_ranks(path: Path, records: Sequence[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w") as handle:
        for r in records:
            handle.write(json.dumps({k: _encode(v) for k, v in r.items()}, sort_keys=True) + "\n")
    tmp.replace(path)
    return path


def read_ranks(path: Path) -> list[dict]:
    out = []
    for line in Path(path).read_text().splitlines():
        r = json.loads(line)
        r["rank"] = math.inf if r["rank"] == "inf" else r["rank"]
        out.append(r)
    return out
