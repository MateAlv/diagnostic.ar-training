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


def _tsv_rows(rel):
    with open(ROOT / rel, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t"))


def _ci(cid, doc, printed_ci, f, v):
    add(f"{cid} CI low", doc, printed_ci[0], f, v["ci95"][0])
    add(f"{cid} CI high", doc, printed_ci[1], f, v["ci95"][1])


def s3_builds():
    adr14 = "docs/decisions/0014-reranker-v11-and-s3-v2.md"
    adr15 = "docs/decisions/0015-onset-follow-up-s3-v3.md"
    for sid, doc, dev, test, sha in [
        ("s3-v2", adr14, 9872, 9696, "fb7d47f04d161aa3c01dbcec133717de52ee06c6a16709872a205f18ef65c58e"),
        ("s3-v3", adr15, 3106, 6974, "746ca7bca7efa24eb4e5497731a063a4d092dc8ced55b1f0ef0993a0e56164db"),
        ("s3-v3b", "docs/BITACORA.md", 4577, 10509, "61660f7a32572f4007c8bbdd8afe4d952cd6bf0e681833360198f2b6082c4925"),
    ]:
        f = f"data/splits/{sid}.json"
        d = load(f)
        add(f"{sid} dev cases", doc, dev, f, d["counts"]["dev"])
        add(f"{sid} test cases", doc, test, f, d["counts"]["test"])
        add(f"{sid} content sha256", doc, sha, f, d["content_sha256"])
    f = "data/s3/s3-v3b-eligible-genes.summary.json"
    d = load(f)
    add("s3-v3b eligible genes", "docs/BITACORA.md", 397, f, d["eligible_genes"])
    add("s3-v3b cases per gene", "docs/BITACORA.md", 38, f, d["cases_per_gene"])
    add("s3-v3b expected cases", "docs/BITACORA.md", 15086, f, d["expected_cases"])
    f = "data/s3/s3-v3-eligible-genes.summary.json"
    d = load(f)
    add("s3-v3 eligible genes", adr15, 120, f, d["eligible_genes"])
    add("s3-v3 expected cases", adr15, 10080, f, d["expected_cases"])
    f = "results/EXP-B-004/kb-weight-sums.json"
    sums = {r["kb"]: r for r in load(f)}
    for kb, off, below in [("kb-v6", 633, 14), ("kb-v7", 601, 11), ("kb-v8", 633, 14)]:
        add(f"ADR-0014 {kb} genes with weight sum != 1", adr14, off, f, sums[kb]["genes_sum_not_1"])
        add(f"ADR-0014 {kb} genes with weight sum < 0.99", adr14, below, f, sums[kb]["genes_sum_below"]["0.99"])
    add("ADR-0014 kb-v6 minimum weight sum", adr14, "0.5", f, sums["kb-v6"]["min_sum"])


def exp_b004():
    doc = "docs/experiments/EXP-B-004.md"
    f = "results/EXP-B-004/dev-search.tsv"
    rows = {(r["arm_id"]): r for r in _tsv_rows(f)}
    for arm, delta, lo, hi, harmed, helped, r1, r1lo, r1hi in [
        ("L1:propagated:k0.5:w0.5", "+0.0063", "+0.0051", "+0.0075", "0.049", "0.233", "-0.0020", "-0.0097", "+0.0044"),
        ("L1:gated:tau0.4:k0.5:w0.5", "+0.0065", "+0.0052", "+0.0078", "0.045", "0.237", "+0.0028", "+0.0006", "+0.0050"),
        ("L1:propagated:k0.8:w0.75", "+0.0132", "+0.0111", "+0.0154", "0.074", "0.331", "-0.0091", "-0.0300", "+0.0056"),
        ("L1:capped:cap2:k0.5:w2", "+0.0161", "+0.0133", "+0.0188", "0.092", "0.367", "-0.0125", "-0.0382", "+0.0057"),
        ("L1:llr:k0.5:w0.5", "+0.0079", "+0.0065", "+0.0093", "0.055", "0.253", "-0.0020", "-0.0097", "+0.0044"),
        ("L2:propagated:k0.5:w0.5:kb-v8", "+0.0064", "+0.0052", "+0.0076", "0.047", "0.236", "-0.0094", "-0.0241", "+0.0007"),
        ("L3:onset:w0.5", "+0.0117", "+0.0101", "+0.0133", "0.052", "0.300", "-0.0004", "-0.0086", "+0.0069"),
        ("L3:onset:w2", "+0.0172", "+0.0147", "+0.0197", "0.084", "0.339", "-0.0127", "-0.0228", "-0.0024"),
        ("L3:sex:w0.5", "+0.0064", "+0.0052", "+0.0076", "0.053", "0.241", "-0.0022", "-0.0098", "+0.0043"),
    ]:
        r = rows[arm]
        c = f"EXP-B-004 dev {arm}"
        add(f"{c} delta", doc, delta, f, float(r["delta_mrr"]))
        add(f"{c} CI low", doc, lo, f, float(r["ci_lo"]))
        add(f"{c} CI high", doc, hi, f, float(r["ci_hi"]))
        add(f"{c} harmed", doc, harmed, f, float(r["harmed"]))
        add(f"{c} helped", doc, helped, f, float(r["helped"]))
        add(f"{c} R1-dev delta", doc, r1, f, float(r["r1dev_delta"]))
        add(f"{c} R1-dev CI low", doc, r1lo, f, float(r["r1dev_ci_lo"]))
        add(f"{c} R1-dev CI high", doc, r1hi, f, float(r["r1dev_ci_hi"]))
    add("EXP-B-004 dev L1 arms logged", doc, 48, f, sum(1 for r in rows.values() if r["lever"] == "L1"))
    add("EXP-B-004 dev L2 arms logged", doc, 6, f, sum(1 for r in rows.values() if r["lever"] == "L2"))
    add("EXP-B-004 dev L3 arms logged", doc, 12, f, sum(1 for r in rows.values() if r["lever"] == "L3"))
    add("EXP-B-004 dev n per arm", doc, 9750, f, int(rows["L1:propagated:k0.5:w0.5"]["n"]))

    f = "results/EXP-B-004/sealed-analysis.json"
    d = load(f)
    add("EXP-B-004 sealed n", doc, 9565, f, d["n"])
    for key, delta, lo, hi, harmed, helped, mrr, vf, flo, fhi in [
        ("F", "+0.0066", "+0.0054", "+0.0079", "0.0506", "0.2235", "0.3562", None, None, None),
        ("rr-v1 formula on kb-v6", "+0.0077", "+0.0063", "+0.0092", "0.0576", "0.2432", "0.3572", "+0.0011", "+0.0003", "+0.0018"),
        ("F on kb-v7", "+0.0070", "+0.0057", "+0.0083", "0.0504", "0.2277", "0.3565", "+0.0003", "+0.0001", "+0.0006"),
        ("F + onset 0.5", "+0.0124", "+0.0107", "+0.0140", "0.0499", "0.2942", "0.3619", "+0.0057", "+0.0045", "+0.0069"),
        ("F + sex 0.5", "+0.0070", "+0.0057", "+0.0083", "0.0525", "0.2311", "0.3565", "+0.0003", "+0.0000", "+0.0007"),
        ("F + age_mean 0.5", "+0.0073", "+0.0059", "+0.0088", "0.0631", "0.2477", "0.3568", "+0.0007", "-0.0001", "+0.0014"),
        ("frontier <=7.5% (propagated k0.8 w0.75)", "+0.0143", "+0.0123", "+0.0164", "0.0741", "0.3255", "0.3639", "+0.0077", "+0.0062", "+0.0093"),
        ("frontier <=10% (capped C2 w2)", "+0.0165", "+0.0138", "+0.0190", "0.0944", "0.3613", "0.3660", "+0.0098", "+0.0076", "+0.0120"),
    ]:
        s = d[key]
        e = s["vs_E0+answers"]
        c = f"EXP-B-004 sealed {key}"
        add(f"{c} delta", doc, delta, f, e["delta"])
        add(f"{c} CI low", doc, lo, f, e["ci95"][0])
        add(f"{c} CI high", doc, hi, f, e["ci95"][1])
        add(f"{c} harmed", doc, harmed, f, e["harmed"])
        add(f"{c} helped", doc, helped, f, e["helped"])
        add(f"{c} MRR final", doc, mrr, f, s["mrr_final"])
        if vf is not None:
            v = s["vs_F"]
            add(f"{c} delta vs F", doc, vf, f, v["delta"])
            add(f"{c} vs F CI low", doc, flo, f, v["ci95"][0])
            add(f"{c} vs F CI high", doc, fhi, f, v["ci95"][1])
    sizes = d["subset_sizes"]
    for k, n in [("lit_onset", 509), ("lit_onset_src_hpoa", 349), ("lit_onset_src_orphanet", 26),
                 ("lit_onset_src_orphanet_exact_alignment", 86), ("lit_onset_src_none", 48),
                 ("lit_onset_age_known", 391)]:
        add(f"EXP-B-004 sealed subset size {k}", doc, n, f, sizes[k])
    h3 = d["H3"]["F + onset 0.5"]
    add("EXP-B-004 sealed onset lit_onset delta", doc, "+0.0064", f, h3["lit_onset"]["vs_E0+answers"]["delta"])
    add("EXP-B-004 sealed onset lit_onset harmed", doc, "0.081", f, h3["lit_onset"]["vs_E0+answers"]["harmed"])
    add("EXP-B-004 sealed onset lit_onset vs F", doc, "+0.0021", f, h3["lit_onset"]["vs_F"]["delta"])
    add("EXP-B-004 sealed onset lit_onset vs F CI low", doc, "-0.0027", f, h3["lit_onset"]["vs_F"]["ci95"][0])
    add("EXP-B-004 sealed onset lit_onset vs F CI high", doc, "+0.0063", f, h3["lit_onset"]["vs_F"]["ci95"][1])
    add("EXP-B-004 sealed onset hpoa delta", doc, "+0.0085", f, h3["lit_onset_src_hpoa"]["vs_E0+answers"]["delta"])


def exp_q001():
    doc = "docs/experiments/EXP-Q-001.md"
    f = "results/EXP-Q-001/dev-search.tsv"
    rows = _tsv_rows(f)

    def find(strategy, noise):
        return next(r for r in rows if r["strategy"] == strategy and float(r["noise"]) == noise)

    for strat, noise, delta, lo, hi, harmed, rrh in [
        ("Q0", 0, "+0.0275", "+0.0250", "+0.0298", "0.081", "0.049"),
        ("Q2", 0, "+0.0328", "+0.0300", "+0.0355", "0.085", "0.051"),
        ("Q2b-lam0.3", 0, "+0.0337", "+0.0308", "+0.0365", "0.086", "0.049"),
        ("Q2b-lam0.6", 0, "+0.0339", "+0.0310", "+0.0368", "0.084", "0.048"),
        ("Q1", 0, "+0.0332", "+0.0302", "+0.0361", "0.077", "0.059"),
        ("Q0", 0.05, "+0.0148", "+0.0117", "+0.0176", "0.166", "0.049"),
        ("Q2b-lam0.6", 0.05, "+0.0203", "+0.0170", "+0.0236", "0.168", "0.049"),
    ]:
        r = find(strat, noise)
        c = f"EXP-Q-001 dev {strat} noise {noise}"
        add(f"{c} primary", doc, delta, f, float(r["delta_primary"]))
        add(f"{c} CI low", doc, lo, f, float(r["ci_lo"]))
        add(f"{c} CI high", doc, hi, f, float(r["ci_hi"]))
        add(f"{c} harmed", doc, harmed, f, float(r["harmed_primary"]))
        add(f"{c} re-ranker harmed", doc, rrh, f, float(r["reranker_harmed"]))
    add("EXP-Q-001 dev cases", doc, 9750, f, int(find("Q0", 0)["cases"]))

    f = "results/EXP-Q-001/sealed-analysis.json"
    d = load(f)
    add("EXP-Q-001 sealed n", doc, 9565, f, d["n"])
    for key, delta, lo, hi, harmed, helped, qe, rre, rrh in [
        ("Q2b", "+0.0330", "+0.0301", "+0.0360", "0.0811", "0.3803", "+0.0263", "+0.0067", "0.0477"),
        ("Q0", "+0.0281", "+0.0255", "+0.0308", "0.0825", "0.3606", "+0.0215", "+0.0066", "0.0506"),
        ("Q1", "+0.0312", "+0.0284", "+0.0340", "0.0792", "0.3800", "+0.0256", "+0.0056", "0.0558"),
        ("Q2b-noise", "+0.0177", "+0.0143", "+0.0210", "0.1603", "0.3570", "+0.0118", "+0.0059", "0.0490"),
        ("Q0-noise", "+0.0153", "+0.0120", "+0.0185", "0.1612", "0.3428", "+0.0089", "+0.0063", "0.0528"),
    ]:
        v = d[key]
        c = f"EXP-Q-001 sealed {key}"
        add(f"{c} primary", doc, delta, f, v["primary"]["delta"])
        add(f"{c} CI low", doc, lo, f, v["primary"]["ci95"][0])
        add(f"{c} CI high", doc, hi, f, v["primary"]["ci95"][1])
        add(f"{c} harmed", doc, harmed, f, v["primary"]["harmed"])
        add(f"{c} helped", doc, helped, f, v["primary"]["helped"])
        add(f"{c} questioner effect", doc, qe, f, v["questioner_effect"]["delta"])
        add(f"{c} re-ranker effect", doc, rre, f, v["reranker_effect"]["delta"])
        add(f"{c} re-ranker harmed", doc, rrh, f, v["reranker_effect"]["harmed"])
    p1 = d["P1"]["paired_Q2b_minus_Q0"]
    add("EXP-Q-001 P1 delta", doc, "+0.0049", f, p1["delta"])
    add("EXP-Q-001 P1 CI low", doc, "+0.0027", f, p1["ci95"][0])
    add("EXP-Q-001 P1 CI high", doc, "+0.0069", f, p1["ci95"][1])
    add("EXP-Q-001 P1 harmed", doc, "0.1476", f, p1["harmed"])
    add("EXP-Q-001 P1 helped", doc, "0.2027", f, p1["helped"])
    add("EXP-Q-001 P1 re-ranker harmed under Q2b", doc, "0.0477", f, d["P1"]["reranker_effect_harmed_Q2b"])
    s1 = d["S1"]["paired_Q2b_minus_Q1"]
    add("EXP-Q-001 S1 delta", doc, "+0.0017", f, s1["delta"])
    add("EXP-Q-001 S1 CI low", doc, "-0.0006", f, s1["ci95"][0])
    add("EXP-Q-001 S1 CI high", doc, "+0.0043", f, s1["ci95"][1])
    s2 = d["S2"]["paired_Q2b_minus_Q0_noise0.05"]
    add("EXP-Q-001 S2 delta", doc, "+0.0024", f, s2["delta"])
    add("EXP-Q-001 S2 CI low", doc, "-0.0002", f, s2["ci95"][0])
    add("EXP-Q-001 S2 CI high", doc, "+0.0050", f, s2["ci95"][1])


def exp_b005():
    doc = "docs/experiments/EXP-B-005.md"
    f = "results/EXP-B-005/dev-analysis.json"
    d = load(f)
    add("EXP-B-005 dev cases interviewed", doc, 4562, f, d["cases"])
    add("EXP-B-005 dev literature cases", doc, 2934, f, d["mask_sizes"]["lit"])
    for arm, delta, lo, hi, harmed, r1, r1lo, r1hi in [
        ("F+onset0.25", "+0.0021", "+0.0006", "+0.0036", "4.16", "-0.0006", "-0.0086", "+0.0060"),
        ("F+onset0.5", "+0.0035", "+0.0011", "+0.0058", "6.00", "-0.0004", "-0.0086", "+0.0069"),
        ("F+onset1", "+0.0038", "+0.0000", "+0.0076", "7.81", "-0.0052", "-0.0133", "+0.0024"),
    ]:
        a = d["arms"][arm]
        v, e = a["vs_F"]["lit"], a["vs_e0"]["lit"]
        c = f"EXP-B-005 dev {arm}"
        add(f"{c} delta vs F", doc, delta, f, v["delta"])
        add(f"{c} CI low", doc, lo, f, v["ci95"][0])
        add(f"{c} CI high", doc, hi, f, v["ci95"][1])
        add(f"{c} harmed % vs E0+answers", doc, harmed, f, e["harmed"] * 100)
        add(f"{c} R1-dev delta", doc, r1, f, a["r1dev"]["delta"])
        add(f"{c} R1-dev CI low", doc, r1lo, f, a["r1dev"]["ci95"][0])
        add(f"{c} R1-dev CI high", doc, r1hi, f, a["r1dev"]["ci95"][1])
    ref = d["reference"]["vs_e0"]["lit"]
    add("EXP-B-005 dev F vs E0+answers", doc, "+0.0089", f, ref["delta"])
    add("EXP-B-005 dev F vs E0+answers CI low", doc, "+0.0067", f, ref["ci95"][0])
    add("EXP-B-005 dev F vs E0+answers CI high", doc, "+0.0115", f, ref["ci95"][1])
    add("EXP-B-005 dev F harmed %", doc, "3.03", f, ref["harmed"] * 100)
    for arm, al, kn, knh in [("F+onset0.25", "+0.0025", "+0.0042", "5.84"), ("F+onset0.5", "+0.0042", "+0.0069", "8.28"),
                             ("F+onset1", "+0.0053", "+0.0088", "11.40")]:
        a = d["arms"][arm]
        add(f"EXP-B-005 dev {arm} all-cases delta vs F", doc, al, f, a["vs_F"]["all"]["delta"])
        add(f"EXP-B-005 dev {arm} known-onset delta vs F", doc, kn, f, a["vs_F"]["known"]["delta"])
        add(f"EXP-B-005 dev {arm} known-onset harmed %", doc, knh, f, a["vs_e0"]["known"]["harmed"] * 100)

    f = "results/EXP-B-005/sealed-analysis.json"
    d = load(f)
    add("EXP-B-005 sealed cases interviewed", doc, 10458, f, d["cases"])
    p1 = d["P1"]["F+onset0.25"]
    add("EXP-B-005 sealed P1 n", doc, 6745, f, p1["n"])
    add("EXP-B-005 sealed P1 delta", doc, "+0.0023", f, p1["delta"])
    add("EXP-B-005 sealed P1 CI low", doc, "+0.0013", f, p1["ci95"][0])
    add("EXP-B-005 sealed P1 CI high", doc, "+0.0034", f, p1["ci95"][1])
    add("EXP-B-005 sealed P1 harmed %", doc, "4.63", f, p1["harmed"] * 100)
    arm = d["arms"]["F+onset0.25"]
    add("EXP-B-005 sealed P1 helped %", doc, "28.35", f, arm["vs_e0"]["lit"]["helped"] * 100)
    ref = d["reference"]["vs_e0"]["lit"]
    add("EXP-B-005 sealed F vs E0+answers", doc, "+0.0076", f, ref["delta"])
    add("EXP-B-005 sealed F vs E0+answers CI low", doc, "+0.0060", f, ref["ci95"][0])
    add("EXP-B-005 sealed F vs E0+answers CI high", doc, "+0.0092", f, ref["ci95"][1])
    add("EXP-B-005 sealed F harmed %", doc, "3.45", f, ref["harmed"] * 100)
    for key, n, delta, lo, hi, harmed in [
        ("all", 10458, "+0.0027", "+0.0019", "+0.0036", "4.75"),
        ("known", 6200, "+0.0046", "+0.0031", "+0.0061", "5.40"),
        ("lit_known", 3993, "+0.0039", "+0.0021", "+0.0056", "5.58"),
        ("lit_unknown", 2752, "+0.0000", None, None, "3.23"),
        ("lit_src_hpoa", 4802, "+0.0025", "+0.0013", "+0.0038", "4.56"),
        ("lit_src_orphanet", 355, "+0.0004", "-0.0033", "+0.0036", "3.94"),
        ("lit_src_orphanet_exact_alignment", 978, "+0.0023", "-0.0001", "+0.0046", "5.42"),
        ("lit_src_none", 610, "+0.0022", "-0.0012", "+0.0062", "4.26"),
    ]:
        v, e = arm["vs_F"][key], arm["vs_e0"][key]
        c = f"EXP-B-005 sealed {key}"
        add(f"{c} n", doc, n, f, v["n"])
        add(f"{c} delta vs F", doc, delta, f, v["delta"])
        if lo is not None:
            add(f"{c} CI low", doc, lo, f, v["ci95"][0])
            add(f"{c} CI high", doc, hi, f, v["ci95"][1])
        add(f"{c} harmed %", doc, harmed, f, e["harmed"] * 100)


def corrections():
    adr = "docs/decisions/0012-data-quality-gate.md"
    half_a = "results/realism/v0.3-baseline.json"
    full = "results/realism/v0.3-full-baseline.json"
    add(
        "ADR-0012 correction: V03 half A terms per case (8.42)",
        adr,
        "8.42",
        half_a,
        load(half_a)["g2c_terms_per_case"]["present"]["sim"]["mean"],
    )
    add(
        "ADR-0012 correction: V03-full terms per case (10.21)",
        adr,
        "10.21",
        full,
        load(full)["g2c_terms_per_case"]["present"]["sim"]["mean"],
    )
    pct = load(full)["g2c_terms_per_case"]["present"]
    add("ADR-0012 correction: V03-full p10", adr, "4", full, pct["sim"]["percentiles"]["10"])
    add("ADR-0012 correction: V03-full p90", adr, "18", full, pct["sim"]["percentiles"]["90"])
    add("ADR-0012 correction: R1-train p10", adr, "2", full, pct["r1_train"]["percentiles"]["10"])
    add("ADR-0012 correction: R1-train p90", adr, "17", full, pct["r1_train"]["percentiles"]["90"])


def exp_b006_v001():
    doc = "docs/evidence/TABLES.md"
    q = "results/EXP-Q-001/sealed-analysis.json"
    s1 = load(q)["S1"]["paired_Q2b_minus_Q1"]
    for k, p, val in [("delta", "+0.0017", s1["delta"]), ("CI low", "-0.0006", s1["ci95"][0]), ("CI high", "+0.0043", s1["ci95"][1])]:
        add(f"EXP-Q-001 S1 Q2b-Q1 {k}", doc, p, q, val)
    doc = "docs/experiments/EXP-B-006.md"
    f = "results/EXP-B-006/r1-v1-test__release-check__report.json"
    d = load(f)
    g = d["given"]
    for name, key, rows in [
        ("candidate vs E0", "candidate_vs_e0", ("-0.0028", "-0.0078", "+0.0013", "0.113", "0.132")),
        ("candidate - rr-v1", "candidate_vs_rr_v1", ("-0.0003", "-0.0019", "+0.0008", "0.053", "0.100")),
        ("rr-v1 vs E0", "rr_v1_vs_e0", ("-0.0025", "-0.0070", "+0.0013", "0.090", "0.063")),
    ]:
        v = g[key]
        for lbl, p, val in zip(("delta", "CI low", "CI high", "harmed", "helped"), rows, (v["delta"], v["ci95"][0], v["ci95"][1], v["harmed"], v["helped"])):
            add(f"EXP-B-006 R1-test {name} {lbl}", doc, p, f, val)
    v = d["descriptive"]["with_usable_onset"]["candidate_vs_rr_v1"]
    add("EXP-B-006 R1-test usable-onset delta", doc, "-0.0006", f, v["delta"])
    add("EXP-B-006 R1-test cases", doc, 2548, f, d["cases"])
    add("EXP-B-006 R1-test usable onset", doc, 1310, f, d["cases_with_usable_onset"])
    doc = "docs/experiments/EXP-V-001.md"
    f = "results/EXP-V-001/r1-v1-vault__final-report__report.json"
    d = load(f)
    add("EXP-V-001 patients", doc, 1771, f, d["cases"])
    add("EXP-V-001 publications", doc, 352, f, d["publications"])
    add("EXP-V-001 usable onset", doc, 969, f, d["cases_with_usable_onset"])
    v = d["views"]["given"]
    for sysn, p in [("E0", "0.4136"), ("rerank-v1.0.0", "0.4114"), ("rerank-v1.1.0", "0.4106")]:
        add(f"EXP-V-001 {sysn} MRR", doc, p, f, v["systems"][sysn]["mrr"])
    for name, key, rows in [
        ("v1.1 vs E0", "v1.1_vs_E0", ("-0.0031", "-0.0055", "-0.0005")),
        ("v1.0 vs E0", "v1.0_vs_E0", ("-0.0022", "-0.0046", "+0.0002")),
        ("v1.1 - v1.0", "v1.1_minus_v1.0", ("-0.0008", "-0.0023", "+0.0004")),
    ]:
        c = v["contrasts"][key]["mrr"]
        for lbl, p, val in zip(("delta", "CI low", "CI high"), rows, (c["delta"], c["ci95"][0], c["ci95"][1])):
            add(f"EXP-V-001 {name} {lbl}", doc, p, f, val)
    c = d["onset_subset"]["with_usable_onset"]["contrasts"]["v1.1_minus_v1.0"]["mrr"]
    add("EXP-V-001 usable-onset v1.1-v1.0 delta", doc, "-0.0015", f, c["delta"])


def verdict(printed: str, value) -> str:
    if printed == str(value) and len(printed) == 64:
        return "MATCH"
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
    for fn in (
        exp_000,
        exp_b001,
        exp_b002,
        exp_s3,
        exp_b003,
        exp_a,
        gate,
        literature,
        analyses,
        s3_builds,
        exp_b004,
        exp_q001,
        exp_b005,
        exp_b006_v001,
        corrections,
    ):
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
