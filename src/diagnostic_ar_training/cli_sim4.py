"""`dxt sim4 …`: the Phase 3 pristine simulator (docs/analyses/SIM4-v1.md)."""

import json
import sys
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, RESULTS_DIR

sim4_app = typer.Typer(no_args_is_help=True, help="Phase 3 simulator sim4: knowledge, fit, validate, sample.")

ANALYSIS_DIR = RESULTS_DIR / "analyses" / "SIM4-v1"
STATS_DIR = DATA_DIR / "sim4"


def _folds(text: str) -> tuple[int, ...]:
    return tuple(sorted({int(x) for x in text.split(",") if x.strip()}))


def _configs(names: str):
    from diagnostic_ar_training.sim4.config import PRESETS, VARIANTS

    known = {**PRESETS, **VARIANTS}
    chosen = [n.strip() for n in names.split(",") if n.strip()]
    unknown = [n for n in chosen if n not in known]
    if unknown:
        raise typer.BadParameter(f"unknown presets {unknown}; known: {sorted(known)}")
    return {n: known[n] for n in chosen}


def _manifest(artifact_id: str, kind: str, params: dict, outputs: list[Path], extra_inputs: list[dict]):
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.sim4.knowledge import lineage_inputs

    manifest.ensure_new(artifact_id)
    m = manifest.build_manifest(artifact_id, kind, lineage_inputs() + extra_inputs, params, outputs)
    path = manifest.write_manifest(m)
    typer.echo(f"manifest: {path}")


def _split_input() -> list[dict]:
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.sim4 import folds

    return [{"id": f"split:{folds.SPLIT}", "sha256": splits.load_frozen(folds.SPLIT)["content_sha256"]}]


@sim4_app.command("knowledge")
def knowledge(
    kb_id: str = typer.Option("sim4-kb-v1", "--id", help="Artifact id of the knowledge build record"),
    manifest: bool = typer.Option(True, help="Write data/manifests/<id>.json (needs a clean tree)"),
):
    """Build sim4's knowledge, report what each filter dropped, check E0's output index."""
    from diagnostic_ar_training.sim4.knowledge import load_knowledge

    kb = load_knowledge()
    parity = None
    try:
        from diagnostic_ar_training.systems.genphenia_v3 import CHECKPOINT, unpack_bundle

        ckpt = unpack_bundle() / "checkpoints" / CHECKPOINT
        bundle_genes = tuple(json.loads((ckpt / "genes.json").read_text()))
        parity = bundle_genes == kb.genes
    except Exception as exc:  # noqa: BLE001 -- the bundle is optional here; the record says why it is missing
        typer.echo(f"E0 bundle not checked: {exc}", err=True)
    body = {
        "artifact_id": kb_id,
        "content_sha256": kb.content_hash(),
        "e0_index_matches_bundle": parity,
        "genes": len(kb.genes),
        "simulable_genes": len(kb.simulable_genes),
        "diseases_in_hpoa_after_filters": kb.n_diseases,
        "stats": kb.stats,
    }
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    out = STATS_DIR / f"{kb_id}.stats.json"
    out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    typer.echo(json.dumps(body, indent=1, sort_keys=True))
    if manifest:
        _manifest(kb_id, "sim4-knowledge", {"content_sha256": body["content_sha256"]}, [out], [])


def _fit(fit_folds: tuple[int, ...], all_citations: bool, kb, reason: str = ""):
    from diagnostic_ar_training.sim4 import fit, folds

    if folds.CONFIRM_FOLD in fit_folds:
        raise typer.BadParameter("the CONFIRM fold never feeds a fit")
    cases = folds.cases_in(fit_folds, reason=reason)
    label = "folds-" + "-".join(map(str, fit_folds))
    return cases, fit(cases, kb, uncited_only=not all_citations, label=label)


@sim4_app.command("fit")
def fit_cmd(
    fit_folds: str = typer.Option("0,1,2", "--folds", help="Comma-separated p3-v1 CV folds to fit on"),
    all_citations: bool = typer.Option(False, help="Also fit on publications E0's knowledge cites"),
    out: Path = typer.Option(
        None, help="Where to write the fitted params (default results/analyses/SIM4-v1)"
    ),
    manifest_id: str = typer.Option("", help="Write a manifest with this artifact id"),
):
    """Fit the global statistics on the given folds; writes FittedParams JSON."""
    from diagnostic_ar_training.sim4 import load_knowledge

    folds_ = _folds(fit_folds)
    kb = load_knowledge()
    _, params = _fit(folds_, all_citations, kb)
    out = out or ANALYSIS_DIR / f"fit-{params.meta['label']}.json"
    params.save(out)
    shown = {k: v for k, v in params.to_dict().items() if k != "off_vocabulary"}
    typer.echo(json.dumps(shown, indent=1, sort_keys=True))
    typer.echo(f"wrote {out} ({len(params.off_vocabulary)} vocabulary terms)")
    if manifest_id:
        _manifest(
            manifest_id,
            "sim4-fit",
            {"folds": list(folds_), "uncited_only": not all_citations},
            [out],
            _split_input(),
        )


@sim4_app.command("validate")
def validate_cmd(
    fit_folds: str = typer.Option("0,1,2", "--fit-folds"),
    eval_fold: int = typer.Option(3, "--eval-fold"),
    presets: str = typer.Option("e0,freq,real,real_noise", help="Comma-separated presets or variants"),
    reps: int = typer.Option(5, help="Simulated cases per evaluation patient"),
    seed: int = typer.Option(0),
    e0: bool = typer.Option(True, help="Score real and simulated cases with E0 (needs onnxruntime)"),
    all_citations: bool = typer.Option(False, help="Fit and evaluate on cited publications too"),
    out_dir: Path = typer.Option(ANALYSIS_DIR),
    manifest_id: str = typer.Option("", help="Write a manifest with this artifact id"),
    reason: str = typer.Option("", help="Required with the CONFIRM fold (main session only)"),
):
    """Fit on --fit-folds, simulate the --eval-fold gene mix, and compare (validation JSON + markdown)."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.sim4 import folds, load_knowledge
    from diagnostic_ar_training.sim4.validate import markdown, validate

    folds_ = _folds(fit_folds)
    if eval_fold in folds_:
        raise typer.BadParameter("the evaluation fold may not be a fitting fold")
    configs = _configs(presets)
    state = code_state()
    kb = load_knowledge()
    fit_cases, params = _fit(folds_, all_citations, kb)
    eval_cases = folds.cases_in((eval_fold,), reason=reason)
    system = None
    if e0:
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        system = GenPheniaV3()
    report = validate(
        kb,
        params,
        configs,
        fit_cases,
        eval_cases,
        folds.train_groups(),
        splits.load_frozen(folds.SPLIT)["group_status"],
        uncited_only=not all_citations,
        reps=reps,
        seed=seed,
        e0_system=system,
    )
    report.update(
        fit_folds=list(folds_),
        eval_fold=eval_fold,
        code=state.as_dict(),
        knowledge_sha256=kb.content_hash(),
        fit_data_hash=params.meta["data_hash"],
    )
    stem = f"validation-fit{''.join(map(str, folds_))}-eval{eval_fold}"
    out_dir.mkdir(parents=True, exist_ok=True)
    params_path = out_dir / f"fit-{params.meta['label']}.json"
    params.save(params_path)
    json_path, md_path = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    md_path.write_text(markdown(report))
    typer.echo(markdown(report))
    typer.echo(f"wrote {json_path}, {md_path}, {params_path}")
    if manifest_id:
        _manifest(
            manifest_id,
            "sim4-validation",
            {
                "fit_folds": list(folds_),
                "eval_fold": eval_fold,
                "presets": list(configs),
                "reps": reps,
                "seed": seed,
            },
            [json_path, md_path, params_path],
            _split_input(),
        )


@sim4_app.command("sample")
def sample_cmd(
    n: int = typer.Option(10, "--n", help="Cases to draw"),
    preset: str = typer.Option("real_noise"),
    params_path: Path = typer.Option(None, "--params", help="FittedParams JSON (from `dxt sim4 fit`)"),
    gene: str = typer.Option("", help="Gene symbol; random simulable genes if empty"),
    seed: int = typer.Option(0),
    covariates: bool = typer.Option(False),
):
    """Print simulated cases as JSON lines on stdout (nothing is written to the repo)."""
    import dataclasses

    import numpy as np

    from diagnostic_ar_training.sim4 import FittedParams, Sampler, load_knowledge

    cfg = _configs(preset)[preset]
    if covariates:
        cfg = dataclasses.replace(cfg, covariates=True)
    kb = load_knowledge()
    params = FittedParams.load(params_path) if params_path else None
    if params is None and cfg.recipe != "e0":
        typer.echo("warning: no --params; using FittedParams() defaults", err=True)
    sampler = Sampler(kb, params, cfg)
    rng = np.random.default_rng(seed)
    for _ in range(n):
        gi = kb.gene_index[gene] if gene else int(rng.choice(sampler.simulable_gene_indices))
        case = sampler.sample_case(gi, rng)
        sys.stdout.write(json.dumps(dataclasses.asdict(case)) + "\n")
