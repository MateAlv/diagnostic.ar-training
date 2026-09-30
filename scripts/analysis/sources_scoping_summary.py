"""SOURCES-SCOPING-001: combine the per-gene table, the GeneReviews sample and the Europe PMC sample.

Reads the files the other three sources_scoping_* scripts wrote to DIR and
writes DIR/summary.json. Rates carry Wilson 95% intervals; Europe PMC
estimates for all simulable construction genes are stratum-weighted.

Usage: python scripts/analysis/sources_scoping_summary.py --dir DIR
"""

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median

OVERVIEW_GENES = 10
# literature-panel-v2 (LITPANEL-v2 §4, BITACORA 2026-09-30): realised rows per source,
# and the extraction's agent time from the batch files' start and end times.
PANEL = {
    "paper_units": 43,
    "genereviews_rows": 164,
    "genereviews_chapters": 23,
    "paper_rows": 367,
    "paper_pmids": 68,
    "raw_rows": 549,
    "batches": 17,
    "agent_minutes": 339,
    "wall_minutes": 55,
    "units_attempted": 120,
    "units_kept": 56,
    "crosscheck_rows": 54,
    "crosscheck_minutes": 9,
}


def wilson(k: int, n: int) -> dict:
    if n == 0:
        return {"k": 0, "n": 0, "p": None, "lo": None, "hi": None}
    z, p = 1.959964, k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"k": k, "n": n, "p": round(p, 4), "lo": round(mid - half, 4), "hi": round(mid + half, 4)}


def tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as h:
        return list(csv.DictReader(h, delimiter="\t"))


def ids(value: str) -> set[str]:
    return set(filter(None, value.split(";")))


def bin_hits(n: int) -> str:
    return "0" if n == 0 else ("1-4" if n < 5 else "5+")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, required=True)
    args = ap.parse_args()
    d = args.dir
    genes = tsv(d / "genes.tsv")
    chapters = {r["shortname"]: r for r in tsv(d / "gr_chapters.tsv")}
    verdicts = tsv(d / "gr_sample30.verdicts.tsv")
    auto = {r["shortname"]: r for r in tsv(d / "gr_sample30.auto.tsv")}
    epmc = tsv(d / "epmc_genes.tsv")
    hits = tsv(d / "epmc_hits.tsv")
    judged = tsv(d / "epmc_precision.tsv") if (d / "epmc_precision.tsv").is_file() else []
    out: dict = {"panel_throughput_inputs": PANEL}

    # 1. GeneReviews coverage
    cov = {}
    for role in ("construction", "evaluation"):
        rs = [r for r in genes if r["role"] == role]
        blocked = [r for r in rs if r["gr_eval_only"] == "True"]
        cov[role] = {
            "genes": len(rs),
            "any_chapter": sum(bool(r["gr_chapters"]) for r in rs),
            "chapter_with_le_10_genes": sum(r["gr_dedicated"] == "True" for r in rs),
            "chapter_lists_main_disease_omim": sum(bool(r["gr_chapter_for_main_disease"]) for r in rs),
            "usable_chapter_strict": sum(bool(r["gr_usable"]) for r in rs),
            "only_eval_touched_chapters": len(blocked),
            "only_eval_touched_via_overview_only": sum(
                all(int(chapters[s]["n_genes"]) > OVERVIEW_GENES for s in ids(r["gr_chapters"]))
                for r in blocked
            ),
        }
    out["genereviews_coverage"] = cov
    out["genereviews_chapters"] = {
        "in_gene_map": len(chapters),
        "touching_eval_units": sum(r["touches_eval_unit"] == "True" for r in chapters.values()),
        "overview_gt_10_genes": sum(int(r["n_genes"]) > OVERVIEW_GENES for r in chapters.values()),
    }

    # GeneReviews 30-chapter sample
    n = len(verdicts)
    yes = lambda col: sum(v[col] == "Y" for v in verdicts)  # noqa: E731
    ft_or_p5 = sum(v["numeric_feature_table"] == "Y" or v["ge5_numeric_features"] == "Y" for v in verdicts)
    any_age = sum(v["numeric_age"] == "Y" or v["qualitative_age_only"] == "Y" for v in verdicts)
    ft_rows = [
        int(auto[v["shortname"]]["feature_table_numeric_rows"])
        for v in verdicts
        if v["numeric_feature_table"] == "Y"
    ]
    out["genereviews_sample30"] = {
        "numeric_feature_table": wilson(yes("numeric_feature_table"), n),
        "ge5_numeric_features": wilson(yes("ge5_numeric_features"), n),
        "table_or_ge5": wilson(ft_or_p5, n),
        "numeric_age": wilson(yes("numeric_age"), n),
        "qualitative_age_only": wilson(yes("qualitative_age_only"), n),
        "any_age": wilson(any_age, n),
        "numeric_table_rows_median": median(ft_rows) if ft_rows else 0,
        "numeric_table_rows_range": [min(ft_rows), max(ft_rows)] if ft_rows else [],
        "chapters_citing_r1_heldout": wilson(
            sum(int(a["cited_pmids_r1_heldout"]) > 0 for a in auto.values()), n
        ),
        "cited_pmids": sum(int(a["cited_pmids"]) for a in auto.values()),
        "cited_pmids_r1_heldout": sum(int(a["cited_pmids_r1_heldout"]) for a in auto.values()),
        "nxml_bytes_mean": round(sum(int(a["nxml_bytes"]) for a in auto.values()) / n),
    }
    p5 = yes("ge5_numeric_features") / n
    age_rate = yes("numeric_age") / n

    # 3. weak profiles x GeneReviews x Europe PMC
    sim = [r for r in genes if r["role"] == "construction" and r["simulable"] == "True"]
    strata_n = Counter(
        ("gr" if r["gr_usable"] else "nogr") + "_" + ("ok" if r["weakness"] == "ok_counts" else "weak")
        for r in sim
    )
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for r in epmc:
        by_stratum[r["stratum"]].append(r)

    def epmc_estimate(strata: list[str], key: str = "hits_title") -> dict:
        total = sum(strata_n[s] for s in strata)
        est = Counter()
        for s in strata:
            rs = by_stratum.get(s, [])
            for r in rs:
                est[bin_hits(int(r[key]))] += strata_n[s] / len(rs)
        return {b: round(est[b] / total, 4) for b in ("0", "1-4", "5+")} | {"genes": total}

    weak_rows = defaultdict(Counter)
    for r in sim:
        w = r["weakness"]
        weak_rows[w]["genes"] += 1
        weak_rows[w]["gr_usable"] += bool(r["gr_usable"])
        weak_rows[w]["gr_usable_lists_main_disease"] += bool(
            ids(r["gr_usable"]) & ids(r["gr_chapter_for_main_disease"])
        )
        weak_rows[w]["main_disease_is_eval_disease"] += r["main_shares_eval_disease"] == "True"
    out["weakness"] = {w: dict(c) for w, c in sorted(weak_rows.items())}
    weak = [r for r in sim if r["weakness"] != "ok_counts"]
    weak_gr = sum(bool(r["gr_usable"]) for r in weak)
    out["weak_cross"] = {
        "weak_genes": len(weak),
        "weak_with_usable_gr": weak_gr,
        "weak_with_usable_gr_expected_ge5_numeric": round(weak_gr * p5),
        "epmc_title_bins_weak_all": epmc_estimate(["gr_weak", "nogr_weak"]),
        "epmc_title_bins_weak_without_gr": epmc_estimate(["nogr_weak"]),
        "epmc_title_bins_ok": epmc_estimate(["gr_ok", "nogr_ok"]),
    }

    # 2. Europe PMC
    ep = {}
    for key in ("hits_broad", "hits_ta", "hits_title"):
        ep[key] = {
            "construction_weighted": epmc_estimate(["gr_ok", "gr_weak", "nogr_ok", "nogr_weak"], key),
            "per_stratum": {
                s: dict(Counter(bin_hits(int(r[key])) for r in rs))
                | {"n": len(rs), "median": median(int(r[key]) for r in rs)}
                for s, rs in sorted(by_stratum.items())
            },
        }
    con_hits = [h for h in hits if h["stratum"] != "evaluation"]
    eval_hits = [h for h in hits if h["stratum"] == "evaluation"]

    def hit_stats(hs: list[dict]) -> dict:
        pm = {h["pmid"]: h for h in hs if h["pmid"]}
        return {
            "retrieved_rows": len(hs),
            "distinct_pmids": len(pm),
            "licences": dict(Counter(h["licence"] for h in hs).most_common()),
            "case_report_type": sum(h["case_report"] == "True" for h in hs),
            "review_type": sum(h["review"] == "True" for h in hs),
            "r1_heldout_pmids": sum(h["r1_heldout"] == "True" for h in pm.values()),
            "in_hpoa_pmids": sum(h["in_hpoa"] == "True" for h in pm.values()),
            "litpanel_source_pmids": sum(h["litpanel_source"] == "True" for h in pm.values()),
        }

    ep["construction_hits"] = hit_stats(con_hits)
    ep["evaluation_hits"] = hit_stats(eval_hits)
    if judged:
        ep["title_precision"] = wilson(sum(j["relevant"] == "Y" for j in judged), len(judged))
    out["europepmc"] = ep

    # 4. age
    age = Counter()
    for r in sim:
        hp, orpha = r["hpoa_onset"] == "True", bool(r["orphanet_onset"])
        src = (
            "hpoa_and_orphanet"
            if hp and orpha
            else "hpoa_only"
            if hp
            else "orphanet_only"
            if orpha
            else "none"
        )
        age[(src, "gr_usable" if r["gr_usable"] else "no_gr")] += 1
    gr_total = sum(bool(r["gr_usable"]) for r in sim)
    out["age"] = {
        "by_source_and_gr": {f"{a}|{b}": c for (a, b), c in sorted(age.items())},
        "gr_usable_genes": gr_total,
        "gr_expected_numeric_age": round(gr_total * age_rate),
        "gr_expected_numeric_age_ci": [
            round(gr_total * out["genereviews_sample30"]["numeric_age"]["lo"]),
            round(gr_total * out["genereviews_sample30"]["numeric_age"]["hi"]),
        ],
        "orphanet_onset_genes": sum(bool(r["orphanet_onset"]) for r in sim),
    }

    # 5. effort
    rows_per_chapter = PANEL["genereviews_rows"] / PANEL["genereviews_chapters"]
    rows_per_paper = PANEL["paper_rows"] / PANEL["paper_pmids"]
    rows_per_agent_hour = PANEL["raw_rows"] / (PANEL["agent_minutes"] / 60)
    crosscheck_rows_per_hour = PANEL["crosscheck_rows"] / (PANEL["crosscheck_minutes"] / 60)

    def scenario(units: int, rows_per_unit: float, parallel: int = 8, crosscheck_share: float = 0.1) -> dict:
        rows = units * rows_per_unit
        agent_h = rows / rows_per_agent_hour
        cc_h = rows * crosscheck_share / crosscheck_rows_per_hour
        return {
            "units": units,
            "rows": round(rows),
            "agent_hours": round(agent_h, 1),
            "wall_hours_at_8_parallel": round(agent_h / parallel, 1),
            "crosscheck_hours_10pct": round(cc_h, 1),
        }

    usable_chapters = {c for r in sim for c in ids(r["gr_usable"])}
    weak_chapters = {c for r in weak for c in ids(r["gr_usable"])}
    out["effort"] = {
        "rows_per_genereviews_chapter": round(rows_per_chapter, 2),
        "rows_per_cohort_paper": round(rows_per_paper, 2),
        "raw_rows_per_agent_hour": round(rows_per_agent_hour, 1),
        "crosscheck_rows_per_hour": round(crosscheck_rows_per_hour, 1),
        "usable_chapters": len(usable_chapters),
        "usable_chapters_of_weak_genes": len(weak_chapters),
        "genereviews_all_usable_chapters_ge5": scenario(round(len(usable_chapters) * p5), rows_per_chapter),
        "genereviews_weak_gene_chapters_ge5": scenario(round(len(weak_chapters) * p5), rows_per_chapter),
    }
    if judged:
        weak_nogr = out["weak_cross"]["epmc_title_bins_weak_without_gr"]
        precision = out["europepmc"]["title_precision"]["p"]
        candidates = round(weak_nogr["genes"] * (1 - weak_nogr["0"]) * precision)
        minutes_per_unit = PANEL["agent_minutes"] / PANEL["units_attempted"]
        survival = PANEL["units_kept"] / PANEL["units_attempted"]
        rows_per_unit = PANEL["paper_rows"] / PANEL["paper_units"]
        out["effort"]["papers_weak_genes_without_gr"] = {
            "candidate_genes": candidates,
            "agent_hours_to_attempt": round(candidates * minutes_per_unit / 60, 1),
            "panel_survival_rate": round(survival, 3),
            "expected_kept_units": round(candidates * survival),
            "rows_per_kept_unit": round(rows_per_unit, 1),
            "expected_rows": round(candidates * survival * rows_per_unit),
        }
    (d / "summary.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
