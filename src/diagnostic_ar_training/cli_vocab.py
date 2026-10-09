"""`dxt vocab …`: Phase 2 Track 4, new-row training and its leave-genes-out standards test (EXP-P-007).

- `select`: train only. Relearn the genes of the held-out train publication groups with each configuration ×
  seed and score `r1-v1` train. Dev is never loaded.
- `choose`: the registered selection rule over the `select` runs.
- `final`: the chosen configuration only. Relearn the dev genes with seeds 0-2, average the rows, and score
  `r1-v1` dev (read once) and train.
"""

import json
import time
from pathlib import Path

import typer

from diagnostic_ar_training import INTERIM_DIR, RESULTS_DIR

vocab_app = typer.Typer(no_args_is_help=True, help="Phase 2 Track 4: new-row training (EXP-P-007).")

MODELS_DIR = INTERIM_DIR / "models" / "vocab"
SELECTION = "selection.json"


def _require_clean():
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    return state


def _require_preregistered(exp: str) -> None:
    from diagnostic_ar_training.lineage import ledger

    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before the run")


def _setup(kb_id: str, device: str, parts: tuple[str, ...]):
    from diagnostic_ar_training.cli_ft import _kb_output
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.vocab.runs import Setup

    kb_path, kb_sha = _kb_output(kb_id)
    return Setup(kb_io.read(kb_path), kb_id, kb_sha, device, parts)


def _write_json(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str) + "\n")
    return path


def _line(label: str, block: dict) -> str:
    if not block["e0"].get("n"):
        return f"{label:24} n 0"
    r, d = block["ratio"], block["vs_e0"]
    return (
        f"{label:24} n {block['e0']['n']:5d} MRR E0 {block['e0']['mrr']:.4f} new {block['new']['mrr']:.4f} "
        f"ratio {r['ratio']:.4f} [{r['ci95'][0]:.4f}, {r['ci95'][1]:.4f}] dMRR {d['delta']:+.5f} "
        f"[{d['ci95'][0]:+.5f}, {d['ci95'][1]:+.5f}] "
        f"top1 {block['e0']['top1']:.3f}->{block['new']['top1']:.3f} "
        f"top10 {block['e0']['top10']:.3f}->{block['new']['top10']:.3f} "
        f"harmed {d['harmed_n']} helped {d['helped_n']}"
    )


@vocab_app.command("select")
def vocab_select(
    exp: str = typer.Option("EXP-P-007"),
    kb_id: str = typer.Option("ft-kb-all-v2", "--kb"),
    config: list[str] = typer.Option(..., help="Configurations of vocab/standards.py"),
    seed: list[int] = typer.Option([0, 1, 2]),
    device: str = typer.Option("cuda"),
) -> None:
    """Train only: relearn the held-out train groups' genes per configuration × seed; score r1-v1 train."""
    import torch

    from diagnostic_ar_training.ft.runs import write_compact_ranks as compact_ranks
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.vocab import rows, runs, standards

    todo = [(name, s) for name in config for s in seed]
    for name, s in todo:
        try:
            standards.config(name)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        ensure_new(f"results-{exp}-select-{name}-s{s}")
    state = _require_clean()
    _require_preregistered(exp)
    wall = time.perf_counter()
    setup = _setup(kb_id, device, ("train",))
    inner_cases = [c for c in setup.cases["train"] if c.case_id in setup.inner]
    relearn, gene_counts = standards.choose_genes(inner_cases, setup.vocabulary, setup.has_profile)
    e0_train = setup.e0_records["train"]
    e0_inner = [r for r in e0_train if r["case_id"] in setup.inner]
    pipeline = {
        "e0_ranks_differ_from_exp_p001": setup.e0_check,
        "e0_rows_through_pipeline_rank_differences_train": setup.e0_rows_rank_differences(relearn, "train"),
    }
    typer.echo(f"setup {time.perf_counter() - wall:.0f} s: relearn {gene_counts['chosen']} genes; {pipeline}")
    for name, s in todo:
        start = time.perf_counter()
        run_id = f"select-{name}-s{s}"
        out_dir, model_dir = RESULTS_DIR / exp / "select" / f"{name}-s{s}", MODELS_DIR / exp / run_id
        if out_dir.exists() or model_dir.exists():
            raise typer.BadParameter(f"{out_dir} or {model_dir} exists; run ids are never reused")
        cfg = rows.RowConfig(seed=s, **standards.config(name))
        typer.echo(f"[{run_id}] {cfg.as_dict()}")
        result, info = setup.fit(relearn, cfg, log=typer.echo)
        weight = result.head.new_weight.detach().cpu().numpy()
        bias = result.head.new_bias.detach().cpu().numpy()
        system = setup.system(relearn, weight, bias, run_id)
        records = setup.run(system, "train")
        inner = [r for r in records if r["case_id"] in setup.inner]
        rep_inner = standards.report(e0_inner, inner, relearn)
        rep_train = standards.report(e0_train, records, relearn)
        info["checks"]["untouched_logits_differ_train"] = setup.untouched_logits_differ(system, "train")
        index = setup.index(relearn)
        weights_path = runs.save_rows(
            model_dir / "rows.pt", relearn, index, weight, bias, {"run": run_id, "config": cfg.as_dict()}
        )
        summary = {
            "run_id": run_id,
            "config_name": name,
            "seed": s,
            "config": cfg.as_dict(),
            "relearned_genes": relearn,
            "gene_choice": gene_counts,
            "best_epoch": result.best_epoch,
            "epochs_run": result.epochs_run,
            "stopped_early": result.stopped_early,
            "fit_seconds": result.seconds,
            "run_seconds": time.perf_counter() - start,
            "device": torch.cuda.get_device_name(setup.device) if setup.device.type == "cuda" else "cpu",
            "torch": torch.__version__,
            "code": state.as_dict(),
            "kb": kb_id,
            "pipeline": pipeline,
            **info,
            "row": {
                "config": name,
                "seed": s,
                "ratio": rep_inner["relearned"]["ratio"]["ratio"],
                "others_delta": rep_train["others"]["vs_e0"]["delta"],
            },
            "inner": rep_inner,
            "train": rep_train,
        }
        outputs = [
            _write_json(out_dir / "curves.json", result.history),
            _write_json(out_dir / "summary.json", summary),
            compact_ranks(out_dir / "r1-v1-train.ranks.jsonl", records),
            weights_path,
        ]
        params = {
            **cfg.as_dict(),
            "exp": exp,
            "run_id": run_id,
            "config_name": name,
            "device": device,
            "relearned": "genes of the held-out train groups (vocab/standards.choose_genes)",
        }
        write_manifest(
            build_manifest(
                f"results-{exp}-{run_id}",
                "vocab-rows-run",
                setup.lineage(),
                params,
                outputs,
                notes="v3.0 frozen; only the relearned rows are trained; rows.pt stays in data/interim.",
                state=state,
            )
        )
        typer.echo(_line(f"[{run_id}] inner (a)", rep_inner["relearned"]))
        typer.echo(_line(f"[{run_id}] train (b)", rep_train["others"]))
        typer.echo(f"[{run_id}] best epoch {result.best_epoch}/{result.epochs_run}, checks {info['checks']}")
    typer.echo(f"select done in {(time.perf_counter() - wall) / 60:.1f} min")


@vocab_app.command("choose")
def vocab_choose(exp: str = typer.Option("EXP-P-007")) -> None:
    """The registered selection rule over the train-only runs: results/<exp>/selection.json, manifested."""
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.vocab import standards

    artifact_id = f"results-{exp}-selection"
    ensure_new(artifact_id)
    state = _require_clean()
    paths = sorted((RESULTS_DIR / exp / "select").glob("*/summary.json"))
    summaries = [json.loads(p.read_text()) for p in paths]
    rows = [s["row"] for s in summaries]
    selection = standards.select(rows)
    selection["runs"] = [
        {**s["row"], "best_epoch": s["best_epoch"], "fit_seconds": s["fit_seconds"]} for s in summaries
    ]
    path = _write_json(RESULTS_DIR / exp / SELECTION, selection)
    refs = [{"id": f"results-{exp}-{s['run_id']}/summary.json", "sha256": sha256_file(p)}
            for s, p in zip(summaries, paths, strict=True)]  # fmt: skip
    write_manifest(build_manifest(artifact_id, "vocab-selection", refs, {"exp": exp}, [path], state=state))
    for name, a in sorted(selection["by_config"].items()):
        typer.echo(
            f"{name:22} ratio {a['ratio']:.4f} (sd {a['ratio_sd']}) others dMRR {a['others_delta']:+.5f}"
        )
    typer.echo(f"selected: {selection['selected']}")


@vocab_app.command("final")
def vocab_final(
    exp: str = typer.Option("EXP-P-007"),
    kb_id: str = typer.Option("ft-kb-all-v2", "--kb"),
    config: str = typer.Option(..., help="The configuration selection.json selected"),
    seed: list[int] = typer.Option([0, 1, 2]),
    device: str = typer.Option("cuda"),
) -> None:
    """The standards test: relearn the dev genes with the chosen configuration; score dev (once) and train."""
    import torch

    from diagnostic_ar_training.ft.runs import Setup as FtSetup
    from diagnostic_ar_training.ft.runs import write_compact_ranks as compact_ranks
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.vocab import rows, runs, standards

    selection_path = RESULTS_DIR / exp / SELECTION
    if not selection_path.is_file():
        raise typer.BadParameter(f"{selection_path} is missing: run `dxt vocab choose` first")
    selected = json.loads(selection_path.read_text())["selected"]
    if config != selected:
        raise typer.BadParameter(f"the train-only selection chose {selected!r}, not {config!r}")
    if tuple(seed) != standards.SEEDS:
        raise typer.BadParameter(f"the registered seeds are {list(standards.SEEDS)}")
    ens_id = f"final-{config}-ens"
    for s in seed:
        ensure_new(f"results-{exp}-final-{config}-s{s}")
    ensure_new(f"results-{exp}-{ens_id}")
    state = _require_clean()
    _require_preregistered(exp)
    wall = time.perf_counter()
    setup = _setup(kb_id, device, ("train", "dev"))
    relearn, gene_counts = standards.choose_genes(setup.cases["dev"], setup.vocabulary, setup.has_profile)
    index = setup.index(relearn)
    train_genes = {c.gene.upper() for c in setup.cases["train"]}
    dev = setup.cases["dev"]
    extra = {
        "post_e0": FtSetup._post_e0(dev, setup.groups),
        "gene_in_train": {c.case_id for c in dev if c.gene.upper() in train_genes},
        "gene_not_in_train": {c.case_id for c in dev if c.gene.upper() not in train_genes},
    }
    pipeline = {
        "e0_ranks_differ_from_exp_p001": setup.e0_check,
        "e0_rows_through_pipeline_rank_differences": {
            p: setup.e0_rows_rank_differences(relearn, p) for p in ("dev", "train")
        },
    }
    typer.echo(f"setup {time.perf_counter() - wall:.0f} s: relearn {gene_counts['chosen']} genes; {pipeline}")

    def evaluate(weight, bias, name):
        system = setup.system(relearn, weight, bias, name)
        records = {p: setup.run(system, p) for p in ("dev", "train")}
        reps = {
            "dev": standards.report(setup.e0_records["dev"], records["dev"], relearn, extra),
            "train": standards.report(setup.e0_records["train"], records["train"], relearn),
        }
        untouched = {p: setup.untouched_logits_differ(system, p) for p in ("dev", "train")}
        return records, reps, untouched

    heads, fit_seconds, seed_rows = [], 0.0, []
    for s in seed:
        start = time.perf_counter()
        run_id = f"final-{config}-s{s}"
        out_dir, model_dir = RESULTS_DIR / exp / "final" / f"{config}-s{s}", MODELS_DIR / exp / run_id
        if out_dir.exists() or model_dir.exists():
            raise typer.BadParameter(f"{out_dir} or {model_dir} exists; run ids are never reused")
        cfg = rows.RowConfig(seed=s, **standards.config(config))
        typer.echo(f"[{run_id}] {cfg.as_dict()}")
        result, info = setup.fit(relearn, cfg, log=typer.echo)
        heads.append(result.head)
        fit_seconds += result.seconds
        weight = result.head.new_weight.detach().cpu().numpy()
        bias = result.head.new_bias.detach().cpu().numpy()
        records, reps, untouched = evaluate(weight, bias, run_id)
        info["checks"]["untouched_logits_differ"] = untouched
        weights_path = runs.save_rows(
            model_dir / "rows.pt", relearn, index, weight, bias, {"run": run_id, "config": cfg.as_dict()}
        )
        summary = {
            "run_id": run_id,
            "config_name": config,
            "seed": s,
            "config": cfg.as_dict(),
            "relearned_genes": relearn,
            "gene_choice": gene_counts,
            "best_epoch": result.best_epoch,
            "epochs_run": result.epochs_run,
            "stopped_early": result.stopped_early,
            "fit_seconds": result.seconds,
            "run_seconds": time.perf_counter() - start,
            "device": torch.cuda.get_device_name(setup.device) if setup.device.type == "cuda" else "cpu",
            "torch": torch.__version__,
            "code": state.as_dict(),
            "kb": kb_id,
            "pipeline": pipeline,
            **info,
            **reps,
        }
        seed_rows.append(
            {
                "seed": s,
                "dev_ratio": reps["dev"]["relearned"]["ratio"]["ratio"],
                "dev_others_delta": reps["dev"]["others"]["vs_e0"]["delta"],
                "train_ratio": reps["train"]["relearned"]["ratio"]["ratio"],
                "train_others_delta": reps["train"]["others"]["vs_e0"]["delta"],
            }
        )
        outputs = [
            _write_json(out_dir / "curves.json", result.history),
            _write_json(out_dir / "summary.json", summary),
            *[compact_ranks(out_dir / f"r1-v1-{p}.ranks.jsonl", r) for p, r in records.items()],
            weights_path,
        ]
        params = {**cfg.as_dict(), "exp": exp, "run_id": run_id, "config_name": config, "device": device,
                  "relearned": "genes of r1-v1 dev (vocab/standards.choose_genes)"}  # fmt: skip
        write_manifest(
            build_manifest(
                f"results-{exp}-{run_id}", "vocab-rows-run", setup.lineage(), params, outputs,
                notes="v3.0 frozen; only the relearned rows are trained; rows.pt stays in data/interim.",
                state=state,
            )
        )  # fmt: skip
        typer.echo(_line(f"[{run_id}] dev (a)", reps["dev"]["relearned"]))
        typer.echo(_line(f"[{run_id}] dev (b)", reps["dev"]["others"]))

    start = time.perf_counter()
    mean_w, mean_b = rows.mean_rows(heads)
    mean_w, mean_b = mean_w.astype("float32"), mean_b.astype("float32")
    records, reps, untouched = evaluate(mean_w, mean_b, ens_id)
    weights_path = runs.save_rows(
        MODELS_DIR / exp / ens_id / "rows.pt", relearn, index, mean_w, mean_b,
        {"run": ens_id, "combine": "mean of the seed rows", "seeds": list(seed)},
    )  # fmt: skip
    out_dir = RESULTS_DIR / exp / "final" / f"{config}-ens"
    summary = {
        "run_id": ens_id,
        "config_name": config,
        "seeds": list(seed),
        "relearned_genes": relearn,
        "gene_choice": gene_counts,
        "code": state.as_dict(),
        "kb": kb_id,
        "pipeline": pipeline,
        "untouched_logits_differ": untouched,
        "gpu_fit_seconds_all_seeds": fit_seconds,
        "wall_minutes": (time.perf_counter() - wall) / 60,
        "seed_rows": seed_rows,
        "rows_sha256": sha256_file(weights_path),
        **reps,
        "per_gene_dev": standards.per_gene(setup.e0_records["dev"], records["dev"], relearn),
    }
    outputs = [
        _write_json(out_dir / "summary.json", summary),
        *[compact_ranks(out_dir / f"r1-v1-{p}.ranks.jsonl", r) for p, r in records.items()],
        weights_path,
    ]
    refs = setup.lineage() + [
        {
            "id": f"results-{exp}-final-{config}-s{s}/rows.pt",
            "sha256": sha256_file(MODELS_DIR / exp / f"final-{config}-s{s}" / "rows.pt"),
        }
        for s in seed
    ]
    params = {"exp": exp, "config_name": config, "seeds": list(seed), "combine": "mean of the seed rows"}
    write_manifest(
        build_manifest(f"results-{exp}-{ens_id}", "vocab-rows-eval", refs, params, outputs, state=state)
    )
    for part in ("dev", "train"):
        typer.echo(_line(f"[{ens_id}] {part} (a)", reps[part]["relearned"]))
        typer.echo(_line(f"[{ens_id}] {part} (b)", reps[part]["others"]))
    typer.echo(f"criterion (dev, ensemble): {reps['dev']['criterion']}")
    typer.echo(
        f"final done in {(time.perf_counter() - wall) / 60:.1f} min ({time.perf_counter() - start:.0f} s ens)"
    )
