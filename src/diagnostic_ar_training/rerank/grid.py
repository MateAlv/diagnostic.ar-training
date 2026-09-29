"""Pre-registered weight search for rr-v1 on one cohort; every configuration is reported.

Stage 1 tries each feature alone at each value of `stage1_values`. Stage 2 is
fixed by rule, not by hand: every feature takes its best stage-1 weight if that
configuration improved MRR over E0, else 0; stage 2 also runs that combination
at half strength. One GNN call per case serves every configuration.
"""

import math

from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.rerank.model import FEATURES, Weights, feature_table


def _records(cases, tables, genes, weights: Weights, groups) -> list[dict]:
    lookup = {g.upper(): i for i, g in enumerate(genes)}
    out = []
    for case, table in zip(cases, tables, strict=True):
        probs = table.combine(weights)
        idx = lookup.get(case.gene.upper())
        if probs is None or idx is None:
            rank = math.inf
        else:
            target = probs[idx]
            rank = float(1 + (probs > target).sum() + ((probs == target).sum() - 1))
        out.append(
            {
                "case_id": case.case_id,
                "group": (groups or {}).get(case.case_id),
                "gene": case.gene,
                "rank": rank,
                "has_excluded": bool(case.excluded),
                "has_sex": case.sex != "unknown",
                "has_age": case.age_years is not None,
                "gene_in_vocab": idx is not None,
                "scorable": probs is not None,
                "latency_ms": 0.0,
            }
        )
    return out


def run(cases, base, knowledge, stage1_values, top_k, groups) -> dict:
    tables = [feature_table(base, knowledge, c, top_k) for c in cases]
    e0 = _records(cases, tables, base.genes, Weights(), groups)

    def evaluate(name: str, weights: Weights) -> dict:
        records = _records(cases, tables, base.genes, weights, groups)
        summary = harness.summarize(records)
        return {
            "name": name,
            "weights": weights.as_dict(),
            "all": summary["all"],
            "vs_e0": harness.compare(e0, records),
            "records": records,
        }

    configs = [evaluate("identity", Weights())]
    best: dict[str, float] = {}
    for feature in FEATURES:
        stage = [evaluate(f"{feature}={v}", Weights(**{feature: v})) for v in stage1_values]
        configs += stage
        winner = max(stage, key=lambda c: c["vs_e0"]["delta"])
        best[feature] = winner["weights"][feature] if winner["vs_e0"]["delta"] > 0 else 0.0
    combined = Weights(**best)
    configs.append(evaluate("stage2-combined", combined))
    configs.append(evaluate("stage2-combined-half", Weights(**{f: w / 2 for f, w in best.items()})))
    return {"e0_records": e0, "configs": configs, "stage2_weights": best}
