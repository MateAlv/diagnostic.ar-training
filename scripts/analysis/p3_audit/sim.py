"""Phase 3 error analysis, step 2: training-free similarity scorers over every annotated gene.

Knowledge: HPO phenotype.hpoa 2025-11-24 (the release E0 was trained on), aspect P, no NOT rows, no
"excluded" frequency; gene-disease links from genes_to_disease 2026-02-16 (only registered release),
POLYGENIC dropped; ontology hp.json 2026-02-16. For each patient, every row citing one of the patient's
own PMIDs is dropped before scoring (per-patient masking of the affected entities).

Usage (repo root): PYTHONPATH=src .venv/bin/python <this> <data_dir> [hpoa source name, default 2025-11-24]
"""

import csv
import json
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch

from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology

DATA = Path(sys.argv[1])
SRC = sys.argv[2] if len(sys.argv) > 2 else "hpo_annotations_2025_11_24"
TAG = "" if SRC == "hpo_annotations_2025_11_24" else "_" + SRC
dev = torch.device("cuda")
d = pickle.load(open(DATA / "cases.pkl", "rb"))
meta, e0_genes = d["meta"], d["genes"]
e0_set = set(e0_genes)

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
pheno_terms = sorted(onto.descendants(PHENOTYPIC_ABNORMALITY) | {PHENOTYPIC_ABNORMALITY})
tidx = {t: i for i, t in enumerate(pheno_terms)}
T = len(pheno_terms)
anc_idx = [None] * T
for t, i in tidx.items():
    anc_idx[i] = np.array(sorted(tidx[a] for a in (onto.ancestors(t) | {t}) if a in tidx), dtype=np.int64)

# disease -> list of (term idx, refs)
EXCL_FREQ = {"HP:0040285"}
drows = defaultdict(list)
with open(open_source(SRC, Purpose.KB)) as f:
    for r in csv.DictReader((x for x in f if not x.startswith("#")), delimiter="\t"):
        if r["aspect"] != "P" or r["qualifier"] == "NOT" or r["frequency"] in EXCL_FREQ:
            continue
        if r["frequency"].startswith("0/"):
            continue
        t = onto.resolve(r["hpo_id"])
        if t is None or t not in tidx:
            continue
        refs = frozenset(x.strip() for x in r["reference"].split(";") if x.strip().startswith("PMID:"))
        drows[r["database_id"]].append((tidx[t], refs))

g2d = defaultdict(set)
with open(open_source("hpo_genes_to_disease", Purpose.KB)) as f:
    for r in csv.DictReader(f, delimiter="\t"):
        if r["association_type"] != "POLYGENIC" and r["disease_id"] in drows:
            g2d[r["gene_symbol"]].add(r["disease_id"])
kb_genes = sorted(g2d)
kidx = {g: i for i, g in enumerate(kb_genes)}
G = len(kb_genes)
diseases = sorted(drows)
didx = {x: i for i, x in enumerate(diseases)}
gd_pairs = np.array([(kidx[g], didx[x]) for g in kb_genes for x in g2d[g]], dtype=np.int64)

grows = {g: [row for x in sorted(g2d[g]) for row in drows[x]] for g in kb_genes}
erows = {"gene": [grows[g] for g in kb_genes], "disease": [drows[x] for x in diseases]}


def direct_set(rows, mask=frozenset()):
    return {t for t, refs in rows if not (refs & mask)}


def closure(terms):
    if len(terms) == 0:
        return np.zeros(0, dtype=np.int64)
    return np.unique(np.concatenate([anc_idx[t] for t in terms]))


def matrices(direct_sets):
    E = len(direct_sets)
    D = torch.zeros((E, T), dtype=torch.bool)
    C = torch.zeros((E, T), dtype=torch.bool)
    for e, s in enumerate(direct_sets):
        if s:
            D[e, list(s)] = True
            C[e, torch.from_numpy(closure(s))] = True
    return D.to(dev), C.to(dev)


full = {}
for level in ("gene", "disease"):
    sets = [direct_set(r) for r in erows[level]]
    D, C = matrices(sets)
    n = C.sum(0).float()
    ic = -torch.log(torch.clamp(n, min=1.0) / len(sets))
    full[level] = dict(D=D, C=C, ic=ic, sets=sets, Df=D.float())
    print(level, len(sets), "entities", time.strftime("%X"), flush=True)

# pmid -> entities with a row citing it
cite = {lvl: defaultdict(set) for lvl in erows}
for lvl, rows_list in erows.items():
    for e, rows in enumerate(rows_list):
        for _, refs in rows:
            for p in refs:
                cite[lvl][p].add(e)

ANC = torch.zeros((T, T), dtype=torch.bool)
for i in range(T):
    ANC[i, torch.from_numpy(anc_idx[i])] = True
ANC = ANC.to(dev)


def scores(D, C, ic, Q, closQ, Df=None):
    """All scorers for entity matrices (D direct, C closure) and patient terms Q (closure closQ)."""
    out = {}
    Qt = torch.from_numpy(Q).to(dev)
    cq = torch.from_numpy(closQ).to(dev)
    pg = torch.zeros(D.shape[0], device=dev)
    for q in Q:
        a = torch.from_numpy(anc_idx[q]).to(dev)
        pg += (C[:, a].float() * ic[a]).amax(1)
    out["resnik_pg"] = pg / len(Q)
    v = (ANC[:, cq].float() * ic[cq]).amax(1)
    Df = D.float() if Df is None else Df
    nd = Df.sum(1)
    gp = (Df @ v) / torch.clamp(nd, min=1)
    out["resnik_sym"] = 0.5 * (out["resnik_pg"] + gp)
    w = ic
    sumQ = w[Qt].sum()
    W = Df @ w
    sj = D[:, Qt].float() @ w[Qt]
    out["heur_exact"] = sj - 0.3 * (sumQ - sj) - 0.15 * (W - sj)
    sjp = C[:, Qt].float() @ w[Qt]
    kmatched = D[:, cq].float() @ w[cq]
    out["heur_prop"] = sjp - 0.3 * (sumQ - sjp) - 0.15 * (W - kmatched)
    return out


gd_g = torch.from_numpy(gd_pairs[:, 0]).to(dev)
gd_d = torch.from_numpy(gd_pairs[:, 1]).to(dev)


def to_gene(sd):
    out = torch.full((G,), -1e30, device=dev)
    return out.scatter_reduce(0, gd_g, sd[gd_d], reduce="amax")


def rank_of(s, t, keep=None):
    if keep is not None:
        s = torch.where(keep, s, torch.tensor(-1e38, device=dev))
    st = s[t]
    return float(1 + (s > st).sum() + 0.5 * ((s == st).sum() - 1))


in_e0 = torch.tensor([g in e0_set for g in kb_genes], device=dev)
CONFIGS = [(lvl, m) for lvl in ("gene", "disease") for m in ("resnik_pg", "resnik_sym", "heur_exact", "heur_prop")]
SAVE = {("gene", "resnik_pg"), ("gene", "resnik_sym"), ("disease", "resnik_sym"), ("disease", "resnik_pg"),
        ("gene", "heur_prop")}
store = {c: np.zeros((len(meta), G), dtype=np.float32) for c in SAVE}
res = []
t0 = time.time()
for i, m in enumerate(meta):
    Q = sorted({tidx[r] for r in (onto.resolve(x) for x in m["present"]) if r in tidx})
    row = {"case_id": m["case_id"], "n_q": len(Q), "gene_in_kb": m["gene"] in kidx}
    if not Q:
        res.append(row)
        continue
    Q = np.array(Q, dtype=np.int64)
    closQ = closure(Q)
    pm = frozenset(m["pmids"])
    per_level = {}
    for lvl in ("gene", "disease"):
        F = full[lvl]
        s = scores(F["D"], F["C"], F["ic"], Q, closQ, F["Df"])
        aff = sorted(set().union(*[cite[lvl].get(p, set()) for p in pm])) if pm else []
        if aff:
            sets = [direct_set(erows[lvl][e], pm) for e in aff]
            D2, C2 = matrices(sets)
            s2 = scores(D2, C2, F["ic"], Q, closQ)
            idx = torch.tensor(aff, device=dev)
            for k in s:
                s[k] = s[k].clone()
                s[k][idx] = s2[k]
                empty = torch.tensor([not x for x in sets], device=dev)
                s[k][idx[empty]] = -1e30
        row[f"n_aff_{lvl}"] = len(aff)
        per_level[lvl] = s
    for lvl, k in CONFIGS:
        sg = per_level[lvl][k] if lvl == "gene" else to_gene(per_level[lvl][k])
        if (lvl, k) in SAVE:
            store[(lvl, k)][i] = sg.float().cpu().numpy()
        if m["gene"] in kidx:
            t = kidx[m["gene"]]
            row[f"{lvl}|{k}|rank_all"] = rank_of(sg, t)
            if m["gene"] in e0_set:
                row[f"{lvl}|{k}|rank_e0vocab"] = rank_of(sg, t, in_e0)
    if m["gene"] in kidx:
        t = kidx[m["gene"]]
        row["gene_n_terms_masked"] = len(direct_set(grows[m["gene"]], pm))
        row["gene_n_terms"] = len(full["gene"]["sets"][t])
        row["gene_n_diseases"] = len(g2d[m["gene"]])
        row["true_ic_mean_q"] = float(full["gene"]["ic"][torch.from_numpy(Q).to(dev)].mean())
    res.append(row)
    if i % 500 == 0:
        print(i, f"{time.time() - t0:.0f}s", flush=True)

json.dump(res, open(DATA / f"sim_ranks{TAG}.json", "w"))
for (lvl, k), arr in store.items():
    np.save(DATA / f"sim{TAG}_{lvl}_{k}.npy", arr)
json.dump({"kb_genes": kb_genes, "n_diseases": len(diseases), "n_terms": T}, open(DATA / f"kb_meta{TAG}.json", "w"))
print("done", G, "kb genes;", len(diseases), "diseases")
