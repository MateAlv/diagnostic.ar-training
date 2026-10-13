"""Q1 (E0 decomposition), Q3 (training-free similarity vs E0) on p2-v1 train+dev."""

import json
import sys

import numpy as np

from common import DATA, Boot, load, summary

genes, meta = load()
N = len(meta)
groups = [m["group"] for m in meta]
B = Boot(groups)
cited = np.array([m["cited"] for m in meta])
in0125 = np.array([m["in_0125"] for m in meta])
inv = np.array([m["in_vocab"] for m in meta])
inkb = np.array([m["sim"]["gene_in_kb"] for m in meta])
dev = np.array([m["part"] == "dev" for m in meta])
e0 = [m["e0_rank"] for m in meta]
ft = [m["ft_rank"] for m in meta]

SIMS = [f"{lvl}|{k}" for lvl in ("gene", "disease") for k in ("resnik_pg", "resnik_sym", "heur_exact", "heur_prop")]
sim_all = {s: [m["sim"].get(f"{s}|rank_all") for m in meta] for s in SIMS}
sim_e0v = {s: [m["sim"].get(f"{s}|rank_e0vocab") for m in meta] for s in SIMS}

era = np.array([("<=0.1.25" if a else "post-0.1.25") + ("/cited" if c else "/uncited") for a, c in zip(in0125, cited)])
out = {"n": N}


def slice_row(name, sel, systems):
    r = {"slice": name, "n": int(sel.sum()), "pubs": int(len({groups[i] for i in np.where(sel)[0]}))}
    for sname, ranks in systems.items():
        r[sname] = summary(ranks, sel)
    return r


slices = {
    "all": np.ones(N, bool),
    "cited": cited,
    "uncited": ~cited,
    "cited & inV": cited & inv,
    "cited & OOV": cited & ~inv,
    "uncited & inV": ~cited & inv,
    "uncited & OOV": ~cited & ~inv,
}
for e in sorted(set(era)):
    slices[e] = era == e
    slices[e + " & inV"] = (era == e) & inv
    slices[e + " & OOV"] = (era == e) & ~inv
for p in ("train", "dev"):
    pm = dev if p == "dev" else ~dev
    slices[f"{p}: cited"] = pm & cited
    slices[f"{p}: uncited"] = pm & ~cited
    slices[f"{p}: uncited & inV"] = pm & ~cited & inv

systems = {"E0": e0, "ft": ft}
for s in SIMS:
    systems[s] = sim_all[s]
out["slices"] = [slice_row(k, v, systems) for k, v in slices.items()]
out["inkb_share"] = {k: float(inkb[v].mean()) for k, v in slices.items()}

# Q1 decomposition
rec = np.array([0 if x is None else 1 / x for x in e0])
dec = {}
for lab, c_sel, u_sel in (("cited vs uncited", cited, ~cited),
                          ("<=0.1.25/cited vs post/uncited", era == "<=0.1.25/cited", era == "post-0.1.25/uncited")):
    mc, mu = rec[c_sel].mean(), rec[u_sel].mean()
    mci, mui = rec[c_sel & inv].mean(), rec[u_sel & inv].mean()
    fc, fu = inv[c_sel].mean(), inv[u_sel].mean()
    gap = mc - mu
    # order A: fix vocab first (uncited at full coverage = mui), then generalisation
    vocabA = mui - mu
    genA = mc - mui
    # order B: generalisation at the uncited coverage, then vocabulary
    genB = fu * (mci - mui)
    vocabB = gap - genB
    dec[lab] = dict(mrr_cited=mc, mrr_uncited=mu, mrr_cited_inV=mci, mrr_uncited_inV=mui, cov_cited=fc,
                    cov_uncited=fu, gap=gap, vocab_A=vocabA, gen_A=genA, vocab_B=vocabB, gen_B=genB,
                    ci_uncited_inV=B.ci_mean(rec, u_sel & inv), ci_uncited=B.ci_mean(rec, u_sel))
out["q1_decomposition"] = dec

# Q3 paired comparisons: sim (all KB genes) vs E0, and vs ft
cmp = {}
for s in SIMS:
    for name, sel in (("all", np.ones(N, bool)), ("cited", cited), ("uncited", ~cited),
                      ("uncited & inV", ~cited & inv), ("uncited & OOV", ~cited & ~inv),
                      ("cited & inV", cited & inv), ("post/uncited", era == "post-0.1.25/uncited"),
                      ("post/uncited & inV", (era == "post-0.1.25/uncited") & inv)):
        cmp[f"{s} vs E0 | {name}"] = B.compare(e0, sim_all[s], sel)
    cmp[f"{s}[E0 vocab only] vs E0 | uncited & inV"] = B.compare(e0, sim_e0v[s], ~cited & inv)
    cmp[f"{s}[E0 vocab only] vs E0 | cited & inV"] = B.compare(e0, sim_e0v[s], cited & inv)
for name, sel in (("all", np.ones(N, bool)), ("cited", cited), ("uncited", ~cited)):
    cmp[f"ft vs E0 | {name}"] = B.compare(e0, ft, sel)
out["q3_compare"] = cmp
json.dump(out, open(DATA / "q13.json", "w"), indent=1)

print("== Q1 decomposition")
for k, v in dec.items():
    print(k, {a: round(b, 4) if isinstance(b, float) else b for a, b in v.items()})
print("== slices (MRR / top1 / top10)")
show = ["E0", "ft", "gene|resnik_pg", "gene|resnik_sym", "disease|resnik_pg", "disease|resnik_sym", "gene|heur_exact",
        "gene|heur_prop", "disease|heur_exact", "disease|heur_prop"]
for r in out["slices"]:
    print(f"{r['slice']:32s} n={r['n']:5d} pubs={r['pubs']:4d} inKB={out['inkb_share'][r['slice']]:.2f} " + " ".join(
        f"{s.split('|')[-1][:10] if '|' in s else s}:{r[s]['mrr']:.3f}/{r[s]['top1']:.2f}/{r[s]['top10']:.2f}" for s in show))
print("== Q3 compare")
for k, v in cmp.items():
    print(f"{k:60s} n={v['n']} pubs={v['pubs']} {v['a_mrr']:.3f}->{v['b_mrr']:.3f} d={v['delta']:+.4f} "
          f"[{v['ci'][0]:+.4f},{v['ci'][1]:+.4f}] help={v['helped']:.2f} harm={v['harmed']:.2f}")
