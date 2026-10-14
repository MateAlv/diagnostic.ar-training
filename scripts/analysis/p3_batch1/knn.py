"""Exploratory: can real training patients (other publications) add to E0?

kNN over FIT patients, fused with E0.
SELECT queries use FIT memory; FIT queries use FIT memory minus their own group. lambda tuned on FIT only."""

import collections
import math
import os
import pickle

import numpy as np
import scipy.sparse as sp

from diagnostic_ar_training.sim4 import load_knowledge
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3
from diagnostic_ar_training.v4 import patients as P

S = os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/"
K = load_knowledge()
onto = K.ontology
fit, sel = P.load("fit"), P.load("select")


def findings(p):
    return {r for r in (onto.resolve(x) for x in p.case.present) if r and K.is_finding(r)}


def clos(Q):
    s = set()
    for t in Q:
        s |= {t} | {a for a in onto.ancestors(t) if K.is_finding(a)}
    return s


def ic(t):
    return -math.log(max(K.disease_counts.get(t, 0), 1) / K.n_diseases)


allp = fit + sel
C = [clos(findings(p)) for p in allp]
vocab = {t: i for i, t in enumerate(sorted(set().union(*C)))}
w = np.array([ic(t) for t in sorted(vocab, key=vocab.get)])
rows, cols, vals = [], [], []
for i, c in enumerate(C):
    for t in c:
        rows.append(i)
        cols.append(vocab[t])
        vals.append(w[vocab[t]])
X = sp.csr_matrix((vals, (rows, cols)), shape=(len(allp), len(vocab)))
norm = np.sqrt(np.asarray(X.multiply(X).sum(1)).ravel()) + 1e-9
nf = len(fit)
Xf = X[:nf]
sim = (X @ Xf.T).toarray() / norm[:, None] / norm[None, :nf]
cache = S + "e0probs.pkl"
if os.path.exists(cache):
    e0p, genes = pickle.load(open(cache, "rb"))
else:
    e0 = GenPheniaV3()
    genes = list(e0.genes)
    e0p = []
    for p in allp:
        s = e0.score(p.case)
        e0p.append(None if s.probs is None else np.asarray(s.probs, dtype=np.float32))
    pickle.dump((e0p, genes), open(cache, "wb"))
gidx = {g.upper(): i for i, g in enumerate(genes)}
fit_gene = np.array([gidx.get(p.case.gene.upper(), -1) for p in fit])
fit_group = np.array([p.group for p in fit])
G = len(genes)


def knn_scores(i):
    s = sim[i].copy()
    if i < nf:
        s[fit_group == allp[i].group] = -1
    out = np.full(G, 0.0)
    ok = fit_gene >= 0
    np.maximum.at(out, fit_gene[ok], np.clip(s[ok], 0, None))
    return out


def rank(score, g):
    return 1 + int((score > score[g]).sum())


recs = []
for i, p in enumerate(allp):
    g = gidx.get(p.case.gene.upper())
    if g is None or e0p[i] is None or p.status != "uncited_e0_knowledge":
        continue
    recs.append(
        dict(
            i=i,
            fold="fit" if i < nf else "select",
            group=p.group,
            g=g,
            lp=np.log(e0p[i] + 1e-12),
            kn=knn_scores(i),
            has_mem=bool((fit_gene[(fit_group != p.group)] == g).any()),
        )
    )
lams = [0, 0.5, 1, 2, 4, 8, 16, 32]


def mrrs(sub, lam):
    rr = np.array([1 / rank(r["lp"] + lam * r["kn"], r["g"]) for r in sub])
    grp = np.array([r["group"] for r in sub])
    gw = np.mean([rr[grp == g].mean() for g in set(grp)])
    return rr.mean(), gw, rr, grp


for fold in ("fit", "select"):
    sub = [r for r in recs if r["fold"] == fold]
    knn_only = np.mean([1 / rank(r["kn"] + 1e-6 * r["lp"], r["g"]) for r in sub])
    n_groups = len({r["group"] for r in sub})
    n_mem = sum(r["has_mem"] for r in sub)
    print(
        f"== {fold} uncited inV n={len(sub)} groups={n_groups} with same-gene memory {n_mem}; "
        f"kNN alone MRR {knn_only:.3f}"
    )
    for lam in lams:
        a, b, _, _ = mrrs(sub, lam)
        print(f"  lam {lam:5}: MRR {a:.4f} pub-weighted {b:.4f}")
# pick lambda on FIT (pub-weighted), report SELECT with group bootstrap CI
fsub = [r for r in recs if r["fold"] == "fit"]
ssub = [r for r in recs if r["fold"] == "select"]
best = max(lams, key=lambda lam: mrrs(fsub, lam)[1])
print("lambda chosen on FIT:", best)
rng = np.random.default_rng(0)
for lab, w in (("patient", False), ("publication", True)):
    _, _, r0, grp = mrrs(ssub, 0)
    _, _, r1, _ = mrrs(ssub, best)
    gs = sorted(set(grp))
    d = np.array([(r1 - r0)[grp == g].sum() for g in gs])
    n = np.array([(grp == g).sum() for g in gs])
    B = rng.integers(0, len(gs), (2000, len(gs)))
    bs = (d[B].sum(1) / n[B].sum(1)) if not w else (d / n)[B].mean(1)
    pt = d.sum() / n.sum() if not w else (d / n).mean()
    lo, hi = np.percentile(bs, 2.5), np.percentile(bs, 97.5)
    print(
        f"SELECT {lab}-weighted Δ vs E0 {pt:+.4f} [{lo:+.4f}, {hi:+.4f}]; "
        f"helped {(r1 > r0).sum()} harmed {(r1 < r0).sum()}"
    )
print("---- controls")


# gene prior: number of other FIT publications with the gene (no phenotype)
def prior(r):
    i = r["i"]
    mask = (fit_group != allp[i].group) & (fit_gene >= 0)
    pubs = collections.defaultdict(set)
    for g, grp in zip(fit_gene[mask], fit_group[mask], strict=True):
        pubs[g].add(grp)
    out = np.zeros(G)
    for g, s in pubs.items():
        out[g] = math.log1p(len(s))
    return out


for r in recs:
    r["pr"] = prior(r)


def mrr_with(sub, f):
    rr = np.array([1 / rank(f(r), r["g"]) for r in sub])
    grp = np.array([r["group"] for r in sub])
    return rr.mean(), np.mean([rr[grp == g].mean() for g in set(grp)])


for fold in ("fit", "select"):
    sub = [r for r in recs if r["fold"] == fold]
    for lam in (0.5, 1, 2, 4, 8):
        a, b = mrr_with(sub, lambda r, lam=lam: r["lp"] + lam * r["pr"])
        print(f"{fold} E0+prior lam {lam}: MRR {a:.4f} pub-w {b:.4f}")
    for lab, cond in (("gene has memory", True), ("no memory", False)):
        s2 = [r for r in sub if r["has_mem"] == cond]
        a0, b0 = mrr_with(s2, lambda r: r["lp"])
        a1, b1 = mrr_with(s2, lambda r: r["lp"] + 32 * r["kn"])
        a2, b2 = mrr_with(s2, lambda r: r["lp"] + 4 * r["kn"])
        print(
            f"{fold} {lab:16} n={len(s2)}: E0 {a0:.3f}/{b0:.3f}  +kNN32 {a1:.3f}/{b1:.3f}  "
            f"+kNN4 {a2:.3f}/{b2:.3f} (patient/pub)"
        )
