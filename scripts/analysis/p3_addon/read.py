"""PHASE3 §2f step 2: the add-on (`v4.addon`) refitted on the network's out-of-fold scores, read out of fold.

Base logits come from logits.py: each patient of folds 0-3 scored by the network that never trained on it,
and by E0. For each fold k the residual is fitted (ft-v1.1's recipe, seeds 0-2, early stopping on held-out
publication groups of the fitting patients) on the patients of the other three folds and applied to fold k:
  a: network alone;  b: network + add-on, sex / age / onset features;  c: network + add-on, every feature;
  d: E0 + add-on, every feature (reference).
Capped MRR, Δ vs E0 and vs (a) with the publication-cluster bootstrap (`v4.report`), per fold and pooled.
(a) and E0 must reproduce crossfit.py's ranks exactly (and its pooled uncited Δ, +0.0714).
Then the final fit of b and c on all of folds 0-3, saved as bundles with manifests (needs a clean tree).
Writes results/P3/addon/oof.json, ranks under data/interim/p3-addon/ranks/ and the bundles under
data/interim/p3-addon/. CPU only (the GPU is left to training).
Usage: read.py <kb_id> <bundle prefix>   (p3-addon-kb-v1 p3-addon-v1)
"""

import json
import sys
import time

import numpy as np
import torch

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.ft.bundle import Knowledge
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, patients, report
from diagnostic_ar_training.v4.runs import E0_RUN, ranks_dir

torch.set_num_threads(8)
FOLDS = (0, 1, 2, 3)
VARIANTS = {"b": ("net", "sex-age-onset"), "c": ("net", "all"), "d": ("e0", "all")}
CROSSFIT_POOLED_UNCITED = 0.0714
REPORTED = ("uncited", "uncited_in_vocab", "cited")

kb_id, prefix = sys.argv[1], sys.argv[2]
final_ids = {fs: f"{prefix}-{fs}" for fs in ("sex-age-onset", "all")}
for bundle_id in final_ids.values():
    ensure_new(bundle_id)
state = code_state()
if state.dirty:
    raise SystemExit("commit first: the final bundles get manifests")
start = time.perf_counter()
kb, kb_sha = addon.load_kb(kb_id)
inputs = V3Inputs(unpack_bundle())
genes = inputs.genes
knowledge = Knowledge(kb, genes, (inputs.emb_index, inputs.vectors), kb_id)
members = patients.load_addon(FOLDS)
by_fold = {k: [p for p in members if p.fold == k] for k in FOLDS}
cache_paths = {k: addon.ADDON_DIR / f"logits-f{k}.npz" for k in FOLDS}
cache = {k: np.load(path) for k, path in cache_paths.items()}
runs = {k: str(cache[k]["run"]) for k in FOLDS}
for k in FOLDS:
    assert list(cache[k]["case_id"]) == [p.case_id for p in by_fold[k]], f"fold {k}: cache order"
    assert tuple(cache[k]["genes"]) == tuple(genes)
order = [p for k in FOLDS for p in by_fold[k]]
ids = [p.case_id for p in order]
groups = [p.group for p in order]
fold = np.array([p.fold for p in order])
logits = {b: np.concatenate([cache[k][b] for k in FOLDS]) for b in ("net", "e0")}
ok = {b: np.concatenate([cache[k][f"{b}_ok"] for k in FOLDS]) for b in ("net", "e0")}
lookup = {g.upper(): i for i, g in enumerate(genes)}
target = np.array([lookup.get(p.case.gene.upper(), -1) for p in order])
case_in = [case_inputs(p.case) for p in order]
feats, z = addon.features(order, knowledge)
print(f"{len(order)} patients, features in {time.perf_counter() - start:.0f} s")


def recs(base: str, rows, model=None) -> list[dict]:
    scores = {}
    for i in rows:
        if ok[base][i]:
            s = logits[base][i]
            scores[ids[i]] = s if model is None else model.scores(s, case_in[i], feats[i])
    return addon.records([order[i] for i in rows], scores, genes, softmax=base == "e0")


def fit_rows(base: str, keep: np.ndarray) -> np.ndarray:
    return np.flatnonzero(keep & ok[base] & (target >= 0))


def fitted(base: str, feature_set: str, rows: np.ndarray, label: str) -> tuple[dict, list[dict]]:
    found, info = addon.fit(
        [ids[i] for i in rows],
        [groups[i] for i in rows],
        logits[base][rows],
        feats[rows],
        z[rows],
        target[rows],
        addon.FEATURE_SETS[feature_set],
        log=lambda m: None,
    )
    model_ids = [f"{label}-s{s}" for s in addon.SEEDS]
    return addon.bundle(kb_id, found, model_ids, base=base, feature_set=feature_set), info


rows_of = {k: np.flatnonzero(fold == k) for k in FOLDS}
out = {"kb": {"id": kb_id, "sha256": kb_sha}, "runs": runs, "folds": {}, "checks": {}}
all_recs = {v: [] for v in ("E0", "a", "b", "c", "d")}
untrained = addon.Addon(addon.untrained(kb_id), knowledge)
for k in FOLDS:
    rows = rows_of[k]
    e0 = recs("e0", rows)
    a = recs("net", rows)
    name = f"{'select' if k == 3 else 'fit'}.ranks.jsonl"
    file_e0 = {r["case_id"]: r["rank"] for r in report.read_ranks(ranks_dir(E0_RUN) / name)}
    file_a = {r["case_id"]: r["rank"] for r in report.read_ranks(ranks_dir(runs[k], "last") / name)}
    out["checks"][f"fold{k}_e0_ranks_differ_from_R0"] = sum(r["rank"] != file_e0[r["case_id"]] for r in e0)
    out["checks"][f"fold{k}_net_ranks_differ_from_run"] = sum(r["rank"] != file_a[r["case_id"]] for r in a)
    same = recs("net", rows, untrained)
    out["checks"][f"fold{k}_untrained_addon_ranks_differ"] = sum(
        x["rank"] != y["rank"] for x, y in zip(a, same, strict=True)
    )
    fold_out = {"n": len(rows), "variants": {}}
    fold_recs = {"E0": e0, "a": a}
    for v, (base, feature_set) in VARIANTS.items():
        t0 = time.perf_counter()
        b, info = fitted(base, feature_set, fit_rows(base, fold != k), f"{v}-f{k}")
        fold_recs[v] = recs(base, rows, addon.Addon(b, knowledge))
        fold_out["variants"][v] = {
            "base": base,
            "feature_set": feature_set,
            "fit_rows": int(fit_rows(base, fold != k).size),
            "theta": addon.mean_theta(b["members"]),
            "seeds": info,
            "seconds": time.perf_counter() - t0,
        }
        print(f"fold {k} {v}: θ {np.round(list(fold_out['variants'][v]['theta'].values()), 3)}")
    fold_out["vs_e0"] = {v: addon.compare(fold_recs[v], e0) for v in ("a", "b", "c", "d")}
    fold_out["vs_a"] = {v: addon.compare(fold_recs[v], a) for v in ("b", "c")}
    out["folds"][k] = fold_out
    for v, r in fold_recs.items():
        all_recs[v] += r
for v, r in all_recs.items():
    report.write_ranks(addon.ADDON_DIR / "ranks" / f"oof-{v}.ranks.jsonl", r)
pooled = {
    "vs_e0": {v: addon.compare(all_recs[v], all_recs["E0"]) for v in ("a", "b", "c", "d")},
    "vs_a": {v: addon.compare(all_recs[v], all_recs["a"]) for v in ("b", "c")},
}
out["pooled"] = pooled
a_uncited = pooled["vs_e0"]["a"]["uncited"]["delta"]["mrr_cap"]
out["checks"]["pooled_a_uncited_delta"] = a_uncited
assert round(a_uncited, 4) == CROSSFIT_POOLED_UNCITED, a_uncited
assert not any(v for key, v in out["checks"].items() if key.startswith("fold")), out["checks"]

final = {}
for feature_set, bundle_id in final_ids.items():
    rows = fit_rows("net", np.ones(len(order), bool))
    b, info = fitted("net", feature_set, rows, bundle_id)
    b["fitted_on"] = {
        "patients": "p3-v1 train folds 0-3, in-vocabulary and scorable",
        "rows": int(rows.size),
        "base": "each patient's out-of-fold network logits",
        "runs": runs,
    }
    model = addon.Addon(b, knowledge)
    check = rows[:: max(1, rows.size // 200)]
    direct = addon.score_patients({ids[i]: logits["net"][i] for i in check}, [order[i] for i in check], model)
    agreement = max(
        float(np.abs(direct[ids[i]] - model.scores(logits["net"][i], case_in[i], feats[i])).max())
        for i in check
    )
    path = addon.ADDON_DIR / bundle_id / addon.BUNDLE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(b, indent=1) + "\n")
    lineage = [
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        {"id": f"split:{patients.SPLIT}", "sha256": sha256_file(SPLITS_DIR / f"{patients.SPLIT}.json")},
        *({"id": f"logits:fold{k}:{runs[k]}", "sha256": sha256_file(p)} for k, p in cache_paths.items()),
    ]
    params = {
        "recipe": addon.CONFIG,
        "seeds": list(addon.SEEDS),
        "features": list(addon.FEATURE_SETS[feature_set]),
        "combine": "mean residual",
        "early_stopping": "ft.configs.inner_split held-out publication groups",
        "network_at_use": "R5x-f4-ef2f309462 (trained with folds 0-3)",
    }
    write_manifest(build_manifest(bundle_id, addon.BUNDLE_KIND, lineage, params, [path], state=state))
    final[bundle_id] = {
        "theta": addon.mean_theta(b["members"]),
        "seeds": info,
        "rows": int(rows.size),
        "scorer_agreement_max_abs": agreement,
        "sha256": sha256_file(path),
    }
out["final"] = final
out["seconds"] = time.perf_counter() - start
out["code"] = state.as_dict()
path = RESULTS_DIR / "P3" / "addon" / "oof.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, default=str) + "\n")

NAMES = {"a": "network", "b": "+ add-on sex/age/onset", "c": "+ add-on all", "d": "E0 + add-on all"}


def cell(x: dict, metric: str = "mrr_cap") -> str:
    lo, hi = x[f"delta_{metric}_ci95"]
    return f"{x['delta'][metric]:+.4f} [{lo:+.4f}, {hi:+.4f}]"


for label, block in [*((f"fold {k}", out["folds"][k]) for k in FOLDS), ("folds 0-3", pooled)]:
    print(f"\n## {label}")
    print(
        "| variant | stratum | n (pubs) | capped MRR (E0) | Δ vs E0 [CI] | helped / harmed | Δ vs a [CI] "
        "| h/h vs a |"
    )
    for v in ("a", "b", "c", "d"):
        for s in REPORTED:
            x = block["vs_e0"][v][s]
            y = block["vs_a"].get(v, {}).get(s)
            va = f"{cell(y)} | {y['helped']} / {y['harmed']}" if y else " | "
            print(
                f"| {NAMES[v]} | {s} | {x['n']} ({x['n_groups']}) | {x['mrr_cap']:.4f} "
                f"({x['e0']['mrr_cap']:.4f}) | {cell(x)} | {x['helped']} / {x['harmed']} | {va} |"
            )
print(json.dumps(out["checks"], indent=1))
print(json.dumps({k: v["theta"] for k, v in final.items()}, indent=1))
