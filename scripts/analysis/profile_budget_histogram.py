"""ADR-0011 amendment 7: `reporting.profile_budget_histogram`, explained terms per uncited R1-train patient.

The population and the "explained" rule are `uncited_categories.py`'s: R1-train patients with a gene in the KB
none of whose PMIDs the pinned hpo_annotations cites (`e0_by_hpoa_citation.py`); a present term (resolved) is
explained when the KB gives it a positive probability for the patient's gene. The histogram keeps the 0 bin
(the simulator ignores it and renormalises the rest).

Writes `data/calib/<id>.json` (calibration keys, merged with `dxt knowledge shrinkage-prior --include`) and
its manifest. R1-train only. Needs a clean, committed tree.

Usage: PYTHONPATH=src .venv/bin/python scripts/analysis/profile_budget_histogram.py --id profile-budget-v1
"""

import argparse
import json
import re
import statistics
from collections import Counter

from diagnostic_ar_training import DATA_DIR, SPLITS_DIR, splits
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import (
    build_manifest,
    ensure_new,
    fetch_outputs,
    load_manifest,
    write_manifest,
)
from diagnostic_ar_training.lineage.registry import LineageError, Purpose, load_sources, open_source
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank import kb
from diagnostic_ar_training.rerank.features import GeneKnowledge

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True, dest="artifact")
ap.add_argument("--kb", default="kb-v3")
args = ap.parse_args()

ensure_new(args.artifact)
state = code_state()
if state.dirty:
    raise LineageError("working tree has uncommitted changes; commit before producing artifacts")

onto = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
kb_path = fetch_outputs(load_manifest(args.kb))[0]
K = kb.read(kb_path)
know = GeneKnowledge(K, onto)
cited = set()
with open(open_source("hpo_annotations", Purpose.KB)) as handle:
    for line in handle:
        if not line.startswith("#"):
            cited.update(re.findall(r"PMID:(\d+)", line))

explained = []
for c in splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL):
    if {p.replace("PMID:", "") for p in c.pmids} & cited or not know.diseases(c.gene):
        continue
    explained.append(sum(1 for t in c.present if know.term_probability(c.gene, onto.resolve(t) or t) > 0))

hist = Counter(explained)
positive = [e for e in explained if e >= 1]
qs = statistics.quantiles(explained, n=10)
summary = {
    "patients": len(explained),
    "mean": round(statistics.fmean(explained), 4),
    "median": statistics.median(explained),
    "p10": qs[0],
    "p90": qs[-1],
    "max": max(explained),
    "zero_explained_patients": hist.get(0, 0),
    "mean_of_k_ge_1": round(statistics.fmean(positive), 4),
}
body = {
    "reporting.profile_budget_histogram": {str(k): hist[k] for k in sorted(hist)},
    "_provenance": {
        "artifact": args.artifact,
        "adr": "0011 amendment 7",
        "population": "R1-train patients with a gene in the KB, none of whose PMIDs the pinned "
        "hpo_annotations cites",
        "statistic": "explained present terms per patient (uncited_categories.py rule)",
        "kb": args.kb,
        "simulator_note": "rare-disease-simulator 0.5.2 ignores the 0 bin and renormalises the rest",
        "code_sha": state.sha,
        **summary,
    },
}
out = DATA_DIR / "calib" / f"{args.artifact}.json"
out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
sources = load_sources()
inputs = [
    {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
    {"id": f"artifact:{args.kb}", "sha256": sha256_file(kb_path)},
    sources["hpo_annotations"].as_input(),
    sources["hpo_ontology"].as_input(),
]
params = {
    "part": "train",
    "population": "uncited in hpo_annotations, gene in KB",
    "statistic": "histogram of explained present terms per patient",
    "kb": args.kb,
    "zero_bin": "kept",
}
manifest = build_manifest(args.artifact, "simulator-calibration-keys", inputs, params, [out], state=state)
write_manifest(manifest)
print(json.dumps(body, indent=1, sort_keys=True))
