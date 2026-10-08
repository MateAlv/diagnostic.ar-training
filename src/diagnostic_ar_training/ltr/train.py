"""Fit ltr-v1 on r1-v1 train and select it on dev (PHASE2.md Track 2, EXP-P-002).

E0 is scored once per case; each case becomes a `Table` of its top-K candidates and their features, which
every configuration reuses. Ranks are computed here the way `LtrModel.apply` orders genes (candidates by
score, ties in E0's order, every other gene keeps its E0 rank), and the selected model is re-run through the
System to check that. LightGBM is imported only to fit and to predict during the selection.
"""

import hashlib
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import metrics
from diagnostic_ar_training.ltr.bundle import (
    FAMILIES,
    GROUP,
    MONOTONE,
    NAMES,
    SPEC_FORMAT,
    TOP_K,
    Knowledge,
    family_features,
    order,
)
from diagnostic_ar_training.ltr.system import case_inputs
from diagnostic_ar_training.systems import System

INNER_SALT = "ltr-v1-inner"
INNER_SHARE = 0.2


@dataclass
class Table:
    case_id: str
    group: str | None
    e0_rank: float
    top: np.ndarray
    x: np.ndarray
    true_pos: int | None


def tables(
    base: System, knowledge: Knowledge, cases: Sequence[Case], groups: dict[str, str], top_k: int = TOP_K
) -> list[Table]:
    lookup = {g.upper(): i for i, g in enumerate(base.genes)}
    out = []
    for case in cases:
        scored = base.score(case.model_copy(update={"excluded": ()}))
        idx = lookup.get(case.gene.upper())
        empty = np.zeros((0, len(NAMES)))
        if scored.probs is None:
            out.append(Table(case.case_id, groups.get(case.case_id), math.inf, np.zeros(0, int), empty, None))
            continue
        rank = math.inf if idx is None else metrics.rank_of(base.genes[idx], base.genes, scored.probs)
        top = np.argsort(-np.asarray(scored.probs, dtype=np.float64), kind="stable")[:top_k]
        logp = np.log(np.clip(scored.probs[top], 1e-300, None))
        x = knowledge.features(base.genes, top, case_inputs(case), logp)
        hits = np.flatnonzero(top == idx) if idx is not None else []
        out.append(
            Table(case.case_id, groups.get(case.case_id), rank, top, x, int(hits[0]) if len(hits) else None)
        )
    return out


def inner_valid(group: str) -> bool:
    digest = hashlib.sha256(f"{INNER_SALT}:{group}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < INNER_SHARE


@dataclass(frozen=True)
class Config:
    name: str
    family: str
    num_leaves: int
    min_data_in_leaf: int
    learning_rate: float = 0.05
    lambda_l2: float = 1.0
    max_rounds: int = 2000
    early_stopping: int = 100
    shrink: float = 1.0
    """Residual families: the final score is log p_E0 + shrink * model score (applied after fitting)."""

    def __post_init__(self) -> None:
        if self.family not in FAMILIES:
            raise ValueError(f"family must be one of {sorted(FAMILIES)}")
        if not 0 < self.shrink <= 1 or (self.shrink != 1 and not FAMILIES[self.family]["init"]):
            raise ValueError("shrink must be in (0, 1], and 1 for a family without E0's starting score")

    def params(self, features: Sequence[str]) -> dict:
        return {
            "objective": "lambdarank",
            "metric": "map",
            "eval_at": [TOP_K],
            "lambdarank_truncation_level": TOP_K,
            "num_leaves": self.num_leaves,
            "min_data_in_leaf": self.min_data_in_leaf,
            "learning_rate": self.learning_rate,
            "lambda_l2": self.lambda_l2,
            "monotone_constraints": [MONOTONE[f] for f in features],
            "monotone_constraints_method": "advanced",
            "deterministic": True,
            "force_row_wise": True,
            "num_threads": 4,
            "seed": 0,
            "verbosity": -1,
        }


def grid() -> list[Config]:
    """The configurations of EXP-P-002, fixed before any dev number (18 of the 20 allowed)."""
    out = []
    for leaves in (3, 7):
        for min_data in (100, 1000):
            out.append(Config(f"residual_new-l{leaves}-m{min_data}", "residual_new", leaves, min_data))
    for shrink in (1.0, 0.25):
        for leaves in (3, 7, 15):
            for min_data in (100, 1000):
                name = f"residual-l{leaves}-m{min_data}-s{shrink:g}"
                out.append(Config(name, "residual", leaves, min_data, shrink=shrink))
    out.append(Config("free-l15-m100", "free", 15, 100))
    out.append(Config("free-l31-m1000", "free", 31, 1000))
    return out


def _dataset(rows: list[Table], features: Sequence[str], init: bool):
    cols = [NAMES.index(f) for f in features]
    x = np.concatenate([t.x[:, cols] for t in rows])
    y = np.concatenate([np.eye(1, t.x.shape[0], t.true_pos).ravel() for t in rows])
    sizes = [t.x.shape[0] for t in rows]
    init_score = np.concatenate([t.x[:, NAMES.index("e0_logp")] for t in rows]) if init else None
    return x, y, sizes, init_score


def fit(config: Config, train: list[Table], ablation: bool = False) -> tuple[str | None, dict]:
    """(LightGBM text model or None when there is no feature to learn from, fit info)."""
    features = family_features(config.family, ablation)
    init = FAMILIES[config.family]["init"]
    usable = [t for t in train if t.true_pos is not None and t.x.shape[0] > 1]
    fit_rows = [t for t in usable if not inner_valid(t.group or t.case_id)]
    valid_rows = [t for t in usable if inner_valid(t.group or t.case_id)]
    info = {
        "features": list(features),
        "init_e0_logp": init,
        "cases_usable": len(usable),
        "cases_fit": len(fit_rows),
        "cases_inner_valid": len(valid_rows),
    }
    if all(GROUP[f] == "e0" for f in features):
        # Monotone in E0's log-probability alone, the score cannot change E0's order: the system is E0.
        info["model"] = "none: no feature beyond E0's order"
        return None, info
    import lightgbm as lgb

    x, y, sizes, init_score = _dataset(fit_rows, features, init)
    vx, vy, vsizes, vinit = _dataset(valid_rows, features, init)
    train_set = lgb.Dataset(x, y, group=sizes, init_score=init_score, feature_name=list(features))
    valid_set = lgb.Dataset(vx, vy, group=vsizes, init_score=vinit, reference=train_set)
    booster = lgb.train(
        config.params(features),
        train_set,
        num_boost_round=config.max_rounds,
        valid_sets=[valid_set],
        valid_names=["inner_valid"],
        callbacks=[lgb.early_stopping(config.early_stopping, verbose=False)],
    )
    info |= {
        "best_iteration": booster.best_iteration,
        "inner_valid_map100": float(booster.best_score["inner_valid"][f"map@{TOP_K}"]),
    }
    return booster.model_to_string(num_iteration=booster.best_iteration), info


def predict(text: str, rows: list[Table], config: Config, ablation: bool = False) -> list[np.ndarray]:
    """Final candidate scores per case with LightGBM's own predictor (the System uses the numpy one)."""
    import lightgbm as lgb

    features = family_features(config.family, ablation)
    cols = [NAMES.index(f) for f in features]
    booster = lgb.Booster(model_str=text)
    sizes = [t.x.shape[0] for t in rows]
    x = np.concatenate([t.x for t in rows]) if rows else np.zeros((0, len(NAMES)))
    raw = booster.predict(x[:, cols], raw_score=True, num_threads=4) if len(x) else np.zeros(0)
    if FAMILIES[config.family]["init"]:
        raw = x[:, NAMES.index("e0_logp")] + config.shrink * raw
    return np.split(raw, np.cumsum(sizes)[:-1]) if rows else []


def ranks(rows: list[Table], scores: list[np.ndarray] | None) -> list[dict]:
    """Records (case_id, group, rank) as the re-ranked system would rank the true gene."""
    out = []
    for i, t in enumerate(rows):
        rank = t.e0_rank
        if scores is not None and t.true_pos is not None:
            rank = float(np.flatnonzero(order(scores[i]) == t.true_pos)[0] + 1)
        out.append({"case_id": t.case_id, "group": t.group, "rank": rank})
    return out


def spec(config: Config, kb_id: str, kb_sha256: str, ablation: bool = False) -> dict:
    features = family_features(config.family, ablation)
    return {
        "format": SPEC_FORMAT,
        "config": asdict(config),
        "family": config.family,
        "ablation": ablation,
        "features": list(features),
        "monotone": {f: MONOTONE[f] for f in features},
        "init_e0_logp": FAMILIES[config.family]["init"],
        "shrink": config.shrink,
        "top_k": TOP_K,
        "kb_id": kb_id,
        "kb_sha256": kb_sha256,
    }
