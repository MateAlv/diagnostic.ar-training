"""P4-SEX steps 2-3: the hard sex rule (`v4.sexrule`) on the network's out-of-fold logits, p3-v1 train folds
0-3.

Base scores are p3_addon/logits.py's cache: each patient scored by the network that never trained on its fold,
and by E0 (present terms only). The rule reads the recorded sex (`patients.load_addon`); unknown sex changes
nothing. Two sex lists: `p3-addon-kb-v1`'s (safe-v1 rules, the add-on's) and the given `sex-kb` artifact.
- Harm check: every patient whose true gene a list makes impossible for the recorded sex (must be none).
- Readings: network and F1 (network + `p3-addon-v1-all` through `v4.addon.Addon`, the vault-tested candidate;
  it was fitted on these folds, so F1's own Δ is in-sample, the rule's Δ on top of it is not) with each list,
  vs their base, vs E0 and v2 vs v1. Capped and plain MRR Δ with the publication-cluster bootstrap
  (`v4.report`), helped / harmed, and the patients with at least one removed gene above their true gene; per
  fold and pooled; uncited / uncited in-vocab / cited. The network alone must reproduce +0.0714 vs E0 and F1
  P3's +0.000149 vs the network (rerankers.py).
Writes results/P4/sex/oof.json. CPU only; no fitting.
Usage: read.py <sex kb id>   (sex-kb-v2)
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
from diagnostic_ar_training.v4 import addon, patients, report, sexrule

FOLDS = (0, 1, 2, 3)
ADDON_KB, F1_BUNDLE = "p3-addon-kb-v1", "p3-addon-v1-all"
CROSSFIT_POOLED_UNCITED = 0.0714
F1_VS_NETWORK_UNCITED = 0.000149  # results/P3/rerankers/oof.json, network + p3-addon-v1-all vs network
BASES = ("network", "F1")
LISTS = ("v1", "v2")
COMPARISONS = [
    ("network", "E0"),
    *((f"{b} + sex {v}", ref) for b in BASES for v in LISTS for ref in (b, "E0")),
    ("F1", "network"),
    ("F1", "E0"),
    *((f"{b} + sex v2", f"{b} + sex v1") for b in BASES),
]

kb_id = sys.argv[1]
start = time.perf_counter()
state = code_state()
if state.dirty:
    raise SystemExit("commit first: results record the code state")
sex_kb, sex_sha = sexrule.load_kb(kb_id)
addon_kb, addon_sha = addon.load_kb(ADDON_KB)
bundle, bundle_sha = addon.load_bundle(F1_BUNDLE, ADDON_KB)
inputs = V3Inputs(unpack_bundle())
genes = inputs.genes
knowledge = Knowledge(addon_kb, genes, (inputs.emb_index, inputs.vectors), ADDON_KB)
f1 = addon.Addon(bundle, knowledge)
gene_limits = {"v1": sexrule.limits(addon_kb), "v2": sexrule.limits(sex_kb)}
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

variants = ["E0", *BASES, *(f"{b} + sex {v}" for b in BASES for v in LISTS)]
recs = {name: [] for name in variants}
above: dict[str, dict[str, int]] = {f"{b} + sex {v}": {} for b in BASES for v in LISTS}
removed_any = {v: 0 for v in LISTS}


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
        for v in LISTS:
            name = f"{b} + sex {v}"
            mask = rules[v].blocked(sexes[p.case_id])
            new = None if base[b] is None else rules[v].apply(base[b], sexes[p.case_id])
            recs[name].append(record(p, target, new))
            if b == "network" and base[b] is not None:
                removed_any[v] += bool(mask.any())
            if base[b] is not None and target is not None:
                above[name][p.case_id] = int(np.sum(mask & (base[b] > base[b][target])))
    if n % 1000 == 0:
        print(f"{n} / {len(order)} patients, {time.perf_counter() - start:.0f} s", flush=True)

checks = {}
oof_a = {r["case_id"]: r["rank"] for r in report.read_ranks(addon.ADDON_DIR / "ranks" / "oof-a.ranks.jsonl")}
checks["network_ranks_differ_from_p3_addon_oof_a"] = sum(
    r["rank"] != oof_a[r["case_id"]] for r in recs["network"]
)
for b in BASES:
    for v in LISTS:
        worse = sum(
            x["rank"] > y["rank"] for x, y in zip(recs[f"{b} + sex {v}"], recs[b], strict=True) if not harm[v]
        )
        checks[f"{b}_sex_{v}_worse_without_harm"] = worse


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
        "v1": {
            "kb": ADDON_KB,
            "kb_sha256": addon_sha,
            "rules": "safe-v1 sex rules (safe.knowledge.sex_limitation)",
        },
        "v2": {"kb": kb_id, "kb_sha256": sex_sha, "rules": sex_kb["schema"]},
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
    "harm_check": {
        v: {"patients_true_gene_impossible": harm[v], "patients_true_gene_sex_limited": limited_true[v]}
        for v in LISTS
    },
    "checks": checks,
    "folds": folds,
    "pooled": pooled,
    "seconds": time.perf_counter() - start,
    "code": state.as_dict(),
}
path = RESULTS_DIR / "P4" / "sex" / "oof.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, default=str) + "\n")


def cell(x: dict, metric: str) -> str:
    lo, hi = x[f"delta_{metric}_ci95"]
    return f"{x['delta'][metric]:+.4f} [{lo:+.4f}, {hi:+.4f}]"


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
print(
    json.dumps(
        {"checks": checks, "cohort": out["cohort"], "harm": out["harm_check"], "sizes": out["list_sizes"]},
        indent=1,
    )
)
