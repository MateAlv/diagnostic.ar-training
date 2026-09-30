"""`dxt knowledge …` and `dxt sim …`: simulator v0.4's artifacts (ADR-0011) and realism gate (ADR-0012)."""

import csv
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR, RESULTS_DIR, SPLITS_DIR
from diagnostic_ar_training.lineage.registry import LineageError

knowledge_app = typer.Typer(no_args_is_help=True, help="Knowledge artifacts for simulator v0.4 (ADR-0011).")
sim_app = typer.Typer(no_args_is_help=True, help="Realism of simulated datasets (ADR-0011, ADR-0012).")

FOCUS_DISEASES = ("OMIM:162000", "OMIM:142900", "OMIM:615471")
REALISM_DIR = RESULTS_DIR / "realism"
LEDGER = REALISM_DIR / "LEDGER.md"
MAX_CANDIDATE_VERSIONS = 3


def _require_clean():
    from diagnostic_ar_training.lineage.gitinfo import code_state

    state = code_state()
    if state.dirty:
        raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    return state


def _artifact_file(artifact_id: str, name: str) -> tuple[Path, str]:
    """Local path (fetched and verified) and sha256 of one output of a published artifact."""
    from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest

    manifest = load_manifest(artifact_id)
    for path, out in zip(fetch_outputs(manifest), manifest.outputs, strict=True):
        if path.name == name:
            return path, out.sha256
    raise LineageError(f"{artifact_id} has no output named {name}")


def _focus_counts(rows: list[dict], heldout: set[str]) -> dict:
    out = {}
    for disease in FOCUS_DISEASES:
        pheno = [r for r in rows if r["database_id"] == disease and r["aspect"] == "P"]
        survivors = [r for r in pheno if not set(r["reference"].split(";")) & heldout]
        out[disease] = {"phenotype_rows": len(pheno), "rows_left_by_whole_row_masking": len(survivors)}
    return out


@knowledge_app.command("recount")
def knowledge_recount(
    recount_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. hpoa-recount-v1"),
    split_id: str = typer.Option("r1-v1"),
    min_patients: int = typer.Option(3, help="Drop a recount with fewer patients (m) than this"),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """phenotype.hpoa with held-out-PMID rows recounted from R1-train phenopackets (ADR-0011 §1)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(recount_id)
    state = _require_clean()
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import genes, recount
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology

    names = ["hpo_ontology", "hpo_annotations", "orphanet_alignments"]
    paths = {n: open_source(n, Purpose.SIMULATE) for n in names}
    splits.write_heldout_pmids(split_id)
    mask_path = splits.heldout_pmids_path(split_id)
    heldout = set(mask_path.read_text().split())
    ontology = Ontology.from_json(paths["hpo_ontology"])
    cases = splits.load_part(split_id, splits.Part.TRAIN, Purpose.SIMULATE)
    patients = recount.patients_by_disease(
        cases, ontology, genes.parse_orphanet_alignments(paths["orphanet_alignments"])
    )
    comments, rows = recount.read_hpoa(paths["hpo_annotations"])
    out_rows, stats = recount.recount(
        rows, heldout, patients, ontology, split_id, min_patients, biocuration=recount_id
    )
    focus = _focus_counts(rows, heldout)
    for disease in FOCUS_DISEASES:
        pheno = [r for r in out_rows if r["database_id"] == disease and r["aspect"] == "P"]
        focus[disease]["rows_after_recount"] = len(pheno)
        focus[disease]["of_which_recount_rows"] = sum(r["reference"].startswith("R1-TRAIN:") for r in pheno)
    stats = {"totals": stats["totals"], "focus": focus, "per_disease": stats["per_disease"]}
    stats["totals"]["train_patients"] = len(cases)

    out_dir = INTERIM_DIR / "hpoa-recount" / recount_id
    hpoa_path = out_dir / "phenotype.hpoa"
    note = (
        f"#derived: {recount_id}; rows citing {split_id} held-out PMIDs recounted from {split_id} "
        f"train phenopackets (n/m, reference R1-TRAIN:{split_id}) or dropped when m < {min_patients}\n"
    )
    recount.write_hpoa(hpoa_path, comments + [note], out_rows)
    onsets_path = out_dir / "feature-onsets.tsv"
    onsets = recount.feature_onsets(out_rows, patients, ontology)
    recount.write_onsets(onsets_path, onsets)
    stats["totals"]["feature_onset_pairs"] = len(onsets)
    stats_path = DATA_DIR / "hpoa-recount" / f"{recount_id}.stats.json"
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")

    sources = load_sources()
    inputs = [sources[n].as_input() for n in names]
    inputs += [
        {"id": f"heldout-pmids:{split_id}", "sha256": sha256_file(mask_path)},
        {"id": f"split:{split_id}", "sha256": sha256_file(SPLITS_DIR / f"{split_id}.json")},
    ]
    params = {
        "adr": "0011 §1",
        "split": split_id,
        "part": "train",
        "min_patients": min_patients,
        "n": "patients with the term or a descendant present",
        "m": "n + patients excluding the term or an ancestor of it",
        "disease_match": "OMIM id directly; ORPHA via exact validated Orphanet alignments",
        "other_aspects_citing_heldout": "dropped",
    }
    notes = ", ".join(
        f"{k}={stats['totals'][k]}"
        for k in ("rows_kept_unchanged", "rows_recounted", "recount_rows_written", "rows_dropped")
    )
    manifest = build_manifest(
        recount_id,
        "hpoa-recount",
        inputs,
        params,
        [hpoa_path, onsets_path, stats_path],
        notes=notes,
        state=state,
    )
    if publish:
        manifest = publish_release(manifest, recount_id)
    write_manifest(manifest)
    typer.echo(json.dumps({"totals": stats["totals"], "focus": focus}, indent=1))


@knowledge_app.command("cardinal")
def knowledge_cardinal(
    cardinal_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. cardinal-v1"),
    recount_id: str = typer.Option("hpoa-recount-v1", "--recount"),
    split_id: str = typer.Option("r1-v1"),
    min_patients: int = typer.Option(10, help="cardinal_proxy: pooled m at least this"),
    min_frequency: float = typer.Option(0.8, help="cardinal_proxy: pooled n/m at least this"),
    publish: bool = typer.Option(False),
) -> None:
    """Hallmark features: Orphadata product-4 diagnostic criteria + count-based proxies (ADR-0011 §4)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(cardinal_id)
    state = _require_clean()
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import cardinal, genes, recount
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology

    names = ["hpo_ontology", "orphanet_phenotypes", "orphanet_alignments"]
    paths = {n: open_source(n, Purpose.SIMULATE) for n in names}
    splits.write_heldout_pmids(split_id)
    mask_path = splits.heldout_pmids_path(split_id)
    hpoa_path, hpoa_sha = _artifact_file(recount_id, "phenotype.hpoa")
    sources = load_sources()
    rows, stats = cardinal.build(
        cardinal.parse_product4(paths["orphanet_phenotypes"]),
        recount.read_hpoa(hpoa_path)[1],
        Ontology.from_json(paths["hpo_ontology"]),
        genes.parse_orphanet_alignments(paths["orphanet_alignments"]),
        set(mask_path.read_text().split()),
        product4_name=f"orphanet_phenotypes@{sources['orphanet_phenotypes'].version}",
        recount_name=recount_id,
        min_patients=min_patients,
        min_frequency=min_frequency,
    )
    out_dir = DATA_DIR / "cardinal"
    tsv = out_dir / f"{cardinal_id}.tsv"
    cardinal.write(tsv, rows)
    stats_path = out_dir / f"{cardinal_id}.stats.json"
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    inputs = [sources[n].as_input() for n in names]
    inputs += [
        {"id": f"artifact:{recount_id}", "sha256": hpoa_sha},
        {"id": f"heldout-pmids:{split_id}", "sha256": sha256_file(mask_path)},
    ]
    params = {
        "adr": "0011 §4",
        "product4_kinds": sorted(cardinal.DIAGNOSTIC_CRITERIA.values()),
        "product4_omim": "rows repeated for OMIM ids exactly and validatedly aligned to the ORPHA disorder",
        "product4_heldout": "disorders citing a held-out PMID are dropped",
        "proxy_min_patients": min_patients,
        "proxy_min_frequency": min_frequency,
        "proxy_rule": "pooled count rows (n/m) of hpoa-recount; raw n/m, no prior",
    }
    manifest = build_manifest(
        cardinal_id, "cardinal-features", inputs, params, [tsv, stats_path], state=state
    )
    if publish:
        manifest = publish_release(manifest, cardinal_id)
    write_manifest(manifest)
    typer.echo(json.dumps(stats, indent=1))


@knowledge_app.command("report-model")
def knowledge_report_model(
    model_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. report-model-v1"),
    kb_id: str = typer.Option("kb-v4", "--kb", help="KB masking every R1 publication"),
    cardinal_id: str = typer.Option("cardinal-v1", "--cardinal"),
    split_id: str = typer.Option("r1-v1"),
    publish: bool = typer.Option(False),
) -> None:
    """Fit how clinicians report true features, on R1-train (ADR-0011 §3)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(model_id)
    state = _require_clean()
    import numpy as np

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import cardinal, genes
    from diagnostic_ar_training.knowledge import report_model as R
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, load_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb as kb_mod
    from diagnostic_ar_training.rerank.features import GeneKnowledge

    kb_manifest = load_manifest(kb_id)
    if kb_manifest.params.get("mask_scope") != "all":
        raise typer.BadParameter(f"{kb_id} must mask every R1 publication (mask_scope=all)")
    kb_path, kb_sha = _artifact_file(kb_id, "kb.json.gz")
    kb = kb_mod.read(kb_path)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.TRAIN))
    pairs = genes.parse_orphanet_alignments(open_source("orphanet_alignments", Purpose.TRAIN))
    card_manifest = load_manifest(cardinal_id)
    card_path = DATA_DIR / "cardinal" / f"{cardinal_id}.tsv"
    all_r1 = splits.mask_pmids(split_id, "all")
    card_rows = cardinal.read(card_path)
    usable = {
        (r["disease_id"], r["hpo_id"])
        for r in card_rows
        if not any(ref in all_r1 or ref.startswith("R1-TRAIN:") for ref in cardinal.references(r["source"]))
    }
    cases = splits.load_part(split_id, splits.Part.TRAIN, Purpose.TRAIN)
    groups = splits.publication_groups(split_id)
    annotations, n_diseases = R.annotation_counts(kb, ontology)
    reportability = R.reportability_counts(cases, ontology)
    featurizer = R.Featurizer(ontology, annotations, n_diseases, reportability, len(cases), usable)
    X, y, row_genes, row_stats = R.training_rows(cases, groups, kb, featurizer, pairs)
    full_cols = tuple(range(len(R.FEATURES)))
    freq_cols = tuple(R.FEATURES.index(f) for f in R.FREQUENCY_ONLY)
    full = R.fit(X, y, full_cols)
    freq_only = R.fit(X, y, freq_cols)
    base_rate = float(y.mean())
    base_logit = np.full(len(y), np.log(base_rate / (1 - base_rate)))
    knowledge = GeneKnowledge(kb, ontology)
    scorers = {
        "full": R.internal_scorer(featurizer, full, full_cols),
        "frequency_only": R.internal_scorer(featurizer, freq_only, freq_cols),
    }
    fit_report = {
        **row_stats,
        "positive_rate": base_rate,
        "log_loss": {
            "base_rate": R.log_loss(y, base_logit),
            "frequency_only": R.log_loss(y, R.logit(freq_only, X, freq_cols)),
            "full": R.log_loss(y, R.logit(full, X, full_cols)),
        },
        "auc": {
            "frequency_only": R.auc(y, R.logit(freq_only, X, freq_cols)),
            "full": R.auc(y, R.logit(full, X, full_cols)),
        },
        "within_gene_rho_r1_train_in_sample": R.gene_level_rho(
            cases, knowledge.diseases, kb, ontology, usable, scorers, min_patients=5
        ),
        "note": "log loss and AUC use leave-publication-out reportability; the within-gene rho uses "
        "full R1-train reportability, so it is in-sample and optimistic. Out-of-sample: "
        "dxt sim report-model-check (R1-dev).",
    }
    sources = load_sources()
    provenance = {
        "adr": "0011 §3",
        "fitted_on": f"{split_id} train ({len(cases)} patients)",
        "kb": kb_id,
        "cardinal": cardinal_id,
        "hpo_version": sources["hpo_ontology"].version,
        "code_sha": state.sha,
        "unit": "(R1-train patient, phenotypic-abnormality term of the patient's disease profile in "
        f"{kb_id}, OMIM and exactly aligned ORPHA ids merged); label 1 if the patient reports the term "
        "or a descendant of it",
        "internal_coefficients": {
            "intercept": full["intercept"],
            **dict(zip(R.FEATURES, full["coef"], strict=True)),
        },
        "reference_models": {
            "frequency_only": {
                "intercept": freq_only["intercept"],
                **dict(zip(R.FREQUENCY_ONLY, freq_only["coef"], strict=True)),
            }
        },
        "fit": fit_report,
        "cardinal_flag": {
            "rows_in_artifact": len(card_rows),
            "rows_used_for_fit": len(usable),
            "fit_rule": "rows resting on any R1 publication or on R1-train recounts are left out while "
            "fitting, so the flag carries no information from the scored patients' papers",
        },
        "term_budget": {k: v for k, v in R.term_budget(cases).items() if k != "histogram"},
    }
    notes = (
        "Fitted with ADR-0007 frequencies from the masked KB; the simulator scores its own merged, "
        "shrunk frequencies. Ancestor counts assume HPO " + sources["hpo_ontology"].version + "."
    )
    body = R.to_simulator_format(
        model_id, full, annotations, n_diseases, reportability, len(cases), R.term_budget(cases),
        provenance, notes,
    )  # fmt: skip
    exported = R.simulator_scorer(body, ontology)
    for term in sorted(set(reportability) | set(annotations))[::97]:
        for freq in (None, 0.3):
            for flag in (False, True):
                gap = abs(exported(term, freq, flag) - scorers["full"](term, freq, flag))
                if gap > 1e-9:
                    raise LineageError(f"exported model disagrees with the fit on {term}: {gap}")
    out_path = INTERIM_DIR / "report-model" / model_id / "report-model.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    summary = {k: v for k, v in body.items() if k not in ("tables", "reportability")}
    summary["reportability"] = {k: v for k, v in body["reportability"].items() if k != "counts"}
    summary_path = DATA_DIR / "report-model" / f"{model_id}.summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    inputs = [
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        {"id": f"artifact:{cardinal_id}", "sha256": card_manifest.outputs[0].sha256},
        {"id": f"split:{split_id}", "sha256": sha256_file(SPLITS_DIR / f"{split_id}.json")},
        {"id": f"all-pmids:{split_id}", "sha256": sha256_file(splits.mask_path(split_id, "all"))},
        sources["hpo_ontology"].as_input(),
        sources["orphanet_alignments"].as_input(),
    ]
    params = {
        "adr": "0011 §3",
        "kb": kb_id,
        "cardinal": cardinal_id,
        "part": "train",
        "l2": R.L2,
        "format": "rare-disease-simulator report-model v1",
    }
    manifest = build_manifest(model_id, "report-model", inputs, params, [out_path, summary_path], state=state)
    if publish:
        manifest = publish_release(manifest, model_id)
    write_manifest(manifest)
    typer.echo(
        json.dumps(
            {"features": body["features"], "intercept": body["intercept"], "fit": fit_report}, indent=1
        )
    )


@knowledge_app.command("shrinkage-prior")
def knowledge_shrinkage_prior(
    calib_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. simcal-v04-v1"),
    recount_id: str = typer.Option("hpoa-recount-v1", "--recount"),
) -> None:
    """Simulator calibration file with frequency.shrinkage_mean: the median count-based frequency
    of an hpoa-recount artifact (ADR-0011, simulator v0.4 step 2)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(calib_id)
    state = _require_clean()
    import statistics

    from diagnostic_ar_training.knowledge import recount
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology

    hpoa_path, hpoa_sha = _artifact_file(recount_id, "phenotype.hpoa")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.SIMULATE))
    freqs = recount.count_frequencies(recount.read_hpoa(hpoa_path)[1], ontology)
    median = statistics.median(freqs)
    body = {
        "frequency.shrinkage_mean": round(median, 6),
        "_provenance": {
            "artifact": calib_id,
            "source": f"{recount_id} ({hpoa_sha})",
            "rule": "median of pooled raw n/m over (disease, term) pairs with count-notation positive "
            "phenotype rows (ADR-0011: Beta prior mean for count-based frequencies, strength 2)",
            "pairs": len(freqs),
            "mean": round(statistics.fmean(freqs), 6),
            "code_sha": state.sha,
        },
    }
    out = DATA_DIR / "calib" / f"{calib_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n")
    inputs = [{"id": f"artifact:{recount_id}", "sha256": hpoa_sha}, load_sources()["hpo_ontology"].as_input()]
    params = {"statistic": "median pooled count-based frequency", "recount": recount_id}
    write_manifest(build_manifest(calib_id, "simulator-calibration-file", inputs, params, [out], state=state))
    typer.echo(json.dumps(body, indent=1))


@knowledge_app.command("panel")
def knowledge_panel(
    panel_id: str = typer.Option(..., "--id", help="Immutable artifact id, e.g. literature-panel-v1"),
    path: Path = typer.Option(..., help="Committed panel TSV"),
) -> None:
    """Check a literature panel's HPO ids and labels against the pinned HPO, and register it."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(panel_id)
    state = _require_clean()
    from diagnostic_ar_training.eval import realism
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology

    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
    rows, _ = realism.read_panel(path)
    problems = []
    with Path(path).open(encoding="utf-8") as handle:
        raw = list(csv.DictReader((x for x in handle if not x.startswith("#")), delimiter="\t"))
    for r, parsed in zip(raw, rows, strict=True):
        term = parsed["hpo_id"]
        if ontology.resolve(term) != term:
            problems.append(f"{r['gene']} {term}: not a current HPO id")
        elif r.get("hpo_label") and ontology.labels.get(term) != r["hpo_label"]:
            problems.append(f"{r['gene']} {term}: label {r['hpo_label']!r} != {ontology.labels.get(term)!r}")
    if problems:
        raise typer.BadParameter("; ".join(problems))
    params = {"rows": len(rows), "genes": len({r["gene"] for r in rows}), "checked_against": "hpo_ontology"}
    manifest = build_manifest(
        panel_id, "literature-panel", [load_sources()["hpo_ontology"].as_input()], params, [path], state=state
    )
    write_manifest(manifest)
    typer.echo(json.dumps(params))


# --- realism --------------------------------------------------------------------------------------


def _ledger_rows() -> list[dict]:
    if not LEDGER.exists():
        return []
    rows = []
    for line in LEDGER.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0][:2] == "20":
            rows.append(
                dict(
                    zip(
                        ("date", "label", "dataset", "sha256", "commit", "role", "version"),
                        cells,
                        strict=True,
                    )
                )
            )
    return rows


def check_budget(version: str | None, baseline: bool, rows: list[dict]) -> None:
    """ADR-0012: at most 3 candidate simulator versions may be compared on R1-dev before one is frozen."""
    if baseline:
        return
    if not version:
        raise typer.BadParameter("a candidate run needs --sim-version (or --baseline for UP/V03)")
    seen = {r["version"] for r in rows if r["role"] == "candidate"}
    if version not in seen and len(seen) >= MAX_CANDIDATE_VERSIONS:
        raise LineageError(f"R1-dev budget spent: candidate versions {sorted(seen)} already compared")


def _append_ledger(label: str, dataset: str, sha: str, commit: str, role: str, version: str) -> None:
    REALISM_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER.exists():
        LEDGER.write_text(
            "# R1-dev realism ledger\n\n"
            "Every `dxt sim realism` run reads R1-dev as a check (ADR-0011, ADR-0012). At most 3 candidate "
            "simulator versions may be compared before one is frozen; baselines (UP, V03) do not count.\n\n"
            "| Date (UTC) | Label | Dataset | Dataset sha256 | Commit | Role | Simulator version |\n"
            "|---|---|---|---|---|---|---|\n"
        )
    date = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
    with LEDGER.open("a") as handle:
        handle.write(f"| {date} | {label} | {dataset} | {sha} | {commit[:12]} | {role} | {version} |\n")


def _dataset(spec: str):
    """(cases, dataset id, sha256) from `source:<name>`, `artifact:<id>` or a path to an export."""
    from diagnostic_ar_training.eval import realism
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source

    if spec.startswith("source:"):
        name = spec.split(":", 1)[1]
        source = load_sources()[name]
        return realism.load_graphens(open_source(name, Purpose.EVAL)), source.as_input()["id"], source.sha256
    if spec.startswith("artifact:"):
        artifact_id = spec.split(":", 1)[1]
        manifest = load_manifest(artifact_id)
        for path, out in zip(fetch_outputs(manifest), manifest.outputs, strict=True):
            if path.name.endswith(".jsonl.gz"):
                return realism.load_export(path), spec, out.sha256
        raise LineageError(f"{artifact_id} has no .jsonl.gz output")
    path = Path(spec)
    return realism.load_export(path), f"path:{path.name}", sha256_file(path)


def _gene_terms_factory(kb: dict, knowledge, ontology):
    """Gene -> {term: P(term | gene)} (`report_model.gene_frequencies`), cached."""
    from diagnostic_ar_training.knowledge.report_model import gene_frequencies

    cache = {}

    def gene_terms(gene: str) -> dict[str, float | None]:
        if gene not in cache:
            cache[gene] = gene_frequencies(kb, knowledge.diseases(gene), ontology)
        return cache[gene]

    return gene_terms


@sim_app.command("realism")
def sim_realism(
    dataset: str = typer.Option(..., help="Export path, artifact:<id> or source:<name> (UP)"),
    label: str = typer.Option(..., help="Name of this report, e.g. v0.3-baseline"),
    baseline: bool = typer.Option(False, help="A comparator (UP, V03): does not spend R1-dev budget"),
    sim_version: str = typer.Option("", help="Candidate simulator version, counted against the budget"),
    panel: Path = typer.Option(DATA_DIR / "realism" / "literature-panel-v1.tsv", help="Evaluation panel TSV"),
    kb_id: str = typer.Option("kb-v5", "--kb", help="KB for the C2ST gene-annotation features"),
    freq_kb_id: str = typer.Option("kb-v4", "--freq-kb", help="KB masking all R1, for frequency calibration"),
    e0_cases: int = typer.Option(5000, help="Fixed-seed subsample scored by E0 (G2e); 0 skips"),
    seed: int = typer.Option(20260930),
) -> None:
    """ANALYSIS-001 + ADR-0012 G2 metrics of one dataset: results/realism/<label>.json, manifest, ledger."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    ensure_new(f"realism-{label}")
    state = _require_clean()
    check_budget(sim_version or None, baseline, _ledger_rows())
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.eval import realism as RZ
    from diagnostic_ar_training.knowledge import report_model as R
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology
    from diagnostic_ar_training.rerank import kb as kb_mod
    from diagnostic_ar_training.rerank.features import GeneKnowledge

    cases, dataset_id, dataset_sha = _dataset(dataset)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
    closure = RZ.Closure(ontology)
    dev = splits.load_part("r1-v1", splits.Part.DEV, Purpose.EVAL)
    train = splits.load_part("r1-v1", splits.Part.TRAIN, Purpose.EVAL)
    groups = splits.publication_groups("r1-v1")

    sim_cases = defaultdict(list)
    for c in cases:
        sim_cases[c.gene.upper()].append(c)
    dev_by_gene = defaultdict(list)
    for c in dev:
        dev_by_gene[c.gene.upper()].append(closure(c.present))
    needed = {g for g, v in dev_by_gene.items() if len(v) >= 5}
    sim_by_gene = {g: [closure(c.present) for c in sim_cases[g]] for g in needed if g in sim_cases}

    g2p = defaultdict(set)
    with open_source("hpo_genes_to_phenotype", Purpose.EVAL).open(encoding="utf-8") as handle:
        for r in csv.DictReader(handle, delimiter="\t"):
            if (t := ontology.resolve(r["hpo_id"])) and ontology.is_a(t, PHENOTYPIC_ABNORMALITY):
                g2p[r["gene_symbol"].upper()].add(t)

    freq_kb_path, freq_kb_sha = _artifact_file(freq_kb_id, "kb.json.gz")
    freq_kb = kb_mod.read(freq_kb_path)
    freq_knowledge = GeneKnowledge(freq_kb, ontology)
    gene_terms = _gene_terms_factory(freq_kb, freq_knowledge, ontology)
    vocab_upper = {k.upper(): k for k in freq_kb.get("vocabulary", {})} | {
        k.upper(): k for k in freq_kb["genes"]
    }

    report: dict = {
        "label": label,
        "dataset": dataset_id,
        "dataset_sha256": dataset_sha,
        "cases": len(cases),
        "genes": len(sim_cases),
        "has_excluded": any(c.excluded is not None for c in cases),
    }
    report["g2b_dev_rho"] = RZ.per_gene_rho(dev_by_gene, sim_by_gene, lambda g: g2p.get(g, set()))
    report["frequency_calibration_dev"] = RZ.frequency_calibration(
        dev_by_gene, sim_by_gene, lambda g: gene_terms(vocab_upper.get(g, g))
    )

    sizes = {
        "sim": [len(c.present) for c in cases],
        "train": [len(c.present) for c in train],
        "dev": [len(c.present) for c in dev],
    }
    present = {
        "sim": RZ.distribution(sizes["sim"]),
        "r1_train": RZ.distribution(sizes["train"]),
        "r1_dev": RZ.distribution(sizes["dev"]),
        "w1_vs_r1_train": RZ.wasserstein(sizes["sim"], sizes["train"]),
        "w1_vs_r1_dev": RZ.wasserstein(sizes["sim"], sizes["dev"]),
    }
    terms_per_case = {"present": present}
    if report["has_excluded"]:
        ex_sim = [len(c.excluded or ()) for c in cases]
        ex_train = [len(c.excluded) for c in train]
        terms_per_case["excluded"] = {
            "sim": RZ.distribution(ex_sim),
            "r1_train": RZ.distribution(ex_train),
            "w1_vs_r1_train": RZ.wasserstein(ex_sim, ex_train),
        }
    report["g2c_terms_per_case"] = terms_per_case

    panel_rows, has_kind = RZ.read_panel(panel)
    panel_sim = {r["gene"]: sim_cases.get(r["gene"].upper(), []) for r in panel_rows}
    report["g2a_panel"] = {
        "panel": panel.name,
        "panel_sha256": sha256_file(panel),
        **RZ.panel_errors(panel_rows, panel_sim, closure, has_kind),
    }

    c2st_kb_path, c2st_kb_sha = _artifact_file(kb_id, "kb.json.gz")
    c2st_kb = kb_mod.read(c2st_kb_path)
    c2st_knowledge = GeneKnowledge(c2st_kb, ontology)
    annotations, n_diseases = R.annotation_counts(c2st_kb, ontology)
    features = RZ.CaseFeatures(ontology, annotations, n_diseases, c2st_knowledge)
    real = [c for c in train if c.gene.upper() in sim_cases]
    sim_index = defaultdict(list)
    for j, c in enumerate(cases):
        sim_index[c.gene.upper()].append(j)
    pairs = RZ.matched_pairs([(c.case_id, c.gene.upper()) for c in real], sim_index, len(cases), seed)
    used_sim = sorted({j for _, j in pairs})
    X_real = [features(c.gene, c.present) for c in real]
    sim_rows = {j: features(cases[j].gene, cases[j].present) for j in used_sim}
    import numpy as np

    X_sim = np.zeros((len(cases), len(features.names())))
    for j, row in sim_rows.items():
        X_sim[j] = row
    report["g2d_c2st"] = {
        **RZ.c2st(np.asarray(X_real), X_sim, [groups[c.case_id] for c in real], pairs, n_scalar=6, seed=seed),
        "r1_train_patients_total": len(train),
        "r1_train_patients_with_gene_in_dataset": len(real),
        "gene_matched_pairs": sum(real[i].gene.upper() == cases[j].gene.upper() for i, j in pairs),
        "features": features.names(),
        "kb": kb_id,
    }

    if e0_cases:
        from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

        report["g2e_e0"] = {
            **RZ.e0_difficulty(GenPheniaV3(), RZ.subsample(cases, e0_cases, seed)),
            "seed": seed,
            "view": "present",
        }

    REALISM_DIR.mkdir(parents=True, exist_ok=True)
    out = REALISM_DIR / f"{label}.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True, default=float) + "\n")
    sources = load_sources()
    inputs = [
        {"id": dataset_id, "sha256": dataset_sha},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        {"id": f"artifact:{kb_id}", "sha256": c2st_kb_sha},
        {"id": f"artifact:{freq_kb_id}", "sha256": freq_kb_sha},
        {"id": f"panel:{panel.name}", "sha256": sha256_file(panel)},
        sources["hpo_ontology"].as_input(),
        sources["hpo_genes_to_phenotype"].as_input(),
    ]
    if e0_cases:
        inputs.append(sources["genphenia_v3"].as_input())
    params = {
        "label": label,
        "role": "baseline" if baseline else "candidate",
        "sim_version": sim_version or None,
        "e0_cases": e0_cases,
        "seed": seed,
        "min_dev_patients_rho": RZ.MIN_DEV_PATIENTS,
    }
    write_manifest(build_manifest(f"realism-{label}", "realism-report", inputs, params, [out], state=state))
    _append_ledger(
        label, dataset_id, dataset_sha, state.sha, "baseline" if baseline else "candidate", sim_version or "—"
    )
    typer.echo(json.dumps(RZ.g2_values(report), indent=1))


def _read_tsv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


@sim_app.command("report-model-check")
def sim_report_model_check(
    model_id: str = typer.Option(..., "--id", help="Report model artifact, e.g. report-model-v2"),
    min_patients: int = typer.Option(5),
) -> None:
    """Out-of-sample check of a report model: within-gene rho on R1-dev vs frequency alone (ledgered)."""
    from diagnostic_ar_training.lineage.manifest import ensure_new

    check_id = f"realism-{model_id}-dev"
    ensure_new(check_id)
    state = _require_clean()
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import report_model as R
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, load_manifest, write_manifest
    from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.rerank import kb as kb_mod
    from diagnostic_ar_training.rerank.features import GeneKnowledge

    manifest = load_manifest(model_id)
    model_path, model_sha = _artifact_file(model_id, "report-model.json")
    body = json.loads(model_path.read_text())
    kb_id, cardinal_id = manifest.params["kb"], manifest.params["cardinal"]
    kb_path, kb_sha = _artifact_file(kb_id, "kb.json.gz")
    kb = kb_mod.read(kb_path)
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.EVAL))
    cardinal = {
        (r["disease_id"], r["hpo_id"]) for r in _read_tsv(DATA_DIR / "cardinal" / f"{cardinal_id}.tsv")
    }
    ref = body["provenance"]["reference_models"]["frequency_only"]
    freq_only = {
        **body,
        "intercept": ref["intercept"],
        "features": [{**body["features"][0], "coefficient": ref["frequency"],
                      "unknown_value": ref["frequency_unknown"] / ref["frequency"]}],
    }  # fmt: skip
    scorers = {
        "full": R.simulator_scorer(body, ontology),
        "frequency_only": R.simulator_scorer(freq_only, ontology),
    }
    dev = splits.load_part("r1-v1", splits.Part.DEV, Purpose.EVAL)
    result = {
        "artifact": model_id,
        "sha256": model_sha,
        "part": "r1-v1 dev",
        "cardinal": cardinal_id,
        **R.gene_level_rho(
            dev, GeneKnowledge(kb, ontology).diseases, kb, ontology, cardinal, scorers, min_patients
        ),
    }
    REALISM_DIR.mkdir(parents=True, exist_ok=True)
    out = REALISM_DIR / f"{model_id}-dev.json"
    out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    inputs = [
        {"id": f"artifact:{model_id}", "sha256": model_sha},
        {"id": f"artifact:{kb_id}", "sha256": kb_sha},
        {"id": "split:r1-v1", "sha256": sha256_file(SPLITS_DIR / "r1-v1.json")},
        load_sources()["hpo_ontology"].as_input(),
    ]
    params = {"min_patients": min_patients, "check": "within-gene rho on R1-dev"}
    write_manifest(build_manifest(check_id, "report-model-check", inputs, params, [out], state=state))
    _append_ledger(check_id, f"artifact:{model_id}", model_sha, state.sha, "check", "—")
    typer.echo(json.dumps(result, indent=1))


@sim_app.command("gate")
def sim_gate(
    baseline: list[str] = typer.Option(["up-graphens", "v0.3-baseline"], help="Realism labels of UP and V03"),
    candidate: list[str] = typer.Option([], help="Realism labels of candidate datasets"),
    name: str = typer.Option("baselines", help="Stem of results/realism/gate-<name>.{json,md}"),
) -> None:
    """ADR-0012 G2 comparison table, with pass/fail per criterion for each candidate."""
    from diagnostic_ar_training.eval import realism as RZ

    def load(label: str) -> dict:
        return json.loads((REALISM_DIR / f"{label}.json").read_text())

    table = RZ.gate({b: load(b) for b in baseline}, {c: load(c) for c in candidate})
    (REALISM_DIR / f"gate-{name}.json").write_text(json.dumps(table, indent=1, sort_keys=True) + "\n")
    (REALISM_DIR / f"gate-{name}.md").write_text(RZ.gate_markdown(table))
    typer.echo(RZ.gate_markdown(table))
