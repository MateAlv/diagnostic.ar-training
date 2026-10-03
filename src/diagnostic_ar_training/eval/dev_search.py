"""The ADR-0014 dev search (EXP-B-004 L1-L3): many re-ranker configurations scored on one interview.

The interview (questioner Q0, budget 9) depends only on Q0 and E0, so it is run once and kept; every
arm is then scored on the same answers. An arm differs from another only in its `RerankConfig`, so per
case the expensive part (E0, P(term | gene) of the excluded terms, the non-negation components) is
computed once per knowledge base and every arm is a few array operations on top of it.

`negation_columns` is the vectorised form of `rerank.features.negation` and is tested against it.
"""

import csv
import math
import multiprocessing
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.config import RerankConfig
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge, components
from diagnostic_ar_training.rerank.learned import Table

NEG = ("neg_llr", "neg_annotated_share")
OTHER = tuple(c for c in COMPONENTS if c not in NEG)
LIMITS = (0.05, 0.075, 0.10)
TIE = 0.001
R1_FLOOR = -0.02

FORM_RANK = {"llr": 0, "propagated": 1, "capped": 2, "gated": 3}
KB_RANK = {"kb-v5": 0, "kb-v6": 0, "kb-v8": 1, "kb-v7": 2}


@dataclass(frozen=True)
class Arm:
    arm_id: str
    lever: str
    config: RerankConfig
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "arm_id": self.arm_id,
            "lever": self.lever,
            "config": self.config.to_dict(),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Arm":
        return cls(d["arm_id"], d["lever"], RerankConfig.from_dict(d["config"]), d.get("note", ""))

    @property
    def uses_other(self) -> bool:
        return any(self.config.weights[c] for c in OTHER)


def complexity(arm: Arm) -> tuple:
    """Fewer weighted components, then the simpler form, then the simpler KB, then the smaller weights."""
    c = arm.config
    nonzero = [k for k, v in c.weights.items() if v]
    return (
        len(nonzero),
        FORM_RANK[c.neg_form],
        KB_RANK.get(c.kb_id, 9),
        sum(abs(c.weights[k]) for k in nonzero),
    )


def negation_columns(
    probs: np.ndarray, keep_general: np.ndarray, form: str, k: float, tau: float | None, cap: float | None
) -> np.ndarray:
    """neg_llr per gene from P(t | gene) of the excluded terms (rows genes, columns terms)."""
    if probs.shape[1] == 0:
        return np.zeros(probs.shape[0])
    mask = np.ones(probs.shape, dtype=bool)
    if form == "gated":
        mask = probs >= tau
    elif form == "propagated":
        mask = np.broadcast_to(keep_general[None, :], probs.shape)
    logs = np.where(mask, np.log(1.0 - k * probs), 0.0)
    total = logs.sum(axis=1)
    return np.maximum(total, -cap) if form == "capped" else total


def most_general(ontology: Ontology, terms: Sequence[str]) -> np.ndarray:
    """Per excluded term: no excluded ancestor and not a repeat (as `features.negation`)."""
    listed = set(terms)
    seen: set[str] = set()
    keep = []
    for t in terms:
        keep.append(not ontology.ancestors(t) & listed and t not in seen)
        seen.add(t)
    return np.array(keep, dtype=bool)


@dataclass
class Prepared:
    """What every arm needs about one case; None probs means E0 cannot score it (rank stays inf)."""

    probs: np.ndarray | None
    top: np.ndarray
    true_idx: int | None
    probs_excl: dict[str, np.ndarray]
    other: dict[str, np.ndarray]
    keep_general: np.ndarray


def gene_index(genes: Sequence[str]) -> dict[str, int]:
    return {g.upper(): i for i, g in enumerate(genes)}


def prepare(
    e0, case: Case, gene: str, knowledges: dict[str, GeneKnowledge], ontology: Ontology, need_other: bool,
    top_k: int, lookup: dict[str, int],
) -> Prepared:  # fmt: skip
    probs = e0.score(case).probs
    true_idx = lookup.get(gene.upper())
    keep = most_general(ontology, case.excluded)
    if probs is None:
        return Prepared(None, np.zeros(0, dtype=int), true_idx, {}, {}, keep)
    top = np.argsort(probs)[::-1][:top_k]
    top_genes = [e0.genes[i] for i in top]
    plain = case.model_copy(update={"excluded": ()})
    excl, other = {}, {}
    for kb_id, kn in knowledges.items():
        excl[kb_id] = np.array(
            [[kn.term_probability(g, t) for t in case.excluded] for g in top_genes], dtype=float
        ).reshape(len(top_genes), len(case.excluded))
        if need_other:
            comps = [components(kn, plain, g) for g in top_genes]
            other[kb_id] = np.array([[c[name] for name in OTHER] for c in comps], dtype=float)
    return Prepared(probs, top, true_idx, excl, other, keep)


def rank_at(probs: np.ndarray | None, idx: int | None) -> float:
    if probs is None or idx is None:
        return math.inf
    t = probs[idx]
    return float(1 + (probs > t).sum() + ((probs == t).sum() - 1))


def design(p: Prepared, config: RerankConfig) -> np.ndarray:
    """The [K, len(COMPONENTS)] matrix `learned.table` would build for this case under `config`."""
    x = np.zeros((p.top.size, len(COMPONENTS)))
    probs = p.probs_excl[config.kb_id]
    if config.weights["neg_llr"] or config.weights["neg_annotated_share"]:
        i = COMPONENTS.index("neg_llr")
        x[:, i] = negation_columns(
            probs, p.keep_general, config.neg_form, config.neg_strength, config.neg_tau, config.neg_cap
        )
        if probs.shape[1]:
            x[:, COMPONENTS.index("neg_annotated_share")] = (probs > 0).sum(axis=1) / probs.shape[1]
    if p.other:
        for j, name in enumerate(OTHER):
            if config.weights[name]:
                x[:, COMPONENTS.index(name)] = p.other[config.kb_id][:, j]
    return x


def arm_rank(p: Prepared, config: RerankConfig) -> float:
    if p.probs is None:
        return math.inf
    table = Table(p.probs, p.top, design(p, config), None, {})
    return rank_at(table.combine(config.beta()), p.true_idx)


_WORKER: dict = {}


def _init_worker(
    knowledges: dict[str, GeneKnowledge], ontology: Ontology, arms: list[Arm], top_k: int
) -> None:
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    e0 = GenPheniaV3()
    _WORKER.update(
        e0=e0,
        knowledges=knowledges,
        ontology=ontology,
        arms=arms,
        top_k=top_k,
        lookup=gene_index(e0.genes),
        need_other=any(a.uses_other for a in arms),
    )


def _score_case(item: tuple[Case, str]) -> tuple[float, list[float]]:
    w = _WORKER
    case, gene = item
    p = prepare(w["e0"], case, gene, w["knowledges"], w["ontology"], w["need_other"], w["top_k"], w["lookup"])
    return rank_at(p.probs, p.true_idx), [arm_rank(p, a.config) for a in w["arms"]]


def score_arms(
    items: list[tuple[Case, str]],
    arms: list[Arm],
    knowledges: dict[str, GeneKnowledge],
    ontology: Ontology,
    top_k: int = 200,
    workers: int = 8,
) -> tuple[list[float], np.ndarray]:
    """(E0 rank per case, ranks [cases, arms]); every arm sees the same E0 distribution per case."""
    missing = {a.config.kb_id for a in arms} - set(knowledges)
    if missing:
        raise ValueError(f"no knowledge loaded for {sorted(missing)}")
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(workers, _init_worker, (knowledges, ontology, arms, top_k)) as pool:
        rows = list(pool.imap(_score_case, items, 16))
    return [r[0] for r in rows], np.array([r[1] for r in rows], dtype=float).reshape(len(rows), len(arms))


def records(case_ids: Sequence[str], groups: Sequence[str], ranks: Iterable[float]) -> list[dict]:
    return [
        {"case_id": c, "group": g, "rank": float(r)} for c, g, r in zip(case_ids, groups, ranks, strict=True)
    ]


def compare(base: list[dict], new: list[dict], mask: Sequence[bool] | None = None) -> dict:
    """Paired Δ MRR with a cluster-bootstrap CI over groups (genes), optionally on a subset of cases."""
    from diagnostic_ar_training.eval import harness

    if mask is not None:
        base = [r for r, m in zip(base, mask, strict=True) if m]
        new = [r for r, m in zip(new, mask, strict=True) if m]
    if not base:
        return {
            "n": 0,
            "delta": float("nan"),
            "ci95": [float("nan")] * 2,
            "harmed": float("nan"),
            "helped": float("nan"),
        }
    return harness.compare(base, new)


def r1_no_harm(delta: float, ci_hi: float) -> bool:
    """EXP-B-003 N2 on R1-dev: CI upper bound reaches 0 and the point estimate is at least -0.02."""
    return ci_hi >= 0 and delta >= R1_FLOOR


def feasible(row: dict, max_harmed: float = 0.05) -> bool:
    return row["harmed"] <= max_harmed and row["ci_lo"] > 0 and bool(row["r1_pass"])


def select(rows: list[dict], arms: dict[str, Arm], max_harmed: float = 0.05) -> dict | None:
    """The fixed rule: max Δ MRR among feasible arms; anything within 0.001 of it goes to the simplest."""
    ok = [r for r in rows if feasible(r, max_harmed)]
    if not ok:
        return None
    best = max(r["delta"] for r in ok)
    near = [r for r in ok if r["delta"] >= best - TIE]
    return min(near, key=lambda r: (complexity(arms[r["arm_id"]]), -r["delta"], r["arm_id"]))


def frontier(rows: list[dict]) -> dict[float, dict | None]:
    """For each harm limit, the arm with the best Δ among those at or under it."""
    out: dict[float, dict | None] = {}
    for limit in LIMITS:
        under = [r for r in rows if r["harmed"] <= limit]
        out[limit] = max(under, key=lambda r: r["delta"]) if under else None
    return out


LOG_COLUMNS = (
    "lever", "arm_id", "config_hash", "kb", "form", "k", "tau", "cap", "weights",
    "delta_mrr", "ci_lo", "ci_hi", "harmed", "helped", "n",
    "r1dev_delta", "r1dev_ci_lo", "r1dev_ci_hi", "r1dev_harmed", "r1dev_pass",
    "code_sha", "note",
)  # fmt: skip


def log_row(arm: Arm, s3: dict, r1: dict, code_sha: str) -> dict:
    c = arm.config
    return {
        "lever": arm.lever,
        "arm_id": arm.arm_id,
        "config_hash": c.config_hash,
        "kb": c.kb_id,
        "form": c.neg_form,
        "k": c.neg_strength,
        "tau": "" if c.neg_tau is None else c.neg_tau,
        "cap": "" if c.neg_cap is None else c.neg_cap,
        "weights": ",".join(f"{k}={v:g}" for k, v in c.weights.items() if v),
        "delta_mrr": round(s3["delta"], 6),
        "ci_lo": round(s3["ci95"][0], 6),
        "ci_hi": round(s3["ci95"][1], 6),
        "harmed": round(s3["harmed"], 5),
        "helped": round(s3["helped"], 5),
        "n": s3["n"],
        "r1dev_delta": round(r1["delta"], 6),
        "r1dev_ci_lo": round(r1["ci95"][0], 6),
        "r1dev_ci_hi": round(r1["ci95"][1], 6),
        "r1dev_harmed": round(r1["harmed"], 5),
        "r1dev_pass": int(r1_no_harm(r1["delta"], r1["ci95"][1])),
        "code_sha": code_sha,
        "note": arm.note,
    }


def append_log(path: Path, rows: list[dict]) -> None:
    """Append rows to the TSV; a '#' header the caller wrote first is kept, the column line added once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.exists() else []
    has_columns = any(line.startswith("lever\t") for line in existing)
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, LOG_COLUMNS, delimiter="\t", lineterminator="\n")
        if not has_columns:
            writer.writeheader()
        writer.writerows(rows)


def read_log(path: Path) -> list[dict]:
    lines = [line for line in path.read_text().splitlines() if not line.startswith("#")]
    rows = list(csv.DictReader(lines, delimiter="\t"))
    for r in rows:
        for key in (
            "delta_mrr",
            "ci_lo",
            "ci_hi",
            "harmed",
            "helped",
            "r1dev_delta",
            "r1dev_ci_lo",
            "r1dev_ci_hi",
        ):
            r[key] = float(r[key])
        r["r1_pass"] = int(r["r1dev_pass"])
        r["delta"] = r["delta_mrr"]
    return rows


def known_sex(case: Case) -> bool:
    return case.sex != Sex.UNKNOWN


Mask = Callable[[Case], bool]
