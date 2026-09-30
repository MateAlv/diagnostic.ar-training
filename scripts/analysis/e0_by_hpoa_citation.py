# ANALYSIS-002. Usage: python scripts/analysis/e0_by_hpoa_citation.py (R1-train only)
import json, re
import numpy as np
from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.registry import Purpose, open_source
cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as f:
    for line in f:
        if line.startswith("#"): continue
        cited.update(re.findall(r"PMID:(\d+)", line))
train = {c.case_id: c for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)}
groups = {"cited": [], "not_cited": []}
for line in open("results/EXP-000/r1-v1-train__genphenia-v3.0__all.ranks.jsonl"):
    r = json.loads(line)
    if not r["gene_in_vocab"] or r["case_id"] not in train: continue
    pm = {p.replace("PMID:", "") for p in train[r["case_id"]].pmids}
    groups["cited" if pm & cited else "not_cited"].append(1.0 / r["rank"] if r["rank"] else 0.0)
for k, v in groups.items():
    print(k, len(v), round(float(np.mean(v)), 3))
