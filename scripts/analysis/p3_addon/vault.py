r"""PHASE3 §2f step 6: the single vault read of the frozen v4 candidate (EXP-V-002, ADR-0019 decision 7).

Mateo runs it once, in his own terminal, after the pre-registration, the independent review and his go:
    cd /home/mate/FIUBA/trabajo-profesional/diagnostic.ar-training && \
      systemd-run --user --scope -q -p MemoryMax=8G -p MemorySwapMax=0 nice -n 10 \
      env DXT_SEALED_READ=EXP-V-002 PYTHONPATH=src .venv/bin/python scripts/analysis/p3_addon/vault.py \
      --reason "..."

Every refusal comes before any patient is loaded or the ledger touched: a reason, DXT_SEALED_READ=EXP-V-002,
docs/experiments/EXP-V-002.md and the contamination check committed unchanged, a clean tree, a vault never
opened, no earlier output, and the frozen system of P3-CONFIRM §1 (network `R5x-f4-ef2f309462` trained on
exactly folds 0-3, the verified add-on knowledge and bundles, every sha256 as frozen). The network and E0 are
loaded before the vault opens. Then `splits.load_part` opens `p3-v1` vault once and writes the row in
docs/TEST_LEDGER.md.

Vault patients are annotated as `patients.annotate`: their own publication components, the frozen
`group_status`, every input kept (the network and E0 get `addon.network_view`), and fold `VAULT_FOLD` (they
have no cross-validation fold). On the same patients:
- F1 (network + `p3-addon-v1-all`, primary) vs E0, F2 (network) vs E0, F1 vs F2, and
  `p3-addon-v1-sex-age-onset` (the same model) as an agreement check; strata uncited (primary), uncited
  in-vocabulary, cited, all;
- the gate: H1 passes when the 95% CI lower bound of F1's Δ capped MRR on uncited patients is > 0; H2 (F2, the
  same rule) is tested only if H1 passes;
- publication-mean MRR Δ (each publication weighs 1), same publication-cluster bootstrap;
- controls as `confirm.py`: phenotype swap within the vault and parent terms, network vs E0;
- F1 and F2 vs E0 without the vault patients whose (gene, present set) a training patient has
  (results/P3/EXP-V-002/overlap.json from `overlap.py`, committed before the read; non-gating).
Writes results/P3/EXP-V-002/vault.json and the ranks under results/P3/EXP-V-002/ranks/; the ranks of E0, the
network and the bundles are written before the controls run.

`--dry-run SCRATCH_DIR` runs the same code on fold 3 (in-sample for this network, so its numbers mean nothing)
without the sealed gate, the clean-tree check or the ledger, and writes under SCRATCH_DIR.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.registry import LineageError, Purpose
from diagnostic_ar_training.v4 import addon, patients, report

sys.path.insert(0, str(Path(__file__).parent))
from confirm import (  # noqa: E402
    BUNDLES,
    KB,
    NETWORK,
    controls,
    knowledge_of,
    network_scorer,
    parent_mapper,
    show,
    training_genes,
)

EXP = "EXP-V-002"
SPLIT = patients.SPLIT
F1_BUNDLE, AGREEMENT_BUNDLE = BUNDLES
FROZEN_SHA256 = {
    NETWORK: "22edfd7ea56510d1210111797215a9a54c22d829979ef05b4e3cc85a758004da",
    F1_BUNDLE: "31299383a7dce279acdfae37248db8e7e04c62225fd892080c39758276a093b6",
    AGREEMENT_BUNDLE: "360c5fe68a863712c72b0ff0d313737935d89a8816cb064a817a2072773f3ec2",
    KB: "089ccf87af2347f19ae37464a4e55629bf43ca6a08cc1a8f70dca828d632535a",
}
OUT = RESULTS_DIR / "P3" / EXP / "vault.json"
RANKS = RESULTS_DIR / "P3" / EXP / "ranks"
OVERLAP = RESULTS_DIR / "P3" / EXP / "overlap.json"
VAULT_FOLD = -1
DRY_RUN_FOLD = 3
STRATA = ("uncited", "uncited_in_vocab", "cited", "all")
PAIRS = {
    "F1_vs_E0": (F1_BUNDLE, "E0"),
    "F2_vs_E0": ("network", "E0"),
    "F1_vs_F2": (F1_BUNDLE, "network"),
    "agreement_vs_E0": (AGREEMENT_BUNDLE, "E0"),
}


def code_state():
    from diagnostic_ar_training.lineage.gitinfo import code_state as state

    return state()


def checkpoint_sha(run_id: str) -> str:
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.v4.runs import run_dir

    return sha256_file(run_dir(run_id) / "last.pt")


def e0_scorer() -> Callable:
    """E0's logits through one production model, built now (before any patient is loaded)."""
    from diagnostic_ar_training.ft.system import E0Logits
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    e0 = E0Logits(GenPheniaV3())
    return lambda members: addon.e0_logits(members, e0)


def preflight(reason: str, out: Path, dry_run: bool, overlap: Path):
    """Every refusal that needs no artifact; returns the code state. The dry run skips the sealed gate."""
    if not reason.strip():
        raise LineageError("a reason is required")
    state = code_state()
    if dry_run:
        return state
    ledger.require_sealed_read_env(SPLIT, "vault", EXP)
    registration = ledger.EXPERIMENTS_DIR / f"{EXP}.md"
    if not (registration.exists() and ledger.is_preregistered(registration)):
        raise LineageError(f"docs/experiments/{EXP}.md must be committed, unmodified, before the vault read")
    if not (Path(overlap).exists() and ledger.is_preregistered(Path(overlap))):
        raise LineageError(
            f"{overlap}: the contamination check must be committed, unmodified, before the read"
        )
    if state.dirty:
        raise LineageError("uncommitted changes: the vault read must be reproducible from a SHA")
    if ledger.entries(SPLIT, "vault"):
        raise LineageError(f"{SPLIT}/vault was already opened (see docs/TEST_LEDGER.md): it opens once")
    if Path(out).exists():
        raise LineageError(f"{out} exists; run outputs are never overwritten")
    return state


def frozen_system() -> tuple[Callable, dict, dict[str, dict], dict[str, str]]:
    """(network scorer, kb, bundles, sha256 by id) of P3-CONFIRM §1, refused unless every hash matches."""
    scorer = network_scorer(NETWORK)
    shas = {NETWORK: checkpoint_sha(NETWORK)}
    kb, shas[KB] = addon.load_kb(KB)
    bundles = {}
    for bundle_id in BUNDLES:
        bundles[bundle_id], shas[bundle_id] = addon.load_bundle(bundle_id, KB)
    wrong = {k: v for k, v in shas.items() if v != FROZEN_SHA256[k]}
    if wrong:
        raise LineageError(f"not the frozen system of P3-CONFIRM §1: {wrong}")
    return scorer, kb, bundles, shas


def vault_members(cases: Iterable, status: Mapping[str, str]) -> list[patients.Patient]:
    """Cases annotated as `patients.annotate`, with their own publication components and fold VAULT_FOLD."""
    from diagnostic_ar_training import splits

    cases = list(cases)
    groups = splits._components(cases)
    return patients.annotate(cases, groups, dict(status), lambda group: VAULT_FOLD, keep_excluded=True)


def open_vault(reason: str, status: Mapping[str, str]) -> list[patients.Patient]:
    """The vault's patients, every input kept; `splits.load_part` ledgers this opening, refuses a second."""
    from diagnostic_ar_training import splits

    cases = splits.load_part(SPLIT, splits.Part.VAULT, Purpose.EVAL, exp_id=EXP, reason=reason)
    return vault_members(cases, status)


def dry_run_patients(status: Mapping[str, str]) -> list[patients.Patient]:
    """Fold 3 through `vault_members`, checked against the train annotation of the same patients."""
    reference = patients.load_addon((DRY_RUN_FOLD,))
    members = vault_members([p.case for p in reference], status)
    if [(p.group, p.status) for p in members] != [(p.group, p.status) for p in reference]:
        raise LineageError("vault_members disagrees with the train annotation on fold 3")
    return members


def score(
    members: Sequence[patients.Patient],
    bundles: Mapping[str, Mapping],
    knowledge,
    network_scores: Callable,
    e0_scores: Callable,
) -> dict[str, list[dict]]:
    """Ranks records of E0, the network and the network + each bundle on the same patients."""
    genes, view = knowledge.genes, addon.network_view(members)
    net = network_scores(view)
    recs = {
        "E0": addon.records(members, e0_scores(view), genes, softmax=True),
        "network": addon.records(members, net, genes),
    }
    for bundle_id, b in bundles.items():
        scores = addon.score_patients(net, members, addon.Addon(b, knowledge))
        recs[bundle_id] = addon.records(members, scores, genes)
    return recs


def publication_mean(new: Sequence[dict], base: Sequence[dict], strata: Sequence[str] = STRATA) -> dict:
    """Per stratum, MRR with each publication group weighing 1, and its Δ with the publication-cluster
    bootstrap of `report.capped_bootstrap` (same draws)."""
    by_id = {r["case_id"]: r["rank"] for r in base}
    out = {}
    for name in strata:
        recs = [r for r in new if name in r["strata"]]
        if not recs:
            continue
        _, inv, sizes = np.unique([r["group"] for r in recs], return_inverse=True, return_counts=True)
        rr_new = np.bincount(inv, weights=1.0 / np.array([r["rank"] for r in recs], dtype=float)) / sizes
        rr_base = np.bincount(inv, weights=1.0 / np.array([by_id[r["case_id"]] for r in recs])) / sizes
        rng = np.random.default_rng(report.BOOTSTRAP["seed"])
        picks = rng.integers(0, sizes.size, size=(report.BOOTSTRAP["n_resamples"], sizes.size))
        deltas = (rr_new - rr_base)[picks].mean(axis=1)
        out[name] = {
            "n": len(recs),
            "n_groups": int(sizes.size),
            "mrr_pub": float(rr_new.mean()),
            "e0_mrr_pub": float(rr_base.mean()),
            "delta": float(rr_new.mean() - rr_base.mean()),
            "ci95": [float(x) for x in np.percentile(deltas, [2.5, 97.5])],
        }
    return out


def gate(f1: Mapping[str, dict], f2: Mapping[str, dict]) -> dict:
    """H1: F1's 95% CI lower bound of Δ capped MRR on uncited patients > 0; H2: the same for F2, if H1."""
    stratum, metric = report.PRIMARY

    def reading(x: Mapping) -> dict:
        s = x[stratum]
        return {
            "n": s["n"],
            "n_groups": s["n_groups"],
            "e0": s["e0"][metric],
            "value": s[metric],
            "delta": s["delta"][metric],
            "ci95": s[f"delta_{metric}_ci95"],
        }

    a, b = reading(f1), reading(f2)
    h1 = a["ci95"][0] > 0
    return {
        "stratum": stratum,
        "metric": metric,
        "F1": a,
        "h1_pass": h1,
        "F2": b,
        "h2_tested": h1,
        "h2_pass": b["ci95"][0] > 0 if h1 else None,
    }


def size_facts(recs: Sequence[dict]) -> dict:
    uncited = Counter(r["group"] for r in recs if "uncited" in r["strata"])
    group, largest = uncited.most_common(1)[0] if uncited else (None, 0)
    n_uncited = sum(uncited.values())
    return {
        "n": len(recs),
        "n_groups": len({r["group"] for r in recs}),
        "by_stratum": {
            s: {
                "n": len(v),
                "n_groups": len({r["group"] for r in v}),
                "out_of_vocab": sum(not r["gene_in_vocab"] for r in v),
                "unscorable": sum(not r["scorable"] for r in v),
            }
            for s, v in report.by_stratum(recs).items()
            if s in STRATA
        },
        "largest_uncited_group": {
            "group": group,
            "n": largest,
            "share": largest / n_uncited if n_uncited else None,
        },
    }


def without(recs: Mapping[str, list[dict]], excluded: set[str]) -> dict:
    """F1 and F2 vs E0 without the `excluded` patients (the contamination check's)."""
    kept = {name: [r for r in v if r["case_id"] not in excluded] for name, v in recs.items()}
    out = {"n_excluded": sum(r["case_id"] in excluded for r in recs["E0"])}
    for name in ("F1_vs_E0", "F2_vs_E0"):
        a, b = PAIRS[name]
        out[name] = addon.compare(kept[a], kept[b], STRATA)
    return out


def run(
    reason: str,
    out: Path = OUT,
    ranks: Path = RANKS,
    dry_run: bool = False,
    overlap: Path | None = None,
) -> dict:
    from diagnostic_ar_training import splits

    overlap = Path(overlap or OVERLAP)
    state = preflight(reason, out, dry_run, overlap)
    scorer, kb, bundles, shas = frozen_system()
    frozen = splits.load_frozen(SPLIT)
    knowledge = knowledge_of(kb, KB)
    e0 = e0_scorer()
    scorer([])
    with_patients, to_parent = training_genes(), parent_mapper()

    status = frozen["group_status"]
    members = dry_run_patients(status) if dry_run else open_vault(reason, status)
    recs = score(members, bundles, knowledge, scorer, e0)
    for name, r in recs.items():
        report.write_ranks(Path(ranks) / f"{name}.ranks.jsonl", r)
    excluded = set() if dry_run else set(json.loads(overlap.read_text())["present_key"]["case_ids"])
    readings = {name: addon.compare(recs[a], recs[b], STRATA) for name, (a, b) in PAIRS.items()}
    control_summary, control_recs = controls(members, scorer, e0, knowledge.genes, with_patients, to_parent)
    f1_ranks = {r["case_id"]: r["rank"] for r in recs[F1_BUNDLE]}
    summary = {
        "exp": EXP,
        "reason": reason,
        "code_sha": state.sha,
        "dry_run_fold_3": dry_run,
        "patients": f"{SPLIT} train fold {DRY_RUN_FOLD} (dry run)" if dry_run else f"{SPLIT} vault",
        "split": {"id": SPLIT, "content_sha256": frozen.get("content_sha256")},
        "frozen_system": {
            "network_run": NETWORK,
            "network_last_pt_sha256": shas[NETWORK],
            "kb": {"id": KB, "sha256": shas[KB]},
            "bundles": {b: shas[b] for b in BUNDLES},
        },
        "finalists": {"F1": f"{NETWORK} + {F1_BUNDLE}", "F2": NETWORK, "agreement": AGREEMENT_BUNDLE},
        "size": size_facts(recs["E0"]),
        "gate": gate(readings["F1_vs_E0"], readings["F2_vs_E0"]),
        "readings": readings,
        "publication_mean": {
            name: publication_mean(recs[PAIRS[name][0]], recs["E0"]) for name in ("F1_vs_E0", "F2_vs_E0")
        },
        "agreement": {
            "bundle": AGREEMENT_BUNDLE,
            "ranks_differing_from_F1": sum(
                r["rank"] != f1_ranks[r["case_id"]] for r in recs[AGREEMENT_BUNDLE]
            ),
        },
        "controls": control_summary,
        "without_overlap": without(recs, excluded),
        "bootstrap": {**report.BOOTSTRAP, "unit": "publication group", "cap": report.CAP},
    }
    for name, r in control_recs.items():
        report.write_ranks(Path(ranks) / f"{name}.ranks.jsonl", r)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return summary


def show_summary(summary: Mapping) -> None:
    size, g = summary["size"], summary["gate"]
    largest = size["largest_uncited_group"]
    print(f"{summary['patients']}: {size['n']} patients in {size['n_groups']} publications")
    for s, x in size["by_stratum"].items():
        print(f"  {s:17} {x['n']:5} patients, {x['n_groups']} publications")
    if largest["group"] is not None:
        print(f"  largest uncited publication: {largest['n']} patients ({largest['share']:.1%})")
    for name, readings in summary["readings"].items():
        show(name, readings)
    for name, by_stratum in summary["publication_mean"].items():
        for s, x in by_stratum.items():
            lo, hi = x["ci95"]
            print(
                f"{name + ' (publication mean)':34} {s:17} {x['e0_mrr_pub']:.4f} -> {x['mrr_pub']:.4f} "
                f"Δ {x['delta']:+.4f} [{lo:+.4f}, {hi:+.4f}] ({x['n_groups']} publications)"
            )
    print(f"{AGREEMENT_BUNDLE}: {summary['agreement']['ranks_differing_from_F1']} ranks differ from F1")
    show("swap: network vs E0", summary["controls"]["swap"]["vs_e0"])
    show("parent terms: network vs E0", summary["controls"]["parent"]["vs_e0"])
    for label, x in summary["controls"]["swap"]["raw_rank"].items():
        print(f"swap raw rank, uncited in-vocab, {label}: {x}")
    for h, key in (("H1 (F1)", "F1"), ("H2 (F2)", "F2")):
        x = g[key]
        lo, hi = x["ci95"]
        print(
            f"{h}: {g['stratum']} {g['metric']} {x['e0']:.4f} -> {x['value']:.4f} "
            f"Δ {x['delta']:+.4f} [{lo:+.4f}, {hi:+.4f}]"
        )
    h2 = "not tested (H1 failed)" if not g["h2_tested"] else ("PASS" if g["h2_pass"] else "FAIL")
    print(f"H1: {'PASS' if g['h1_pass'] else 'FAIL'}; H2: {h2}")
    if summary["dry_run_fold_3"]:
        print("DRY RUN on fold 3 (in-sample for the network): these numbers mean nothing")


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reason", required=True)
    parser.add_argument("--dry-run", type=Path, metavar="SCRATCH_DIR")
    args = parser.parse_args(argv)
    paths = {}
    if args.dry_run:
        paths = {"out": args.dry_run / "vault.json", "ranks": args.dry_run / "ranks", "dry_run": True}
    show_summary(run(args.reason, **paths))


if __name__ == "__main__":
    main()
