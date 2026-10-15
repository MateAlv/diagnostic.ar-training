"""P4-AGE step 3: the chosen hard age rule (`v4.agerule`, `age-v1`: late-onset genes only, margin 30 years,
ages in years) alone and with the hard sex rule (`v4.sexrule`, `sex-kb-v2`), on the network's out-of-fold
logits, p3-v1 train folds 0-3.

Base scores are p3_addon/logits.py's cache, as p4_sex/read.py: the network (each patient scored by the network
that never trained on its fold) and F1 (network + `p3-addon-v1-all` through `v4.addon.Addon`, fitted on these
folds: F1's own Δ is in-sample, the rules' Δ on top of it is not fitted at all). Unknown age and onset change
nothing. Both rules together move the union of their genes below every other gene.
- Harm check of the chosen rule (must be none) and how many patients it could harm at all.
- Readings: each base with the age rule, the sex rule and both, vs the base, vs E0 and both vs sex alone.
  Capped and plain MRR Δ with the publication-cluster bootstrap (`v4.report`), helped / harmed, the patients
  with at least one removed gene above their true gene; per fold and pooled; uncited / uncited in-vocab /
  cited. The network alone must reproduce +0.0714 vs E0, F1 P3's +0.000149 vs the network and the sex rule
  P4-SEX's 130 / 0 (uncited, network).
- What a doctor sees: patients whose top 1 / 5 / 10 / 50 on the network shows a gene the rule blocks.
Writes results/P4/age/oof.json. CPU only; no fitting.
Usage: read.py <age kb id> <sex kb id>   (age-kb-v1 sex-kb-v2)
"""

import json
import sys
import time

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.ft.bundle import Knowledge
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, agerule, patients, report, sexrule

FOLDS = (0, 1, 2, 3)
ADDON_KB, F1_BUNDLE = "p3-addon-kb-v1", "p3-addon-v1-all"
CROSSFIT_POOLED_UNCITED = 0.0714
F1_VS_NETWORK_UNCITED = 0.000149  # results/P3/rerankers/oof.json, network + p3-addon-v1-all vs network
SEX_V2_HELPED_UNCITED = 130  # results/P4/sex/oof.json, network + sex v2 vs network
BASES = ("network", "F1")
RULES = ("age", "sex", "age + sex")
TOPK = (1, 5, 10, 50)
COMPARISONS = [
    ("network", "E0"),
    *((f"{b} + {r}", b) for b in BASES for r in RULES),
    *((f"{b} + age + sex", f"{b} + sex") for b in BASES),
    *((f"{b} + {r}", "E0") for b in BASES for r in ("age", "age + sex")),
    ("F1", "network"),
    ("F1", "E0"),
]

age_id, sex_id = sys.argv[1], sys.argv[2]
start = time.perf_counter()
state = code_state()
if state.dirty:
    raise SystemExit("commit first: results record the code state")
age_kb, age_sha = agerule.load_kb(age_id)
sex_kb, sex_sha = sexrule.load_kb(sex_id)
addon_kb, addon_sha = addon.load_kb(ADDON_KB)
bundle, bundle_sha = addon.load_bundle(F1_BUNDLE, ADDON_KB)
inputs = V3Inputs(unpack_bundle())
genes = inputs.genes
knowledge = Knowledge(addon_kb, genes, (inputs.emb_index, inputs.vectors), ADDON_KB)
f1 = addon.Addon(bundle, knowledge)
age_rule = agerule.AgeRule(agerule.bounds(age_kb), genes)
sex_rule = sexrule.SexRule(sexrule.limits(sex_kb), genes)

members = patients.load_addon(FOLDS)
by_fold = {k: [p for p in members if p.fold == k] for k in FOLDS}
order = [p for k in FOLDS for p in by_fold[k]]
net, e0, runs = {}, {}, {}
for k in FOLDS:
    with np.load(addon.ADDON_DIR / f"logits-f{k}.npz") as z:
        ids_k, genes_k, runs[k] = list(z["case_id"]), tuple(z["genes"]), str(z["run"])
        arrays = {b: (z[b], z[f"{b}_ok"]) for b in ("net", "e0")}
    assert ids_k == [p.case_id for p in by_fold[k]], f"fold {k}: cache order"
    assert genes_k == tuple(genes)
    for out, key in ((net, "net"), (e0, "e0")):
        values, ok = arrays[key]
        out.update({c: values[i] for i, c in enumerate(ids_k) if ok[i]})
    del arrays
print(f"{len(order)} patients loaded in {time.perf_counter() - start:.0f} s", flush=True)

lookup = {g.upper(): i for i, g in enumerate(genes)}
latest = {p.case_id: agerule.case_latest_onset(p.case, agerule.ONSET_CLASSES) for p in order}
masks = {}
for p in order:
    age = age_rule.blocked(latest[p.case_id])
    sex = sex_rule.blocked(p.case.sex)
    masks[p.case_id] = {"age": age, "sex": sex, "age + sex": age | sex}
blockable = np.isfinite(age_rule.earliest)
harm = [
    {"case_id": p.case_id, "gene": p.case.gene, "latest_onset": latest[p.case_id], "status": p.status}
    for p in order
    if (t := lookup.get(p.case.gene.upper())) is not None and masks[p.case_id]["age"][t]
]
exposed = [p.case_id for p in order if (t := lookup.get(p.case.gene.upper())) is not None and blockable[t]]

variants = ["E0", *BASES, *(f"{b} + {r}" for b in BASES for r in RULES)]
recs = {name: [] for name in variants}
above: dict[str, dict[str, int]] = {f"{b} + {r}": {} for b in BASES for r in RULES}
doctor = {r: {k: [0, 0] for k in TOPK} for r in RULES}
doctor_n = {r: 0 for r in RULES}


def record(p, target, scores, softmax=False) -> dict:
    r = float("inf") if target is None or scores is None else addon.rank(scores, target, softmax)
    return report.record(p, target is not None, scores is not None, r)


for n, p in enumerate(order):
    target = lookup.get(p.case.gene.upper())
    s = net.get(p.case_id)
    recs["E0"].append(record(p, target, e0.get(p.case_id), softmax=True))
    case_in = case_inputs(p.case)
    base = {"network": s, "F1": None if s is None else f1.scores(s, case_in, knowledge.features(case_in))}
    for b in BASES:
        recs[b].append(record(p, target, base[b]))
        for r in RULES:
            mask = masks[p.case_id][r]
            new = None if base[b] is None else sexrule.block(base[b], mask)
            recs[f"{b} + {r}"].append(record(p, target, new))
            if base[b] is not None and target is not None:
                above[f"{b} + {r}"][p.case_id] = int(np.sum(mask & (base[b] > base[b][target])))
    if s is not None:
        top = np.argsort(-s, kind="stable")[: max(TOPK)]
        for r in RULES:
            mask = masks[p.case_id][r]
            if not mask.any():
                continue
            doctor_n[r] += 1
            for k in TOPK:
                hit = mask[top[:k]]
                doctor[r][k][0] += bool(hit.any())
                doctor[r][k][1] += int(hit.sum())
    if n % 1000 == 0:
        print(f"{n} / {len(order)} patients, {time.perf_counter() - start:.0f} s", flush=True)


def compare(new: list[dict], ref: list[dict], name: str) -> dict:
    out = addon.compare(new, ref)
    for stratum, x in out.items():
        ids = {r["case_id"] for r in new if stratum in r["strata"]}
        counts = above.get(name, {})
        x["removed_above_true"] = sum(counts.get(c, 0) > 0 for c in ids)
    return out


def block(rows: dict[str, list[dict]]) -> dict:
    return {f"{a} vs {b}": compare(rows[a], rows[b], a) for a, b in COMPARISONS}


folds = {k: block({v: [r for r in rs if r["fold"] == k] for v, rs in recs.items()}) for k in FOLDS}
pooled = block(recs)
checks = {
    "pooled_network_uncited_delta": pooled["network vs E0"]["uncited"]["delta"]["mrr_cap"],
    "pooled_F1_vs_network_uncited_delta": pooled["F1 vs network"]["uncited"]["delta"]["mrr_cap"],
    "network_sex_helped_uncited": pooled["network + sex vs network"]["uncited"]["helped"],
    "age_harmed": len(harm),
    "rules_worse_any_patient": sum(
        x["rank"] > y["rank"]
        for b in BASES
        for r in RULES
        for x, y in zip(recs[f"{b} + {r}"], recs[b], strict=True)
    ),
}
assert round(checks["pooled_network_uncited_delta"], 4) == CROSSFIT_POOLED_UNCITED, checks
assert round(checks["pooled_F1_vs_network_uncited_delta"], 6) == F1_VS_NETWORK_UNCITED, checks
assert checks["network_sex_helped_uncited"] == SEX_V2_HELPED_UNCITED, checks

out = {
    "cohort": {
        "split": patients.SPLIT,
        "folds": list(FOLDS),
        "patients": len(order),
        "latest_onset_known": sum(v is not None for v in latest.values()),
        "scorable_with_any_gene_removed": {r: sum(bool(masks[c][r].any()) for c in net) for r in RULES},
    },
    "network_runs": runs,
    "age_rule": {
        "kb": age_id,
        "kb_sha256": age_sha,
        "variant": "age-v1",
        "min_earliest_years": age_rule.min_earliest_years,
        "margin_years": age_rule.margin_years,
        "patient_onset_classes": agerule.ONSET_CLASSES,
        "blockable_genes": sorted(g for g, b in zip(genes, blockable, strict=True) if b),
    },
    "sex_rule": {"kb": sex_id, "kb_sha256": sex_sha, "rules": sex_kb["schema"]},
    "F1": {
        "bundle": F1_BUNDLE,
        "bundle_sha256": bundle_sha,
        "kb": ADDON_KB,
        "kb_sha256": addon_sha,
        "theta": addon.mean_theta(bundle["members"]),
    },
    "harm_check": {"patients_true_gene_blocked": harm, "patients_true_gene_blockable": len(exposed)},
    "doctor_view": {
        r: {"patients_with_any_block": doctor_n[r]}
        | {f"top{k}": {"patients": v[0], "genes": v[1]} for k, v in doctor[r].items()}
        for r in RULES
    },
    "checks": checks,
    "folds": folds,
    "pooled": pooled,
    "seconds": time.perf_counter() - start,
    "code": state.as_dict(),
}
path = RESULTS_DIR / "P4" / "age" / "oof.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, default=str) + "\n")


def cell(x: dict, metric: str) -> str:
    lo, hi = x[f"delta_{metric}_ci95"]
    return f"{x['delta'][metric]:+.2e} [{lo:+.2e}, {hi:+.2e}]"


for label, b in [*((f"fold {k}", folds[k]) for k in FOLDS), ("folds 0-3", pooled)]:
    print(f"\n## {label}")
    print(
        "| comparison | stratum | n (pubs) | capped MRR (ref) | Δ capped [CI] | Δ MRR [CI] | helped / harmed "
        "| removed above |"
    )
    for name, rows in b.items():
        for s in addon.STRATA:
            x = rows[s]
            print(
                f"| {name} | {s} | {x['n']} ({x['n_groups']}) "
                f"| {x['mrr_cap']:.4f} ({x['e0']['mrr_cap']:.4f}) | {cell(x, 'mrr_cap')} | {cell(x, 'mrr')} "
                f"| {x['helped']} / {x['harmed']} | {x['removed_above_true']} |"
            )
print(json.dumps({k: out[k] for k in ("checks", "cohort", "harm_check", "doctor_view")}, indent=1))
