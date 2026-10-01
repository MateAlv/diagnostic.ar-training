"""ANALYSIS-005 §3: does a simulated record's size follow its profile's richness, gene by gene?

Over the genes with at least `--min-patients` R1-train patients that the export simulates: per gene, the mean
reported terms per case (real and simulated) and the mean simulated true-term count (`true_present`), with
the Spearman correlations across genes. With `--no-r1`, reads no R1 data and scores every simulated gene
(the pilots' check of simulated size vs true terms only).

R1-train only. Usage:
  PYTHONPATH=src .venv/bin/python scripts/analysis/record_size_by_gene.py <export.jsonl.gz> \
    [--no-r1] [--out f]
"""

import argparse
import gzip
import json
import statistics
from collections import defaultdict

from scipy.stats import spearmanr

ap = argparse.ArgumentParser()
ap.add_argument("export")
ap.add_argument("--min-patients", type=int, default=10)
ap.add_argument("--no-r1", action="store_true")
ap.add_argument("--out")
args = ap.parse_args()

size, true = defaultdict(list), defaultdict(list)
with gzip.open(args.export, "rt") as handle:
    for line in handle:
        r = json.loads(line)
        g = r["gene"].upper()
        size[g].append(len(r["present"]))
        true[g].append(len(r["true_present"]))

real = defaultdict(list)
if not args.no_r1:
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.lineage.registry import Purpose

    for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
        real[c.gene.upper()].append(len(c.present))
    genes = sorted(g for g, v in real.items() if len(v) >= args.min_patients and g in size)
else:
    genes = sorted(size)

sim_size = [statistics.fmean(size[g]) for g in genes]
sim_true = [statistics.fmean(true[g]) for g in genes]
out = {
    "export": args.export,
    "genes": len(genes),
    "gene_rule": "every simulated gene"
    if args.no_r1
    else f">= {args.min_patients} R1-train patients and simulated",
    "mean_terms_per_case_sim": round(statistics.fmean(sim_size), 2),
    "mean_true_terms_per_case_sim": round(statistics.fmean(sim_true), 2),
    "spearman_sim_record_size_vs_sim_true_terms": round(float(spearmanr(sim_size, sim_true)[0]), 3),
}
if not args.no_r1:
    real_size = [statistics.fmean(real[g]) for g in genes]
    ratios = [s / r for s, r in zip(sim_size, real_size, strict=True)]
    out.update({
        "mean_terms_per_case_real": round(statistics.fmean(real_size), 2),
        "spearman_real_vs_sim_record_size_by_gene": round(float(spearmanr(real_size, sim_size)[0]), 3),
        "spearman_real_record_size_vs_sim_true_terms": round(float(spearmanr(real_size, sim_true)[0]), 3),
        "sim_over_real_ratio_median": round(statistics.median(ratios), 2),
    })
text = json.dumps(out, indent=1)
print(text)
if args.out:
    with open(args.out, "w") as handle:
        handle.write(text + "\n")
