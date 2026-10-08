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
) -> None:
    """Build the ft-v1 knowledge with every r1-v1 PMID masked (train, dev, test and vault)."""
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
    splits.write_mask(MASK_SPLIT, MASK_SCOPE)  # refuses if the committed list drifted from the split
    mask_path = splits.mask_path(MASK_SPLIT, MASK_SCOPE)
    ontology = Ontology.from_json(paths["hpo_ontology"])
    built, stats = ft_knowledge.build(
        vocabulary,
        knowledge.read_genes_to_disease(paths["hpo_genes_to_disease"]),
        knowledge.read_annotations(paths["hpo_annotations"], mask_path.read_text().split()),
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
    inputs.append({"id": f"{MASK_SCOPE}-pmids:{MASK_SPLIT}", "sha256": sha256_file(mask_path)})
    if overrides:
        inputs.append({"id": f"overrides:{overrides}", "sha256": sha256_file(Path(overrides))})
    params = {
        "schema": ft_knowledge.SCHEMA,
        "vocabulary": "E0 (genphenia_v3) genes",
        "mask_split": MASK_SPLIT,
        "mask_scope": MASK_SCOPE,
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
