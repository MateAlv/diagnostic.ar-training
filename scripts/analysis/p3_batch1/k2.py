"""PHASE3 §2e K2: K1 with harm controls, read out of fold over FIT and SELECT (folds 0-3).

Memory = every fold 0-3 patient. A query never sees its own publication, in memory or in the per-gene null.
Fused score: log p_E0 + gate * min(lambda * max(0, z - t), B), with z K1's calibrated per-gene evidence.
B caps how far a gene can climb, so genes without memory cannot fall far; gate = 0 when E0's top probability
>= tau. Nested selection: each outer fold's (lambda, t, B, tau) is chosen by capped MRR on the other three
folds' uncited queries, then the outer fold is scored once. K1 (B and tau off) is read the same way. The
pooled out-of-fold readings cover four folds instead of SELECT alone. Popularity control: each query's
phenotype is swapped for another query's of the same fold, both publications excluded, true gene kept.
Variants (K3, PHASE3 §2e): `--sim` ic (term weight = disease IC, K1), idf (inverse frequency among the
fold 0-3 patients) or direct (disease IC, present terms without their ancestors); `--agg` max (best patient,
K1) or top2 (mean of the gene's two best publications, each publication scored by its best patient).
`--perturb parent` replaces each query term by one of its parents (seeded) before the memory lookup; memory,
null and E0 keep the curated terms. It tests how much of the gain needs the curators' exact terms.
Reads `$P3_B1_DATA/e0probs.pkl` (written by knn.py).
"""

import argparse
import collections
import itertools
import math
import os
import pickle

import numpy as np
import scipy.sparse as sp

from diagnostic_ar_training.sim4 import load_knowledge
from diagnostic_ar_training.v4 import patients as P
from diagnostic_ar_training.v4.report import CAP

DATA = os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/"
LAMBDAS = (0.5, 1, 2, 4, 8, 16)
THRESHOLDS = (0, 1, 2, 3)
CAPS = (math.inf, 1, 2, 4)
TAUS = (math.inf, 0.9, 0.7, 0.5)
UNCITED = "uncited_e0_knowledge"
cli = argparse.ArgumentParser()
cli.add_argument("--sim", choices=("ic", "idf", "direct"), default="ic")
cli.add_argument("--agg", choices=("max", "top2"), default="max")
cli.add_argument("--perturb", choices=("none", "parent"), default="none")
cli.add_argument("--dump", help="save SELECT queries' evidence (z, swapped z) to this .npz, for r5_checks.py")
args = cli.parse_args()
print(f"similarity {args.sim}, aggregation {args.agg}, query terms {args.perturb}")

K = load_knowledge()
onto = K.ontology
allp = P.load("fit") + P.load("select")
N = len(allp)


def closure(p, rng=None):
    out = set()
    for x in p.case.present:
        t = onto.resolve(x)
        if t and K.is_finding(t):
            if rng is not None:
                parents = sorted(a for a in onto.parents(t) if K.is_finding(a))
                t = parents[rng.integers(len(parents))] if parents else t
            out |= {t} if args.sim == "direct" else {t} | {a for a in onto.ancestors(t) if K.is_finding(a)}
    return out


C = [closure(p) for p in allp]
perturb_rng = np.random.default_rng(1)
Cq = [closure(p, perturb_rng) for p in allp] if args.perturb == "parent" else C
patient_df = collections.Counter(t for c in C for t in c)


def ic(t):
    if args.sim == "idf":
        return -math.log(patient_df[t] / N)
    return -math.log(max(K.disease_counts.get(t, 0), 1) / K.n_diseases)


vocab = {t: i for i, t in enumerate(sorted(set().union(*C, *Cq)))}


def matrix(closures):
    rows = [i for i, c in enumerate(closures) for _ in c]
    cols = [vocab[t] for c in closures for t in c]
    vals = [ic(t) for c in closures for t in c]
    m = sp.csr_matrix((vals, (rows, cols)), shape=(N, len(vocab)))
    return m, np.sqrt(np.asarray(m.multiply(m).sum(1)).ravel()) + 1e-9


X, norm = matrix(C)
sim = (X @ X.T).toarray() / norm[:, None] / norm[None, :]
Xq, norm_q = matrix(Cq)
sim_q = sim if Cq is C else (Xq @ X.T).toarray() / norm_q[:, None] / norm[None, :]

e0p, genes = pickle.load(open(DATA + "e0probs.pkl", "rb"))
gidx = {g.upper(): i for i, g in enumerate(genes)}
G = len(genes)
gene = np.array([gidx.get(p.case.gene.upper(), -1) for p in allp])
names, group = np.unique([p.group for p in allp], return_inverse=True)
fold = np.array([p.fold for p in allp])
members = collections.defaultdict(list)
for j, g in enumerate(gene):
    if g >= 0:
        members[g].append(j)
mgenes = np.array(sorted(members))
publications = {
    g: [[j for j in js if group[j] == x] for x in np.unique(group[js])] for g, js in members.items()
}


def aggregate(s, g):
    if args.agg == "max":
        return s[:, members[g]].max(1)
    per_pub = np.stack([s[:, js].max(1) for js in publications[g]], 1)
    if per_pub.shape[1] == 1:
        return per_pub[:, 0]
    top = -np.sort(-per_pub, 1)[:, :2]
    return np.where(top[:, 1] >= 0, top.mean(1), top[:, 0])


def best_sim(rows, excluded):
    """Best similarity of each phenotype row to each memory gene, skipping those in `excluded` groups."""
    s = rows.copy()
    for ex in excluded:
        s[group[None, :] == ex[:, None]] = -1.0
    return np.stack([aggregate(s, g) for g in mgenes], 1)


# Per-gene null: best similarity of other genes' patients, per group, so a query's group can be dropped.
own = best_sim(sim, [group])
valid = (gene[:, None] != mgenes[None, :]) & (own >= 0)
sums = np.zeros((3, group.max() + 1, mgenes.size))
for k, v in enumerate((valid, np.where(valid, own, 0.0), np.where(valid, own, 0.0) ** 2)):
    np.add.at(sums[k], group, v)
total = sums.sum(1)


def zscores(s, excluded):
    """z of each row's best similarities against the null without the rows' `excluded` groups."""
    c, s1, s2 = (total[k] - sums[k][excluded[0]] for k in range(3))
    for ex in excluded[1:]:
        other = (ex != excluded[0])[:, None]
        c, s1, s2 = c - other * sums[0][ex], s1 - other * sums[1][ex], s2 - other * sums[2][ex]
    mean = s1 / np.maximum(c, 1)
    sd = np.sqrt(np.maximum(s2 / np.maximum(c, 1) - mean**2, 0)) + 1e-6
    mean, sd = np.where(c > 1, mean, 1.0), np.where(c > 1, sd, 1.0)
    z = np.zeros((s.shape[0], G))
    z[:, mgenes] = np.where(s >= 0, (s - mean) / sd, 0.0)
    return z


queries = np.array([i for i, p in enumerate(allp) if gene[i] >= 0 and e0p[i] is not None])
lp = np.log(np.stack([e0p[i] for i in queries]) + 1e-12)
top = np.exp(lp.max(1))
qg = gene[queries]
z = zscores(best_sim(sim_q[queries], [group[queries]]), [group[queries]])
rng = np.random.default_rng(0)
perm = queries.copy()
for f in np.unique(fold[queries]):
    m = fold[queries] == f
    perm[m] = rng.permutation(queries[m])
excl = [group[queries], group[perm]]
z_swap = zscores(best_sim(sim_q[perm], excl), excl)

uncited = np.array([allp[i].status == UNCITED for i in queries])
oov = [i for i, p in enumerate(allp) if p.status == UNCITED and not (gene[i] >= 0 and e0p[i] is not None)]
grid = list(itertools.product(LAMBDAS, THRESHOLDS, CAPS, TAUS))
K1_GRID = [c for c in grid if c[2] == math.inf and c[3] == math.inf]


def rr(zz, cfg):
    lam, t, cap, tau = cfg
    boost = np.minimum(lam * np.clip(zz - t, 0, None), cap) * (top < tau)[:, None]
    score = lp + boost
    own_score = score[np.arange(len(queries)), qg]
    return 1 / (1 + (score > own_score[:, None]).sum(1))


def capped(groups, values):
    _, inv, n = np.unique(groups, return_inverse=True, return_counts=True)
    w = np.minimum(n, CAP)[inv] / n[inv]
    return float(np.sum(w * values) / np.sum(w)), w, inv


def delta_ci(groups, new, base):
    point, w, inv = capped(groups, new - base)
    num, den = np.bincount(inv, weights=w * (new - base)), np.bincount(inv, weights=w)
    picks = np.random.default_rng(0).integers(0, num.size, (2000, num.size))
    lo, hi = np.percentile(num[picks].sum(1) / den[picks].sum(1), [2.5, 97.5])
    return point, lo, hi


base = rr(z, (0, 0, math.inf, math.inf))
table = {cfg: rr(z, cfg) for cfg in grid}
qgroup = group[queries]
qfold = fold[queries]


def nested(candidates):
    """Out-of-fold reciprocal ranks (own and swapped phenotype) and each outer fold's chosen configuration."""
    new, swap, chosen = np.zeros(len(queries)), np.zeros(len(queries)), {}
    for f in np.unique(qfold):
        tune = uncited & (qfold != f)
        cfg = max(candidates, key=lambda c: capped(qgroup[tune], table[c][tune])[0])
        out = qfold == f
        new[out], swap[out], chosen[int(f)] = table[cfg][out], rr(z_swap, cfg)[out], cfg
    return new, swap, chosen


def report(name, new, swap, chosen):
    print(f"\n== {name}; chosen per outer fold: {chosen}")
    folds_of = {
        "all folds": (0, 1, 2, 3),
        "SELECT": (3,),
        "FIT": (0, 1, 2),
        "fold 0": (0,),
        "fold 1": (1,),
        "fold 2": (2,),
    }
    for label, cited, where, pad in (
        ("uncited, all folds", False, "all folds", True),
        ("uncited, SELECT", False, "SELECT", True),
        ("uncited, FIT", False, "FIT", True),
        *((f"uncited, fold {f}", False, f"fold {f}", True) for f in range(3)),
        ("uncited in-vocab, all folds", False, "all folds", False),
        ("cited, all folds", True, "all folds", False),
    ):
        mask = (uncited != cited) & np.isin(qfold, folds_of[where])
        groups, b, n, s = qgroup[mask], base[mask], new[mask], swap[mask]
        if pad:
            extra = [i for i in oov if fold[i] in folds_of[where]]
            groups = np.concatenate([groups, group[extra]])
            b, n, s = (np.concatenate([a, np.zeros(len(extra))]) for a in (b, n, s))
        d, lo, hi = delta_ci(groups, n, b)
        ds = delta_ci(groups, s, b)
        print(
            f"{label:28} n {len(b):5} groups {np.unique(groups).size:4}  E0 {capped(groups, b)[0]:.4f}"
            f" -> {capped(groups, n)[0]:.4f}  Δ {d:+.4f} [{lo:+.4f}, {hi:+.4f}]  swap Δ {ds[0]:+.4f}"
            f" [{ds[1]:+.4f}, {ds[2]:+.4f}]  helped {(n > b).sum()} harmed {(n < b).sum()}"
            f" lost top-1 {((b == 1) & (n < 1)).sum()}"
        )
    m = uncited
    for label, mask in (("harmed", new[m] < base[m]), ("helped", new[m] > base[m])):
        pubs = collections.Counter(names[qgroup[m][mask]])
        print(f"uncited {label}: {mask.sum()} patients in {len(pubs)} publications;", pubs.most_common(3))
    for pub, _ in collections.Counter(names[qgroup[m][new[m] < base[m]]]).most_common(3):
        g = qg[m][names[qgroup[m]] == pub][0]
        others = len({group[j] for j in members.get(g, ())} - {np.where(names == pub)[0][0]})
        print(f"  {pub}: gene {genes[g]}, memory publications of that gene outside it: {others}")


print(f"queries {len(queries)} (uncited {uncited.sum()}), uncited OOV {len(oov)}, memory genes {mgenes.size}")
report("K1 (no cap, no gate)", *nested(K1_GRID))
if args.dump:
    sel = qfold == 3
    case_ids = np.array([allp[i].case.case_id for i in queries[sel]])
    np.savez_compressed(
        args.dump, case_id=case_ids, z=z[sel].astype(np.float32), z_swap=z_swap[sel].astype(np.float32)
    )
report("K2 (cap B, gate tau)", *nested(grid))
