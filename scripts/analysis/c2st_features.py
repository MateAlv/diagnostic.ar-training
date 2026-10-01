"""ANALYSIS-005: which source-neutral features separate simulated from real R1-train patients (G2d)?

R1-train only. One gene-matched simulated case per real patient; univariate AUC per feature.
Usage: python scripts/analysis/c2st_features.py <export.jsonl.gz> [seed]
"""

import gzip
import json
import random
import sys
from collections import defaultdict

import numpy as np
from scipy.stats import rankdata

from diagnostic_ar_training import splits
from diagnostic_ar_training.eval import realism as RZ
from diagnostic_ar_training.knowledge import report_model as R
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb as kb_mod
from diagnostic_ar_training.rerank.features import GeneKnowledge

seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
kb = kb_mod.read(fetch_outputs(load_manifest("kb-v5"))[0])
know = GeneKnowledge(kb, onto)
ann, nd = R.annotation_counts(kb, onto)
F = RZ.CaseFeatures(onto, ann, nd, know)
train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL)
genes = {c.gene.upper() for c in train}
sim = defaultdict(list)
with gzip.open(sys.argv[1], "rt") as f:
    for line in f:
        r = json.loads(line)
        if r["gene"].upper() in genes:
            sim[r["gene"].upper()].append(r["present"])


def roc_auc_score(y, x):
    r = rankdata(x)
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    return (r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


rng = random.Random(seed)
Xr, Xs = [], []
for c in train:
    pool = sim.get(c.gene.upper())
    if not pool:
        continue
    Xr.append(F(c.gene, c.present))
    Xs.append(F(c.gene, rng.choice(pool)))
Xr, Xs = np.array(Xr), np.array(Xs)
y = np.r_[np.zeros(len(Xr)), np.ones(len(Xs))]
X = np.r_[Xr, Xs]
out = []
for i, name in enumerate(F.names()):
    col = X[:, i]
    if col.std() == 0:
        continue
    auc = roc_auc_score(y, col)
    out.append({"feature": name, "auc": round(float(auc), 3), "sep": round(abs(auc - 0.5), 3),
                "real_mean": round(float(Xr[:, i].mean()), 3), "sim_mean": round(float(Xs[:, i].mean()), 3)})
out.sort(key=lambda d: -d["sep"])
for k, label in ((onto.labels.get(d["feature"].split(":", 1)[1], ""), d) for d in out if d["feature"].startswith("system:")):
    label["label"] = k
print(json.dumps({"pairs": len(Xr), "top": out[:15]}, indent=1))
