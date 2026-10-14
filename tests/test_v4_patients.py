"""v4 patients: fold filtering never reaches CONFIRM, excluded terms never enter, strata."""

import hashlib
import types

import pytest

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.v4 import patients


def fold_of(group: str) -> int:
    """Local copy of sim4.folds.fold_of (PHASE3.md §1b), for tests only."""
    return int(hashlib.sha256(f"diagnostic.ar-training/p3-v1-cv:{group}".encode()).hexdigest(), 16) % 5


FOLDS = types.SimpleNamespace(FIT_FOLDS=(0, 1, 2), SELECT_FOLD=3, CONFIRM_FOLD=4, fold_of=fold_of)


def case(i: int, **kw) -> Case:
    return Case(case_id=f"c{i}", cohort="t", gene="G", present=("HP:1",), excluded=("HP:2",), **kw)


@pytest.fixture
def annotated():
    groups = {f"c{i}": f"PMID:{i}" for i in range(60)}
    status = {f"PMID:{i}": patients.STATUSES[i % 3] for i in range(60)}
    cases = [case(i, sex=Sex.FEMALE, age_years=3.0) for i in range(60)]
    return patients.annotate(cases, groups, status, fold_of)


def test_folds_follow_the_salted_group_hash(annotated):
    assert {p.fold for p in annotated} == {0, 1, 2, 3, 4}
    assert all(p.fold == fold_of(p.group) for p in annotated)


def test_confirm_fold_is_refused(annotated):
    with pytest.raises(LineageError, match="CONFIRM"):
        patients.in_folds(annotated, (3, 4), FOLDS.CONFIRM_FOLD)
    with pytest.raises(LineageError, match="CONFIRM"):
        patients.fold_numbers("confirm", FOLDS)
    select = patients.in_folds(annotated, patients.fold_numbers("select", FOLDS), FOLDS.CONFIRM_FOLD)
    fit = patients.in_folds(annotated, patients.fold_numbers("fit", FOLDS), FOLDS.CONFIRM_FOLD)
    assert select and fit and {p.fold for p in select} == {3} and {p.fold for p in fit} == {0, 1, 2}
    assert not {p.case_id for p in select} & {p.case_id for p in fit}


def test_load_goes_through_sim4_folds_and_refuses_confirm(monkeypatch, annotated):
    monkeypatch.setattr(patients, "_folds", lambda: FOLDS)
    monkeypatch.setattr(patients, "load_train", lambda keep_covariates=False: annotated)
    assert {p.fold for p in patients.load("select")} == {3}
    with pytest.raises(LineageError):
        patients.load("confirm")


def test_excluded_terms_never_enter_and_covariates_only_when_asked(annotated):
    assert all(p.case.excluded == () for p in annotated)
    assert all(p.case.sex == Sex.UNKNOWN and p.case.age_years is None for p in annotated)
    kept = patients.annotate(
        [case(1, sex=Sex.FEMALE, age_years=3.0)],
        {"c1": "PMID:1"},
        {"PMID:1": patients.UNCITED},
        fold_of,
        True,
    )[0]
    assert kept.case.excluded == () and kept.case.sex == Sex.FEMALE and kept.case.age_years == 3.0


def test_every_group_needs_a_frozen_status():
    with pytest.raises(LineageError, match="group_status"):
        patients.annotate([case(1)], {"c1": "PMID:1"}, {}, fold_of)


def test_strata():
    assert patients.strata(patients.UNCITED, True) == ["all", "uncited", "in_vocab", "uncited_in_vocab"]
    assert patients.strata(patients.CITED, False) == ["all", "cited", "oov", "cited_oov"]
    assert patients.strata(patients.NO_PMID, True)[1] == "no_pmid"


def test_phenotype_swap_is_one_seeded_cycle(annotated):
    source = patients.swap_sources(len(annotated))
    assert sorted(source) == list(range(len(annotated))) and all(source != range(len(annotated)))
    assert list(source) == list(patients.swap_sources(len(annotated)))
    seen, i = set(), 0
    while i not in seen:
        seen.add(i)
        i = source[i]
    assert len(seen) == len(annotated)
    swapped, ids = patients.phenotype_swap(annotated)
    for p, q, j, cid in zip(annotated, swapped, source, ids, strict=True):
        donor = annotated[j]
        assert cid == donor.case_id and q.case.present == donor.case.present
        assert (q.case_id, q.case.gene, q.group, q.status, q.fold) == (
            p.case_id,
            p.case.gene,
            p.group,
            p.status,
            p.fold,
        )
