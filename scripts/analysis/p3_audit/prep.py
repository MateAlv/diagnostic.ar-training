"""Phase 3 error analysis, step 1: p2-v1 train+dev patients, eras, E0 full probabilities, ft-v1.1 ranks.

Only non-sealed parts are loaded (splits.load_part on p2-v1 train and dev).
Usage (repo root): PYTHONPATH=src .venv/bin/python <this> <out_dir>
"""

import json
import pickle
import sys
from pathlib import Path

import numpy as np

from diagnostic_ar_training import splits
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.splits import Part
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

train = splits.load_part("p2-v1", Part.TRAIN, Purpose.EVAL)
dev = splits.load_part("p2-v1", Part.DEV, Purpose.EVAL)
cases = train + dev
part = ["train"] * len(train) + ["dev"] * len(dev)
groups = splits._components(cases)

release = splits.release_index(open_source("phenopacket_store_0_1_25", Purpose.KB))
pm25 = set().union(*release.values())
e0_cited = splits.cited_pmids(open_source("hpo_annotations_2025_11_24", Purpose.KB))

e0 = GenPheniaV3()
genes = list(e0.genes)
gidx = {g: i for i, g in enumerate(genes)}
P = np.zeros((len(cases), len(genes)), dtype=np.float64)
scorable = np.zeros(len(cases), bool)
for i, c in enumerate(cases):
    s = e0.score(c)
    if s.probs is not None:
        P[i] = s.probs
        scorable[i] = True
logP = np.log(np.maximum(P, 1e-300)).astype(np.float32)
np.save(OUT / "e0_logp.npy", logP)

ft = {}
for p in ("train", "dev"):
    for line in open(f"results/EXP-P-003/ft-v1.1-c1-lin-all-ens/r1-v1-{p}.ranks.jsonl"):
        r = json.loads(line)
        ft[r["case_id"]] = r["rank"]

meta = []
for i, c in enumerate(cases):
    pm = set(c.pmids)
    t = gidx.get(c.gene, -1)
    if t >= 0 and scorable[i]:
        pt = P[i, t]
        rank = 1 + (P[i] > pt).sum() + 0.5 * ((P[i] == pt).sum() - 1)
    else:
        rank = None
    meta.append(
        dict(
            case_id=c.case_id,
            part=part[i],
            group=groups[c.case_id],
            gene=c.gene,
            pmids=sorted(pm),
            present=list(c.present),
            excluded=list(c.excluded),
            sex=str(c.sex),
            age=c.age_years,
            onset=c.onset_years,
            disease_ids=list(c.disease_ids),
            cited=bool(pm & e0_cited),
            in_0125=bool(pm & pm25),
            in_vocab=t >= 0,
            scorable=bool(scorable[i]),
            e0_rank=None if rank is None else float(rank),
            ft_rank=ft.get(c.case_id),
        )
    )
pickle.dump({"genes": genes, "meta": meta}, open(OUT / "cases.pkl", "wb"))
rr = np.array([0 if m["e0_rank"] is None else 1 / m["e0_rank"] for m in meta])
print("cases", len(cases), "train", len(train), "dev", len(dev), "groups", len(set(groups.values())))
print("E0 MRR", rr.mean(), "ft missing", sum(m["ft_rank"] is None for m in meta))
