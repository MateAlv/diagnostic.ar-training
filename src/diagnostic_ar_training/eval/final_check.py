"""The Phase 2 final check (ADR-0017 decision 5): E0 and every candidate on `p2-v1` vault plus `p2-fresh-v1`
vault, each vault loaded once, every system scored on the same cases.

E0 runs once per case: the candidates reuse its memoised logits and probabilities. Statistics are
`safe_eval.contrast`'s (paired publication-cluster bootstrap, 2,000 resamples, seed 0, 95% CI; harmed and
helped; top-1 and top-10 entries and exits), overall, on the safe report's subsets, and per component.
"""

from collections.abc import Mapping, Sequence

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import harness, safe_eval
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.safe.bundle import SafeRules
from diagnostic_ar_training.safe.system import SafeV1
from diagnostic_ar_training.systems import System

SPLITS = ("p2-v1", "p2-fresh-v1")
PART = "vault"
COHORT = "p2-v1+p2-fresh-v1-vault"
OUT_DIR = "final-check"
SAFE_VARIANTS = ("all", "sex+onset", "sex", "onset", "negation")


def run_id(exp: str) -> str:
    return f"results-{exp}-{OUT_DIR}"


def check_frozen(frozen: Mapping[str, Mapping]) -> dict[str, int]:
    """Vault sizes; refuses unless every split has a vault part and no case id is in two vaults."""
    seen: dict[str, str] = {}
    sizes = {}
    for split_id in SPLITS:
        ids = frozen[split_id].get("case_ids", {}).get(PART)
        if not ids:
            raise LineageError(f"{split_id} has no {PART} part")
        for case_id in ids:
            if case_id in seen:
                raise LineageError(f"case {case_id} is in both {seen[case_id]} and {split_id} vaults")
            seen[case_id] = split_id
        sizes[split_id] = len(ids)
    return sizes


def check_names(names: Sequence[str]) -> None:
    """System names become file names next to each other: unique, not E0's, and path-safe."""
    if len(set(names)) != len(names):
        raise ValueError(f"system names collide: {list(names)}")
    for name in names:
        if name == "E0" or not name or "/" in name or "__" in name:
            raise ValueError(f"{name!r} cannot name a system's output files")


def safe_systems(memo: safe_eval.Memo, rules: SafeRules) -> list[SafeV1]:
    return [SafeV1(memo, rules, safe_eval.VARIANTS[v]) for v in SAFE_VARIANTS]


def _fired(record: dict) -> bool:
    return bool(record.get("safe_contradicted") or record.get("safe_blocked") or record.get("ft_lowered"))


def cohort_report(
    records: Mapping[str, list[dict]], cases: Sequence[Case], groups: Mapping[str, str]
) -> dict:
    """Every system vs E0 on these cases (records in case order, E0 under "E0")."""
    e0 = records["E0"]
    subsets = {"gene_in_vocab": {r["case_id"] for r in e0 if r["gene_in_vocab"]}}
    subsets |= safe_eval.known_subsets(cases)
    out: dict = {
        "cases": len(cases),
        "publications": len({groups[c.case_id] for c in cases}),
        "subset_sizes": {k: len(v) for k, v in subsets.items()},
        "e0": harness.summarize(e0)["all"] if e0 else None,
        "systems": {},
    }
    for name, recs in records.items():
        if name == "E0":
            continue
        unfired = {r["case_id"] for r in recs if not _fired(r)}
        out["systems"][name] = {
            "summary": harness.summarize(recs)["all"] if recs else None,
            "vs_e0": safe_eval.contrast(e0, recs),
            "cases_where_the_system_changed_a_score": len(recs) - len(unfired),
            "rank_changes_where_it_changed_none": sum(
                a["rank"] != b["rank"] for a, b in zip(e0, recs, strict=True) if a["case_id"] in unfired
            ),
            "subsets": {
                k: safe_eval.contrast(safe_eval._subset(e0, v), safe_eval._subset(recs, v))
                for k, v in subsets.items()
            },
        }
    return out


def present_identity(
    memo: safe_eval.Memo, systems: Sequence[System], cases: Sequence[Case]
) -> dict[str, int]:
    """Per system, the cases whose present-only view differs from E0, bit for bit."""
    out = {}
    for system in systems:
        mismatches = 0
        for case in cases:
            want = memo.score(case).probs
            got = system.score(harness.apply_view(case, "present")).probs
            mismatches += (got is None) != (want is None) or (
                got is not None and not np.array_equal(got, want)
            )
        out[system.name] = mismatches
    return out


def evaluate(
    memo: safe_eval.Memo,
    systems: Sequence[System],
    by_split: Mapping[str, tuple[list[Case], dict[str, str]]],
) -> tuple[dict, dict[str, list[dict]]]:
    """(report, records by system name) over the concatenated vaults, with a report per component.

    `by_split` maps each split to its cases and their publication groups (prefixed by the split).
    """
    check_names([s.name for s in systems])
    cases = [c for cs, _ in by_split.values() for c in cs]
    groups = {k: v for _, g in by_split.values() for k, v in g.items()}
    if len({c.case_id for c in cases}) != len(cases):
        raise ValueError("a case id appears twice across the vaults")
    records = {"E0": harness.run(memo, cases, "all", groups)}
    for system in systems:
        records[system.name] = harness.run(system, cases, "all", groups)
    report = cohort_report(records, cases, groups)
    report["systems_order"] = [s.name for s in systems]
    report["identity"] = {"present_view_vs_e0_mismatches": present_identity(memo, systems, cases)}
    report["components"] = {}
    for split_id, (split_cases, split_groups) in by_split.items():
        keep = {c.case_id for c in split_cases}
        part = {name: safe_eval._subset(recs, keep) for name, recs in records.items()}
        report["components"][split_id] = cohort_report(part, split_cases, split_groups)
    return report, records


def table(report: dict) -> list[str]:
    """One line per system, overall and per component."""
    from diagnostic_ar_training.ft.evaluate import line

    lines = []
    scopes = [("all", report), *report["components"].items()]
    for name in report["systems_order"]:
        for scope, r in scopes:
            lines.append(line(f"{name} {scope}", r["systems"][name]["vs_e0"]))
    return lines
