"""Q5: E0 failure patterns (true gene outside the top 10) on uncited publications, with examples."""

import json
from collections import Counter

import numpy as np

from common import DATA, load

genes, meta = load()
feat = json.load(open(DATA / "q2_features.json"))
s26 = {r["case_id"]: r for r in json.load(open(DATA / "sim_ranks_hpo_annotations.json"))}
rng = np.random.default_rng(0)


def pattern(m, f):
    if not m["in_vocab"]:
        r26 = s26[m["case_id"]]
        if (r26.get("gene_n_terms_masked") or 0) == 0:
            return "A1 OOV, annotated only from own paper (or not at all) even in HPO 2026-02"
        return "A2 OOV, other-paper annotations exist in HPO 2026-02"
    if f["gene_terms"] < 10:
        return "B gene with <10 annotated terms"
    if f["n_q"] <= 2:
        return "C sparse phenotype (<=2 present terms)"
    if f["explained"] < 0.5:
        return "D phenotype mostly outside the gene's annotated profile (<50% explained)"
    return "E well explained (>=50%), still missed"


rows = []
for m, f in zip(meta, feat):
    if m["cited"]:
        continue
    miss = m["e0_rank"] is None or m["e0_rank"] > 10
    rows.append((m, f, miss, pattern(m, f)))
fails = [r for r in rows if r[2]]
print("uncited patients", len(rows), "E0 misses (rank>10 or unranked)", len(fails))
by = Counter(r[3] for r in fails)
out = {"n_uncited": len(rows), "n_miss": len(fails), "patterns": {}}
for p, n in sorted(by.items()):
    sel = [r for r in fails if r[3] == p]
    pubs = len({r[0]["group"] for r in sel})
    rp = [r[0]["sim"].get("gene|resnik_pg|rank_all") for r in sel]
    rp_top10 = float(np.mean([x is not None and x <= 10 for x in rp]))
    allp = [r for r in rows if r[3] == p]
    ex_idx = rng.choice(len(sel), size=min(4, len(sel)), replace=False)
    ex = []
    for i in ex_idx:
        m, f = sel[i][0], sel[i][1]
        ex.append({"gene": m["gene"], "n_present": f["n_q"], "explained": round(f["explained"], 2),
                   "gene_terms": f["gene_terms"], "e0_rank": m["e0_rank"], "resnik_pg_rank": m["sim"].get("gene|resnik_pg|rank_all"),
                   "inh": f["inh"]})
    out["patterns"][p] = {"n_miss": n, "share_of_misses": n / len(fails), "pubs": pubs, "n_all_in_pattern": len(allp),
                          "miss_rate_in_pattern": n / len(allp), "resnik_top10_among_misses": rp_top10,
                          "top_genes": Counter(r[0]["gene"] for r in sel).most_common(5), "examples": ex}
    print(f"\n{p}: misses {n} ({n / len(fails):.1%}), pubs {pubs}, pattern miss rate {n / len(allp):.2f}, "
          f"resnik top10 among misses {rp_top10:.2f}, top genes {Counter(r[0]['gene'] for r in sel).most_common(5)}")
    for e in ex:
        print("   ", e)
json.dump(out, open(DATA / "q5.json", "w"), indent=1)
