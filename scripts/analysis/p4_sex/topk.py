"""P4-SEX: how often the network's list shows a gene impossible for the patient's sex (a `sex-kb`), folds 0-3
out of fold. What a doctor would see without the hard sex rule; the rule removes every one of them.
read.py also reports these counts, for the network and F1.
Usage: topk.py [<sex kb id>]   (sex-kb-v2 by default)"""

import sys

import numpy as np

from diagnostic_ar_training.v4 import addon, patients, sexrule

kb, _ = sexrule.load_kb(sys.argv[1] if len(sys.argv) > 1 else "sex-kb-v2")
members = {p.case_id: p for p in patients.load_addon((0, 1, 2, 3))}
counts = {k: [0, 0] for k in sexrule.TOP_K}
n_sex = 0
for f in range(4):
    with np.load(addon.ADDON_DIR / f"logits-f{f}.npz") as z:
        genes, net, ok, ids = list(z["genes"]), z["net"], z["net_ok"], z["case_id"]
    rule = sexrule.SexRule(sexrule.limits(kb), genes)
    for i, c in enumerate(ids):
        if not ok[i]:
            continue
        mask = rule.blocked(members[c].case.sex)
        if not mask.any():
            continue
        n_sex += 1
        for k, hits in sexrule.shown(net[i], mask).items():
            counts[k][0] += hits > 0
            counts[k][1] += hits
print("patients with known sex (scored):", n_sex)
for k, (pats, genes_) in counts.items():
    print(
        f"top-{k}: patients shown >=1 sex-impossible gene: {pats} ({pats / n_sex:.2%});"
        f" such genes shown: {genes_}"
    )
