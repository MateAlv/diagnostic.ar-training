"""ANALYSIS-002 term categories of one simulated export, against the R1-train targets. Reads no R1 data.

The classification is `term_categories.py`'s (`knowledge.calibration.TermCategories`), against `--kb`
(default kb-v4): each present term is explained, more specific
than an annotated term, or unexplained and binned by the IC of its most informative common ancestor with an
annotated term. The three ADR-0011 amendment 3 targets (R1-train shares of present terms) are:
more specific 0.115, related (IC >= 2) 0.108, weak (IC < 2) 0.239.

Candidate 3 (ADR-0011 amendment 4) measures against kb-v3 with calib-v2's targets.

Usage: PYTHONPATH=src .venv/bin/python scripts/analysis/dataset_term_categories.py <export.jsonl.gz> \
    [--sample FRACTION] [--out result.json] [--kb kb-v3] [--targets data/calib/calib-v2.targets.json]
"""

import argparse
import gzip
import json
import random
from collections import Counter

from diagnostic_ar_training.knowledge.calibration import TermCategories as Categories
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge

TARGETS = {"more_specific": 0.115, "related_ic_ge_2": 0.108, "weak_ic_lt_2": 0.239}
SAMPLE_SEED = 7


def load_categories(kb_id: str) -> Categories:
    onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    kb_data = kb.read(fetch_outputs(load_manifest(kb_id))[0])
    return Categories(kb_data, GeneKnowledge(kb_data, onto), onto)


def read_targets(path: str) -> dict[str, float]:
    """The category shares of a `dxt calib build` targets file (e.g. calib-v2, against its own KB)."""
    with open(path, encoding="utf-8") as handle:
        categories = json.load(handle)["categories"]
    return {k: categories[k] for k in TARGETS}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("export")
    ap.add_argument("--sample", type=float, default=1.0, help="Fraction of records, seed 7 (1.0 = all)")
    ap.add_argument("--out")
    ap.add_argument("--kb", default="kb-v4", help="KB artifact the categories are measured against")
    ap.add_argument("--targets", help="calib targets JSON whose categories replace the ANALYSIS-002 targets")
    args = ap.parse_args()
    cats = load_categories(args.kb)
    targets = read_targets(args.targets) if args.targets else TARGETS
    rng = random.Random(SAMPLE_SEED)
    tally, terms, records, skipped = Counter(), 0, 0, 0
    with gzip.open(args.export, "rt", encoding="utf-8") as handle:
        for line in handle:
            if args.sample < 1.0 and rng.random() >= args.sample:
                continue
            r = json.loads(line)
            if not cats.knowledge.diseases(r["gene"]):
                skipped += 1
                continue
            records += 1
            for t in r["present"]:
                tally[cats.classify(r["gene"], t)] += 1
                terms += 1
    shares = {k: tally[k] / terms for k in ("explained", *TARGETS)}
    errors = {k: abs(shares[k] - v) for k, v in targets.items()}
    result = {
        "export": args.export,
        "sample": args.sample,
        "records": records,
        "records_without_kb_gene": skipped,
        "terms": terms,
        "shares": {k: round(v, 4) for k, v in shares.items()},
        "kb": args.kb,
        "targets": targets,
        "targets_file": args.targets,
        "abs_errors": {k: round(v, 4) for k, v in errors.items()},
        "summed_abs_error": round(sum(errors.values()), 4),
    }
    text = json.dumps(result, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
