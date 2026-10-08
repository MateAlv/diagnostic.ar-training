"""safe-v1 vs E0 on one cohort: overall, per rule, and on the subsets where each input is known.

One E0 pass per case serves every variant (`Memo`). Statistics are the harness's: `harness.compare` (paired
publication-cluster bootstrap, 2,000 resamples, seed 0, 95% CI; harmed and helped shares), plus counts and
top-1/top-10 entries and exits.

The sealed read (`dxt safe confirm`) goes through `preflight` first: every refusal comes before any data is
loaded, any artifact fetched or the ledger touched.
"""

from collections.abc import Iterable, Sequence

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.eval import harness
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.gitinfo import code_state
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.safe.bundle import RULES, SafeRules
from diagnostic_ar_training.safe.system import SafeV1
from diagnostic_ar_training.systems import Scored, System

EXPERIMENT = "EXP-P-001"
FREE_PARTS = ("train", "dev")
VARIANTS: dict[str, tuple[str, ...]] = {
    "sex": ("sex",),
    "onset": ("onset",),
    "negation": ("negation",),
    "sex+onset": ("sex", "onset"),
    "all": RULES,
}
TOP_KS = (1, 10)
# Sealed reads this command may make (ADR-0017): the confirmation read of one candidate, and the final check,
# which reads both vaults together, once.
SEALED_READS: dict[str, tuple[str, ...]] = {
    "test": ("p2-v1",),
    "vault": ("p2-v1", "p2-fresh-v1"),
}


class Memo:
    """E0 scored once per case (present terms only); every variant reuses it."""

    def __init__(self, base: System) -> None:
        self.base = base
        self.name = base.name
        self.genes = base.genes
        self._cache: dict[tuple[str, tuple[str, ...]], Scored] = {}

    def lineage_inputs(self) -> list[dict]:
        return self.base.lineage_inputs()

    def score(self, case: Case) -> Scored:
        key = (case.case_id, case.present)
        if key not in self._cache:
            self._cache[key] = self.base.score(case.model_copy(update={"excluded": ()}))
        return self._cache[key]


def known_subsets(cases: Sequence[Case]) -> dict[str, set[str]]:
    return {
        "sex_known": {c.case_id for c in cases if c.sex != Sex.UNKNOWN},
        "age_known": {c.case_id for c in cases if c.age_years is not None},
        "onset_known": {c.case_id for c in cases if c.onset_years is not None},
        "excluded_known": {c.case_id for c in cases if c.excluded},
    }


def top_moves(base: list[dict], new: list[dict], ks: Iterable[int] = TOP_KS) -> dict:
    a = np.array([r["rank"] for r in base], dtype=float)
    b = np.array([r["rank"] for r in new], dtype=float)
    out = {}
    for k in ks:
        out[f"top{k}_entered"] = int(((b <= k) & (a > k)).sum())
        out[f"top{k}_left"] = int(((b > k) & (a <= k)).sum())
    return out


def contrast(base: list[dict], new: list[dict]) -> dict:
    """Δ MRR new − base with its CI, harmed/helped shares and counts, top-1/top-10 moves."""
    if not base:
        return {"n": 0}
    if [r["case_id"] for r in base] != [r["case_id"] for r in new]:
        raise ValueError("records must cover the same cases in the same order")
    a = np.array([r["rank"] for r in base], dtype=float)
    b = np.array([r["rank"] for r in new], dtype=float)
    return {
        **harness.compare(base, new),
        "helped_n": int((b < a).sum()),
        "harmed_n": int((b > a).sum()),
        **top_moves(base, new),
    }


def _subset(records: list[dict], keep: set[str]) -> list[dict]:
    return [r for r in records if r["case_id"] in keep]


def evaluate(
    base: System, rules: SafeRules, cases: Sequence[Case], groups: dict[str, str] | None
) -> tuple[dict, dict[str, list[dict]]]:
    """(report, records by system name). E0 is scored on the present terms; each variant on the full case."""
    memo = base if isinstance(base, Memo) else Memo(base)
    records = {"E0": harness.run(memo, list(cases), "all", groups)}
    systems = {label: SafeV1(memo, rules, active) for label, active in VARIANTS.items()}
    for system in systems.values():
        records[system.name] = harness.run(system, list(cases), "all", groups)
    subsets = {"gene_in_vocab": {r["case_id"] for r in records["E0"] if r["gene_in_vocab"]}}
    subsets |= known_subsets(cases)
    e0 = records["E0"]
    full = systems["all"]
    present_mismatches = 0
    for case in cases:
        e0_probs = memo.score(case).probs
        got = full.score(harness.apply_view(case, "present")).probs
        if (got is None) != (e0_probs is None) or (got is not None and not np.array_equal(got, e0_probs)):
            present_mismatches += 1
    report: dict = {
        "cases": len(cases),
        "publications": len({groups[c.case_id] for c in cases}) if groups else None,
        "subset_sizes": {k: len(v) for k, v in subsets.items()},
        "e0": harness.summarize(e0)["all"],
        "identity": {"present_view_all_rules_vs_e0_mismatches": present_mismatches},
        "variants": {},
    }
    for label, system in systems.items():
        recs = records[system.name]
        fired = [r for r in recs if r.get("safe_contradicted") or r.get("safe_blocked")]
        unfired = {r["case_id"] for r in recs} - {r["case_id"] for r in fired}
        report["variants"][label] = {
            "system": system.name,
            "rules": list(system.active),
            "summary": harness.summarize(recs)["all"],
            "vs_e0": contrast(e0, recs),
            "cases_where_a_rule_fired": len(fired),
            "rank_changes_where_no_rule_fired": sum(
                a["rank"] != b["rank"] for a, b in zip(e0, recs, strict=True) if a["case_id"] in unfired
            ),
            "subsets": {
                name: contrast(_subset(e0, keep), _subset(recs, keep)) for name, keep in subsets.items()
            },
        }
    return report, records


def table(report: dict) -> list[str]:
    """One line per variant and subset, for the terminal and the log."""
    lines = []
    for v in report["variants"].values():
        for scope, d in [("all", v["vs_e0"]), *v["subsets"].items()]:
            if not d.get("n"):
                continue
            lines.append(
                f"{v['system']:24} {scope:15} n {d['n']:5d} dMRR {d['delta']:+.5f} "
                f"[{d['ci95'][0]:+.5f}, {d['ci95'][1]:+.5f}] helped {d['helped_n']:4d} ({d['helped']:.4f}) "
                f"harmed {d['harmed_n']:3d} ({d['harmed']:.4f}) top1 +{d['top1_entered']}/-{d['top1_left']} "
                f"top10 +{d['top10_entered']}/-{d['top10_left']}"
            )
    return lines


def check_free_part(split_id: str, part: str) -> None:
    if part not in FREE_PARTS:
        raise ValueError(
            f"`dxt safe eval` reads free parts only ({', '.join(FREE_PARTS)}); {part!r} is sealed"
        )


def check_request(exp: str, split_ids: Sequence[str], part: str) -> None:
    """A sealed read names a known experiment id and exactly the splits its part requires."""
    if not ledger.EXP_ID.match(exp):
        raise ValueError(f"{exp!r} is not an experiment id")
    if part not in SEALED_READS:
        raise ValueError(f"part must be one of {sorted(SEALED_READS)} (dev and train go through `safe eval`)")
    if sorted(split_ids) != sorted(SEALED_READS[part]) or len(set(split_ids)) != len(split_ids):
        raise ValueError(
            f"a {part} read covers exactly the splits {list(SEALED_READS[part])}, got {split_ids}"
        )


def preflight(exp: str, split_ids: Sequence[str], part: str, reason: str) -> None:
    """Every refusal of a sealed read, in this order, before anything is loaded or ledgered.

    Raises ValueError for a malformed request and LineageError for a rule of the protocol.
    """
    check_request(exp, split_ids, part)
    for split_id in split_ids:
        ledger.require_sealed_read_env(split_id, part, exp)
    registration = ledger.EXPERIMENTS_DIR / f"{exp}.md"
    if not ledger.is_preregistered(registration):
        raise LineageError(f"docs/experiments/{exp}.md must be committed, unmodified, before the read")
    if code_state().dirty:
        raise LineageError("uncommitted changes: a sealed read must be reproducible from a SHA")
    if not reason.strip():
        raise LineageError("a reason is required for a sealed read")
    if part == "vault":
        opened = [s for s in split_ids if ledger.entries(s, "vault")]
        if opened:
            raise LineageError(f"vault already opened for {opened} (see docs/TEST_LEDGER.md): it opens once")
