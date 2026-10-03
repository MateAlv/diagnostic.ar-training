"""Parity of the dev-search scorer with the legacy path (learned.table + Table.combine + s3_run.rank).

Takes the first N kept interviews of S3-v2-dev and compares, per config, the rank each path gives the
true gene. Reads only the kept dev interview; writes nothing. Exit code 1 on any difference.

Usage: python scripts/dev_search_parity.py [N]
"""

import sys

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.eval import dev_run, dev_search, s3_run
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.config import RerankConfig
from diagnostic_ar_training.rerank.features import GeneKnowledge
from diagnostic_ar_training.rerank.learned import table
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

CONFIGS = [
    RerankConfig("kb-v6", "llr", 0.5, weights={"neg_llr": 0.5}),
    RerankConfig("kb-v6", "gated", 0.8, neg_tau=0.2, weights={"neg_llr": 2.0}),
    RerankConfig("kb-v6", "capped", 0.5, neg_cap=1.0, weights={"neg_llr": 3.0}),
    RerankConfig("kb-v6", "propagated", 0.5, weights={"neg_llr": 1.5}),
    RerankConfig(
        "kb-v6",
        "llr",
        0.5,
        weights={
            "neg_llr": 1.0,
            "sex_prior": 1.0,
            "sex_restricted": 1.0,
            "age_mean": 0.5,
            "age_any": 1.0,
            "onset": 2.0,
        },
    ),
]


def main(n: int) -> int:
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(load_manifest("kb-v6"))[0]), ontology)
    e0 = GenPheniaV3()
    lookup = dev_search.gene_index(e0.genes)
    rows = dev_run.read_interviews(
        RESULTS_DIR / "EXP-B-004" / "dev-search" / "interviews.q0-kb-v6-b9.jsonl.gz"
    )[:n]
    differ = 0
    for config in CONFIGS:
        legacy_knowledge = config.knowledge(knowledge.kb, ontology)
        for r in rows:
            p = dev_search.prepare(
                e0, r["case"], r["gene"], {"kb-v6": knowledge}, ontology, True, 200, lookup
            )
            new = dev_search.arm_rank(p, config)
            t = table(e0, legacy_knowledge, r["case"], 200)
            old = s3_run.rank(t.combine(config.beta()), e0.genes, r["gene"])
            differ += new != old
        print(f"{config.config_hash} {config.neg_form:10} cases={len(rows)} differing_ranks={differ}")
    return int(differ > 0)


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 300))
