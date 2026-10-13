"""Per-gene rho gap (fit folds vs SELECT fold) of a simulator with no patient-fitted parameter at all.

Frequency-proportional sampling (gamma 1, default frequency 0.5), E0's term counts and imprecision. If its
gap matches the fitted presets' gap, the gap comes from fold composition, not memorisation.
Run from the repo root: PYTHONPATH=src python scripts/analysis/sim4/gap_control.py
"""

import json

from diagnostic_ar_training import RESULTS_DIR, splits
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.sim4 import FittedParams, SimConfig, folds, load_knowledge
from diagnostic_ar_training.sim4.validate import validate

SEEDS = (0, 1, 2)

kb = load_knowledge()
groups = folds.train_groups()
status = splits.load_frozen(folds.SPLIT)["group_status"]
fit_cases = folds.cases_in(folds.FIT_FOLDS)
eval_cases = folds.cases_in((folds.SELECT_FOLD,))
cfg = SimConfig("freq_prop_nofit", frequency="proportional", counts="e0", count_slope=False, categories="e0")
out = {"code": code_state().as_dict(), "config": cfg.as_dict(), "params": "FittedParams()", "runs": {}}
for seed in SEEDS:
    r = validate(kb, FittedParams(), {cfg.name: cfg}, fit_cases, eval_cases, groups, status, seed=seed)
    out["runs"][str(seed)] = r["configs"][cfg.name]["per_gene_rho"]
    print(seed, out["runs"][str(seed)])
path = RESULTS_DIR / "analyses" / "SIM4-v1" / "gap-control.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print(f"wrote {path}")
