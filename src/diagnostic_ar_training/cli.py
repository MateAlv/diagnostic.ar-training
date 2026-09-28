"""`dxt`: sources, splits and lineage checks. Run `dxt --help`."""

import json
from pathlib import Path

import typer

from diagnostic_ar_training import MANIFESTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage import registry
from diagnostic_ar_training.lineage.manifest import Manifest, verify_outputs
from diagnostic_ar_training.lineage.registry import LineageError

app = typer.Typer(no_args_is_help=True, help=__doc__)
sources_app = typer.Typer(no_args_is_help=True, help="Pinned external inputs (data/sources.yaml).")
split_app = typer.Typer(no_args_is_help=True, help="Frozen, publication-grouped cohort splits.")
lineage_app = typer.Typer(no_args_is_help=True, help="Integrity of everything recorded.")
app.add_typer(sources_app, name="sources")
app.add_typer(split_app, name="split")
app.add_typer(lineage_app, name="lineage")


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
