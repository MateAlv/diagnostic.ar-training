"""PHASE3 §2f step 3 scoping (run under a memory cap: `systemd-run --user --scope -p MemoryMax=4G`):
how much room sex and age leave on top of the network, folds 0-3 out of fold.

Hard filters on the network's out-of-fold logits (a gene removed goes below every kept gene):
- sex: the gene is limited to the other sex (`p3-addon-kb-v1`);
- onset: the gene's strict earliest onset is later than the patient's latest possible onset. That onset is, in
  the `now` reading, the onset in years else the current age (what the add-on reads); in the `full` reading
  also the upper end of the onset class (HPO onset term) and of each per-symptom onset.
Then, for uncited patients whose gene is not first, what the genes ranked above it are: removable now, without
onset knowledge, or known and compatible.
"""

import math

import numpy as np

from diagnostic_ar_training.v4 import addon, patients

UPPER = {
    "HP:0030674": 0, "HP:0011460": 0, "HP:0011461": 0, "HP:0034199": 0, "HP:0034198": 0, "HP:0034197": 0,
    "HP:0003577": 0, "HP:0003623": 28 / 365, "HP:0003593": 1, "HP:0011463": 5, "HP:0003621": 16,
    "HP:0410280": 16, "HP:0011462": 40, "HP:0025708": 19, "HP:0025709": 25, "HP:0025710": 40,
    "HP:0003596": 60,
}  # fmt: skip

kb, _ = addon.load_kb("p3-addon-kb-v1")
members = {p.case_id: p for p in patients.load_addon((0, 1, 2, 3))}
genes, net = None, {}
for k in range(4):
    with np.load(f"data/interim/p3-addon/logits-f{k}.npz") as z:
        genes, logits, ok, case_ids = list(z["genes"]), z["net"], z["net_ok"], z["case_id"]
    net.update({c: logits[i].copy() for i, c in enumerate(case_ids) if ok[i]})
    del logits
G = len(genes)
onset = np.full(G, np.nan)
other_sex = {"male": np.zeros(G, bool), "female": np.zeros(G, bool)}
for j, g in enumerate(genes):
    rec = kb["safe"]["genes"].get(g, {})
    y = (rec.get("onset") or {}).get("earliest_years")
    if y is not None:
        onset[j] = y
    limited = (rec.get("sex") or {}).get("limit")
    if limited in ("male", "female"):
        other_sex["female" if limited == "male" else "male"][j] = True
print(
    "genes with strict onset",
    int(np.isfinite(onset).sum()),
    "sex-limited",
    sum(int(v.sum()) for v in other_sex.values()),
)


def latest_onset(case, full):
    vals = [case.onset_years, None if case.onset_years is not None else case.age_years]
    if full:
        vals += [UPPER.get(case.onset_term), case.age_years]
        for _, years, term in case.feature_onsets:
            vals += [years, UPPER.get(term)]
    vals = [max(v, 0.0) for v in vals if v is not None]
    return min(vals) if vals else None


def removed(case, full, use_sex=True, use_onset=True):
    out = np.zeros(G, bool)
    if use_sex and case.sex.value in other_sex:
        out |= other_sex[case.sex.value]
    ref = latest_onset(case, full) if use_onset else None
    if ref is not None:
        out |= np.nan_to_num(onset, nan=-1) > ref
    return out


ids = [c for c in members if c in net]
idx = {g.upper(): i for i, g in enumerate(genes)}
base = addon.records([members[c] for c in ids], {c: net[c] for c in ids}, genes)


def reading(label, full, **kw):
    scores = {}
    for c in ids:
        s = net[c].astype(np.float64).copy()
        s[removed(members[c].case, full, **kw)] = -1e9
        scores[c] = s
    new = addon.records([members[c] for c in ids], scores, genes)
    for name, x in addon.compare(new, base).items():
        lo, hi = x["delta_mrr_cap_ci95"]
        lost = sum(
            1 for a, b in zip(base, new, strict=True) if name in a["strata"] and b["rank"] > G / 2 > a["rank"]
        )
        print(
            f"{label:28} {name:17} n {x['n']:5}  network {x['e0']['mrr_cap']:.4f} -> {x['mrr_cap']:.4f}"
            f"  Δ {x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}]"
            f"  helped {x['helped']} harmed {x['harmed']}"
            f"  true gene removed {lost}"
        )


cases = [members[c].case for c in ids]
n = len(cases)
print(f"patients {n}; reference age now {sum(latest_onset(c, False) is not None for c in cases) / n:.2f}, "
      f"full {sum(latest_onset(c, True) is not None for c in cases) / n:.2f}; "
      f"reference age lowered by the full reading "
      f"{sum((latest_onset(c, True) or 0) < (latest_onset(c, False) or math.inf) for c in cases)}"
)  # fmt: skip
reading("sex only", False, use_onset=False)
reading("onset, now", False, use_sex=False)
reading("onset, full", True, use_sex=False)
reading("sex + onset, now", False)
reading("sex + onset, full", True)

above = {
    "removable now": 0,
    "removable with full onset": 0,
    "no onset knowledge": 0,
    "known and compatible": 0,
}
n_pat = 0
for c in ids:
    p = members[c]
    t = idx.get(p.case.gene.upper())
    if p.status != patients.UNCITED or t is None:
        continue
    s = net[c]
    up = np.where(s > s[t])[0]
    if up.size == 0:
        continue
    n_pat += 1
    now, full = removed(p.case, False)[up], removed(p.case, True)[up]
    above["removable now"] += int(now.sum())
    above["removable with full onset"] += int((full & ~now).sum())
    rest = ~full
    above["no onset knowledge"] += int((rest & ~np.isfinite(onset[up])).sum())
    above["known and compatible"] += int((rest & np.isfinite(onset[up])).sum())
total = sum(above.values())
print(f"uncited in-vocab patients with the gene not first: {n_pat}; genes ranked above it: {total}")
for k, v in above.items():
    print(f"  {k:28} {v:7}  {v / total:.3f}")

near = {
    "removable now": 0,
    "removable with full onset": 0,
    "no onset knowledge": 0,
    "known and compatible": 0,
}
n_near = first_removable = 0
for c in ids:
    p = members[c]
    t = idx.get(p.case.gene.upper())
    if p.status != patients.UNCITED or t is None:
        continue
    s = net[c]
    up = np.where(s > s[t])[0]
    if not 1 <= up.size <= 9:
        continue
    n_near += 1
    now, full = removed(p.case, False)[up], removed(p.case, True)[up]
    first_removable += bool(full[np.argmax(s[up])])
    near["removable now"] += int(now.sum())
    near["removable with full onset"] += int((full & ~now).sum())
    near["no onset knowledge"] += int((~full & ~np.isfinite(onset[up])).sum())
    near["known and compatible"] += int((~full & np.isfinite(onset[up])).sum())
total = sum(near.values())
print(
    f"uncited patients with the gene at rank 2-10: {n_near}; genes above it: {total};"
    f" top gene removable {first_removable}"
)
for k, v in near.items():
    print(f"  {k:28} {v:7}  {v / total:.3f}")
