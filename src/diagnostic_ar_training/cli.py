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
    mask_split: str = typer.Option("r1-v1", help="Split whose PMIDs are masked"),
    mask_scope: str = typer.Option("heldout", help="heldout (dev/test/vault) or all R1 publications"),
    gene_profiles: str = typer.Option("genes-v1", help="Gene profiles artifact for gene -> disease weights"),
    holdout_annotations: str = typer.Option(
        "", help="Annotation split artifact whose half B is dropped (S3)"
    ),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """Build the knowledge base (schema 2) from pinned sources with held-out publications masked."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(kb_id)
    from diagnostic_ar_training import INTERIM_DIR, splits
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        fetch_outputs,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb

    names = [
        "hpo_ontology",
        "hpo_annotations",
        "hpo_genes_to_disease",
        "hpo_genes_to_phenotype",
        "orphanet_ages_2026_06",
        "orphanet_alignments",
    ]
    paths = {n: open_source(n, Purpose.KB) for n in names}
    profiles_manifest = load_manifest(gene_profiles)
    profiles_path = fetch_outputs(profiles_manifest)[0]
    dropped, holdout_manifest = None, None
    if holdout_annotations:
        from diagnostic_ar_training.knowledge import annotation_split

        holdout_manifest = load_manifest(holdout_annotations)
        dropped = annotation_split.read(fetch_outputs(holdout_manifest)[0])
    splits.write_mask(mask_split, mask_scope)  # refuses if the committed list drifted from the split
    mask_path = splits.mask_path(mask_split, mask_scope)
    masked = set(mask_path.read_text().split())
    built, stats = kb.build(
        Ontology.from_json(paths["hpo_ontology"]),
        paths["hpo_annotations"],
        paths["hpo_genes_to_disease"],
        paths["hpo_genes_to_phenotype"],
        paths["orphanet_ages_2026_06"],
        masked,
        orphanet_alignments=paths["orphanet_alignments"],
        gene_profiles=kb.read(profiles_path),
        drop_annotations=dropped,
    )
    out_dir = INTERIM_DIR / "kb" / kb_id
    kb_path = out_dir / "kb.json.gz"
    kb.write(built, kb_path)
    stats_path = DATA_DIR / "kb" / f"{kb_id}.stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [sources[n].as_input() for n in names]
    inputs.append({"id": f"{mask_scope}-pmids:{mask_split}", "sha256": sha256_file(mask_path)})
    inputs.append({"id": f"artifact:{gene_profiles}", "sha256": profiles_manifest.outputs[0].sha256})
    if holdout_manifest:
        inputs.append({"id": f"artifact:{holdout_annotations}", "sha256": holdout_manifest.outputs[0].sha256})
    params = {
        "mask_split": mask_split,
        "mask_scope": mask_scope,
        "schema": built["schema"],
        "frequency": "ADR-0007",
        "gene_weights": gene_profiles,
        "heldout_annotations_dropped": holdout_annotations or None,
    }
    manifest = build_manifest(kb_id, "rerank-kb", inputs, params, [kb_path, stats_path])
    if publish:
        manifest = publish_release(manifest, kb_id)
    write_manifest(manifest)
    typer.echo(json.dumps(stats, indent=1))


genes_app = typer.Typer(no_args_is_help=True, help="Gene profiles (ADR-0008).")
app.add_typer(genes_app, name="genes")

GENE_SOURCES = [
    "hpo_ontology", "hgnc", "hpo_annotations", "hpo_genes_to_disease", "hpo_genes_to_phenotype",
    "orphanet_genes", "orphanet_alignments", "orphanet_prevalence", "clingen_validity", "mondo",
    "clinvar_variants",
]  # fmt: skip


@genes_app.command("build")
def genes_build(
    genes_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. genes-v1"),
    mask_split: str = typer.Option("r1-v1", help="Split whose held-out PMIDs are masked"),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """Per-gene disease entities, validity, ClinVar evidence, inheritance and weights."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(genes_id)
    from diagnostic_ar_training import INTERIM_DIR, splits
    from diagnostic_ar_training.knowledge import genes
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb
    from diagnostic_ar_training.systems.genphenia_v3 import CHECKPOINT, unpack_bundle

    paths = {n: open_source(n, Purpose.SIMULATE) for n in GENE_SOURCES}
    splits.write_heldout_pmids(mask_split)
    mask_path = splits.heldout_pmids_path(mask_split)
    vocab_path = unpack_bundle() / "checkpoints" / CHECKPOINT / "genes.json"
    built, stats = genes.build(
        Ontology.from_json(paths.pop("hpo_ontology")),
        *paths.values(),
        masked_pmids=set(mask_path.read_text().split()),
        vocabulary=json.loads(vocab_path.read_text()),
    )
    out_path = INTERIM_DIR / "genes" / genes_id / "genes.json.gz"
    kb.write(built, out_path)
    stats_path = DATA_DIR / "genes" / f"{genes_id}.stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [sources[n].as_input() for n in GENE_SOURCES]
    inputs += [
        {"id": f"heldout-pmids:{mask_split}", "sha256": sha256_file(mask_path)},
        sources["genphenia_v3"].as_input(),
    ]
    params = {"mask_split": mask_split, "adr": "0008", "weight": "validity * sqrt(1 + clinvar_plp_alleles)"}
    manifest = build_manifest(genes_id, "gene-profiles", inputs, params, [out_path, stats_path])
    if publish:
        manifest = publish_release(manifest, genes_id)
    write_manifest(manifest)
    typer.echo(json.dumps(stats, indent=1))


@genes_app.command("calibrate")
def genes_calibrate(genes_id: str = typer.Option(..., "--id"), split_id: str = "r1-v1") -> None:
    """Score disease weights against R1-train patients' own diseases (never dev/test/vault)."""
    from diagnostic_ar_training import INTERIM_DIR, RESULTS_DIR, splits
    from diagnostic_ar_training.knowledge import genes
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, load_manifest, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.rerank import kb

    manifest = load_manifest(genes_id)
    built = kb.read(INTERIM_DIR / "genes" / genes_id / "genes.json.gz")
    cases = splits.load_part(split_id, splits.Part.TRAIN, Purpose.TRAIN)
    report = genes.calibration(
        built["genes"], built["vocabulary"], cases, splits.publication_groups(split_id)
    )
    out = RESULTS_DIR / genes_id / "calibration-r1-train.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    inputs = [
        {"id": f"artifact:{genes_id}", "sha256": manifest.outputs[0].sha256},
        {"id": f"split:{split_id}", "sha256": sha256_file(SPLITS_DIR / f"{split_id}.json")},
    ]
    write_manifest(
        build_manifest(f"calibration-{genes_id}", "gene-calibration", inputs, {"part": "train"}, [out])
    )
    typer.echo(json.dumps(report, indent=1))


rerank_app = typer.Typer(no_args_is_help=True, help="Front B re-ranker (rr-v1).")
app.add_typer(rerank_app, name="rerank")


@rerank_app.command("grid")
def rerank_grid(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-B-001"),
    cohort: str = typer.Option("r1-v1/dev"),
    kb_id: str = typer.Option("kb-v3", "--kb"),
    stage1: list[float] = typer.Option([0.5, 1.0, 2.0], help="Stage-1 weights per feature"),
    top_k: int = typer.Option(200),
) -> None:
    """Run the pre-registered rr-v1 weight search; write every configuration's result."""
    from diagnostic_ar_training import RESULTS_DIR, splits
    from diagnostic_ar_training.cohorts import access
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.lineage import ledger
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        fetch_outputs,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import grid, kb
    from diagnostic_ar_training.rerank.features import GeneKnowledge
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    if code_state().dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before the search runs")
    kb_manifest = load_manifest(kb_id)
    knowledge = GeneKnowledge(
        kb.read(fetch_outputs(kb_manifest)[0]), Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    )
    base = GenPheniaV3()
    cases = access.load(cohort)
    groups = splits.publication_groups("r1-v1") if cohort.startswith("r1-v1/") else None
    result = grid.run(cases, base, knowledge, stage1, top_k, groups)

    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = cohort.replace("/", "-")
    outputs = []
    for config in result["configs"]:
        path, _ = harness.write(exp, cohort, f"rr-v1[{config['name']}]", "all", config.pop("records"))
        outputs.append(path)
    report = {
        "cohort": cohort,
        "kb": kb_id,
        "top_k": top_k,
        "stage1_values": stage1,
        "stage2_weights": result["stage2_weights"],
        "configs": result["configs"],
    }
    report_path = out_dir / f"{stem}__rr-v1-grid.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = base.lineage_inputs() + [{"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256}]
    if cohort.startswith("r1-v1/"):
        inputs.append({"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")})
    params = {"cohort": cohort, "kb": kb_id, "stage1": stage1, "top_k": top_k}
    write_manifest(build_manifest(f"results-{exp}-{stem}-rr-v1-grid", "rerank-grid", inputs, params, outputs))
    typer.echo(f"{'config':24} {'MRR':>7} {'dMRR':>8} {'CI95':>18} {'harmed':>7} {'helped':>7}")
    for c in result["configs"]:
        d = c["vs_e0"]
        typer.echo(
            f"{c['name']:24} {c['all']['mrr']:7.4f} {d['delta']:+8.4f} "
            f"[{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}] {d['harmed']:7.3f} {d['helped']:7.3f}"
        )


@rerank_app.command("fit")
def rerank_fit(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-B-002"),
    kb_id: str = typer.Option("kb-v4", "--kb"),
    l2: list[float] = typer.Option([0.01, 0.1, 1.0, 10.0], help="Penalty values, selected on R1-dev"),
    top_k: int = typer.Option(200),
) -> None:
    """Fit rr-v2 on R1-train for each penalty, evaluate on R1-dev; write everything."""
    import numpy as np

    from diagnostic_ar_training import RESULTS_DIR, splits
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.lineage import ledger
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        fetch_outputs,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb, learned
    from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before fitting")
    kb_manifest = load_manifest(kb_id)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(kb_manifest)[0]), ontology)
    base = GenPheniaV3()
    groups = splits.publication_groups("r1-v1")
    parts = {
        "train": splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN),
        "dev": splits.load_part("r1-v1", splits.Part.DEV, Purpose.EVAL),
    }
    tables = {k: [learned.table(base, knowledge, c, top_k) for c in v] for k, v in parts.items()}

    def records(part: str, beta) -> list[dict]:
        lookup = {g.upper(): i for i, g in enumerate(base.genes)}
        out = []
        for case, t in zip(parts[part], tables[part], strict=True):
            probs = t.combine(beta)
            idx = lookup.get(case.gene.upper())
            rank = float("inf")
            if probs is not None and idx is not None:
                rank = float(1 + (probs > probs[idx]).sum() + ((probs == probs[idx]).sum() - 1))
            out.append(
                {
                    "case_id": case.case_id,
                    "group": groups[case.case_id],
                    "gene": case.gene,
                    "rank": rank,
                    "has_excluded": bool(case.excluded),
                    "has_sex": case.sex != "unknown",
                    "has_age": case.age_years is not None,
                    "gene_in_vocab": idx is not None,
                    "scorable": probs is not None,
                    "latency_ms": 0.0,
                }
            )
        return out

    zero = np.zeros(len(COMPONENTS))
    e0 = {part: records(part, zero) for part in parts}
    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    report, outputs = {"kb": kb_id, "top_k": top_k, "components": list(COMPONENTS), "fits": []}, []
    for penalty in l2:
        beta, info = learned.fit(tables["train"], penalty)
        entry = {"l2": penalty, "beta": dict(zip(COMPONENTS, map(float, beta), strict=True)), "fit": info}
        for part in parts:
            recs = records(part, beta)
            entry[part] = {
                "summary": harness.summarize(recs)["all"],
                "vs_e0": harness.compare(e0[part], recs),
            }
            if part == "dev":
                path, _ = harness.write(exp, "r1-v1/dev", f"rr-v2[l2={penalty}]", "all", recs)
                outputs.append(path)
        beta_path = out_dir / f"rr-v2-l2={penalty}.beta.json"
        learned.save_beta(beta, beta_path)
        outputs.append(beta_path)
        report["fits"].append(entry)
        d = entry["dev"]["vs_e0"]
        typer.echo(
            f"l2={penalty:<6} train dMRR={entry['train']['vs_e0']['delta']:+.4f} "
            f"dev dMRR={d['delta']:+.4f} [{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}] "
            f"harmed={d['harmed']:.3f} helped={d['helped']:.3f}"
        )
        typer.echo(f"  beta={np.round(beta, 3).tolist()}")
    # Exploratory (EXP-B-002): ablations of the best-dev penalty. "zeroed" keeps the fitted
    # weights and drops a group at evaluation; "refit" fits again without that group.
    best = max(report["fits"], key=lambda f: f["dev"]["vs_e0"]["delta"])
    best_beta = np.array([best["beta"][c] for c in COMPONENTS])
    groups_of = {
        "negation": ("neg_llr", "neg_annotated_share"),
        "sex": ("sex_prior", "sex_restricted"),
        "age": ("age_mean", "age_any"),
        "onset": ("onset",),
    }
    ablations = []
    for name, members in groups_of.items():
        mask = np.array([c not in members for c in COMPONENTS], dtype=float)
        zeroed = records("dev", best_beta * mask)
        refit_tables = [
            learned.Table(t.probs, t.top, t.x * mask, t.true_pos, t.info) for t in tables["train"]
        ]
        refit_beta, _ = learned.fit(refit_tables, best["l2"])
        refit = records("dev", refit_beta * mask)
        ablations.append(
            {
                "without": name,
                "zeroed": harness.compare(e0["dev"], zeroed),
                "refit": harness.compare(e0["dev"], refit),
                "refit_beta": dict(zip(COMPONENTS, map(float, refit_beta * mask), strict=True)),
            }
        )
        typer.echo(
            f"without {name:9} zeroed dMRR={ablations[-1]['zeroed']['delta']:+.4f} "
            f"refit dMRR={ablations[-1]['refit']['delta']:+.4f} "
            f"[{ablations[-1]['refit']['ci95'][0]:+.4f},{ablations[-1]['refit']['ci95'][1]:+.4f}] "
            f"harmed={ablations[-1]['refit']['harmed']:.3f}"
        )
    report["ablations_exploratory"] = {"l2": best["l2"], "results": ablations}
    report_path = out_dir / "rr-v2-fits.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = base.lineage_inputs() + [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
    ]
    params = {"kb": kb_id, "l2": l2, "top_k": top_k, "fit_on": "r1-v1/train", "selected_on": "r1-v1/dev"}
    write_manifest(
        build_manifest(f"results-{exp}-rr-v2-fits", "rerank-fit", inputs, params, outputs, state=state)
    )


calib_app = typer.Typer(no_args_is_help=True, help="Simulator calibration targets from R1-train.")
app.add_typer(calib_app, name="calib")


@calib_app.command("build")
def calib_build(
    calib_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. calib-v1"),
    kb_id: str = typer.Option("kb-v4", "--kb", help="KB masking every R1 publication"),
    min_noise_count: int = typer.Option(2),
) -> None:
    """Measure R1-train patients: term counts, missingness, negation sources, noise vocabulary."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(calib_id)
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import calibration
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        fetch_outputs,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb
    from diagnostic_ar_training.rerank.features import GeneKnowledge

    state = code_state()
    kb_manifest = load_manifest(kb_id)
    if kb_manifest.params.get("mask_scope") != "all":
        raise typer.BadParameter(f"{kb_id} must mask every R1 publication (mask_scope=all)")
    knowledge = GeneKnowledge(
        kb.read(fetch_outputs(kb_manifest)[0]), Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    )
    cases = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
    targets, rows = calibration.measure(cases, knowledge, min_noise_count)
    out_dir = DATA_DIR / "calib"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets_path = out_dir / f"{calib_id}.targets.json"
    targets_path.write_text(json.dumps(targets, indent=1, sort_keys=True) + "\n")
    vocab_path = out_dir / f"{calib_id}.noise_vocabulary.tsv"
    vocab_path.write_text("hpo_id\tpatients\tweight\n" + "".join(f"{t}\t{k}\t{w:.6f}\n" for t, k, w in rows))
    inputs = [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
    ]
    params = {"part": "train", "kb": kb_id, "min_noise_count": min_noise_count}
    manifest = build_manifest(
        calib_id, "simulator-calibration", inputs, params, [targets_path, vocab_path], state=state
    )
    write_manifest(manifest)
    typer.echo(json.dumps(targets, indent=1))


annotations_app = typer.Typer(no_args_is_help=True, help="Known/held-out annotation splits (S3).")
app.add_typer(annotations_app, name="annotations")


@annotations_app.command("split")
def annotations_split(
    split_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. annot-split-v1"),
    fraction: float = typer.Option(..., help="Share of positive annotations held out (half B)"),
    publish: bool = typer.Option(False),
) -> None:
    """Freeze which HPOA annotations systems under S3 may not know (EVAL_PROTOCOL §8)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(split_id)
    from diagnostic_ar_training import INTERIM_DIR
    from diagnostic_ar_training.knowledge import annotation_split
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source

    salt = f"diagnostic.ar-training/{split_id}"
    pairs = annotation_split.split(open_source("hpo_annotations", Purpose.KB), fraction, salt)
    path = INTERIM_DIR / "annotations" / split_id / "heldout.tsv"
    annotation_split.write(pairs, path)
    params = {"fraction": fraction, "salt": salt, "unit": "(disease_id, hpo_id) positive aspect-P annotation"}
    manifest = build_manifest(
        split_id, "annotation-split", [load_sources()["hpo_annotations"].as_input()], params, [path]
    )
    if publish:
        manifest = publish_release(manifest, split_id)
    write_manifest(manifest)
    typer.echo(f"{split_id}: {len(pairs)} held-out annotations -> {path}")


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
