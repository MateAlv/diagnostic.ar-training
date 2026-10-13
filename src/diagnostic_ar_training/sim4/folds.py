"""Publication-grouped cross-validation folds of `p3-v1` train (ADR-0019 §5), shared with the v4 harness.

Folds 0-2 fit, fold 3 selects, fold 4 confirms. The CONFIRM fold is read only by the main session:
any read needs DXT_P3_CONFIRM=1 and appends a row to results/P3/CONFIRM_LEDGER.md.
"""

import hashlib
import os
import subprocess
from collections.abc import Iterable
from datetime import UTC, datetime

from diagnostic_ar_training import REPO_ROOT, RESULTS_DIR
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.lineage.registry import LineageError, Purpose

SPLIT = "p3-v1"
SALT = "diagnostic.ar-training/p3-v1-cv"
N_FOLDS = 5
FIT_FOLDS = (0, 1, 2)
SELECT_FOLD = 3
CONFIRM_FOLD = 4
CONFIRM_ENV = "DXT_P3_CONFIRM"
CONFIRM_LEDGER = RESULTS_DIR / "P3" / "CONFIRM_LEDGER.md"
LEDGER_HEADER = (
    "# CONFIRM fold reads (p3-v1 cross-validation, fold 4)\n\n| Date | Git SHA | Reason |\n|---|---|---|\n"
)


def fold_of(group: str) -> int:
    return int(hashlib.sha256(f"{SALT}:{group}".encode()).hexdigest(), 16) % N_FOLDS


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def require_confirm(reason: str) -> None:
    """Gate for the CONFIRM fold: the environment flag, a reason, and a ledger row."""
    if os.environ.get(CONFIRM_ENV) != "1":
        raise LineageError(f"the CONFIRM fold needs {CONFIRM_ENV}=1 (main session only)")
    if not reason.strip():
        raise LineageError("a CONFIRM read needs a reason")
    CONFIRM_LEDGER.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIRM_LEDGER.exists():
        CONFIRM_LEDGER.write_text(LEDGER_HEADER)
    when = datetime.now(UTC).isoformat(timespec="seconds")
    with CONFIRM_LEDGER.open("a") as handle:
        handle.write(f"| {when} | {_git_sha()} | {reason.strip().replace('|', '/')} |\n")


def train_groups() -> dict[str, str]:
    """case_id -> publication group, for `p3-v1` train cases only."""
    from diagnostic_ar_training import splits

    train = set(splits.load_frozen(SPLIT)["case_ids"]["train"])
    return {cid: g for cid, g in splits.publication_groups(SPLIT).items() if cid in train}


def assign(groups: dict[str, str]) -> dict[str, int]:
    """case_id -> fold."""
    return {cid: fold_of(g) for cid, g in groups.items()}


def cases_in(folds: Iterable[int], purpose: Purpose = Purpose.SIMULATE, reason: str = "") -> list[Case]:
    """`p3-v1` train cases whose publication group falls in `folds`."""
    from diagnostic_ar_training import splits

    wanted = set(folds)
    if not wanted <= set(range(N_FOLDS)):
        raise ValueError(f"folds must be in 0..{N_FOLDS - 1}")
    if CONFIRM_FOLD in wanted:
        require_confirm(reason)
    groups = train_groups()
    cases = splits.load_part(SPLIT, splits.Part.TRAIN, purpose)
    return [c for c in cases if fold_of(groups[c.case_id]) in wanted]
