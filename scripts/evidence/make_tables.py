"""Write docs/evidence/TABLES.md: the evidence results as markdown tables, numbers only, read from committed result files."""

import csv

import fig_b_gate
from common import ROOT, load

OUT = ROOT / "docs" / "evidence" / "TABLES.md"
L: list[str] = []


def h(title: str, source: str) -> None:
    L.extend(["", f"## {title}", "", f"Source: {source}", ""])


def table(head: list[str], rows: list[list]) -> None:
    L.append("| " + " | ".join(head) + " |")
    L.append("|" + "|".join("---" for _ in head) + "|")
    for r in rows:
        L.append("| " + " | ".join(str(x) for x in r) + " |")
    L.append("")


def f4(x) -> str:
    return f"{x:.4f}"


def f3(x) -> str:
    return f"{x:.3f}"


def ci(v, k=4) -> str:
    return f"[{v[0]:+.{k}f}, {v[1]:+.{k}f}]"


def tsv(rel):
    with open(ROOT / rel, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def e0():
    h(
        "T1. EXP-000: E0 (production v3.0) on every cohort",
        "results/EXP-000/*.clustered-summary.json (R1) and *.summary.json (others)",
    )
    rows = []
    for name, label, split in [
        ("r1-v1-train", "R1-train", "train-side"),
        ("r1-v1-dev", "R1-dev", "dev"),
        ("r1-v1-test", "R1-test", "sealed"),
        ("mcrd", "MCRD", "sealed, eval-only"),
        ("ddd", "DDD", "sealed, eval-only"),
        ("s2", "S2", "simulated"),
    ]:
        suffix = "clustered-summary" if name.startswith("r1") else "summary"
        d = load(f"results/EXP-000/{name}__genphenia-v3.0__all.{suffix}.json")
        a, iv = d["all"], d["gene_in_vocab"]
        rows.append(
            [
                label,
                split,
                a["n"],
                f4(a["mrr"]),
                f"[{a['mrr_ci95'][0]:.4f}, {a['mrr_ci95'][1]:.4f}]" if "mrr_ci95" in a else "not in file",
                a.get("ci_resample_unit", ""),
                f3(a["top1"]),
                f3(a["top5"]),
                f3(a["top10"]),
                f3(a["top50"]),
                d["coverage"]["gene_not_in_vocab"],
                f3(iv["mrr"]),
            ]
        )
    table(
        [
            "Cohort",
            "Split",
            "n",
            "MRR",
            "95% CI",
            "CI unit",
            "top-1",
            "top-5",
            "top-10",
            "top-50",
            "gene not in vocab",
            "MRR in-vocab",
        ],
        rows,
    )


def b001():
    h("T2. EXP-B-001: rr-v1 grid on R1-dev (Delta MRR vs E0)", "results/EXP-B-001/r1-v1-dev__rr-v1-grid.json")
    rows = []
    for c in load("results/EXP-B-001/r1-v1-dev__rr-v1-grid.json")["configs"]:
        v = c["vs_e0"]
        rows.append(
            [
                c["name"],
                f4(c["all"]["mrr"]),
                f"{v['delta']:+.4f}",
                ci(v["ci95"]),
                f3(v["harmed"]),
                f3(v["helped"]),
            ]
        )
    table(["Config", "MRR", "Delta MRR", "95% CI", "harmed", "helped"], rows)


def b002():
    h("T3. EXP-B-002: rr-v2 (fitted on R1-train), dev Delta MRR vs E0", "results/EXP-B-002/rr-v2-fits.json")
    d = load("results/EXP-B-002/rr-v2-fits.json")
    rows = []
    for fit in d["fits"]:
        v = fit["dev"]["vs_e0"]
        l2 = fit.get("l2", fit.get("fit", {}).get("l2"))
        tr = (
            fit.get("train", {}).get("vs_e0", {}).get("delta") if isinstance(fit.get("train"), dict) else None
        )
        rows.append(
            [
                l2,
                f"{tr:+.4f}" if tr is not None else "",
                f"{v['delta']:+.4f}",
                ci(v["ci95"]),
                f3(v["harmed"]),
                f3(v["helped"]),
            ]
        )
    table(["L2", "train Delta", "dev Delta", "dev 95% CI", "harmed", "helped"], rows)
    rows = []
    for x in d["ablations_exploratory"]["results"]:
        rows.append(
            [
                x["without"],
                f"{x['zeroed']['delta']:+.4f}",
                f"{x['refit']['delta']:+.4f}",
                ci(x["refit"]["ci95"]),
                f3(x["refit"]["harmed"]),
            ]
        )
    table(["without (L2 = 0.1)", "zeroed Delta", "refit Delta", "refit 95% CI", "refit harmed"], rows)


def s3():
    h(
        "T4. EXP-S3-001: S3-dev (simulated interviews), Delta MRR vs E0+answers",
        "results/EXP-S3-001/s3-v1-dev__report.json",
    )
    d = load("results/EXP-S3-001/s3-v1-dev__report.json")
    rows = [
        [
            "E0-initial",
            f4(d["E0-initial"]["summary"]["mrr"]),
            f"{d['E0-initial']['vs_E0+answers']['delta']:+.4f}",
            "",
            "",
            "",
        ]
    ]
    for k, s in d["systems"].items():
        v = s["vs_E0+answers"]
        rows.append(
            [
                k,
                f4(s["summary"]["mrr"]),
                f"{v['delta']:+.4f}",
                ci(v["ci95"]),
                f3(v["harmed"]),
                f3(v["helped"]),
            ]
        )
    table(["System", "MRR", "Delta MRR", "95% CI (genes)", "harmed", "helped"], rows)
    table(
        ["cases", "questions per case", "yes per case", "no per case"],
        [
            [
                d["cases"],
                f"{d['questions_per_case']:.2f}",
                f"{d['yes_per_case']:.2f}",
                f"{d['no_per_case']:.2f}",
            ]
        ],
    )


def b003():
    h(
        "T5. EXP-B-003: rr-v1[neg=0.5] on sealed S3-test and R1-test",
        "results/EXP-B-003/s3-v1-test__report.json; results/EXP-B-003/r1-v1-test__rr-v1[neg=0.5]__report.json",
    )
    s = load("results/EXP-B-003/s3-v1-test__report.json")
    r = load("results/EXP-B-003/r1-v1-test__rr-v1[neg=0.5]__report.json")["views"]
    rr = s["systems"]["rr-v1[neg=0.5]"]["vs_E0+answers"]
    rows = [
        [
            "S3-test (n=9,990)",
            "vs E0+answers",
            f4(s["systems"]["E0+answers"]["summary"]["mrr"]),
            f4(s["systems"]["rr-v1[neg=0.5]"]["summary"]["mrr"]),
            f"{rr['delta']:+.4f}",
            ci(rr["ci95"]),
            f3(rr["harmed"]),
            f3(rr["helped"]),
        ],
    ]
    for view, key in [("R1-test, all view (n=2,548)", "all"), ("R1-test, present view", "present")]:
        v = r[key]["vs_e0"]
        rows.append(
            [
                view,
                "vs E0",
                "",
                f4(r[key]["summary"]["mrr"]),
                f"{v['delta']:+.4f}",
                ci(v["ci95"]),
                f3(v["harmed"]),
                f3(v["helped"]),
            ]
        )
    v = r["all"]["vs_e0_cases_with_excluded"]
    rows.append(
        [
            "R1-test, all view, cases with excluded terms (n=1,897)",
            "vs E0",
            "",
            "",
            f"{v['delta']:+.4f}",
            ci(v["ci95"]),
            f3(v["harmed"]),
            f3(v["helped"]),
        ]
    )
    table(
        [
            "Cohort / view",
            "Reference",
            "reference MRR",
            "rr-v1 MRR",
            "Delta MRR",
            "95% CI",
            "harmed",
            "helped",
        ],
        rows,
    )
    table(
        ["S3-test E0-initial MRR", "S3-test E0-initial Delta vs E0+answers"],
        [[f4(s["E0-initial"]["summary"]["mrr"]), f"{s['E0-initial']['vs_E0+answers']['delta']:+.4f}"]],
    )


def release():
    h(
        "T6. rerank-v1.0.0 release notes (diagnostic.ar-model), as printed",
        "GitHub release rerank-v1.0.0 of MateAlv/diagnostic.ar-model (gh release view); PR #2, merge c26301be",
    )
    table(
        ["Quantity", "Value"],
        [
            [
                "bundle sha256 (rerank-v1.0.tar.gz)",
                "4b83f5e39e003aca2dde834948392800655102199f8af099985191b69f8e79e2",
            ],
            ["parity: scorable R1-dev cases where E0 and rr-v1 ranks match EXP-B-003 tooling", 1680],
            ["of those, cases whose rank changes with rr-v1", 367],
            ["committed parity fixture (cases)", 50],
            ["latency sample (R1-dev cases with negations)", 1575],
            ["re-ranker, first call per case: p50 / p95 / max (ms)", "2.46 / 6.77 / 40.66"],
            ["v3.0 alone: p50 / p95 / max (ms)", "0.77 / 2.25 / 10.63"],
            ["bundle load (s)", 0.70],
        ],
    )


def front_a():
    for eid, view, title in [
        ("EXP-A-001", None, "T7. EXP-A-001: fine-tuning on simulator positives, R1-dev present view"),
        (
            "EXP-A-002f",
            "excluded",
            "T8. EXP-A-002f: negation parameters into frozen v3.0, R1-dev +excluded view",
        ),
        ("EXP-A-003f", "all", "T9. EXP-A-003f: sex, age, onset into frozen v3.0, R1-dev all view"),
    ]:
        h(
            title,
            f"results/{eid}/report.json (R1-dev Delta MRR vs E0, n=1,883, publication-clustered CI; S3-dev Delta vs E0+answers)",
        )
        rows = []
        for run in load(f"results/{eid}/report.json")["runs"]:
            if "pipeline-check" in run["run_id"]:
                continue
            r = run["r1_dev"] if view is None else run["r1_dev"][view]
            s3d = run["s3_dev"]
            s3v = (
                s3d
                if "delta" in s3d
                else next((x for x in s3d.values() if isinstance(x, dict) and "delta" in x), None)
            )
            rows.append(
                [
                    run["run_id"],
                    f"{r['delta']:+.4f}",
                    ci(r["ci95"]),
                    f3(r["harmed"]),
                    f3(r["helped"]),
                    f"{s3v['delta']:+.4f}" if s3v else "",
                ]
            )
        table(["Run", "R1-dev Delta MRR", "95% CI", "harmed", "helped", "S3-dev Delta"], rows)


def gate():
    h(
        "T10. Simulator gate G2 values per dataset (ADR-0012)",
        "results/realism/gate-v0.5.4-cand6-gonogo.json, gate-v0.4-cand3-gonogo.json, gate-v0.4-cand1.json, v0.5.4-cand6.json",
    )
    vals = fig_b_gate.collect()
    rows = []
    for k, v in vals.items():
        rows.append([k] + [f3(v[m]) if v.get(m) is not None else "n/a" for m in "abcde"])
    table(
        [
            "Dataset",
            "G2a literature MAE (truth layer)",
            "G2b R1-dev rho",
            "G2c W1 terms/case",
            "G2d C2ST AUC",
            "G2e gap",
        ],
        rows,
    )
    L.append(
        "Thresholds: G2a lower than UP and V03-full; G2b higher than both; G2c lower than both; G2d lower than both and <= 0.75; G2e smaller than both and <= 0.10. "
        "Candidate 1 was scored under the original rules (G2a emission layer, G2e target 0.512; its G2a and G2e are n/a here). "
        "G2b exists only where R1-dev was read (UP, V03-full, candidates 1, 2, 6)."
    )
    L.append("")
    rows = []
    for name, f in [
        ("UP", "up-graphens"),
        ("V03-full", "v0.3-full-baseline"),
        ("Candidate 2", "v0.4-cand2"),
        ("Candidate 6", "v0.5.4-cand6"),
    ]:
        d = load(f"results/realism/{f}.json")["g2b_dev_rho"]
        rows.append([name, d["genes_eligible"], d["genes_scored"], f4(d["mean_rho"])])
    table(["Dataset", "dev genes eligible", "genes scored", "G2b mean rho (all scored genes)"], rows)


def g2b_dev():
    h(
        "T11. G2b on R1-dev with bootstrap CIs (38 genes scored by all four datasets; 10,000 resamples over genes)",
        "docs/evidence/data/fig_c_g2b_dev_intervals.json (scripts/evidence/fig_c_g2b_dev.py)",
    )
    d = load("docs/evidence/data/fig_c_g2b_dev_intervals.json")
    rows = []
    for k in ("UP", "Candidate 2", "Candidate 6", "V03-full"):
        r, b = d["datasets"][k], d["bitacora_datasets"][k]
        rows.append(
            [
                k,
                f3(r["mean"]),
                f"[{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}]",
                f"{b[0]:.3f} [{b[1]:.3f}, {b[2]:.3f}]",
            ]
        )
    table(["Dataset", "mean rho", "95% CI (recomputed)", "BITACORA 2026-10-03"], rows)
    rows = []
    for k in ("UP", "Candidate 2", "V03-full"):
        r, b = d["candidate6_minus"][k], d["bitacora_candidate6_minus"][k]
        rows.append(
            [
                f"candidate 6 minus {k}",
                f"{r['diff']:+.3f}",
                f"[{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]",
                f"{b[0]:+.3f} [{b[1]:+.3f}, {b[2]:+.3f}]",
            ]
        )
    table(["Paired difference", "difference", "95% CI (recomputed)", "BITACORA"], rows)


def terms():
    h(
        "T12. Present terms per case (G2c view)",
        "docs/evidence/data/fig_d_terms_per_case.json (from results/realism/*.json g2c blocks)",
    )
    d = load("docs/evidence/data/fig_d_terms_per_case.json")
    rows = []
    for k, v in d.items():
        p = v["percentiles"]
        rows.append(
            [k, f"{v['n']:,}", f"{v['mean']:.2f}"]
            + [f"{p[x]:g}" for x in ("10", "25", "50", "75", "90")]
            + [f3(v["w1_vs_r1_train"]) if v["w1_vs_r1_train"] is not None else ""]
        )
    table(["Dataset", "cases", "mean", "p10", "p25", "p50", "p75", "p90", "W1 vs R1-train"], rows)


def categories():
    h(
        "T13. Term categories, share of present terms (ANALYSIS-002 and ANALYSIS-003)",
        "docs/evidence/data/fig_e_term_categories.json",
    )
    d = load("docs/evidence/data/fig_e_term_categories.json")
    for frame, title in [
        ("frame1", "Frame 1: all R1-train, kb-v4"),
        ("frame2", "Frame 2: R1-train uncited, kb-v3"),
    ]:
        L.append(f"{title}:")
        L.append("")
        rows = [
            [k] + [f3(v[c]) for c in ("explained", "more_specific", "related_ic_ge_2", "weak_ic_lt_2")]
            for k, v in d[frame].items()
        ]
        table(["Dataset", "explained", "more specific", "related (IC>=2)", "weak (IC<2)"], rows)


def literature():
    h(
        "T14. Literature: sources, frozen lists (lit-sources-v1)",
        "data/lit-sources/lit-sources-v1/summary.json; results/analyses/SOURCES-ACQUISITION-001/summary.json",
    )
    s = load("data/lit-sources/lit-sources-v1/summary.json")
    sa = load("results/analyses/SOURCES-ACQUISITION-001/summary.json")["source_sizes"]
    table(
        ["Quantity", "Value"],
        [
            ["GeneReviews chapters in gene map", s["chapters"]["in_gene_map"]],
            ["usable chapters", s["chapters"]["by_status"]["usable"]],
            ["dropped: touches evaluation unit", s["chapters"]["by_status"]["dropped_eval_unit"]],
            ["dropped: cites held-out PMID", s["chapters"]["by_status"]["dropped_heldout_pmid"]],
            ["dropped: no construction gene", s["chapters"]["by_status"]["dropped_no_construction_gene"]],
            [
                "usable with numeric table / age sentence",
                f"{s['chapters']['usable_with_numeric_table']} / {s['chapters']['usable_with_numeric_age_sentence']}",
            ],
            [
                "construction genes covered by chapters (weak)",
                f"{s['chapters']['construction_genes_covered']} ({s['chapters']['weak_construction_genes_covered']})",
            ],
            [
                "open-access records screened (pass 1 + pass 2)",
                f"{s['papers']['open_access_records_screened']} + {s['papers']['second_pass_records_screened']}",
            ],
            [
                "selected papers (pass 1 / total)",
                f"{s['papers']['selected_cited_by_genereviews']} / {s['papers']['selected']}",
            ],
            [
                "genes with selected paper (weak)",
                f"{s['papers']['genes_with_selected_paper']} ({s['papers']['weak_genes_with_selected_paper']})",
            ],
            [
                "genes with chapter or paper (weak of 2,485 simulable weak)",
                f"{s['genes']['with_chapter_or_paper']} ({s['genes']['weak_with_chapter_or_paper']})",
            ],
            [
                "G2P records / PanelApp entries / PanelApp panels / MedlinePlus conditions",
                f"{sa['g2p_records']} / {sa['panelapp_gene_entries']} / {sa['panelapp_panels']} / {sa['medlineplus_conditions']}",
            ],
        ],
    )
    h(
        "T15. Literature: blind cross-check (lit-extract-v1)",
        "data/lit-extract/crosscheck/lit-extract-v1.{tsv,summary.json,adjudication.tsv}; docs/evidence/data/fig_f_literature_quality.json",
    )
    d = load("docs/evidence/data/fig_f_literature_quality.json")
    rows = [
        [
            k,
            v["agree"],
            v["n"],
            f"{v['wilson95'][0] * 100:.1f}%",
            f"[{v['wilson95'][1] * 100:.1f}%, {v['wilson95'][2] * 100:.1f}%]",
        ]
        for k, v in d["crosscheck"].items()
    ]
    table(["Checker", "agree", "items", "rate", "Wilson 95% CI"], rows)
    table(["Verdict on the 29 disagreements", "count"], [[k, v] for k, v in d["crosscheck_verdicts"].items()])
    h(
        "T16. Literature: audit of 98 sampled sources (LIT-AUDIT-v1)",
        "data/lit-extract/audit/lit-extract-v1.{items,adjudication,summary}; docs/evidence/data/fig_f_literature_quality.json",
    )
    table(
        ["Kind", "valid", "not valid"],
        [[k, v.get("yes", 0), v.get("no", 0)] for k, v in d["audit_verdicts"].items()],
    )
    rows = [
        [
            k,
            f"{v['k']}/{v['n']}",
            f"{v['wilson95'][0] * 100:.2f}%",
            f"[{v['wilson95'][1] * 100:.2f}%, {v['wilson95'][2] * 100:.2f}%]",
        ]
        for k, v in {**d["rates"], **d["recall"]}.items()
    ]
    table(["Estimate", "k/n", "point", "Wilson 95% CI"], rows)
    h(
        "T17. Literature: builds",
        "data/lit-build/hpoa-lit-v1.report.json; data/lit-build/hpoa-lit-v2.report.json",
    )
    rows = []
    for v in (1, 2):
        b = load(f"data/lit-build/hpoa-lit-v{v}.report.json")
        rows.append(
            [
                f"v{v}",
                len(b["inputs"]["shards_accepted"]),
                b["rows_in"]["total"],
                b["rows_in"]["feature"],
                b["rows_in"]["age_onset"],
                b["rows_in"]["age_presentation"],
                b["hpoa_enriched"]["lit_rows"],
                b["hpoa_lit"]["diseases"],
                b["onset_ages"]["diseases"],
                b["presentation_ages"]["diseases"],
                b["code"]["sha"][:7],
            ]
        )
    table(
        [
            "Build",
            "shards",
            "rows in",
            "feature rows",
            "AGE_ONSET rows",
            "AGE_PRESENTATION rows",
            "HPOA lit rows",
            "diseases",
            "onset-age diseases",
            "presentation-age diseases",
            "code",
        ],
        rows,
    )


def main() -> None:
    L.append("# Evidence tables (numbers only)")
    L.append("")
    L.append(
        "Generated by `scripts/evidence/make_tables.py` from committed result files; do not edit by hand. "
        "Splits: R1-dev, R1-test (sealed), S3-dev, S3-test (sealed), train-side as stated in each table."
    )
    for fn in (e0, b001, b002, s3, b003, release, front_a, gate, g2b_dev, terms, categories, literature):
        fn()
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
