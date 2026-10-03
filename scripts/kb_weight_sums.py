"""Check that each gene's disease weights sum to 1 in a KB (ADR-0014 addendum, phase 3 start).

`onset` and `term_probability` assume it. Reports, per KB, the distribution of the sums and the
genes that deviate; changes nothing.

Usage: python scripts/kb_weight_sums.py kb-v6 kb-v7 kb-v8 > results/EXP-B-004/kb-weight-sums.json
"""

import json
import sys

from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.rerank import kb

TOLERANCE = 1e-6


def check(kb_id: str) -> dict:
    data = kb.read(fetch_outputs(load_manifest(kb_id))[0])
    sums = {gene: sum(diseases.values()) for gene, diseases in data["genes"].items()}
    off = {g: s for g, s in sums.items() if abs(s - 1.0) > TOLERANCE}
    empty = [g for g, d in data["genes"].items() if not d]
    values = sorted(sums.values())
    return {
        "kb": kb_id,
        "genes": len(sums),
        "genes_without_diseases": len(empty),
        "genes_sum_not_1": len(off),
        "min_sum": values[0] if values else None,
        "max_sum": values[-1] if values else None,
        "genes_sum_below": {str(t): sum(v < t for v in values) for t in (0.99, 0.9, 0.75, 0.6)},
        "worst_examples": dict(sorted(off.items(), key=lambda kv: abs(kv[1] - 1.0), reverse=True)[:10]),
        "tolerance": TOLERANCE,
        "negative_weights": sum(w < 0 for d in data["genes"].values() for w in d.values()),
        "diseases_missing_from_kb": sum(
            d not in data["diseases"] for ds in data["genes"].values() for d in ds
        ),
    }


if __name__ == "__main__":
    print(json.dumps([check(k) for k in sys.argv[1:]], indent=1, sort_keys=True))
