"""`dxt final-check`: the Phase 2 final check (ADR-0017 decision 5, PHASE2.md).

`p2-v1` vault and `p2-fresh-v1` vault are each loaded once, and E0, `safe-v1` with every rule and its rule
subsets (`[sex+onset]`, `[sex]`, `[onset]`, `[negation]`) and the ft-v1 bundle are scored on the same cases.
Every refusal comes before any data is loaded or the ledger touched.
"""

import json

import typer

from diagnostic_ar_training import RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage.registry import LineageError


def final_check(
    exp: str = typer.Option(..., help="The pre-registered experiment, e.g. EXP-P-005"),
    safe_kb: str = typer.Option(..., "--safe-kb", help="safe-v1 knowledge artifact, e.g. safe-kb-v1"),
    ft_bundle: str = typer.Option(..., "--ft-bundle", help="ft-bundle artifact, e.g. ft-v1-c1-lin-all-ens"),
    ft_kb: str = typer.Option(..., "--ft-kb", help="The bundle's knowledge artifact, e.g. ft-kb-all-v1"),
    reason: str = typer.Option("", help="Required"),
) -> None:
    """The final check, read once: `DXT_SEALED_READ=<exp> dxt final-check --exp <exp> --safe-kb safe-kb-v1
    --ft-bundle ft-v1-c1-lin-all-ens --ft-kb ft-kb-all-v1 --reason ...`.

    Writes results/<exp>/final-check/: report.json (every system vs E0, overall, on the subsets and per
    vault), the ranks and summary of each system, and the manifest results-<exp>-final-check.
    """
    from diagnostic_ar_training.eval import final_check as fc
    from diagnostic_ar_training.eval import safe_eval

    try:
        safe_eval.preflight(exp, list(fc.SPLITS), fc.PART, reason)
    except (ValueError, LineageError) as e:
        raise typer.BadParameter(str(e)) from e

    from diagnostic_ar_training import cli_ft, cli_safe, splits
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.ft.system import E0Logits, E0System
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.safe.bundle import SafeRules, load
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    artifact_id = fc.run_id(exp)
    out_dir = RESULTS_DIR / exp / fc.OUT_DIR
    try:
        manifest.ensure_new(artifact_id)
        if out_dir.exists():
            raise LineageError(f"{out_dir} exists; run outputs are never overwritten")
        sizes = fc.check_frozen({s: splits.load_frozen(s) for s in fc.SPLITS})
        safe_path, safe_sha = cli_safe._kb_output(safe_kb, cli_safe.BUNDLE_FILE)
        bundle, bundle_path, bundle_exp = cli_ft.verified_bundle(ft_bundle, ft_kb)
        ft_kb_path, ft_kb_sha = cli_ft._kb_output(ft_kb)
    except LineageError as e:
        raise typer.BadParameter(str(e)) from e
    state = code_state()

    # Every system is built before the vaults open, so that a failure here costs no read.
    base = GenPheniaV3()
    e0 = E0Logits(base)
    memo = safe_eval.Memo(E0System(e0))
    systems = [
        *fc.safe_systems(memo, SafeRules(load(safe_path))),
        cli_ft.ft_system(base, e0, bundle, ft_bundle, ft_kb_path, ft_kb, bundle_exp or exp),
    ]
    fc.check_names([s.name for s in systems])
    groups = {s: splits.publication_groups(s) for s in fc.SPLITS}

    by_split = {}
    for split_id in fc.SPLITS:
        cases = splits.load_part(split_id, fc.PART, Purpose.EVAL, exp, reason)
        by_split[split_id] = (cases, {c.case_id: f"{split_id}:{groups[split_id][c.case_id]}" for c in cases})
    report, records = fc.evaluate(memo, systems, by_split)
    report |= {
        "exp": exp,
        "cohort": fc.COHORT,
        "frozen_vault_sizes": sizes,
        "safe_kb": safe_kb,
        "safe_bundle_sha256": safe_sha,
        "ft_bundle": ft_bundle,
        "ft_bundle_sha256": sha256_file(bundle_path),
        "ft_kb": ft_kb,
        "code_sha": state.sha,
        "reason": reason,
    }

    outputs = [
        path
        for name, recs in records.items()
        for path in harness.write(f"{exp}/{fc.OUT_DIR}", fc.COHORT, name, "all", recs)
    ]
    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = [
        *base.lineage_inputs(),
        {"id": f"artifact:{safe_kb}/{cli_safe.BUNDLE_FILE}", "sha256": safe_sha},
        {"id": f"artifact:{ft_bundle}", "sha256": report["ft_bundle_sha256"]},
        {"id": f"artifact:{ft_kb}", "sha256": ft_kb_sha},
        *({"id": f"split:{s}", "sha256": sha256_file(SPLITS_DIR / f"{s}.json")} for s in fc.SPLITS),
    ]
    params = {
        "exp": exp,
        "splits": list(fc.SPLITS),
        "part": fc.PART,
        "systems": ["E0", *report["systems_order"]],
        "safe_kb": safe_kb,
        "ft_bundle": ft_bundle,
        "ft_kb": ft_kb,
    }
    manifest.write_manifest(
        manifest.build_manifest(artifact_id, "final-check", inputs, params, outputs, state=state)
    )
    for line in fc.table(report):
        typer.echo(line)
    typer.echo(f"-> {out_dir} (manifest {artifact_id})")
