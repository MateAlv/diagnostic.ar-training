"""Candidate 6a pilot rounds (ADR-0011 amendment 7): measurements, round-2 trigger and selection.

Each `<root>/round<k>.*` file is a pilot round's calib.json, run.summary.json, validate.log (simulator 0.5.2),
categories.json (`dataset_term_categories.py --kb kb-v3`), noise-signal.json (`noise_signal.py`) and
record-size-{all,r1}.json (`record_size_by_gene.py`). Targets and rules are the BITACORA pre-registration's.
Reads no R1 data.

Usage: python scripts/analysis/cand6a_pilot_rounds.py <root> <round> [<round> ...]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
M_T, S_T, E_REF, DRIFT = 0.026, 0.0929, 5.3772, 0.20


def read(rnd: str, name: str):
    return json.loads((ROOT / f"round{rnd}.{name}").read_text())


rows = []
for rnd in sys.argv[2:]:
    cal, cat, ns = read(rnd, "calib.json"), read(rnd, "categories.json"), read(rnd, "noise-signal.json")
    rep = read(rnd, "run.summary.json")["reporting"]
    size_all, size_r1 = read(rnd, "record-size-all.json"), read(rnd, "record-size-r1.json")
    val = (ROOT / f"round{rnd}.validate.log").read_text()
    viol = int(re.search(r"Invariant violations: (\d+)", val).group(1))
    qerr = float(re.search(r"q calibration error ([0-9.]+)", val).group(1))
    rel_share = float(re.search(r"related share ([0-9.]+)", val).group(1))
    M, S = ns["all_noise"]["mrr_in_vocab"], cat["shares"]["more_specific"]
    err_m, err_s = abs(M - M_T) / M_T, abs(S - S_T) / S_T
    s, r = cal["noise.related_share"], cal["reporting.specialize_rate"]
    mv, mr = ns["vocabulary"]["mrr_in_vocab"], ns["related"]["mrr_in_vocab"]
    bn = rep["budget_normalized"]
    rows.append({
        "round": int(rnd), "s": s, "r": r,
        "M_noise_mrr": M, "S_more_specific": S,
        "relative_errors": {"M": round(err_m, 4), "S": round(err_s, 4)},
        "score": round(err_m + err_s, 4),
        "drift_over_0.20": {"M": err_m > DRIFT, "S": err_s > DRIFT},
        "next_round_rule": {
            "s": (round(min(1.0, max(0.0, (M_T - mv) / (mr - mv))), 4) if mr > mv else s)
            if err_m > DRIFT else s,
            "r": round(min(1.0, max(0.0, r * S_T / S)), 4) if err_s > DRIFT else r,
        },
        "shares": cat["shares"], "per_record": cat["per_record"],
        "E_explained_per_record": cat["per_record"]["explained"], "E_reference": E_REF,
        "profile_per_case": rep["reported_profile_mean"], "noise_per_case": rep["reported_noise_mean"],
        "shown_per_case": rep["reported_total_mean"],
        "true_terms_reported_share": rep["true_terms_reported_share"],
        "forced_min_one": rep["forced_min_one"], "cases": rep["cases"],
        "q_mean": rep["q_mean"], "q_capped_share": rep["q_capped_share"], "q_calibration_error": qerr,
        "k_mean": bn["k_mean"], "realized_profile_mean": bn["realized_profile_mean"],
        "total_variation_k_vs_realized": bn["total_variation_k_vs_realized"], "mean_c": bn["scale_mean"],
        "invariant_violations": viol, "related_share_of_noise": rel_share,
        "specialized_share_of_profile_terms": rep["specialized"]["share_of_profile_terms"],
        "mrr_vocabulary": mv, "mrr_related": mr,
        "mean_ic_vocabulary": ns["vocabulary"]["mean_ic"], "mean_ic_related": ns["related"]["mean_ic"],
        "mean_ic_all_noise": ns["all_noise"]["mean_ic"],
        "record_size_spearman_all_genes": {
            "genes": size_all["genes"],
            "sim_size_vs_sim_true": size_all["spearman_sim_record_size_vs_sim_true_terms"],
        },
        "record_size_r1_genes": {k: v for k, v in size_r1.items() if k != "export"},
    })
run_round_2 = any(rows[0]["drift_over_0.20"].values())
selected = min(rows, key=lambda x: x["score"])["round"] if len(rows) > 1 else 1
print(json.dumps({"rounds": rows, "round_2_triggered": run_round_2, "selected_round": selected}, indent=1))
