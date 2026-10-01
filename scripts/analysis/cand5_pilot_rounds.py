"""Candidate 5 pilot rounds (ADR-0011 amendment 6): measurements, selection score and the next round's knobs.

Each `<root>/pilot-r<k>/` holds the round's calib.json, run.summary.json, validate.log (simulator 0.5.1),
categories.json (`dataset_term_categories.py --kb kb-v3`) and noise-signal.json (`noise_signal.py`).
Targets and rules are the BITACORA pre-registration's. Reads no R1 data.

Usage: python scripts/analysis/cand5_pilot_rounds.py <root> <round> [<round> ...]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1])
E_T, M_T, S_T = 5.3772, 0.026, 0.0929

rows = []
for rnd in sys.argv[2:]:
    o = ROOT / f"pilot-r{rnd}"
    cal = json.loads((o / "calib.json").read_text())
    cat = json.loads((o / "categories.json").read_text())
    ns = json.loads((o / "noise-signal.json").read_text())
    rep = json.loads((o / "run.summary.json").read_text())["reporting"]
    val = (o / "validate.log").read_text()
    qerr = float(re.search(r"q calibration error ([0-9.]+)", val).group(1))
    viol = int(re.search(r"Invariant violations: (\d+)", val).group(1))
    rel_share = float(re.search(r"related share ([0-9.]+)", val).group(1))
    E = cat["per_record"]["explained"]
    M = ns["all_noise"]["mrr_in_vocab"]
    S = cat["shares"]["more_specific"]
    errs = (abs(E - E_T) / E_T, abs(M - M_T) / M_T, abs(S - S_T) / S_T)
    q, s, r = cal["reporting.q_scale"], cal["noise.related_share"], cal["reporting.specialize_rate"]
    mv, mr = ns["vocabulary"]["mrr_in_vocab"], ns["related"]["mrr_in_vocab"]
    nxt = (
        round(min(10.0, max(1.0, q * E_T / E)), 4),
        round(min(1.0, max(0.0, (M_T - mv) / (mr - mv))), 4) if mr > mv else s,
        round(min(1.0, max(0.0, r * S_T / S)), 4),
    )
    rows.append({
        "round": int(rnd), "q_scale": q, "s": s, "r": r,
        "E_explained_per_record": E, "M_noise_mrr": M, "S_more_specific": S,
        "shares": cat["shares"], "terms_per_record": cat["per_record"]["terms"],
        "profile_per_case": rep["reported_profile_mean"], "noise_per_case": rep["reported_noise_mean"],
        "true_terms_reported_share": rep["true_terms_reported_share"],
        "forced_min_one": rep["forced_min_one"], "q_mean": rep["q_mean"],
        "q_capped_share": rep["q_capped_share"],
        "q_calibration_error": qerr, "invariant_violations": viol,
        "related_share_of_noise": rel_share,
        "specialized_share_of_profile_terms": rep["specialized"]["share_of_profile_terms"],
        "mrr_vocabulary": mv, "mrr_related": mr,
        "mean_ic_vocabulary": ns["vocabulary"]["mean_ic"], "mean_ic_related": ns["related"]["mean_ic"],
        "mean_ic_all_noise": ns["all_noise"]["mean_ic"],
        "relative_errors": [round(e, 4) for e in errs], "score": round(sum(errs), 4),
        "all_within_0.05": all(e <= 0.05 for e in errs),
        "next_round_rule": {"q_scale": nxt[0], "s": nxt[1], "r": nxt[2]},
    })
print(json.dumps(rows, indent=1))
