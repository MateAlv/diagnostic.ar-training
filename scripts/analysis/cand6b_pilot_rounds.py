"""Candidate 6b pilot rounds (ADR-0011 amendment 8): measurements, next-round rule and selection.

Each `<root>/round<k>.*` file is a pilot round's calib.json, run.summary.json, validate.log (simulator 0.5.3,
`reporting.budget_scope: record`), categories.json (`dataset_term_categories.py --kb kb-v3`), exactness.json
(`explained_exactness.py`, every record), noise-signal.json (`noise_signal.py`) and record-size-{all,r1}.json
(`record_size_by_gene.py`). Targets and rules are the BITACORA pre-registration's. Reads no R1 data.

Usage: python scripts/analysis/cand6b_pilot_rounds.py <root> <round> [<round> ...]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
A_T, S_T, M_T = 0.093, 0.0929, 0.026
TOL = {"A": 0.10, "S": 0.10, "M": 0.20}
MAX_ROUNDS = 3
OSR = "presets.medium.ontology_smoothing_rate"
S_KEY, R_KEY = "noise.related_share", "reporting.specialize_rate"


def read(rnd: str, name: str):
    return json.loads((ROOT / f"round{rnd}.{name}").read_text())


rows = []
for rnd in sys.argv[2:]:
    cal, cat, ns = read(rnd, "calib.json"), read(rnd, "categories.json"), read(rnd, "noise-signal.json")
    ex = read(rnd, "exactness.json")
    rep = read(rnd, "run.summary.json")["reporting"]
    size_all, size_r1 = read(rnd, "record-size-all.json"), read(rnd, "record-size-r1.json")
    val = (ROOT / f"round{rnd}.validate.log").read_text()
    viol = int(re.search(r"Invariant violations: (\d+)", val).group(1))
    A = ex["simulated"]["ancestor_share_4dp"]
    S = cat["shares"]["more_specific"]
    M = ns["all_noise"]["mrr_in_vocab"]
    err = {"A": abs(A - A_T) / A_T, "S": abs(S - S_T) / S_T, "M": abs(M - M_T) / M_T}
    drift = {k: err[k] > TOL[k] for k in err}
    osr, s, r = cal[OSR], cal[S_KEY], cal[R_KEY]
    mv, mr = ns["vocabulary"]["mrr_in_vocab"], ns["related"]["mrr_in_vocab"]
    s_next = round(min(1.0, max(0.0, (M_T - mv) / (mr - mv))), 4) if mr > mv else s
    bn = rep["budget_normalized"]
    rec = bn["record"]
    rows.append({
        "round": int(rnd), "ontology_smoothing_rate": osr, "s": s, "r": r,
        "A_ancestor_share": A, "S_more_specific": S, "M_noise_mrr": M,
        "relative_errors": {k: round(v, 4) for k, v in err.items()},
        "score": round(sum(err.values()), 4),
        "drift": drift,
        "next_round_rule": {
            "ontology_smoothing_rate": round(min(1.0, max(0.0, osr * A_T / A)), 4) if drift["A"] else osr,
            "s": s_next if drift["M"] else s,
            "r": round(min(1.0, max(0.0, r * S_T / S)), 4) if drift["S"] else r,
        },
        "r1_train_uncited_ancestor_share": ex["r1_train_uncited"]["ancestor_share_4dp"],
        "explained_terms_scored": ex["simulated"]["explained_terms"],
        "record": rec,
        "shown_per_case": rep["reported_total_mean"],
        "profile_per_case": rep["reported_profile_mean"], "noise_per_case": rep["reported_noise_mean"],
        "k_mean": bn["k_mean"], "realized_profile_mean": bn["realized_profile_mean"],
        "mean_c": bn["scale_mean"],
        "shares": cat["shares"], "per_record": cat["per_record"],
        "true_terms_reported_share": rep["true_terms_reported_share"],
        "forced_min_one": rep["forced_min_one"], "cases": rep["cases"],
        "q_mean": rep["q_mean"], "q_capped_share": rep["q_capped_share"],
        "invariant_violations": viol,
        "specialized_share_of_profile_terms": rep["specialized"]["share_of_profile_terms"],
        "mrr_vocabulary": mv, "mrr_related": mr,
        "mean_ic_vocabulary": ns["vocabulary"]["mean_ic"], "mean_ic_related": ns["related"]["mean_ic"],
        "record_size_spearman_all_genes": {
            "genes": size_all["genes"],
            "sim_size_vs_sim_true": size_all["spearman_sim_record_size_vs_sim_true_terms"],
        },
        "record_size_r1_genes": {k: v for k, v in size_r1.items() if k != "export"},
    })
last = rows[-1]
next_round = any(last["drift"].values()) and last["round"] < MAX_ROUNDS
selected = min(rows, key=lambda x: (x["score"], x["round"]))["round"]
print(json.dumps({
    "targets": {"A": A_T, "S": S_T, "M": M_T}, "tolerances": TOL,
    "rounds": rows, "next_round_runs": next_round,
    "next_round_knobs": last["next_round_rule"] if next_round else None,
    "selected_round": None if next_round else selected,
}, indent=1))
