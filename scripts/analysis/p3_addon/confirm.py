"""PHASE3 §2f step 5 (not run yet): the CONFIRM read of the claimed v4, network and network + add-on vs E0.

Main session only, once the system is frozen (PHASE3 §2f step 4) and the protocol is written:
    DXT_P3_CONFIRM=1 PYTHONPATH=src python scripts/analysis/p3_addon/confirm.py --reason "..."
Fold 4 is opened only through `sim4.folds.cases_in` (DXT_P3_CONFIRM=1, a reason, a row in
results/P3/CONFIRM_LEDGER.md), after every check that needs no patient: a clean tree, the verified knowledge
and bundles, and a network trained with the real patients of folds 0-3 exactly. The network and E0 get the
present terms only; the add-on every input. Writes results/P3/addon/confirm.json and the ranks under
data/interim/p3-addon/confirm/.
"""

import argparse
import json
from collections.abc import Callable, Sequence
from pathlib import Path

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.v4 import addon, report

NETWORK = "R5x-f4-ef2f309462"
KB = "p3-addon-kb-v1"
BUNDLES = ("p3-addon-v1-sex-age-onset", "p3-addon-v1-all")
OUT = RESULTS_DIR / "P3" / "addon" / "confirm.json"
RANKS = addon.ADDON_DIR / "confirm"
TRAINED_ON = [0, 1, 2, 3]


def network_scorer(run_id: str) -> Callable:
    """The network's logits on a patient list; refuses a run that did not train on exactly folds 0-3."""
    from diagnostic_ar_training.v4.evaluate import PatientSet
    from diagnostic_ar_training.v4.runs import Context, load_config, run_dir

    cfg = load_config(run_id)
    if sorted(cfg.sim.real_folds) != TRAINED_ON or not (run_dir(run_id) / "last.pt").is_file():
        raise LineageError(f"{run_id}: needs a final checkpoint trained with the real patients of folds 0-3")

    def score(members):
        ctx = Context("cuda")
        net, cfg = addon.load_network(run_id, ctx)
        pset = PatientSet.build(members, ctx.builder, ctx.genes)
        return addon.network_logits(net, pset, ctx.tables(cfg.encoding.ic_feature), cfg.encoding)

    return score


def knowledge_of(kb: dict, kb_id: str):
    from diagnostic_ar_training.ft.bundle import Knowledge
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle

    inputs = V3Inputs(unpack_bundle())
    return Knowledge(kb, inputs.genes, (inputs.emb_index, inputs.vectors), kb_id)


def code_dirty() -> bool:
    from diagnostic_ar_training.lineage.gitinfo import code_state

    return code_state().dirty


def run(
    reason: str,
    network: str = NETWORK,
    kb_id: str = KB,
    bundle_ids: Sequence[str] = BUNDLES,
    out: Path = OUT,
    ranks: Path = RANKS,
) -> dict:
    if code_dirty():
        raise LineageError("a CONFIRM read runs from a clean, committed tree")
    kb, kb_sha = addon.load_kb(kb_id)
    bundles, shas = {}, {}
    for bundle_id in bundle_ids:
        bundles[bundle_id], shas[bundle_id] = addon.load_bundle(bundle_id, kb_id)
    scorer = network_scorer(network)
    knowledge = knowledge_of(kb, kb_id)
    summary, recs = addon.confirm_read(reason, bundles, knowledge, scorer, addon.e0_logits)
    summary |= {"network_run": network, "kb": {"id": kb_id, "sha256": kb_sha}, "bundles": shas}
    for name, r in recs.items():
        report.write_ranks(Path(ranks) / f"{name}.ranks.jsonl", r)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return summary


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--network", default=NETWORK)
    parser.add_argument("--kb", default=KB)
    parser.add_argument("--bundle", action="append", dest="bundles")
    args = parser.parse_args(argv)
    summary = run(args.reason, args.network, args.kb, args.bundles or BUNDLES)
    for name in ("network", *(args.bundles or BUNDLES)):
        for stratum, x in summary[name]["vs_e0"].items():
            lo, hi = x["delta_mrr_cap_ci95"]
            print(
                f"{name:28} {stratum:17} n {x['n']:5} capped {x['mrr_cap']:.4f} "
                f"Δ vs E0 {x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}] "
                f"helped {x['helped']} harmed {x['harmed']}"
            )


if __name__ == "__main__":
    main()
