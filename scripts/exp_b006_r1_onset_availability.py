"""EXP-B-006: how many R1-train patients carry usable onset information. Counts only, R1-train only.

Usage: PYTHONPATH=src .venv/bin/python scripts/exp_b006_r1_onset_availability.py

"Usable" is what the re-ranker's `onset` feature reads (`rerank.features.case_onset_years`): the case's
`onset_years`, or the midpoint of its `onset_term` when that term is one of the HPO onset classes the feature
maps. The patient-level onset a web user supplies is the earliest of the per-symptom onsets, so the script also
counts patients whose symptoms carry onsets (`Case.feature_onsets`). Writes results/EXP-B-006/r1-train-onset.json.
"""

import json
from collections import Counter

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.cohorts import access
from diagnostic_ar_training.rerank.features import case_onset_years, onset_bin
from diagnostic_ar_training.rerank.kb import HPO_ONSET_YEARS


def feature_level_onset(case) -> float | None:
    """Earliest per-symptom onset in years, a class counting as its interval midpoint."""
    values = []
    for _, years, onset_class in case.feature_onsets:
        if years is not None:
            values.append(years)
        elif onset_class in HPO_ONSET_YEARS:
            lo, hi = HPO_ONSET_YEARS[onset_class]
            values.append((lo + hi) / 2)
    return min(values) if values else None


def main() -> None:
    cases = access.load("r1-v1/train")
    n = len(cases)
    disease_years = sum(c.onset_years is not None for c in cases)
    disease_term = sum(c.onset_term is not None for c in cases)
    term_mapped = sum(c.onset_term in HPO_ONSET_YEARS for c in cases)
    term_unmapped = Counter(c.onset_term for c in cases if c.onset_term and c.onset_term not in HPO_ONSET_YEARS)
    usable = [case_onset_years(c) for c in cases]
    n_usable = sum(u is not None for u in usable)
    feature = [feature_level_onset(c) for c in cases]
    n_feature = sum(f is not None for f in feature)
    either = sum(u is not None or f is not None for u, f in zip(usable, feature, strict=True))
    both = [(u, f) for u, f in zip(usable, feature, strict=True) if u is not None and f is not None]
    bins = Counter(onset_bin(u) for u in usable if u is not None)
    report = {
        "part": "r1-v1/train",
        "patients": n,
        "disease_onset_years": disease_years,
        "disease_onset_term": disease_term,
        "disease_onset_term_in_feature_map": term_mapped,
        "disease_onset_term_not_in_feature_map": dict(term_unmapped),
        "usable_by_feature": n_usable,
        "usable_by_feature_share": round(n_usable / n, 4),
        "with_feature_level_onset": n_feature,
        "with_feature_level_onset_share": round(n_feature / n, 4),
        "usable_or_feature_level": either,
        "usable_or_feature_level_share": round(either / n, 4),
        "both_usable_and_feature_level": len(both),
        "same_onset_bin_when_both": sum(onset_bin(u) == onset_bin(f) for u, f in both),
        "usable_by_onset_bin": {str(b): bins[b] for b in sorted(bins)},
        "with_excluded_terms": sum(bool(c.excluded) for c in cases),
        "usable_and_excluded": sum(u is not None and bool(c.excluded) for u, c in zip(usable, cases, strict=True)),
    }
    out = RESULTS_DIR / "EXP-B-006"
    out.mkdir(parents=True, exist_ok=True)
    (out / "r1-train-onset.json").write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    print(json.dumps(report, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
