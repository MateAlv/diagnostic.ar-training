"""`dxt ft …`: Phase 2 Track 3, ft-v1 (docs/PHASE2.md): knowledge build, dev grid, seed ensembles, report, and
the sealed confirmation read."""

import json
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR, RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage.registry import LineageError

ft_app = typer.Typer(
    no_args_is_help=True, help="Phase 2 Track 3: ft-v1, a knowledge-conditioned residual on v3.0."
)

KB_SOURCES = ("hpo_genes_to_disease", "hpo_annotations", "orphanet_ages_2026_06", "hgnc", "hpo_ontology")
KB_FILE = "ft-kb.json.gz"
MASK_SPLIT, MASK_SCOPE = "r1-v1", "all"
KB_MASK_SCOPES = ("all", "none")
SPLIT = "r1-v1"
MODELS_DIR = INTERIM_DIR / "models" / "ft"


def _require_clean():
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    return state


def _kb_output(kb_id: str) -> tuple[Path, str]:
    from diagnostic_ar_training.lineage import manifest

    m = manifest.load_manifest(kb_id)
    if m.kind != "ft-kb":
        raise typer.BadParameter(f"{kb_id} is a {m.kind!r} artifact, not an ft-kb")
    for out in m.outputs:
        path = manifest.output_path(out)
        if path.name == KB_FILE:
            if not path.is_file() or manifest.verify_outputs(m):
                path = manifest.fetch_outputs(m)[[o.path for o in m.outputs].index(out.path)]
            return path, out.sha256
    raise LineageError(f"{kb_id} has no output named {KB_FILE}")


@ft_app.command("kb")
def ft_kb(
    kb_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. ft-kb-all-v2"),
    overrides: str = typer.Option(
        "data/curation/safe-v1-overrides.csv", help="safe-v1 curation overrides ('' for none)"
    ),
    mask_scope: str = typer.Option(
        MASK_SCOPE,
        help="'all' masks every r1-v1 PMID (the evaluated knowledge); 'none' masks nothing (production only)",
    ),
) -> None:
    """Build the ft-v1 knowledge, by default with every r1-v1 PMID masked (train, dev, test and vault).

    `--mask-scope none` builds the production knowledge: the same sources, rules and overrides, with no PMID
    masked. Patients whose papers it includes cannot evaluate it.
    """
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.ft import knowledge as ft_knowledge
    from diagnostic_ar_training.lineage import registry
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.safe import knowledge
    from diagnostic_ar_training.safe import overrides as curation
    from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle

    if mask_scope not in KB_MASK_SCOPES:
        raise typer.BadParameter(f"--mask-scope must be one of {KB_MASK_SCOPES}")
    ensure_new(kb_id)
    state = _require_clean()
    rows = []
    if overrides:
        try:
            rows = curation.read(Path(overrides))
        except curation.OverrideError as e:
            raise typer.BadParameter(str(e)) from e
    paths = {n: open_source(n, Purpose.KB) for n in KB_SOURCES}
    vocabulary = V3Inputs(unpack_bundle()).genes
    masked: list[str] = []
    mask_path = None
    if mask_scope != "none":
        splits.write_mask(MASK_SPLIT, mask_scope)  # refuses if the committed list drifted from the split
        mask_path = splits.mask_path(MASK_SPLIT, mask_scope)
        masked = mask_path.read_text().split()
    ontology = Ontology.from_json(paths["hpo_ontology"])
    built, stats = ft_knowledge.build(
        vocabulary,
        knowledge.read_genes_to_disease(paths["hpo_genes_to_disease"]),
        knowledge.read_annotations(paths["hpo_annotations"], masked),
        knowledge.read_orphanet_onsets(paths["orphanet_ages_2026_06"]),
        knowledge.read_hgnc_locations(paths["hgnc"]),
        ontology.ancestors,
        rows,
    )
    kb_path = INTERIM_DIR / "ft" / kb_id / KB_FILE
    kb_io.write(built, kb_path)
    committed = DATA_DIR / "ft" / kb_id
    committed.mkdir(parents=True, exist_ok=True)
    stats_path = committed / "stats.json"
    stats_path.write_text(
        json.dumps({**stats, "overrides_skipped_rows": built["overrides_skipped"]}, indent=1) + "\n"
    )
    sources = registry.load_sources()
    inputs = [sources[n].as_input() for n in (*KB_SOURCES, E0_SOURCE)]
    if mask_path is not None:
        inputs.append({"id": f"{mask_scope}-pmids:{MASK_SPLIT}", "sha256": sha256_file(mask_path)})
    if overrides:
        inputs.append({"id": f"overrides:{overrides}", "sha256": sha256_file(Path(overrides))})
    params = {
        "schema": ft_knowledge.SCHEMA,
        "vocabulary": "E0 (genphenia_v3) genes",
        "mask_split": MASK_SPLIT if mask_scope != "none" else None,
        "mask_scope": mask_scope,
        "associations": "hpo_genes_to_disease without POLYGENIC",
        "safe_rules": "safe/knowledge.py (safe-kb/1)",
        "xlr_only": sorted(ft_knowledge.XLR),
        "profile": "aspect P, qualifier not NOT, of the gene's diseases",
        "overrides": overrides or None,
    }
    write_manifest(build_manifest(kb_id, "ft-kb", inputs, params, [kb_path, stats_path], state=state))
    shown = {k: v for k, v in stats.items() if not k.startswith("hpoa_")}
    typer.echo(json.dumps(shown, indent=1))


def _setup(kb_id: str, device: str, pooled: bool):
    from diagnostic_ar_training.ft.runs import Setup
    from diagnostic_ar_training.rerank import kb as kb_io

    kb_path, kb_sha = _kb_output(kb_id)
    return Setup(kb_io.read(kb_path), kb_id, kb_sha, device, pooled)


def _echo_report(label: str, report: dict) -> None:
    from diagnostic_ar_training.ft.evaluate import line

    typer.echo(line(f"{label} dev", report["dev"]["vs_e0"]))
    for name in ("post_e0", "gene_not_in_train"):
        typer.echo(line(f"  dev {name}", report["dev"]["subsets"][name]))
    typer.echo(line("  dev present view", report["dev_present_view"]))
    typer.echo(line("  train", report["train"]["vs_e0"]))
    typer.echo(line("  train held-out groups", report["train"]["subsets"]["inner_val"]))


def _require_preregistered(exp: str) -> None:
    from diagnostic_ar_training.lineage import ledger

    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before the run")


@ft_app.command("grid")
def ft_grid(
    exp: str = typer.Option("EXP-P-003", help="Pre-registered experiment id"),
    kb_id: str = typer.Option("ft-kb-all-v2", "--kb"),
    config: list[str] = typer.Option(..., help="Configurations of ft/configs.py (or <name>-nosexage)"),
    seed: list[int] = typer.Option([0, 1, 2]),
    device: str = typer.Option("cuda"),
) -> None:
    """Fit each configuration × seed on R1-train (early stopping on held-out train groups), report it vs E0.

    Dev and train are reported. Writes results/<exp>/<PREFIX>-<config>-s<seed>/ (PREFIX in ft/configs.py) with
    a manifest; the weights go
    to data/interim/models/ft.
    """
    import time

    import numpy as np
    import torch

    from diagnostic_ar_training.ft import configs, runs
    from diagnostic_ar_training.ft import train as ft_train
    from diagnostic_ar_training.ft.bundle import FtResidual, load_deltas
    from diagnostic_ar_training.ft.system import FtV1
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest

    todo = [(name, s) for name in config for s in seed]
    for name, s in todo:
        try:
            configs.config(name)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        ensure_new(f"results-{exp}-{configs.PREFIX}-{name}-s{s}")
    state = _require_clean()
    _require_preregistered(exp)
    wall = time.perf_counter()
    setup = _setup(kb_id, device, any(configs.config(n).get("classifier") for n, _ in todo))
    a = setup.arrays
    typer.echo(
        f"setup {runs.elapsed(wall):.0f} s: {setup.counts()}; E0 check {setup.e0_check}; "
        f"pooled check {setup.pooled_check}; replay {setup.replay_stats}"
    )
    part = ft_train.to_part(
        a["case_ids"], a["logits"], a["feats"], a["z"], a["target"], setup.device, setup.pooled_train
    )
    trn, val = part.rows(set(a["case_ids"]) - setup.inner), part.rows(setup.inner)
    by_id = {c.case_id: c for c in setup.train_cases}
    for name, s in todo:
        start = time.perf_counter()
        cfg = ft_train.FitConfig(seed=s, **configs.config(name))
        model_id = f"{configs.PREFIX}-{name}-s{s}"
        out_dir, model_dir = RESULTS_DIR / exp / model_id, MODELS_DIR / exp / model_id
        if out_dir.exists() or model_dir.exists():
            raise typer.BadParameter(f"{out_dir} or {model_dir} exists; run ids are never reused")
        typer.echo(f"[{model_id}] {cfg.as_dict()}")
        if setup.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(setup.device)
        result = ft_train.fit(cfg, trn, val, setup.replay if cfg.classifier else None, log=typer.echo)
        model = result.model
        untrained = ft_train.ResidualNet(cfg.hidden, cfg.features, cfg.covariates).to(setup.device)
        with torch.no_grad():
            step0_nonzero = int(torch.count_nonzero(untrained(trn.feats[:512], trn.z[:512])))
        model_dir.mkdir(parents=True)
        delta_name = None
        if cfg.classifier:
            delta_name = f"{model_id}/delta.npz"
            np.savez(
                model_dir / "delta.npz",
                weight=model.delta_weight.detach().cpu().numpy(),
                bias=model.delta_bias.detach().cpu().numpy(),
            )
        member = model.member(delta_name)
        member_path = runs.write_json(model_dir / "member.json", member)
        torch.save(model.state_dict(), model_dir / "weights.pt")
        bundle = runs.bundle(kb_id, [member], [model_id])
        residual = FtResidual(bundle, setup.knowledge, load_deltas(bundle, MODELS_DIR / exp))
        system = FtV1(setup.e0, residual, model_id, setup.pooler if cfg.classifier else None)
        report, records = setup.evaluate(system)
        checks = {
            "step0_residual_nonzero_entries": step0_nonzero,
            "theta_nonnegative": bool((model.theta >= 0).all()),
            "numpy_vs_torch_max_abs_residual_diff": runs.residual_agreement(model, residual, val, by_id),
            "dev_present_view_probs_differ": report["dev_present_identity"]["probs_differ"],
            "e0": setup.e0_check,
        }
        checks["valid"] = bool(
            step0_nonzero == 0
            and checks["theta_nonnegative"]
            and checks["numpy_vs_torch_max_abs_residual_diff"] <= 1e-3
            and (cfg.classifier or checks["dev_present_view_probs_differ"] == 0)
        )
        summary = {
            "model_id": model_id,
            "config_name": name,
            "seed": s,
            "config": cfg.as_dict(),
            "n_parameters": configs.n_parameters(name),
            "selectable": name in configs.SELECTABLE,
            "best_epoch": result.best_epoch,
            "epochs_run": result.epochs_run,
            "stopped_early": result.stopped_early,
            "fit_seconds": result.seconds,
            "run_seconds": runs.elapsed(start),
            "max_gpu_memory_gb": torch.cuda.max_memory_allocated(setup.device) / 1e9
            if setup.device.type == "cuda"
            else None,
            "device": torch.cuda.get_device_name(setup.device) if setup.device.type == "cuda" else "cpu",
            "torch": torch.__version__,
            "code": state.as_dict(),
            "kb": kb_id,
            "counts": {**setup.counts(), "fit_rows": len(trn), "held_out_rows": len(val)},
            "replay": setup.replay_stats if cfg.classifier else None,
            "pooled_check": setup.pooled_check if cfg.classifier else None,
            "member": {k: v for k, v in member.items() if k != "mlp"},
            "checks": checks,
            "row": runs.row(report),
            **report,
        }
        outputs = [
            runs.write_json(out_dir / "curves.json", result.history),
            runs.write_json(out_dir / "summary.json", summary),
            *runs.write_records(out_dir, records),
            member_path,
            model_dir / "weights.pt",
        ]
        if cfg.classifier:
            outputs.append(model_dir / "delta.npz")
        params = {**cfg.as_dict(), "exp": exp, "model_id": model_id, "config_name": name, "device": device}
        write_manifest(
            build_manifest(
                f"results-{exp}-{model_id}",
                "ft-run",
                setup.lineage(),
                params,
                outputs,
                notes="E0 frozen; the weights stay in data/interim/models/ft.",
                state=state,
            )
        )
        _echo_report(model_id, report)
        typer.echo(
            f"[{model_id}] best epoch {result.best_epoch}/{result.epochs_run}, theta "
            f"{[round(x, 3) for x in member['theta']]}, checks {'pass' if checks['valid'] else 'FAIL'}, "
            f"{summary['run_seconds']:.0f} s"
        )
    typer.echo(f"grid done in {runs.elapsed(wall) / 60:.1f} min")


def _member(exp: str, model_id: str) -> dict:
    from diagnostic_ar_training.lineage.manifest import load_manifest, output_path, verify_outputs

    m = load_manifest(f"results-{exp}-{model_id}")
    if problems := verify_outputs(m):
        raise LineageError("; ".join(problems))
    path = next(output_path(o) for o in m.outputs if o.path.endswith(f"{model_id}/member.json"))
    return json.loads(path.read_text())


@ft_app.command("ensemble")
def ft_ensemble(
    exp: str = typer.Option("EXP-P-003"),
    kb_id: str = typer.Option("ft-kb-all-v2", "--kb"),
    config: str = typer.Option(..., help="A configuration whose seeds all ran"),
    seed: list[int] = typer.Option([0, 1, 2]),
    device: str = typer.Option("cuda"),
) -> None:
    """The mean of a configuration's seed residuals as one bundle, reported vs E0 on dev and train.

    Writes the bundle to data/ft/<PREFIX>-<config>-ens/ (committed; classifier deltas stay in data/interim)
    and the report to results/<exp>/<PREFIX>-<config>-ens/, each with a manifest.
    """
    import time

    from diagnostic_ar_training.ft import configs, runs
    from diagnostic_ar_training.ft.bundle import FtResidual, load_deltas
    from diagnostic_ar_training.ft.system import FtV1
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest

    bundle_id = f"{configs.PREFIX}-{config}-ens"
    ensure_new(bundle_id)
    ensure_new(f"results-{exp}-{bundle_id}")
    state = _require_clean()
    _require_preregistered(exp)
    start = time.perf_counter()
    model_ids = [f"{configs.PREFIX}-{config}-s{s}" for s in seed]
    members = [_member(exp, m) for m in model_ids]
    bundle = runs.bundle(kb_id, members, model_ids)
    bundle_path = runs.write_json(DATA_DIR / "ft" / bundle_id / "ft-v1-bundle.json", bundle)
    classifier = bool(configs.config(config).get("classifier"))
    setup = _setup(kb_id, device, classifier)
    residual = FtResidual(bundle, setup.knowledge, load_deltas(bundle, MODELS_DIR / exp))
    system = FtV1(setup.e0, residual, bundle_id, setup.pooler if classifier else None)
    report, records = setup.evaluate(system)
    refs = setup.lineage() + [
        {"id": f"results-{exp}-{m}/member.json", "sha256": sha256_file(MODELS_DIR / exp / m / "member.json")}
        for m in model_ids
    ]
    deltas = [MODELS_DIR / exp / m / "delta.npz" for m in model_ids] if classifier else []
    params = {"exp": exp, "config_name": config, "seeds": list(seed), "kb": kb_id, "combine": "mean residual"}
    write_manifest(build_manifest(bundle_id, "ft-bundle", refs, params, [bundle_path, *deltas], state=state))
    out_dir = RESULTS_DIR / exp / bundle_id
    summary = {
        "bundle_id": bundle_id,
        "config_name": config,
        "seeds": list(seed),
        "code": state.as_dict(),
        "kb": kb_id,
        "counts": setup.counts(),
        "e0_check": setup.e0_check,
        "row": runs.row(report),
        "run_seconds": runs.elapsed(start),
        **report,
    }
    outputs = [runs.write_json(out_dir / "summary.json", summary), *runs.write_records(out_dir, records)]
    refs = setup.lineage() + [{"id": f"artifact:{bundle_id}", "sha256": sha256_file(bundle_path)}]
    write_manifest(
        build_manifest(f"results-{exp}-{bundle_id}", "ft-ensemble-eval", refs, params, outputs, state=state)
    )
    _echo_report(bundle_id, report)


@ft_app.command("report")
def ft_report(exp: str = typer.Option("EXP-P-003")) -> None:
    """Every run of the grid, mean ± sd per configuration, and the pre-registered selection;
    results/<exp>/report-<PREFIX>.json, with a manifest."""
    import statistics

    from diagnostic_ar_training.ft import configs, runs
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest

    artifact_id = f"results-{exp}-report-{configs.PREFIX}"
    ensure_new(artifact_id)
    state = _require_clean()
    rows: dict[str, list[dict]] = {}
    ensembles = {}
    summaries = sorted((RESULTS_DIR / exp).glob(f"{configs.PREFIX}-*/summary.json"))
    for path in summaries:
        s = json.loads(path.read_text())
        if "bundle_id" in s:
            ensembles[s["config_name"]] = {"bundle_id": s["bundle_id"], **s["row"]}
            continue
        rows.setdefault(s["config_name"], []).append(
            {
                "model_id": s["model_id"],
                "seed": s["seed"],
                "valid": s["checks"]["valid"],
                "best_epoch": s["best_epoch"],
                "theta": s["member"]["theta"],
                **s["row"],
            }
        )
    by_config = {}
    for name, rs in rows.items():
        agg = configs.aggregate(rs)
        agg["valid"] = all(r["valid"] for r in rs)
        agg["n_parameters"] = configs.n_parameters(name)
        agg["selectable"] = name in configs.SELECTABLE
        by_config[name] = agg
    grid = [n for n in by_config if n in configs.CONFIGS]
    means = [by_config[n]["dev_delta"]["mean"] for n in grid]
    out = {
        "exp": exp,
        "runs": rows,
        "configurations": by_config,
        "median_config_dev_delta": statistics.median(means) if means else None,
        "selection": configs.select({n: by_config[n] for n in grid}),
        "ensembles": ensembles,
    }
    out_path = runs.write_json(RESULTS_DIR / exp / f"report-{configs.PREFIX}.json", out)
    refs = [{"id": f"summary:{p.parent.name}", "sha256": sha256_file(p)} for p in summaries]
    params = {"exp": exp, "prefix": configs.PREFIX, "rule": "configs.select"}
    write_manifest(build_manifest(artifact_id, "ft-report", refs, params, [out_path], state=state))
    for name, agg in by_config.items():
        d, h = agg["dev_delta"], agg["dev_harmed"]
        typer.echo(
            f"{name:28} seeds {agg['seeds']} dev Δ {d['mean']:+.5f} ± {d['sd'] or 0:.5f} harmed "
            f"{h['mean']:.4f} present {agg['present_delta']['mean']:+.5f} "
            f"train {agg['train_delta']['mean']:+.5f} "
            f"held-out {agg['inner_delta']['mean']:+.5f} post-E0 {agg['post_e0_delta']['mean']:+.5f} "
            f"params {agg['n_parameters']}{'' if agg['selectable'] else ' (not selectable)'}"
        )
    typer.echo(json.dumps(out["selection"], indent=1))


def verified_bundle(bundle_id: str, kb_id: str) -> tuple[dict, Path, str | None]:
    """(bundle, its path, the experiment its members were fitted in) of a verified ft-bundle on `kb_id`."""
    from diagnostic_ar_training.ft.bundle import load
    from diagnostic_ar_training.lineage import manifest

    m = manifest.load_manifest(bundle_id)
    problems = manifest.verify_outputs(m)
    if m.kind != "ft-bundle" or problems:
        raise LineageError(f"{bundle_id}: not a verified ft-bundle (kind {m.kind!r}; {problems})")
    bundle_path = next(manifest.output_path(o) for o in m.outputs if o.path.endswith("ft-v1-bundle.json"))
    bundle = load(bundle_path)
    if bundle["kb_id"] != kb_id:
        raise LineageError(f"{bundle_id} was trained on {bundle['kb_id']}, not {kb_id}")
    return bundle, bundle_path, m.params.get("exp")


def ft_system(base, e0, bundle: dict, bundle_id: str, kb_path: Path, kb_id: str, deltas_exp: str):
    """`FtV1` for a loaded bundle on v3.0 (`base`) through the shared E0 logits `e0`."""
    from diagnostic_ar_training.ft.bundle import FtResidual, Knowledge, load_deltas
    from diagnostic_ar_training.ft.system import FtV1
    from diagnostic_ar_training.rerank import kb as kb_io

    knowledge = Knowledge(
        kb_io.read(kb_path), base.genes, (base.inputs.emb_index, base.inputs.vectors), kb_id
    )
    residual = FtResidual(bundle, knowledge, load_deltas(bundle, MODELS_DIR / deltas_exp))
    pooler = None
    if residual.needs_pooled:
        from diagnostic_ar_training.ft import replay as ft_replay
        from diagnostic_ar_training.gnn.model import load_v3

        v3 = load_v3(base.inputs.root, map_location="cpu")

        def pooler(case):
            return ft_replay.pooled_vectors(v3, base.inputs, [case.present], "cpu")[0]

    return FtV1(e0, residual, bundle_id, pooler)


@ft_app.command("prod-bundle")
def ft_prod_bundle(
    bundle_id: str = typer.Option(..., "--id", help="New immutable id, e.g. ft-v1.1-prod"),
    source: str = typer.Option(..., "--from", help="The fitted ft-bundle whose members (θ) are kept"),
    source_kb: str = typer.Option("ft-kb-all-v2", "--source-kb", help="The knowledge θ was fitted on"),
    kb_id: str = typer.Option(..., "--kb", help="The production knowledge, e.g. ft-kb-prod-v1"),
) -> None:
    """A fitted bundle's members, unchanged, on another knowledge: θ is not refitted.

    Writes data/ft/<id>/ft-v1-bundle.json with a manifest. The bundle records where θ came from.
    """
    from diagnostic_ar_training.ft import runs
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest

    if kb_id == source_kb:
        raise typer.BadParameter("--kb is the knowledge θ was fitted on: use the source bundle itself")
    ensure_new(bundle_id)
    state = _require_clean()
    bundle, source_path, source_exp = verified_bundle(source, source_kb)
    if any(m.get("classifier_delta") for m in bundle["members"]):
        raise typer.BadParameter(f"{source} has classifier deltas, which are per gene: not supported here")
    _, kb_sha = _kb_output(kb_id)
    source_sha = sha256_file(source_path)
    theta_source = {
        "bundle": source,
        "sha256": source_sha,
        "fitted_on_kb": source_kb,
        "exp": source_exp,
        "refit": False,
    }
    out = {**bundle, "kb_id": kb_id, "theta_source": theta_source}
    path = runs.write_json(DATA_DIR / "ft" / bundle_id / "ft-v1-bundle.json", out)
    inputs = [
        {"id": f"artifact:{source}", "sha256": source_sha},
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
    ]
    params = {"from": source, "theta_fitted_on": source_kb, "refit": False, "kb": kb_id}
    notes = f"θ of {source} (fitted on {source_kb}), unchanged; only the knowledge differs."
    write_manifest(build_manifest(bundle_id, "ft-bundle", inputs, params, [path], notes=notes, state=state))
    typer.echo(f"{bundle_id}: {len(bundle['members'])} members of {source} on {kb_id} -> {path}")


PARITY_TOLERANCE = 1e-9


@ft_app.command("prod-package")
def ft_prod_package(
    out: str = typer.Option(
        "dist/ft-v1.1-prod", "--out", help="Package directory; its ft_prod.py is committed"
    ),
    artifact_id: str = typer.Option("", "--id", help="Default: <out directory name>-package"),
    bundle_id: str = typer.Option("ft-v1.1-prod", "--bundle", help="The production ft-bundle"),
    kb_id: str = typer.Option("ft-kb-prod-v1", "--kb", help="Its knowledge"),
    evaluated_kb: str = typer.Option("ft-kb-all-v2", help="The evaluated knowledge, for the diff"),
    n_cases: int = typer.Option(200, help="r1-v1 dev cases in the parity fixture"),
    seed: int = typer.Option(0, help="Seed of the fixture's sample"),
) -> None:
    """Export an ft bundle for diagnostic.ar-model, check it on r1-v1 dev, and write its parity fixture.

    Writes <out>/ (the export `<name>-bundle.json.gz`, the fixture, SHA256SUMS; `ft_prod.py` there is
    committed code) and data/ft/<name>/package-report.json, with a manifest. θ comes from the bundle's
    `theta_source` (a `dxt ft prod-bundle` bundle) or from the bundle itself on its own knowledge (e.g. the
    confirmed `ft-v1.1-c1-lin-all-ens` on `ft-kb-all-v2`). Refuses to write anything if the standalone module
    differs from `FtV1` by more than 1e-9 on any dev or synthetic case. Free parts only: r1-v1 dev. The dev
    numbers are descriptive when the knowledge includes the dev papers.
    """
    import random
    import time

    import numpy as np

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.cohorts.schema import Sex
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.ft import evaluate as ft_eval
    from diagnostic_ar_training.ft import prod, runs
    from diagnostic_ar_training.ft.bundle import FtResidual, Knowledge, softmax64
    from diagnostic_ar_training.ft.system import E0Logits, E0System, FtV1, case_inputs
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    out_dir = (Path(out) if Path(out).is_absolute() else prod.REPO_ROOT / out).absolute()
    paths = prod.package_paths(out_dir)
    if not paths["module"].is_file():
        raise typer.BadParameter(f"{out} has no committed {paths['module'].name}: copy dist/ft-v1.1-prod's")
    artifact_id = artifact_id or f"{out_dir.name}-package"
    manifest.ensure_new(artifact_id)
    state = _require_clean()
    start = time.perf_counter()
    bundle, bundle_path, bundle_exp = verified_bundle(bundle_id, kb_id)
    source = prod.theta_source(bundle, bundle_id, sha256_file(bundle_path), bundle_exp)
    source_bundle, source_path, _ = verified_bundle(source["bundle"], source["fitted_on_kb"])
    kb_path, kb_sha = _kb_output(kb_id)
    old_path, old_sha = _kb_output(evaluated_kb)
    kb, old_kb = kb_io.read(kb_path), kb_io.read(old_path)
    standalone = prod.load_standalone(paths["module"])
    base = GenPheniaV3()
    genes = base.genes
    e0 = E0Logits(base)
    embeddings = (base.inputs.emb_index, base.inputs.vectors)
    kb_manifest = manifest.load_manifest(kb_id)
    provenance = {
        "model": bundle_id,
        "knowledge": {
            "id": kb_id,
            "sha256": kb_sha,
            "mask_scope": kb_manifest.params.get("mask_scope"),
            "inputs": {i.id: i.sha256 for i in kb_manifest.inputs},
        },
        "theta": {
            "bundle": source["bundle"],
            "sha256": source["sha256"],
            "fitted_on_kb": source["fitted_on_kb"],
            "exp": source.get("exp"),
            "refit": False,
            "production_bundle": bundle_id,
            "production_bundle_sha256": sha256_file(bundle_path),
        },
        "e0": base.lineage_inputs()[0],
        "code": {"repo": state.repo, "sha": state.sha},
        "decision": "docs/decisions/0018-ft-v11-production-ready.md",
    }
    exported = prod.export(bundle, kb, genes, provenance, standalone.FEATURES)
    model = standalone.FtProd(exported)
    _, dropped, _ = prod.split_features(bundle)

    full = FtV1(e0, FtResidual(bundle, Knowledge(kb, genes, embeddings, kb_id)), bundle_id)
    no_dropped = FtV1(
        e0, FtResidual(prod.without(bundle, dropped), Knowledge(kb, genes, None, kb_id)), "drop"
    )
    evaluated = FtV1(
        e0,
        FtResidual(source_bundle, Knowledge(old_kb, genes, embeddings, evaluated_kb)),
        source["bundle"],
    )
    dev_cases = splits.load_part(SPLIT, "dev", Purpose.EVAL)
    groups = splits.publication_groups(SPLIT)
    checks = {"dev_cases": len(dev_cases), "scorable": 0}
    worst = dict.fromkeys(
        (
            "drop_max_abs_dp",
            "ensemble_max_abs_dr",
            "standalone_logits_max_abs_dp",
            "standalone_log_probs_max_abs_dp",
            "standalone_probs_max_abs_dp",
        ),
        0.0,
    )
    lookup = {g.upper(): i for i, g in enumerate(genes)}

    def compare(case) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None:
        logits, _ = e0(case)
        if logits is None:
            return None
        inputs = case_inputs(case)
        expected = full.score(case).probs
        e0_probs = softmax64(logits)
        r_members = full.residual.residual(inputs)
        r_mean = model.residual(inputs)
        worst["drop_max_abs_dp"] = max(
            worst["drop_max_abs_dp"], float(np.abs(no_dropped.score(case).probs - expected).max())
        )
        worst["ensemble_max_abs_dr"] = max(
            worst["ensemble_max_abs_dr"], float(np.abs(r_members - r_mean).max())
        )
        for key, got in (
            ("standalone_logits_max_abs_dp", model.apply(logits, inputs)),
            ("standalone_log_probs_max_abs_dp", model.apply(np.log(e0_probs), inputs)),
            ("standalone_probs_max_abs_dp", model.apply_probs(e0_probs, inputs)),
        ):
            worst[key] = max(worst[key], float(np.abs(got - expected).max()))
        return logits, e0_probs, expected, r_mean

    scored = {}
    for case in dev_cases:
        out = compare(case)
        if out is not None:
            checks["scorable"] += 1
            if case.gene.upper() in lookup:
                scored[case.case_id] = (case, *out)
    sample = random.Random(seed).sample(sorted(scored), min(n_cases, len(scored)))
    cases = []
    for cid in sample:
        case, logits, e0_probs, expected, r = scored[cid]
        cases.append(
            prod.fixture_case(
                cid,
                "r1-v1-dev",
                case.gene,
                lookup[case.gene.upper()],
                case.present,
                case_inputs(case),
                logits,
                e0_probs,
                expected,
                int((r < 0).sum()),
            )
        )

    def top_negatable(e0_probs: np.ndarray) -> str | None:
        for i in np.argsort(-e0_probs, kind="stable")[:20]:
            if genes[i] in exported["obligate"]:
                return genes[i]
        return None

    anchor = next(cid for cid in sample if top_negatable(scored[cid][2]))
    anchor_case, anchor_logits, anchor_probs = scored[anchor][:3]
    target = top_negatable(anchor_probs)
    negating = sorted({terms[0] for terms in exported["obligate"][target].values()})
    unknown = "HP:9999999"
    synthetic = {
        "no-inputs": {"sex": None, "age_years": None, "onset_years": None, "excluded": []},
        "unknown-sex": {"sex": "unknown", "age_years": 30.0, "onset_years": None, "excluded": []},
        "negative-age": {"sex": "female", "age_years": -2.0, "onset_years": None, "excluded": []},
        "negative-onset": {"sex": "male", "age_years": 12.0, "onset_years": -0.5, "excluded": []},
        "only-excluded": {
            "sex": None,
            "age_years": None,
            "onset_years": None,
            "excluded": [*negating, unknown],
        },
        "only-unknown-excluded": {"sex": None, "age_years": None, "onset_years": None, "excluded": [unknown]},
        "all-inputs": {"sex": "female", "age_years": 40.0, "onset_years": 30.0, "excluded": negating},
    }
    for name, inputs in synthetic.items():
        sex = Sex(inputs["sex"]) if inputs["sex"] in ("male", "female") else Sex.UNKNOWN
        case = anchor_case.model_copy(
            update={
                "sex": sex,
                "age_years": inputs["age_years"],
                "onset_years": inputs["onset_years"],
                "excluded": tuple(inputs["excluded"]),
            }
        )
        _, _, expected, r = compare(case)
        cases.append(
            prod.fixture_case(
                f"synthetic:{name}",
                "synthetic",
                anchor_case.gene,
                lookup[anchor_case.gene.upper()],
                anchor_case.present,
                inputs,
                anchor_logits,
                anchor_probs,
                expected,
                int((r < 0).sum()),
            )
        )
    identity = model.apply(anchor_logits, synthetic["no-inputs"])
    checks["no_inputs_bit_identical_to_e0"] = bool(np.array_equal(identity, softmax64(anchor_logits)))
    checks["no_inputs_apply_probs_returns_input"] = model.apply_probs(anchor_probs, {}) is anchor_probs
    checks["parity_cases"] = len(cases)
    checks |= worst
    checks["tolerance"] = PARITY_TOLERANCE
    parity = max(v for k, v in worst.items() if k.startswith("standalone_"))
    checks["valid"] = bool(
        parity <= PARITY_TOLERANCE
        and worst["drop_max_abs_dp"] == 0.0
        and worst["ensemble_max_abs_dr"] <= 1e-12
        and checks["no_inputs_bit_identical_to_e0"]
        and checks["no_inputs_apply_probs_returns_input"]
    )
    if not checks["valid"]:
        raise LineageError(f"package checks failed, nothing written: {json.dumps(checks)}")

    e0_dev = harness.run(E0System(e0), dev_cases, "all", groups)
    prod_dev = harness.run(full, dev_cases, "all", groups)
    evaluated_dev = harness.run(evaluated, dev_cases, "all", groups)
    by_id = {c.case_id: c for c in dev_cases}
    artefact = [
        {
            "case_id": a["case_id"],
            "gene": a["gene"],
            "rank_e0": a["rank"],
            f"rank_{source['bundle']}": b["rank"],
            f"rank_{bundle_id}": c["rank"],
        }
        for a, b, c in zip(e0_dev, evaluated_dev, prod_dev, strict=True)
        if a["gene"].upper() in prod.ARTEFACT_GENES and by_id[a["case_id"]].sex == Sex.FEMALE
    ]
    sanity = {
        "note": (
            f"Descriptive only, not a claim: {kb_id} includes the dev papers' annotations, so dev patients "
            "can see knowledge curated from their own publication."
        ),
        bundle_id: ft_eval.report(e0_dev, prod_dev, dev_cases),
        f"{source['bundle']} (evaluated, {evaluated_kb})": ft_eval.report(e0_dev, evaluated_dev, dev_cases),
        "female_artefact_gene_cases": artefact,
    }

    module_path, export_path, fixture_path = paths["module"], paths["bundle"], paths["fixture"]
    kb_io.write(exported, export_path)
    export_sha = sha256_file(export_path)
    fixture = {
        "format": prod.FIXTURE_FORMAT,
        "bundle": {"file": export_path.name, "sha256": export_sha},
        "module": {"file": module_path.name, "sha256": sha256_file(module_path)},
        "tolerance": PARITY_TOLERANCE,
        "selection": (
            f"{len(sample)} scorable r1-v1 dev cases whose gene is in E0's vocabulary, "
            f"random.Random({seed}).sample over the sorted case ids; then synthetic edge cases on the "
            f"logits and present terms of {anchor} (excluded terms: an obligate phenotype per disease of "
            f"{target}, E0's top negatable gene there, and the unknown id {unknown})"
        ),
        "expected": f"FtV1 (diagnostic_ar_training.ft.system) with {bundle_id} on {kb_id}, code {state.sha}",
        "cases": cases,
    }
    kb_io.write(fixture, fixture_path)
    sums = paths["sums"]
    sums.write_text(
        "".join(f"{sha256_file(p)}  {p.name}\n" for p in (module_path, export_path, fixture_path))
    )
    report = {
        "artifact_id": artifact_id,
        "bundle": bundle_id,
        "kb": kb_id,
        "code": state.as_dict(),
        "files": {
            p.name: {
                "path": str(p.relative_to(prod.REPO_ROOT)),
                "sha256": sha256_file(p),
                "bytes": p.stat().st_size,
            }
            for p in (module_path, export_path, fixture_path)
        },
        "features": exported["features"],
        "theta": dict(zip(exported["features"], exported["theta"], strict=True)),
        "dropped_features": dropped,
        "checks": checks,
        "kb_diff": {"from": evaluated_kb, "to": kb_id, **prod.kb_diff(old_kb, kb, genes)},
        "dev_sanity": sanity,
        "run_seconds": runs.elapsed(start),
    }
    report_path = runs.write_json(paths["report"], report)
    inputs = [
        *base.lineage_inputs(),
        {"id": f"artifact:{bundle_id}", "sha256": sha256_file(bundle_path)},
        {"id": f"artifact:{source['bundle']}", "sha256": sha256_file(source_path)},
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        {"id": f"artifact:{evaluated_kb}", "sha256": old_sha},
        {"id": f"split:{SPLIT}", "sha256": sha256_file(SPLITS_DIR / f"{SPLIT}.json")},
        {"id": f"code:{module_path.relative_to(prod.REPO_ROOT)}", "sha256": sha256_file(module_path)},
    ]
    params = {
        "bundle": bundle_id,
        "kb": kb_id,
        "evaluated_kb": evaluated_kb,
        "format": prod.FORMAT,
        "fixture_format": prod.FIXTURE_FORMAT,
        "n_cases": n_cases,
        "seed": seed,
        "tolerance": PARITY_TOLERANCE,
        "part": f"{SPLIT}/dev",
    }
    outputs = [export_path, fixture_path, sums, report_path]
    manifest.write_manifest(
        manifest.build_manifest(artifact_id, "ft-prod-package", inputs, params, outputs, state=state)
    )
    typer.echo(json.dumps(checks, indent=1))
    typer.echo(ft_eval.line(f"{bundle_id} dev (descriptive)", sanity[bundle_id]["vs_e0"]))
    typer.echo(
        ft_eval.line(
            f"{source['bundle']} dev", sanity[f"{source['bundle']} (evaluated, {evaluated_kb})"]["vs_e0"]
        )
    )
    for p in outputs:
        typer.echo(f"{sha256_file(p)}  {p.stat().st_size:>9}  {p.relative_to(prod.REPO_ROOT)}")


@ft_app.command("confirm")
def ft_confirm(
    exp: str = typer.Option(..., help="Pre-registered experiment id"),
    split: list[str] = typer.Option(..., help="p2-v1 for test; p2-v1 and p2-fresh-v1 together for vault"),
    part: str = typer.Option(..., help="test (confirmation) or vault (final check, opens once)"),
    bundle_id: str = typer.Option(..., "--bundle", help="The ft-bundle artifact the pre-registration names"),
    kb_id: str = typer.Option(
        "ft-kb-all-v2", "--kb", help="The knowledge artifact the pre-registration names"
    ),
    reason: str = typer.Option("", help="Required"),
) -> None:
    """The sealed read of an ft-v1 bundle vs E0.

    `DXT_SEALED_READ=<exp> dxt ft confirm --exp <exp> --split p2-v1 --part test --bundle <id> --reason ...`.
    Refusals come in `safe_eval.preflight`'s order, before any data is loaded or the ledger touched.
    """
    from diagnostic_ar_training.eval import safe_eval

    try:
        safe_eval.preflight(exp, split, part, reason)
    except (ValueError, LineageError) as e:
        raise typer.BadParameter(str(e)) from e

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.ft import evaluate as ft_eval
    from diagnostic_ar_training.ft import runs
    from diagnostic_ar_training.ft.system import E0Logits, E0System
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    label = "+".join(split) + f"-{part}"
    artifact_id = f"results-{exp}-{label}-{bundle_id}"
    manifest.ensure_new(artifact_id)
    state = code_state()
    bundle, bundle_path, bundle_exp = verified_bundle(bundle_id, kb_id)
    kb_path, kb_sha = _kb_output(kb_id)
    base = GenPheniaV3()
    e0 = E0Logits(base)
    system = ft_system(base, e0, bundle, bundle_id, kb_path, kb_id, bundle_exp or exp)
    by_split = {}
    for split_id in split:
        groups = splits.publication_groups(split_id)
        cases = splits.load_part(split_id, part, Purpose.EVAL, exp, reason)
        by_split[split_id] = (cases, {c.case_id: f"{split_id}:{groups[c.case_id]}" for c in cases})
    cases = [c for cs, _ in by_split.values() for c in cs]
    groups = {k: v for _, g in by_split.values() for k, v in g.items()}
    e0_records = harness.run(E0System(e0), cases, "all", groups)
    records = harness.run(system, cases, "all", groups)
    report = ft_eval.report(e0_records, records, cases)
    if len(by_split) > 1:
        report["components"] = {
            s: ft_eval.report(
                [r for r in e0_records if r["case_id"] in {c.case_id for c in cs}],
                [r for r in records if r["case_id"] in {c.case_id for c in cs}],
                cs,
            )
            for s, (cs, _) in by_split.items()
        }
    report |= {"cohort": label, "bundle": bundle_id, "kb": kb_id, "code_sha": state.sha, "reason": reason}
    out_dir = RESULTS_DIR / exp / f"{label}-{bundle_id}"
    outputs = [
        runs.write_json(out_dir / "report.json", report),
        runs.write_compact_ranks(out_dir / "E0.ranks.jsonl", e0_records),
        runs.write_compact_ranks(out_dir / f"{bundle_id}.ranks.jsonl", records),
    ]
    inputs = [
        *base.lineage_inputs(),
        {"id": f"artifact:{bundle_id}", "sha256": sha256_file(bundle_path)},
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        *({"id": f"split:{s}", "sha256": sha256_file(SPLITS_DIR / f"{s}.json")} for s in split),
    ]
    params = {"exp": exp, "splits": list(split), "part": part, "bundle": bundle_id, "kb": kb_id}
    manifest.write_manifest(
        manifest.build_manifest(artifact_id, "ft-confirm", inputs, params, outputs, state=state)
    )
    typer.echo(ft_eval.line(label, report["vs_e0"]))
    typer.echo(f"-> {out_dir} (manifest {artifact_id})")
