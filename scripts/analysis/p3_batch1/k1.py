"""PHASE3 §2e K1: real-patient memory fused with E0, phenotype evidence only (no cohort gene prior).

Memory = FIT patients. A query's gene score is its best IC-cosine similarity to that gene's memory patients
from other publications, calibrated per gene against the best similarity that patients of *other* genes reach
(z-score), so a gene with many memory patients gains nothing from their number alone. Fused as
log p_E0 + lambda * max(0, z - threshold), both chosen on FIT (own group left out). Popularity control: each
query's phenotype is swapped for another query's of the same fold, keeping its true gene.
Reads `$P3_B1_DATA/e0probs.pkl` (written by knn.py). Capped MRR as in v4.report (10 patients per publication).
"""

import collections
import math
import os
import pickle

import numpy as np
import scipy.sparse as sp

from diagnostic_ar_training.sim4 import load_knowledge
from diagnostic_ar_training.v4 import patients as P
from diagnostic_ar_training.v4.report import CAP

DATA = os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/"
LAMBDAS = (0, 0.25, 0.5, 1, 2, 4, 8, 16)
THRESHOLDS = (0, 1, 2, 3, 4)
UNCITED = "uncited_e0_knowledge"

K = load_knowledge()
onto = K.ontology
fit, sel = P.load("fit"), P.load("select")
allp = fit + sel
nf = len(fit)


def closure(p):
    out = set()
    for x in p.case.present:
        t = onto.resolve(x)
        if t and K.is_finding(t):
            out |= {t} | {a for a in onto.ancestors(t) if K.is_finding(a)}
    return out


def ic(t):
    return -math.log(max(K.disease_counts.get(t, 0), 1) / K.n_diseases)


C = [closure(p) for p in allp]
vocab = {t: i for i, t in enumerate(sorted(set().union(*C)))}
rows = [i for i, c in enumerate(C) for _ in c]
cols = [vocab[t] for c in C for t in c]
vals = [ic(t) for c in C for t in c]
X = sp.csr_matrix((vals, (rows, cols)), shape=(len(allp), len(vocab)))
norm = np.sqrt(np.asarray(X.multiply(X).sum(1)).ravel()) + 1e-9
sim = (X @ X[:nf].T).toarray() / norm[:, None] / norm[None, :nf]

e0p, genes = pickle.load(open(DATA + "e0probs.pkl", "rb"))
gidx = {g.upper(): i for i, g in enumerate(genes)}
G = len(genes)
fit_gene = np.array([gidx.get(p.case.gene.upper(), -1) for p in fit])
fit_group = np.array([p.group for p in fit])
members = collections.defaultdict(list)
for j, g in enumerate(fit_gene):
    if g >= 0:
        members[g].append(j)

# Per-gene null: best similarity of FIT patients of other genes (and other publications) to the gene's memory.
null = {}
for g, js in members.items():
    js = np.array(js)
    others = np.where(fit_gene != g)[0]
    best = np.full(others.size, -1.0)
    for j in js:
        ok = fit_group[others] != fit_group[j]
        best = np.where(ok, np.maximum(best, sim[others, j]), best)
    best = best[best >= 0]
    null[g] = (best.mean(), best.std() + 1e-6) if best.size > 1 else (1.0, 1.0)


def evidence(i, phen):
    """z-scores of every gene for query i, using the phenotype of patient `phen` (= i unless swapped)."""
    out = np.zeros(G)
    for g, js in members.items():
        js = [j for j in js if fit_group[j] != allp[i].group]
        if not js:
            continue
        mu, sd = null[g]
        out[g] = (sim[phen, js].max() - mu) / sd
    return out


def rank(score, g):
    return 1 + int((score > score[g]).sum())


recs = []
for i, p in enumerate(allp):
    if p.status != UNCITED:
        continue
    g = gidx.get(p.case.gene.upper())
    lp = None if (g is None or e0p[i] is None) else np.log(e0p[i] + 1e-12)
    recs.append({"i": i, "fold": "fit" if i < nf else "select", "group": p.group, "g": g, "lp": lp})
rng = np.random.default_rng(0)
for fold in ("fit", "select"):
    idx = [r["i"] for r in recs if r["fold"] == fold]
    perm = dict(zip(idx, rng.permutation(idx), strict=True))
    for r in recs:
        if r["fold"] == fold and r["lp"] is not None:
            r["z"] = evidence(r["i"], r["i"])
            r["z_swap"] = evidence(r["i"], perm[r["i"]])


def rr(r, lam, key="z", t=0):
    if r["lp"] is None:
        return 0.0
    return 1 / rank(r["lp"] + lam * np.clip(r[key] - t, 0, None), r["g"])


def capped(sub, vals):
    groups = np.array([r["group"] for r in sub])
    _, inv, n = np.unique(groups, return_inverse=True, return_counts=True)
    w = np.minimum(n, CAP)[inv] / n[inv]
    return float(np.sum(w * vals) / np.sum(w)), w, inv


def delta_ci(sub, new, base):
    point, w, inv = capped(sub, new - base)
    num, den = np.bincount(inv, weights=w * (new - base)), np.bincount(inv, weights=w)
    picks = np.random.default_rng(0).integers(0, num.size, (2000, num.size))
    lo, hi = np.percentile(num[picks].sum(1) / den[picks].sum(1), [2.5, 97.5])
    return point, lo, hi


fit_inv = [r for r in recs if r["fold"] == "fit" and r["lp"] is not None]
grid = [(lam, t) for lam in LAMBDAS for t in THRESHOLDS]
scores = {k: capped(fit_inv, np.array([rr(r, *k[:1], t=k[1]) for r in fit_inv]))[0] for k in grid}
for t in THRESHOLDS:
    print(f"FIT capped MRR, threshold {t}:", {lam: round(scores[(lam, t)], 4) for lam in LAMBDAS})
best, best_t = max(grid, key=scores.get)
print("chosen on FIT: lambda", best, "threshold", best_t)
for fold in ("fit", "select"):
    for label, keep in (("uncited", lambda r: True), ("uncited in-vocab", lambda r: r["lp"] is not None)):
        sub = [r for r in recs if r["fold"] == fold and keep(r)]
        base = np.array([rr(r, 0) for r in sub])
        for key in ("z", "z_swap"):
            new = np.array([rr(r, best, key, best_t) for r in sub])
            d, lo, hi = delta_ci(sub, new, base)
            print(
                f"{fold:6} {label:16} {key:6} E0 {capped(sub, base)[0]:.4f} -> {capped(sub, new)[0]:.4f}"
                f"  Δ {d:+.4f} [{lo:+.4f}, {hi:+.4f}]"
                f"  helped {(new > base).sum()} harmed {(new < base).sum()}"
                f"  lost top-1 {((base == 1) & (new < 1)).sum()}"
                f" lost top-10 {((base >= 0.1) & (new < 0.1)).sum()}"
                f"  gained top-10 {((base < 0.1) & (new >= 0.1)).sum()}"
            )

sub = [r for r in recs if r["fold"] == "select"]
base = np.array([rr(r, 0) for r in sub])
new = np.array([rr(r, best, "z", best_t) for r in sub])
for label, mask in (("lost top-1", (base == 1) & (new < 1)), ("harmed", new < base), ("helped", new > base)):
    pubs = collections.Counter(sub[k]["group"] for k in np.where(mask)[0])
    print(f"select {label}: {mask.sum()} patients in {len(pubs)} publications; largest {pubs.most_common(3)}")
