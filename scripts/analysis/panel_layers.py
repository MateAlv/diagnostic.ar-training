"""ANALYSIS-003: literature panel error by layer (R1-train reported, simulated true, simulated reported).

R1-train only. Usage: python scripts/analysis/panel_layers.py <sim export.jsonl.gz> [min_real_patients]
"""

import csv
import gzip
import json
import sys
from collections import defaultdict

from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
min_real = int(sys.argv[2]) if len(sys.argv) > 2 else 10


def closure(terms):
    out = set()
    for t in terms:
        t = onto.resolve(t) or t
        out.add(t)
        out |= onto.ancestors(t)
    return out


rows = [r for r in csv.DictReader(open("data/realism/literature-panel-v2.tsv"), delimiter="\t")
        if r["independent"] == "true"]
genes = {r["gene"] for r in rows}
real = defaultdict(list)
for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
    if c.gene in genes:
        real[c.gene].append(closure(c.present))
sim_p, sim_t = defaultdict(list), defaultdict(list)
with gzip.open(sys.argv[1], "rt") as f:
    for line in f:
        r = json.loads(line)
        if r["gene"] in genes:
            sim_p[r["gene"]].append(closure(r["present"]))
            sim_t[r["gene"]].append(closure(r["true_present"]))


def mae(layer, subset):
    errs = []
    for r in subset:
        sets = layer.get(r["gene"])
        if not sets:
            continue
        t = onto.resolve(r["hpo_id"]) or r["hpo_id"]
        errs.append(abs(sum(t in s for s in sets) / len(sets) - float(r["prevalence"])))
    return round(sum(errs) / len(errs), 3) if errs else None, len(errs)


with_real = [r for r in rows if len(real.get(r["gene"], [])) >= min_real]
print(json.dumps({
    "rows_independent": len(rows),
    f"rows_genes_with_>={min_real}_r1_train": len(with_real),
    "on_those_rows": {"r1_train_reported": mae(real, with_real), "sim_true": mae(sim_t, with_real),
                      "sim_reported": mae(sim_p, with_real)},
    "all_independent_rows": {"sim_true": mae(sim_t, rows), "sim_reported": mae(sim_p, rows)},
}, indent=1))
