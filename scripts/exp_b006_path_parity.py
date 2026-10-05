"""EXP-B-006: the `RerankConfig` path (dev sessions) and the `Weights` path (R1 gate) agree.

Usage: PYTHONPATH=src .venv/bin/python scripts/exp_b006_path_parity.py [N]

Scores the first N R1-train patients (default 300; R1-train only) on kb-v3 with rr-v1 and rr-v1 + onset 0.25
through both code paths and counts the cases whose output differs at all. Exit 1 if any does.
"""

import sys

import numpy as np

from diagnostic_ar_training.cohorts import access
from diagnostic_ar_training.eval import release_check
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.config import RerankConfig, rr_v1_reference
from diagnostic_ar_training.rerank.learned import table
from diagnostic_ar_training.rerank.model import feature_table
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3


def main(n: int) -> int:
    reference = rr_v1_reference(release_check.KB_ID)
    candidate = RerankConfig.from_dict(
        {**reference.to_dict(), "weights": {**reference.weights, "onset": 0.25}}
    )
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = reference.knowledge(kb.read(fetch_outputs(load_manifest(release_check.KB_ID))[0]), ontology)
    base = GenPheniaV3()
    cases = access.load("r1-v1/train")[:n]
    bad = {"rr-v1": 0, "candidate": 0}
    for case in cases:
        old = table(base, knowledge, case, release_check.TOP_K)
        new = feature_table(base, knowledge, case, release_check.TOP_K)
        for name, config, weights in (
            ("rr-v1", reference, release_check.REFERENCE),
            ("candidate", candidate, release_check.CANDIDATE),
        ):
            a, b = old.combine(config.beta()), new.combine(weights)
            if (a is None) != (b is None) or (a is not None and not np.array_equal(a, b)):
                bad[name] += 1
    print(f"cases={len(cases)} hashes={reference.config_hash},{candidate.config_hash} mismatches={bad}")
    return int(any(bad.values()))


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
