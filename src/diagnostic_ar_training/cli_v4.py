"""`dxt v4 …`: Phase 3 training and evaluation harness for GenPhenAI v4.0 (ADR-0019, docs/PHASE3.md)."""

import json
from pathlib import Path

import typer

v4_app = typer.Typer(no_args_is_help=True, help="Phase 3: v4.0 training, evaluation and grids (ADR-0019).")


def _context(device: str):
    from diagnostic_ar_training.v4.runs import Context

    return Context(device)


def _free_gpu() -> None:
    import gc

    import torch

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


@v4_app.command("train")
def v4_train(
    config: str = typer.Option(..., "--config", help="Run configuration YAML (configs/p3/R*.yaml)"),
    seed: int | None = typer.Option(None, help="Override the configuration's seed"),
    force: bool = typer.Option(False, help="Retrain even when the results row says complete"),
    allow_dirty: bool = typer.Option(False, help="Allow uncommitted code (scratch runs only)"),
    device: str = typer.Option("cuda"),
) -> None:
    """Train one configuration (resuming from its last.pt), then read its best and final checkpoints vs E0."""
    from diagnostic_ar_training.v4 import config as v4config
    from diagnostic_ar_training.v4 import runs

    cfg = v4config.load(config)
    if seed is not None:
        cfg = v4config.with_seed(cfg, seed)
    typer.echo(f"run {cfg.run_id} -> {runs.run_dir(cfg.run_id)}")
    row = runs.train_run(cfg, _context(device), force=force, require_clean=not allow_dirty, log=typer.echo)
    typer.echo(json.dumps(row.get("select", {}).get("primary"), indent=1))


@v4_app.command("eval")
def v4_eval(
    run: str = typer.Option(..., "--run", help="Run id under data/interim/v4/, or R0 for E0 as released"),
    checkpoint: str = typer.Option("best", help="best (chosen on SELECT) or last (the final checkpoint)"),
    swap: bool = typer.Option(
        False, help="Phenotype-swap control: each patient scored with another's phenotype"
    ),
    device: str = typer.Option("cuda"),
) -> None:
    """Score a run's checkpoint (or E0 for R0) on SELECT and FIT; ranks, summary, results row."""
    from diagnostic_ar_training.v4 import runs

    if checkpoint not in runs.CHECKPOINTS:
        raise typer.BadParameter(f"one of {runs.CHECKPOINTS}", param_hint="--checkpoint")
    ctx = _context(device)
    if run == runs.E0_RUN:
        if checkpoint != "best":
            raise typer.BadParameter("R0 is E0 as released: it has no checkpoints", param_hint="--checkpoint")
        row = runs.eval_e0(ctx, typer.echo, swap)
        key = "swap" if swap else None
    else:
        row = runs.evaluate_run(run, ctx, typer.echo, checkpoint, swap)
        key = runs.section(checkpoint, swap)
    typer.echo(json.dumps((row[key] if key else row)["select"]["primary"], indent=1))


@v4_app.command("grid")
def v4_grid(
    spec: str = typer.Option(..., "--spec", help="Grid spec YAML (configs/p3/R8-grid.yaml)"),
    minutes: float | None = typer.Option(None, help="Override the spec's total_minutes for this invocation"),
    allow_dirty: bool = typer.Option(False, help="Allow uncommitted code (scratch runs only)"),
    device: str = typer.Option("cuda"),
) -> None:
    """Run every configuration and seed of a grid in sequence; completed runs are skipped (resumable)."""
    from diagnostic_ar_training.v4 import grid, runs

    ctx = _context(device)
    table = grid.run_grid(
        grid.load_spec(spec),
        lambda cfg: runs.train_run(cfg, ctx, require_clean=not allow_dirty, log=typer.echo),
        total_minutes=minutes,
        log=typer.echo,
        after_run=_free_gpu,
    )
    for row in table:
        typer.echo(f"{row['run_id']:<32} seed {row['seed']} {row['status']:<15} {row.get('primary')}")


@v4_app.command("throughput")
def v4_throughput(
    config: str = typer.Option(..., "--config"),
    workers: str = typer.Option("4,8,12,14", help="Worker counts to time for the loader alone"),
    batch_sizes: str = typer.Option("128,256,512", help="Batch sizes to time full training steps"),
    seconds: float = typer.Option(30.0, help="Seconds per measurement"),
    device: str = typer.Option("cuda"),
) -> None:
    """Graphs/s of simulated batches: loader alone per worker count, and full GPU training steps."""
    import torch

    from diagnostic_ar_training.v4 import config as v4config
    from diagnostic_ar_training.v4 import data, model, runs, samplers, throughput

    cfg = v4config.load(config)
    ctx = _context(device)
    sampler = samplers.build(cfg.sim)
    samplers.check_genes(sampler, ctx.genes)
    pool = samplers.gene_pool(sampler, cfg.encoding.drop_dash)
    tables = ctx.tables(cfg.encoding.ic_feature)
    out = {"run_config": cfg.run_id, "loader": [], "train": []}
    for w in (int(x) for x in workers.split(",")):
        stream = data.TrainStream(sampler, ctx.builder, pool, cfg.train.batch_size, cfg.seed)
        out["loader"].append(throughput.loader_rate(stream, w, seconds))
        typer.echo(json.dumps(out["loader"][-1]))
    for b in (int(x) for x in batch_sizes.split(",")):
        c = v4config.override(cfg, {"train.batch_size": b})
        e0 = ctx.e0_weights() if c.arch.init == "e0" else None
        weights, _ = runs.run_weights(c.arch)
        net = model.build(c.arch, c.encoding, e0, len(ctx.genes), ctx.inputs.dim, weights).to(ctx.device)
        stream = data.TrainStream(
            sampler, ctx.builder, pool, b, c.seed, with_covariates=c.encoding.covariates
        )
        out["train"].append(throughput.train_rate(c, net, stream, tables, ctx.device, seconds))
        typer.echo(json.dumps(out["train"][-1]))
        del net
        torch.cuda.empty_cache()
    typer.echo(json.dumps(out, indent=1))


def _release_state(scratch: str, artifact_id: str):
    """The code state of a release command: clean and with a new artifact id, unless it writes to scratch."""
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if not scratch:
        manifest.ensure_new(artifact_id)
        if state.dirty:
            raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    return state


@v4_app.command("release-network")
def v4_release_network(
    artifact_id: str = typer.Option("genphenia-v4.0-b2", "--id", help="Lineage id of the bundle"),
    scratch: str = typer.Option("", help="Write everything under this directory instead, with no manifest"),
    packer: str = typer.Option("", help="Default: diagnostic.ar-model's scripts/package_bundle.sh"),
    engine_dir: str = typer.Option("", "--engine", help="Default: diagnostic.ar-model's vendored engine"),
    mapping_patients: int = typer.Option(200, help="Patients for the GinV4 vs GinV3 bit-for-bit check"),
    device: str = typer.Option("cuda"),
) -> None:
    """F3's network as `genphenia-v4.0`: E0's bundle with model.onnx and best_model.pt replaced, then checked.

    Exports `R5x-f4-ef2f309462`'s last.pt (frozen sha256) in E0's layout with `gnn.export.export_v3` and as
    E0's checkpoint, then on every patient of p3-v1 train folds 0-3 (`patients.load_addon`) compares the torch
    network's logits with the ONNX through `systems.genphenia_v3` and through diagnostic.ar-model's vendored
    engine run on the packed tarball, and with the engine's own torch model loaded from best_model.pt. It also
    lets the engine rebuild a deleted model.onnx from best_model.pt (scratch copy) and records the outcome,
    and whether the engine accepts model_version "4.0". Writes dist/genphenia-v4.0/ (the bundle directory and
    the tarball, ignored by git; the .sha256 and MANIFEST.json), results/P4/release/genphenia-v4.0-parity.json
    and a manifest, whose outputs leave the tarball out so `dxt lineage verify` passes without the asset.
    """
    import tarfile
    import tempfile
    import time

    import numpy as np
    import torch

    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.ft import runs as ft_runs
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.registry import LineageError, Purpose, load_sources, open_source
    from diagnostic_ar_training.systems.genphenia_v3 import SOURCE, GenPheniaV3
    from diagnostic_ar_training.v4 import patients, release

    state = _release_state(scratch, artifact_id)
    start = time.perf_counter()
    out_dir = Path(scratch) / release.BUNDLE if scratch else release.NETWORK_DIST
    report_dir = Path(scratch) if scratch else RESULTS_DIR / "P4" / "release"
    report_path = report_dir / f"{release.BUNDLE}-parity.json"
    ctx = _context(device)
    net, cfg = release.frozen_network(ctx)
    e0_tarball = open_source(SOURCE, Purpose.BASELINE)
    bundle_dir = release.build_bundle(e0_tarball, release.to_ginv3(net), out_dir)
    onnx_file, checkpoint_file = release.onnx_path(bundle_dir), release.checkpoint_path(bundle_dir)
    packer_path = Path(packer) if packer else release.PACKER
    tarball, sha_file = release.pack(bundle_dir, out_dir, packer_path)
    e0_source = load_sources()[SOURCE]
    with tempfile.TemporaryDirectory() as tmp:
        e0_copy = release.extract_e0(e0_tarball, Path(tmp) / "bundle", release.E0_BUNDLE)
        e0_repacked = sha256_file(release.pack(e0_copy, Path(tmp) / "out", packer_path)[0])
    if e0_repacked != e0_source.sha256:
        raise LineageError(f"the packer turns E0's own files into {e0_repacked}, not {e0_source.sha256}")

    members = patients.load_addon(release.TRAINED_ON)
    torch_scores = release.torch_logits(net, cfg, ctx, members)
    onnx_system = GenPheniaV3(bundle_dir)
    mapping = release.mapping_check(net, members, onnx_system, mapping_patients)
    del net
    _free_gpu()
    engine_cls = release.vendored_engine(Path(engine_dir) if engine_dir else release.ENGINE)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(tarball) as archive:
            archive.extractall(tmp, filter="data")
        engine = engine_cls.load(Path(tmp) / release.BUNDLE, auto_refresh_seconds=1e9)
        health = engine.health()
        if tuple(engine.genes) != onnx_system.genes:
            raise typer.BadParameter("the engine's gene order differs from E0's")
        parity = release.network_parity(members, torch_scores, onnx_system, engine, onnx_system.genes)
        engine_path = Path(engine_dir) if engine_dir else release.ENGINE
        adapter = release.engine_model(Path(tmp) / release.BUNDLE, engine_path)
        with torch.inference_mode():
            parity["engine_model_from_best_model_pt"] = release.logits_parity(
                members,
                torch_scores,
                onnx_system,
                lambda x, e: adapter(torch.from_numpy(x), torch.from_numpy(e)).numpy(),
                onnx_system.genes,
            )
    parity["ginv4_vs_ginv3"] = mapping
    parity["engine_health"] = {k: health[k] for k in ("model_version", "out_channels", "in_channels")}
    with tempfile.TemporaryDirectory() as tmp:
        rebuilt, error = release.engine_reexport(engine_cls, tarball, Path(tmp))
        reexport = {"rebuilt": rebuilt is not None, "error": error}
        if rebuilt is not None:
            again = GenPheniaV3(rebuilt)

            def run(x, e):
                feeds = {"x": x, "edge_index": e, "batch": np.zeros(len(x), dtype=np.int64)}
                return again.session.run(None, {k: v for k, v in feeds.items() if k in again.input_names})[0]

            reexport |= release.logits_parity(members, torch_scores, onnx_system, run, onnx_system.genes)
    parity["engine_reexport_from_best_model_pt"] = reexport
    version_error = release.engine_version_error(release.VERSION)

    summary = {
        "bundle": release.BUNDLE,
        "network": {
            "run": release.NETWORK,
            "checkpoint": "last.pt",
            "sha256": release.FROZEN_SHA256[release.NETWORK],
            "trained_on": f"{patients.SPLIT} train folds {list(release.TRAINED_ON)} + sim4 (ADR-0019)",
        },
        "base": {"source": SOURCE, "version": e0_source.version, "tarball_sha256": e0_source.sha256},
        "changed_from_base": [str(p.relative_to(bundle_dir)) for p in (onnx_file, checkpoint_file)],
        "model_version": {
            "spec_json": release.spec_of(bundle_dir)["model_version"],
            "best_model_pt": release.VERSION,
            "why_spec_json_stays": (
                "the vendored engine reads spec.json's model_version as the architecture and rejects others: "
                f"{version_error}"
            )
            if version_error
            else None,
        },
        "packer": {"script": "diagnostic.ar-model scripts/package_bundle.sh", "repacks_base_exactly": True},
        "model_onnx": {"sha256": sha256_file(onnx_file), "bytes": onnx_file.stat().st_size},
        "best_model_pt": {
            "sha256": sha256_file(checkpoint_file),
            "bytes": checkpoint_file.stat().st_size,
            "layout": "E0's: {model_version, model_state_dict (GinV3 / PyG keys), source_run, ...}",
        },
        "tarball": {"file": tarball.name, "sha256": sha256_file(tarball), "bytes": tarball.stat().st_size},
        "export": {"code": "gnn.export.export_v3", "repo": state.repo, "sha": state.sha},
        "parity_patients": f"{patients.SPLIT} train folds {list(release.TRAINED_ON)}, every patient",
        "parity": {k: v for k, v in parity.items() if k != "rank_differs"},
        "rank_differs": parity["rank_differs"],
        "decision": "docs/decisions/0020-v4-validated-and-next.md",
    }
    manifest_file = ft_runs.write_json(out_dir / "MANIFEST.json", summary)
    report = ft_runs.write_json(report_path, {**summary, "run_seconds": ft_runs.elapsed(start)})
    if not scratch:
        inputs = [
            e0_source.as_input(),
            {"id": f"artifact:{release.NETWORK}/last.pt", "sha256": release.FROZEN_SHA256[release.NETWORK]},
        ]
        params = {"network": release.NETWORK, "checkpoint": "last", "folds": list(release.TRAINED_ON)}
        outputs = [sha_file, manifest_file, report]
        notes = (
            f"The tarball dist/{release.BUNDLE}/{tarball.name} (sha256 in {sha_file.name}) and its unpacked "
            "directory are release assets (ADR-0005), ignored by git. Supersedes genphenia-v4.0 (build 1, "
            "never published), whose best_model.pt was still E0's."
        )
        manifest.write_manifest(
            manifest.build_manifest(
                artifact_id, "release-bundle", inputs, params, outputs, notes=notes, state=state
            )
        )
    typer.echo(json.dumps(summary["parity"], indent=1))
    typer.echo(f"{summary['tarball']['sha256']}  {tarball}")


@v4_app.command("release-layer")
def v4_release_layer(
    artifact_id: str = typer.Option("v4-layer-package", "--id", help="Lineage id of the package"),
    scratch: str = typer.Option("", help="Write everything under this directory instead, with no manifest"),
    bundle_dir: str = typer.Option("", "--bundle-dir", help="Default: dist/genphenia-v4.0/genphenia-v4.0"),
    n_cases: int = typer.Option(10, help="Fixture patients of each kind (sex rule, add-on, other)"),
    seed: int = typer.Option(0, help="Seed of the fixture's sample"),
    device: str = typer.Option("cuda"),
) -> None:
    """F3's add-on and hard sex rule as the numpy package dist/v4-layer/, checked against the research F3.

    Exports `p3-addon-v1-all` (without its θ = 0 features) on `p3-addon-kb-v1` and `sex-kb-v3`, every sha256
    frozen, for `dist/v4-layer/v4_layer.py` (committed code). On every patient of p3-v1 train folds 0-3 it
    checks, on the torch network's logits, that the package's scores equal the research F3's (`v4.addon.Addon`
    then `v4.sexrule.SexRule`) and give the same ranks, and that dropping the θ = 0 features changes nothing;
    on `genphenia-v4.0`'s ONNX logits, the end-to-end ranks. Refuses to write anything if a check fails.
    Writes the bundle, the staging fixture (expected top genes of the network and of F3 through production's
    runtime) and SHA256SUMS under dist/v4-layer/, results/P4/release/v4-layer-parity.json and a manifest.
    """
    import time

    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.ft import prod
    from diagnostic_ar_training.ft import runs as ft_runs
    from diagnostic_ar_training.ft.bundle import Knowledge, softmax64
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.registry import LineageError
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3
    from diagnostic_ar_training.v4 import addon, patients, release, sexrule

    state = _release_state(scratch, artifact_id)
    start = time.perf_counter()
    out_dir = Path(scratch) if scratch else release.LAYER_DIST
    report_path = (Path(scratch) if scratch else RESULTS_DIR / "P4" / "release") / "v4-layer-parity.json"
    network_dir = Path(bundle_dir) if bundle_dir else release.NETWORK_DIST / release.BUNDLE
    network_manifest = json.loads((network_dir.parent / "MANIFEST.json").read_text())
    onnx_sha = sha256_file(release.onnx_path(network_dir))
    if onnx_sha != network_manifest["model_onnx"]["sha256"]:
        raise LineageError(f"{network_dir}: model.onnx differs from its MANIFEST.json")
    bundle, kb, sex_kb, shas = release.frozen_layer()
    standalone = release.load_standalone()
    e0 = GenPheniaV3()
    genes = e0.genes
    dropped_features = release.zero_features(bundle)
    embeddings = (e0.inputs.emb_index, e0.inputs.vectors)
    full = addon.Addon(bundle, Knowledge(kb, genes, embeddings, release.ADDON_KB))
    no_zero = prod.without(bundle, dropped_features)
    dropped = addon.Addon(no_zero, Knowledge(kb, genes, None, release.ADDON_KB))
    rule = sexrule.SexRule(sexrule.limits(sex_kb), genes)
    provenance = {
        "network": {"run": release.NETWORK, "last_pt_sha256": release.FROZEN_SHA256[release.NETWORK]},
        "network_bundle": {"id": release.BUNDLE, "model_onnx_sha256": onnx_sha},
        "addon": {"bundle": release.ADDON, "sha256": shas[release.ADDON]},
        "addon_knowledge": {"id": release.ADDON_KB, "sha256": shas[release.ADDON_KB]},
        "sex_rule_knowledge": {"id": release.SEX_KB, "sha256": shas[release.SEX_KB]},
        "gene_order": "E0's genes.json (genphenia-v3.0 and genphenia-v4.0)",
        "code": {"repo": state.repo, "sha": state.sha},
        "decision": "docs/decisions/0020-v4-validated-and-next.md",
    }
    exported = release.export_layer(bundle, kb, sex_kb, genes, provenance, standalone.FEATURES)
    layer = standalone.V4Layer(exported)

    members = patients.load_addon(release.TRAINED_ON)
    ctx = _context(device)
    net, cfg = release.frozen_network(ctx)
    torch_scores = release.torch_logits(net, cfg, ctx, members)
    del net
    _free_gpu()
    network = GenPheniaV3(network_dir)
    onnx_scores = {}
    for p in members:
        known, _ = network.inputs.known_present(p.case)
        if known and p.case_id in torch_scores:
            onnx_scores[p.case_id] = network.logits(known)[0]
    checks, kept = release.layer_parity(members, torch_scores, onnx_scores, full, dropped, rule, layer, genes)
    del torch_scores
    n = checks["patients"]
    checks["valid"] = bool(
        checks["dropped_equals_full"] == n
        and checks["scores_bit_identical"] == n
        and checks["no_inputs_is_softmax"] == n
        and checks["rank_identical_scores"] == checks["in_vocab"]
        and checks["rank_identical_probs"] == checks["in_vocab"]
    )
    if not checks["valid"]:
        raise LineageError(f"package checks failed, nothing written: {json.dumps(checks)}")

    lookup = {g.upper(): i for i, g in enumerate(genes)}
    by_id = {p.case_id: p for p in members}
    cases = []
    for case_id, kind, inputs in release.select_fixture(members, kept, layer, genes, n_cases, seed):
        p, z = by_id[case_id], kept[case_id]["onnx"]
        net_probs, f3_probs = softmax64(z), layer.apply(z, inputs)
        idx = lookup[p.case.gene.upper()]
        hpo_ids, _ = network.inputs.known_present(p.case)
        cases.append(
            release.fixture_case(
                case_id,
                kind,
                p.case.gene,
                hpo_ids,
                inputs,
                genes,
                net_probs,
                f3_probs,
                int(addon.rank(net_probs, idx)),
                int(addon.rank(f3_probs, idx)),
            )
        )
    module_path, bundle_path = release.STANDALONE, out_dir / release.LAYER_FILE
    fixture_path, sums = out_dir / release.FIXTURE_FILE, out_dir / "SHA256SUMS"
    kb_io.write(exported, bundle_path)
    if standalone.load(bundle_path) != json.loads(json.dumps(exported)):
        raise LineageError("the written bundle does not read back as exported")
    fixture = {
        "format": release.FIXTURE_FORMAT,
        "network": {"bundle": release.BUNDLE, "model_onnx_sha256": onnx_sha},
        "layer": {"file": bundle_path.name, "sha256": sha256_file(bundle_path)},
        "module": {"file": module_path.name, "sha256": sha256_file(module_path)},
        "tolerance": {"top_genes": "same genes in the same order", "probability_abs": 2e-6},
        "selection": (
            f"{patients.SPLIT} train folds {list(release.TRAINED_ON)} (the network was fine-tuned on these "
            f"patients: a parity fixture, not an evaluation), in-vocabulary and scorable, "
            f"random.Random({seed}).sample over sorted case ids: up to {n_cases} whose sex rule blocks a "
            f"gene of the network's top {release.TOP}, {n_cases} whose top {release.TOP} the add-on changes, "
            f"{n_cases} others; then 3 of the first two kinds with no input (F3 = the network)"
        ),
        "expected": (
            f"genphenia-v4.0's model.onnx through systems.genphenia_v3 (production's graph and softmax), "
            f"then v4_layer.py; code {state.sha}"
        ),
        "cases": cases,
    }
    ft_runs.write_json(fixture_path, fixture)
    release.write_sums([module_path, bundle_path, fixture_path], sums)
    report = {
        "artifact_id": artifact_id,
        "files": {
            p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
            for p in (module_path, bundle_path, fixture_path)
        },
        "features": exported["addon"]["features"],
        "theta": exported["addon"]["theta"],
        "dropped_features": dropped_features,
        "sex_rule": {k: len(v) for k, v in exported["sex_rule"].items()},
        "checks": checks,
        "fixture_kinds": {k: sum(c["kind"] == k for c in cases) for k in {c["kind"] for c in cases}},
        "provenance": provenance,
        "run_seconds": ft_runs.elapsed(start),
    }
    report_file = ft_runs.write_json(report_path, report)
    if not scratch:
        inputs = [
            *e0.lineage_inputs(),
            {"id": f"artifact:{release.BUNDLE}/model.onnx", "sha256": onnx_sha},
            *({"id": f"artifact:{k}", "sha256": v} for k, v in shas.items()),
            {"id": f"code:{module_path.relative_to(release.REPO_ROOT)}", "sha256": sha256_file(module_path)},
        ]
        params = {"format": release.FORMAT, "fixture_format": release.FIXTURE_FORMAT, "n_cases": n_cases}
        params |= {"seed": seed, "folds": list(release.TRAINED_ON)}
        outputs = [bundle_path, fixture_path, sums, report_file]
        manifest.write_manifest(
            manifest.build_manifest(artifact_id, "release-layer", inputs, params, outputs, state=state)
        )
    typer.echo(json.dumps({k: v for k, v in checks.items() if k != "rank_differs"}, indent=1))
    for p in (module_path, bundle_path, fixture_path):
        typer.echo(f"{sha256_file(p)}  {p.stat().st_size:>9}  {p}")
