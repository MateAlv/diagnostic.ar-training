"""ANALYSIS-003: information content and E0 damage by noise type (sim) vs R1-train unexplained terms.

R1-train only. Usage: python scripts/analysis/noise_types.py <rich cases.jsonl> [keep_one_in]
"""

import hashlib
import json
import math
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
ic = lambda t: -math.log(max(cnt.get(onto.resolve(t) or t, 0), 1) / N)  # noqa: E731
q = lambda v: [round(statistics.quantiles(v, n=4)[i], 2) for i in range(3)] if len(v) > 3 else None  # noqa: E731

vocab_ic, related_ic, cases = [], [], {"as_exported": [], "no_vocab_noise": [], "no_related_noise": []}
with open(sys.argv[1]) as f:
    for line in f:
        cid = line[13:80].split('"')[0]
        if int(hashlib.sha256(cid.encode()).hexdigest(), 16) % keep:
            continue
        r = json.loads(line)
        pos = [p["hpo_id"] for p in r["positive_phenotypes"]]
        voc = [n["hpo_id"] for n in r.get("noise_phenotypes", []) if n.get("reason") != "related"]
        rel = [n["hpo_id"] for n in r.get("noise_phenotypes", []) if n.get("reason") == "related"]
        vocab_ic += [ic(t) for t in voc]
        related_ic += [ic(t) for t in rel]
        g = r["target"]["gene"]
        for k, terms in (("as_exported", pos + voc + rel), ("no_vocab_noise", pos + rel), ("no_related_noise", pos + voc)):
            cases[k].append(Case(case_id=r["case_id"], cohort="sim", gene=g, present=tuple(dict.fromkeys(terms))))

train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL)
unexpl, spec = [], []
for c in train:
    if not know.diseases(c.gene):
        continue
    annotated = {t for d in know.diseases(c.gene) for t in K["diseases"][d]["phenotypes"]}
    for t in c.present:
        if know.term_probability(c.gene, t) == 0:
            (spec if onto.ancestors(onto.resolve(t) or t) & annotated else unexpl).append(ic(t))
e0 = GenPheniaV3()
out = {
    "ic_quartiles": {"sim_vocab_noise": q(vocab_ic), "sim_related_noise": q(related_ic),
                     "r1_train_unexplained": q(unexpl), "r1_train_more_specific": q(spec)},
    "ic_mean": {"sim_vocab_noise": round(statistics.mean(vocab_ic), 2),
                "sim_related_noise": round(statistics.mean(related_ic), 2),
                "r1_train_unexplained": round(statistics.mean(unexpl), 2),
                "r1_train_more_specific": round(statistics.mean(spec), 2)},
    "noise_terms": {"vocab": len(vocab_ic), "related": len(related_ic)},
}
for k, cs in cases.items():
    s = harness.summarize(harness.run(e0, cs, view="present"))
    out[f"e0_{k}"] = round(s.get("gene_in_vocab", {}).get("mrr", s["all"]["mrr"]), 4)
print(json.dumps(out, indent=1))
