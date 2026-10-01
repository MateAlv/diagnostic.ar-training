"""ANALYSIS-006: among explained terms (vs kb-v3), how many are the exact annotated term vs a strict ancestor?

R1-train uncited patients vs a simulated export (1 in 50 sample). Usage: python ... <export.jsonl.gz>
"""

import gzip
import hashlib
import json
import re
import sys
from collections import Counter

from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
K = kb.read(fetch_outputs(load_manifest("kb-v3"))[0])
know = GeneKnowledge(K, onto)
cache = {}


def annotated(gene):
    if gene not in cache:
        cache[gene] = {t for d in know.diseases(gene) for t in K["diseases"][d]["phenotypes"]}
    return cache[gene]


def tally(records):
    c = Counter()
    for gene, terms in records:
        if not know.diseases(gene):
            continue
        a = annotated(gene)
        for t in terms:
            t = onto.resolve(t) or t
            if know.term_probability(gene, t) > 0:
                c["exact" if t in a else "ancestor"] += 1
    n = c["exact"] + c["ancestor"]
    return {"explained_terms": n, "exact_share": round(c["exact"] / n, 3), "ancestor_share": round(c["ancestor"] / n, 3)}


cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for line in f:
        if not line.startswith("#"):
            cited.update(re.findall(r"PMID:(\d+)", line))
real = [(c.gene, c.present) for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL)
        if not {p.replace("PMID:", "") for p in c.pmids} & cited]
sim = []
with gzip.open(sys.argv[1], "rt") as f:
    for line in f:
        r = json.loads(line)
        if int(hashlib.sha256(r["case_id"].encode()).hexdigest(), 16) % 50 == 0:
            sim.append((r["gene"], r["present"]))
print(json.dumps({"r1_train_uncited": tally(real), "simulated": tally(sim)}, indent=1))
