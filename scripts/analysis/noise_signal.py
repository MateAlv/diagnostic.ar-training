"""E0 in-vocab MRR on a simulated run's noise terms only (ANALYSIS-004's method, `unexplained_signal.py`).

Scores each case on its vocabulary noise alone, its related noise alone, and both together (the ADR-0011
amendment 5 component target, 0.026 on real uncited patients' non-g2p unexplained terms). Also the mean IC
of each noise kind, with `e0_ablation.py`'s IC (disease counts of `--ic-kb`, default kb-v4). Reads no R1 data.

Usage: PYTHONPATH=src .venv/bin/python scripts/analysis/noise_signal.py <rich cases> [keep_one_in] [--out f]
"""

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3


def information_content(kb_id: str):
    onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    diseases = kb.read(fetch_outputs(load_manifest(kb_id))[0])["diseases"]
    counts = Counter()
    for d in diseases.values():
        closure = set(d["phenotypes"])
        for t in d["phenotypes"]:
            closure |= onto.ancestors(t)
        counts.update(closure)

    def ic(t: str) -> float:
        t = onto.resolve(t) or t
        return -math.log(max(counts.get(t, 0), 1) / len(diseases))

    return ic


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cases")
    ap.add_argument("keep_one_in", nargs="?", type=int, default=1, help="Keep cases whose id hash % N == 0")
    ap.add_argument("--out")
    ap.add_argument("--ic-kb", default="kb-v4", help="KB whose disease counts define the IC")
    args = ap.parse_args()
    ic = information_content(args.ic_kb)
    sets: dict[str, list[Case]] = {"vocabulary": [], "related": [], "all_noise": []}
    ics: dict[str, list[float]] = {name: [] for name in sets}
    total = 0
    with open(args.cases, encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            if int(hashlib.sha256(r["case_id"].encode()).hexdigest(), 16) % args.keep_one_in:
                continue
            total += 1
            gene = r["target"]["gene"]
            noise = r.get("noise_phenotypes") or []
            parts = {
                "vocabulary": tuple(n["hpo_id"] for n in noise if n.get("reason") != "related"),
                "related": tuple(n["hpo_id"] for n in noise if n.get("reason") == "related"),
            }
            parts["all_noise"] = tuple(dict.fromkeys(parts["vocabulary"] + parts["related"]))
            for name, terms in parts.items():
                ics[name] += [ic(t) for t in terms]
                if terms:
                    sets[name].append(Case(case_id=r["case_id"], cohort="sim", gene=gene, present=terms))
    e0 = GenPheniaV3()
    out = {"cases_read": total, "keep_one_in": args.keep_one_in}
    for name, cases in sets.items():
        summary = harness.summarize(harness.run(e0, cases, view="present"))
        scored = summary.get("gene_in_vocab", summary["all"])
        out[name] = {"cases_with_terms": len(cases), "mrr_in_vocab": round(scored["mrr"], 4),
                     "terms": len(ics[name]),
                     "mean_ic": round(statistics.mean(ics[name]), 3) if ics[name] else None}
    out["ic_kb"] = args.ic_kb
    text = json.dumps(out, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
