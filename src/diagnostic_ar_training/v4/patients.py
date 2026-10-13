"""`p3-v1` train patients for v4: publication group, E0-knowledge status, fold and strata (PHASE3.md §1b).

- Patients come only from `splits.load_part("p3-v1", Part.TRAIN, …)`; the vault is never loaded.
- Folds are `sim4.folds.fold_of(group)`: FIT (0-2) feeds training, SELECT (3) selects. The CONFIRM fold (4)
  is refused here: only the main session reads it, through `sim4.folds` and its ledger.
- Publication groups are the connected components of the train patients. A `p3-v1` group never straddles
  parts, so they equal the frozen union's groups; each must carry a frozen `group_status`.
- Excluded terms never reach v4: patients are stripped to their present terms here.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.lineage.registry import LineageError, Purpose

SPLIT = "p3-v1"
UNCITED = "uncited_e0_knowledge"
CITED = "cited_e0_knowledge"
NO_PMID = "no_pmid"
STATUSES = (CITED, UNCITED, NO_PMID)
FOLD_NAMES = ("fit", "select")


@dataclass(frozen=True)
class Patient:
    case: Case
    group: str
    status: str
    fold: int

    @property
    def case_id(self) -> str:
        return self.case.case_id


def _folds():
    try:
        from diagnostic_ar_training.sim4 import folds
    except ImportError as error:
        raise LineageError("v4 needs sim4.folds (branch p3/sim4) for fold assignment") from error
    return folds


def fold_numbers(name: str, folds_module=None) -> tuple[int, ...]:
    folds = folds_module or _folds()
    if name == "fit":
        return tuple(folds.FIT_FOLDS)
    if name == "select":
        return (folds.SELECT_FOLD,)
    raise LineageError(f"unknown fold set {name!r}: one of {FOLD_NAMES}; CONFIRM is never read by v4")


def present_only(case: Case) -> Case:
    return case.model_copy(
        update={
            "excluded": (),
            "sex": Sex.UNKNOWN,
            "age_years": None,
            "onset_years": None,
            "onset_term": None,
        }
    )


def annotate(
    cases: Sequence[Case],
    groups: dict[str, str],
    status: dict[str, str],
    fold_of: Callable[[str], int],
    keep_covariates: bool = False,
) -> list[Patient]:
    out = []
    for case in cases:
        group = groups[case.case_id]
        if group not in status:
            raise LineageError(f"{case.case_id}: group {group} has no frozen {SPLIT} group_status")
        kept = case.model_copy(update={"excluded": ()}) if keep_covariates else present_only(case)
        out.append(Patient(kept, group, status[group], int(fold_of(group))))
    return out


def in_folds(patients: Iterable[Patient], folds: Iterable[int], confirm_fold: int) -> list[Patient]:
    wanted = set(folds)
    if confirm_fold in wanted:
        raise LineageError(
            f"fold {confirm_fold} is CONFIRM: v4 never reads it (main session only, via sim4.folds)"
        )
    return [p for p in patients if p.fold in wanted]


_CACHE: dict[bool, list[Patient]] = {}


def load_train(keep_covariates: bool = False) -> list[Patient]:
    """Every `p3-v1` train patient, annotated; cached per process."""
    if keep_covariates not in _CACHE:
        from diagnostic_ar_training import splits

        cases = splits.load_part(SPLIT, splits.Part.TRAIN, Purpose.TRAIN)
        groups = splits._components(cases)
        status = splits.load_frozen(SPLIT)["group_status"]
        _CACHE[keep_covariates] = annotate(cases, groups, status, _folds().fold_of, keep_covariates)
    return _CACHE[keep_covariates]


def load(fold_set: str, keep_covariates: bool = False) -> list[Patient]:
    """The patients of `fold_set` ('fit' or 'select')."""
    folds = _folds()
    return in_folds(load_train(keep_covariates), fold_numbers(fold_set, folds), folds.CONFIRM_FOLD)


def strata(status: str, gene_in_vocab: bool) -> list[str]:
    """Every stratum a patient counts in."""
    s = {CITED: "cited", UNCITED: "uncited", NO_PMID: "no_pmid"}[status]
    vocab = "in_vocab" if gene_in_vocab else "oov"
    return ["all", s, vocab, f"{s}_{vocab}"]
