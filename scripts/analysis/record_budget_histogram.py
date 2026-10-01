"""ADR-0011 amendment 8: `reporting.profile_budget_histogram` read as total present terms per case.

Copies report-model-v2's `term_budget` histogram (present terms per R1-train case, every R1-train patient,
mean 8.70: the population G2c compares with) into a calibration-keys file for simulator 0.5.3's
`reporting.budget_scope: record`. Reads no patient data itself; the histogram was computed on R1-train when
report-model-v2 was fitted.

Writes `data/calib/<id>.json` (merged with `dxt knowledge shrinkage-prior --include`) and its manifest.
Needs a clean, committed tree.

Usage: PYTHONPATH=src .venv/bin/python scripts/analysis/record_budget_histogram.py --id record-budget-v1
"""

import argparse
import json

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import (
    build_manifest,
    ensure_new,
    fetch_outputs,
    load_manifest,
    write_manifest,
)
from diagnostic_ar_training.lineage.registry import LineageError

ap = argparse.ArgumentParser()
ap.add_argument("--id", required=True, dest="artifact")
ap.add_argument("--report-model", default="report-model-v2")
args = ap.parse_args()

ensure_new(args.artifact)
state = code_state()
if state.dirty:
    raise LineageError("working tree has uncommitted changes; commit before producing artifacts")

rm_path = next(p for p in fetch_outputs(load_manifest(args.report_model)) if p.name == "report-model.json")
rm = json.loads(rm_path.read_text())
hist = {int(k): v for k, v in rm["term_budget"]["histogram"].items()}
cases = sum(hist.values())
mean = sum(k * v for k, v in hist.items()) / cases
summary = {
    "cases": cases,
    "mean": round(mean, 4),
    "min": min(hist),
    "max": max(hist),
    "zero_bin": hist.get(0, 0),
    "report_model_percentiles": rm["provenance"]["term_budget"]["percentiles"],
}
body = {
    "reporting.profile_budget_histogram": {str(k): hist[k] for k in sorted(hist)},
    "_provenance": {
        "artifact": args.artifact,
        "adr": "0011 amendment 8",
        "source": f"{args.report_model} term_budget.histogram ({rm['term_budget']['description']})",
        "source_sha256": sha256_file(rm_path),
        "population": rm["provenance"]["fitted_on"],
        "simulator_note": "rare-disease-simulator 0.5.3 with reporting.budget_scope 'record' reads it as "
        "total present terms per case (noise included)",
        "code_sha": state.sha,
        **summary,
    },
}
out = DATA_DIR / "calib" / f"{args.artifact}.json"
out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
inputs = [{"id": f"artifact:{args.report_model}", "sha256": sha256_file(rm_path)}]
params = {
    "statistic": "report-model term_budget histogram, copied as is",
    "reads": "R1-train (through the report model's term_budget)",
    "report_model": args.report_model,
}
manifest = build_manifest(args.artifact, "simulator-calibration-keys", inputs, params, [out], state=state)
write_manifest(manifest)
print(json.dumps(body["_provenance"], indent=1, sort_keys=True))
