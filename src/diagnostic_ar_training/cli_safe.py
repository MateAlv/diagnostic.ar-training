"""`dxt safe …`: Phase 2 Track 1, safe-v1 (docs/PHASE2.md): knowledge build, curation queue, dev dry run,
and the sealed confirmation read."""

import json
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR, RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage.registry import LineageError

safe_app = typer.Typer(no_args_is_help=True, help="Phase 2 Track 1: safe-v1, knowledge-only constraints.")

KB_SOURCES = ("hpo_genes_to_disease", "hpo_annotations", "orphanet_ages_2026_06", "hgnc", "hpo_ontology")
KB_FILE = "safe-kb.json.gz"
BUNDLE_FILE = "safe-v1-bundle.json"
MASK_SPLIT, MASK_SCOPE = "r1-v1", "heldout"


def _require_clean():
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    return state


def _kb_output(kb_id: str, name: str) -> tuple[Path, str]:
    from diagnostic_ar_training.lineage import manifest

    m = manifest.load_manifest(kb_id)
    if m.kind != "safe-kb":
        raise typer.BadParameter(f"{kb_id} is a {m.kind!r} artifact, not a safe-kb")
    local = [manifest.output_path(o) for o in m.outputs]
    # Local files that verify against the manifest are used as they are; only a missing one needs the release.
    if not all(p.is_file() for p in local) or manifest.verify_outputs(m):
        local = manifest.fetch_outputs(m)
    for path, out in zip(local, m.outputs, strict=True):
        if path.name == name:
            return path, out.sha256
    raise LineageError(f"{kb_id} has no output named {name}")


@safe_app.command("build")
def safe_build(
    kb_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. safe-kb-v1a"),
    overrides: str = typer.Option(
        "", help="Curation overrides CSV, e.g. data/curation/safe-v1-overrides.csv"
    ),
    onset_factor: float | None = typer.Option(
        None, help="Multiply onset-incompatible genes by this instead of blocking them (bundle onset_factor)"
    ),
    mask_scope: str = typer.Option(
        MASK_SCOPE,
        help="r1-v1 PMIDs to mask: heldout (dev, test, vault) or all (every part; models fitted on train)",
    ),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """Build the safe knowledge artifact and its production bundle; held-out (or all) r1-v1 PMIDs masked."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.lineage import registry
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.safe import bundle, knowledge
    from diagnostic_ar_training.safe import overrides as curation
    from diagnostic_ar_training.systems.genphenia_v3 import SOURCE as E0_SOURCE
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle

    if mask_scope not in splits.MASK_SCOPES:
        raise typer.BadParameter(f"--mask-scope must be one of {sorted(splits.MASK_SCOPES)}")
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
    splits.write_mask(MASK_SPLIT, mask_scope)  # refuses if the committed list drifted from the split
    mask_path = splits.mask_path(MASK_SPLIT, mask_scope)
    ontology = Ontology.from_json(paths["hpo_ontology"])
    built, stats = knowledge.build(
        vocabulary,
        knowledge.read_genes_to_disease(paths["hpo_genes_to_disease"]),
        knowledge.read_annotations(paths["hpo_annotations"], mask_path.read_text().split()),
        knowledge.read_orphanet_onsets(paths["orphanet_ages_2026_06"]),
        knowledge.read_hgnc_locations(paths["hgnc"]),
        ontology.ancestors,
    )
    uncurated = knowledge.summary_stats(built)
    try:
        built = curation.apply(built, rows)
    except curation.OverrideError as e:
        raise typer.BadParameter(str(e)) from e
    stats = {**stats, **knowledge.summary_stats(built), "uncurated": uncurated}

    # The full artifact is large and lives in data/interim; the bundle and the stats are small and committed.
    kb_path = INTERIM_DIR / "safe" / kb_id / KB_FILE
    kb_io.write(built, kb_path)
    committed = DATA_DIR / "safe" / kb_id
    committed.mkdir(parents=True, exist_ok=True)
    bundle_path, stats_path = committed / BUNDLE_FILE, committed / "stats.json"
    if onset_factor is not None and not 0 < onset_factor < 1:
        raise typer.BadParameter("--onset-factor must be in (0, 1)")
    exported = bundle.export(built, kb_id, onset_factor=onset_factor)
    bundle_path.write_text(json.dumps(exported, sort_keys=True, separators=(",", ":")) + "\n")
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")

    sources = registry.load_sources()
    inputs = [sources[n].as_input() for n in (*KB_SOURCES, E0_SOURCE)]
    inputs.append({"id": f"{mask_scope}-pmids:{MASK_SPLIT}", "sha256": sha256_file(mask_path)})
    if overrides:
        inputs.append({"id": f"overrides:{overrides}", "sha256": sha256_file(Path(overrides))})
    params = {
        "schema": knowledge.SCHEMA,
        "bundle_format": bundle.FORMAT,
        "onset_factor": onset_factor,
        "vocabulary": "E0 (genphenia_v3) genes",
        "mask_split": MASK_SPLIT,
        "mask_scope": mask_scope,
        "associations": "hpo_genes_to_disease without POLYGENIC",
        "onset_lower_years": built["onset_lower_years"],
        "onset_strict": "every OMIM disease of the gene has onset data",
        "obligate": "HP:0040280, 100%, or n/n with n >= 5",
        "negation_factor": bundle.NEGATION_FACTOR,
        "overrides": overrides or None,
        "overrides_applied": len(rows),
    }
    manifest = build_manifest(
        kb_id, "safe-kb", inputs, params, [kb_path, bundle_path, stats_path], state=state
    )
    if publish:
        manifest = publish_release(manifest, kb_id)
    write_manifest(manifest)
    typer.echo(json.dumps({k: v for k, v in stats.items() if not k.startswith("hpoa_")}, indent=1))


@safe_app.command("queue")
def safe_queue(
    kb_id: str = typer.Option(..., "--kb"),
    out: Path = typer.Option(..., help="e.g. results/P2/<kb>/curation_queue.csv"),
) -> None:
    """The curation queue: each sex-limited gene and each gene with a strict earliest onset >= 1 year."""
    from diagnostic_ar_training.lineage import registry
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.safe import queue

    artifact_id = f"curation-queue-{kb_id}"
    ensure_new(artifact_id)
    state = _require_clean()
    kb_path, kb_sha = _kb_output(kb_id, KB_FILE)
    built = kb_io.read(kb_path)
    symbols = {g for g, r in built["genes"].items() if "sex" in r or "onset" in r}
    genereviews = queue.mentions(open_source("genereviews", Purpose.KB), symbols, queue.genereviews_chapter)
    medlineplus = queue.mentions(
        open_source("medlineplus_genetics", Purpose.KB), symbols, queue.medlineplus_page
    )
    table = queue.rows(built, genereviews, medlineplus)
    queue.write(out, table)
    sources = registry.load_sources()
    inputs = [
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        sources["genereviews"].as_input(),
        sources["medlineplus_genetics"].as_input(),
    ]
    params = {"kb": kb_id, "onset_min_years": queue.ONSET_MIN_YEARS, "match": "case-sensitive symbol token"}
    write_manifest(build_manifest(artifact_id, "safe-curation-queue", inputs, params, [out], state=state))
    by_rule = {r: sum(row["rule"] == r for row in table) for r in ("sex", "onset")}
    typer.echo(
        f"{len(table)} rows ({by_rule}); with a GeneReviews file "
        f"{sum(bool(r['genereviews_files']) for r in table)}, with a MedlinePlus page "
        f"{sum(bool(r['medlineplus_files']) for r in table)} -> {out}"
    )


def _run_id(exp: str, label: str, kb_id: str) -> str:
    return f"results-{exp}-{label.replace('/', '-')}-safe-v1-{kb_id}"


def _write_run(exp: str, label: str, kb_id: str, report: dict, records: dict, state, inputs: list[dict]):
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest

    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = [
        path for name, recs in records.items() for path in harness.write(exp, label, name, "all", recs)
    ]
    report_path = out_dir / f"{label.replace('/', '-')}__safe-v1__{kb_id}__report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    params = {"cohort": label, "kb": kb_id, "systems": sorted(records)}
    artifact_id = _run_id(exp, label, kb_id)
    write_manifest(build_manifest(artifact_id, "safe-eval", inputs, params, outputs, state=state))
    return report_path, artifact_id


@safe_app.command("eval")
def safe_eval_cmd(
    kb_id: str = typer.Option(..., "--kb"),
    split: str = typer.Option("r1-v1", help="Split id; the parts read here are free"),
    part: str = typer.Option("dev", help="train or dev"),
    exp: str = typer.Option("EXP-P-001", help="Experiment the dry run belongs to (results/<exp>/)"),
    onset_factor: float | None = typer.Option(
        None, help="Dev variant: multiply onset-incompatible genes by this instead of blocking them"
    ),
    tag: str = typer.Option(
        "", help="Appended to the run label, so a rerun of the same configuration writes new files (e.g. v2)"
    ),
) -> None:
    """Dry run on a free part: safe-v1, each rule alone and sex + onset vs E0, overall and on the subsets."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.eval import safe_eval
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import ensure_new
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.safe.bundle import SafeRules, load
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    try:
        safe_eval.check_free_part(split, part)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    # The knowledge id is part of the label so that runs with different artifacts never share output files.
    label = f"{split}/{part}/{kb_id}" + ("" if onset_factor is None else f"/onset-x{onset_factor:g}")
    if tag:
        if not tag.replace("-", "").replace(".", "").isalnum():
            raise typer.BadParameter("--tag takes letters, digits, '-' and '.' only")
        label += f"/{tag}"
    ensure_new(_run_id(exp, label, kb_id))
    state = _require_clean()
    bundle_path, bundle_sha = _kb_output(kb_id, BUNDLE_FILE)
    bundle = load(bundle_path)
    if onset_factor is not None:
        if not 0 < onset_factor < 1:
            raise typer.BadParameter("--onset-factor must be in (0, 1)")
        bundle = {**bundle, "onset_factor": onset_factor}
    rules = SafeRules(bundle)
    base = GenPheniaV3()
    cases = splits.load_part(split, part, Purpose.EVAL)
    groups = splits.publication_groups(split)
    report, records = safe_eval.evaluate(base, rules, cases, groups)
    report |= {
        "cohort": label,
        "kb": kb_id,
        "bundle_sha256": bundle_sha,
        "onset_factor": onset_factor,
        "code_sha": state.sha,
    }
    inputs = [
        *base.lineage_inputs(),
        {"id": f"artifact:{kb_id}/{BUNDLE_FILE}", "sha256": bundle_sha},
        {"id": f"split:{split}", "sha256": sha256_file(SPLITS_DIR / f"{split}.json")},
    ]
    report_path, artifact_id = _write_run(exp, label, kb_id, report, records, state, inputs)
    typer.echo(f"{label}: {report['cases']} cases, E0 MRR {report['e0']['mrr']:.4f}; {report['identity']}")
    for line in safe_eval.table(report):
        typer.echo(line)
    typer.echo(f"-> {report_path} (manifest {artifact_id})")


@safe_app.command("confirm")
def safe_confirm(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-P-001"),
    split: list[str] = typer.Option(..., help="p2-v1 for test; p2-v1 and p2-fresh-v1 together for vault"),
    part: str = typer.Option(..., help="test (confirmation) or vault (final check, opens once)"),
    kb_id: str = typer.Option(..., "--kb", help="The knowledge artifact the pre-registration names"),
    reason: str = typer.Option("", help="Required"),
) -> None:
    """The sealed read: `DXT_SEALED_READ=<exp> dxt safe confirm --exp <exp> --split p2-v1 --part test --kb
    <id> --reason ...`. The final check reads both vaults in one call: `--split p2-v1 --split p2-fresh-v1
    --part vault`. Every refusal comes before any data is loaded or the ledger touched.
    """
    from diagnostic_ar_training.eval import safe_eval

    try:
        safe_eval.preflight(exp, split, part, reason)
    except (ValueError, LineageError) as e:
        raise typer.BadParameter(str(e)) from e

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import ensure_new
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.safe.bundle import SafeRules, load
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    label = "+".join(split) + f"/{part}/{kb_id}"
    ensure_new(_run_id(exp, label, kb_id))
    state = code_state()
    bundle_path, bundle_sha = _kb_output(kb_id, BUNDLE_FILE)
    rules = SafeRules(load(bundle_path))
    base = safe_eval.Memo(GenPheniaV3())
    by_split = {}
    for split_id in split:
        groups = splits.publication_groups(split_id)
        cases = splits.load_part(split_id, part, Purpose.EVAL, exp, reason)
        by_split[split_id] = (cases, {c.case_id: f"{split_id}:{groups[c.case_id]}" for c in cases})
    cases = [c for cs, _ in by_split.values() for c in cs]
    groups = {k: v for _, g in by_split.values() for k, v in g.items()}
    report, records = safe_eval.evaluate(base, rules, cases, groups)
    if len(by_split) > 1:
        report["components"] = {
            s: safe_eval.evaluate(base, rules, cs, g)[0] for s, (cs, g) in by_split.items()
        }
    report |= {
        "cohort": label,
        "kb": kb_id,
        "bundle_sha256": bundle_sha,
        "code_sha": state.sha,
        "reason": reason,
    }
    inputs = [
        *base.lineage_inputs(),
        {"id": f"artifact:{kb_id}/{BUNDLE_FILE}", "sha256": bundle_sha},
        *({"id": f"split:{s}", "sha256": sha256_file(SPLITS_DIR / f"{s}.json")} for s in split),
    ]
    report_path, artifact_id = _write_run(exp, label, kb_id, report, records, state, inputs)
    for line in safe_eval.table(report):
        typer.echo(line)
    typer.echo(f"-> {report_path} (manifest {artifact_id})")
