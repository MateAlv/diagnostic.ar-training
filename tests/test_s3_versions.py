from types import SimpleNamespace

import pytest
import typer
from typer.testing import CliRunner

from diagnostic_ar_training import cli
from diagnostic_ar_training.cohorts import s3


def test_s3_versions_name_their_dataset_annotation_split_and_exclusions():
    v1, v2 = s3.spec("s3-v1"), s3.spec("s3-v2")
    assert (v1.dataset_artifact, v1.annotation_split, v1.exclusion_artifact) == (
        "s3-data-v1",
        "annot-split-v1",
        None,
    )
    assert (v2.dataset_artifact, v2.annotation_split, v2.exclusion_artifact) == (
        "s3-data-v2",
        "annot-split-v2",
        "s3-data-v2-excl-v1",
    )
    with pytest.raises(ValueError):
        s3.spec("s3-v9")


@pytest.mark.parametrize(
    ("split", "dropped", "ok"),
    [
        ("s3-v1", "annot-split-v1", True),
        ("s3-v1", "annot-split-v2", False),
        ("s3-v2", "annot-split-v2", True),
        ("s3-v2", "annot-split-v1", False),
        ("s3-v2", None, False),
    ],
)
def test_a_kb_serves_an_s3_version_only_if_it_dropped_that_versions_half_b(split, dropped, ok):
    if ok:
        s3.check_kb_split(split, dropped)
    else:
        with pytest.raises(ValueError, match="half B"):
            s3.check_kb_split(split, dropped)


def test_s3_commands_refuse_an_unknown_split_and_a_kb_for_the_other_split():
    for command, extra in (("run", ["--exp", "EXP-S3-001"]), ("interviews", [])):
        result = CliRunner().invoke(cli.app, ["s3", command, "--split", "s3-v9", *extra])
        assert result.exit_code != 0
    manifest = SimpleNamespace(artifact_id="kb-x", params={"heldout_annotations_dropped": "annot-split-v1"})
    with pytest.raises(typer.BadParameter, match="annot-split-v2"):
        cli._check_s3_kb("s3-v2", manifest)
    cli._check_s3_kb("s3-v1", manifest)
    with pytest.raises(typer.BadParameter):
        cli._s3_dataset("s3-v9")


def _sealed_interview_args(*extra):
    return [
        "s3", "interview", "--exp", "EXP-B-004", "--part", "test", "--strategy", "Q0", "--cases", "0",
        "--reason", "test", *extra,
    ]  # fmt: skip


@pytest.fixture
def sealed_guard(monkeypatch):
    from diagnostic_ar_training.lineage import gitinfo, ledger

    touched = []
    monkeypatch.setattr(gitinfo, "code_state", lambda: SimpleNamespace(dirty=False, sha="x"))
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    monkeypatch.setattr(s3, "load_part", lambda *a, **k: touched.append("load_part"))
    monkeypatch.setattr(ledger, "record_access", lambda *a, **k: touched.append("record_access"))
    return touched


def test_a_refused_sealed_interview_never_loads_or_ledgers_the_part(sealed_guard, tmp_path):
    bad_kb = CliRunner().invoke(cli.app, _sealed_interview_args("--kb", "kb-v5"))
    assert bad_kb.exit_code != 0
    assert "annot-split-v2" in bad_kb.output
    config = tmp_path / "rr.json"
    config.write_text('{"kb_id": "kb-v5", "weights": {"neg_llr": 0.5}}')
    bad_rr = CliRunner().invoke(cli.app, _sealed_interview_args("--reranker", str(config)))
    assert bad_rr.exit_code != 0
    assert "annot-split-v2" in bad_rr.output
    bad_strategy = CliRunner().invoke(cli.app, ["s3", "interview", "--exp", "EXP-B-004", "--part", "test",
        "--strategy", "Q9", "--cases", "0", "--reason", "test"])  # fmt: skip
    assert bad_strategy.exit_code != 0
    assert sealed_guard == []
