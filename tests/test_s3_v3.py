import gzip
import json

import pytest

from diagnostic_ar_training.cohorts import s3
from diagnostic_ar_training.lineage import ledger
from diagnostic_ar_training.lineage.registry import LineageError


def test_s3_v3_names_its_dataset_reuses_annot_split_v2_and_splits_30_70():
    v3 = s3.spec("s3-v3")
    assert (v3.dataset_artifact, v3.annotation_split, v3.exclusion_artifact) == (
        "s3-data-v3",
        "annot-split-v2",
        "s3-data-v3-excl-v1",
    )
    s3.check_kb_split("s3-v3", "annot-split-v2")
    with pytest.raises(ValueError, match="half B"):
        s3.check_kb_split("s3-v3", "annot-split-v1")
    salt = "diagnostic.ar-training/s3-v3"
    parts = [s3._part(salt, f"c{i}", s3.DEV_TENTHS["s3-v3"]) for i in range(20000)]
    assert 0.28 < parts.count("dev") / len(parts) < 0.32


def test_the_even_split_of_s3_v2_is_unchanged():
    salt = "diagnostic.ar-training/s3-v2"
    assert [s3._part(salt, f"c{i}") for i in range(50)] == [s3._part(salt, f"c{i}", None) for i in range(50)]
    assert "s3-v2" not in s3.DEV_TENTHS


def _tiny_dataset(path, n):
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for i in range(n):
            row = {"case_id": f"c{i}", "gene": "G", "present": ["HP:1"], "true_present": ["HP:1"],
                   "sex": "male", "age_years": None, "onset_years": None}  # fmt: skip
            handle.write(json.dumps(row) + "\n")


def test_s3_v3_test_part_is_sealed_with_the_same_guards_as_s3_v2(tmp_path, monkeypatch):
    monkeypatch.setattr(s3, "SPLITS_DIR", tmp_path)
    data = tmp_path / "d.jsonl.gz"
    _tiny_dataset(data, 400)
    body = s3.freeze("s3-v3", data, "x")
    assert body["sealed_parts"] == ["test"]
    assert 0.2 < body["counts"]["dev"] / 400 < 0.4
    assert body["counts"]["dev"] + body["counts"]["test"] == 400
    assert "% 10" in body["rule"]

    recorded = []
    monkeypatch.setattr(ledger, "record_access", lambda *a, **k: recorded.append(a))
    monkeypatch.delenv("DXT_SEALED_READ", raising=False)
    with pytest.raises(LineageError, match="sealed"):
        s3.load_part("s3-v3", "test", data)
    with pytest.raises(LineageError, match="DXT_SEALED_READ"):
        s3.load_part("s3-v3", "test", data, exp_id="EXP-B-005", reason="r")
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-OTHER")
    with pytest.raises(LineageError, match="DXT_SEALED_READ"):
        s3.load_part("s3-v3", "test", data, exp_id="EXP-B-005", reason="r")
    assert recorded == []
    assert len(s3.load_part("s3-v3", "dev", data)) == body["counts"]["dev"]
    assert recorded == []
