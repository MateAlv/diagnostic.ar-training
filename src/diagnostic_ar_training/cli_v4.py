"""`dxt v4 …`: Phase 3 training and evaluation harness for GenPhenAI v4.0 (ADR-0019, docs/PHASE3.md)."""

import json

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
    """Train one configuration (resuming from its last.pt), then evaluate its best checkpoint vs E0."""
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
    device: str = typer.Option("cuda"),
) -> None:
    """Score a run's best checkpoint (or E0 for R0) on SELECT and FIT; ranks, summary, results row."""
    from diagnostic_ar_training.v4 import runs

    ctx = _context(device)
    row = runs.eval_e0(ctx, typer.echo) if run == runs.E0_RUN else runs.evaluate_run(run, ctx, typer.echo)
    typer.echo(json.dumps(row["select"]["primary"], indent=1))


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
    from diagnostic_ar_training.v4 import data, model, samplers, throughput

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
        net = model.build(c.arch, c.encoding, e0, len(ctx.genes), ctx.inputs.dim).to(ctx.device)
        stream = data.TrainStream(
            sampler, ctx.builder, pool, b, c.seed, with_covariates=c.encoding.covariates
        )
        out["train"].append(throughput.train_rate(c, net, stream, tables, ctx.device, seconds))
        typer.echo(json.dumps(out["train"][-1]))
        del net
        torch.cuda.empty_cache()
    typer.echo(json.dumps(out, indent=1))
