"""P4-SEX steps 2-3: the hard sex rule (`v4.sexrule`) on the network's out-of-fold logits, p3-v1 train folds
0-3.

Base scores are p3_addon/logits.py's cache: each patient scored by the network that never trained on its fold,
and by E0 (present terms only). The rule reads the recorded sex (`patients.load_addon`); unknown sex changes
nothing. Two sex lists: an earlier one (`p3-addon-kb-v1`'s, safe-v1 rules, the add-on's, by default; or an
earlier `sex-kb`) and the given `sex-kb` artifact, labelled by their version ("v1" for the add-on's list).
- Harm check: every patient whose true gene a list makes impossible for the recorded sex (must be none).
- Readings: network and F1 (network + `p3-addon-v1-all` through `v4.addon.Addon`, the vault-tested candidate;
  it was fitted on these folds, so F1's own Δ is in-sample, the rule's Δ on top of it is not) with each list,
  vs their base, vs E0 and the new list vs the earlier one. The add-on on top of the network + the new list
  (F1 + rule vs network + rule), also with the add-on cross-fitted out of fold (`F1oof`: for fold k, the seeds
  P3-ADDON's variant c fitted without fold k, from results/P3/addon/oof.json; their ranks must equal
  `oof-c`). Capped and plain MRR Δ with the publication-cluster bootstrap (`v4.report`), helped / harmed, and
  the patients with at least one removed gene above their true gene; per fold and pooled; uncited / uncited
  in-vocab / cited. The network alone must reproduce +0.0714 vs E0 and F1 P3's +0.000149 vs the network
  (rerankers.py).
- What a doctor would see without the rule: patients of known sex whose network or F1 top 1 / 5 / 10 / 50
  shows a gene the new list makes impossible for them (`sexrule.shown`).
Writes results/P4/sex/oof-<kb id>.json (sex-kb-v2's reading, from an earlier version of this script, is
results/P4/sex/oof.json). CPU only; no fitting.
Usage: read.py <sex kb id> [<earlier list>]   (sex-kb-v2;  sex-kb-v3 sex-kb-v2)
"""

import json
import sys
import time

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.ft.bundle import FEATURES, Knowledge
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, patients, report, sexrule

FOLDS = (0, 1, 2, 3)
ADDON_KB, F1_BUNDLE = "p3-addon-kb-v1", "p3-addon-v1-all"
CROSSFIT_POOLED_UNCITED = 0.0714
F1_VS_NETWORK_UNCITED = 0.000149  # results/P3/rerankers/oof.json, network + p3-addon-v1-all vs network
CROSSFIT_VARIANT = "c"
BASES = ("network", "F1", "F1oof")
OOF_RANKS = addon.ADDON_DIR / "ranks"


def label(list_id: str) -> str:
    return "v1" if list_id == ADDON_KB else list_id.removeprefix("sex-kb-")


kb_id = sys.argv[1]
before_id = sys.argv[2] if len(sys.argv) > 2 else ADDON_KB
OLD, NEW = LISTS = (label(before_id), label(kb_id))
COMPARISONS = [
    ("network", "E0"),
    *((f"{b} + sex {v}", ref) for b in BASES[:2] for v in LISTS for ref in (b, "E0")),
    ("F1", "network"),
    ("F1", "E0"),
    *((f"{b} + sex {NEW}", f"{b} + sex {OLD}") for b in BASES[:2]),
    (f"F1 + sex {NEW}", f"network + sex {NEW}"),
    ("F1oof", "network"),
    (f"F1oof + sex {NEW}", f"network + sex {NEW}"),
]
start = time.perf_counter()
state = code_state()
if state.dirty:
    raise SystemExit("commit first: results record the code state")
sex_kb, sex_sha = sexrule.load_kb(kb_id)
before_kb, before_sha = addon.load_kb(before_id) if before_id == ADDON_KB else sexrule.load_kb(before_id)
addon_kb, addon_sha = addon.load_kb(ADDON_KB)
bundle, bundle_sha = addon.load_bundle(F1_BUNDLE, ADDON_KB)
inputs = V3Inputs(unpack_bundle())
genes = inputs.genes
knowledge = Knowledge(addon_kb, genes, (inputs.emb_index, inputs.vectors), ADDON_KB)
f1 = addon.Addon(bundle, knowledge)
crossfit = json.loads((RESULTS_DIR / "P3" / "addon" / "oof.json").read_text())
fold_addons = {}
for k in FOLDS:
    variant = crossfit["folds"][str(k)]["variants"][CROSSFIT_VARIANT]
    seeds = [
        {
            "active_features": list(addon.FEATURE_SETS[variant["feature_set"]]),
            "active_covariates": [],
            "theta": [seed["theta"][f] for f in FEATURES],
            "mlp": None,
        }
        for seed in variant["seeds"]
    ]
    model_ids = [f"{CROSSFIT_VARIANT}-f{k}-s{s}" for s in addon.SEEDS]
    fold_addons[k] = addon.Addon(addon.bundle(ADDON_KB, seeds, model_ids), knowledge)
gene_limits = {OLD: sexrule.limits(before_kb), NEW: sexrule.limits(sex_kb)}
rules = {v: sexrule.SexRule(gene_limits[v], genes) for v in LISTS}

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
sexes = {p.case_id: sexrule.sex_of(p.case.sex) for p in order}
harm = {
    v: [
        {
            "case_id": p.case_id,
            "sex": sexes[p.case_id],
            "gene": p.case.gene,
            "limit": gene_limits[v][p.case.gene.upper()],
            "status": p.status,
            "fold": p.fold,
            "group": p.group,
            "pmids": list(p.case.pmids),
        }
        for p in order
        if sexes[p.case_id] and gene_limits[v].get(p.case.gene.upper(), sexes[p.case_id]) != sexes[p.case_id]
    ]
    for v in LISTS
}
limited_true = {
    v: sum(bool(sexes[p.case_id]) and p.case.gene.upper() in gene_limits[v] for p in order) for v in LISTS
}

ruled = [*(f"{b} + sex {v}" for b in BASES[:2] for v in LISTS), f"F1oof + sex {NEW}"]
recs = {name: [] for name in ("E0", *BASES, *ruled)}
above: dict[str, dict[str, int]] = {name: {} for name in ruled}
removed_any = {v: 0 for v in LISTS}
doctor = {b: {k: [0, 0] for k in sexrule.TOP_K} for b in BASES[:2]}
shown_after = 0
n_sex_scored = 0


def record(p, target, scores, softmax=False) -> dict:
    r = float("inf") if target is None or scores is None else addon.rank(scores, target, softmax)
    return report.record(p, target is not None, scores is not None, r)


for n, p in enumerate(order):
    target = lookup.get(p.case.gene.upper())
    s = net.get(p.case_id)
    recs["E0"].append(record(p, target, e0.get(p.case_id), softmax=True))
    case_in = case_inputs(p.case)
    feats = None if s is None else knowledge.features(case_in)
    base = {"network": s}
    for b, model in (("F1", f1), ("F1oof", fold_addons[p.fold])):
        base[b] = None if s is None else model.scores(s, case_in, feats)
    sex = sexes[p.case_id]
    n_sex_scored += s is not None and sex is not None
    for b in BASES:
        recs[b].append(record(p, target, base[b]))
        for v in (NEW,) if b == "F1oof" else LISTS:
            name = f"{b} + sex {v}"
            mask = rules[v].blocked(sex)
            new = None if base[b] is None else rules[v].apply(base[b], sex)
            recs[name].append(record(p, target, new))
            if b == "network" and base[b] is not None:
                removed_any[v] += bool(mask.any())
            if base[b] is not None and target is not None:
                above[name][p.case_id] = int(np.sum(mask & (base[b] > base[b][target])))
            if b in doctor and v == NEW and new is not None and mask.any():
                for k, hits in sexrule.shown(base[b], mask).items():
                    doctor[b][k][0] += hits > 0
                    doctor[b][k][1] += hits
                shown_after += sexrule.shown(new, mask)[max(sexrule.TOP_K)]
    if n % 1000 == 0:
        print(f"{n} / {len(order)} patients, {time.perf_counter() - start:.0f} s", flush=True)

checks = {}
oof_ranks = {
    v: {r["case_id"]: r["rank"] for r in report.read_ranks(OOF_RANKS / f"oof-{v}.ranks.jsonl")}
    for v in ("a", CROSSFIT_VARIANT)
}
checks["network_ranks_differ_from_p3_addon_oof_a"] = sum(
    r["rank"] != oof_ranks["a"][r["case_id"]] for r in recs["network"]
)
checks[f"F1oof_ranks_differ_from_p3_addon_oof_{CROSSFIT_VARIANT}"] = sum(
    r["rank"] != oof_ranks[CROSSFIT_VARIANT][r["case_id"]] for r in recs["F1oof"]
)
for name in ruled:
    b, v = name.split(" + sex ")
    worse = sum(x["rank"] > y["rank"] for x, y in zip(recs[name], recs[b], strict=True) if not harm[v])
    checks[f"{b}_sex_{v}_worse_without_harm"] = worse
checks[f"sex_{NEW}_impossible_genes_in_top_{max(sexrule.TOP_K)}_after_the_rule"] = shown_after


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
checks["pooled_network_uncited_delta"] = pooled["network vs E0"]["uncited"]["delta"]["mrr_cap"]
checks["pooled_F1_vs_network_uncited_delta"] = pooled["F1 vs network"]["uncited"]["delta"]["mrr_cap"]
assert round(checks["pooled_network_uncited_delta"], 4) == CROSSFIT_POOLED_UNCITED, checks
assert round(checks["pooled_F1_vs_network_uncited_delta"], 6) == F1_VS_NETWORK_UNCITED, checks
assert not any(v for key, v in checks.items() if not key.startswith("pooled_")), checks

out = {
    "cohort": {
        "split": patients.SPLIT,
        "folds": list(FOLDS),
        "patients": len(order),
        "sex": {s: sum(v == s for v in sexes.values()) for s in sexrule.SEXES}
        | {"unknown": sum(v is None for v in sexes.values())},
        "scorable_with_any_gene_removed": removed_any,
    },
    "network_runs": runs,
    "lists": {
        OLD: {
            "kb": before_id,
            "kb_sha256": before_sha,
            "rules": "safe-v1 sex rules (safe.knowledge.sex_limitation)"
            if before_id == ADDON_KB
            else before_kb["schema"],
        },
        NEW: {"kb": kb_id, "kb_sha256": sex_sha, "rules": sex_kb["schema"]},
    },
    "list_sizes": {
        v: {s: sum(x == s for x in gene_limits[v].values()) for s in sexrule.SEXES} for v in LISTS
    },
    "F1": {
        "bundle": F1_BUNDLE,
        "bundle_sha256": bundle_sha,
        "kb": ADDON_KB,
        "theta": addon.mean_theta(bundle["members"]),
    },
    "F1oof": {
        "source": f"results/P3/addon/oof.json, variant {CROSSFIT_VARIANT} of each fold (its seeds' θ)",
        "theta": {k: crossfit["folds"][str(k)]["variants"][CROSSFIT_VARIANT]["theta"] for k in FOLDS},
    },
    "harm_check": {
        v: {"patients_true_gene_impossible": harm[v], "patients_true_gene_sex_limited": limited_true[v]}
        for v in LISTS
    },
    "doctor_view": {
        "list": NEW,
        "patients_sex_known_scored": n_sex_scored,
        "shown_without_the_rule": {
            b: {k: {"patients": x[0], "genes": x[1]} for k, x in by_k.items()} for b, by_k in doctor.items()
        },
    },
    "checks": checks,
    "folds": folds,
    "pooled": pooled,
    "seconds": time.perf_counter() - start,
    "code": state.as_dict(),
}
path = RESULTS_DIR / "P4" / "sex" / f"oof-{kb_id}.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, default=str) + "\n")


def cell(x: dict, metric: str) -> str:
    lo, hi = x[f"delta_{metric}_ci95"]
    return f"{x['delta'][metric]:+.4f} [{lo:+.4f}, {hi:+.4f}]"


for title, b in [*((f"fold {k}", folds[k]) for k in FOLDS), ("folds 0-3", pooled)]:
    print(f"\n## {title}")
    print(
        "| comparison | stratum | n (pubs) | capped MRR (ref) | Δ capped [CI] | Δ MRR [CI] | helped / harmed "
        "| removed above |"
    )
    for comparison, rows in b.items():
        for s in addon.STRATA:
            x = rows[s]
            print(
                f"| {comparison} | {s} | {x['n']} ({x['n_groups']}) "
                f"| {x['mrr_cap']:.4f} ({x['e0']['mrr_cap']:.4f}) | {cell(x, 'mrr_cap')} | {cell(x, 'mrr')} "
                f"| {x['helped']} / {x['harmed']} | {x['removed_above_true']} |"
            )
summary = ("checks", "cohort", "harm_check", "list_sizes", "doctor_view")
print(json.dumps({key: out[key] for key in summary}, indent=1))
