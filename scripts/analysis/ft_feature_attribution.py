"""Which features of ft-v1.1 carry its gain? Leave-one-out and one-only variants on free parts
(r1-v1 dev, train).

Each variant copies the bundle and sets the chosen θ entries to 0 in every member; nothing is refitted.
Descriptive (EXP-P-005 explained after the read); sealed parts are never loaded.

Usage: python scripts/analysis/ft_feature_attribution.py <out.json> [part ...]
"""

import copy
import json
import sys

from diagnostic_ar_training import splits
from diagnostic_ar_training.cli_ft import _kb_output, ft_system, verified_bundle
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.eval.metrics import harmed_helped, paired_bootstrap
from diagnostic_ar_training.ft.system import E0Logits, E0System
from diagnostic_ar_training.lineage.registry import Purpose
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

BUNDLE, KB = "ft-v1.1-c1-lin-all-ens", "ft-kb-all-v2"
GROUPS = {
    "sex": ("sex_mismatch", "xlr_female"),
    "onset": ("onset_strict_late", "onset_strict_gap", "onset_lenient_gap"),
    "negation": ("neg_obligate", "neg_embed"),
}

out_path = sys.argv[1]
parts = sys.argv[2:] or ["dev"]
bundle, _, deltas_exp = verified_bundle(BUNDLE, KB)
kb_path, _ = _kb_output(KB)
features = bundle["features"]
base = GenPheniaV3()
e0 = E0Logits(base)


def variant(keep: set[str]):
    b = copy.deepcopy(bundle)
    for m in b["members"]:
        m["theta"] = [t if f in keep else 0.0 for f, t in zip(features, m["theta"], strict=True)]
    return ft_system(base, e0, b, BUNDLE, kb_path, KB, deltas_exp)


variants = {"all": set(features)}
for f in features:
    variants[f"without {f}"] = set(features) - {f}
    variants[f"only {f}"] = {f}
for g, fs in GROUPS.items():
    variants[f"without group {g}"] = set(features) - set(fs)
    variants[f"only group {g}"] = set(fs)

report = {"bundle": BUNDLE, "kb": KB, "features": features, "parts": {}}
for part in parts:
    cases = splits.load_part("r1-v1", part, Purpose.EVAL)
    groups = splits.publication_groups("r1-v1")
    ref = harness.run(E0System(e0), cases, "all", groups)
    base_ranks = [r["rank"] for r in ref]
    g = [r["group"] for r in ref]
    rows = {}
    for name, keep in variants.items():
        new = [r["rank"] for r in harness.run(variant(keep), cases, "all", groups)]
        res = paired_bootstrap(base_ranks, new, groups=g)
        hh = harmed_helped(base_ranks, new)
        rows[name] = {"delta": res["delta"], "ci95": res["ci95"], **hh}
        print(
            f"{part:5s} {name:32s} {res['delta']:+.5f} [{res['ci95'][0]:+.5f}, {res['ci95'][1]:+.5f}] "
            f"harmed {hh['harmed']:.4f} helped {hh['helped']:.4f}",
            flush=True,
        )
    report["parts"][part] = rows
with open(out_path, "w") as fh:
    json.dump(report, fh, indent=1)
