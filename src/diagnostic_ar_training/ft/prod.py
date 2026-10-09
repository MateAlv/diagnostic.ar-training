"""ft-v1.1's production package for diagnostic.ar-model (ADR-0018): export, checks, parity fixture.

- `export` turns an ft-v1 bundle of linear members and its knowledge into one `ft-v1.1-prod-bundle/1` JSON
  object, read by the standalone `dist/ft-v1.1-prod/ft_prod.py` (numpy and the standard library only):
  - the per-gene arrays the active features read, in E0's vocabulary order;
  - the obligate phenotypes of each negatable gene, per disease, with their ancestors-or-self closures;
  - one θ per active feature: the members' mean. For linear members the ensemble's residual is
    mean_m(−θ_m · f) = −(mean_m θ_m) · f, so the mean θ is the same model;
  - provenance.
  Features whose θ is 0 in every member are dropped (`onset_lenient_gap` and `neg_embed` for ft-v1.1), so
  production needs no HPO embeddings.
- `kb_diff` counts, field by field, the genes whose knowledge differs between two `ft-kb/2` builds.
- `fixture_case` is one parity case: the inputs, E0's logits in full (float32, base64), and E0's and the
  expected probabilities on the genes that matter (E0's and the expected top 50, and the true gene).
"""

import base64
import importlib.util
from collections.abc import Mapping, Sequence
from types import ModuleType

import numpy as np

from diagnostic_ar_training import REPO_ROOT
from diagnostic_ar_training.ft.bundle import FEATURES, Knowledge
from diagnostic_ar_training.safe import knowledge as safe_knowledge
from diagnostic_ar_training.safe.bundle import export as safe_export

FORMAT = "ft-v1.1-prod-bundle/1"
FIXTURE_FORMAT = "ft-v1.1-prod-parity/1"
DIST_DIR = REPO_ROOT / "dist" / "ft-v1.1-prod"
STANDALONE = DIST_DIR / "ft_prod.py"
BUNDLE_FILE = "ft-v1.1-prod-bundle.json.gz"
FIXTURE_FILE = "parity-fixture.json.gz"
ARTEFACT_GENES = ("OFD1", "F8", "SLC9A6", "THOC2")
TOP = 50


def load_standalone(path=STANDALONE) -> ModuleType:
    spec = importlib.util.spec_from_file_location("ft_prod", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def effective_theta(bundle: Mapping) -> np.ndarray:
    """[members, len(FEATURES)]: max(θ, 0) on each member's active features, 0 elsewhere.

    Refuses members that are not linear (an MLP or a classifier delta): their residuals do not average into
    one θ.
    """
    rows = []
    for m in bundle["members"]:
        if m.get("mlp") or m.get("classifier_delta"):
            raise ValueError("only linear members (no MLP, no classifier delta) export to one θ")
        active = np.array([f in set(m["active_features"]) for f in FEATURES], dtype=np.float64)
        rows.append(np.maximum(np.asarray(m["theta"], dtype=np.float64), 0.0) * active)
    if tuple(bundle["features"]) != FEATURES or not rows:
        raise ValueError("bundle features differ from ft/bundle.py's, or it has no members")
    return np.stack(rows)


def split_features(bundle: Mapping) -> tuple[list[str], list[str], np.ndarray]:
    """(kept features, dropped features, mean θ over the kept ones). Dropped: θ = 0 in every member."""
    theta = effective_theta(bundle)
    zero = (theta == 0).all(axis=0)
    kept = [f for f, z in zip(FEATURES, zero, strict=True) if not z]
    dropped = [f for f, z in zip(FEATURES, zero, strict=True) if z]
    return kept, dropped, theta[:, ~zero].mean(axis=0)


def without(bundle: Mapping, dropped: Sequence[str]) -> dict:
    """The bundle with `dropped` removed from every member's active features."""
    members = [
        {**m, "active_features": [f for f in m["active_features"] if f not in set(dropped)]}
        for m in bundle["members"]
    ]
    return {**bundle, "members": members}


def export(
    bundle: Mapping,
    kb: Mapping,
    genes: Sequence[str],
    provenance: Mapping,
    standalone_features: Sequence[str],
) -> dict:
    """The `ft-v1.1-prod-bundle/1` object of a linear ft-v1 bundle on its knowledge, over E0's `genes`."""
    kept, dropped, theta = split_features(bundle)
    if tuple(kept) != tuple(standalone_features):
        raise ValueError(
            f"active features {kept}; the standalone module computes {list(standalone_features)}"
        )
    know = Knowledge(kb, genes, None, bundle["kb_id"])
    safe = safe_export(kb["safe"], bundle["kb_id"])
    member_theta = effective_theta(bundle)
    return {
        "format": FORMAT,
        "genes": list(genes),
        "features": kept,
        "theta": theta.tolist(),
        "arrays": {
            "male_limited": know.male.astype(int).tolist(),
            "female_limited": know.female.astype(int).tolist(),
            "xlr_only": know.xlr.astype(int).tolist(),
            "strict_onset_years": [None if np.isneginf(v) else float(v) for v in know.strict],
        },
        "obligate": safe["obligate"],
        "ancestors_or_self": safe["ancestors_or_self"],
        "members": {
            "combine": "mean of the members' θ (their residuals are linear in θ)",
            "theta": {f: member_theta[:, FEATURES.index(f)].tolist() for f in FEATURES},
            "dropped_features": {f: "θ = 0 in every member" for f in dropped},
        },
        "provenance": dict(provenance),
    }


def _fields(kb: Mapping, gene: str) -> dict:
    safe = kb["safe"]["genes"].get(gene, {})
    extra = kb["genes"].get(gene, {})
    return {
        "sex_limit": safe.get("sex", {}).get("limit"),
        "xlr_only": bool(extra.get("xlr_only")),
        "strict_onset_years": safe.get("onset", {}).get("earliest_years"),
        "lenient_onset_years": extra.get("lenient_onset_years"),
        "negatable": safe_knowledge.negatable(safe),
        "obligate": {d: sorted(t) for d, t in sorted(safe.get("obligate", {}).items())},
    }


def kb_diff(old: Mapping, new: Mapping, genes: Sequence[str], named: Sequence[str] = ARTEFACT_GENES) -> dict:
    """Per field, the genes whose value differs from `old` to `new`, with gained / lost / changed counts.

    Gained: no value (or false) before, a value after; lost: the reverse; for onsets, `later` and `earlier`
    split the changed values.
    """
    out = {}
    before = {g: _fields(old, g) for g in genes}
    after = {g: _fields(new, g) for g in genes}
    for field in (
        "sex_limit",
        "xlr_only",
        "strict_onset_years",
        "lenient_onset_years",
        "negatable",
        "obligate",
    ):
        changed = sorted(g for g in genes if before[g][field] != after[g][field])
        gained = [g for g in changed if not before[g][field] and after[g][field]]
        lost = [g for g in changed if before[g][field] and not after[g][field]]
        entry = {"changed": len(changed), "gained": len(gained), "lost": len(lost)}
        if field.endswith("onset_years"):
            both = [g for g in changed if before[g][field] is not None and after[g][field] is not None]
            gained = [g for g in changed if before[g][field] is None]
            lost = [g for g in changed if after[g][field] is None]
            entry.update(
                gained=len(gained),
                lost=len(lost),
                later=sum(after[g][field] > before[g][field] for g in both),
                earlier=sum(after[g][field] < before[g][field] for g in both),
            )
        if field in ("sex_limit", "xlr_only", "negatable"):
            entry["genes"] = {g: [before[g][field], after[g][field]] for g in changed}
        out[field] = entry
    out["named"] = {
        g: {f: [before[g][f], after[g][f]] for f in before[g] if f != "obligate"}
        for g in named
        if g in before
    }
    return out


def encode_f32(values: np.ndarray) -> str:
    return base64.b64encode(np.asarray(values, dtype="<f4").tobytes()).decode("ascii")


def decode_f32(text: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(text), dtype="<f4")


def rank(probs: np.ndarray, idx: int) -> int:
    """Pessimistic rank, as `eval.metrics.rank_of`."""
    return int(1 + np.sum(probs > probs[idx]) + (np.sum(probs == probs[idx]) - 1))


def fixture_case(
    case_id: str,
    kind: str,
    gene: str,
    gene_index: int,
    present: Sequence[str],
    inputs: Mapping,
    logits: np.ndarray,
    e0_probs: np.ndarray,
    expected: np.ndarray,
    lowered: int,
) -> dict:
    if np.asarray(logits).dtype != np.float32:
        raise ValueError("E0's logits are float32; the fixture stores them exactly as such")
    top = set(np.argsort(-e0_probs, kind="stable")[:TOP]) | set(np.argsort(-expected, kind="stable")[:TOP])
    idx = sorted(int(i) for i in top | {gene_index})
    return {
        "case_id": case_id,
        "kind": kind,
        "gene": gene,
        "gene_index": gene_index,
        "present": list(present),
        "inputs": {k: inputs.get(k) for k in ("sex", "age_years", "onset_years", "excluded")},
        "e0_logits_f32_b64": encode_f32(logits),
        "indices": idx,
        "e0_probs": [float(e0_probs[i]) for i in idx],
        "expected_probs": [float(expected[i]) for i in idx],
        "rank_e0": rank(e0_probs, gene_index),
        "rank_expected": rank(expected, gene_index),
        "genes_lowered": lowered,
    }
