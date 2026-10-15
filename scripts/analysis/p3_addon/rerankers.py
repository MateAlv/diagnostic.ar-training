"""The earlier re-rankers plugged on top of the v4 network, read out of fold on `p3-v1` train folds 0-3.

Base scores are logits.py's cache: each patient scored by the network that never trained on its fold, and by
E0 (present terms only). Each re-ranker runs through its own released code, unchanged, on both bases:
- rerank-v1.0.0: `rerank.model.ReRanker` with `release_check.REFERENCE` (rr-v1[neg=0.5]) on kb-v3, top 200,
  on the base distribution softmax64(logits);
- ft-v1.1: `v4.addon.Addon` (`ft.bundle.FtResidual`) of `ft-v1.1-c1-lin-all-ens` on `ft-kb-all-v2`, added to
  the logits;
- safe-v1[sex+onset]: `safe.system.SafeV1` with the sex and onset rules of the `safe-kb-v1` bundle, on
  softmax64(logits);
- p3-addon-v1-all (comparison): the add-on's final bundle on `p3-addon-kb-v1`, added to the logits; it was
  fitted on these patients. Its out-of-fold reading (P3-ADDON variant c) is re-read from read.py's ranks.
The re-rankers read every patient input (`patients.load_addon`); the bases never do. Ranks are pessimistic:
the network on its logits, E0 on the softmax, a probability output on itself (softmax64 of the network's
logits must rank as its logits: checked). Per fold and pooled, uncited / uncited in-vocab / cited, and pooled
by the patient's `r1-v1` part (train or dev), capped MRR Δ with the publication-cluster bootstrap
(`v4.report`): network + R vs network and vs E0, E0 + R vs E0.
Writes results/P3/rerankers/oof.json. CPU only; no fitting.
Usage: rerankers.py
"""

import json
import time

import numpy as np

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR, cli_ft, cli_safe
from diagnostic_ar_training.eval import final_report, release_check
from diagnostic_ar_training.ft.bundle import Knowledge, softmax64
from diagnostic_ar_training.ft.system import case_inputs
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb as kb_io
from diagnostic_ar_training.rerank.config import rr_v1_reference
from diagnostic_ar_training.rerank.model import ReRanker
from diagnostic_ar_training.safe.bundle import SafeRules
from diagnostic_ar_training.safe.bundle import load as load_safe
from diagnostic_ar_training.safe.system import SafeV1
from diagnostic_ar_training.systems import Scored
from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle
from diagnostic_ar_training.v4 import addon, patients, report
from diagnostic_ar_training.v4.runs import E0_RUN, ranks_dir

FOLDS = (0, 1, 2, 3)
BASES = ("network", "E0")
FT_BUNDLE, FT_KB = "ft-v1.1-c1-lin-all-ens", "ft-kb-all-v2"
SAFE_KB, SAFE_RULES = "safe-kb-v1", ("sex", "onset")
ADDON_KB, ADDON_BUNDLE = "p3-addon-kb-v1", "p3-addon-v1-all"
RERANKERS = ("rerank-v1.0.0", "ft-v1.1", "safe-v1[sex+onset]", ADDON_BUNDLE)
ADDON_OOF = "p3-addon-c-oof"
R1_PARTS = ("train", "dev")
CROSSFIT_POOLED_UNCITED = 0.0714


class Cached:
    """A `System` over cached logits: softmax64 of the case's base logits (None when unscorable)."""

    name = "cached"

    def __init__(self, genes, logits: dict[str, np.ndarray]) -> None:
        self.genes, self.logits = tuple(genes), logits

    def lineage_inputs(self) -> list[dict]:
        return []

    def score(self, case) -> Scored:
        s = self.logits.get(case.case_id)
        return Scored(None if s is None else softmax64(s))


start = time.perf_counter()
state = code_state()
inputs = V3Inputs(unpack_bundle())
genes = inputs.genes
embeddings = (inputs.emb_index, inputs.vectors)

members = patients.load_addon(FOLDS)
by_fold = {k: [p for p in members if p.fold == k] for k in FOLDS}
order = [p for k in FOLDS for p in by_fold[k]]
logits = {b: {} for b in BASES}
runs = {}
for k in FOLDS:
    with np.load(addon.ADDON_DIR / f"logits-f{k}.npz") as z:
        ids_k, genes_k, run = list(z["case_id"]), tuple(z["genes"]), str(z["run"])
        arrays = {b: (z[b], z[f"{b}_ok"]) for b in ("net", "e0")}
    assert ids_k == [p.case_id for p in by_fold[k]], f"fold {k}: cache order"
    assert genes_k == tuple(genes)
    runs[k] = run
    for base, key in (("network", "net"), ("E0", "e0")):
        values, ok = arrays[key]
        logits[base].update({c: values[i] for i, c in enumerate(ids_k) if ok[i]})

r1 = {
    part: set(ids)
    for part, ids in json.loads((SPLITS_DIR / "r1-v1.json").read_text())["case_ids"].items()
    if part in R1_PARTS
}
r1_part = {p.case_id: next((part for part in R1_PARTS if p.case_id in r1[part]), "other") for p in order}

config = rr_v1_reference(release_check.KB_ID)
assert config.config_hash == final_report.CONFIG_HASHES["rerank-v1.0.0"], config.config_hash
assert config.top_k == release_check.TOP_K
kb_manifest = load_manifest(release_check.KB_ID)
rr_knowledge = config.knowledge(
    kb_io.read(fetch_outputs(kb_manifest)[0]), Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
)
ft_bundle, ft_bundle_path, _ = cli_ft.verified_bundle(FT_BUNDLE, FT_KB)
ft_kb_path, ft_kb_sha = cli_ft._kb_output(FT_KB)
ft_knowledge = Knowledge(kb_io.read(ft_kb_path), genes, embeddings, FT_KB)
safe_path, safe_sha = cli_safe._kb_output(SAFE_KB, cli_safe.BUNDLE_FILE)
safe_bundle = load_safe(safe_path)
addon_kb, addon_kb_sha = addon.load_kb(ADDON_KB)
addon_bundle, addon_bundle_sha = addon.load_bundle(ADDON_BUNDLE, ADDON_KB)
addon_knowledge = Knowledge(addon_kb, genes, embeddings, ADDON_KB)
residuals = {"ft-v1.1": (addon.Addon(ft_bundle, ft_knowledge), ft_knowledge)}
residuals[ADDON_BUNDLE] = (addon.Addon(addon_bundle, addon_knowledge), addon_knowledge)
systems = {}
for base in BASES:
    cached = Cached(genes, logits[base])
    systems[base] = {
        "rerank-v1.0.0": ReRanker(
            cached, rr_knowledge, release_check.REFERENCE, config.top_k, "rerank-v1.0.0"
        ),
        "safe-v1[sex+onset]": SafeV1(cached, SafeRules(safe_bundle), SAFE_RULES),
    }
assert systems["E0"]["safe-v1[sex+onset]"].name == "safe-v1[sex+onset]"
print(f"{len(order)} patients, knowledge loaded in {time.perf_counter() - start:.0f} s")

lookup = {g.upper(): i for i, g in enumerate(genes)}
variants = ["E0", "network", *(f"{b} + {r}" for b in BASES for r in RERANKERS)]
recs = {v: [] for v in variants}
checks = {"network_softmax_rank_differs": 0, "span_over_745_network": 0}


def record(p, target: int | None, scores: np.ndarray | None, softmax: bool) -> dict:
    r = float("inf") if target is None or scores is None else addon.rank(scores, target, softmax)
    rec = report.record(p, target is not None, scores is not None, r)
    part = r1_part[p.case_id]
    rec["strata"] = rec["strata"] + [f"{s}_r1{part}" for s in ("uncited", "cited") if s in rec["strata"]]
    return rec


for n, p in enumerate(order):
    target = lookup.get(p.case.gene.upper())
    case_in = case_inputs(p.case)
    feats = {name: knowledge.features(case_in) for name, (_, knowledge) in residuals.items()}
    for base in BASES:
        s = logits[base].get(p.case_id)
        softmax = base == "E0"
        recs[base].append(record(p, target, s, softmax))
        if base == "network" and s is not None and target is not None:
            checks["network_softmax_rank_differs"] += addon.rank(s, target, True) != addon.rank(s, target)
            checks["span_over_745_network"] += float(s.max() - s.min()) > 745
        for name, (model, _) in residuals.items():
            out = None if s is None else model.scores(s, case_in, feats[name])
            recs[f"{base} + {name}"].append(record(p, target, out, softmax))
        for name, system in systems[base].items():
            recs[f"{base} + {name}"].append(record(p, target, system.score(p.case).probs, False))
    if n % 500 == 0:
        print(f"{n} / {len(order)} patients, {time.perf_counter() - start:.0f} s", flush=True)

for k in FOLDS:
    name = f"{'select' if k == 3 else 'fit'}.ranks.jsonl"
    for base, run in (("E0", E0_RUN), ("network", runs[k])):
        path = ranks_dir(run) if base == "E0" else ranks_dir(run, "last")
        expected = {r["case_id"]: r["rank"] for r in report.read_ranks(path / name)}
        mine = [r for r in recs[base] if r["fold"] == k]
        checks[f"fold{k}_{base}_ranks_differ_from_harness"] = sum(
            r["rank"] != expected[r["case_id"]] for r in mine
        )
oof = {r["case_id"]: r for r in report.read_ranks(addon.ADDON_DIR / "ranks" / "oof-a.ranks.jsonl")}
checks["network_ranks_differ_from_p3_addon_oof_a"] = sum(
    r["rank"] != oof[r["case_id"]]["rank"] for r in recs["network"]
)
by_id = {r["case_id"]: r for r in recs["network"]}
recs[ADDON_OOF] = [
    {**by_id[r["case_id"]], "rank": r["rank"]}
    for r in report.read_ranks(addon.ADDON_DIR / "ranks" / "oof-c.ranks.jsonl")
]
assert [r["case_id"] for r in recs[ADDON_OOF]] == [r["case_id"] for r in recs["network"]]


def block(rows: dict[str, list[dict]], strata=addon.STRATA) -> dict:
    out = {"network": {"vs_E0": addon.compare(rows["network"], rows["E0"], strata)}}
    for name in (*RERANKERS, ADDON_OOF):
        on_net = rows[name if name == ADDON_OOF else f"network + {name}"]
        out[name] = {
            "network_vs_network": addon.compare(on_net, rows["network"], strata),
            "network_vs_E0": addon.compare(on_net, rows["E0"], strata),
        }
        if name != ADDON_OOF:
            out[name]["E0_vs_E0"] = addon.compare(rows[f"E0 + {name}"], rows["E0"], strata)
    return out


folds = {k: block({v: [r for r in rs if r["fold"] == k] for v, rs in recs.items()}) for k in FOLDS}
by_part = tuple(f"{s}_r1{part}" for s in ("uncited", "cited") for part in R1_PARTS)
pooled = block(recs, addon.STRATA + by_part)
checks["pooled_network_uncited_delta"] = pooled["network"]["vs_E0"]["uncited"]["delta"]["mrr_cap"]
assert round(checks["pooled_network_uncited_delta"], 4) == CROSSFIT_POOLED_UNCITED, checks
assert not any(v for key, v in checks.items() if key.startswith(("fold", "network_"))), checks

out = {
    "cohort": {
        "split": patients.SPLIT,
        "folds": list(FOLDS),
        "patients": len(order),
        "r1_v1_part": {part: sum(v == part for v in r1_part.values()) for part in (*R1_PARTS, "other")},
    },
    "network_runs": runs,
    "rerankers": {
        "rerank-v1.0.0": {
            "config": config.to_dict(),
            "config_hash": config.config_hash,
            "weights": release_check.REFERENCE.as_dict(),
            "kb": release_check.KB_ID,
            "kb_sha256": kb_manifest.outputs[0].sha256,
        },
        "ft-v1.1": {
            "bundle": FT_BUNDLE,
            "kb": FT_KB,
            "kb_sha256": ft_kb_sha,
            "theta": addon.mean_theta(ft_bundle["members"]),
        },
        "safe-v1[sex+onset]": {
            "kb": SAFE_KB,
            "bundle_sha256": safe_sha,
            "rules": list(SAFE_RULES),
            "onset_factor": safe_bundle.get("onset_factor"),
        },
        ADDON_BUNDLE: {
            "kb": ADDON_KB,
            "kb_sha256": addon_kb_sha,
            "bundle_sha256": addon_bundle_sha,
            "theta": addon.mean_theta(addon_bundle["members"]),
        },
        ADDON_OOF: {"ranks": "data/interim/p3-addon/ranks/oof-c.ranks.jsonl (read.py variant c)"},
    },
    "checks": checks,
    "folds": folds,
    "pooled": pooled,
    "seconds": time.perf_counter() - start,
    "code": state.as_dict(),
}
path = RESULTS_DIR / "P3" / "rerankers" / "oof.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, default=str) + "\n")


def cell(x: dict) -> str:
    lo, hi = x["delta_mrr_cap_ci95"]
    return f"{x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}] ({x['helped']} / {x['harmed']})"


for label, b, strata in [
    *((f"fold {k}", folds[k], addon.STRATA) for k in FOLDS),
    ("folds 0-3", pooled, addon.STRATA + by_part),
]:
    print(f"\n## {label}")
    print("| re-ranker | stratum | n | net+R vs net | net+R vs E0 | E0+R vs E0 | Δtop1 / Δtop10 vs net |")
    for s in strata:
        x = b["network"]["vs_E0"][s]
        print(f"| network | {s} | {x['n']} ({x['n_groups']}) | | {cell(x)} | | |")
    for name in (*RERANKERS, ADDON_OOF):
        for s in strata:
            a, e = b[name]["network_vs_network"][s], b[name]["network_vs_E0"][s]
            r = cell(b[name]["E0_vs_E0"][s]) if "E0_vs_E0" in b[name] else ""
            top = f"{a['delta']['top1']:+.4f} / {a['delta']['top10']:+.4f}"
            print(f"| {name} | {s} | {a['n']} | {cell(a)} | {cell(e)} | {r} | {top} |")
print(json.dumps({"checks": checks, "cohort": out["cohort"]}, indent=1))
