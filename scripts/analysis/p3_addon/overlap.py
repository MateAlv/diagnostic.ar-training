"""EXP-V-002 contamination check, keys only: vault patients whose (gene, present set) a training patient has.

The network trained on the real patients of `p3-v1` train folds 0-3 and nearly memorises them, so a vault
patient with the same gene and present terms as one of them (the same patient in two publications, or a
templated description) would be read as a recall. This compares keys as `splits.presentation_keys` does
(EVAL_PROTOCOL §4.2, §9.7): nothing is scored or ranked. Also counted with the excluded terms in the key.
Writes results/P3/EXP-V-002/overlap.json, committed before the read: its case ids define the pre-registered
sensitivity reading without them.
"""

import json
from collections import Counter

from diagnostic_ar_training import RESULTS_DIR, splits
from diagnostic_ar_training.v4 import patients

SPLIT, EXP = "p3-v1", "EXP-V-002"
OUT = RESULTS_DIR / "P3" / EXP / "overlap.json"


def present_key(case):
    return case.gene.upper(), frozenset(case.present)


def full_key(case):
    return case.gene.upper(), frozenset(case.present), frozenset(case.excluded)


def main() -> None:
    training = patients.load_addon((0, 1, 2, 3))
    train_present = Counter(present_key(p.case) for p in training)
    train_full = {full_key(p.case) for p in training}
    frozen = splits.load_frozen(SPLIT)
    wanted = set(frozen["case_ids"][splits.Part.VAULT.value])
    cases, _ = splits._all_cases(splits.SPECS[SPLIT])
    vault = [c for c in cases if c.case_id in wanted]
    groups = splits._components(vault)
    status = {c.case_id: frozen["group_status"][groups[c.case_id]] for c in vault}
    hits = [c for c in vault if present_key(c) in train_present]
    full_hits = [c for c in vault if full_key(c) in train_full]
    out = {
        "exp": EXP,
        "training": "p3-v1 train folds 0-3 (the network's real patients)",
        "n_training": len(training),
        "n_vault": len(vault),
        "present_key": {
            "n": len(hits),
            "by_status": dict(Counter(status[c.case_id] for c in hits)),
            "n_groups": len({groups[c.case_id] for c in hits}),
            "n_present_terms": dict(Counter(min(len(c.present), 5) for c in hits)),
            "case_ids": sorted(c.case_id for c in hits),
        },
        "present_and_excluded_key": {
            "n": len(full_hits),
            "by_status": dict(Counter(status[c.case_id] for c in full_hits)),
            "case_ids": sorted(c.case_id for c in full_hits),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    print({k: v for k, v in out["present_key"].items() if k != "case_ids"})
    print({k: v for k, v in out["present_and_excluded_key"].items() if k != "case_ids"})


if __name__ == "__main__":
    main()
