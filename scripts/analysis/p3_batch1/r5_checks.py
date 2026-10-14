"""PHASE3 §2e R5 checks on SELECT, final checkpoints vs E0.

1. Popularity, on the phenotype-swap ranks the harness wrote: capped MRR is near its floor there, so the
   true gene's raw rank is compared, split by whether the gene has real FIT patients (the genes a learned
   cohort prior would lift).
2. Curated-terms stress test (as k2.py `--perturb parent`): every present term moved to one of its parents
   (seeded), scored by E0 and by each run.
Usage: r5_checks.py <run_id> [<run_id> ...]
"""

import sys

import numpy as np

from diagnostic_ar_training.sim4 import load_knowledge
from diagnostic_ar_training.v4 import evaluate, model, patients, report, train
from diagnostic_ar_training.v4.evaluate import PatientSet
from diagnostic_ar_training.v4.runs import E0_RUN, Context, load_config, ranks_dir, run_dir

runs = sys.argv[1:]
fit_genes = {p.case.gene.upper() for p in patients.load("fit")}


def ranks(run, checkpoint, swap):
    recs = report.read_ranks(ranks_dir(run, checkpoint, swap) / "select.ranks.jsonl")
    return {r["case_id"]: r for r in recs if r["status"] == patients.UNCITED and r["gene_in_vocab"]}


e0 = ranks(E0_RUN, "best", True)
for run in runs:
    new = ranks(run, "last", True)
    for label, keep in (("gene with FIT patients", True), ("gene without", False)):
        ids = [c for c, r in e0.items() if (r["gene"].upper() in fit_genes) == keep]
        a = np.array([e0[c]["rank"] for c in ids], dtype=float)
        b = np.array([new[c]["rank"] for c in ids], dtype=float)
        print(
            f"{run} swap, uncited in-vocab, {label}: n {len(ids)}  median rank E0 {np.median(a):.0f} -> "
            f"{np.median(b):.0f}  mean log2 ratio {np.mean(np.log2(b / a)):+.3f}"
            f"  improved {(b < a).mean():.2f}"
        )

K = load_knowledge()
rng = np.random.default_rng(1)


def to_parent(term):
    t = K.ontology.resolve(term)
    if not (t and K.is_finding(t)):
        return term
    parents = sorted(a for a in K.ontology.parents(t) if K.is_finding(a))
    return parents[rng.integers(len(parents))] if parents else t


select = patients.load("select")
moved = [
    patients.Patient(p.case.model_copy(update={"present": [to_parent(x) for x in p.case.present]}), *rest)
    for p in select
    for rest in [(p.group, p.status, p.fold)]
]
ctx = Context("cuda")
pset = PatientSet.build(moved, ctx.builder, ctx.genes)
base = evaluate.e0_records(pset.patients)
for run in runs:
    cfg = load_config(run)
    net = model.GinV4(ctx.inputs.dim, len(ctx.genes), cfg.arch, cfg.encoding).to(ctx.device)
    train.load_weights(net, run_dir(run) / "last.pt", ctx.device)
    strata = report.summarize(
        evaluate.model_records(net, pset, ctx.tables(cfg.encoding.ic_feature), cfg.encoding), base
    )
    for name in ("uncited", "uncited_in_vocab", "cited"):
        x = strata["strata"][name]
        lo, hi = x["delta_mrr_cap_ci95"]
        print(
            f"{run} parent terms, SELECT {name:17} E0 {x['e0']['mrr_cap']:.4f} -> {x['mrr_cap']:.4f}"
            f"  Δ {x['delta']['mrr_cap']:+.4f} [{lo:+.4f}, {hi:+.4f}]"
            f"  helped {x['helped']} harmed {x['harmed']}"
        )
