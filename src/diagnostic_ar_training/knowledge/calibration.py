"""What real patients look like, measured on R1-train only, as targets for the simulator.

Measured against a KB that masks every R1 publication, so that "explained by the
gene" means what it would for a new patient, not for one whose paper fed the KB.
"""

from collections import Counter

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.rerank.features import GeneKnowledge


def _distribution(values: list[int]) -> dict:
    arr = np.asarray(values)
    return {
        "mean": float(arr.mean()),
        "share_zero": float((arr == 0).mean()),
        "percentiles": {str(p): float(np.percentile(arr, p)) for p in (10, 25, 50, 75, 90)},
    }


def measure(
    cases: list[Case], knowledge: GeneKnowledge, min_noise_count: int = 2
) -> tuple[dict, list[tuple]]:
    """Returns (targets, noise vocabulary rows (hpo_id, patients, weight))."""
    in_kb = [c for c in cases if knowledge.diseases(c.gene)]
    own = other = 0
    unexplained_per_case = []
    noise: Counter = Counter()
    for case in in_kb:
        for term in case.excluded:
            if knowledge.term_probability(case.gene, term) > 0:
                own += 1
            else:
                other += 1
        unexplained = {t for t in case.present if knowledge.term_probability(case.gene, t) == 0}
        unexplained_per_case.append(len(unexplained))
        noise.update(unexplained)
    n = len(cases)
    targets = {
        "cases": n,
        "cases_with_gene_in_kb": len(in_kb),
        "present_per_case": _distribution([len(c.present) for c in cases]),
        "excluded_per_case": _distribution([len(c.excluded) for c in cases]),
        "excluded_annotated_to_own_gene_share": own / (own + other) if own + other else None,
        "unexplained_present_per_case": _distribution(unexplained_per_case),
        "unexplained_present_share": sum(unexplained_per_case) / max(1, sum(len(c.present) for c in in_kb)),
        "missing": {
            "sex": sum(c.sex == Sex.UNKNOWN for c in cases) / n,
            "age": sum(c.age_years is None for c in cases) / n,
            "onset": sum(c.onset_years is None and c.onset_term is None for c in cases) / n,
            "excluded": sum(not c.excluded for c in cases) / n,
        },
    }
    # Terms seen once are more likely one paper's idiosyncrasy than a recurring pattern.
    kept = {t: k for t, k in noise.items() if k >= min_noise_count}
    total = sum(kept.values())
    rows = sorted(((t, k, k / total) for t, k in kept.items()), key=lambda r: (-r[1], r[0]))
    targets["noise_vocabulary"] = {
        "terms": len(rows),
        "min_patients": min_noise_count,
        "dropped_singletons": len(noise) - len(kept),
    }
    return targets, rows
