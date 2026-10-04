import math

import pytest
from typer.testing import CliRunner

from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import onset_run


def test_sealed_part_is_opened_only_by_its_own_experiment_with_a_reason_and_all_cases():
    onset_run.check_sealed_request("s3-v3b", "test", "EXP-B-005", "pre-registered abc")
    onset_run.check_sealed_request("s3-v3b", "dev", "EXP-B-005", "")
    onset_run.check_sealed_request("s3-v3b", "dev", "EXP-B-004", "")
    for exp, reason, cases in (
        ("EXP-B-004", "r", 0),
        ("EXP-B-005", "", 0),
        ("EXP-B-005", "  ", 0),
        ("EXP-B-005", "r", 10),
    ):
        with pytest.raises(ValueError, match="one pre-registered read"):
            onset_run.check_sealed_request("s3-v3b", "test", exp, reason, cases)
    for split in ("s3-v2", "s3-v3"):
        with pytest.raises(ValueError, match="one pre-registered read"):
            onset_run.check_sealed_request(split, "test", "EXP-B-005", "r")


def test_onset_session_cli_refuses_a_sealed_read_by_another_experiment(tmp_path):
    arms = tmp_path / "arms.json"
    arms.write_text("[]")
    result = CliRunner().invoke(
        app,
        ["s3", "onset-session", "--exp", "EXP-B-004", "--part", "test", "--arms", str(arms), "--reason", "r"],
        env={"COLUMNS": "400"},
    )
    assert result.exit_code != 0
    assert "one pre-registered read" in result.output


def test_rows_roundtrip_infinite_ranks(tmp_path):
    case = Case(case_id="s3-v3b:c1", cohort="s3-question", gene="", present=("HP:0000001",))
    row = {
        "case_id": "s3-v3b:c1",
        "gene": "G",
        "questions": [],
        "answers": {},
        "after": case.model_dump(mode="json"),
        "rank_initial": "inf",
        "rank_driver_final": 3.0,
    }
    path = tmp_path / "rows.jsonl.gz"
    onset_run.write_rows(path, [row])
    (back,) = onset_run.read_rows(path)
    assert math.isinf(back["rank_initial"]) and back["rank_driver_final"] == 3.0
    assert back["case"].case_id == "s3-v3b:c1"
