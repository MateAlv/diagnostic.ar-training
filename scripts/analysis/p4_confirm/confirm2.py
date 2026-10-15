r"""P4: the second CONFIRM read (fold 4), of the final model F3 (P4-CONFIRM, ADR-0020 decision 3).

Mateo runs it once, in his own terminal, after the protocol is committed:
    cd /home/mate/FIUBA/trabajo-profesional/diagnostic.ar-training && \
      systemd-run --user --scope -q -p MemoryMax=8G -p MemorySwapMax=0 nice -n 10 \
      env DXT_P3_CONFIRM=1 PYTHONPATH=src .venv/bin/python scripts/analysis/p4_confirm/confirm2.py \
      --reason "..."

Every refusal comes before any patient is loaded or the ledger touched: a reason, no earlier output,
DXT_P3_CONFIRM=1, docs/analyses/P4-CONFIRM.md committed unchanged, a clean tree, exactly one row already in
results/P3/CONFIRM_LEDGER.md (the first CONFIRM read: this second read happens once), and the frozen F3
(network `R5x-f4-ef2f309462` trained on exactly folds 0-3, the add-on `p3-addon-v1-all` on `p3-addon-kb-v1`,
the sex list `sex-kb-v3`, every sha256 as frozen). The network and E0 are loaded before the fold opens. Then
`addon.confirm_patients` opens fold 4 once (DXT_P3_CONFIRM=1, a second ledger row).

On the same patients (the network and E0 get the present terms only, the add-on and the rule every input):
- E0; F2 the network; F1 network + add-on; F3 F1 + the hard sex rule (`v4.sexrule`, `sex-kb-v3`);
- F3 vs E0 (primary), F3 vs F1 (the sex rule), F1 vs F2 (the add-on), F2 vs E0; strata uncited, uncited
  in-vocabulary, cited, all; capped and plain MRR, top-1 and top-10, both CIs (`v4.report`), helped / harmed;
- the doctor view: patients of known sex whose F2, F1 or F3 top 1 / 5 / 10 / 50 shows a gene impossible for
  their sex (`sexrule.shown`), and the patients whose true gene the list makes impossible;
- the gate fields: `pass_primary` (F3 vs E0, uncited, capped: 95% CI lower bound > 0), `sex_rule_harmed`
  (patients F3 ranks below F1) and `addon_helped_minus_harmed` (F1 vs F2, all patients).
Writes results/P4/confirm2/confirm2.json and the ranks under results/P4/confirm2/ranks/ (E0 and F3 first).

`--dry-run SCRATCH_DIR` runs the same code on fold 3 (`patients.load_addon`; in-sample for this network, so
its numbers mean nothing) without the gate, the ledger, the clean-tree and the protocol checks, and writes
under SCRATCH_DIR.
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from diagnostic_ar_training import DOCS_DIR, RESULTS_DIR
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.sim4 import folds
from diagnostic_ar_training.v4 import addon, patients, report, sexrule

sys.path.insert(0, str(Path(__file__).parents[1] / "p3_addon"))
from confirm import KB, NETWORK, knowledge_of, network_scorer, show  # noqa: E402
from vault import checkpoint_sha, code_state, e0_scorer, size_facts  # noqa: E402

F1_BUNDLE = "p3-addon-v1-all"
SEX_KB = "sex-kb-v3"
FROZEN_SHA256 = {
    NETWORK: "22edfd7ea56510d1210111797215a9a54c22d829979ef05b4e3cc85a758004da",
    F1_BUNDLE: "31299383a7dce279acdfae37248db8e7e04c62225fd892080c39758276a093b6",
    KB: "089ccf87af2347f19ae37464a4e55629bf43ca6a08cc1a8f70dca828d632535a",
    SEX_KB: "7317a6bd5fa6b9b3fd67ae631bde203bb65fc1e5f9ebfb3f768c217ea665c971",
}
PROTOCOL = DOCS_DIR / "analyses" / "P4-CONFIRM.md"
OUT = RESULTS_DIR / "P4" / "confirm2" / "confirm2.json"
RANKS = RESULTS_DIR / "P4" / "confirm2" / "ranks"
EARLIER_READS = 1
DRY_RUN_FOLD = 3
STRATA = ("uncited", "uncited_in_vocab", "cited", "all")
SYSTEMS = ("E0", "F3", "F1", "F2")
PAIRS = {
    "F3_vs_E0": ("F3", "E0"),
    "F3_vs_F1": ("F3", "F1"),
    "F1_vs_F2": ("F1", "F2"),
    "F2_vs_E0": ("F2", "E0"),
}


def confirm_rows() -> list[str]:
    """The rows of results/P3/CONFIRM_LEDGER.md, one per earlier read of fold 4."""
    path = folds.CONFIRM_LEDGER
    if not path.exists():
        return []
    header = set(folds.LEDGER_HEADER.splitlines())
    return [line for line in path.read_text().splitlines() if line.startswith("|") and line not in header]


def preflight(reason: str, out: Path, ranks: Path, dry_run: bool):
    """Every refusal that needs no artifact; returns the code state. The dry run skips the gate, the ledger,
    the clean-tree and the protocol checks."""
    if not reason.strip():
        raise LineageError("a reason is required")
    if Path(out).exists() or Path(ranks).exists():
        raise LineageError(f"{out} or {ranks} exists; run outputs are never overwritten")
    state = code_state()
    if dry_run:
        return state
    if os.environ.get(folds.CONFIRM_ENV) != "1":
        raise LineageError(f"the CONFIRM fold needs {folds.CONFIRM_ENV}=1 (main session only)")
    if not (PROTOCOL.exists() and ledger.is_preregistered(PROTOCOL)):
        raise LineageError(f"{PROTOCOL.name} must be committed, unmodified, before the second CONFIRM read")
    if state.dirty:
        raise LineageError("uncommitted changes: the CONFIRM read must be reproducible from a SHA")
    rows = confirm_rows()
    if len(rows) != EARLIER_READS:
        raise LineageError(
            f"{folds.CONFIRM_LEDGER.name} has {len(rows)} rows; the second CONFIRM read needs exactly "
            f"{EARLIER_READS} (the first read): it happens once"
        )
    return state


def frozen_system() -> tuple[Callable, dict, dict, dict, dict[str, str]]:
    """(network scorer, add-on kb, add-on bundle, sex kb, sha256 by id) of F3, refused unless every hash
    matches."""
    scorer = network_scorer(NETWORK)
    shas = {NETWORK: checkpoint_sha(NETWORK)}
    kb, shas[KB] = addon.load_kb(KB)
    bundle, shas[F1_BUNDLE] = addon.load_bundle(F1_BUNDLE, KB)
    sex_kb, shas[SEX_KB] = sexrule.load_kb(SEX_KB)
    wrong = {k: v for k, v in shas.items() if v != FROZEN_SHA256[k]}
    if wrong:
        raise LineageError(f"not the frozen F3: {wrong}")
    return scorer, kb, bundle, sex_kb, shas


def score(
    members: Sequence[patients.Patient],
    bundle: Mapping,
    knowledge,
    rule: sexrule.SexRule,
    network_scores: Callable,
    e0_scores: Callable,
) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """(scores, ranks records) of E0, F3, F1 and F2 on the same patients."""
    genes, view = knowledge.genes, addon.network_view(members)
    f2 = network_scores(view)
    e0 = e0_scores(view)
    f1 = addon.score_patients(f2, members, addon.Addon(bundle, knowledge))
    sexes = {p.case_id: p.case.sex for p in members}
    f3 = {c: rule.apply(s, sexes[c]) for c, s in f1.items()}
    scores = {"E0": e0, "F3": f3, "F1": f1, "F2": f2}
    recs = {name: addon.records(members, scores[name], genes, softmax=name == "E0") for name in SYSTEMS}
    return scores, recs


def doctor_view(
    members: Sequence[patients.Patient], scores: Mapping[str, dict], rule: sexrule.SexRule
) -> dict:
    """Per system, patients of known sex whose top k shows a gene impossible for their sex, and such genes."""
    out = {}
    for name in ("F2", "F1", "F3"):
        counts = {k: {"patients": 0, "genes": 0} for k in sexrule.TOP_K}
        n = 0
        for p in members:
            mask, s = rule.blocked(p.case.sex), scores[name].get(p.case_id)
            if s is None or not mask.any():
                continue
            n += 1
            for k, hits in sexrule.shown(s, mask).items():
                counts[k]["patients"] += hits > 0
                counts[k]["genes"] += hits
        out[name] = {"patients_sex_known_scored": n, "shown": counts}
    return out


def impossible_true_genes(members: Sequence[patients.Patient], rule: sexrule.SexRule) -> list[dict]:
    """Patients whose true gene the sex list makes impossible for their recorded sex."""
    lookup = {g.upper(): i for i, g in enumerate(rule.genes)}
    out = []
    for p in members:
        i = lookup.get(p.case.gene.upper())
        if i is not None and rule.blocked(p.case.sex)[i]:
            out.append({"case_id": p.case_id, "gene": p.case.gene, "sex": sexrule.sex_of(p.case.sex)})
    return out


def gate(readings: Mapping[str, dict], recs: Mapping[str, list[dict]]) -> dict:
    """The gate fields: F3's primary reading vs E0, the sex rule's harm on F1, the add-on's net on F2."""
    stratum, metric = report.PRIMARY
    x = readings["F3_vs_E0"][stratum]
    f1 = {r["case_id"]: r["rank"] for r in recs["F1"]}
    harmed = sum(r["rank"] > f1[r["case_id"]] for r in recs["F3"])
    a = readings["F1_vs_F2"]["all"]
    return {
        "stratum": stratum,
        "metric": metric,
        "F3_vs_E0": {
            "n": x["n"],
            "n_groups": x["n_groups"],
            "e0": x["e0"][metric],
            "value": x[metric],
            "delta": x["delta"][metric],
            "ci95": x[f"delta_{metric}_ci95"],
        },
        "pass_primary": x[f"delta_{metric}_ci95"][0] > 0,
        "sex_rule_harmed": harmed,
        "addon_helped": a["helped"],
        "addon_harmed": a["harmed"],
        "addon_helped_minus_harmed": a["helped"] - a["harmed"],
    }


def run(reason: str, out: Path = OUT, ranks: Path = RANKS, dry_run: bool = False) -> dict:
    state = preflight(reason, out, ranks, dry_run)
    scorer, kb, bundle, sex_kb, shas = frozen_system()
    knowledge = knowledge_of(kb, KB)
    rule = sexrule.SexRule(sexrule.limits(sex_kb), knowledge.genes)
    e0 = e0_scorer()
    scorer([])

    members = patients.load_addon((DRY_RUN_FOLD,)) if dry_run else addon.confirm_patients(reason)
    scores, recs = score(members, bundle, knowledge, rule, scorer, e0)
    for name in SYSTEMS:
        report.write_ranks(Path(ranks) / f"{name}.ranks.jsonl", recs[name])
    readings = {name: addon.compare(recs[a], recs[b], STRATA) for name, (a, b) in PAIRS.items()}
    summary = {
        "reason": reason,
        "code_sha": state.sha,
        "dry_run_fold_3": dry_run,
        "patients": f"{patients.SPLIT} train fold {DRY_RUN_FOLD} (dry run)"
        if dry_run
        else f"{patients.SPLIT} train fold {folds.CONFIRM_FOLD} (CONFIRM, second read)",
        "frozen_system": {
            "network_run": NETWORK,
            "network_last_pt_sha256": shas[NETWORK],
            "addon": {"bundle": F1_BUNDLE, "sha256": shas[F1_BUNDLE], "kb": KB, "kb_sha256": shas[KB]},
            "sex_kb": {"id": SEX_KB, "sha256": shas[SEX_KB]},
        },
        "systems": {
            "F3": f"{NETWORK} + {F1_BUNDLE} + hard sex rule ({SEX_KB})",
            "F1": f"{NETWORK} + {F1_BUNDLE}",
            "F2": NETWORK,
        },
        "size": size_facts(recs["E0"]),
        "gate": gate(readings, recs),
        "readings": readings,
        "sex_rule": {
            "list_sizes": {s: sum(v == s for v in sexrule.limits(sex_kb).values()) for s in sexrule.SEXES},
            "true_gene_impossible": impossible_true_genes(members, rule),
            "doctor_view": doctor_view(members, scores, rule),
        },
        "bootstrap": {**report.BOOTSTRAP, "unit": "publication group", "cap": report.CAP},
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return summary


def show_summary(summary: Mapping) -> None:
    size, g = summary["size"], summary["gate"]
    print(f"{summary['patients']}: {size['n']} patients in {size['n_groups']} publications")
    for s, x in size["by_stratum"].items():
        print(f"  {s:17} {x['n']:5} patients, {x['n_groups']} publications")
    for name, readings in summary["readings"].items():
        show(name, readings)
    for name, x in summary["sex_rule"]["doctor_view"].items():
        shown = ", ".join(f"top {k}: {c['patients']} ({c['genes']} genes)" for k, c in x["shown"].items())
        print(f"{name}, sex-impossible genes shown ({x['patients_sex_known_scored']} of known sex): {shown}")
    print(f"true gene impossible for the recorded sex: {len(summary['sex_rule']['true_gene_impossible'])}")
    x = g["F3_vs_E0"]
    lo, hi = x["ci95"]
    print(
        f"primary, F3 vs E0: {g['stratum']} {g['metric']} {x['e0']:.4f} -> {x['value']:.4f} "
        f"Δ {x['delta']:+.4f} [{lo:+.4f}, {hi:+.4f}]: {'PASS' if g['pass_primary'] else 'FAIL'}"
    )
    print(f"sex rule: {g['sex_rule_harmed']} patients ranked below F1")
    net = g["addon_helped_minus_harmed"]
    print(f"add-on: {g['addon_helped']} helped, {g['addon_harmed']} harmed ({net:+d})")
    if summary["dry_run_fold_3"]:
        print("DRY RUN on fold 3 (in-sample for the network): these numbers mean nothing")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--dry-run", type=Path, metavar="SCRATCH_DIR")
    args = parser.parse_args(argv)
    paths = {}
    if args.dry_run:
        paths = {"out": args.dry_run / "confirm2.json", "ranks": args.dry_run / "ranks", "dry_run": True}
    show_summary(run(args.reason, **paths))


if __name__ == "__main__":
    main()
