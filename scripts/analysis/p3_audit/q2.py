"""Q2: where E0 fails on uncited in-vocabulary patients (p2-v1 train+dev). Per-patient features from the
HPO 2025-11-24 knowledge (own PMID masked), sliced; E0, ft-v1.1 and gene|resnik_pg shown side by side.

Usage (repo root): PYTHONPATH=src .venv/bin/python <this>
"""

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import DATA, Boot, load, summary  # noqa: E402

from diagnostic_ar_training.lineage.registry import Purpose, open_source  # noqa: E402
from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology  # noqa: E402

genes, meta = load()
N = len(meta)
onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
pheno = onto.descendants(PHENOTYPIC_ABNORMALITY) | {PHENOTYPIC_ABNORMALITY}

drows, dinh = defaultdict(list), defaultdict(set)
with open(open_source("hpo_annotations_2025_11_24", Purpose.KB)) as f:
    for r in csv.DictReader((x for x in f if not x.startswith("#")), delimiter="\t"):
        refs = frozenset(x.strip() for x in r["reference"].split(";") if x.strip().startswith("PMID:"))
        if r["aspect"] == "I":
            dinh[r["database_id"]].add(r["hpo_id"])
        if r["aspect"] != "P" or r["qualifier"] == "NOT" or r["frequency"] == "HP:0040285" or r["frequency"].startswith("0/"):
            continue
        t = onto.resolve(r["hpo_id"])
        if t in pheno:
            drows[r["database_id"]].append((t, refs))
g2d = defaultdict(set)
with open(open_source("hpo_genes_to_disease", Purpose.KB)) as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r["association_type"] != "POLYGENIC" and r["disease_id"] in drows:
            g2d[r["gene_symbol"]].add(r["disease_id"])


def clos(ts):
    out = set()
    for t in ts:
        out |= onto.ancestors(t) | {t}
    return out & pheno


gene_clos = {g: clos({t for x in ds for t, _ in drows[x]}) for g, ds in g2d.items()}
cnt = Counter(t for c in gene_clos.values() for t in c)
G = len(gene_clos)
ic = {t: -np.log(c / G) for t, c in cnt.items()}
ICMAX = -np.log(1 / G)

AD, AR, XL = "HP:0000006", "HP:0000007", {"HP:0001417", "HP:0001419", "HP:0001423"}


def inheritance(g):
    s = set().union(*[dinh.get(x, set()) for x in g2d.get(g, ())]) if g in g2d else set()
    k = []
    if AD in s:
        k.append("AD")
    if AR in s:
        k.append("AR")
    if s & XL:
        k.append("XL")
    return "+".join(k) if k else "none/other"


gene_count = Counter(m["gene"] for m in meta)
group_size = Counter(m["group"] for m in meta)
feat = []
for m in meta:
    Q = {r for r in (onto.resolve(x) for x in m["present"]) if r in pheno}
    pm = set(m["pmids"])
    prof = {t for x in g2d.get(m["gene"], ()) for t, refs in drows[x] if not (refs & pm)}
    gc = clos(prof)
    prof_u = {t for x in g2d.get(m["gene"], ()) for t, _ in drows[x]}
    gcu = clos(prof_u)
    leaves = {q for q in Q if not any(q in onto.ancestors(o) for o in Q if o != q)}
    feat.append(
        dict(
            n_q=len(Q),
            ic_mean=float(np.mean([ic.get(q, ICMAX) for q in Q])) if Q else np.nan,
            redundant=(1 - len(leaves) / len(Q)) if Q else np.nan,
            explained=(len(Q & gc) / len(Q)) if Q else np.nan,
            exact=(len(Q & prof) / len(Q)) if Q else np.nan,
            explained_unmasked=(len(Q & gcu) / len(Q)) if Q else np.nan,
            has_excl=bool(m["excluded"]),
            gene_terms=len(prof),
            gene_dis=len(g2d.get(m["gene"], ())),
            inh=inheritance(m["gene"]),
            gene_cohort=gene_count[m["gene"]],
            group_size=group_size[m["group"]],
        )
    )
json.dump(feat, open(DATA / "q2_features.json", "w"))

cited = np.array([m["cited"] for m in meta])
inv = np.array([m["in_vocab"] for m in meta])
e0 = [m["e0_rank"] for m in meta]
ft = [m["ft_rank"] for m in meta]
rp = [m["sim"].get("gene|resnik_pg|rank_all") for m in meta]
groups = [m["group"] for m in meta]


def col(k):
    return np.array([f[k] for f in feat], dtype=float if k != "inh" else object)


def bins(k, edges, labels):
    v = col(k)
    return [(f"{k} {lab}", (v >= lo) & (v < hi)) for (lo, hi), lab in zip(edges, labels)]


specs = []
specs += bins("n_q", [(0, 1), (1, 3), (3, 6), (6, 11), (11, 21), (21, 1e9)], ["0", "1-2", "3-5", "6-10", "11-20", ">20"])
icq = col("ic_mean")
qs = np.nanpercentile(icq[~cited & inv], [25, 50, 75])
specs += bins("ic_mean", [(-1, qs[0]), (qs[0], qs[1]), (qs[1], qs[2]), (qs[2], 99)],
              [f"<{qs[0]:.2f}", f"{qs[0]:.2f}-{qs[1]:.2f}", f"{qs[1]:.2f}-{qs[2]:.2f}", f">={qs[2]:.2f}"])
specs += bins("redundant", [(0, 0.001), (0.001, 0.25), (0.25, 2)], ["0", "0-25%", ">=25%"])
specs += bins("explained", [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)], ["<25%", "25-50%", "50-75%", ">=75%"])
specs += bins("exact", [(0, 0.001), (0.001, 0.25), (0.25, 0.5), (0.5, 1.01)], ["0", "0-25%", "25-50%", ">=50%"])
he = col("has_excl")
specs += [("excluded: yes", he == 1), ("excluded: no", he == 0)]
specs += bins("gene_terms", [(0, 1), (1, 10), (10, 30), (30, 100), (100, 1e9)], ["0", "1-9", "10-29", "30-99", ">=100"])
specs += bins("gene_dis", [(0, 2), (2, 3), (3, 5), (5, 1e9)], ["1 (or 0)", "2", "3-4", ">=5"])
inh = col("inh")
specs += [(f"inh {k}", inh == k) for k in sorted(set(inh))]
specs += bins("gene_cohort", [(1, 2), (2, 6), (6, 21), (21, 1e9)], ["1", "2-5", "6-20", ">20"])
specs += bins("group_size", [(1, 2), (2, 6), (6, 21), (21, 1e9)], ["1", "2-5", "6-20", ">20"])

B = Boot(groups)
rows = []
rec_e0 = np.array([0 if x is None else 1 / x for x in e0])
for base_name, base in (("uncited & inV", ~cited & inv), ("cited & inV", cited & inv)):
    for name, s in specs:
        sel = base & s
        if sel.sum() == 0:
            continue
        r = {"base": base_name, "slice": name, "n": int(sel.sum()), "pubs": int(len({groups[i] for i in np.where(sel)[0]}))}
        r["E0"], r["ft"], r["resnik_pg"] = summary(e0, sel), summary(ft, sel), summary(rp, sel)
        r["E0_ci"] = B.ci_mean(rec_e0, sel)
        rows.append(r)
json.dump(rows, open(DATA / "q2.json", "w"), indent=1)
for r in rows:
    print(f"{r['base']:14s} {r['slice']:28s} n={r['n']:5d} pubs={r['pubs']:4d} "
          f"E0 {r['E0']['mrr']:.3f} [{r['E0_ci'][0]:.3f},{r['E0_ci'][1]:.3f}] t1 {r['E0']['top1']:.2f} t10 {r['E0']['top10']:.2f} | "
          f"ft {r['ft']['mrr']:.3f} | resnik_pg {r['resnik_pg']['mrr']:.3f} t10 {r['resnik_pg']['top10']:.2f}")

# Direct standardisation: E0 MRR by explained-share bin (own PMID masked for both; unmasked for cited = what E0 saw)
EDGES = [(0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.01)]
std = {}
for kcit in ("explained", "explained_unmasked"):
    vc, vu = col(kcit), col("explained")
    c_sel, u_sel = cited & inv, ~cited & inv
    wc = np.array([((vc >= lo) & (vc < hi) & c_sel).mean() / c_sel.mean() for lo, hi in EDGES])
    wu = np.array([((vu >= lo) & (vu < hi) & u_sel).mean() / u_sel.mean() for lo, hi in EDGES])
    mc = np.array([rec_e0[(vc >= lo) & (vc < hi) & c_sel].mean() for lo, hi in EDGES])
    mu = np.array([rec_e0[(vu >= lo) & (vu < hi) & u_sel].mean() for lo, hi in EDGES])
    std[kcit] = dict(w_cited=wc.tolist(), w_uncited=wu.tolist(), bin_mrr_cited=mc.tolist(), bin_mrr_uncited=mu.tolist(),
                     uncited_at_cited_mix=float((wc * mu).sum()), cited_at_uncited_mix=float((wu * mc).sum()),
                     mrr_cited=float(rec_e0[c_sel].mean()), mrr_uncited=float(rec_e0[u_sel].mean()))
    print(kcit, json.dumps({k: (np.round(v, 3).tolist() if isinstance(v, list) else round(v, 4)) for k, v in std[kcit].items()}))
json.dump(std, open(DATA / "q2_standardisation.json", "w"), indent=1)
