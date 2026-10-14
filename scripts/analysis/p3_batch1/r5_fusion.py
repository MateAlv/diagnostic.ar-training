"""PHASE3 §2e: R5 (final checkpoint) fused with the K1 memory on SELECT, vs E0 and E0 + K1.

The memory evidence is k2.py's (`--dump`, memory = folds 0-3 without the query's publication) and the fusion
keeps the configuration K1's nested selection chose for fold 3 (lambda 4, threshold 1), so nothing is tuned
on SELECT. Capped MRR over SELECT uncited patients, out-of-vocabulary genes included at 0.
Usage: r5_fusion.py <run_id> <k1 evidence .npz> [...]
"""

import os
import pickle
import sys

import numpy as np
import torch

from diagnostic_ar_training.v4 import data, model, patients, report, train
from diagnostic_ar_training.v4.evaluate import PatientSet
from diagnostic_ar_training.v4.runs import Context, load_config, run_dir

LAMBDA, THRESHOLD = 4, 1
DATA = os.environ.get("P3_B1_DATA", "data/interim/p3-b1") + "/"
run, dumps = sys.argv[1], sys.argv[2:]

ctx = Context("cuda")
select = patients.load("select")
e0p, genes = pickle.load(open(DATA + "e0probs.pkl", "rb"))
assert tuple(genes) == tuple(ctx.genes)
e0_lp = {
    p.case.case_id: np.log(e0p[len(patients.load("fit")) + k] + 1e-12)
    for k, p in enumerate(select)
    if e0p[len(patients.load("fit")) + k] is not None
}

cfg = load_config(run)
net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device).eval()
train.load_weights(net, run_dir(run) / "last.pt", ctx.device)
pset = PatientSet.build(select, ctx.builder, ctx.genes)
tables = ctx.tables(cfg.encoding.ic_feature)
r5_lp = {}
with torch.no_grad():
    for p, g, t, c in zip(pset.patients, pset.graphs, pset.targets, pset.covariates, strict=True):
        if g is not None and t is not None:
            inputs = data.to_device(data.collate([data.Item(g, t, c, True)]), tables, cfg.encoding)
            r5_lp[p.case.case_id] = (
                torch.log_softmax(net(**data.model_inputs(inputs)).float(), 1)[0].cpu().numpy()
            )

uncited = [p for p in select if p.status == patients.UNCITED]
groups = [p.group for p in uncited]
target = {p.case.case_id: t for p, t in zip(pset.patients, pset.targets, strict=True)}


def ranks(vals):
    return np.where(vals > 0, 1 / np.maximum(vals, 1e-12), np.inf)


def rr(lp, boost, case_id):
    if lp is None or target[case_id] is None:
        return 0.0
    score = lp + boost
    return 1 / (1 + int((score > score[target[case_id]]).sum()))


for dump in dumps:
    ev = np.load(dump)
    z = dict(zip(ev["case_id"], ev["z"], strict=True))
    readings = {}
    for name, lps in (("E0", e0_lp), (run, r5_lp)):
        for memory in (False, True):
            vals = []
            for p in uncited:
                c = p.case.case_id
                boost = LAMBDA * np.clip(z[c] - THRESHOLD, 0, None) if memory and c in z else 0.0
                vals.append(rr(lps.get(c), boost, c))
            readings[(name, memory)] = np.array(vals)
    base = readings[("E0", False)]
    w = report.cap_weights(groups)
    print(f"== memory evidence {os.path.basename(dump)}; SELECT uncited n {len(uncited)}")
    for key, vals in readings.items():
        lo, hi = report.capped_bootstrap(ranks(base), ranks(vals), groups)
        d = np.sum(w * (vals - base)) / w.sum()
        print(
            f"  {key[0]:18} {'+ K1' if key[1] else '    '}  capped {np.sum(w * vals) / w.sum():.4f}"
            f"  Δ vs E0 {d:+.4f} [{lo:+.4f}, {hi:+.4f}]"
            f"  helped {(vals > base).sum()} harmed {(vals < base).sum()}"
        )
    lo, hi = report.capped_bootstrap(ranks(readings[(run, False)]), ranks(readings[(run, True)]), groups)
    gain = np.sum(w * (readings[(run, True)] - readings[(run, False)])) / w.sum()
    print(f"  K1 on top of {run}: {gain:+.4f} [{lo:+.4f}, {hi:+.4f}]")
