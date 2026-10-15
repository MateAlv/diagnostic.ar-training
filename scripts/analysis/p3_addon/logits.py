"""PHASE3 §2f step 2: for folds 0-3, cache each patient's gene logits under its held-out network and E0.

Fold k is scored by the run that never trained on it (`RUNS`, final checkpoints), on the fold set the harness
read it on (FIT for 0-2, SELECT for 3), batched as `v4.evaluate.model_ranks`, so the ranks are crossfit.py's.
The network and E0 get present terms only. Writes data/interim/p3-addon/logits-f<k>.npz: case_id (every
patient of fold k, in `load_train` order), net / e0 [n, genes] float32 and net_ok / e0_ok (scorable).
Inference only; GPU when available, batches of 512 graphs.
Usage: logits.py
"""

import numpy as np

from diagnostic_ar_training.ft.system import E0Logits
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3
from diagnostic_ar_training.v4 import addon
from diagnostic_ar_training.v4.runs import Context

RUNS = {0: "R5x-f0-34cd370c47", 1: "R5x-f1-fc60f6a846", 2: "R5x-f2-bcb6ff0d93", 3: "R5-r30-fa772ffa7e"}

ctx = Context("cuda")
e0 = E0Logits(GenPheniaV3())
addon.ADDON_DIR.mkdir(parents=True, exist_ok=True)
for k, run in RUNS.items():
    fold_set = "select" if k == 3 else "fit"
    pset = ctx.patient_set(fold_set)
    net, cfg = addon.load_network(run, ctx)
    held = [p for p in pset.patients if p.fold == k]
    if k in cfg.sim.real_folds:
        raise SystemExit(f"{run} trained on fold {k}")
    scored = addon.network_logits(net, pset, ctx.tables(cfg.encoding.ic_feature), cfg.encoding)
    base = addon.e0_logits(held, e0)
    n, g = len(held), len(ctx.genes)
    out = {"net": np.zeros((n, g), np.float32), "e0": np.zeros((n, g), np.float32)}
    ok = {"net": np.zeros(n, bool), "e0": np.zeros(n, bool)}
    for i, p in enumerate(held):
        for name, src in (("net", scored), ("e0", base)):
            if p.case_id in src:
                out[name][i], ok[name][i] = src[p.case_id], True
    path = addon.ADDON_DIR / f"logits-f{k}.npz"
    np.savez(
        path,
        case_id=np.array([p.case_id for p in held]),
        run=np.array(run),
        genes=np.array(ctx.genes),
        net_ok=ok["net"],
        e0_ok=ok["e0"],
        **out,
    )
    print(
        f"fold {k} ({run}): {n} patients, network scorable {ok['net'].sum()}, E0 {ok['e0'].sum()} -> {path}"
    )
