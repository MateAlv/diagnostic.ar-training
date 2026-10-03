"""Check numbers printed in docs against the committed result files; write docs/evidence/data/number_checks.tsv.

Each check is (id, doc, doc value as printed, file, value read from the file). A doc value matches when it equals the
file value rounded to the doc's decimals (DIFF otherwise; ROUND+-1 when it is one unit of the last printed digit off).
"""

import csv
from decimal import Decimal

from common import DATA_DIR, ROOT, load

CHECKS: list[tuple] = []


def add(cid, doc, printed, file, value):
    CHECKS.append((cid, doc, str(printed), file, value))


def lookup(rel, *path):
    d = load(rel)
    for p in path:
        d = d[p]
    return d


def pick(lst, key, val):
    return next(x for x in lst if x[key] == val)


def exp_000():
    doc = "docs/experiments/EXP-000.md"
    for tag, n, mrr, lo, hi in [
        ("train", 4103, "0.440", "0.387", "0.494"),
        ("dev", 1883, "0.448", "0.399", "0.504"),
        ("test", 2548, "0.370", "0.266", "0.480"),
    ]:
        f = f"results/EXP-000/r1-v1-{tag}__genphenia-v3.0__all.clustered-summary.json"
        d = load(f)["all"]
        add(f"EXP-000 R1-{tag} n", doc, n, f, d["n"])
        add(f"EXP-000 R1-{tag} MRR", doc, mrr, f, d["mrr"])
        add(f"EXP-000 R1-{tag} MRR CI low", doc, lo, f, d["mrr_ci95"][0])
        add(f"EXP-000 R1-{tag} MRR CI high", doc, hi, f, d["mrr_ci95"][1])
    for name, n, mrr, top1 in [
        ("mcrd", 229, "0.747", "0.677"),
        ("ddd", 1048, "0.757", "0.689"),
        ("s2", 5228, "0.812", "0.751"),
    ]:
        f = f"results/EXP-000/{name}__genphenia-v3.0__all.summary.json"
        d = load(f)["all"]
        add(f"EXP-000 {name} n", doc, n, f, d["n"])
        add(f"EXP-000 {name} MRR", doc, mrr, f, d["mrr"])
        add(f"EXP-000 {name} top-1", doc, top1, f, d["top1"])


def exp_b001():
    doc = "docs/experiments/EXP-B-001.md"
    f = "results/EXP-B-001/r1-v1-dev__rr-v1-grid.json"
    cfgs = load(f)["configs"]
    for name, delta, lo, hi, harmed, helped in [
        ("neg=0.5", "-0.0067", "-0.0235", "+0.0051", "0.116", "0.079"),
        ("neg=2.0", "-0.0219", "-0.0611", "+0.0060", "0.186", "0.112"),
        ("sex=1.0", "+0.0003", "-0.0006", "+0.0014", "0.019", "0.033"),
        ("age=2.0", "-0.0079", "-0.0154", "-0.0005", "0.114", "0.107"),
        ("onset=0.5", "+0.0017", "-0.0012", "+0.0051", "0.061", "0.090"),
        ("stage2-combined", "+0.0020", "-0.0012", "+0.0053", "0.070", "0.104"),
    ]:
        try:
            c = pick(cfgs, "name", name)
        except StopIteration:
            c = (
                pick(cfgs, "name", "stage2-combined (sex=1, onset=0.5)")
                if name == "stage2-combined"
                else None
            )
        if c is None:
            continue
        v = c["vs_e0"]
        add(f"EXP-B-001 {name} delta", doc, delta, f, v["delta"])
        add(f"EXP-B-001 {name} CI low", doc, lo, f, v["ci95"][0])
        add(f"EXP-B-001 {name} CI high", doc, hi, f, v["ci95"][1])
        add(f"EXP-B-001 {name} harmed", doc, harmed, f, v["harmed"])
        add(f"EXP-B-001 {name} helped", doc, helped, f, v["helped"])


def exp_b002():
    doc = "docs/experiments/EXP-B-002.md"
    f = "results/EXP-B-002/rr-v2-fits.json"
    fits = load(f)["fits"]
    for l2, dev, lo, hi, harmed in [
        (0.01, "0.0562", "0.0084", "0.1172", "0.103"),
        (0.1, "0.0565", "0.0086", "0.1179", "0.103"),
        (1, "0.0564", "0.0086", "0.1179", "0.100"),
        (10, "0.0494", "0.0048", "0.1105", "0.100"),
    ]:
        fit = (
            next(x for x in fits if abs(x.get("l2", x.get("fit", {}).get("l2", -1)) - l2) < 1e-9)
            if "l2" in fits[0] or "l2" in fits[0].get("fit", {})
            else None
        )
        if fit is None:
            continue
        v = fit["dev"]["vs_e0"]
        add(f"EXP-B-002 L2={l2} dev delta", doc, dev, f, v["delta"])
        add(f"EXP-B-002 L2={l2} CI low", doc, lo, f, v["ci95"][0])
        add(f"EXP-B-002 L2={l2} CI high", doc, hi, f, v["ci95"][1])
    ab = load(f)["ablations_exploratory"]["results"]
    neg = next(x for x in ab if x["without"] == "negation")
    add("EXP-B-002 refit without negation delta", doc, "0.0014", f, neg["refit"]["delta"])
    add("EXP-B-002 zeroed without negation delta", doc, "0.0019", f, neg["zeroed"]["delta"])


def exp_s3():
    doc = "docs/experiments/EXP-S3-001.md"
    f = "results/EXP-S3-001/s3-v1-dev__report.json"
    d = load(f)
    add("EXP-S3-001 questions per case", doc, "6.88", f, d["questions_per_case"])
    add("EXP-S3-001 cases", doc, 10210, f, d["cases"])
    add("EXP-S3-001 E0-initial MRR", doc, "0.3178", f, d["E0-initial"]["summary"]["mrr"])
    add("EXP-S3-001 E0+answers MRR", doc, "0.3298", f, d["systems"]["E0+answers"]["summary"]["mrr"])
    for name, delta, lo, hi, harmed, helped in [
        ("rr-v1[neg=0.5]", "0.0045", "0.0034", "0.0056", "0.040", "0.168"),
        ("rr-v1[neg=1]", "0.0078", "0.0064", "0.0093", "0.053", "0.222"),
        ("rr-v1[neg=2]", "0.0095", "0.0075", "0.0116", "0.072", "0.277"),
        ("rr-v1[all=1]", "0.0140", "0.0120", "0.0159", "0.065", "0.289"),
        ("rr-v2[EXP-B-002 l2=0.1]", "-0.0299", "-0.0326", "-0.0271", "0.282", "0.078"),
    ]:
        v = d["systems"][name]["vs_E0+answers"]
        add(f"EXP-S3-001 {name} delta", doc, delta, f, v["delta"])
        add(f"EXP-S3-001 {name} CI low", doc, lo, f, v["ci95"][0])
        add(f"EXP-S3-001 {name} CI high", doc, hi, f, v["ci95"][1])
        add(f"EXP-S3-001 {name} harmed", doc, harmed, f, v["harmed"])
        add(f"EXP-S3-001 {name} helped", doc, helped, f, v["helped"])


def exp_b003():
    doc = "docs/experiments/EXP-B-003.md"
    f = "results/EXP-B-003/s3-v1-test__report.json"
    d = load(f)
    add("EXP-B-003 S3-test cases", doc, 9990, f, d["cases"])
    add("EXP-B-003 S3-test E0-initial MRR", doc, "0.3204", f, d["E0-initial"]["summary"]["mrr"])
    add("EXP-B-003 S3-test E0+answers MRR", doc, "0.3336", f, d["systems"]["E0+answers"]["summary"]["mrr"])
    add("EXP-B-003 S3-test rr MRR", doc, "0.3380", f, d["systems"]["rr-v1[neg=0.5]"]["summary"]["mrr"])
    v = d["systems"]["rr-v1[neg=0.5]"]["vs_E0+answers"]
    for k, p, val in [
        ("delta", "0.0044", v["delta"]),
        ("CI low", "0.0032", v["ci95"][0]),
        ("CI high", "0.0057", v["ci95"][1]),
        ("harmed", "0.039", v["harmed"]),
        ("helped", "0.176", v["helped"]),
    ]:
        add(f"EXP-B-003 S3-test {k}", doc, p, f, val)
    add("EXP-B-003 S3-test E0-initial delta", doc, "-0.0132", f, d["E0-initial"]["vs_E0+answers"]["delta"])
    add("EXP-B-003 S3-test questions per case", doc, "6.89", f, d["questions_per_case"])
    f = "results/EXP-B-003/r1-v1-test__rr-v1[neg=0.5]__report.json"
    d = load(f)["views"]
    add("EXP-B-003 R1-test all MRR", doc, "0.3674", f, d["all"]["summary"]["mrr"])
    add("EXP-B-003 R1-test present MRR", doc, "0.3698", f, d["present"]["summary"]["mrr"])
    v = d["all"]["vs_e0"]
    for k, p, val in [
        ("delta", "-0.0025", v["delta"]),
        ("CI low", "-0.0070", v["ci95"][0]),
        ("CI high", "0.0013", v["ci95"][1]),
        ("harmed", "0.090", v["harmed"]),
        ("helped", "0.063", v["helped"]),
    ]:
        add(f"EXP-B-003 R1-test all {k}", doc, p, f, val)
    v = d["all"]["vs_e0_cases_with_excluded"]
    add("EXP-B-003 R1-test excluded-cases delta", doc, "-0.0033", f, v["delta"])
    add("EXP-B-003 R1-test excluded-cases n", doc, 1897, f, v["n"])
    add("EXP-B-003 R1-test present delta", doc, "0", f, d["present"]["vs_e0"]["delta"])


def exp_a():
    for eid, view, rows in [
        (
            "EXP-A-001",
            None,
            [
                ("a001-c1-lr1e-5-bntrain-s0", "-0.0913", "-0.1223", "-0.0588", "0.461"),
                ("a001-c3-lr2e-4-bntrain-s0", "-0.2047", "-0.2445", "-0.1627", "0.603"),
                ("a001-c6-lr2e-4-bnfrozen-s0", "-0.2075", "-0.2478", "-0.1641", "0.607"),
            ],
        ),
        (
            "EXP-A-002f",
            "excluded",
            [
                ("a002f-c4-neg2-lr1e-4-s0", "-0.1365", "-0.1864", "-0.0854", "0.448"),
                ("a002f-c5-neg2-lr1e-3-s0", "-0.2542", "-0.3059", "-0.1958", "0.596"),
                ("a002f-c6-neg2-lr1e-2-s0", "-0.2788", "-0.3306", "-0.2232", "0.635"),
            ],
        ),
        (
            "EXP-A-003f",
            "all",
            [
                ("a003f-c1-cov16-lr1e-4-s0", "-0.2090", "-0.2584", "-0.1556", "0.545"),
                ("a003f-c3-cov16-lr1e-2-s0", "-0.2310", "-0.2805", "-0.1776", "0.593"),
                ("a003f-c6-cov64-lr1e-2-s0", "-0.2336", "-0.2837", "-0.1794", "0.588"),
            ],
        ),
    ]:
        f = f"results/{eid}/report.json"
        runs = load(f)["runs"]
        for rid, delta, lo, hi, harmed in rows:
            r = pick(runs, "run_id", rid)["r1_dev"]
            v = r if view is None else r[view]
            add(f"{eid} {rid} R1-dev delta", f"docs/experiments/{eid}.md", delta, f, v["delta"])
            add(f"{eid} {rid} CI low", f"docs/experiments/{eid}.md", lo, f, v["ci95"][0])
            add(f"{eid} {rid} CI high", f"docs/experiments/{eid}.md", hi, f, v["ci95"][1])
            add(f"{eid} {rid} harmed", f"docs/experiments/{eid}.md", harmed, f, v["harmed"])
    runs = load("results/EXP-A-002f/report.json")["runs"]
    s3 = [pick(runs, "run_id", f"a002f-c5-neg2-lr1e-3-s{i}")["s3_dev"] for i in range(3)]
    sample = s3[0]
    key = (
        "delta"
        if "delta" in sample
        else next(k for k in sample if isinstance(sample[k], dict) and "delta" in sample[k])
    )
    get = (lambda x: x["delta"]) if key == "delta" else (lambda x: x[key]["delta"])
    add(
        "EXP-A-002f c5 s0 S3-dev delta",
        "docs/experiments/EXP-A-002f.md",
        "0.0925",
        "results/EXP-A-002f/report.json",
        get(s3[0]),
    )


GATE = "results/realism/gate-v0.5.4-cand6-gonogo.json"


def gate():
    g = load(GATE)
    md = "results/realism/gate-v0.5.4-cand6-gonogo.md"
    for name, key, vals in [
        ("UP", ("baselines", "up-graphens"), dict(a="0.416", b="0.231", c="3.717", d="0.840", e="0.414")),
        (
            "V03-full",
            ("baselines", "v0.3-full-baseline"),
            dict(a="0.336", b="0.095", c="1.653", d="0.819", e="0.183"),
        ),
        ("cand3", ("secondary", "v0.4-cand3-full-nodev"), dict(a="0.305", c="1.732", d="0.764", e="0.142")),
        ("cand4", ("secondary", "v0.5-cand4-full-nodev"), dict(a="0.307", c="5.754", d="0.822", e="0.204")),
        ("cand5", ("secondary", "v0.5.1-cand5-full-nodev"), dict(a="0.306", c="1.908", d="0.809", e="0.049")),
        (
            "cand6a",
            ("secondary", "v0.5.2-cand6a-full-nodev"),
            dict(a="0.306", c="2.955", d="0.764", e="0.011"),
        ),
        (
            "cand6b",
            ("secondary", "v0.5.3-cand6b-full-nodev"),
            dict(a="0.304", c="1.816", d="0.721", e="0.077"),
        ),
        (
            "cand6",
            ("candidates", "v0.5.4-cand6-full-nodev", "values"),
            dict(a="0.304", c="1.795", d="0.730", e="0.079"),
        ),
    ]:
        d = g
        for k in key:
            d = d[k]
        for m, p in vals.items():
            add(f"gate {name} G2{m}", md, p, GATE, d[m])
    gb = load("results/realism/gate-v0.4-cand1.json")
    c1 = gb["candidates"]["v0.4-cand1"]["values"]
    for m, p in dict(b="0.152", c="1.214", d="0.737").items():
        add(
            f"gate cand1 G2{m}",
            "results/realism/gate-v0.4-cand1.md",
            p,
            "results/realism/gate-v0.4-cand1.json",
            c1[m],
        )
    g3 = load("results/realism/gate-v0.4-cand3-gonogo.json")["secondary"]["v0.4-cand2"]
    for m, p in dict(a="0.304", b="0.193", c="1.315", d="0.792", e="0.242").items():
        add(
            f"gate cand2 G2{m}",
            "results/realism/gate-v0.4-cand2.md / cand3 gonogo",
            p,
            "results/realism/gate-v0.4-cand3-gonogo.json",
            g3[m],
        )
    adr = "docs/decisions/0012-data-quality-gate.md (amendment 5)"
    c6 = load("results/realism/v0.5.4-cand6.json")
    f6 = "results/realism/v0.5.4-cand6.json"
    add("ADR-0012 am.5 cand6 G2d", adr, "0.730", f6, c6["g2d_c2st"]["auc"])
    add("ADR-0012 am.5 cand6 G2d CI low", adr, "0.699", f6, c6["g2d_c2st"]["ci95"][0])
    add("ADR-0012 am.5 cand6 G2d CI high", adr, "0.764", f6, c6["g2d_c2st"]["ci95"][1])
    add("ADR-0012 am.5 cand6 G2b-train", adr, "0.519", f6, c6["g2b_train_rho"]["mean_rho"])
    add(
        "ADR-0012 am.5 cand6 terms per case",
        adr,
        "6.90",
        f6,
        c6["g2c_terms_per_case"]["present"]["sim"]["mean"],
    )
    add(
        "ADR-0012 am.5 cand6 p90",
        adr,
        "13",
        f6,
        c6["g2c_terms_per_case"]["present"]["sim"]["percentiles"]["90"],
    )
    add(
        "ADR-0012 am.5 real p90",
        adr,
        "17",
        f6,
        c6["g2c_terms_per_case"]["present"]["r1_train"]["percentiles"]["90"],
    )
    add(
        "ADR-0012 am.5 real terms per case",
        adr,
        "8.70",
        f6,
        c6["g2c_terms_per_case"]["present"]["r1_train"]["mean"],
    )
    v03 = "results/realism/v0.3-full-baseline.json"
    add(
        "ADR-0012 am.5 V03-full terms per case (doc says 8.42)",
        adr,
        "8.42",
        v03,
        load(v03)["g2c_terms_per_case"]["present"]["sim"]["mean"],
    )
    add(
        "ADR-0012 am.5 age median |log ratio| cand6",
        adr,
        "0.585",
        f6,
        c6["age"]["median_abs_log_ratio"]
        if "median_abs_log_ratio" in c6["age"]
        else c6["age"].get("median_abs_log_ratio_vs_r1_train"),
    )
    add("BITACORA G2b dev cand6", "docs/BITACORA.md 2026-10-03", "0.159", f6, c6["g2b_dev_rho"]["mean_rho"])
    add(
        "BITACORA G2b dev UP (all 42 genes)",
        "docs/decisions/0012 am.5 (UP 0.231)",
        "0.231",
        "results/realism/up-graphens.json",
        load("results/realism/up-graphens.json")["g2b_dev_rho"]["mean_rho"],
    )
    add(
        "BITACORA G2b dev V03-full",
        "docs/decisions/0012 am.5",
        "0.095",
        v03,
        load(v03)["g2b_dev_rho"]["mean_rho"],
    )
    c6b = "results/realism/v0.5.3-cand6b-full-nodev.json"
    add(
        "STATE cand6b terms per case",
        "docs/STATE.md",
        "6.88",
        c6b,
        load(c6b)["g2c_terms_per_case"]["present"]["sim"]["mean"],
    )
    c6a = "results/realism/v0.5.2-cand6a-full-nodev.json"
    add(
        "ANALYSIS-006 cand6a terms per case",
        "docs/analyses/ANALYSIS-006-candidate-6a.md",
        "5.74",
        c6a,
        load(c6a)["g2c_terms_per_case"]["present"]["sim"]["mean"],
    )
    add(
        "ANALYSIS-006 cand6a G2b-train",
        "docs/analyses/ANALYSIS-006-candidate-6a.md",
        "0.507",
        c6a,
        load(c6a)["g2b_train_rho"]["mean_rho"],
    )
    add(
        "ANALYSIS-006 cand6a G2e E0 MRR",
        "docs/analyses/ANALYSIS-006-candidate-6a.md",
        "0.394",
        c6a,
        load(c6a)["g2e_e0"]["mrr"],
    )


def literature():
    f = "data/lit-sources/lit-sources-v1/summary.json"
    s = load(f)
    doc = "docs/analyses/SOURCES-ACQUISITION-001.md"
    for label, printed, val in [
        ("usable chapters", 695, s["chapters"]["by_status"]["usable"]),
        ("chapters dropped eval unit", 78, s["chapters"]["by_status"]["dropped_eval_unit"]),
        ("chapters dropped held-out PMID", 99, s["chapters"]["by_status"]["dropped_heldout_pmid"]),
        ("construction genes covered by chapters", 1084, s["chapters"]["construction_genes_covered"]),
        ("usable with numeric table", 332, s["chapters"]["usable_with_numeric_table"]),
        ("selected papers", 1011, s["papers"]["selected"]),
        ("pass 1 selected", 707, s["papers"]["selected_cited_by_genereviews"]),
        ("genes with selected paper", 775, s["papers"]["genes_with_selected_paper"]),
        (
            "pass 2 genes with selected paper (doc table: 218)",
            218,
            s["papers"]["second_pass_genes_with_selected_paper"],
        ),
        ("weak genes with chapter or paper", 735, s["genes"]["weak_with_chapter_or_paper"]),
        ("genes with chapter or paper", 1304, s["genes"]["with_chapter_or_paper"]),
        (
            "records screened total",
            14332,
            s["papers"]["open_access_records_screened"] + s["papers"]["second_pass_records_screened"],
        ),
    ]:
        add(f"lit-sources-v1 {label}", doc, printed, f, val)
    sa = load("results/analyses/SOURCES-ACQUISITION-001/summary.json")
    f = "results/analyses/SOURCES-ACQUISITION-001/summary.json"
    add("PanelApp panels", doc, 433, f, sa["source_sizes"]["panelapp_panels"])
    add("PanelApp gene entries", doc, 32534, f, sa["source_sizes"]["panelapp_gene_entries"])
    add("G2P records", doc, 3851, f, sa["source_sizes"]["g2p_records"])
    add("MedlinePlus conditions", doc, 1305, f, sa["source_sizes"]["medlineplus_conditions"])
    f = "data/lit-extract/crosscheck/lit-extract-v1.summary.json"
    x = load(f)
    add("crosscheck items", "docs/analyses/LIT-CROSSCHECK-v1.md", 744, f, x["items"])
    add("crosscheck agree", "docs/analyses/LIT-CROSSCHECK-v1.md", 715, f, x["agree"])
    add("crosscheck agreement", "docs/analyses/LIT-CROSSCHECK-v1.md", "0.961", f, x["agreement"])
    f = "data/lit-extract/audit/lit-extract-v1.summary.json"
    a = load(f)["total"]
    d = "docs/analyses/LIT-AUDIT-v1.md"
    add("audit sources", d, 98, f, a["sources"])
    add("audit answered", d, 98, f, a["answered"])
    add("audit rows audited", d, 852, f, a["rows_audited"])
    add("audit sources with issue", d, 58, f, a["sources_with_issue"])
    add("audit missed facts raised", d, 143, f, a["missed_facts"])
    add("audit bad_rows raised", d, 116, f, a["bad_rows"])
    add("audit wrong_unit raised", d, 6, f, a["wrong_unit_rows"])
    lb = "data/lit-build/hpoa-lit-v2.report.json"
    b = load(lb)
    add("build v2 shards accepted", "docs/BITACORA.md", 97, lb, len(b["inputs"]["shards_accepted"]))
    add("build v2 rows in", "docs/BITACORA.md", 7083, lb, b["rows_in"]["total"])
    b1 = load("data/lit-build/hpoa-lit-v1.report.json")
    add(
        "build v1 rows in",
        "docs/BITACORA.md (2026-10-02 build entry)",
        7085,
        "data/lit-build/hpoa-lit-v1.report.json",
        b1["rows_in"]["total"],
    )


def analyses():
    d3 = "docs/analyses/ANALYSIS-003-why-simulated-patients-are-hard.md"
    f = "results/analyses/ANALYSIS-003/e0_ablation.json"
    a = load(f)
    for label, printed, key, field in [
        ("cand2 as exported", "0.163", "as_exported", "mrr_in_vocab"),
        ("no noise", "0.472", "no_noise", "mrr_in_vocab"),
        ("no generalisation", "0.179", "no_generalization", "mrr_in_vocab"),
        ("no specialisation", "0.194", "no_specialization", "mrr_in_vocab"),
        ("ungeneralised no noise", "0.559", "profile_terms_ungeneralized_no_noise", "mrr_in_vocab"),
        ("all true terms", "0.742", "all_true_terms", "mrr_in_vocab"),
        ("R1-train uncited", "0.405", "R1-train uncited", "mrr_in_vocab"),
        ("uncited explained only", "0.479", "R1-train uncited, explained terms only", "mrr_in_vocab"),
        ("cand2 terms per case", "7.45", "as_exported", "terms_per_case"),
        ("uncited terms per case", "8.11", "R1-train uncited", "terms_per_case"),
    ]:
        add(f"ANALYSIS-003 E0 {label}", d3, printed, f, a[key][field])
    add("ANALYSIS-003 mean IC of simulator noise (doc: 4.79)", d3, "4.79", f, a["mean_ic"]["sim_noise"])
    f = "results/analyses/ANALYSIS-003/uncited_categories.kb-v3.json"
    u = load(f)["uncited"]
    for label, printed, key in [
        ("explained", "0.668", "explained"),
        ("more specific", "0.093", "more_specific"),
        ("related", "0.082", "related_ic>=2"),
        ("weak", "0.157", "weak_ic<2"),
        ("unexplained per case", "1.92", "unexplained_per_case_mean"),
    ]:
        add(f"ANALYSIS-003 uncited vs kb-v3 {label}", d3, printed, f, u[key])
    d4 = "docs/analyses/ANALYSIS-004-noise-signal-and-candidate-3.md"
    f = "results/analyses/ANALYSIS-004/unexplained_signal.json"
    s4 = load(f)
    for label, printed, key in [
        ("real unexplained", "0.059", "real uncited: unexplained terms only"),
        ("real explained", "0.498", "real uncited: explained terms only"),
        ("sim vocabulary noise", "0.001", "sim: vocabulary noise only"),
        ("sim related noise", "0.030", "sim: related noise only"),
    ]:
        add(f"ANALYSIS-004 E0 MRR {label}", d4, printed, f, s4[key]["mrr_in_vocab"])
    f = "results/analyses/ANALYSIS-004/unexplained_in_g2p.json"
    g = load(f)
    add(
        "ANALYSIS-004 share annotated in unmasked g2p",
        d4,
        "0.135",
        f,
        g["share_annotated_to_gene_in_unmasked_g2p"],
    )
    add("ANALYSIS-004 MRR in g2p", d4, "0.305", f, g["in_g2p"]["mrr_in_vocab"])
    add("ANALYSIS-004 MRR not in g2p", d4, "0.026", f, g["not_in_g2p"]["mrr_in_vocab"])
    d5 = "docs/analyses/ANALYSIS-005-what-separates-candidate-5.md"
    f = "results/analyses/ANALYSIS-005/c2st_features.cand5.json"
    c = load(f)
    add("ANALYSIS-005 pairs", d5, 3514, f, c["pairs"])
    t = c["top"][0]
    add("ANALYSIS-005 term-count AUC", d5, "0.655", f, t["auc"])
    add("ANALYSIS-005 term-count real mean", d5, "8.06", f, t["real_mean"])
    add("ANALYSIS-005 term-count sim mean", d5, "14.26", f, t["sim_mean"])
    f = "results/analyses/ANALYSIS-005/record_size_by_gene.json"
    r = load(f)
    add("ANALYSIS-005 genes with >=10 train patients", d5, 84, f, r["genes_with_>=10_r1_train"])
    add("ANALYSIS-005 real terms per case", d5, "8.60", f, r["mean_terms_per_case_real"])
    add("ANALYSIS-005 sim terms per case", d5, "13.38", f, r["mean_terms_per_case_sim"])
    add(
        "ANALYSIS-005 Spearman sim size vs true terms",
        d5,
        "0.966",
        f,
        r["spearman_sim_record_size_vs_sim_true_terms"],
    )
    add(
        "ANALYSIS-005 Spearman real size vs sim true terms",
        d5,
        "0.532",
        f,
        r["spearman_real_record_size_vs_sim_true_terms"],
    )
    d6 = "docs/analyses/ANALYSIS-006-candidate-6a.md"
    f = "results/analyses/ANALYSIS-006/explained_exactness.cand6a.json"
    e = load(f)
    add("ANALYSIS-006 ancestor share real", d6, "0.093", f, e["r1_train_uncited"]["ancestor_share"])
    add("ANALYSIS-006 ancestor share cand6a", d6, "0.152", f, e["simulated"]["ancestor_share"])
    add("ANALYSIS-006 explained terms real", d6, 6130, f, e["r1_train_uncited"]["explained_terms"])
    add("ANALYSIS-006 explained terms cand6a", d6, 41376, f, e["simulated"]["explained_terms"])
    d2 = "docs/analyses/ANALYSIS-002-noise-structure-and-e0-contamination.md"
    f = "results/analyses/ANALYSIS-002/e0_by_hpoa_citation.txt"
    txt = {ln.split()[0]: ln.split() for ln in open(ROOT / f)}
    add("ANALYSIS-002 E0 cited n", d2, 2398, f, int(txt["cited"][1]))
    add("ANALYSIS-002 E0 cited MRR", d2, "0.562", f, float(txt["cited"][2]))
    add("ANALYSIS-002 E0 uncited n", d2, 1124, f, int(txt["not_cited"][1]))
    add("ANALYSIS-002 E0 uncited MRR", d2, "0.405", f, float(txt["not_cited"][2]))


def verdict(printed: str, value) -> str:
    try:
        p = Decimal(printed.lstrip("+"))
    except Exception:
        return "N/A"
    dec = -p.as_tuple().exponent
    unit = 10 ** (-dec)
    diff = abs(float(p) - float(value))
    if diff <= 0.5 * unit + 1e-9:
        return "MATCH"
    return "ROUND+-1" if diff <= 1.5 * unit + 1e-9 else "DIFF"


def main() -> None:
    for fn in (exp_000, exp_b001, exp_b002, exp_s3, exp_b003, exp_a, gate, literature, analyses):
        try:
            fn()
        except Exception as e:  # keep going so one broken lookup does not hide the rest
            add(f"ERROR in {fn.__name__}", "", "", "", repr(e))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / "number_checks.tsv"
    counts: dict[str, int] = {}
    with open(out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["check", "doc", "doc_value", "result_file", "file_value", "status"])
        for cid, doc, printed, file, value in CHECKS:
            st = "ERROR" if cid.startswith("ERROR") else verdict(printed, value)
            counts[st] = counts.get(st, 0) + 1
            w.writerow(
                [cid, doc, printed, file, value if isinstance(value, (int, str)) else f"{value:.6g}", st]
            )
    print(counts, "->", out)
    for cid, doc, printed, file, value in CHECKS:
        st = "ERROR" if cid.startswith("ERROR") else verdict(printed, value)
        if st not in ("MATCH",):
            print(st, cid, printed, value)


if __name__ == "__main__":
    main()
