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


s3_app = typer.Typer(no_args_is_help=True, help="S3: simulated question-agent evaluation (EVAL_PROTOCOL §8).")
app.add_typer(s3_app, name="s3")


@s3_app.command("run")
def s3_run_cmd(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-S3-001"),
    part: str = typer.Option("dev", help="dev, or test (sealed)"),
    reason: str = typer.Option("", help="Required for the sealed part"),
    kb_id: str = typer.Option("kb-v5", "--kb", help="KB without half B, for the questioner and the features"),
    rr2_fits: str = typer.Option(
        "results/EXP-B-002/rr-v2-fits.json", help="rr-v2 fitted weights (EXP-B-002)"
    ),
    n_candidates: int = typer.Option(10),
    n_questions: int = typer.Option(7),
    top_k: int = typer.Option(200),
) -> None:
    """Interview every S3 case once, score every pre-registered system on the same answers."""
    import numpy as np

    from diagnostic_ar_training import REPO_ROOT, RESULTS_DIR
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.eval import harness, s3_run
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
    from diagnostic_ar_training.rerank import kb
    from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before S3 runs")
    kb_manifest = load_manifest(kb_id)
    if kb_manifest.params.get("heldout_annotations_dropped") != "annot-split-v1":
        raise typer.BadParameter(f"{kb_id} must be built without half B of annot-split-v1 (EVAL_PROTOCOL §8)")
    data_manifest = load_manifest("s3-data-v1")
    data = next(p for p in fetch_outputs(data_manifest) if p.name.endswith(".jsonl.gz"))
    pairs = s3.load_part("s3-v1", part, data, exp_id=exp if part in s3.SEALED else None, reason=reason)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(kb_manifest)[0]), ontology)
    e0 = GenPheniaV3()
    interviewed = s3_run.interview_all(pairs, e0, knowledge, ontology, n_candidates, n_questions, top_k)

    fits = json.loads((REPO_ROOT / rr2_fits).read_text())
    chosen = next(f for f in fits["fits"] if f["l2"] == 0.1)
    no_neg = next(a for a in fits["ablations_exploratory"]["results"] if a["without"] == "negation")
    as_vec = lambda d: np.array([d[c] for c in COMPONENTS])  # noqa: E731
    systems = {
        "E0+answers": np.zeros(len(COMPONENTS)),
        "rr-v1[neg=0.5]": s3_run.rr_v1_beta(neg=0.5),
        "rr-v1[neg=1]": s3_run.rr_v1_beta(neg=1.0),
        "rr-v1[neg=2]": s3_run.rr_v1_beta(neg=2.0),
        "rr-v1[all=1]": s3_run.rr_v1_beta(1.0, 1.0, 1.0, 1.0),
        "rr-v2[EXP-B-002 l2=0.1]": as_vec(chosen["beta"]),
        "rr-v2[without negation]": as_vec(no_neg["refit_beta"]),
    }

    def records(probs_of) -> list[dict]:
        return [
            {
                "case_id": i.case_id,
                "group": i.gene,
                "gene": i.gene,
                "rank": s3_run.rank(probs_of(i), e0.genes, i.gene),
                "has_excluded": i.no > 0,
                "has_sex": False,
                "has_age": False,
                "gene_in_vocab": True,
                "scorable": True,
                "latency_ms": 0.0,
            }  # fmt: skip
            for i in interviewed
        ]

    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    base = records(lambda i: i.table.combine(np.zeros(len(COMPONENTS))))
    initial = records(lambda i: i.initial_probs)
    report = {
        "part": part,
        "cases": len(interviewed),
        "kb": kb_id,
        "n_candidates": n_candidates,
        "n_questions": n_questions,
        "questions_per_case": float(np.mean([len(i.questions) for i in interviewed])),
        "yes_per_case": float(np.mean([i.yes for i in interviewed])),
        "no_per_case": float(np.mean([i.no for i in interviewed])),
        "E0-initial": {
            "summary": harness.summarize(initial)["all"],
            "vs_E0+answers": harness.compare(base, initial),
        },
        "systems": {},
    }  # fmt: skip
    outputs = [harness.write(exp, f"s3-v1/{part}", "E0-initial", "interviewed", initial)[0]]
    for name, beta in systems.items():
        recs = records(lambda i, b=beta: i.table.combine(b))
        report["systems"][name] = {
            "beta": dict(zip(COMPONENTS, map(float, beta), strict=True)),
            "summary": harness.summarize(recs)["all"],
            "vs_E0+answers": harness.compare(base, recs),
        }
        outputs.append(harness.write(exp, f"s3-v1/{part}", name, "interviewed", recs)[0])
    report_path = out_dir / f"s3-v1-{part}__report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = e0.lineage_inputs() + [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": "artifact:s3-data-v1", "sha256": sha256_file(data)},
        {"id": "split:s3-v1", "sha256": sha256_file(SPLITS_DIR / "s3-v1.json")},
        {"id": rr2_fits, "sha256": sha256_file(REPO_ROOT / rr2_fits)},
    ]
    params = {
        "part": part,
        "kb": kb_id,
        "n_candidates": n_candidates,
        "n_questions": n_questions,
        "top_k": top_k,
    }
    write_manifest(
        build_manifest(f"results-{exp}-s3-v1-{part}", "s3-run", inputs, params, outputs, state=state)
    )
    typer.echo(f"cases={len(interviewed)} questions/case={report['questions_per_case']:.2f} "
               f"yes/case={report['yes_per_case']:.2f} no/case={report['no_per_case']:.2f}")  # fmt: skip
    ini = report["E0-initial"]
    typer.echo(
        f"{'E0-initial':28} MRR={ini['summary']['mrr']:.4f} "
        f"(vs E0+answers {ini['vs_E0+answers']['delta']:+.4f})"
    )
    typer.echo(f"{'E0+answers':28} MRR={harness.summarize(base)['all']['mrr']:.4f}")
    for name, r in report["systems"].items():
        d = r["vs_E0+answers"]
        typer.echo(
            f"{name:28} MRR={r['summary']['mrr']:.4f} d={d['delta']:+.4f} "
            f"[{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}] harmed={d['harmed']:.3f} helped={d['helped']:.3f}"
        )


@artifacts_app.command("fetch")
def artifacts_fetch(artifact_id: str) -> None:
    """Download a published artifact's files and verify them against its manifest."""
    from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest

    for path in fetch_outputs(load_manifest(artifact_id)):
        typer.echo(path)


def _system(name: str, device: str = "cpu"):
    if name == "genphenia-v3":
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        return GenPheniaV3()
    if name == "ginv3-torch":
        from diagnostic_ar_training.systems.ginv3_torch import GinV3Torch

        return GinV3Torch(device=device)
    raise typer.BadParameter(f"unknown system {name!r}")


@eval_app.command("run")
def eval_run(
    system: str = typer.Option(..., help="genphenia-v3 | ginv3-torch"),
    cohort: str = typer.Option(..., help="r1-v1/<part>, mcrd, ddd or s2"),
    exp: str = typer.Option(..., help="Experiment id, e.g. EXP-000"),
    view: list[str] = typer.Option(["all"], help="Input views (repeatable)"),
    reason: str = typer.Option("", help="Required for sealed cohorts"),
    device: str = typer.Option("cpu", help="Torch systems only: cpu or cuda"),
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
    runner = _system(system, device)
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
            artifact,
            "eval-results",
            inputs,
            {"system": system, "cohort": cohort, "view": v, "device": device},
            list(outputs),
        )
        write_manifest(manifest)
        summary = harness.summarize(records)["all"]
        typer.echo(
            f"{cohort} {v}: n={summary['n']} mrr={summary['mrr']:.4f} top1={summary['top1']:.4f} "
            f"top10={summary['top10']:.4f} -> {outputs[1]}"
        )


@eval_app.command("compare")
def eval_compare(
    base: Path = typer.Option(..., help="E0 ranks file, e.g. results/EXP-000/<stem>.ranks.jsonl"),
    new: Path = typer.Option(..., help="Candidate ranks file on the same cases"),
    exp: str = typer.Option(..., help="Experiment the comparison belongs to"),
) -> None:
    """Paired Δ MRR (publication bootstrap on R1), harmed/helped and identical ranks; no cohort is read."""
    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.eval import harness
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest

    a, b = harness.read(base), harness.read(new)
    delta = harness.compare(a, b)
    rank_b = {r["case_id"]: r["rank"] for r in b}
    changed = [r["case_id"] for r in a if r["rank"] != rank_b[r["case_id"]]]
    report = {"base": str(base), "new": str(new), "n": len(a), "identical_ranks": len(a) - len(changed)}
    report |= {"changed_cases": changed, "mrr": delta}
    stem = f"{new.name.removesuffix('.ranks.jsonl')}__vs__{base.name.removesuffix('.ranks.jsonl')}"
    out = RESULTS_DIR / exp / f"{stem}.compare.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    inputs = [{"id": f"results:{p.parent.name}/{p.name}", "sha256": sha256_file(p)} for p in (base, new)]
    write_manifest(build_manifest(f"compare-{exp}-{stem}", "eval-compare", inputs, {}, [out]))
    typer.echo(
        f"identical ranks {report['identical_ranks']}/{report['n']}; dMRR {delta['delta']:+.6f} {delta}"
    )


gnn_app = typer.Typer(no_args_is_help=True, help="Front A GNN (PyTorch).")
app.add_typer(gnn_app, name="gnn")


@gnn_app.command("parity")
def gnn_parity(
    exp: str = typer.Option("EXP-A-000", help="Pre-registered experiment id"),
    n: int = typer.Option(1000, help="R1-train cases to sample"),
    seed: int = typer.Option(20260929),
    device: str = typer.Option("cpu"),
    batch_size: int = typer.Option(128),
) -> None:
    """Torch GinV3 vs the production ONNX on a seeded R1-train sample: logits, top-10, ranks, timings."""
    import tempfile

    import onnxruntime as ort

    from diagnostic_ar_training import RESULTS_DIR, splits
    from diagnostic_ar_training.gnn import export, parity
    from diagnostic_ar_training.lineage import ledger
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3
    from diagnostic_ar_training.systems.ginv3_torch import GinV3Torch

    if code_state().dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before the run")
    e0, system = GenPheniaV3(), GinV3Torch(device=device)
    cases = parity.sample_scorable(splits.load_part("r1-v1", "train", Purpose.EVAL), e0, n, seed)
    with tempfile.TemporaryDirectory() as tmp:
        onnx_path = export.export_v3(system.model, Path(tmp) / "ginv3.onnx")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        reexport = ort.InferenceSession(str(onnx_path), options, providers=["CPUExecutionProvider"])
    summary, rows = parity.run(e0, system, cases, batch_size, reexport=reexport)
    summary |= {"seed": seed, "sample": "r1-v1/train", "torch": system.torch.__version__}
    if system.device.type == "cuda":
        summary["gpu"] = system.torch.cuda.get_device_name(system.device)
    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"parity-r1-v1-train-n{n}-s{seed}-{system.device.type}"
    summary_path, rows_path = out_dir / f"{stem}.json", out_dir / f"{stem}.cases.jsonl"
    summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True, default=str) + "\n")
    rows_path.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows))
    inputs = system.lineage_inputs() + [
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")}
    ]
    params = {"n": n, "seed": seed, "device": device, "batch_size": batch_size}
    write_manifest(
        build_manifest(f"results-{exp}-{stem}", "gnn-parity", inputs, params, [summary_path, rows_path])
    )
    typer.echo(json.dumps(summary, indent=1, default=str))


S3_INTERVIEWS_DIR = DATA_DIR / "interim" / "s3-interviews"


@s3_app.command("interviews")
def s3_interviews(
    kb_id: str = typer.Option("kb-v5", "--kb", help="KB without half B, for the questioner"),
    n_candidates: int = typer.Option(10),
    n_questions: int = typer.Option(7),
) -> None:
    """Interview S3-dev once, as `dxt s3 run` does, and keep the interviewed cases for Front A runs.

    Writes the cases systems receive (present + "yes", "no" as excluded) with a manifest, and checks that
    E0 on them reproduces EXP-S3-001's E0+answers ranks. S3-test is never read here.
    """
    import numpy as np

    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.eval import harness, s3_run
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        ensure_new,
        fetch_outputs,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb
    from diagnostic_ar_training.rerank.features import GeneKnowledge
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    artifact = f"s3-v1-dev-interviews-{kb_id}-c{n_candidates}-q{n_questions}"
    ensure_new(artifact)
    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    kb_manifest = load_manifest(kb_id)
    if kb_manifest.params.get("heldout_annotations_dropped") != "annot-split-v1":
        raise typer.BadParameter(f"{kb_id} must be built without half B of annot-split-v1 (EVAL_PROTOCOL §8)")
    data_manifest = load_manifest("s3-data-v1")
    dataset = next(p for p in fetch_outputs(data_manifest) if p.name.endswith(".jsonl.gz"))
    pairs = s3.load_part("s3-v1", "dev", dataset)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(kb_manifest)[0]), ontology)
    e0 = GenPheniaV3()
    interviews = s3_run.interview_cases(pairs, e0, knowledge, ontology, n_candidates, n_questions)
    path = S3_INTERVIEWS_DIR / f"{artifact}.jsonl.gz"
    s3_run.write_interviews(path, interviews)

    reference = {r["case_id"]: r["rank"] for r in harness.read(
        RESULTS_DIR / "EXP-S3-001" / "s3-v1-dev__E0+answers__interviewed.ranks.jsonl")}  # fmt: skip
    after = s3_run.read_interviews(path)
    ranks = {c.case_id: s3_run.rank(e0.score(c).probs, e0.genes, c.gene) for c in after}
    if set(ranks) != set(reference):
        raise LineageError("the interviewed cases are not EXP-S3-001's S3-dev cases")
    identical = sum(ranks[k] == reference[k] for k in ranks)
    params = {
        "part": "dev",
        "kb": kb_id,
        "n_candidates": n_candidates,
        "n_questions": n_questions,
        "cases": len(after),
        "questions_per_case": float(np.mean([len(i.questions) for i in interviews])),
        "yes_per_case": float(np.mean([i.yes for i in interviews])),
        "no_per_case": float(np.mean([len(i.after.excluded) for i in interviews])),
        "e0_ranks_identical_to_EXP-S3-001": identical,
    }
    inputs = e0.lineage_inputs() + [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": "artifact:s3-data-v1", "sha256": sha256_file(dataset)},
        {"id": "split:s3-v1", "sha256": sha256_file(SPLITS_DIR / "s3-v1.json")},
    ]
    write_manifest(build_manifest(artifact, "s3-interviews", inputs, params, [path], state=state))
    typer.echo(json.dumps(params, indent=1))
    if identical != len(after):
        raise typer.Exit(1)


def _gnn_setup(device_name: str, workers: int):
    import torch

    from diagnostic_ar_training.gnn import data
    from diagnostic_ar_training.gnn.model import load_v3
    from diagnostic_ar_training.systems.genphenia_v3 import V3Inputs, unpack_bundle

    device = torch.device(device_name)
    inputs = V3Inputs(unpack_bundle())
    table = torch.from_numpy(data.embedding_table(inputs)).to(device)
    base = load_v3(inputs.root, map_location=device)
    torch.set_num_threads(max(1, (torch.get_num_threads() - workers) or 1))
    return torch, device, inputs, table, base


@gnn_app.command("throughput")
def gnn_throughput(
    batches: int = typer.Option(60, help="Batches per measurement"),
    batch_size: int = typer.Option(256),
    workers: list[int] = typer.Option([0, 4, 10], help="Loader worker counts to measure"),
    device: str = typer.Option("cuda"),
) -> None:
    """Loader and training-step throughput on the simulated training split. Reads no evaluation cohort."""
    import time

    from diagnostic_ar_training.gnn import data, experiment
    from diagnostic_ar_training.gnn import train as training

    torch, dev, inputs, table, base = _gnn_setup(device, max(workers))
    training_data = experiment.load_training_data()
    dataset = data.SimGraphs(inputs, training_data.splits["train"])
    report = {"batch_size": batch_size, "loader_cases_per_s": {}}
    for k in workers:
        loader = iter(data.loader(dataset, batch_size, 0, k))
        next(loader)
        start, n = time.perf_counter(), 0
        for _ in range(batches):
            n += int(next(loader)["target"].numel())
        report["loader_cases_per_s"][k] = n / (time.perf_counter() - start)
    batch = data.to_device(data.collate([dataset[i] for i in range(batch_size)]), table, dev)
    for amp in (False, True):
        cfg = training.TrainConfig(amp=amp)
        model = training.build_model(base, cfg)
        training.set_train_mode(model, cfg.bn)
        optimizer = torch.optim.AdamW(training.param_groups(model, cfg), weight_decay=cfg.weight_decay)
        for i in range(batches + 5):
            if i == 5:
                torch.cuda.synchronize(dev) if dev.type == "cuda" else None
                start = time.perf_counter()
            with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=amp and dev.type == "cuda"):
                logits = training.forward(model, batch)
            loss = torch.nn.functional.cross_entropy(logits.float(), batch["target"])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        torch.cuda.synchronize(dev) if dev.type == "cuda" else None
        report[f"train_step_cases_per_s_amp_{amp}"] = batches * batch_size / (time.perf_counter() - start)
    if dev.type == "cuda":
        report["gpu"] = torch.cuda.get_device_name(dev)
        report["max_memory_gb"] = torch.cuda.max_memory_allocated(dev) / 1e9
    typer.echo(json.dumps(report, indent=1))


@gnn_app.command("train")
def gnn_train(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-A-001"),
    run_id: str = typer.Option(..., help="Unique run id, e.g. a001-lr5e-5-bntrain-s0"),
    lr_base: float = typer.Option(..., help="Learning rate of v3.0's tensors (≤ 5e-4)"),
    lr_new: float = typer.Option(0.0, help="Learning rate of the new zero-init tensors; 0 freezes them"),
    bn: str = typer.Option("train", help="BatchNorm: train (batch stats) or frozen (v3.0's running stats)"),
    seed: int = typer.Option(0),
    max_epochs: int = typer.Option(6),
    patience: int = typer.Option(2),
    batch_size: int = typer.Option(256),
    warmup_steps: int = typer.Option(200),
    amp: bool = typer.Option(False, help="bf16 autocast on CUDA"),
    workers: int = typer.Option(10),
    s3_interviews: str = typer.Option(
        "s3-v1-dev-interviews-kb-v5-c10-q7", help="Artifact of interviewed S3-dev cases ('' to skip S3-dev)"
    ),
    max_train_cases: int = typer.Option(0, help="Debug only: cap the training cases (0 = all)"),
    device: str = typer.Option("cuda"),
) -> None:
    """Fine-tune v3.0 on the simulated training split; curves each epoch; best/last checkpoints; manifest."""
    import time

    from diagnostic_ar_training import RESULTS_DIR, splits
    from diagnostic_ar_training.cohorts import access
    from diagnostic_ar_training.eval import s3_run
    from diagnostic_ar_training.gnn import data, experiment
    from diagnostic_ar_training.gnn import train as training
    from diagnostic_ar_training.lineage import ledger
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        ensure_new,
        load_manifest,
        output_path,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose
    from diagnostic_ar_training.systems.ginv3_torch import GinModelSystem

    wall_start = time.perf_counter()
    artifact = f"results-{exp}-{run_id}"
    ensure_new(artifact)
    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before the run")
    out_dir = RESULTS_DIR / exp / run_id
    ckpt_dir = DATA_DIR / "interim" / "models" / run_id
    if out_dir.exists() or ckpt_dir.exists():
        raise typer.BadParameter(f"{out_dir} or {ckpt_dir} exists; run ids are never reused")
    cfg = training.TrainConfig(
        lr_base=lr_base,
        lr_new=lr_new,
        bn=bn,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
        batch_size=batch_size,
        warmup_steps=warmup_steps,
        amp=amp,
        num_workers=workers,
        max_train_cases=max_train_cases or None,
    )
    torch, dev, inputs, table, base = _gnn_setup(device, workers)

    training_data = experiment.load_training_data()
    train_cases = training_data.splits["train"]
    if cfg.max_train_cases:
        train_cases = train_cases[: cfg.max_train_cases]
    r1_dev = splits.load_part("r1-v1", "dev", Purpose.EVAL)
    s3_dev, s3_lineage = None, []
    if s3_interviews:
        s3_manifest = load_manifest(s3_interviews)
        s3_path = output_path(s3_manifest.outputs[0])
        if sha256_file(s3_path) != s3_manifest.outputs[0].sha256:
            raise LineageError(f"{s3_path} does not match {s3_interviews}'s manifest")
        s3_dev = s3_run.read_interviews(s3_path)
        s3_lineage = [{"id": f"artifact:{s3_interviews}", "sha256": s3_manifest.outputs[0].sha256}]
    sets = experiment.EvalSets(
        sim_val=data.SimGraphs(inputs, training_data.splits["val"], negated=cfg.negated),
        r1_dev=r1_dev,
        r1_groups=splits.publication_groups("r1-v1"),
        s2=access.load("s2"),
        s3_dev=s3_dev,
    )
    contamination = experiment.check_contamination(
        training_data.splits["train"] + training_data.splits["val"],
        {
            "r1-v1/train": splits.load_part("r1-v1", "train", Purpose.EVAL),
            "r1-v1/dev": r1_dev,
            **({"s3-v1/dev": s3_dev} if s3_dev else {}),
        },
    )
    if any(v["present_set_overlap"] for v in contamination.values()):
        raise LineageError(f"training cases overlap evaluation cases after the exclusion: {contamination}")
    contamination["sealed_cohorts"] = "certified 0 by the exclusion artifact's manifest (not read here)"
    contamination["s2 (reported, not required 0)"] = experiment.check_contamination(
        training_data.splits["train"], {"s2": sets.s2}
    )["s2"]
    baselines = sets.baselines()
    name = f"{exp}-{run_id}"

    def evaluate(model, epoch: int) -> dict:
        sim = training.evaluate_sim(model, sets.sim_val, table, dev, cfg)
        metrics, _ = experiment.score_cohorts(
            GinModelSystem(model, inputs, name, cfg.negated), sets, baselines, s3=False
        )
        typer.echo(
            f"[{run_id}] epoch {epoch}: sim-val loss {sim['loss']:.4f} mrr {sim['mrr']:.4f} | "
            f"R1-dev {metrics['r1_dev_present']['mrr']:.4f} (Δ {metrics['r1_dev_present']['delta']:+.4f}) | "
            f"S2 {metrics['s2']['mrr']:.4f}"
        )
        return {"sim_val": sim, **metrics}

    out_dir.mkdir(parents=True)
    run_info = {
        "exp": exp,
        "run_id": run_id,
        "config": cfg.__dict__,
        "code": state.as_dict(),
        "device": torch.cuda.get_device_name(dev) if dev.type == "cuda" else "cpu",
        "torch": torch.__version__,
        "data_counts": training_data.counts,
        "train_cases": len(train_cases),
        "contamination": contamination,
    }
    training.write_json(out_dir / "run.json", run_info)
    curves_path = out_dir / "curves.json"
    if dev.type == "cuda":
        torch.cuda.reset_peak_memory_stats(dev)
    model = training.build_model(base, cfg)
    result = training.train(
        model,
        cfg,
        data.SimGraphs(inputs, train_cases, negated=cfg.negated),
        table,
        dev,
        evaluate,
        ckpt_dir,
        on_epoch=lambda history: training.write_json(curves_path, history),
    )
    best_epoch = training.load_checkpoint(model, ckpt_dir / "best.pt")
    model.eval()
    final, records = experiment.score_cohorts(
        GinModelSystem(model, inputs, name, cfg.negated), sets, baselines, s3=True
    )
    outputs = [curves_path, out_dir / "run.json"]
    outputs += list(harness_write(out_dir, "r1-v1-dev", "present", records["r1_dev_present"]))
    outputs.append(experiment.write_compact_ranks(out_dir / "s2.ranks.jsonl", records["s2"]))
    if "s3_dev_present" in records:
        s3_path = out_dir / "s3-v1-dev.ranks.jsonl"
        outputs.append(experiment.write_compact_ranks(s3_path, records["s3_dev_present"]))
    summary = {
        **{k: v for k, v in result.items() if k != "history"},
        "best_epoch_reloaded": best_epoch,
        "at_best": final,
        "sim_val_at_best": next(h for h in result["history"] if h["epoch"] == best_epoch)["sim_val"],
        "flags": experiment.flags(result["history"], best_epoch),
        "wall_seconds": time.perf_counter() - wall_start,
        "max_gpu_memory_gb": torch.cuda.max_memory_allocated(dev) / 1e9 if dev.type == "cuda" else None,
        "checkpoints": {p.name: p.stat().st_size for p in sorted(ckpt_dir.glob("*.pt"))},
    }
    summary_path = out_dir / "summary.json"
    training.write_json(summary_path, summary)
    outputs.append(summary_path)
    inputs_refs = GinModelSystem(model, inputs, name).lineage_inputs() + training_data.lineage
    inputs_refs += sets.lineage() + s3_lineage
    params = {**cfg.__dict__, "exp": exp, "run_id": run_id, "device": device}
    checkpoints = [ckpt_dir / "best.pt", ckpt_dir / "last.pt"]
    write_manifest(
        build_manifest(
            artifact,
            "gnn-training-run",
            inputs_refs,
            params,
            outputs + [p for p in checkpoints if p.exists()],
            notes="Checkpoints stay local (data/interim/models); results are committed.",
            state=state,
        )
    )
    r1, s2 = final["r1_dev_present"], final["s2"]
    typer.echo(
        f"[{run_id}] best epoch {best_epoch}/{result['epochs_run']}: "
        f"R1-dev {r1['mrr']:.4f} Δ {r1['delta']:+.4f} "
        f"[{r1['ci95'][0]:+.4f},{r1['ci95'][1]:+.4f}] harmed {r1['harmed']:.3f} | S2 {s2['mrr']:.4f} | "
        f"flags {summary['flags']} | {summary['wall_seconds'] / 60:.1f} min"
    )


def harness_write(out_dir: Path, cohort: str, view: str, records: list[dict]) -> tuple[Path, Path]:
    from diagnostic_ar_training.eval import harness

    return harness.write(f"{out_dir.parent.name}/{out_dir.name}", cohort, "model", view, records)


@gnn_app.command("report")
def gnn_report(exp: str = typer.Option("EXP-A-001", help="Experiment whose runs to tabulate")) -> None:
    """The experiment table from the committed run files: every run, and mean ± sd per configuration."""
    import re

    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.gnn import experiment
    from diagnostic_ar_training.lineage.hashing import sha256_file

    training_data = experiment.load_training_data()
    trained_genes = {c.gene.upper() for c in training_data.splits["train"]}
    exp_dir = RESULTS_DIR / exp
    run_dirs = sorted(p for p in exp_dir.iterdir() if (p / "summary.json").is_file())
    rows = [experiment.run_row(p, trained_genes) for p in run_dirs]
    by_config: dict[str, list[dict]] = {}
    for row in rows:
        by_config.setdefault(re.sub(r"-s\d+$", "", row["run_id"]), []).append(row)
    report = {
        "runs": rows,
        "configurations": {k: experiment.seed_aggregate(v) for k, v in by_config.items()},
        "inputs": {
            str(p.relative_to(RESULTS_DIR)): sha256_file(p)
            for d in run_dirs
            for p in sorted(d.glob("*.json"))
        },
    }
    out = exp_dir / "report.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    for r in rows:
        d, s3 = r["r1_dev"], r["s3_dev"] or {}
        typer.echo(
            f"{r['run_id']:32} ep {r['best_epoch']}/{r['epochs_run']} simval {r['sim_val_mrr']['best']:.4f} "
            f"R1 {d['mrr']:.4f} d {d['delta']:+.4f} [{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}] "
            f"h {d['harmed']:.3f} S2 {r['s2']['mrr']:.4f} S3 d {s3.get('delta', float('nan')):+.4f}"
        )
    typer.echo(f"-> {out}")


@gnn_app.command("s1")
def gnn_s1(
    exp: str = typer.Option(..., help="Pre-registered experiment id"),
    run_id: str = typer.Option(..., help="The selected run"),
    workers: int = typer.Option(10),
    device: str = typer.Option("cuda"),
) -> None:
    """S1 (the simulator's own test split), once, for the selected run: v3.0 and the run's best checkpoint."""
    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.gnn import data, experiment
    from diagnostic_ar_training.gnn import train as training
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest

    artifact = f"results-{exp}-{run_id}-s1"
    ensure_new(artifact)
    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    torch, dev, inputs, table, base = _gnn_setup(device, workers)
    run = json.loads((RESULTS_DIR / exp / run_id / "run.json").read_text())
    cfg = training.TrainConfig(**{**run["config"], "num_workers": workers})
    training_data = experiment.load_training_data()
    s1 = data.SimGraphs(inputs, training_data.splits["test"], negated=cfg.negated)
    model = training.build_model(base, cfg).eval()
    report = {"cases": len(s1), "e0": training.evaluate_sim(model, s1, table, dev, cfg)}
    ckpt = DATA_DIR / "interim" / "models" / run_id / "best.pt"
    report["best_epoch"] = training.load_checkpoint(model, ckpt)
    report["model"] = training.evaluate_sim(model, s1, table, dev, cfg)
    report["delta_mrr"] = report["model"]["mrr"] - report["e0"]["mrr"]
    out = RESULTS_DIR / exp / run_id / "s1.json"
    training.write_json(out, report)
    refs = training_data.lineage + [{"id": f"checkpoint:{run_id}/best.pt", "sha256": sha256_file(ckpt)}]
    write_manifest(build_manifest(artifact, "gnn-s1-eval", refs, {"run_id": run_id}, [out], state=state))
    typer.echo(json.dumps(report, indent=1))


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
