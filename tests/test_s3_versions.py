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
        s3.spec("s3-v3")


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
