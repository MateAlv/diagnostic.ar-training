"""ft-v1 vs E0 on one cohort: overall, on the subsets, and the present-only identity check.

Statistics are safe-v1's (`eval.safe_eval.contrast`): paired publication-cluster bootstrap (2,000 resamples,
seed 0, 95% CI), harmed and helped shares and counts, top-1 and top-10 entries and exits. Subsets:
in-vocabulary, each input known (sex, age, onset, excluded), post-E0 publications, and any named extra subsets
(e.g. the held-out train groups).
"""

from collections.abc import Mapping, Sequence

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.eval.safe_eval import contrast, known_subsets


def _subset(records: list[dict], keep: set[str]) -> list[dict]:
    return [r for r in records if r["case_id"] in keep]


def present_identity(system, e0_system, cases: Sequence[Case]) -> dict:
    """Cases where the present-only view of `system` differs from E0, bit for bit, and in rank."""
    differ, scorable = 0, 0
    for case in cases:
        plain = harness.apply_view(case, "present")
        a, b = system.score(plain).probs, e0_system.score(plain).probs
        if a is None and b is None:
            continue
        scorable += 1
        differ += (a is None) != (b is None) or not np.array_equal(a, b)
    return {"scorable": scorable, "probs_differ": differ}


def report(
    e0: list[dict],
    new: list[dict],
    cases: Sequence[Case],
    extra_subsets: Mapping[str, set[str]] | None = None,
) -> dict:
    subsets = {"gene_in_vocab": {r["case_id"] for r in e0 if r["gene_in_vocab"]}}
    subsets |= known_subsets(cases)
    subsets |= dict(extra_subsets or {})
    return {
        "cases": len(cases),
        "e0": harness.summarize(e0)["all"],
        "summary": harness.summarize(new)["all"],
        "vs_e0": contrast(e0, new),
        "subset_sizes": {k: len(v) for k, v in subsets.items()},
        "subsets": {k: contrast(_subset(e0, v), _subset(new, v)) for k, v in subsets.items()},
    }


def line(label: str, d: dict) -> str:
    if not d.get("n"):
        return f"{label:28} n 0"
    return (
        f"{label:28} n {d['n']:5d} dMRR {d['delta']:+.5f} [{d['ci95'][0]:+.5f}, {d['ci95'][1]:+.5f}] "
        f"helped {d['helped_n']:4d} harmed {d['harmed_n']:4d} ({d['harmed']:.4f}) "
        f"top1 +{d['top1_entered']}/-{d['top1_left']} top10 +{d['top10_entered']}/-{d['top10_left']}"
    )
