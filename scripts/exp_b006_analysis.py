# ruff: noqa: E501
"""Dev analysis of EXP-B-006: rr-v1 + onset 0.25 against rr-v1 on S3-v3b-dev (one interview driven by rr-v1).

Usage: python scripts/exp_b006_analysis.py dev

Reuses EXP-B-005's analysis (same populations, same bootstrap: genes, 2,000 resamples, seed 0) on the session
written by `dxt s3 onset-session --exp EXP-B-006`. Its first arm (rr-v1) is the reference. Reads ranks only;
never opens a split.

Dev rule (fixed in docs/experiments/EXP-B-006.md before the run): the candidate exists only if, on the
literature-onset dev cases, the paired delta CI lower bound is > 0 and harmed vs E0+answers is <= 5%, and the
R1-dev no-harm check (EXP-B-003 N2 form) passes.
"""

import importlib.util
import json
import sys
from pathlib import Path

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.eval import dev_search

EXP = "EXP-B-006"
HARM_CAP = 0.05

spec = importlib.util.spec_from_file_location(
    "exp_b005_analysis", Path(__file__).with_name("exp_b005_analysis.py")
)
b005 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b005)
b005.EXP = EXP


def dev() -> None:
    directory = RESULTS_DIR / EXP / "dev"
    out = b005.analyse(directory, "dev")
    r1 = json.loads((directory / "r1dev.json").read_text())
    verdicts = {}
    for arm_id, a in out["arms"].items():
        prim = a["vs_F"]["lit"]
        harmed = a["vs_e0"]["lit"]["harmed"]
        r = r1["arms"][arm_id]
        r1_pass = dev_search.r1_no_harm(r["delta"], r["ci95"][1])
        verdicts[arm_id] = {
            "delta": prim["delta"],
            "ci95": prim["ci95"],
            "n": prim["n"],
            "harmed_vs_e0": harmed,
            "r1dev": r | {"pass": r1_pass},
            "ci_lower_gt_0": prim["ci95"][0] > 0,
            "harmed_le_cap": harmed <= HARM_CAP,
            "candidate_exists": bool(prim["ci95"][0] > 0 and harmed <= HARM_CAP and r1_pass),
        }
    out["dev_verdict"] = verdicts
    lines = b005.fmt_tables(out)
    r1_ref = r1["arms"][out["reference"]["arm_id"]]
    lines += ["", f"R1-dev (all view, vs E0, as given): reference {r1_ref['delta']:+.4f} [{r1_ref['ci95'][0]:+.4f}, {r1_ref['ci95'][1]:+.4f}] harmed {r1_ref['harmed']:.4f}"]  # fmt: skip
    for arm_id, v in verdicts.items():
        r = v["r1dev"]
        lines += [
            "",
            f"{arm_id}: delta vs rr-v1 (literature-onset, n={v['n']}) {v['delta']:+.4f} [{v['ci95'][0]:+.4f}, {v['ci95'][1]:+.4f}], "
            f"harmed vs E0+answers {v['harmed_vs_e0']:.4f}; R1-dev {r['delta']:+.4f} [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] "
            f"harmed {r['harmed']:.4f} pass={r['pass']}; CANDIDATE EXISTS: {v['candidate_exists']}",
        ]
    b005.write("dev-analysis", out, lines)


if __name__ == "__main__":
    if sys.argv[1:] == ["dev"]:
        dev()
    else:
        raise SystemExit(__doc__)
