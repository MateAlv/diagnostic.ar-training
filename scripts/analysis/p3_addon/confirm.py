"""PHASE3 §2f step 5: the CONFIRM read of the claimed v4, network and network + add-on vs E0 (P3-CONFIRM).

Main session only, once the system is frozen (PHASE3 §2f step 4) and the protocol is written:
    DXT_P3_CONFIRM=1 PYTHONPATH=src python scripts/analysis/p3_addon/confirm.py --reason "..."
Fold 4 is opened only through `sim4.folds.cases_in` (DXT_P3_CONFIRM=1, a reason, a row in
results/P3/CONFIRM_LEDGER.md), after every check that needs no patient: a clean tree, the verified knowledge
and bundles, and a network trained with the real patients of folds 0-3 exactly. The network and E0 get the
present terms only; the add-on every input. Writes results/P3/addon/confirm.json and the ranks under
data/interim/p3-addon/confirm/.

Controls on the same patients, network vs E0 (P3-BATCH1-DIAG §10-§11):
- phenotype swap (`patients.phenotype_swap` within the fold): capped Δ, and the true gene's raw rank split by
  whether the gene has real patients in folds 0-3;
- parent terms: every present term moved to a seeded parent, both scored on them.

`--dry-run` runs everything on fold 3 instead (in-sample for this network, so its numbers mean nothing),
without the gate or the ledger, and writes under the scratch directory given: it checks the code path before
the read.
"""

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.v4 import addon, patients, report

NETWORK = "R5x-f4-ef2f309462"
KB = "p3-addon-kb-v1"
BUNDLES = ("p3-addon-v1-all", "p3-addon-v1-sex-age-onset")
OUT = RESULTS_DIR / "P3" / "addon" / "confirm.json"
RANKS = addon.ADDON_DIR / "confirm"
TRAINED_ON = [0, 1, 2, 3]
PARENT_SEED = 1


def network_scorer(run_id: str) -> Callable:
    """The network's logits on a patient list; refuses a run that did not train on exactly folds 0-3."""
    from diagnostic_ar_training.v4.evaluate import PatientSet
    from diagnostic_ar_training.v4.runs import Context, load_config, run_dir

    cfg = load_config(run_id)
    if sorted(cfg.sim.real_folds) != TRAINED_ON or not (run_dir(run_id) / "last.pt").is_file():
        raise LineageError(f"{run_id}: needs a final checkpoint trained with the real patients of folds 0-3")
    loaded = {}

    def score(members):
        if not loaded:
            ctx = Context("cuda")
            net, net_cfg = addon.load_network(run_id, ctx)
            loaded.update(ctx=ctx, net=net, cfg=net_cfg)
        ctx, net, net_cfg = loaded["ctx"], loaded["net"], loaded["cfg"]
        pset = PatientSet.build(members, ctx.builder, ctx.genes)
        return addon.network_logits(net, pset, ctx.tables(net_cfg.encoding.ic_feature), net_cfg.encoding)

    return score


def knowledge_of(kb: dict, kb_id: str):
    from diagnostic_ar_training.ft.bundle import Knowledge
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle

    inputs = V3Inputs(unpack_bundle())
    return Knowledge(kb, inputs.genes, (inputs.emb_index, inputs.vectors), kb_id)


def code_dirty() -> bool:
    from diagnostic_ar_training.lineage.gitinfo import code_state

    return code_state().dirty


def training_genes() -> set[str]:
    """Genes with real patients in the network's training folds (0-3)."""
    return {p.case.gene.upper() for p in patients.load_folds(TRAINED_ON)}


def parent_mapper() -> Callable[[str], str]:
    """Each present term to one of its finding parents (seeded), as `r5_checks.py` and `crossfit.py`."""
    from diagnostic_ar_training.sim4 import load_knowledge

    knowledge, rng = load_knowledge(), np.random.default_rng(PARENT_SEED)

    def to_parent(term: str) -> str:
        t = knowledge.ontology.resolve(term)
        if not (t and knowledge.is_finding(t)):
            return term
        parents = sorted(a for a in knowledge.ontology.parents(t) if knowledge.is_finding(a))
        return parents[rng.integers(len(parents))] if parents else t

    return to_parent


def swap_ranks(e0: Sequence[dict], net: Sequence[dict], with_patients: set[str]) -> dict:
    """The true gene's raw rank under phenotype swap, uncited in-vocabulary, split by `with_patients`."""
    by_id = {r["case_id"]: r for r in net}
    out = {}
    for label, keep in (("gene_with_training_patients", True), ("gene_without", False)):
        pairs = [
            (r["rank"], by_id[r["case_id"]]["rank"])
            for r in e0
            if "uncited_in_vocab" in r["strata"] and (r["gene"].upper() in with_patients) == keep
        ]
        pairs = [(x, y) for x, y in pairs if np.isfinite(x) and np.isfinite(y)]
        a, b = (np.array(x, dtype=float) for x in zip(*pairs, strict=True)) if pairs else (np.zeros(0),) * 2
        out[label] = {
            "n": len(pairs),
            "median_rank_e0": float(np.median(a)) if pairs else None,
            "median_rank_network": float(np.median(b)) if pairs else None,
            "mean_log2_ratio": float(np.mean(np.log2(b / a))) if pairs else None,
            "improved": float(np.mean(b < a)) if pairs else None,
        }
    return out


def controls(
    members: Sequence[patients.Patient],
    score: Callable,
    e0_score: Callable,
    genes: Sequence[str],
    with_patients: set[str],
    to_parent: Callable[[str], str],
) -> tuple[dict, dict[str, list[dict]]]:
    """Phenotype-swap and parent-term readings of the network vs E0 on `members` (present terms only)."""
    view = addon.network_view(members)
    swapped, _ = patients.phenotype_swap(view)
    moved = [
        patients.Patient(
            p.case.model_copy(update={"present": tuple(to_parent(x) for x in p.case.present)}),
            p.group,
            p.status,
            p.fold,
        )
        for p in view
    ]
    recs = {}
    for name, inputs in (("swap", swapped), ("parent", moved)):
        recs[f"E0_{name}"] = addon.records(view, e0_score(inputs), genes, softmax=True)
        recs[f"network_{name}"] = addon.records(view, score(inputs), genes)
    summary = {
        "swap": {
            "vs_e0": addon.compare(recs["network_swap"], recs["E0_swap"]),
            "raw_rank": swap_ranks(recs["E0_swap"], recs["network_swap"], with_patients),
        },
        "parent": {"vs_e0": addon.compare(recs["network_parent"], recs["E0_parent"])},
    }
    return summary, recs


def run(
    reason: str,
    network: str = NETWORK,
    kb_id: str = KB,
    bundle_ids: Sequence[str] = BUNDLES,
    out: Path = OUT,
    ranks: Path = RANKS,
    dry_run: bool = False,
) -> dict:
    if code_dirty() and not dry_run:
        raise LineageError("a CONFIRM read runs from a clean, committed tree")
    kb, kb_sha = addon.load_kb(kb_id)
    bundles, shas = {}, {}
    for bundle_id in bundle_ids:
        bundles[bundle_id], shas[bundle_id] = addon.load_bundle(bundle_id, kb_id)
    scorer = network_scorer(network)
    knowledge = knowledge_of(kb, kb_id)
    with_patients, to_parent = training_genes(), parent_mapper()
    opened: dict[str, list[patients.Patient]] = {}

    def load(why: str) -> list[patients.Patient]:
        opened["members"] = patients.load_addon((3,)) if dry_run else addon.confirm_patients(why)
        return opened["members"]

    summary, recs = addon.confirm_read(reason, bundles, knowledge, scorer, addon.e0_logits, load)
    summary["controls"], control_recs = controls(
        opened["members"], scorer, addon.e0_logits, knowledge.genes, with_patients, to_parent
    )
    summary |= {
        "network_run": network,
        "kb": {"id": kb_id, "sha256": kb_sha},
        "bundles": shas,
        "dry_run_fold_3": dry_run,
    }
    for name, r in (recs | control_recs).items():
        report.write_ranks(Path(ranks) / f"{name}.ranks.jsonl", r)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return summary


def show(label: str, readings: dict) -> None:
    for stratum, x in readings.items():
        lo, hi = x["delta_mrr_cap_ci95"]
        print(
            f"{label:34} {stratum:17} n {x['n']:5} capped {x['mrr_cap']:.4f} (base {x['e0']['mrr_cap']:.4f}) "
            f"Δ {x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}] helped {x['helped']} harmed {x['harmed']}"
        )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--network", default=NETWORK)
    parser.add_argument("--kb", default=KB)
    parser.add_argument("--bundle", action="append", dest="bundles")
    parser.add_argument("--dry-run", type=Path, metavar="SCRATCH_DIR")
    args = parser.parse_args(argv)
    paths = {}
    if args.dry_run:
        paths = {"out": args.dry_run / "confirm.json", "ranks": args.dry_run / "ranks", "dry_run": True}
    bundles = args.bundles or BUNDLES
    summary = run(args.reason, args.network, args.kb, bundles, **paths)
    show("network vs E0", summary["network"]["vs_e0"])
    for name in bundles:
        show(f"{name} vs E0", summary[name]["vs_e0"])
        show(f"{name} vs network", summary[name]["vs_network"])
    show("swap: network vs E0", summary["controls"]["swap"]["vs_e0"])
    show("parent terms: network vs E0", summary["controls"]["parent"]["vs_e0"])
    for label, x in summary["controls"]["swap"]["raw_rank"].items():
        print(f"swap raw rank, uncited in-vocab, {label}: {x}")


if __name__ == "__main__":
    main()
