"""P4-AGE step 2: the harm check of every age-rule variant tried, p3-v1 train folds 0-3 (dev, out of fold).

A variant blocks a gene whose certain earliest onset (`age-kb-v1`) is at least `min_earliest` and later than
the patient's latest possible onset (`v4.agerule.case_latest_onset`) plus `margin` years. Dimensions:
- patient side: `classes` (onset years, onset class upper ends, per-symptom onsets, current age) or `years`
  (no onset class);
- gene side: `rows` (the knowledge's bound, lowered by HPOA's per-phenotype onsets) or `classes` (aspect C
  onset classes alone); and, as a reference, `p3-addon-kb-v1`'s strict onsets (only OMIM diseases need an
  onset), the bound P3-ADDON's ceiling.py read;
- `min_earliest` (which onset classes may block) and `margin` (years).
Per variant: harmed (patients whose true gene is blocked: the bar is 0), helped (scored patients whose true
gene is not blocked with at least one blocked gene above it on the network's out-of-fold logits), patients
with any gene blocked and blocked genes per such patient. Harmed patients are listed with their onset inputs
and their gene's diseases, once each. Writes results/P4/age/harm.json. CPU only; no fitting.
Usage: harm.py <age kb id>   (age-kb-v1)
"""

import json
import sys
import time

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.v4 import addon, agerule, patients

FOLDS = (0, 1, 2, 3)
ADDON_KB = "p3-addon-kb-v1"
MIN_EARLIEST = (1, 5, 16, 25, 40, 60)
MARGINS = (0, 5, 10, 15, 20, 30)
STATUS = {patients.UNCITED: "uncited", patients.CITED: "cited", patients.NO_PMID: "no_pmid"}

kb_id = sys.argv[1]
start = time.perf_counter()
state = code_state()
if state.dirty:
    raise SystemExit("commit first: results record the code state")
kb, kb_sha = agerule.load_kb(kb_id)
addon_kb, addon_sha = addon.load_kb(ADDON_KB)
gene_bounds = {
    "rows": agerule.bounds(kb),
    "classes": agerule.bounds(kb, rows=False),
    "p3-addon-kb-v1": {
        g: r["onset"]["earliest_years"] for g, r in addon_kb["safe"]["genes"].items() if "onset" in r
    },
}

members = patients.load_addon(FOLDS)
by_fold = {k: [p for p in members if p.fold == k] for k in FOLDS}
order = [p for k in FOLDS for p in by_fold[k]]
genes, net = None, {}
for k in FOLDS:
    with np.load(addon.ADDON_DIR / f"logits-f{k}.npz") as z:
        ids_k, genes, logits, ok = list(z["case_id"]), tuple(z["genes"]), z["net"], z["net_ok"]
    assert ids_k == [p.case_id for p in by_fold[k]], f"fold {k}: cache order"
    net.update({c: logits[i] for i, c in enumerate(ids_k) if ok[i]})
    del logits
lookup = {g.upper(): i for i, g in enumerate(genes)}
target = {p.case_id: lookup.get(p.case.gene.upper()) for p in order}
latest = {
    r: {p.case_id: agerule.case_latest_onset(p.case, r == "classes") for p in order}
    for r in ("classes", "years")
}
above_true = {c: s > s[target[c]] for c, s in net.items() if target[c] is not None}
print(f"{len(order)} patients, {len(net)} scored, loaded in {time.perf_counter() - start:.0f} s", flush=True)


harmed_patients: dict[str, dict] = {}


def harmed_case(p) -> dict:
    c, g = p.case, genes[target[p.case_id]]
    rec = kb["genes"].get(g, {})
    return {
        "gene": c.gene,
        "status": p.status,
        "fold": p.fold,
        "pmids": list(c.pmids),
        "latest_onset": {r: x[p.case_id] for r, x in latest.items()},
        "gene_bound": {b: x.get(g) for b, x in gene_bounds.items()},
        "onset_years": c.onset_years,
        "onset_term": c.onset_term,
        "age_years": c.age_years,
        "feature_onsets": [list(x) for x in c.feature_onsets],
        "diseases": {
            d: {
                "name": kb["disease_names"].get(d, ""),
                "classes": r["classes"],
                "row_onsets": r["row_onsets"],
            }
            for d, r in rec.get("diseases", {}).items()
        },
    }


def variant(bound: str, reading: str, min_earliest: float, margin: float) -> dict:
    rule = agerule.AgeRule(gene_bounds[bound], genes, margin, min_earliest)
    harmed, helped, any_block, n_blocked = [], {"uncited": 0, "cited": 0, "no_pmid": 0}, 0, 0
    exposed = {"true_gene_blockable": 0, "with_latest_onset": 0}
    for p in order:
        t = target[p.case_id]
        if t is not None and np.isfinite(rule.earliest[t]):
            exposed["true_gene_blockable"] += 1
            exposed["with_latest_onset"] += latest[reading][p.case_id] is not None
        mask = rule.blocked(latest[reading][p.case_id])
        if not mask.any():
            continue
        if p.case_id in net:
            any_block += 1
            n_blocked += int(mask.sum())
        if t is None:
            continue
        if mask[t]:
            harmed.append(p.case_id)
            harmed_patients.setdefault(p.case_id, harmed_case(p))
        elif p.case_id in above_true and (mask & above_true[p.case_id]).any():
            helped[STATUS[p.status]] += 1
    return {
        "bound": bound,
        "patient": reading,
        "min_earliest": min_earliest,
        "margin": margin,
        "blockable_genes": int(np.isfinite(rule.earliest).sum()),
        "patients_exposed": exposed,
        "harmed": len(harmed),
        "harmed_uncited": sum(harmed_patients[c]["status"] == patients.UNCITED for c in harmed),
        "helped": helped,
        "patients_with_any_block": any_block,
        "blocked_genes_per_blocked_patient": n_blocked / any_block if any_block else 0.0,
        "harmed_cases": harmed,
    }


variants = [
    variant(b, r, t, m)
    for b in ("rows", "classes")
    for r in ("classes", "years")
    for t in MIN_EARLIEST
    for m in MARGINS
]
variants += [variant("p3-addon-kb-v1", r, 0, 0) for r in ("classes", "years")]
out = {
    "cohort": {"split": patients.SPLIT, "folds": list(FOLDS), "patients": len(order), "scored": len(net)},
    "kb": {"id": kb_id, "sha256": kb_sha, "reference": ADDON_KB, "reference_sha256": addon_sha},
    "patients_with_latest_onset": {r: sum(v is not None for v in x.values()) for r, x in latest.items()},
    "variants": variants,
    "harmed_patients": harmed_patients,
    "seconds": time.perf_counter() - start,
    "code": state.as_dict(),
}
path = RESULTS_DIR / "P4" / "age" / "harm.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, default=str) + "\n")
print(json.dumps(out["patients_with_latest_onset"]))
print(
    "| bound | patient | min earliest | margin | blockable genes | exposed (onset known) | harmed (uncited) "
    "| helped unc / cited | patients blocked | genes / patient |"
)
for v in variants:
    print(
        f"| {v['bound']} | {v['patient']} | {v['min_earliest']} | {v['margin']} | {v['blockable_genes']} "
        f"| {v['patients_exposed']['true_gene_blockable']} ({v['patients_exposed']['with_latest_onset']}) "
        f"| {v['harmed']} ({v['harmed_uncited']}) | {v['helped']['uncited']} / {v['helped']['cited']} "
        f"| {v['patients_with_any_block']} | {v['blocked_genes_per_blocked_patient']:.1f} |"
    )
