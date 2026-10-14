"""Exploratory: publication-weighted MRR of R1-R4 vs E0 on uncited in-vocab patients, group bootstrap."""

import json

import numpy as np

V = "data/interim/v4/"
runs = {
    "E0": "R0",
    "R1": "R1-179b7df65b",
    "R2": "R2-7530916138",
    "R3": "R3-bb65d5e066",
    "R4": "R4-5ea113ec1b",
}
rng = np.random.default_rng(0)


def load(d, fold):
    return {(x := json.loads(ln))["case_id"]: x for ln in open(f"{V}{d}/ranks/{fold}.ranks.jsonl")}


def rr(r):
    return 0.0 if r == "inf" else 1 / float(r)


def gm(d, fold, U, base, groups, gi):
    r = load(d, fold)
    s = np.zeros(len(groups))
    n = np.zeros(len(groups))
    for c in U:
        s[gi[base[c]["group"]]] += rr(r[c]["rank"])
        n[gi[base[c]["group"]]] += 1
    return s / n


for fold in ("select", "fit"):
    base = load("R0", fold)
    U = [c for c, x in base.items() if x["status"] == "uncited_e0_knowledge" and x["gene_in_vocab"]]
    groups = sorted({base[c]["group"] for c in U})
    gi = {g: i for i, g in enumerate(groups)}

    e0 = gm("R0", fold, U, base, groups, gi)
    B = rng.integers(0, len(groups), (2000, len(groups)))
    print(
        f"== {fold} uncited in-vocab, publication-weighted "
        f"(each of {len(groups)} groups weight 1): E0 {e0.mean():.3f}"
    )
    for k, d in runs.items():
        if k == "E0":
            continue
        v = gm(d, fold, U, base, groups, gi)
        dd = v - e0
        bs = dd[B].mean(1)
        lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
        better, worse = int((dd > 1e-9).sum()), int((dd < -1e-9).sum())
        print(
            f"  {k}: {v.mean():.3f}  Δ {dd.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]  "
            f"groups better/worse {better}/{worse}"
        )
