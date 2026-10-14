"""Exploratory: E0 vs R1-R4 MRR by cited/uncited status and gene features, plus group concentration."""

import collections
import json
import os

import numpy as np

S = os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/"
V = "data/interim/v4/"
feat = json.load(open(S + "feat.json"))
runs = {
    "E0": "R0",
    "R1": "R1-179b7df65b",
    "R2": "R2-7530916138",
    "R3": "R3-bb65d5e066",
    "R4": "R4-5ea113ec1b",
}
R = {}
for k, d in runs.items():
    for fold in ("select", "fit"):
        for ln in open(f"{V}{d}/ranks/{fold}.ranks.jsonl"):
            x = json.loads(ln)
            R.setdefault((fold, x["case_id"]), {"meta": x})[k] = x["rank"]
rows = [
    {
        **v["meta"],
        **{k: v[k] for k in runs},
        **{kk: vv for kk, vv in feat.get(c, {}).items() if kk != "fold"},
        "fold": f,
        "cid": c,
    }
    for (f, c), v in R.items()
]


def rr(r):
    return 0.0 if r in (None, "inf") else 1.0 / float(r)


def mrr(sub, k):
    return np.mean([rr(x[k]) for x in sub]) if sub else float("nan")


def line(lbl, sub):
    g = len({x["group"] for x in sub})
    print(f"  {lbl:28} n={len(sub):5} g={g:4} " + " ".join(f"{k}={mrr(sub, k):.3f}" for k in runs))


for fold in ("select", "fit"):
    U = [x for x in rows if x["fold"] == fold and x["status"] == "uncited_e0_knowledge"]
    C = [x for x in rows if x["fold"] == fold and x["status"] == "cited_e0_knowledge"]
    print(f"== {fold}")
    line("cited", C)
    line("uncited", U)
    line("uncited OOV", [x for x in U if not x["gene_in_vocab"]])
    Ui = [x for x in U if x["gene_in_vocab"]]
    line("uncited inV", Ui)
    for lo, hi, bin_ in (
        (0, 0.25, "<25%"),
        (0.25, 0.5, "25-50%"),
        (0.5, 0.75, "50-75%"),
        (0.75, 1.01, ">=75%"),
    ):
        line(
            f" inV explained {bin_}",
            [x for x in Ui if x.get("explained") is not None and lo <= x["explained"] < hi],
        )
    for lo, hi, bin_ in ((0, 10, "<10 terms"), (10, 40, "10-39"), (40, 10**6, ">=40")):
        line(f" inV gene profile {bin_}", [x for x in Ui if lo <= x.get("gene_terms", 0) < hi])
    line(" inV gene has other FIT pubs", [x for x in Ui if x.get("fit_groups_same_gene", 0) > 0])
    line(" inV gene has no FIT pub", [x for x in Ui if x.get("fit_groups_same_gene", 0) == 0])
# group concentration on SELECT uncited
U = [x for x in rows if x["fold"] == "select" and x["status"] == "uncited_e0_knowledge"]
n = len(U)
for a, b in (("R2", "R1"), ("R4", "E0"), ("R1", "E0"), ("R4", "R1")):
    g = collections.defaultdict(float)
    for x in U:
        g[x["group"]] += (rr(x[a]) - rr(x[b])) / n
    tot = sum(g.values())
    top = sorted(g.items(), key=lambda kv: kv[1])
    sizes = collections.Counter(x["group"] for x in U)
    print(
        f"{a}-{b}: total {tot:+.4f}; 5 worst groups "
        + ", ".join(f"{k}({sizes[k]})={v:+.4f}" for k, v in top[:5])
        + "; 3 best "
        + ", ".join(f"{k}({sizes[k]})={v:+.4f}" for k, v in top[-3:])
    )
    wo = tot - sum(v for _, v in top[:5])
    print(
        f"   without 5 worst: {wo:+.4f}; "
        f"median group Δ {np.median(list(g.values())) * n / 1:+.4f} (patient-sum units)"
    )
sizes = collections.Counter(x["group"] for x in U)
print(
    "SELECT uncited largest groups",
    sizes.most_common(5),
    "share of patients top5",
    sum(c for _, c in sizes.most_common(5)) / n,
)
