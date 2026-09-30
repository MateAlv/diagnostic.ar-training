"""E0 in-vocab MRR on a simulated run's noise terms only (ANALYSIS-004's method, `unexplained_signal.py`).

Scores each case on its vocabulary noise alone, its related noise alone, and both together (the ADR-0011
amendment 5 component target, 0.026 on real uncited patients' non-g2p unexplained terms). Reads no R1 data.

Usage: PYTHONPATH=src .venv/bin/python scripts/analysis/noise_signal.py <rich cases> [keep_one_in] [--out f]
"""

import argparse
import hashlib
import json

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cases")
    ap.add_argument("keep_one_in", nargs="?", type=int, default=1, help="Keep cases whose id hash % N == 0")
    ap.add_argument("--out")
    args = ap.parse_args()
    sets: dict[str, list[Case]] = {"vocabulary": [], "related": [], "all_noise": []}
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
                if terms:
                    sets[name].append(Case(case_id=r["case_id"], cohort="sim", gene=gene, present=terms))
    e0 = GenPheniaV3()
    out = {"cases_read": total, "keep_one_in": args.keep_one_in}
    for name, cases in sets.items():
        summary = harness.summarize(harness.run(e0, cases, view="present"))
        scored = summary.get("gene_in_vocab", summary["all"])
        out[name] = {"cases_with_terms": len(cases), "mrr_in_vocab": round(scored["mrr"], 4)}
    text = json.dumps(out, indent=1)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
