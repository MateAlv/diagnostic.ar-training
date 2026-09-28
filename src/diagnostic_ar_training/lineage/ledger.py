"""Every read of a sealed split part is pre-registered and logged in docs/TEST_LEDGER.md."""

import re
from datetime import UTC, datetime

from diagnostic_ar_training import DOCS_DIR
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.registry import LineageError

LEDGER = DOCS_DIR / "TEST_LEDGER.md"
EXPERIMENTS_DIR = DOCS_DIR / "experiments"
EXP_ID = re.compile(r"^EXP-(000|[AB]-\d{3})$")
ROW = "| {when} | {split}/{part} | {exp} | {sha} | {reason} |\n"


def entries(split_id: str, part: str) -> list[str]:
    if not LEDGER.exists():
        return []
    tag = f"| {split_id}/{part} |"
    return [line for line in LEDGER.read_text().splitlines() if tag in line]


def record_access(split_id: str, part: str, exp_id: str, reason: str) -> None:
    """Refuses unless the experiment is pre-registered and the code is committed."""
    if not EXP_ID.match(exp_id):
        raise LineageError(f"{exp_id!r} is not an experiment id (EXP-000, EXP-A-001, EXP-B-001, ...)")
    if not (EXPERIMENTS_DIR / f"{exp_id}.md").exists():
        raise LineageError(
            f"docs/experiments/{exp_id}.md missing: pre-register the hypothesis and gate "
            "before opening a sealed split"
        )
    state = code_state()
    if state.dirty:
        raise LineageError("uncommitted changes: a sealed evaluation must be reproducible from a SHA")
    if not reason.strip():
        raise LineageError("a reason is required")
    row = ROW.format(
        when=datetime.now(UTC).isoformat(timespec="seconds"),
        split=split_id,
        part=part,
        exp=exp_id,
        sha=state.sha[:12],
        reason=reason.replace("|", "/"),
    )
    with LEDGER.open("a") as handle:
        handle.write(row)
