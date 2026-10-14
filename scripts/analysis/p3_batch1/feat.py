"""Exploratory: per-patient features (gene-profile coverage, FIT-publication overlap) for p3-b1."""

import collections
import json
import os

from diagnostic_ar_training.sim4 import load_knowledge
from diagnostic_ar_training.v4 import patients as P

K = load_knowledge()
onto = K.ontology
fit, sel = P.load("fit"), P.load("select")
fit_gene_groups = collections.defaultdict(set)
for p in fit:
    fit_gene_groups[p.case.gene].add(p.group)
clos = {}


def closure(g):
    if g not in clos:
        s = set()
        for t in K.profile(g):
            s |= {t} | set(onto.ancestors(t))
        clos[g] = s
    return clos[g]


out = {}
for name, pts in (("fit", fit), ("select", sel)):
    for p in pts:
        Q = {r for r in (onto.resolve(x) for x in p.case.present) if r and K.is_finding(r)}
        g = p.case.gene
        c = closure(g)
        prof = K.profile(g)
        out[p.case_id] = dict(
            fold=name,
            n_q=len(Q),
            explained=(len(Q & c) / len(Q)) if Q else None,
            exact=(len(Q & prof) / len(Q)) if Q else None,
            gene_terms=len(prof),
            fit_groups_same_gene=len(fit_gene_groups[g] - {p.group}),
        )
json.dump(out, open(os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/feat.json", "w"))
print(len(out))
