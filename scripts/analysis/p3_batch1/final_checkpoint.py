"""PHASE3 §2d A1: score a run's final checkpoint (`last.pt`, not chosen on SELECT) on SELECT and FIT vs E0.

Usage: final_checkpoint.py <run_id> [out_dir]. Rank files go to <out_dir>/<run_id>/ranks/ (default
`data/interim/v4/final`); capped and plain Δ vs E0 are printed for the gate strata.
"""

import sys
from pathlib import Path

from diagnostic_ar_training.v4 import evaluate, model, report, train
from diagnostic_ar_training.v4.runs import Context, load_config, run_dir

run = sys.argv[1]
out = Path(sys.argv[2] if len(sys.argv) > 2 else "data/interim/v4/final")
ctx = Context("cuda")
cfg = load_config(run)
net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device)
print("step", train.load_weights(net, run_dir(run) / "last.pt", ctx.device)["step"])
for fold in ("select", "fit"):
    pset = ctx.patient_set(fold, cfg.encoding.covariates)
    records = evaluate.model_records(net, pset, ctx.tables(cfg.encoding.ic_feature), cfg.encoding)
    report.write_ranks(out / run / "ranks" / f"{fold}.ranks.jsonl", records)
    strata = report.summarize(records, ctx.e0_records(fold, print))["strata"]
    for name in ("uncited", "uncited_in_vocab", "cited"):
        x = strata[name]
        lo, hi = x["delta_mrr_cap_ci95"]
        print(
            f"{fold:6} {name:17} capped {x['mrr_cap']:.4f} (E0 {x['e0']['mrr_cap']:.4f})"
            f" Δ {x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}]  plain Δ {x['delta']['mrr']:+.4f}"
        )
