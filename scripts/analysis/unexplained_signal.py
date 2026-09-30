"""ANALYSIS-004: do real patients' unexplained terms carry gene signal for E0? Compared with simulated noise.

R1-train only. Usage: python scripts/analysis/unexplained_signal.py <rich cases.jsonl> [keep_one_in]
"""

import hashlib
import json
import re
import sys

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
K = kb.read(fetch_outputs(load_manifest("kb-v3"))[0])
know = GeneKnowledge(K, onto)
cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for line in f:
        if not line.startswith("#"):
            cited.update(re.findall(r"PMID:(\d+)", line))
real_unexpl, real_expl = [], []
for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
    if {p.replace("PMID:", "") for p in c.pmids} & cited or not know.diseases(c.gene):
        continue
    u = tuple(t for t in c.present if know.term_probability(c.gene, onto.resolve(t) or t) == 0)
    e = tuple(t for t in c.present if know.term_probability(c.gene, onto.resolve(t) or t) > 0)
    if u:
        real_unexpl.append(c.model_copy(update={"present": u}))
    if e:
        real_expl.append(c.model_copy(update={"present": e}))
sim_voc, sim_rel = [], []
with open(sys.argv[1]) as f:
    for line in f:
        r = json.loads(line)
        if int(hashlib.sha256(r["case_id"].encode()).hexdigest(), 16) % keep:
            continue
        g = r["target"]["gene"]
        voc = tuple(n["hpo_id"] for n in r.get("noise_phenotypes", []) if n.get("reason") != "related")
        rel = tuple(n["hpo_id"] for n in r.get("noise_phenotypes", []) if n.get("reason") == "related")
        if voc:
            sim_voc.append(Case(case_id=r["case_id"], cohort="sim", gene=g, present=voc))
        if rel:
            sim_rel.append(Case(case_id=r["case_id"], cohort="sim", gene=g, present=rel))
e0 = GenPheniaV3()
out = {}
for name, cs in (("real uncited: unexplained terms only", real_unexpl), ("real uncited: explained terms only", real_expl),
                 ("sim: vocabulary noise only", sim_voc), ("sim: related noise only", sim_rel)):
    s = harness.summarize(harness.run(e0, cs, view="present"))
    g = s.get("gene_in_vocab", s["all"])
    out[name] = {"n": len(cs), "mrr_in_vocab": round(g["mrr"], 4),
                 "top10": round(g.get("top10", g.get("hit@10", float("nan"))), 4) if isinstance(g, dict) else None}
print(json.dumps(out, indent=1))
