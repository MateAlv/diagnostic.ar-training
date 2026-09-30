"""ANALYSIS-003: what makes simulated cases hard for E0? Ablations on a rich-cases file, vs R1-train.

R1-train only (uncited-in-HPOA patients, ANALYSIS-002). Usage:
  python scripts/analysis/e0_ablation.py <rich cases.jsonl> [keep_one_in]
"""

import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter

from diagnostic_ar_training import splits
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

keep = int(sys.argv[2]) if len(sys.argv) > 2 else 160
onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
K = kb.read(fetch_outputs(load_manifest("kb-v4"))[0])
know = GeneKnowledge(K, onto)
cnt = Counter()
for d in K["diseases"].values():
    c = set()
    for t in d["phenotypes"]:
        c.add(t)
        c |= onto.ancestors(t)
    cnt.update(c)
N = len(K["diseases"])


def ic(t):
    t = onto.resolve(t) or t
    return -math.log(max(cnt.get(t, 0), 1) / N)


variants = {k: [] for k in ("as_exported", "no_noise", "no_generalization", "no_specialization",
                            "profile_terms_ungeneralized_no_noise", "all_true_terms")}
ics = {"sim_profile_positives": [], "sim_noise": []}
with open(sys.argv[1]) as f:
    for line in f:
        cid = line[13:80].split('"')[0]
        if int(hashlib.sha256(cid.encode()).hexdigest(), 16) % keep:
            continue
        r = json.loads(line)
        gene = r["target"]["gene"]
        pos = r["positive_phenotypes"]
        noise = [n["hpo_id"] for n in r.get("noise_phenotypes", [])]
        shown = [p["hpo_id"] for p in pos]
        ungen = [p.get("source_hpo_id") or p["hpo_id"] if p.get("reason") == "generalized" else p["hpo_id"]
                 for p in pos]
        unspec = [p.get("source_hpo_id") or p["hpo_id"] if p.get("reason") == "specialized" else p["hpo_id"]
                  for p in pos]
        orig = [p.get("source_hpo_id") or p["hpo_id"] for p in pos]
        truth = orig + [m["hpo_id"] for m in r.get("missing_phenotypes", [])] + [
            u["hpo_id"] for u in r.get("unknown_phenotypes", [])]
        sets = {"as_exported": shown + noise, "no_noise": shown, "no_generalization": ungen + noise,
                "no_specialization": unspec + noise, "profile_terms_ungeneralized_no_noise": orig,
                "all_true_terms": sorted(set(truth))}
        for k, terms in sets.items():
            variants[k].append(Case(case_id=r["case_id"], cohort="sim", gene=gene, present=tuple(dict.fromkeys(terms))))
        ics["sim_profile_positives"] += [ic(t) for t in shown]
        ics["sim_noise"] += [ic(t) for t in noise]

cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for line in f:
        if not line.startswith("#"):
            cited.update(re.findall(r"PMID:(\d+)", line))
train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL)
uncited = [c for c in train if not {p.replace("PMID:", "") for p in c.pmids} & cited]
real_expl = [c.model_copy(update={"present": tuple(t for t in c.present if know.term_probability(c.gene, t) > 0)})
             for c in uncited]
real_expl = [c for c in real_expl if c.present]
ics["r1_train_present"] = [ic(t) for c in train for t in c.present]
ics["r1_train_explained"] = [ic(t) for c in train for t in c.present if know.term_probability(c.gene, t) > 0]

e0 = GenPheniaV3()
out = {"sim_cases": len(variants["as_exported"])}
for name, cases in list(variants.items()) + [("R1-train uncited", uncited),
                                              ("R1-train uncited, explained terms only", real_expl)]:
    s = harness.summarize(harness.run(e0, cases, view="present"))
    out[name] = {"n": len(cases), "mrr_in_vocab": round(s.get("gene_in_vocab", {}).get("mrr", s["all"]["mrr"]), 4),
                 "terms_per_case": round(statistics.mean(len(c.present) for c in cases), 2)}
out["mean_ic"] = {k: round(statistics.mean(v), 3) for k, v in ics.items() if v}
print(json.dumps(out, indent=1))
