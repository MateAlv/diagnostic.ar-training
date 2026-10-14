"""PHASE3 §2e R5 cross-fitted reading over folds 0-3, final checkpoints vs E0.

Each fold k is read by the run fine-tuned with real patients of the other three folds (`sim.real_folds`); fold
3 by R5-r30 (real folds 0-2). real_ratio 0.3 was chosen on fold 3, so folds 0-2 are also reported without it.
1. Capped Δ vs E0 per fold, pooled over 0-3 and over 0-2 (publication-group bootstrap as in v4.report).
2. Popularity, on the phenotype-swap ranks: the true gene's raw rank, split by whether the gene has real
   patients in the run's training folds.
3. With `--parent`: every present term moved to a seeded parent (as r5_checks.py), E0 and the run rescored.
Usage: crossfit.py 0=<run_id> 1=<run_id> 2=<run_id> 3=<run_id> [--parent]
"""

import sys

import numpy as np

from diagnostic_ar_training.v4 import evaluate, model, patients, report, train
from diagnostic_ar_training.v4.runs import E0_RUN, ranks_dir

STRATA = ("uncited", "uncited_in_vocab", "cited")
args = [a for a in sys.argv[1:] if a != "--parent"]
runs = {int(k): v for k, v in (a.split("=") for a in args)}
assert sorted(runs) == [0, 1, 2, 3]


def fold_ranks(run, k, checkpoint, swap=False):
    name = "select" if k == 3 else "fit"
    recs = report.read_ranks(ranks_dir(run, checkpoint, swap) / f"{name}.ranks.jsonl")
    return [r for r in recs if r["fold"] == k]


def show(label, records, e0):
    for name in STRATA:
        recs = [r for r in records if name in r["strata"]]
        e0_by_id = {r["case_id"]: r for r in e0}
        x = report.stratum_summary(recs, [e0_by_id[r["case_id"]] for r in recs])
        lo, hi = x["delta_mrr_cap_ci95"]
        print(
            f"{label:10} {name:17} n {x['n']:5} pubs {x['n_groups']:4}  E0 {x['e0']['mrr_cap']:.4f} -> "
            f"{x['mrr_cap']:.4f}  Δ {x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}]"
            f"  helped {x['helped']} harmed {x['harmed']}"
        )


new = {k: fold_ranks(run, k, "last") for k, run in runs.items()}
base = {k: fold_ranks(E0_RUN, k, "best") for k in runs}
for k in runs:
    show(f"fold {k}", new[k], base[k])
show("folds 0-2", [r for k in (0, 1, 2) for r in new[k]], [r for k in (0, 1, 2) for r in base[k]])
show("folds 0-3", [r for k in runs for r in new[k]], [r for k in runs for r in base[k]])

train_patients = patients.load("fit") + patients.load("select")
genes_in = {k: {p.case.gene.upper() for p in train_patients if p.fold != k} for k in runs}
for keep, label in ((True, "gene with training patients"), (False, "gene without")):
    a, b = [], []
    for k, run in runs.items():
        e0 = fold_ranks(E0_RUN, k, "best", True)
        e0 = {r["case_id"]: r for r in e0 if "uncited_in_vocab" in r["strata"]}
        mod = {r["case_id"]: r for r in fold_ranks(run, k, "last", True)}
        ids = [c for c, r in e0.items() if (r["gene"].upper() in genes_in[k]) == keep]
        a += [e0[c]["rank"] for c in ids]
        b += [mod[c]["rank"] for c in ids]
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    print(
        f"swap, folds 0-3 uncited in-vocab, {label}: n {a.size}  median rank E0 {np.median(a):.0f} -> "
        f"{np.median(b):.0f}  mean log2 ratio {np.mean(np.log2(b / a)):+.3f}  improved {(b < a).mean():.2f}"
    )

if "--parent" in sys.argv:
    from diagnostic_ar_training.sim4 import load_knowledge
    from diagnostic_ar_training.v4.evaluate import PatientSet
    from diagnostic_ar_training.v4.runs import Context, load_config, run_dir

    K = load_knowledge()
    rng = np.random.default_rng(1)

    def to_parent(term):
        t = K.ontology.resolve(term)
        if not (t and K.is_finding(t)):
            return term
        parents = sorted(a for a in K.ontology.parents(t) if K.is_finding(a))
        return parents[rng.integers(len(parents))] if parents else t

    ctx = Context("cuda")
    moved_new, moved_base = [], []
    for k, run in runs.items():
        held = [p for p in train_patients if p.fold == k]
        moved = [
            patients.Patient(
                p.case.model_copy(update={"present": [to_parent(x) for x in p.case.present]}),
                p.group,
                p.status,
                p.fold,
            )
            for p in held
        ]
        pset = PatientSet.build(moved, ctx.builder, ctx.genes)
        cfg = load_config(run)
        net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device)
        train.load_weights(net, run_dir(run) / "last.pt", ctx.device)
        moved_new.append(evaluate.model_records(net, pset, ctx.tables(cfg.encoding.ic_feature), cfg.encoding))
        moved_base.append(evaluate.e0_records(pset.patients))
        show(f"parent {k}", moved_new[-1], moved_base[-1])
    show("parent 0-3", [r for x in moved_new for r in x], [r for x in moved_base for r in x])
