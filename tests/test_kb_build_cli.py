import json
from types import SimpleNamespace

from test_kb import HEADER, ROWS, _write_fixtures, built, hpoa_row  # noqa: F401
from typer.testing import CliRunner

import diagnostic_ar_training as pkg
from diagnostic_ar_training import cli, splits
from diagnostic_ar_training.knowledge import annotation_split
from diagnostic_ar_training.lineage import manifest, registry
from diagnostic_ar_training.rerank import kb as kb_mod

SOURCES = (
    "hpo_ontology",
    "hpo_annotations",
    "hpo_genes_to_disease",
    "hpo_genes_to_phenotype",
    "orphanet_ages_2026_06",
    "orphanet_alignments",
)
SHA = "0" * 64


def test_frequency_basis_is_counted(built):  # noqa: F811
    _, _, (_, stats) = built
    keys = ("from_counts", "from_percent", "from_category", "unknown")
    basis = [stats[f"phenotypes_frequency_{k}"] for k in keys]
    assert sum(basis) == stats["phenotype_annotations"]
    assert stats["phenotypes_frequency_from_counts"] >= 1 and stats["phenotypes_frequency_unknown"] >= 1


def _run_kb_build(tmp_path, monkeypatch, clean_tree, extra):
    onto_path = _write_fixtures(tmp_path)
    extra_row = hpoa_row("OMIM:1", "HP:0000028", ref="PMID:5")
    enriched = tmp_path / "enriched.hpoa"
    enriched.write_text("#version: test\n" + HEADER + "\n" + "\n".join([*ROWS, extra_row]) + "\n")
    held = tmp_path / "heldout.tsv"
    annotation_split.write([("OMIM:1", "HP:0000028")], held)
    mask = tmp_path / "mask.txt"
    mask.write_text("PMID:666\n")
    profiles = tmp_path / "profiles.json"
    profiles.write_text("{}")
    profile_data = {
        "genes": {"GENEA": {"entities": [{"sim_weight": 1.0, "profile_ids": ["OMIM:1"]}]}},
        "vocabulary": {},
    }
    artifact_files = {"genes-t": profiles, "annot-t": held, "hpoa-t": enriched}
    fake_sources = {
        n: SimpleNamespace(as_input=lambda n=n: {"id": f"source:{n}@t", "sha256": SHA}) for n in SOURCES
    }
    files = {
        "hpo_ontology": onto_path,
        "hpo_annotations": tmp_path / "phenotype.hpoa",
        "hpo_genes_to_disease": tmp_path / "g2d.txt",
        "hpo_genes_to_phenotype": tmp_path / "g2p.txt",
        "orphanet_ages_2026_06": tmp_path / "ages.xml",
        "orphanet_alignments": None,
    }
    opened = []

    def open_source(name, purpose):
        opened.append(name)
        return files[name]

    def load_manifest(artifact_id):
        return SimpleNamespace(outputs=[SimpleNamespace(sha256=SHA)], file=artifact_files[artifact_id])

    real_read = kb_mod.read
    monkeypatch.setattr(registry, "open_source", open_source)
    monkeypatch.setattr(registry, "load_sources", lambda: fake_sources)
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path / "manifests")
    monkeypatch.setattr(manifest, "load_manifest", load_manifest)
    monkeypatch.setattr(manifest, "fetch_outputs", lambda m: [m.file])
    monkeypatch.setattr(pkg, "INTERIM_DIR", tmp_path / "interim")
    monkeypatch.setattr(cli, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(splits, "write_mask", lambda *a: "")
    monkeypatch.setattr(splits, "mask_path", lambda *a: mask)
    monkeypatch.setattr(kb_mod, "read", lambda p: profile_data if p == profiles else real_read(p))
    args = ["kb", "build", "--id", "kb-t", "--gene-profiles", "genes-t", *extra]
    result = CliRunner().invoke(cli.app, args)
    return result, opened, tmp_path / "manifests" / "kb-t.json"


def test_kb_build_reads_an_hpoa_artifact_and_records_it(tmp_path, monkeypatch, clean_tree):
    extra = ["--hpoa-artifact", "hpoa-t", "--holdout-annotations", "annot-t"]
    result, opened, path = _run_kb_build(tmp_path, monkeypatch, clean_tree, extra)
    assert result.exit_code == 0, result.output
    assert "hpo_annotations" not in opened
    body = json.loads(path.read_text())
    ids = [i["id"] for i in body["inputs"]]
    assert "artifact:hpoa-t" in ids and not any(i.startswith("source:hpo_annotations") for i in ids)
    assert body["params"]["hpoa_artifact"] == "hpoa-t"
    assert body["params"]["heldout_annotations_dropped"] == "annot-t"
    stats = json.loads((tmp_path / "data" / "kb" / "kb-t.stats.json").read_text())
    assert stats["rows_dropped_heldout_annotation"] == 2


def test_kb_build_without_hpoa_artifact_uses_the_pinned_source(tmp_path, monkeypatch, clean_tree):
    result, opened, path = _run_kb_build(tmp_path, monkeypatch, clean_tree, [])
    assert result.exit_code == 0, result.output
    assert "hpo_annotations" in opened
    body = json.loads(path.read_text())
    assert "hpoa_artifact" not in body["params"]
    assert any(i["id"].startswith("source:hpo_annotations") for i in body["inputs"])
