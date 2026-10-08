"""ltr-v1 vs E0 on one cohort: the selected model and its ablation, overall and on subsets.

Statistics are safe_eval's (`contrast`: paired publication-cluster bootstrap, 2,000 resamples, seed 0,
95% CI; harmed and helped shares and counts; top-1 and top-10 entries and exits). The sealed read
(`dxt ltr confirm`) goes through `safe_eval.preflight`, so its refusals come in the same order as
`dxt safe confirm`'s, before any data is loaded, any artifact fetched or the ledger touched.
"""

from collections.abc import Mapping, Sequence

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.eval.safe_eval import Memo, contrast, known_subsets
from diagnostic_ar_training.systems import System


def subset(records: list[dict], keep: set[str]) -> list[dict]:
    return [r for r in records if r["case_id"] in keep]


def post_e0_cases(cases: Sequence[Case], groups: Mapping[str, str]) -> set[str]:
    """Cases whose publication group is post-E0 (ADR-0017 §2): no PMID in phenopacket-store 0.1.25 and none
    cited in HPO 2025-11-24."""
    from diagnostic_ar_training import splits

    release, cited = splits._e0_seen()
    status = {
        g: splits.group_status(p, release, cited) for g, p in splits.group_pmids(cases, dict(groups)).items()
    }
    return {c.case_id for c in cases if status[groups[c.case_id]] == splits.POST_E0}


def evaluate(
    base: System,
    systems: Mapping[str, System],
    cases: Sequence[Case],
    groups: Mapping[str, str] | None,
    extra_subsets: Mapping[str, set[str]] | None = None,
) -> tuple[dict, dict[str, list[dict]]]:
    """(report, records by system name). E0 is scored on the present terms; each system on the full case.

    `systems` maps a role ("ltr", "ablation") to a System; with both, the report also has ltr vs ablation, the
    part the new inputs add.
    """
    memo = base if isinstance(base, Memo) else Memo(base)
    groups = dict(groups or {})
    records = {"E0": harness.run(memo, list(cases), "all", groups)}
    for system in systems.values():
        records[system.name] = harness.run(system, list(cases), "all", groups)
    subsets = {"gene_in_vocab": {r["case_id"] for r in records["E0"] if r["gene_in_vocab"]}}
    subsets |= known_subsets(cases)
    subsets |= dict(extra_subsets or {})
    e0 = records["E0"]
    report: dict = {
        "cases": len(cases),
        "publications": len({groups[c.case_id] for c in cases}) if groups else None,
        "subset_sizes": {k: len(v) for k, v in subsets.items()},
        "e0": harness.summarize(e0)["all"],
        "systems": {},
    }
    for role, system in systems.items():
        recs = records[system.name]
        report["systems"][role] = {
            "system": system.name,
            "summary": harness.summarize(recs)["all"],
            "vs_e0": contrast(e0, recs),
            "cases_changed": sum(bool(r.get("ltr_changed")) for r in recs),
            "subsets": {
                name: contrast(subset(e0, keep), subset(recs, keep)) for name, keep in subsets.items()
            },
        }
    if {"ltr", "ablation"} <= set(systems):
        full, abl = records[systems["ltr"].name], records[systems["ablation"].name]
        report["ltr_vs_ablation"] = {
            "all": contrast(abl, full),
            "subsets": {
                name: contrast(subset(abl, keep), subset(full, keep)) for name, keep in subsets.items()
            },
        }
    return report, records


def line(label: str, d: dict) -> str:
    if not d.get("n"):
        return f"{label:40} n 0"
    return (
        f"{label:40} n {d['n']:5d} dMRR {d['delta']:+.5f} [{d['ci95'][0]:+.5f}, {d['ci95'][1]:+.5f}] "
        f"helped {d['helped_n']:4d} ({d['helped']:.4f}) harmed {d['harmed_n']:4d} ({d['harmed']:.4f}) "
        f"top1 +{d['top1_entered']}/-{d['top1_left']} top10 +{d['top10_entered']}/-{d['top10_left']}"
    )


def table(report: dict) -> list[str]:
    lines = []
    for role, v in report["systems"].items():
        lines.append(line(f"{v['system']} ({role}) all", v["vs_e0"]))
        lines += [line(f"{v['system']} ({role}) {k}", d) for k, d in v["subsets"].items()]
    if "ltr_vs_ablation" in report:
        lines.append(line("ltr vs ablation, all", report["ltr_vs_ablation"]["all"]))
        lines += [line(f"ltr vs ablation, {k}", d) for k, d in report["ltr_vs_ablation"]["subsets"].items()]
    return lines
