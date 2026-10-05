"""EXP-V-001: the final R1-vault report. Descriptive, not a gate.

One pass over a cohort, three systems scored from the same GNN output per case:
- E0: the GNN alone (production v3.0);
- rerank-v1.0.0: `Weights(neg=0.5)` on kb-v3;
- rerank-v1.1.0: the same plus `onset` 0.25, the final chosen system.

Views: "given" (excluded terms and onset as the cohort records them) and "present" (both removed).
The scoring is `release_check`'s (same views, same records, same statistics); this module adds the vault
rules and the report layout. Pre-registration: docs/experiments/EXP-V-001.md.
"""

from collections.abc import Sequence

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness, metrics, release_check
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.rerank import grid
from diagnostic_ar_training.rerank.features import GeneKnowledge
from diagnostic_ar_training.rerank.model import FeatureTable, Weights, feature_table
from diagnostic_ar_training.systems import System

EXPERIMENT = "EXP-V-001"
SPLIT = "r1-v1"
KB_ID = release_check.KB_ID
TOP_K = release_check.TOP_K
VAULT = "r1-v1/vault"
DRY_RUN = "r1-v1/dev"
ALLOWED_COHORTS = {DRY_RUN, VAULT}

SYSTEMS: dict[str, Weights] = {
    "E0": release_check.E0,
    "rerank-v1.0.0": release_check.REFERENCE,
    "rerank-v1.1.0": release_check.CANDIDATE,
}
CONFIG_HASHES = {"rerank-v1.0.0": "fe58053033fa", "rerank-v1.1.0": "71713c8d15b0"}
CONTRASTS = {
    "v1.1_vs_E0": ("E0", "rerank-v1.1.0"),
    "v1.0_vs_E0": ("E0", "rerank-v1.0.0"),
    "v1.1_minus_v1.0": ("rerank-v1.0.0", "rerank-v1.1.0"),
}
VIEWS = ("given", "present")
METRICS = ("mrr", "top1", "top10", "top100")
KS = (1, 10, 100)

NOTE = (
    "Descriptive final report, not a gate: this result cannot change a release decision. A bug found after "
    "the read gets a new pre-registration; the vault is not re-read."
)


def check_request(exp: str, cohort: str, reason: str) -> None:
    if exp != EXPERIMENT:
        raise ValueError(f"this report belongs to {EXPERIMENT}, not {exp!r}")
    if cohort not in ALLOWED_COHORTS:
        raise ValueError(f"cohort must be one of {sorted(ALLOWED_COHORTS)}, got {cohort!r}")
    if cohort == VAULT and not reason.strip():
        raise ValueError(f"{cohort} is sealed: a reason is required")


def preflight(exp: str, cohort: str, reason: str) -> None:
    """Every refusal, before any data is loaded or fetched and before the ledger is touched.

    Raises ValueError for a malformed request and LineageError for a rule of the protocol.
    """
    check_request(exp, cohort, reason)
    if cohort == VAULT:
        ledger.require_sealed_read_env(SPLIT, "vault", exp)
        if ledger.entries(SPLIT, "vault"):
            raise LineageError(f"{VAULT} was already opened (see docs/TEST_LEDGER.md): it opens once")
    registration = ledger.EXPERIMENTS_DIR / f"{exp}.md"
    if not ledger.is_preregistered(registration):
        raise LineageError(f"docs/experiments/{exp}.md must be committed, unmodified, before the run")
    if code_state().dirty:
        raise LineageError("uncommitted changes: results must be reproducible from a SHA")


def _summary(records: list[dict]) -> dict:
    ranks = [r["rank"] for r in records]
    groups = [r.get("group") for r in records]
    grouped = all(g is not None for g in groups)
    return {
        **metrics.summarize(ranks, KS),
        "mrr_ci95": metrics.bootstrap_ci(ranks, "mrr", groups if grouped else None),
        "ci_resample_unit": "publication" if grouped else "case",
    }


def _subset(records: list[dict], keep: set[str]) -> list[dict]:
    return [r for r in records if r["case_id"] in keep]


def _block(records: dict[str, list[dict]]) -> dict:
    n = len(next(iter(records.values())))
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "systems": {name: _summary(recs) for name, recs in records.items()},
        "contrasts": {
            label: {m: harness.compare(records[base], records[new], m) for m in METRICS}
            for label, (base, new) in CONTRASTS.items()
        },
    }


def evaluate(
    base: System,
    knowledge: GeneKnowledge,
    cases: Sequence[Case],
    groups: dict[str, str] | None,
    top_k: int = TOP_K,
) -> tuple[dict, dict[str, dict[str, list[dict]]]]:
    """The report and the per-case records (view -> system -> records)."""
    views = release_check.make_views(cases)
    tables: dict[str, list[FeatureTable]] = {
        v: [feature_table(base, knowledge, c, top_k) for c in views[v]] for v in VIEWS
    }
    records = {
        v: {
            name: grid._records(views[v], tables[v], base.genes, weights, groups)
            for name, weights in SYSTEMS.items()
        }
        for v in VIEWS
    }
    with_onset = {c.case_id for c in cases if release_check.has_onset(c)}
    without = {c.case_id for c in cases} - with_onset
    given = records["given"]
    present = tables["present"]
    report = {
        "descriptive_only": True,
        "note": NOTE,
        "cases": len(cases),
        "publications": len(set((groups or {}).get(c.case_id) for c in cases)) if groups else None,
        "cases_with_usable_onset": len(with_onset),
        "cases_with_excluded": sum(bool(c.excluded) for c in cases),
        "views": {v: _block(records[v]) for v in VIEWS},
        "onset_subset": {
            label: {"cases": len(keep), **_block({n: _subset(r, keep) for n, r in given.items()})}
            for label, keep in (("with_usable_onset", with_onset), ("without_usable_onset", without))
        },
        "sanity": {
            "present_view_v1.1_vs_E0_mismatches": release_check.mismatches(
                present, SYSTEMS["rerank-v1.1.0"], present, SYSTEMS["E0"]
            ),
            "present_view_v1.0_vs_E0_mismatches": release_check.mismatches(
                present, SYSTEMS["rerank-v1.0.0"], present, SYSTEMS["E0"]
            ),
        },
    }
    return report, records
