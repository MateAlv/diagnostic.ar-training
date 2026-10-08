"""EXP-P-003's dev grid (docs/experiments/EXP-P-003.md): 8 configurations × seeds 0-2, the ablation, the
selection.

The grid and the selection rule were committed with the pre-registration before any dev run.
"""

import hashlib
import math
import statistics
from collections.abc import Mapping

from diagnostic_ar_training.ft.bundle import COVARIATE_GROUPS, COVARIATES, FEATURE_GROUPS, FEATURES

# Run and bundle ids: ft-v1.1 is the grid rerun with the fixed X-linked features (EXP-P-003, addendum).
PREFIX = "ft-v1.1"
SEEDS = (0, 1, 2)
HELD_OUT_SHARE = 0.2
HELD_OUT_SALT = "ft-v1/inner"


def inner_split(groups: Mapping[str, str], case_ids, share: float = HELD_OUT_SHARE) -> set[str]:
    """Case ids of the held-out train publication groups (early stopping): a salted hash of the group."""

    def bucket(group: str) -> int:
        return int(hashlib.sha256(f"{HELD_OUT_SALT}/{group}".encode()).hexdigest()[:8], 16) % 100

    return {c for c in case_ids if bucket(groups[c]) < round(share * 100)}


SAFE3 = ("sex_mismatch", "onset_strict_late", "neg_obligate")
NO_XL = tuple(f for f in FEATURES if f != "xlr_female")
CLASSIFIER = {"classifier": True, "lr_classifier": 1e-4, "replay_weight": 1.0}

CONFIGS: dict[str, dict] = {
    "c1-lin-all": {"hidden": 0, "lr": 0.05},
    "c2-lin-safe3": {"hidden": 0, "lr": 0.05, "features": SAFE3},
    "c3-lin-noxl": {"hidden": 0, "lr": 0.05, "features": NO_XL},
    "c4-mlp16": {"hidden": 16, "lr": 0.05, "lr_mlp": 0.01},
    "c5-mlp16-lr0.01": {"hidden": 16, "lr": 0.01, "lr_mlp": 0.002},
    "c6-mlp64": {"hidden": 64, "lr": 0.05, "lr_mlp": 0.01},
    "c7-cls-l2sp1e-2": {"hidden": 16, "lr": 0.05, "lr_mlp": 0.01, **CLASSIFIER, "l2sp": 1e-2},
    "c8-cls-l2sp1e-4": {"hidden": 16, "lr": 0.05, "lr_mlp": 0.01, **CLASSIFIER, "l2sp": 1e-4},
}
# EVAL_PROTOCOL §10: learned Phase 2 candidates use gene-agnostic features. The classifier configurations
# learn
# per-gene weights from patients, so they are measured and reported but cannot be selected.
SELECTABLE = tuple(k for k, v in CONFIGS.items() if not v.get("classifier"))
ABLATION_SUFFIX = "-nosexage"
TIE_MARGIN = 0.0005
MAX_HARMED = 0.05


def config(name: str) -> dict:
    """The FitConfig fields of a grid configuration or of its ablation (`<name>-nosexage`)."""
    base = name.removesuffix(ABLATION_SUFFIX)
    if base not in CONFIGS:
        raise ValueError(
            f"unknown configuration {name!r}; one of {sorted(CONFIGS)} (optionally {ABLATION_SUFFIX})"
        )
    out = dict(CONFIGS[base])
    if name.endswith(ABLATION_SUFFIX):
        features = out.get("features", FEATURES)
        out["features"] = tuple(f for f in features if f in FEATURE_GROUPS["negation"])
        out["covariates"] = tuple(c for c in COVARIATES if c in COVARIATE_GROUPS["counts"])
        if not out["features"]:
            raise ValueError(f"{base} has no negation feature: its ablation would be E0")
    return out


def n_parameters(name: str, n_genes: int = 5229, hidden_dim: int = 512) -> int:
    c = config(name)
    k, h = len(FEATURES), c.get("hidden", 0)
    n = len(c.get("features", FEATURES))
    if h:
        n += (len(COVARIATES) * h + h) + (h * k + k)
    if c.get("classifier"):
        n += n_genes * hidden_dim + n_genes
    return n


def _mean_sd(values: list[float]) -> dict:
    return {
        "mean": statistics.fmean(values),
        "sd": statistics.stdev(values) if len(values) > 1 else None,
        "n": len(values),
    }


def aggregate(rows: list[dict]) -> dict:
    """Mean ± sd over a configuration's seeds of dev Δ, CI bounds and harmed share; never the best seed."""
    out = {"seeds": sorted(r["seed"] for r in rows)}
    for key in ("delta", "ci_low", "ci_high", "harmed", "helped"):
        values = [r["dev"][key] for r in rows]
        if all(v is not None and not math.isnan(v) for v in values):
            out[f"dev_{key}"] = _mean_sd(values)
    for key in ("present_delta", "train_delta", "inner_delta", "post_e0_delta"):
        values = [r.get(key) for r in rows]
        if all(v is not None for v in values):
            out[key] = _mean_sd(values)
    return out


def select(by_config: Mapping[str, dict], seeds: tuple[int, ...] = SEEDS) -> dict:
    """EXP-P-003's rule over the configurations that ran every seed.

    1. Selectable configurations (no per-gene parameters) with every seed valid and mean harmed ≤ 5%. 2. The
       highest mean dev Δ. A configuration with fewer parameters within `TIE_MARGIN` of it is preferred
       (fewest first, then the lower learning rate). 3. No candidate when the chosen mean dev Δ is not above
       0.
    """
    eligible = {}
    for name, agg in by_config.items():
        if name not in SELECTABLE or tuple(agg["seeds"]) != tuple(seeds) or not agg.get("valid", True):
            continue
        if agg["dev_harmed"]["mean"] <= MAX_HARMED:
            eligible[name] = agg["dev_delta"]["mean"]
    if not eligible:
        return {"selected": None, "eligible": {}, "why": "no eligible configuration"}
    best = max(eligible.values())
    close = [n for n, d in eligible.items() if d >= best - TIE_MARGIN]
    chosen = min(close, key=lambda n: (n_parameters(n), CONFIGS[n].get("lr", 0), -eligible[n]))
    out = {"eligible": eligible, "best_mean_delta": best, "within_margin": sorted(close), "selected": chosen}
    if eligible[chosen] <= 0:
        out |= {
            "selected": None,
            "why": "the chosen configuration's mean dev Δ is not above 0",
            "would_be": chosen,
        }
    return out
