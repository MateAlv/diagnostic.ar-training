"""`dxt`: sources, splits and lineage checks. Run `dxt --help`."""

import json
from collections import Counter
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, MANIFESTS_DIR, SPLITS_DIR
from diagnostic_ar_training.cli_lit import lit_app
from diagnostic_ar_training.cli_lit_extract import extract_app
from diagnostic_ar_training.cli_sim import knowledge_app, sim_app
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
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(sim_app, name="sim")
app.add_typer(lit_app, name="lit-sources")
app.add_typer(extract_app, name="lit")


@kb_app.command("build")
def kb_build(
    kb_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. kb-v1"),
    mask_split: str = typer.Option("r1-v1", help="Split whose PMIDs are masked"),
    mask_scope: str = typer.Option("heldout", help="heldout (dev/test/vault) or all R1 publications"),
    gene_profiles: str = typer.Option("genes-v1", help="Gene profiles artifact for gene -> disease weights"),
    holdout_annotations: str = typer.Option(
        "", help="Annotation split artifact whose half B is dropped (S3)"
    ),
    hpoa_artifact: str = typer.Option(
        "",
        help="phenotype.hpoa artifact (e.g. hpoa-enriched-v2) read instead of the pinned hpo_annotations "
        "source; onset (aspect C), inheritance (aspect I) and Orphanet onset still come from the same places",
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
    if hpoa_artifact:
        names.remove("hpo_annotations")
    paths = {n: open_source(n, Purpose.KB) for n in names}
    hpoa_manifest = None
    if hpoa_artifact:
        hpoa_manifest = load_manifest(hpoa_artifact)
        paths["hpo_annotations"] = fetch_outputs(hpoa_manifest)[0]
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
    if hpoa_manifest:
        inputs.append({"id": f"artifact:{hpoa_artifact}", "sha256": hpoa_manifest.outputs[0].sha256})
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
    if hpoa_artifact:
        params["hpoa_artifact"] = hpoa_artifact
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
    scheme: str = typer.Option(
        "v1", help="v1 (ADR-0008) or v2 (ADR-0011 §2: + R1-train patients, zero rules)"
    ),
    hpoa_artifact: str = typer.Option("", help="hpoa-recount artifact to take profiles from (scheme v2)"),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """Per-gene disease entities, validity, ClinVar evidence, inheritance and weights."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(genes_id)
    from diagnostic_ar_training import INTERIM_DIR, splits
    from diagnostic_ar_training.knowledge import genes
    from diagnostic_ar_training.lineage.gitinfo import code_state
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
    from diagnostic_ar_training.systems.genphenia_v3 import CHECKPOINT, unpack_bundle

    if scheme == "v2" and not hpoa_artifact:
        raise typer.BadParameter(
            "scheme v2 takes its profiles from an hpoa-recount artifact (--hpoa-artifact)"
        )
    state = code_state()
    paths = {n: open_source(n, Purpose.SIMULATE) for n in GENE_SOURCES}
    extra_inputs, diagnoses = [], []
    if hpoa_artifact:
        recount_manifest = load_manifest(hpoa_artifact)
        recount_out = dict(
            zip((o.path for o in recount_manifest.outputs), recount_manifest.outputs, strict=True)
        )
        hpoa_path = next(p for p in fetch_outputs(recount_manifest) if p.name == "phenotype.hpoa")
        paths["hpo_annotations"] = hpoa_path
        sha = next(o.sha256 for k, o in recount_out.items() if k.endswith("phenotype.hpoa"))
        extra_inputs.append({"id": f"artifact:{hpoa_artifact}", "sha256": sha})
    if scheme == "v2":
        cases = splits.load_part(mask_split, splits.Part.TRAIN, Purpose.SIMULATE)
        diagnoses = [(c.gene, c.disease_ids) for c in cases]
        extra_inputs.append(
            {"id": f"split:{mask_split}", "sha256": sha256_file(SPLITS_DIR / f"{mask_split}.json")}
        )
    splits.write_heldout_pmids(mask_split)
    mask_path = splits.heldout_pmids_path(mask_split)
    vocab_path = unpack_bundle() / "checkpoints" / CHECKPOINT / "genes.json"
    built, stats = genes.build(
        Ontology.from_json(paths.pop("hpo_ontology")),
        *paths.values(),
        masked_pmids=set(mask_path.read_text().split()),
        vocabulary=json.loads(vocab_path.read_text()),
        scheme=scheme,
        r1_train_diagnoses=diagnoses,
    )
    out_path = INTERIM_DIR / "genes" / genes_id / "genes.json.gz"
    kb.write(built, out_path)
    stats_path = DATA_DIR / "genes" / f"{genes_id}.stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [sources[n].as_input() for n in GENE_SOURCES if not (hpoa_artifact and n == "hpo_annotations")]
    inputs += [
        {"id": f"heldout-pmids:{mask_split}", "sha256": sha256_file(mask_path)},
        sources["genphenia_v3"].as_input(),
        *extra_inputs,
    ]
    params = {"mask_split": mask_split, "adr": "0008", "weight": "validity * sqrt(1 + clinvar_plp_alleles)"}
    if scheme == "v2":
        params = {
            "mask_split": mask_split,
            "adr": "0008 + 0011 §2",
            "scheme": "v2",
            "profiles_from": hpoa_artifact,
            "weight": "validity * sqrt(1 + clinvar_plp_alleles + r1_train_patients)",
            "r1_train_patients": "R1-train patients of this gene diagnosed with any id of the entity",
            "zero_weight": "somatic_only (Orphanet associations all somatic, no ClinGen); validity_zero; "
            "no_supporting_evidence (no ClinVar P/LP, Orphanet product-6 association, ClinGen curation "
            "or R1-train patient)",
        }
    manifest = build_manifest(genes_id, "gene-profiles", inputs, params, [out_path, stats_path], state=state)
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
    groups = splits.publication_groups(split_id)
    report = genes.calibration(built["genes"], built["vocabulary"], cases, groups)
    if manifest.params.get("scheme") == "v2":
        report = {
            "adr0008_gamma": report,
            "v2": genes.calibration_v2(built["genes"], built["vocabulary"], cases, groups),
        }
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


@rerank_app.command("eval")
def rerank_eval(
    exp: str = typer.Option(..., help="Pre-registered experiment id"),
    cohort: str = typer.Option(
        ..., help="e.g. r1-v1/test (sealed: needs --reason and DXT_SEALED_READ=<exp> in the environment)"
    ),
    reason: str = typer.Option("", help="Required for a sealed cohort"),
    kb_id: str = typer.Option("kb-v3", "--kb"),
    neg: float = typer.Option(0.0),
    sex: float = typer.Option(0.0),
    age: float = typer.Option(0.0),
    onset: float = typer.Option(0.0),
    top_k: int = typer.Option(200),
) -> None:
    """One fixed rr-v1 configuration vs E0 on a cohort, as given and with excluded terms removed.

    A sealed cohort is read only with DXT_SEALED_READ=<exp> set to the same experiment id, e.g.
    `DXT_SEALED_READ=EXP-B-003 dxt rerank eval --exp EXP-B-003 --cohort r1-v1/test --reason ...`.
    """

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
    from diagnostic_ar_training.rerank.model import Weights, feature_table
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before the run")
    kb_manifest = load_manifest(kb_id)
    knowledge = GeneKnowledge(
        kb.read(fetch_outputs(kb_manifest)[0]), Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    )
    base = GenPheniaV3()
    cases = access.load(cohort, exp_id=exp, reason=reason)
    groups = splits.publication_groups("r1-v1") if cohort.startswith("r1-v1/") else None
    weights = Weights(neg=neg, sex=sex, age=age, onset=onset)
    name = "rr-v1[" + ",".join(f"{k}={v:g}" for k, v in weights.as_dict().items() if v) + "]"

    out_dir = RESULTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = cohort.replace("/", "-")
    report: dict = {"cohort": cohort, "kb": kb_id, "top_k": top_k, "system": name, "views": {}}
    outputs = []
    views = {"all": cases, "present": [c.model_copy(update={"excluded": ()}) for c in cases]}
    for view, view_cases in views.items():
        tables = [feature_table(base, knowledge, c, top_k) for c in view_cases]
        e0 = grid._records(view_cases, tables, base.genes, Weights(), groups)
        recs = grid._records(view_cases, tables, base.genes, weights, groups)
        with_excluded = [r for r in recs if r["has_excluded"]]
        e0_with_excluded = [r for r in e0 if r["has_excluded"]]
        report["views"][view] = {
            "summary": harness.summarize(recs)["all"],
            "vs_e0": harness.compare(e0, recs),
            "cases_with_excluded": len(with_excluded),
            "vs_e0_cases_with_excluded": harness.compare(e0_with_excluded, with_excluded)
            if with_excluded
            else None,
        }
        outputs.append(harness.write(exp, cohort, "E0", view, e0)[0])
        outputs.append(harness.write(exp, cohort, name, view, recs)[0])
    report_path = out_dir / f"{stem}__{name}__report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = base.lineage_inputs() + [{"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256}]
    if cohort.startswith("r1-v1/"):
        inputs.append({"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")})
    params = {"cohort": cohort, "kb": kb_id, "weights": weights.as_dict(), "top_k": top_k}
    write_manifest(
        build_manifest(f"results-{exp}-{stem}-{name}", "rerank-eval", inputs, params, outputs, state=state)
    )
    for view, v in report["views"].items():
        d = v["vs_e0"]
        typer.echo(
            f"{view:8} MRR {v['summary']['mrr']:.4f} dMRR {d['delta']:+.4f} "
            f"[{d['ci95'][0]:+.4f},{d['ci95'][1]:+.4f}] harmed {d['harmed']:.3f} helped {d['helped']:.3f}"
        )


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
    population: str = typer.Option(
        "all",
        help="R1-train patients measured: all, or uncited (publications the pinned HPOA does not cite; "
        "then the KB may mask only held-out PMIDs, e.g. kb-v3, as their papers fed no annotation)",
    ),
    vocabulary: str = typer.Option(
        "unexplained",
        help="Noise vocabulary terms: every unexplained term (calib-v1), or related_or_weak "
        "(leaving more specific terms to the simulator's specialisation)",
    ),
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
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb
    from diagnostic_ar_training.rerank.features import GeneKnowledge

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    if population not in calibration.POPULATIONS:
        raise typer.BadParameter(f"population must be one of {calibration.POPULATIONS}")
    if vocabulary not in calibration.VOCABULARY_RULES:
        raise typer.BadParameter(f"vocabulary must be one of {calibration.VOCABULARY_RULES}")
    kb_manifest = load_manifest(kb_id)
    mask_scope = kb_manifest.params.get("mask_scope", "heldout")
    if kb_manifest.params.get("mask_split") != "r1-v1":
        raise typer.BadParameter(f"{kb_id} must mask split r1-v1")
    if population == "all" and mask_scope != "all":
        raise typer.BadParameter(f"{kb_id} must mask every R1 publication (mask_scope=all) for all patients")
    kb_data = kb.read(fetch_outputs(kb_manifest)[0])
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb_data, ontology)
    train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
    extra_inputs = []
    if population == "uncited":
        extra_inputs.append(load_sources()["hpo_annotations"].as_input())
        cited = calibration.cited_pmids(open_source("hpo_annotations", Purpose.KB))
        cases = calibration.select_population(train, population, cited)
    else:
        cases = calibration.select_population(train, population)
    categories = calibration.TermCategories(kb_data, knowledge, ontology)
    targets, rows = calibration.measure(cases, knowledge, min_noise_count, categories, vocabulary)
    targets["population"] = {"rule": population, "r1_train_cases": len(train), "cases": len(cases)}
    out_dir = DATA_DIR / "calib"
    out_dir.mkdir(parents=True, exist_ok=True)
    targets_path = out_dir / f"{calib_id}.targets.json"
    targets_path.write_text(json.dumps(targets, indent=1, sort_keys=True) + "\n")
    vocab_path = out_dir / f"{calib_id}.noise_vocabulary.tsv"
    vocab_path.write_text("hpo_id\tpatients\tweight\n" + "".join(f"{t}\t{k}\t{w:.6f}\n" for t, k, w in rows))
    inputs = [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        load_sources()["hpo_ontology"].as_input(),
        *extra_inputs,
    ]
    params = {
        "part": "train",
        "kb": kb_id,
        "kb_mask_scope": mask_scope,
        "population": population,
        "population_rule": "all R1-train patients"
        if population == "all"
        else "R1-train patients none of whose PMIDs the pinned hpo_annotations cites",
        "min_noise_count": min_noise_count,
        "vocabulary": vocabulary,
    }
    manifest = build_manifest(
        calib_id, "simulator-calibration", inputs, params, [targets_path, vocab_path], state=state
    )
    write_manifest(manifest)
    typer.echo(json.dumps(targets, indent=1))


@calib_app.command("age-durations")
def calib_age_durations(
    calib_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. age-durations-v1"),
    min_patients: int = typer.Option(20, help="Categories with fewer patients take the overall mean"),
) -> None:
    """Mean (age - onset) per onset category, R1-train patients with both: `age.duration_mean_by_onset`."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import calibration
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose

    ensure_new(calib_id)
    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.TRAIN)
    result = calibration.duration_means(train, min_patients=min_patients)
    body = {
        **result["keys"],
        "_provenance": {
            "artifact": calib_id,
            "population": f"R1-train patients with age and onset ({result['patients']} of {len(train)})",
            "windows": "rare-disease-simulator 0.5.0 (020e41d) AgeSettings.onset_years",
            "code_sha": state.sha,
            **{k: v for k, v in result.items() if k != "keys"},
        },
    }
    out = DATA_DIR / "calib" / f"{calib_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    inputs = [{"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")}]
    params = {
        "part": "train",
        "statistic": "mean(age - onset) per onset category",
        "category_rule": result["category_rule"],
        "min_patients": min_patients,
        "windows": result["windows"],
    }
    write_manifest(build_manifest(calib_id, "simulator-calibration-keys", inputs, params, [out], state=state))
    typer.echo(json.dumps(body, indent=1, sort_keys=True))


annotations_app = typer.Typer(no_args_is_help=True, help="Known/held-out annotation splits (S3).")
app.add_typer(annotations_app, name="annotations")


@annotations_app.command("split")
def annotations_split(
    split_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. annot-split-v1"),
    fraction: float = typer.Option(..., help="Share of positive annotations held out (half B)"),
    publish: bool = typer.Option(False),
    hpoa_artifact: str = typer.Option(
        "", help="Split the positive pairs of this hpoa-* artifact instead of the pinned upstream HPOA"
    ),
) -> None:
    """Freeze which HPOA annotations systems under S3 may not know (EVAL_PROTOCOL §8)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(split_id)
    from diagnostic_ar_training import INTERIM_DIR
    from diagnostic_ar_training.knowledge import annotation_split
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        fetch_outputs,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source

    salt = f"diagnostic.ar-training/{split_id}"
    if hpoa_artifact:
        hpoa = next(p for p in fetch_outputs(load_manifest(hpoa_artifact)) if p.name == "phenotype.hpoa")
        input_ref = {"id": f"artifact:{hpoa_artifact}", "sha256": sha256_file(hpoa)}
    else:
        hpoa = open_source("hpo_annotations", Purpose.KB)
        input_ref = load_sources()["hpo_annotations"].as_input()
    pairs = annotation_split.split(hpoa, fraction, salt)
    path = INTERIM_DIR / "annotations" / split_id / "heldout.tsv"
    annotation_split.write(pairs, path)
    params = {"fraction": fraction, "salt": salt, "unit": "(disease_id, hpo_id) positive aspect-P annotation"}
    manifest = build_manifest(split_id, "annotation-split", [input_ref], params, [path])
    if publish:
        manifest = publish_release(manifest, split_id)
    write_manifest(manifest)
    typer.echo(f"{split_id}: {len(pairs)} held-out annotations -> {path}")


s3_app = typer.Typer(no_args_is_help=True, help="S3: simulated question-agent evaluation (EVAL_PROTOCOL §8).")
app.add_typer(s3_app, name="s3")


def _s3_dataset(split_id: str):
    """(spec, dataset path, excluded case ids) of an S3 version; the exclusion list applies to s3-v2 only."""
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest

    try:
        spec = s3.spec(split_id)
    except ValueError as e:
        raise typer.BadParameter(str(e)) from e
    data = next(
        p for p in fetch_outputs(load_manifest(spec.dataset_artifact)) if p.name.endswith(".jsonl.gz")
    )
    excluded: set[str] = set()
    if spec.exclusion_artifact:
        path = next(
            p for p in fetch_outputs(load_manifest(spec.exclusion_artifact)) if p.name == "exclude.txt"
        )
        excluded = set(path.read_text().split())
    return spec, data, excluded


def _s3_exclusion_sha(spec) -> str | None:
    from diagnostic_ar_training.lineage.manifest import load_manifest

    if not spec.exclusion_artifact:
        return None
    return next(
        o.sha256 for o in load_manifest(spec.exclusion_artifact).outputs if o.path.endswith("exclude.txt")
    )


def _check_s3_kb(split_id: str, kb_manifest) -> None:
    from diagnostic_ar_training.cohorts import s3

    try:
        s3.check_kb_split(split_id, kb_manifest.params.get("heldout_annotations_dropped"))
    except ValueError as e:
        raise typer.BadParameter(f"{kb_manifest.artifact_id}: {e} (EVAL_PROTOCOL §8)") from e


@s3_app.command("run")
def s3_run_cmd(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-S3-001"),
    split: str = typer.Option("s3-v1", help="s3-v1, or s3-v2 (drops the s3-data-v2-excl-v1 cases)"),
    part: str = typer.Option(
        "dev", help="dev, or test (sealed: needs --reason and DXT_SEALED_READ=<exp> in the environment)"
    ),
    reason: str = typer.Option("", help="Required for the sealed part"),
    kb_id: str = typer.Option("kb-v5", "--kb", help="KB without half B of the split's annotation split"),
    rr2_fits: str = typer.Option(
        "results/EXP-B-002/rr-v2-fits.json", help="rr-v2 fitted weights (EXP-B-002)"
    ),
    n_candidates: int = typer.Option(10),
    n_questions: int = typer.Option(7),
    top_k: int = typer.Option(200),
    only: list[str] = typer.Option(
        [], "--system", help="Score only these systems (E0 references are always scored)"
    ),
) -> None:
    """Interview every S3 case once, score every pre-registered system on the same answers.

    The sealed test part is read only with DXT_SEALED_READ=<exp> set to the same experiment id, e.g.
    `DXT_SEALED_READ=EXP-B-004 dxt s3 run --exp EXP-B-004 --part test --reason ...`.
    """
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
    _check_s3_kb(split, kb_manifest)
    spec, data, excluded = _s3_dataset(split)
    excl_sha = _s3_exclusion_sha(spec)
    pairs = s3.load_part(split, part, data, exp_id=exp if part in s3.SEALED else None, reason=reason)
    pairs = [p for p in pairs if p[0].case_id not in excluded]
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
    if unknown := set(only) - set(systems):
        raise typer.BadParameter(f"unknown systems {sorted(unknown)}; known: {sorted(systems)}")
    if only:
        systems = {name: beta for name, beta in systems.items() if name in only or name == "E0+answers"}

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
    outputs = [harness.write(exp, f"{split}/{part}", "E0-initial", "interviewed", initial)[0]]
    for name, beta in systems.items():
        recs = records(lambda i, b=beta: i.table.combine(b))
        report["systems"][name] = {
            "beta": dict(zip(COMPONENTS, map(float, beta), strict=True)),
            "summary": harness.summarize(recs)["all"],
            "vs_E0+answers": harness.compare(base, recs),
        }
        outputs.append(harness.write(exp, f"{split}/{part}", name, "interviewed", recs)[0])
    report_path = out_dir / f"{split}-{part}__report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    outputs.append(report_path)
    inputs = e0.lineage_inputs() + [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": f"artifact:{spec.dataset_artifact}", "sha256": sha256_file(data)},
        {"id": f"split:{split}", "sha256": sha256_file(SPLITS_DIR / f"{split}.json")},
        {"id": rr2_fits, "sha256": sha256_file(REPO_ROOT / rr2_fits)},
    ]
    if spec.exclusion_artifact:
        inputs.append({"id": f"artifact:{spec.exclusion_artifact}", "sha256": excl_sha})
    params = {
        "split": split,
        "part": part,
        "kb": kb_id,
        "n_candidates": n_candidates,
        "n_questions": n_questions,
        "top_k": top_k,
        "systems": sorted(systems),
    }
    write_manifest(
        build_manifest(f"results-{exp}-{split}-{part}", "s3-run", inputs, params, outputs, state=state)
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


litpanel_app = typer.Typer(no_args_is_help=True, help="Evaluation literature panel (ADR-0012 G4).")
app.add_typer(litpanel_app, name="litpanel")
REALISM_DIR = DATA_DIR / "realism"


@litpanel_app.command("split")
def litpanel_split(
    split_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. litpanel-split-v1"),
    genes_id: str = typer.Option("genes-v1", help="Gene profiles that define each gene's main disease"),
    size: int = typer.Option(60, help="Panel units, anchors included"),
    reserves: int = typer.Option(20, help="Ordered reserve units, also evaluation-only"),
    seed: int = typer.Option(20260930),
) -> None:
    """Freeze which (gene, main disease) units are evaluation-only; every other unit is construction."""
    from diagnostic_ar_training import INTERIM_DIR, splits
    from diagnostic_ar_training.knowledge import literature_panel as lp
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        ensure_new,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb

    ensure_new(split_id)
    genes_manifest = load_manifest(genes_id)
    genes_path = INTERIM_DIR / "genes" / genes_id / "genes.json.gz"
    if sha256_file(genes_path) != genes_manifest.outputs[0].sha256:
        raise LineageError(f"{genes_path} does not match the {genes_id} manifest")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
    mask_path = splits.heldout_pmids_path("r1-v1")
    splits.write_heldout_pmids("r1-v1")
    phenotypes, names = lp.hpoa_phenotypes(
        open_source("hpo_annotations", Purpose.EVAL), ontology, set(mask_path.read_text().split())
    )
    train = lp.patients_per_gene(splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL))
    dev = lp.patients_per_gene(splits.load_part("r1-v1", splits.Part.DEV, Purpose.EVAL))
    pool = lp.units(kb.read(genes_path), ontology, phenotypes, names, train, dev)
    chosen = lp.select(pool, size=size, reserves=reserves, seed=seed)
    rows = lp.split_rows(chosen)
    out = REALISM_DIR / f"{split_id}.tsv"
    lp.write_tsv(rows, lp.SPLIT_COLUMNS, out)
    summary = lp.split_summary(rows, pool)
    summary_path = REALISM_DIR / f"{split_id}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [
        {"id": f"artifact:{genes_id}", "sha256": genes_manifest.outputs[0].sha256},
        sources["hpo_ontology"].as_input(),
        sources["hpo_annotations"].as_input(),
        {"id": "heldout-pmids:r1-v1", "sha256": sha256_file(mask_path)},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
    ]
    params = {
        "anchors": list(lp.ANALYSIS_001_GENES),
        "size": size,
        "reserves": reserves,
        "seed": seed,
        "dev_share": 0.5,
        "dev_min": 10,
        "main_disease": "simulable entity with the highest sim_weight",
        "strata": "organ system (modal child of HP:0000118), inheritance (AD/AR/XL/other), "
        "R1-train patients (0, 1-9, >=10); square-root allocation per margin",
        "r1_parts_read": ["train", "dev"],
    }
    notes = (
        "Evaluation units: every row of the TSV (anchor, sampled and reserve). Their genes and all "
        "their disease ids must never feed literature-derived construction. Every other unit is construction."
    )
    write_manifest(build_manifest(split_id, "litpanel-split", inputs, params, [out, summary_path], notes))
    typer.echo(json.dumps(summary, indent=1))


CROSSCHECK_COLUMNS = (
    "row", "gene", "disease_id", "feature_label", "hpo_id", "citation", "section", "prevalence",
    "prevalence_low", "prevalence_high", "other_found", "other_prevalence", "other_low", "other_high",
    "other_quote", "agree", "resolution",
)  # fmt: skip


@litpanel_app.command("crosscheck")
def litpanel_crosscheck(
    rows_path: Path = typer.Option(..., "--rows", help="Working TSV: curated columns + source_text_file"),
    out: Path = typer.Option(..., help="Cross-check TSV to write"),
    fraction: float = typer.Option(0.1),
    seed: int = typer.Option(20260930),
    command: str = typer.Option(
        "codex exec --skip-git-repo-check --sandbox read-only",
        help="Re-extractor; the prompt is its last argument",
    ),
    log_dir: Path = typer.Option(..., help="Where each raw answer is kept"),
) -> None:
    """Re-extract a seeded sample with another model that sees gene, disease, feature, citation only."""
    import shlex
    import subprocess

    from diagnostic_ar_training.knowledge import literature_panel as lp

    rows = lp.read_tsv(rows_path)
    log_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i in lp.crosscheck_sample(rows, fraction, seed):
        row = rows[i]
        prompt = lp.crosscheck_prompt(row)
        source = Path(row["source_text_file"])
        answer = subprocess.run(
            [*shlex.split(command), prompt],
            input=source.read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        ).stdout
        (log_dir / f"row{i:04d}.txt").write_text(
            f"{prompt}\n\n=== STDIN: {source} ===\n\n=== ANSWER ===\n{answer}"
        )
        try:
            other = lp.parse_answer(answer)
        except (ValueError, json.JSONDecodeError):
            other = {
                "found": False,
                "prevalence": "",
                "prevalence_low": "",
                "prevalence_high": "",
                "quote": "",
            }
        results.append(
            {
                **{c: row[c] for c in CROSSCHECK_COLUMNS[1:10]},
                "row": i,
                "other_found": str(other["found"]).lower(),
                "other_prevalence": other["prevalence"],
                "other_low": other["prevalence_low"],
                "other_high": other["prevalence_high"],
                "other_quote": other["quote"],
                "agree": str(
                    lp.agrees(
                        row,
                        {
                            "prevalence": other["prevalence"],
                            "prevalence_low": other["prevalence_low"],
                            "prevalence_high": other["prevalence_high"],
                        },
                    )
                ).lower(),
            }
        )
        typer.echo(f"row {i} {row['gene']} {row['feature_label']}: agree={results[-1]['agree']}")
    lp.write_tsv(results, CROSSCHECK_COLUMNS, out)
    agree = sum(r["agree"] == "true" for r in results)
    typer.echo(f"{agree}/{len(results)} agree")


@litpanel_app.command("build")
def litpanel_build(
    panel_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. literature-panel-v2"),
    split_id: str = typer.Option("litpanel-split-v1", "--split"),
    extraction: Path = typer.Option(
        DATA_DIR / "realism" / "extraction", help="curated.tsv, dropped.tsv, access-log.tsv, crosscheck.tsv"
    ),
    source_archive: str = typer.Option(
        "", help="Provenance of the GeneReviews bulk archive: 'url sha256 date'"
    ),
) -> None:
    """Validate the curated rows against the split and HPO, add independence columns, and write the panel."""
    from diagnostic_ar_training.knowledge import literature_panel as lp
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        ensure_new,
        load_manifest,
        write_manifest,
    )
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology

    ensure_new(panel_id)
    split_manifest = load_manifest(split_id)
    split_path = REALISM_DIR / f"{split_id}.tsv"
    if sha256_file(split_path) != split_manifest.outputs[0].sha256:
        raise LineageError(f"{split_path} does not match the {split_id} manifest")
    files = {n: extraction / f"{n}.tsv" for n in ("curated", "dropped", "access-log", "crosscheck")}
    crosscheck = lp.read_tsv(files["crosscheck"])
    unresolved = [r["row"] for r in crosscheck if r["agree"] != "true" and not r["resolution"].strip()]
    if unresolved:
        raise LineageError(f"cross-check disagreements without a resolution: rows {unresolved}")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
    hpoa_path = open_source("hpo_annotations", Purpose.EVAL)
    r1 = lp.r1_pmid_parts(
        set((SPLITS_DIR / "r1-v1.all-pmids.txt").read_text().split()),
        set((SPLITS_DIR / "r1-v1.heldout-pmids.txt").read_text().split()),
    )
    split_rows = lp.read_tsv(split_path)
    rows, problems = lp.validate_rows(
        lp.read_tsv(files["curated"]), split_rows, ontology, lp.hpoa_cited_pmids(hpoa_path), r1
    )
    if problems:
        for p in problems:
            typer.echo(p, err=True)
        raise typer.Exit(1)
    out = REALISM_DIR / f"{panel_id}.tsv"
    lp.write_tsv(rows, lp.PANEL_COLUMNS, out)
    summary = lp.panel_summary(rows, split_rows, lp.read_tsv(files["dropped"]))
    summary["crosscheck"] = {
        "rows": len(crosscheck),
        "agree": sum(r["agree"] == "true" for r in crosscheck),
        "resolutions": dict(
            sorted(Counter(r["resolution"].split(":")[0] for r in crosscheck if r["agree"] != "true").items())
        ),
    }
    summary_path = REALISM_DIR / f"{panel_id}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    sources = registry.load_sources()
    inputs = [
        {"id": f"artifact:{split_id}", "sha256": split_manifest.outputs[0].sha256},
        sources["hpo_ontology"].as_input(),
        sources["hpo_annotations"].as_input(),
        {"id": "r1-pmids:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.all-pmids.txt")},
        {"id": "heldout-pmids:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.heldout-pmids.txt")},
        *({"id": f"extraction:{n}", "sha256": sha256_file(p)} for n, p in files.items()),
    ]
    params = {
        "split": split_id,
        "independent_rule": "source_kind != orphanet and no cited PMID in phenotype.hpoa or in R1-train",
        "genereviews_bulk_archive": source_archive,
        "crosscheck": "10% seeded sample (seed 20260930) re-extracted by Codex CLI from gene, disease, "
        "feature and citation only; agree = ranges overlap or |point difference| <= 0.10",
    }
    notes = (
        "Evaluation only (ADR-0012 G4): never a fitting target and never an input to simulator profiles. "
        "Private: short evidence quotes of copyrighted sources; do not publish as a release asset."
    )
    write_manifest(build_manifest(panel_id, "literature-panel", inputs, params, [out, summary_path], notes))
    typer.echo(json.dumps({k: v for k, v in summary.items() if k != "rows_per_unit"}, indent=1))


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
    split: str = typer.Option("s3-v1", help="s3-v1, or s3-v2 (drops the s3-data-v2-excl-v1 cases)"),
    kb_id: str = typer.Option("kb-v5", "--kb", help="KB without half B, for the questioner"),
    n_candidates: int = typer.Option(10),
    n_questions: int = typer.Option(7),
) -> None:
    """Interview S3-dev once, as `dxt s3 run` does, and keep the interviewed cases for Front A runs.

    Writes the cases systems receive (present + "yes", "no" as excluded) with a manifest. For s3-v1 it also
    checks that E0 on them reproduces EXP-S3-001's E0+answers ranks. S3-test is never read here.
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

    artifact = f"{split}-dev-interviews-{kb_id}-c{n_candidates}-q{n_questions}"
    ensure_new(artifact)
    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    kb_manifest = load_manifest(kb_id)
    _check_s3_kb(split, kb_manifest)
    spec, dataset, excluded = _s3_dataset(split)
    pairs = [p for p in s3.load_part(split, "dev", dataset) if p[0].case_id not in excluded]
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(kb_manifest)[0]), ontology)
    e0 = GenPheniaV3()
    interviews = s3_run.interview_cases(pairs, e0, knowledge, ontology, n_candidates, n_questions)
    path = S3_INTERVIEWS_DIR / f"{artifact}.jsonl.gz"
    s3_run.write_interviews(path, interviews)

    after = s3_run.read_interviews(path)
    identical = None
    if split == "s3-v1":
        reference = {r["case_id"]: r["rank"] for r in harness.read(
            RESULTS_DIR / "EXP-S3-001" / "s3-v1-dev__E0+answers__interviewed.ranks.jsonl")}  # fmt: skip
        ranks = {c.case_id: s3_run.rank(e0.score(c).probs, e0.genes, c.gene) for c in after}
        if set(ranks) != set(reference):
            raise LineageError("the interviewed cases are not EXP-S3-001's S3-dev cases")
        identical = sum(ranks[k] == reference[k] for k in ranks)
    params = {
        "split": split,
        "part": "dev",
        "kb": kb_id,
        "n_candidates": n_candidates,
        "n_questions": n_questions,
        "cases": len(after),
        "questions_per_case": float(np.mean([len(i.questions) for i in interviews])),
        "yes_per_case": float(np.mean([i.yes for i in interviews])),
        "no_per_case": float(np.mean([len(i.after.excluded) for i in interviews])),
    }
    if identical is not None:
        params["e0_ranks_identical_to_EXP-S3-001"] = identical
    inputs = e0.lineage_inputs() + [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": f"artifact:{spec.dataset_artifact}", "sha256": sha256_file(dataset)},
        {"id": f"split:{split}", "sha256": sha256_file(SPLITS_DIR / f"{split}.json")},
    ]
    if spec.exclusion_artifact:
        inputs.append({"id": f"artifact:{spec.exclusion_artifact}", "sha256": _s3_exclusion_sha(spec)})
    write_manifest(build_manifest(artifact, "s3-interviews", inputs, params, [path], state=state))
    typer.echo(json.dumps(params, indent=1))
    if identical is not None and identical != len(after):
        raise typer.Exit(1)


@gnn_app.command("interview-sim")
def gnn_interview_sim(
    artifact: str = typer.Option("ds-sim0.3.1-A-iv-v1", help="Immutable id of the interviewed dataset"),
    per_gene_train: int = typer.Option(20, help="Cases per gene from the simulator's train split"),
    per_gene_val: int = typer.Option(5, help="Cases per gene from the simulator's val split"),
    kb_id: str = typer.Option("kb-v5", "--kb", help="KB without half B, for the questioner"),
    n_candidates: int = typer.Option(10),
    n_questions: int = typer.Option(7),
    workers: int = typer.Option(14),
    limit: int = typer.Option(0, help="Debug only: interview the first N selected cases, write nothing"),
) -> None:
    """Interview a declared subsample of the simulated training data like S3 (ADR-0010 §2).

    Checks the result against R1 (every part, keys only) and S3 (raw presentations, and the interviewed
    S3-dev cases): an interviewed case whose (gene, present set) equals one of theirs is dropped and listed
    in the manifest, and the residual overlap must be 0. S3-test is never interviewed.
    """
    import time

    import numpy as np

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.eval import s3_run
    from diagnostic_ar_training.gnn import experiment, interviewed
    from diagnostic_ar_training.gnn.data import overlap_key
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import (
        build_manifest,
        ensure_new,
        fetch_outputs,
        load_manifest,
        output_path,
        write_manifest,
    )
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    ensure_new(artifact)
    state = code_state()
    if state.dirty and not limit:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    kb_manifest = load_manifest(kb_id)
    if kb_manifest.params.get("heldout_annotations_dropped") != "annot-split-v1":
        raise typer.BadParameter(f"{kb_id} must be built without half B of annot-split-v1 (EVAL_PROTOCOL §8)")
    kb_path = fetch_outputs(kb_manifest)[0]
    source, exclude, source_lineage = experiment.source_with_exclusion()
    salt = f"diagnostic.ar-training/{artifact}"
    per_gene = {"train": per_gene_train, "val": per_gene_val}

    start = time.perf_counter()
    chosen = interviewed.select(
        ((r["split"], r["gene"], r["case_id"]) for r in interviewed.iter_source(source, exclude)),
        per_gene,
        salt,
    )
    wanted = {i: s for s, ids in chosen.items() for i in ids}
    keep = (
        "case_id",
        "gene",
        "gene_index",
        "split",
        "present",
        "true_present",
        "sex",
        "age_years",
        "onset_years",
    )
    records = [
        {k: r[k] for k in keep} for r in interviewed.iter_source(source, exclude) if r["case_id"] in wanted
    ]
    order = {s: i for i, s in enumerate(interviewed.SPLIT_ORDER)}
    records.sort(key=lambda r: (order[r["split"]], r["case_id"]))
    if limit:
        records = records[:limit]
    select_seconds = time.perf_counter() - start

    start = time.perf_counter()
    results = interviewed.interview_parallel(records, kb_path, n_candidates, n_questions, workers)
    interview_seconds = time.perf_counter() - start
    rows = [row for row, _ in results]
    ranks = {row["case_id"]: rk for row, rk in results}

    s3_data = next(p for p in fetch_outputs(load_manifest("s3-data-v1")) if p.name.endswith(".jsonl.gz"))
    s3_dev_iv = load_manifest("s3-v1-dev-interviews-kb-v5-c10-q7")
    s3_dev_path = output_path(s3_dev_iv.outputs[0])
    if sha256_file(s3_dev_path) != s3_dev_iv.outputs[0].sha256:
        raise LineageError(f"{s3_dev_path} does not match its manifest")
    cohorts = {
        "r1-v1 (all parts, keys only)": splits.presentation_keys("r1-v1"),
        "s3-data-v1 (raw presentations, all cases)": {
            overlap_key(c.gene, c.present) for c, _ in s3.read_dataset(s3_data, "s3-v1")
        },
        "s3-v1/dev interviewed": {
            overlap_key(c.gene, c.present) for c in s3_run.read_interviews(s3_dev_path)
        },
    }
    overlap = interviewed.contamination(rows, cohorts)
    dropped = sorted({i for ids in overlap.values() for i in ids})
    rows = [r for r in rows if r["case_id"] not in set(dropped)]
    residual = interviewed.contamination(rows, cohorts)
    if any(residual.values()):
        raise LineageError(f"residual overlap after dropping: {residual}")

    def stats(split: str) -> dict:
        part = [r for r in rows if r["split"] == split]
        return {
            "cases": len(part),
            "genes": len({r["gene"] for r in part}),
            "questions_per_case": float(np.mean([len(r["questions"]) for r in part])),
            "yes_per_case": float(np.mean([r["yes"] for r in part])),
            "no_per_case": float(np.mean([r["no"] for r in part])),
            "cases_without_questions": sum(not r["questions"] for r in part),
            "cases_with_excluded": sum(r["no"] > 0 for r in part),
            "present_per_case": float(np.mean([len(r["present"]) for r in part])),
            "e0_mrr_initial": interviewed.mrr(ranks[r["case_id"]]["initial"] for r in part),
            "e0_mrr_answers": interviewed.mrr(ranks[r["case_id"]]["answers"] for r in part),
        }

    params = {
        "source": experiment.DATASET,
        "exclusion": experiment.EXCLUSION,
        "selection": "per (split, gene): the k smallest sha256(salt:case_id), after the exclusion",
        "salt": salt,
        "per_gene": per_gene,
        "kb": kb_id,
        "kb_heldout_annotations_dropped": kb_manifest.params["heldout_annotations_dropped"],
        "questioner": "eval.s3_run.interview_cases (E0 = production ONNX, as S3)",
        "initial_presentation": "reported present + sex/age/onset; the simulator's excluded terms dropped",
        "n_candidates": n_candidates,
        "n_questions": n_questions,
        "cases": {s: sum(r["split"] == s for r in rows) for s in interviewed.SPLIT_ORDER},
        "stats": {s: stats(s) for s in interviewed.SPLIT_ORDER},
        "contamination": {
            "key": "(gene upper-cased, present set after the interview)",
            "overlap_before_drop": {k: len(v) for k, v in overlap.items()},
            "dropped_case_ids": dropped,
            "residual": {k: len(v) for k, v in residual.items()},
        },
        "residual_overlap": sum(len(v) for v in residual.values()),
        "timing": {
            "workers": workers,
            "select_seconds": select_seconds,
            "interview_seconds": interview_seconds,
        },
    }
    if limit:
        typer.echo(json.dumps(params, indent=1))
        return
    out_dir = DATA_DIR / "interim" / "datasets" / artifact
    path = out_dir / f"{artifact}.jsonl.gz"
    interviewed.write_rows(path, rows)
    params["sha256"] = sha256_file(path)
    inputs = (
        source_lineage
        + GenPheniaV3.__new__(GenPheniaV3).lineage_inputs()
        + [
            {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
            {"id": "split:r1-v1 (all parts, keys only)", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
            {"id": "artifact:s3-data-v1", "sha256": sha256_file(s3_data)},
            {"id": "artifact:s3-v1-dev-interviews-kb-v5-c10-q7", "sha256": s3_dev_iv.outputs[0].sha256},
        ]
    )
    write_manifest(
        build_manifest(artifact, "interviewed-training-dataset", inputs, params, [path], state=state)
    )
    shown = {**params["contamination"], "dropped_case_ids": len(dropped)}
    typer.echo(json.dumps(params | {"contamination": shown}, indent=1))


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


@gnn_app.command("train-frozen")
def gnn_train_frozen(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-A-002f"),
    run_id: str = typer.Option(..., help="Unique run id"),
    design: str = typer.Option(..., help="neg, neg2, cov, neg+cov or neg2+cov (gnn.frozen.DESIGNS)"),
    lr_new: float = typer.Option(..., help="Learning rate of the new parameters (v3.0 stays frozen)"),
    cov_hidden: int = typer.Option(32, help="Width of the covariate MLP"),
    seed: int = typer.Option(0),
    max_epochs: int = typer.Option(15),
    patience: int = typer.Option(3),
    batch_size: int = typer.Option(256),
    warmup_steps: int = typer.Option(200),
    workers: int = typer.Option(10),
    dataset: str = typer.Option("ds-sim0.3.1-A-iv-v1", help="Interviewed training artifact"),
    s3_interviews: str = typer.Option("s3-v1-dev-interviews-kb-v5-c10-q7", help="Interviewed S3-dev cases"),
    max_train_cases: int = typer.Option(0, help="Pipeline check only: cap the training cases (0 = all)"),
    device: str = typer.Option("cuda"),
) -> None:
    """ADR-0010: train only the new inputs' parameters on interviewed simulated cases; v3.0 frozen.

    Curves every epoch (train loss, sim-val, the design's R1-dev views, S2); at the checkpoint selected by
    sim-val: every R1-dev view, S2 and S3-dev; then the identity checks (present-only logits bit-identical
    to v3.0 on CPU, R1-dev present-view ranks equal to EXP-000's, v3.0 tensors untouched).
    """
    import time

    from diagnostic_ar_training import RESULTS_DIR, splits
    from diagnostic_ar_training.cohorts import access
    from diagnostic_ar_training.eval import s3_run
    from diagnostic_ar_training.gnn import data, experiment, frozen
    from diagnostic_ar_training.gnn import train as training
    from diagnostic_ar_training.gnn.model import load_v3
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
    if design not in frozen.DESIGNS:
        raise typer.BadParameter(f"design must be one of {sorted(frozen.DESIGNS)}")
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
        lr_base=0.0,
        lr_new=lr_new,
        frozen_base=True,
        cov_hidden=cov_hidden,
        seed=seed,
        max_epochs=max_epochs,
        patience=patience,
        batch_size=batch_size,
        warmup_steps=warmup_steps,
        num_workers=workers,
        max_train_cases=max_train_cases or None,
        **frozen.DESIGNS[design],
    )
    torch, dev, inputs, table, base = _gnn_setup(device, workers)

    training_data = experiment.load_interviewed(dataset)
    train_cases = training_data.splits["train"]
    if cfg.max_train_cases:
        train_cases = train_cases[: cfg.max_train_cases]
    r1_dev = splits.load_part("r1-v1", "dev", Purpose.EVAL)
    r1_groups = splits.publication_groups("r1-v1")
    s3_manifest = load_manifest(s3_interviews)
    s3_path = output_path(s3_manifest.outputs[0])
    if sha256_file(s3_path) != s3_manifest.outputs[0].sha256:
        raise LineageError(f"{s3_path} does not match {s3_interviews}'s manifest")
    s3_dev = s3_run.read_interviews(s3_path)
    s2 = access.load("s2")
    contamination = experiment.check_contamination(
        training_data.splits["train"] + training_data.splits["val"],
        {
            "r1-v1/train": splits.load_part("r1-v1", "train", Purpose.EVAL),
            "r1-v1/dev": r1_dev,
            "s3-v1/dev": s3_dev,
        },
    )
    if any(v["present_set_overlap"] for v in contamination.values()):
        raise LineageError(f"training cases overlap evaluation cases: {contamination}")
    contamination["certified_by_artifact"] = load_manifest(dataset).params["contamination"]["residual"]
    baselines = frozen.e0_baselines(r1_groups, s3=True)
    views = frozen.epoch_views(cfg)
    sim_val = data.SimGraphs(inputs, training_data.splits["val"], negated=cfg.negated)
    name = f"{exp}-{run_id}"

    def evaluate(model, epoch: int) -> dict:
        sim = training.evaluate_sim(model, sim_val, table, dev, cfg)
        system = GinModelSystem(model, inputs, name, cfg.negated)
        metrics, _ = frozen.score(system, r1_dev, r1_groups, s2, None, baselines, views)
        shown = " ".join(f"{v} {metrics[f'r1_dev_{v}']['delta']:+.4f}" for v in views)
        typer.echo(
            f"[{run_id}] epoch {epoch}: sim-val loss {sim['loss']:.4f} mrr {sim['mrr']:.4f} | "
            f"R1-dev Δ {shown} | S2 {metrics['s2']['mrr']:.4f}"
        )
        return {"sim_val": sim, **metrics}

    out_dir.mkdir(parents=True)
    run_info = {
        "exp": exp,
        "run_id": run_id,
        "design": design,
        "config": cfg.__dict__,
        "code": state.as_dict(),
        "device": torch.cuda.get_device_name(dev) if dev.type == "cuda" else "cpu",
        "torch": torch.__version__,
        "dataset": dataset,
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
    last_state = {
        "base_unchanged": training.base_unchanged(model, base),
        "positive_types_closed": training.positive_types_closed(model),
    }
    best_epoch = training.load_checkpoint(model, ckpt_dir / "best.pt")
    model.eval()
    final, records = frozen.score(
        GinModelSystem(model, inputs, name, cfg.negated),
        r1_dev,
        r1_groups,
        s2,
        s3_dev,
        baselines,
        frozen.ALL_VIEWS,
        frozen.S3_VIEWS,
    )
    epoch0 = frozen.score(
        GinModelSystem(training.build_model(base, cfg).eval(), inputs, name, cfg.negated),
        r1_dev,
        r1_groups,
        s2,
        None,
        baselines,
        ("present",),
    )[1]
    v3_cpu = load_v3(inputs.root, map_location="cpu")
    model_cpu = training.build_model(v3_cpu, cfg).eval()
    training.load_checkpoint(model_cpu, ckpt_dir / "best.pt")
    identity = {
        "r1_dev": frozen.present_only_identity(model_cpu, v3_cpu, inputs, r1_dev),
        "s2": frozen.present_only_identity(model_cpu, v3_cpu, inputs, s2),
    }
    checks = {
        "present_only_logits_bit_identical_cpu": identity,
        "r1_dev_present_ranks_changed_vs_exp000": frozen.same_ranks(
            records["r1_dev_present"], baselines["r1_dev_present"]
        ),
        "s2_ranks_changed_vs_untrained": frozen.same_ranks(records["s2"], epoch0["s2"]),
        "s2_ranks_changed_vs_exp000_onnx": frozen.same_ranks(records["s2"], baselines["s2"]),
        **last_state,
        "best_base_unchanged": training.base_unchanged(model, base),
        "best_positive_types_closed": training.positive_types_closed(model),
    }
    checks["pass"] = (
        all(v["identical"] == v["scorable"] for v in identity.values())
        and checks["r1_dev_present_ranks_changed_vs_exp000"] == 0
        and checks["s2_ranks_changed_vs_untrained"] == 0
        and all(last_state.values())
        and checks["best_base_unchanged"]
        and checks["best_positive_types_closed"]
    )
    outputs = [curves_path, out_dir / "run.json", *frozen.write_ranks(out_dir, records)]
    summary = {
        **{k: v for k, v in result.items() if k != "history"},
        "best_epoch_reloaded": best_epoch,
        "epoch_views": views,
        "at_best": final,
        "sim_val_at_best": next(h for h in result["history"] if h["epoch"] == best_epoch)["sim_val"],
        "flags": frozen.flags(result["history"], best_epoch, frozen.primary_r1_view(cfg)),
        "checks": checks,
        "wall_seconds": time.perf_counter() - wall_start,
        "max_gpu_memory_gb": torch.cuda.max_memory_allocated(dev) / 1e9 if dev.type == "cuda" else None,
        "checkpoints": {p.name: p.stat().st_size for p in sorted(ckpt_dir.glob("*.pt"))},
    }
    summary_path = out_dir / "summary.json"
    training.write_json(summary_path, summary)
    outputs.append(summary_path)
    refs = GinModelSystem(model, inputs, name).lineage_inputs() + training_data.lineage
    refs += [
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        {"id": f"artifact:{s3_interviews}", "sha256": s3_manifest.outputs[0].sha256},
    ]
    refs += [
        {"id": f"results:{p.parent.name}/{p.name}", "sha256": sha256_file(p)}
        for p in (experiment.E0_R1_DEV["present"], experiment.E0_S2, experiment.E0_S3_DEV)
    ]
    params = {**cfg.__dict__, "exp": exp, "run_id": run_id, "design": design, "device": device}
    checkpoints = [ckpt_dir / "best.pt", ckpt_dir / "last.pt"]
    write_manifest(
        build_manifest(
            artifact,
            "gnn-frozen-base-run",
            refs,
            params,
            outputs + [p for p in checkpoints if p.exists()],
            notes="v3.0 frozen (ADR-0010); checkpoints hold the new tensors only and stay local.",
            state=state,
        )
    )
    primary = final[f"r1_dev_{frozen.primary_r1_view(cfg)}"]
    s3 = final["s3_dev_all"]
    typer.echo(
        f"[{run_id}] best epoch {best_epoch}/{result['epochs_run']}: "
        f"R1-dev {frozen.primary_r1_view(cfg)} Δ {primary['delta']:+.4f} "
        f"[{primary['ci95'][0]:+.4f},{primary['ci95'][1]:+.4f}] harmed {primary['harmed']:.3f} | "
        f"S3-dev all Δ {s3['delta']:+.4f} [{s3['ci95'][0]:+.4f},{s3['ci95'][1]:+.4f}] "
        f"harmed {s3['harmed']:.3f} | checks {'pass' if checks['pass'] else 'FAIL'} | "
        f"{summary['wall_seconds'] / 60:.1f} min"
    )
    if not checks["pass"]:
        raise typer.Exit(1)


@gnn_app.command("report-frozen")
def gnn_report_frozen(
    exp: str = typer.Option(..., help="Experiment whose frozen-base runs to tabulate"),
) -> None:
    """The frozen-base experiment table from the committed run files, and mean ± sd per configuration."""
    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.gnn import frozen

    exp_dir = RESULTS_DIR / exp
    report = frozen.report(exp_dir)
    out = exp_dir / "report.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")

    def cell(m):
        if not m:
            return "-"
        return f"{m['delta']:+.4f} [{m['ci95'][0]:+.4f},{m['ci95'][1]:+.4f}] h{m['harmed']:.3f}"

    for r in report["runs"]:
        typer.echo(
            f"{r['run_id']:34} ep {r['best_epoch']}/{r['epochs_run']} "
            f"simval {r['sim_val']['best']['mrr']:.4f} "
            f"checks {'ok' if r['checks']['pass'] else 'FAIL'}"
        )
        for v in frozen.ALL_VIEWS:
            typer.echo(f"    R1 {v:9} {cell(r['r1_dev'][v])}")
        for v in frozen.S3_VIEWS:
            typer.echo(f"    S3 {v:9} {cell(r['s3_dev'][v])}")
    typer.echo(f"-> {out}")


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


@s3_app.command("interview")
def s3_interview_cmd(
    exp: str = typer.Option(..., help="Pre-registered experiment id, e.g. EXP-Q-001"),
    part: str = typer.Option("dev", help="dev; test is sealed and refused unless every sealed rule holds"),
    strategy: str = typer.Option(..., help="Q0, Q1, Q2 or Q2b"),
    reranker: str = typer.Option("rr-v1", help="rr-v1, rr-v1[neg=..,sex=..], or a JSON file with a beta"),
    cases: int = typer.Option(300, help="Cases to interview (0 = all)"),
    noise: float = typer.Option(0.0, help="Answer noise rate: flipped or unknown, half each"),
    seed: int = typer.Option(0, help="Seed of the answer noise"),
    reason: str = typer.Option("", help="Required for the sealed part"),
    label: str = typer.Option("dev", help="Outputs go to results/<exp>/<label>/"),
    lam: float = typer.Option(0.5, help="Q2b diversity weight"),
    kb_id: str = typer.Option("kb-v6", "--kb", help="KB without half B of annot-split-v2"),
    allow_kb_mismatch: bool = typer.Option(
        False, help="Use a KB not built without half B of annot-split-v2 (smoke only)"
    ),
    top_k: int = typer.Option(200),
) -> None:
    """Interview S3 v2 cases with one question strategy; score E0-initial, E0+answers and the final system."""
    from diagnostic_ar_training import RESULTS_DIR
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.eval import question_run, questioning
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
    from diagnostic_ar_training.rerank.features import GeneKnowledge
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    if part not in s3.PARTS:
        raise typer.BadParameter(f"part must be one of {s3.PARTS}")
    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before S3 runs")
    if part in s3.SEALED and (not reason.strip() or exp != "EXP-B-004" or cases != 0):
        raise typer.BadParameter(
            "the sealed part is read only by EXP-B-004's one pre-registered read: all cases, with a reason"
        )
    kb_manifest = load_manifest(kb_id)
    heldout = kb_manifest.params.get("heldout_annotations_dropped")
    if heldout != "annot-split-v2" and not allow_kb_mismatch:
        raise typer.BadParameter(f"{kb_id} must be built without half B of annot-split-v2, not {heldout!r}")
    reranker_name, beta = question_run.parse_reranker(reranker)
    chosen = question_run.make_strategy(strategy, lam)
    data = next(p for p in fetch_outputs(load_manifest("s3-data-v2")) if p.name.endswith(".jsonl.gz"))
    excl_path = next(p for p in fetch_outputs(load_manifest("s3-data-v2-excl-v1")) if p.name == "exclude.txt")
    excluded = set(excl_path.read_text().split())
    pairs = s3.load_part("s3-v2", part, data, exp_id=exp if part in s3.SEALED else None, reason=reason)
    chosen_pairs = question_run.select_cases(pairs, cases, excluded)

    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(kb_manifest)[0]), ontology)
    e0 = GenPheniaV3()
    ctx = questioning.Context(e0, knowledge, ontology, beta, top_k)
    agent = None
    if strategy == "Q1":
        from diagnostic_ar_training.eval.agent_selector import agent_version

        agent = agent_version()
    rows = question_run.run(chosen_pairs, chosen, ctx, noise, seed, top_k)
    report = {
        "label": label,
        "exp": exp,
        "split": f"s3-v2/{part}",
        "strategy": strategy,
        "schedule": list(chosen.schedule),
        "reranker": reranker_name,
        "noise": noise,
        "seed": seed,
        "kb": kb_id,
        "kb_heldout_annotations_dropped": heldout,
        "exclusion_list": "s3-data-v2-excl-v1",
        "excluded_in_part": len(pairs) - len(question_run.select_cases(pairs, 0, excluded)),
        "agent": agent,
        "code_sha": state.sha,
        **question_run.report(rows),
    }
    out_dir = RESULTS_DIR / exp / label
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"s3-v2-{part}__{strategy}__{reranker_name}__noise{noise:g}"
    questions_path = out_dir / f"{stem}.interviews.jsonl"
    questions_path.write_text("".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows))
    report_path = out_dir / f"{stem}.report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True, default=str) + "\n")
    inputs = e0.lineage_inputs() + [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": "artifact:s3-data-v2", "sha256": sha256_file(data)},
        {"id": "artifact:s3-data-v2-excl-v1", "sha256": sha256_file(excl_path)},
        {"id": "split:s3-v2", "sha256": sha256_file(SPLITS_DIR / "s3-v2.json")},
    ]
    params = {k: report[k] for k in ("strategy", "reranker", "noise", "seed", "kb", "agent", "label")}
    params["cases"] = len(rows)
    artifact = f"results-{exp}-{label}-{strategy}-{reranker_name}-noise{noise:g}"
    artifact = "".join(c if c.isalnum() or c in ".-" else "_" for c in artifact)
    write_manifest(
        build_manifest(
            artifact, "question-interview", inputs, params, [questions_path, report_path], state=state
        )
    )
    typer.echo(f"{strategy} cases={len(rows)} s/case={report['seconds_per_case']['mean']:.2f}")
    for name in ("E0-initial", "E0+answers", "final"):
        typer.echo(f"{name:12} MRR={report[name]['mrr']:.4f}")
    for name in (
        "questioner_effect (E0+answers vs E0-initial)",
        "reranker_effect (final vs E0+answers)",
        "primary (final vs E0-initial)",
    ):
        d = report[name]
        typer.echo(f"{name}: d={d['delta']:+.4f} harmed={d['harmed']:.3f} helped={d['helped']:.3f}")


DEV_SEARCH_DIR = "dev-search"


def _dev_dir(exp: str):
    from diagnostic_ar_training import RESULTS_DIR

    path = RESULTS_DIR / exp / DEV_SEARCH_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _require_clean_registered(exp: str):
    from diagnostic_ar_training.lineage import ledger
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: results must be reproducible from a SHA")
    if not ledger.is_preregistered(ledger.EXPERIMENTS_DIR / f"{exp}.md"):
        raise typer.BadParameter(f"docs/experiments/{exp}.md must be committed before S3 runs")
    return state


@s3_app.command("dev-interview")
def s3_dev_interview(
    exp: str = typer.Option("EXP-B-004", help="Pre-registered experiment id"),
    kb_id: str = typer.Option("kb-v6", "--kb", help="KB without half B of annot-split-v2, for Q0"),
    n_questions: int = typer.Option(9),
    top_k: int = typer.Option(200),
    workers: int = typer.Option(8),
) -> None:
    """Interview S3-v2-dev once with Q0 (dev only, exclusion list applied); every dev-search arm scores it."""
    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.eval import dev_run
    from diagnostic_ar_training.gnn.interviewed import write_rows
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

    artifact = f"results-{exp}-dev-interviews-q0-{kb_id}-b{n_questions}"
    ensure_new(artifact)
    state = _require_clean_registered(exp)
    kb_manifest = load_manifest(kb_id)
    _check_s3_kb("s3-v2", kb_manifest)
    spec, data, excluded = _s3_dataset("s3-v2")
    dev = s3.load_part("s3-v2", "dev", data)
    pairs = [p for p in dev if p[0].case_id not in excluded]
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    knowledge = GeneKnowledge(kb.read(fetch_outputs(kb_manifest)[0]), ontology)
    rows = dev_run.interview_dev(pairs, knowledge, ontology, n_questions, top_k, workers)
    path = _dev_dir(exp) / f"interviews.q0-{kb_id}-b{n_questions}.jsonl.gz"
    write_rows(path, [dev_run.encode_interview(r) for r in rows])
    answers = [a for r in rows for a in r["answers"].values()]
    params = {
        "split": "s3-v2/dev",
        "strategy": "Q0",
        "kb": kb_id,
        "n_questions": n_questions,
        "cases": len(rows),
        "excluded_in_dev": len(dev) - len(pairs),
        "questions_per_case": sum(len(r["questions"]) for r in rows) / len(rows),
        "yes_per_case": answers.count("yes") / len(rows),
        "no_per_case": answers.count("no") / len(rows),
    }
    inputs = [
        {"id": f"artifact:{kb_id}", "sha256": kb_manifest.outputs[0].sha256},
        {"id": f"artifact:{spec.dataset_artifact}", "sha256": sha256_file(data)},
        {"id": f"artifact:{spec.exclusion_artifact}", "sha256": _s3_exclusion_sha(spec)},
        {"id": "split:s3-v2", "sha256": sha256_file(SPLITS_DIR / "s3-v2.json")},
    ]
    write_manifest(build_manifest(artifact, "dev-interviews", inputs, params, [path], state=state))
    typer.echo(json.dumps({**params, "artifact": artifact}, indent=1))


def _load_dev_arms(directory) -> dict:
    from diagnostic_ar_training.eval.dev_search import Arm

    out = {}
    for path in sorted(directory.glob("arms-*.json")):
        for d in json.loads(path.read_text()):
            arm = Arm.from_dict(d)
            out.setdefault(arm.arm_id, arm)
    return out


@s3_app.command("dev-arms")
def s3_dev_arms(
    stage: str = typer.Option(..., help="l1a, l1b, l1c, l2 or l3: writes the arms the next dev-score runs"),
    exp: str = typer.Option("EXP-B-004"),
) -> None:
    """Generate one stage's arms by the fixed rules in eval/dev_arms.py (later stages read the log)."""
    from diagnostic_ar_training.eval import dev_arms, dev_search

    directory = _dev_dir(exp)
    log = directory.parent / "dev-search.tsv"
    arms = _load_dev_arms(directory)
    rows = dev_search.read_log(log) if log.exists() else []

    def by_lever(lever):
        return [r for r in rows if r["lever"] == lever]

    if stage == "l1a":
        chosen = dev_arms.l1_stage_a()
    elif stage == "l1b":
        chosen = dev_arms.l1_stage_b(by_lever("L1"), arms)
    elif stage == "l1c":
        chosen = dev_arms.l1_stage_c()
    elif stage == "l2":
        chosen = dev_arms.l2_arms(by_lever("L1"), arms)
    elif stage == "l3":
        winner = dev_search.select(by_lever("L2"), arms)
        if winner is None:
            raise typer.BadParameter("no L2 arm satisfies the selection rule; decide the L3 base explicitly")
        chosen = dev_arms.l3_arms(arms[winner["arm_id"]].config)
    else:
        raise typer.BadParameter("stage must be l1a, l1b, l1c, l2 or l3")
    lever = {"l1a": "L1", "l1b": "L1", "l1c": "L1", "l2": "L2", "l3": "L3"}[stage]
    if len(by_lever(lever)) + len([a for a in chosen if a.lever == lever]) > dev_arms.BUDGET[lever]:
        raise typer.BadParameter(f"{lever} budget {dev_arms.BUDGET[lever]} would be exceeded")
    out = directory / f"arms-{stage}.json"
    if out.exists():
        raise typer.BadParameter(f"{out} exists; stages are generated once")
    out.write_text(json.dumps([a.to_dict() for a in chosen], indent=1, sort_keys=True) + "\n")
    typer.echo(f"{stage}: {len(chosen)} arms -> {out}")
    for a in chosen:
        typer.echo(f"  {a.arm_id}  {a.config.config_hash}")


@s3_app.command("dev-score")
def s3_dev_score(
    stage: str = typer.Option(..., help="Name of the arms file arms-<stage>.json; also names the outputs"),
    exp: str = typer.Option("EXP-B-004"),
    interviews: str = typer.Option(
        "interviews.q0-kb-v6-b9.jsonl.gz", help="File in results/<exp>/dev-search/"
    ),
    vs: str = typer.Option("", help="Arm ids (comma-separated) to compare the others against, paired"),
    with_reference: bool = typer.Option(False, help="Also score rr-v1[neg=0.5] on kb-v5 as the bar (once)"),
    top_k: int = typer.Option(200),
    workers: int = typer.Option(8),
) -> None:
    """Score one stage's arms on the kept Q0 interview (S3-v2-dev) and on R1-dev, logging every arm."""
    import gzip

    import numpy as np

    from diagnostic_ar_training.cohorts import s3
    from diagnostic_ar_training.eval import dev_arms, dev_run, dev_search
    from diagnostic_ar_training.knowledge import annotation_split
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

    artifact = f"results-{exp}-dev-{stage}"
    ensure_new(artifact)
    state = _require_clean_registered(exp)
    directory = _dev_dir(exp)
    log = directory.parent / "dev-search.tsv"
    arms = [dev_search.Arm.from_dict(d) for d in json.loads((directory / f"arms-{stage}.json").read_text())]
    if with_reference:
        arms += dev_run.reference_arms()
    ids = [a.arm_id for a in arms]
    if len(set(ids)) != len(ids):
        raise typer.BadParameter("duplicate arm ids")
    logged_rows = dev_search.read_log(log) if log.exists() else []
    if repeated := {r["arm_id"] for r in logged_rows} & set(ids):
        raise typer.BadParameter(f"already logged, not re-scored: {sorted(repeated)}")
    logged = Counter(r["lever"] for r in logged_rows)
    for lever, n in Counter(a.lever for a in arms if a.lever != "ref").items():
        if logged[lever] + n > dev_arms.BUDGET[lever]:
            raise typer.BadParameter(f"{lever} budget {dev_arms.BUDGET[lever]} would be exceeded")

    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    kb_ids = sorted({a.config.kb_id for a in arms} | {"kb-v6"})
    manifests = {k: load_manifest(k) for k in kb_ids}
    kb_data = {k: kb.read(fetch_outputs(m)[0]) for k, m in manifests.items()}
    for k, m in manifests.items():
        if k != "kb-v5":
            _check_s3_kb("s3-v2", m)
    knowledges = {k: GeneKnowledge(d, ontology) for k, d in kb_data.items()}

    rows = dev_run.read_interviews(directory / interviews)
    items = [(r["case"], r["gene"]) for r in rows]
    base_ranks, arm_ranks = dev_search.score_arms(items, arms, knowledges, ontology, top_k, workers)

    spec, data, _ = _s3_dataset("s3-v2")
    entities = s3.read_entities(data, "s3-v2", {r["case_id"] for r in rows})
    onset_manifest = load_manifest("onset-ages-v2")
    onset_tsv = fetch_outputs(onset_manifest)[0]
    lit = {line.split("\t")[0] for line in onset_tsv.read_text().splitlines()[1:]}
    split_manifest = load_manifest("annot-split-v2")
    half_b = annotation_split.read(fetch_outputs(split_manifest)[0])
    source_of = {d: v["onset_source"] for d, v in kb_data["kb-v6"]["diseases"].items()}
    masks = dev_run.subset_masks(rows, entities, lit, half_b, source_of)
    index = {a.arm_id: j for j, a in enumerate(arms)}
    baselines = {v: index[v] for v in vs.split(",") if v}
    report_arms = dev_run.analyse(rows, base_ranks, arm_ranks, arms, masks, baselines)

    r1_meta, r1_base, r1_ranks = dev_run.r1_dev(arms, knowledges, ontology, top_k, workers)
    r1 = dev_run.r1_summary(r1_meta, r1_base, r1_ranks, arms)

    log_rows = [
        dev_search.log_row(a, report_arms[a.arm_id]["vs_e0_answers"]["all"], r1[a.arm_id], state.sha)
        for a in arms
    ]
    dev_search.append_log(log, log_rows)
    report = {
        "stage": stage,
        "cases": len(rows),
        "e0_answers_mrr": float(np.mean(1.0 / np.array(base_ranks))),
        "e0_initial_mrr": float(np.mean([1.0 / r["rank_initial"] for r in rows])),
        "subset_sizes": {k: int(sum(v)) for k, v in masks.items()},
        "r1_dev_cases": len(r1_meta),
        "r1_dev": r1,
        "arms": report_arms,
        "vs": vs,
        "code_sha": state.sha,
    }
    report_path = directory / f"{stage}.report.json"
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    ranks_path = directory / f"{stage}.ranks.tsv.gz"
    with gzip.open(ranks_path, "wt", newline="") as handle:
        handle.write("case_id\tgene\te0_answers\t" + "\t".join(ids) + "\n")
        for i, r in enumerate(rows):
            cells = "\t".join(f"{x:g}" for x in arm_ranks[i])
            handle.write(f"{r['case_id']}\t{r['gene']}\t{base_ranks[i]:g}\t{cells}\n")
    inputs = GenPheniaV3().lineage_inputs() + [
        {"id": f"artifact:{k}", "sha256": m.outputs[0].sha256} for k, m in manifests.items()
    ]
    inputs += [
        {"id": f"artifact:{spec.dataset_artifact}", "sha256": sha256_file(data)},
        {"id": f"artifact:{spec.exclusion_artifact}", "sha256": _s3_exclusion_sha(spec)},
        {"id": "split:s3-v2", "sha256": sha256_file(SPLITS_DIR / "s3-v2.json")},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        {"id": f"file:{interviews}", "sha256": sha256_file(directory / interviews)},
        {"id": "artifact:annot-split-v2", "sha256": split_manifest.outputs[0].sha256},
        {"id": "artifact:onset-ages-v2 (subset labels only)", "sha256": onset_manifest.outputs[0].sha256},
    ]
    params = {"stage": stage, "arms": ids, "vs": vs, "top_k": top_k, "interviews": interviews}
    write_manifest(
        build_manifest(artifact, "dev-search", inputs, params, [report_path, ranks_path, log], state=state)
    )
    for a, row in zip(arms, log_rows, strict=True):
        typer.echo(
            f"{a.arm_id:34} {a.config.config_hash} d={row['delta_mrr']:+.4f} "
            f"[{row['ci_lo']:+.4f},{row['ci_hi']:+.4f}] harmed={row['harmed']:.3f} "
            f"helped={row['helped']:.3f} "
            f"R1 d={row['r1dev_delta']:+.4f} [{row['r1dev_ci_lo']:+.4f},{row['r1dev_ci_hi']:+.4f}] "
            f"pass={row['r1dev_pass']}"
        )


if __name__ == "__main__":
    app()
