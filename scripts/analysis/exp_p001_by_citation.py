"""EXP-P-001 addendum (descriptive, after the read): the test result split by whether E0's training
annotations (HPO 2025-11-24) cite the patient's publication. Reads only the read's own ranks files.

Usage: python scripts/analysis/exp_p001_by_citation.py
"""

import json
import math

import numpy as np

from diagnostic_ar_training.eval.metrics import paired_bootstrap
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.splits import cited_pmids

cited = cited_pmids(open_source("hpo_annotations_2025_11_24", Purpose.EVAL))
LABEL = "results/EXP-P-001/p2-v1-test-safe-kb-v1"


def ranks(name: str) -> dict:
    with open(f"{LABEL}__{name}__all.ranks.jsonl") as f:
        return {x["case_id"]: x for x in map(json.loads, f)}


def rank(x: dict) -> float:
    return math.inf if x["rank"] in (None, "inf") else float(x["rank"])


e0 = ranks("E0")
systems = {name: ranks(name) for name in ("safe-v1", "safe-v1[onset]", "safe-v1[sex]", "safe-v1[negation]")}
out = {}
for label, want in (("cited", True), ("not_cited", False)):
    ids = [c for c in e0 if ("PMID:" + e0[c]["group"].split("PMID:")[-1] in cited) == want]
    groups = [e0[c]["group"] for c in ids]
    base = [rank(e0[c]) for c in ids]
    out[label] = {
        "n": len(ids),
        "groups": len(set(groups)),
        "e0_mrr": float(np.mean([0.0 if math.isinf(b) else 1 / b for b in base])),
    }
    for name, ranks_ in systems.items():
        res = paired_bootstrap(base, [rank(ranks_[c]) for c in ids], groups=groups)
        out[label][name] = {"delta": res["delta"], "ci95": res["ci95"]}
path = f"{LABEL}__by_citation.json"
with open(path, "w") as f:
    json.dump(out, f, indent=1)
print(json.dumps(out, indent=1))
