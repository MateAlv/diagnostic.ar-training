"""ANALYSIS-002 term categories of one simulated export, against the R1-train targets. Reads no R1 data.

The classification is `term_categories.py`'s, against `kb-v4`: each present term is explained, more specific
than an annotated term, or unexplained and binned by the IC of its most informative common ancestor with an
annotated term. The three ADR-0011 amendment 3 targets (R1-train shares of present terms) are:
more specific 0.115, related (IC >= 2) 0.108, weak (IC < 2) 0.239.

Usage: PYTHONPATH=src .venv/bin/python scripts/analysis/dataset_term_categories.py <export.jsonl.gz> \
    [--sample FRACTION] [--out result.json]
"""

import argparse
import gzip
import json
import math
import random
from collections import Counter

from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge

TARGETS = {"more_specific": 0.115, "related_ic_ge_2": 0.108, "weak_ic_lt_2": 0.239}
SAMPLE_SEED = 7


class Categories:
    def __init__(self) -> None:
        self.onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
        self.kb = kb.read(fetch_outputs(load_manifest("kb-v4"))[0])
        self.know = GeneKnowledge(self.kb, self.onto)
        self.dis = self.kb["diseases"]
        counts = Counter()
        for d in self.dis.values():
            closure = set()
            for t in d["phenotypes"]:
                closure.add(t)
                closure |= self.onto.ancestors(t)
            counts.update(closure)
        self.counts, self.n = counts, len(self.dis)
        self._annotated: dict[str, set[str]] = {}

    def ic(self, t: str) -> float:
        return -math.log(max(self.counts.get(t, 0), 1) / self.n)

    def annotated(self, gene: str) -> set[str]:
        if gene not in self._annotated:
            self._annotated[gene] = {t for d in self.know.diseases(gene) for t in self.dis[d]["phenotypes"]}
        return self._annotated[gene]

    def classify(self, gene: str, term: str) -> str:
        t = self.onto.resolve(term) or term
        if self.know.term_probability(gene, t) > 0:
            return "explained"
        annotated = self.annotated(gene)
        ancestors = self.onto.ancestors(t)
        if ancestors & annotated:
            return "more_specific"
        best = 0.0
        own = ancestors | {t}
        for a in annotated:
            common = own & (self.onto.ancestors(a) | {a})
            if common:
                best = max(best, max(self.ic(c) for c in common))
        return "related_ic_ge_2" if best >= 2 else "weak_ic_lt_2"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("export")
    ap.add_argument("--sample", type=float, default=1.0, help="Fraction of records, seed 7 (1.0 = all)")
    ap.add_argument("--out")
    args = ap.parse_args()
    cats = Categories()
    rng = random.Random(SAMPLE_SEED)
    tally, terms, records, skipped = Counter(), 0, 0, 0
    with gzip.open(args.export, "rt", encoding="utf-8") as handle:
        for line in handle:
            if args.sample < 1.0 and rng.random() >= args.sample:
                continue
            r = json.loads(line)
            if not cats.know.diseases(r["gene"]):
                skipped += 1
                continue
            records += 1
            for t in r["present"]:
                tally[cats.classify(r["gene"], t)] += 1
                terms += 1
    shares = {k: tally[k] / terms for k in ("explained", *TARGETS)}
    errors = {k: abs(shares[k] - v) for k, v in TARGETS.items()}
    result = {
        "export": args.export,
        "sample": args.sample,
        "records": records,
        "records_without_kb_gene": skipped,
        "terms": terms,
        "shares": {k: round(v, 4) for k, v in shares.items()},
        "targets": TARGETS,
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
