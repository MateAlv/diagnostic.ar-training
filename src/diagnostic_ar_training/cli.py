"""`dxt`: sources, splits and lineage checks. Run `dxt --help`."""

import json
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, MANIFESTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.lineage.manifest import Manifest, verify_outputs
from diagnostic_ar_training.lineage.registry import LineageError

app = typer.Typer(no_args_is_help=True, help=__doc__)
sources_app = typer.Typer(no_args_is_help=True, help="Pinned external inputs (data/sources.yaml).")
split_app = typer.Typer(no_args_is_help=True, help="Frozen, publication-grouped cohort splits.")
lineage_app = typer.Typer(no_args_is_help=True, help="Integrity of everything recorded.")
eval_app = typer.Typer(no_args_is_help=True, help="Run systems on cohorts; results + manifest.")
kb_app = typer.Typer(no_args_is_help=True, help="Front B knowledge base.")
artifacts_app = typer.Typer(no_args_is_help=True, help="Derived artifacts published as releases.")
app.add_typer(sources_app, name="sources")
app.add_typer(split_app, name="split")
app.add_typer(lineage_app, name="lineage")
app.add_typer(eval_app, name="eval")
app.add_typer(kb_app, name="kb")
app.add_typer(artifacts_app, name="artifacts")


@kb_app.command("build")
def kb_build(
    kb_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. kb-v1"),
    mask_split: str = typer.Option("r1-v1", help="Split whose held-out PMIDs are masked"),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """Build the knowledge base from pinned sources with held-out publications masked."""
    from diagnostic_ar_training import INTERIM_DIR, splits
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb

    names = [
        "hpo_ontology",
        "hpo_annotations",
        "hpo_genes_to_disease",
        "hpo_genes_to_phenotype",
        "orphanet_ages",
    ]
    paths = {n: open_source(n, Purpose.KB) for n in names}
    splits.write_heldout_pmids(mask_split)  # refuses if the committed list drifted from the split
    mask_path = splits.heldout_pmids_path(mask_split)
    masked = set(mask_path.read_text().split())
    built, stats = kb.build(
        Ontology.from_json(paths["hpo_ontology"]),
        paths["hpo_annotations"],
        paths["hpo_genes_to_disease"],
        paths["hpo_genes_to_phenotype"],
        paths["orphanet_ages"],
        masked,
    )
    out_dir = INTERIM_DIR / "kb" / kb_id
    kb_path = out_dir / "kb.json.gz"
    kb.write(built, kb_path)
    stats_path = DATA_DIR / "kb" / f"{kb_id}.stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [sources[n].as_input() for n in names]
    inputs.append({"id": f"heldout-pmids:{mask_split}", "sha256": sha256_file(mask_path)})
    params = {
        "mask_split": mask_split,
        "excluded_associations": sorted(kb.EXCLUDED_ASSOCIATIONS),
        "schema": 1,
    }
    manifest = build_manifest(kb_id, "rerank-kb", inputs, params, [kb_path, stats_path])
    if publish:
        manifest = publish_release(manifest, kb_id)
    write_manifest(manifest)
    typer.echo(json.dumps(stats, indent=1))


@artifacts_app.command("fetch")
def artifacts_fetch(artifact_id: str) -> None:
    """Download a published artifact's files and verify them against its manifest."""
    from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest

    for path in fetch_outputs(load_manifest(artifact_id)):
        typer.echo(path)


def _system(name: str):
    if name == "genphenia-v3":
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        return GenPheniaV3()
    raise typer.BadParameter(f"unknown system {name!r}")


@eval_app.command("run")
def eval_run(
    system: str = typer.Option(..., help="genphenia-v3"),
    cohort: str = typer.Option(..., help="r1-v1/<part>, mcrd, ddd or s2"),
    exp: str = typer.Option(..., help="Experiment id, e.g. EXP-000"),
    view: list[str] = typer.Option(["all"], help="Input views (repeatable)"),
    reason: str = typer.Option("", help="Required for sealed cohorts"),
) -> None:
    """Score every case; write ranks, summary and a lineage manifest under results/<exp>/."""
    from diagnostic_ar_training import SPLITS_DIR
    from diagnostic_ar_training.cohorts import access
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest

    if code_state().dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    runner = _system(system)
    cases = access.load(cohort, exp_id=exp, reason=reason)
    inputs = runner.lineage_inputs()
    if cohort.startswith("r1-v1/"):
        inputs.append({"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")})
    else:
        source = {"s2": access.S2_SOURCE}.get(cohort, cohort)
        inputs.append(registry.load_sources()[source].as_input())
    groups = None
    if cohort.startswith("r1-v1/"):
        from diagnostic_ar_training import splits

        groups = splits.publication_groups("r1-v1")
    for v in view:
        records = harness.run(runner, cases, view=v, groups=groups)
        outputs = harness.write(exp, cohort, runner.name, v, records)
        artifact = f"results-{exp}-{cohort.replace('/', '-')}-{runner.name}-{v}"
        manifest = build_manifest(
            artifact, "eval-results", inputs, {"system": system, "cohort": cohort, "view": v}, list(outputs)
        )
        write_manifest(manifest)
        summary = harness.summarize(records)["all"]
        typer.echo(
            f"{cohort} {v}: n={summary['n']} mrr={summary['mrr']:.4f} top1={summary['top1']:.4f} "
            f"top10={summary['top10']:.4f} -> {outputs[1]}"
        )


@sources_app.command("list")
def sources_list() -> None:
    for s in registry.load_sources().values():
        state = "ok" if registry.verify(s) else "missing"
        typer.echo(f"{s.name:24} {s.role:9} {s.version:16} {state}")


@sources_app.command("fetch")
def sources_fetch(
    name: list[str] = typer.Argument(None, help="Sources to fetch; all if omitted."),
    no_download: bool = typer.Option(False, help="Only use verified local copies."),
) -> None:
    sources = registry.load_sources()
    for n in name or list(sources):
        path = registry.fetch(sources[n], allow_download=not no_download)
        typer.echo(f"{n}: {path}")


@sources_app.command("verify")
def sources_verify() -> None:
    bad = [s.name for s in registry.load_sources().values() if not registry.verify(s)]
    if bad:
        typer.echo(f"missing or modified: {', '.join(bad)}", err=True)
        raise typer.Exit(1)
    typer.echo("all sources match their pinned sha256")


@split_app.command("freeze")
def split_freeze(split_id: str) -> None:
    from diagnostic_ar_training import splits

    body = splits.freeze(split_id)
    typer.echo(json.dumps({"content_sha256": body["content_sha256"], "stats": body["stats"]}, indent=1))


@split_app.command("show")
def split_show(split_id: str) -> None:
    from diagnostic_ar_training import splits

    body = splits.load_frozen(split_id)
    shown = {k: body[k] for k in ("split_id", "source", "rule", "sealed_parts", "parse_drops", "stats")}
    typer.echo(json.dumps(shown, indent=1))


@split_app.command("heldout-pmids")
def split_heldout_pmids(split_id: str) -> None:
    """Write data/splits/<id>.heldout-pmids.txt: PMIDs every KB and simulator must mask."""
    from diagnostic_ar_training import splits

    digest = splits.write_heldout_pmids(split_id)
    typer.echo(f"{splits.heldout_pmids_path(split_id)} sha256={digest}")


@eval_app.command("cluster-summaries")
def eval_cluster_summaries(exp: str, split_id: str = "r1-v1") -> None:
    """Publication-clustered summaries for rank files written without groups.

    Reads existing ranks (no new read of any cohort) and writes
    <stem>.clustered-summary.json as a new artifact; the originals stay untouched.
    """
    from diagnostic_ar_training import RESULTS_DIR, splits
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest

    groups = splits.publication_groups(split_id)
    for ranks_path in sorted((RESULTS_DIR / exp).glob(f"{split_id}-*.ranks.jsonl")):
        records = [{**r, "group": groups[r["case_id"]]} for r in harness.read(ranks_path)]
        stem = ranks_path.name.removesuffix(".ranks.jsonl")
        out = ranks_path.with_name(f"{stem}.clustered-summary.json")
        out.write_text(json.dumps(harness.summarize(records), indent=1, sort_keys=True) + "\n")
        inputs = [
            {"id": f"results:{exp}/{ranks_path.name}", "sha256": sha256_file(ranks_path)},
            {"id": f"split:{split_id}", "sha256": sha256_file(SPLITS_DIR / f"{split_id}.json")},
        ]
        write_manifest(
            build_manifest(f"clustered-{exp}-{stem}", "eval-summary", inputs, {"split": split_id}, [out])
        )
        s = harness.summarize(records)["all"]
        typer.echo(f"{stem}: mrr={s['mrr']:.4f} publication-CI={[round(x, 3) for x in s['mrr_ci95']]}")


@lineage_app.command("verify")
def lineage_verify() -> None:
    """Sources, frozen splits and every manifest's outputs."""
    from diagnostic_ar_training import splits

    problems = [
        f"source {s.name}: missing or modified"
        for s in registry.load_sources().values()
        if not registry.verify(s)
    ]
    for path in sorted(SPLITS_DIR.glob("*.json")):
        try:
            splits.load_frozen(path.stem)
            if splits.heldout_pmids_path(path.stem).exists():
                splits.write_heldout_pmids(path.stem)
        except LineageError as err:
            problems.append(str(err))
    for path in sorted(MANIFESTS_DIR.glob("*.json")):
        manifest = Manifest.model_validate_json(Path(path).read_text())
        problems += [f"{manifest.artifact_id}: {p}" for p in verify_outputs(manifest)]
    for p in problems:
        typer.echo(p, err=True)
    if problems:
        raise typer.Exit(1)
    typer.echo("lineage ok")


if __name__ == "__main__":
    app()
