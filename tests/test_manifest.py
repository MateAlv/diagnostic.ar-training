import pytest

from diagnostic_ar_training.lineage import manifest
from diagnostic_ar_training.lineage.registry import LineageError


def test_manifest_records_inputs_params_and_output_hashes(tmp_path, clean_tree, monkeypatch):
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path)
    out = tmp_path / "ds.jsonl"
    out.write_text("{}\n")
    m = manifest.build_manifest(
        "ds-test", "dataset", [{"id": "source:x@1", "sha256": "0" * 64}], {"seed": 1}, [out]
    )
    manifest.write_manifest(m)
    assert m.code["sha"] == clean_tree.sha and m.outputs[0].bytes == 3
    assert manifest.verify_outputs(m) == []
    out.write_text("changed\n")
    assert manifest.verify_outputs(m) == [f"{out}: sha256 mismatch"]
    with pytest.raises(LineageError):
        manifest.write_manifest(m)


def test_artifacts_cannot_be_built_from_uncommitted_code(tmp_path, dirty_tree):
    out = tmp_path / "x"
    out.write_text("x")
    with pytest.raises(LineageError):
        manifest.build_manifest("x", "dataset", [], {}, [out])


def test_run_outputs_do_not_count_as_dirty_code(monkeypatch):
    from diagnostic_ar_training.lineage import gitinfo

    status = " M docs/TEST_LEDGER.md\n M results/EXP-000/x.json\n M data/manifests/a.json"
    monkeypatch.setattr(gitinfo, "_run_git", lambda args, cwd: status if args[0] == "status" else "sha\n")
    assert gitinfo.code_state().dirty is False
    status += "\n M src/diagnostic_ar_training/splits.py"
    assert gitinfo.code_state().dirty is True


def test_a_published_output_missing_locally_is_not_a_lineage_problem(tmp_path, clean_tree):
    out = tmp_path / "kb.json.gz"
    out.write_text("x")
    m = manifest.build_manifest("kb-test", "rerank-kb", [], {}, [out])
    out.unlink()
    assert manifest.verify_outputs(m) == [f"{out}: missing"]
    assert manifest.verify_outputs(m.model_copy(update={"release": "kb-test"})) == []


def test_an_existing_artifact_id_is_refused_before_any_work(tmp_path, monkeypatch):
    monkeypatch.setattr(manifest, "MANIFESTS_DIR", tmp_path)
    manifest.ensure_new("kb-v9")
    (tmp_path / "kb-v9.json").write_text("{}")
    with pytest.raises(LineageError):
        manifest.ensure_new("kb-v9")
