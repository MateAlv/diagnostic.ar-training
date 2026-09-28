"""Checks that training material and evaluation cases do not overlap."""

from collections.abc import Iterable

from diagnostic_ar_training.cohorts.schema import Case


def signature_overlap(train: Iterable[Case], evaluation: Iterable[Case]) -> list[str]:
    """Eval case ids whose (gene, present, excluded) also appears in training."""
    seen = {c.signature() for c in train}
    return [c.case_id for c in evaluation if c.signature() in seen]


def present_set_overlap(train: Iterable[Case], evaluation: Iterable[Case]) -> list[str]:
    """Looser: same gene and same present terms, ignoring excluded ones."""
    seen = {(c.gene, frozenset(c.present)) for c in train}
    return [c.case_id for c in evaluation if (c.gene, frozenset(c.present)) in seen]


def pmid_overlap(used_pmids: Iterable[str], evaluation: Iterable[Case]) -> list[str]:
    """Eval case ids whose publication fed some training input (e.g. an HPOA row)."""
    used = set(used_pmids)
    return [c.case_id for c in evaluation if used.intersection(c.pmids)]
