"""P4-SEX: how often the network's list shows a gene impossible for the patient's sex (`sex-kb-v2`), folds 0-3
out of fold. What a doctor would see without the hard sex rule; the rule removes every one of them."""

import numpy as np

from diagnostic_ar_training.v4 import patients, sexrule

kb, _ = sexrule.load_kb("sex-kb-v2")
members = {p.case_id: p for p in patients.load_addon((0, 1, 2, 3))}
counts = {k: [0, 0] for k in (1, 5, 10, 50)}
n_sex = 0
for f in range(4):
    with np.load(f"data/interim/p3-addon/logits-f{f}.npz") as z:
        genes, net, ok, ids = list(z["genes"]), z["net"], z["net_ok"], z["case_id"]
    rule = sexrule.SexRule(sexrule.limits(kb), genes)
    for i, c in enumerate(ids):
        if not ok[i]:
            continue
        mask = rule.blocked(members[c].case.sex)
        if not mask.any():
            continue
        n_sex += 1
        order = np.argsort(-net[i])
        for k in counts:
            hit = mask[order[:k]]
            counts[k][0] += bool(hit.any())
            counts[k][1] += int(hit.sum())
print("patients with known sex (scored):", n_sex)
for k, (pats, genes_) in counts.items():
    print(
        f"top-{k}: patients shown >=1 sex-impossible gene: {pats} ({pats / n_sex:.2%});"
        f" such genes shown: {genes_}"
    )
