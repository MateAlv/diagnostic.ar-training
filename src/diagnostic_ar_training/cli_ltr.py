"""`dxt ltr …`: Phase 2 Track 2, ltr-v1 (docs/PHASE2.md): knowledge build, dev selection, sealed read."""

import json
import statistics
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR, RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage.registry import LineageError

ltr_app = typer.Typer(
    no_args_is_help=True, help="Phase 2 Track 2: ltr-v1, a re-ranker learned on r1-v1 train."
)

KB_FILE = "ltr-kb.json.gz"
SAFE_BUNDLE = "safe-v1-bundle.json"
MODEL_FILES = ("spec.json", "model.txt")
ABLATION_DIR = "ablation"
SPLIT = "r1-v1"
EXPERIMENT = "EXP-P-002"
HARMED_CAP = 0.05


def _require_clean():
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    return state


def _output(artifact_id: str, kind: str, name: str) -> tuple[Path, str]:
    """A local output of an artifact that verifies against its manifest (else fetched from its release)."""
    from diagnostic_ar_training.lineage import manifest

    m = manifest.load_manifest(artifact_id)
    if m.kind != kind:
        raise typer.BadParameter(f"{artifact_id} is a {m.kind!r} artifact, not a {kind}")
    local = [manifest.output_path(o) for o in m.outputs]
    if not all(p.is_file() for p in local) or manifest.verify_outputs(m):
        local = manifest.fetch_outputs(m)
    for path, out in zip(local, m.outputs, strict=True):
        if (path.name == name) if "/" not in name else out.path.endswith("/" + name):
            return path, out.sha256
    raise LineageError(f"{artifact_id} has no output named {name}")


def _check_mask_scope(artifact_id: str) -> None:
    from diagnostic_ar_training.lineage import manifest

    params = manifest.load_manifest(artifact_id).params
    if params.get("mask_split") != SPLIT or params.get("mask_scope") != "all":
        raise typer.BadParameter(f"{artifact_id} must mask every {SPLIT} publication (mask scope 'all')")


@ltr_app.command("kb")
def ltr_kb(
    kb_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. ltr-kb-v1"),
    rerank_kb: str = typer.Option("kb-v4", help="Schema-2 rerank KB masking every r1-v1 publication"),
    safe_kb: str = typer.Option(
        ..., help="safe-kb artifact built with --mask-scope all, e.g. safe-kb-all-v1"
    ),
) -> None:
    """Build the knowledge ltr-v1's features read (`ltr-kb/1`)."""
    from diagnostic_ar_training.lineage import registry
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ltr import knowledge
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.safe.bundle import load as load_safe
    from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle

    ensure_new(kb_id)
    _check_mask_scope(rerank_kb)
    _check_mask_scope(safe_kb)
    state = _require_clean()
    rerank_path, rerank_sha = _output(rerank_kb, "kb", "kb.json.gz")
    safe_path, safe_sha = _output(safe_kb, "safe-kb", SAFE_BUNDLE)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    vocabulary = V3Inputs(unpack_bundle()).genes
    built, stats = knowledge.build(kb_io.read(rerank_path), load_safe(safe_path), ontology, vocabulary)
    kb_path = INTERIM_DIR / "ltr" / kb_id / KB_FILE
    kb_io.write(built, kb_path)
    stats_path = DATA_DIR / "ltr" / kb_id / "stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [
        {"id": f"artifact:{rerank_kb}", "sha256": rerank_sha},
        {"id": f"artifact:{safe_kb}/{SAFE_BUNDLE}", "sha256": safe_sha},
        sources["hpo_ontology"].as_input(),
        sources[E0_SOURCE].as_input(),
    ]
    params = {
        "format": built["format"],
        "rerank_kb": rerank_kb,
        "safe_kb": safe_kb,
        "mask_split": SPLIT,
        "mask_scope": "all",
        "vocabulary": "E0 (genphenia_v3) genes",
        "epsilon": built["epsilon"],
        "unknown_frequency": built["unknown_frequency"],
        "ic": "-log(share of the vocabulary's diseases annotating the term or a descendant)",
        "background": "mean P(term | gene) over the vocabulary",
    }
    write_manifest(build_manifest(kb_id, "ltr-kb", inputs, params, [kb_path, stats_path], state=state))
    typer.echo(json.dumps(stats, indent=1))


def _run_id(exp: str, label: str) -> str:
    return f"results-{exp}-{label.replace('/', '-')}"


def _load_model(model_id: str):
    """(LtrModel, ablation LtrModel or None, lineage inputs) of a model artifact, with its knowledge."""
    from diagnostic_ar_training.lineage import manifest
    from diagnostic_ar_training.ltr.bundle import Knowledge, LtrModel, read_spec

    m = manifest.load_manifest(model_id)
    if m.kind != "ltr-model":
        raise typer.BadParameter(f"{model_id} is a {m.kind!r} artifact, not an ltr-model")
    spec_path, _ = _output(model_id, "ltr-model", f"{model_id}/spec.json")
    spec = read_spec(spec_path)
    kb_path, kb_sha = _output(spec["kb_id"], "ltr-kb", KB_FILE)
    if kb_sha != spec["kb_sha256"]:
        raise LineageError(f"{model_id} was fitted with another {spec['kb_id']}")
    knowledge = Knowledge.load(kb_path)
    model = LtrModel.load(spec_path.parent, knowledge)
    ablation_dir = spec_path.parent / ABLATION_DIR
    ablation = LtrModel.load(ablation_dir, knowledge) if (ablation_dir / "model.txt").is_file() else None
    inputs = [
        {"id": f"artifact:{spec['kb_id']}", "sha256": kb_sha},
        *({"id": f"artifact:{model_id}:{o.path}", "sha256": o.sha256} for o in m.outputs),
    ]
    return model, ablation, inputs


@ltr_app.command("select")
def ltr_select(
    kb_id: str = typer.Option(..., "--kb", help="ltr-kb artifact, e.g. ltr-kb-v1"),
    model_id: str = typer.Option(..., "--id", help="Immutable id of the selected model, e.g. ltr-v1"),
    exp: str = typer.Option(EXPERIMENT, help="Experiment the dev selection belongs to (results/<exp>/)"),
) -> None:
    """Fit every configuration on r1-v1 train, select on dev, refit the winner without the new inputs, and
    write the model artifact. Reads the free parts only."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.eval import harness, ltr_eval
    from diagnostic_ar_training.eval.safe_eval import Memo, contrast
    from diagnostic_ar_training.lineage import registry
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.ltr import train
    from diagnostic_ar_training.ltr.bundle import Knowledge, LtrModel
    from diagnostic_ar_training.ltr.system import NAME, LtrV1
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    label = f"{SPLIT}/{model_id}"
    run_id = _run_id(exp, label)
    ensure_new(run_id)
    ensure_new(model_id)
    state = _require_clean()
    kb_path, kb_sha = _output(kb_id, "ltr-kb", KB_FILE)
    knowledge = Knowledge.load(kb_path)
    base = Memo(GenPheniaV3())
    groups = splits.publication_groups(SPLIT)
    parts = {
        "train": splits.load_part(SPLIT, "train", Purpose.TRAIN),
        "dev": splits.load_part(SPLIT, "dev", Purpose.EVAL),
    }
    tables = {p: train.tables(base, knowledge, cs, groups) for p, cs in parts.items()}
    e0 = {p: train.ranks(t, None) for p, t in tables.items()}
    typer.echo({p: len(t) for p, t in tables.items()})

    def assess(text, cfg, ablation=False):
        out = {}
        for p, rows in tables.items():
            scores = None if text is None else train.predict(text, rows, cfg, ablation)
            out[p] = contrast(e0[p], train.ranks(rows, scores))
        return out

    tried, models = [], {}
    for cfg in train.grid():
        text, info = train.fit(cfg, tables["train"])
        result = assess(text, cfg)
        models[cfg.name] = text
        tried.append({"config": cfg.name, "fit": info, **result})
        d = result["dev"]
        typer.echo(
            f"{cfg.name:24} dev {d['delta']:+.5f} [{d['ci95'][0]:+.5f}, {d['ci95'][1]:+.5f}] harmed "
            f"{d['harmed']:.4f} top10 +{d['top10_entered']}/-{d['top10_left']}; "
            f"train {result['train']['delta']:+.5f}"
        )
    within = [t for t in tried if t["dev"]["harmed"] <= HARMED_CAP]
    pool = within or tried
    winner = max(pool, key=lambda t: t["dev"]["delta"])
    cfg = next(c for c in train.grid() if c.name == winner["config"])
    ablation_text, ablation_info = train.fit(cfg, tables["train"], ablation=True)
    ablation_result = assess(ablation_text, cfg, ablation=True)

    # The model artifact: what production ships next to the knowledge.
    model_dir = DATA_DIR / "ltr" / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    spec = train.spec(cfg, kb_id, kb_sha)
    (model_dir / "spec.json").write_text(json.dumps(spec, indent=1, sort_keys=True) + "\n")
    (model_dir / "model.txt").write_text(models[cfg.name])
    model_outputs = [model_dir / "spec.json", model_dir / "model.txt"]
    if ablation_text is not None:
        (model_dir / ABLATION_DIR).mkdir(exist_ok=True)
        ablation_spec = train.spec(cfg, kb_id, kb_sha, ablation=True)
        (model_dir / ABLATION_DIR / "spec.json").write_text(
            json.dumps(ablation_spec, indent=1, sort_keys=True) + "\n"
        )
        (model_dir / ABLATION_DIR / "model.txt").write_text(ablation_text)
        model_outputs += [model_dir / ABLATION_DIR / "spec.json", model_dir / ABLATION_DIR / "model.txt"]

    # The selected model and its ablation, through the System and the numpy evaluator that ship.
    model = LtrModel.load(model_dir, knowledge)
    systems = {"ltr": LtrV1(base, model, NAME)}
    if ablation_text is not None:
        systems["ablation"] = LtrV1(
            base, LtrModel.load(model_dir / ABLATION_DIR, knowledge), f"{NAME}-ablation"
        )
    reports, outputs = {}, []
    for p, cases in parts.items():
        extra = {"post_e0": ltr_eval.post_e0_cases(cases, groups)} if p == "dev" else {}
        report, records = ltr_eval.evaluate(base, systems, cases, groups, extra)
        fast = train.ranks(tables[p], train.predict(models[cfg.name], tables[p], cfg))
        report["system_vs_selection_rank_mismatches"] = sum(
            a["rank"] != b["rank"] for a, b in zip(fast, records[NAME], strict=True)
        )
        reports[p] = report
        cohort = f"{SPLIT}/{p}/{model_id}"
        for name, recs in records.items():
            outputs += harness.write(exp, cohort, name, "all", recs)
        typer.echo(f"{p}: {len(cases)} cases, E0 MRR {report['e0']['mrr']:.4f}")
        for text_line in ltr_eval.table(report):
            typer.echo(text_line)

    dev_deltas = [t["dev"]["delta"] for t in tried]
    report = {
        "experiment": exp,
        "model_id": model_id,
        "kb": kb_id,
        "kb_sha256": kb_sha,
        "code_sha": state.sha,
        "selection_rule": f"highest dev delta MRR among configurations with dev harmed <= {HARMED_CAP}; "
        "if none, highest dev delta MRR",
        "configurations": tried,
        "configurations_within_harmed_cap": len(within),
        "winner": winner["config"],
        "dev_delta_median": statistics.median(dev_deltas),
        "dev_delta_range": [min(dev_deltas), max(dev_deltas)],
        "ablation": {"fit": ablation_info, **ablation_result},
        "reports": reports,
        "inner_split": {"salt": train.INNER_SALT, "share": train.INNER_SHARE},
    }
    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"{label.replace('/', '-')}__selection.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True, default=float) + "\n")
    outputs.append(report_path)

    sources = registry.load_sources()
    inputs = [
        *base.lineage_inputs(),
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        {"id": f"split:{SPLIT}", "sha256": sha256_file(SPLITS_DIR / f"{SPLIT}.json")},
        sources[splits.E0_RELEASE].as_input(),
        sources[splits.E0_ANNOTATIONS].as_input(),
    ]
    params = {"split": SPLIT, "parts": ["train", "dev"], "kb": kb_id, "grid": [c.name for c in train.grid()]}
    write_manifest(build_manifest(run_id, "ltr-select", inputs, params, outputs, state=state))
    model_params = {"spec": spec, "selected_by": run_id, "fitted_on": f"{SPLIT}/train"}
    model_inputs = [
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        {"id": f"split:{SPLIT}", "sha256": sha256_file(SPLITS_DIR / f"{SPLIT}.json")},
    ]
    write_manifest(
        build_manifest(model_id, "ltr-model", model_inputs, model_params, model_outputs, state=state)
    )
    typer.echo(
        f"winner {winner['config']}; median dev delta {report['dev_delta_median']:+.5f} -> {report_path}"
    )


@ltr_app.command("confirm")
def ltr_confirm(
    exp: str = typer.Option(..., help="Pre-registered experiment id"),
    split: list[str] = typer.Option(..., help="p2-v1 for test; p2-v1 and p2-fresh-v1 together for vault"),
    part: str = typer.Option(..., help="test (confirmation) or vault (final check, opens once)"),
    model_id: str = typer.Option(..., "--model", help="The model artifact the pre-registration names"),
    reason: str = typer.Option("", help="Required"),
) -> None:
    """The sealed read: `DXT_SEALED_READ=<exp> dxt ltr confirm --exp <exp> --split p2-v1 --part test --model
    <id> --reason ...`. The final check reads both vaults in one call. Every refusal comes before any data is
    loaded or the ledger touched (`safe_eval.preflight`, the same order as `dxt safe confirm`).
    """
    from diagnostic_ar_training.eval import safe_eval

    try:
        safe_eval.preflight(exp, split, part, reason)
    except (ValueError, LineageError) as e:
        raise typer.BadParameter(str(e)) from e

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.eval import harness, ltr_eval
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.ltr.system import NAME, LtrV1
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    label = "+".join(split) + f"/{part}/{model_id}"
    run_id = _run_id(exp, label)
    ensure_new(run_id)
    state = code_state()
    model, ablation, model_inputs = _load_model(model_id)
    base = safe_eval.Memo(GenPheniaV3())
    systems = {"ltr": LtrV1(base, model, NAME)}
    if ablation is not None:
        systems["ablation"] = LtrV1(base, ablation, f"{NAME}-ablation")
    by_split = {}
    for split_id in split:
        groups = splits.publication_groups(split_id)
        cases = splits.load_part(split_id, part, Purpose.EVAL, exp, reason)
        by_split[split_id] = (cases, {c.case_id: f"{split_id}:{groups[c.case_id]}" for c in cases})
    cases = [c for cs, _ in by_split.values() for c in cs]
    groups = {k: v for _, g in by_split.values() for k, v in g.items()}
    report, records = ltr_eval.evaluate(base, systems, cases, groups)
    if len(by_split) > 1:
        report["components"] = {
            s: ltr_eval.evaluate(base, systems, cs, g)[0] for s, (cs, g) in by_split.items()
        }
    report |= {"cohort": label, "model": model_id, "code_sha": state.sha, "reason": reason}
    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = [p for name, recs in records.items() for p in harness.write(exp, label, name, "all", recs)]
    report_path = out_dir / f"{label.replace('/', '-')}__report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = [
        *base.lineage_inputs(),
        *model_inputs,
        *({"id": f"split:{s}", "sha256": sha256_file(SPLITS_DIR / f"{s}.json")} for s in split),
    ]
    params = {"cohort": label, "model": model_id, "systems": sorted(records)}
    write_manifest(build_manifest(run_id, "ltr-eval", inputs, params, outputs, state=state))
    for text_line in ltr_eval.table(report):
        typer.echo(text_line)
    typer.echo(f"-> {report_path} (manifest {run_id})")
