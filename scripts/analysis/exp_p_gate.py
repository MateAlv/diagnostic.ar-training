"""Gate of a Phase 2 confirmation read (EXP-P-NNN): Bonferroni-level CI from the read's own ranks files.

Usage: python scripts/analysis/exp_p_gate.py <EXP-id> <label> [system] [n_reads]
  e.g. python scripts/analysis/exp_p_gate.py EXP-P-001 p2-v1-test-safe-kb-v1
Reads results/<EXP-id>/<label>__E0__all.ranks.jsonl and <label>__<system>__all.ranks.jsonl (system defaults to
safe-v1), pairs them by case, and resamples publication groups (2,000 draws, seed 0) as the harness does. The
gate level is 1 - 0.05 / n_reads (default 3, the Phase 2 confirmation budget; PHASE2.md).
"""

import json
import sys
from pathlib import Path

from diagnostic_ar_training.eval.metrics import harmed_helped, paired_bootstrap

exp, label = sys.argv[1], sys.argv[2]
system = sys.argv[3] if len(sys.argv) > 3 else "safe-v1"
n_reads = int(sys.argv[4]) if len(sys.argv) > 4 else 3
out = Path("results") / exp


def ranks(name: str) -> dict[str, dict]:
    with open(out / f"{label}__{name}__all.ranks.jsonl") as f:
        return {r["case_id"]: r for r in map(json.loads, f)}


base, new = ranks("E0"), ranks(system)
if set(base) != set(new):
    raise SystemExit("the two ranks files do not hold the same cases")
ids = sorted(base)
level = 1 - 0.05 / n_reads
res = paired_bootstrap(
    [base[i]["rank"] for i in ids],
    [new[i]["rank"] for i in ids],
    groups=[base[i]["group"] for i in ids],
    level=level,
)
res |= harmed_helped([base[i]["rank"] for i in ids], [new[i]["rank"] for i in ids])
res |= {"exp": exp, "label": label, "system": system, "n_reads": n_reads}
res["gate"] = {
    "ci_lower_above_0": res["ci"][0] > 0,
    "harmed_at_most_5pct": res["harmed"] <= 0.05,
    "production_harmed_at_most_0.5pct": res["harmed"] <= 0.005,
}
res["gate"]["passed"] = res["gate"]["ci_lower_above_0"] and res["gate"]["harmed_at_most_5pct"]
path = out / f"{label}__{system}__gate.json"
path.write_text(json.dumps(res, indent=1) + "\n")
print(json.dumps(res, indent=1))
