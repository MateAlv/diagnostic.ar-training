"""Patients of a cohort source may only be reached through the frozen split."""

import re

from diagnostic_ar_training import REPO_ROOT

PACKAGE = REPO_ROOT / "src" / "diagnostic_ar_training"
PARSER_USE = r"phenopackets\.iter_cases|from .*phenopackets import iter_cases"
ALLOWED = {PACKAGE / "splits.py", PACKAGE / "cohorts" / "phenopackets.py"}


def test_only_splits_reads_the_phenopacket_parser():
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in PACKAGE.rglob("*.py")
        if p not in ALLOWED and re.search(PARSER_USE, p.read_text())
    ]
    assert offenders == []
