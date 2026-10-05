import pytest
from test_release_check import GROUPS, FakeBase, K, make_cases
from typer.testing import CliRunner

from diagnostic_ar_training import splits
from diagnostic_ar_training.cli import app
from diagnostic_ar_training.cohorts import access
from diagnostic_ar_training.eval import final_report
from diagnostic_ar_training.lineage import gitinfo, ledger, manifest
from diagnostic_ar_training.lineage.registry import LineageError
from diagnostic_ar_training.rerank.config import RerankConfig, rr_v1_reference

ARGS = ["rerank", "final-report", "--exp", "EXP-V-001", "--cohort", "r1-v1/vault", "--reason", "final"]
ROW = "| 2026-10-06T00:00:00+00:00 | r1-v1/vault | EXP-V-001 | abcdef123456 | final |\n"
CLEAN = gitinfo.CodeState(repo="r", sha="a" * 40, dirty=False)


class Touched(Exception):
    pass


@pytest.fixture
def tripwires(monkeypatch):
    """Anything that loads data, fetches an artifact or touches the ledger fails the test."""

    def boom(*a, **k):
        raise Touched

    monkeypatch.setattr(splits, "load_part", boom)
    monkeypatch.setattr(access, "load", boom)
    monkeypatch.setattr(splits, "publication_groups", boom)
    monkeypatch.setattr(manifest, "load_manifest", boom)
    monkeypatch.setattr(manifest, "fetch_outputs", boom)
    monkeypatch.setattr(ledger, "record_access", boom)


@pytest.fixture
def good(monkeypatch, tmp_path):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-V-001")
    monkeypatch.setattr(ledger, "LEDGER", tmp_path / "TEST_LEDGER.md")
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: True)
    monkeypatch.setattr(final_report, "code_state", lambda: CLEAN)


def run(args=ARGS):
    return CliRunner().invoke(app, args, env={"COLUMNS": "400"})


def refused(result):
    return result.exit_code != 0 and not isinstance(result.exception, Touched)


def test_tripwires_are_live_once_every_check_passes(tripwires, good):
    result = run()
    assert isinstance(result.exception, Touched)


def test_refusal_without_the_env_var_comes_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.delenv("DXT_SEALED_READ")
    result = run()
    assert refused(result)
    assert "DXT_SEALED_READ=EXP-V-001" in result.output


def test_refusal_with_another_env_value_comes_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.setenv("DXT_SEALED_READ", "EXP-B-006")
    assert refused(run())


def test_refusal_without_a_reason_comes_before_any_load(tripwires, good):
    result = run(ARGS[:-2])
    assert refused(result)
    assert "reason is required" in result.output


def test_refusal_when_not_preregistered_comes_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.setattr(ledger, "is_preregistered", lambda path: False)
    result = run()
    assert refused(result)
    assert "committed" in result.output


def test_refusal_on_a_dirty_tree_comes_before_any_load(tripwires, good, monkeypatch):
    monkeypatch.setattr(
        final_report, "code_state", lambda: gitinfo.CodeState(repo="r", sha="a" * 40, dirty=True)
    )
    result = run()
    assert refused(result)
    assert "uncommitted" in result.output


def test_second_vault_read_is_refused_before_any_load(tripwires, good):
    ledger.LEDGER.write_text(ROW)
    result = run()
    assert refused(result)
    assert "already opened" in result.output
    assert ledger.LEDGER.read_text() == ROW


def test_wrong_experiment_and_cohort_are_refused_before_any_load(tripwires, good):
    for args in (
        ["rerank", "final-report", "--exp", "EXP-B-006", "--cohort", "r1-v1/dev"],
        ["rerank", "final-report", "--exp", "EXP-V-001", "--cohort", "r1-v1/test", "--reason", "r"],
        ["rerank", "final-report", "--exp", "EXP-V-001", "--cohort", "mcrd", "--reason", "r"],
    ):
        assert refused(run(args))


def test_dry_run_on_dev_needs_no_reason():
    final_report.check_request("EXP-V-001", "r1-v1/dev", "")


def test_vault_opens_once_through_load_part_with_exactly_one_ledger_row(good, monkeypatch):
    monkeypatch.setattr(ledger, "code_state", lambda: CLEAN)
    monkeypatch.setattr(splits, "_all_cases", lambda spec: ([], None))
    registered = ledger.EXPERIMENTS_DIR / "EXP-V-001.md"
    assert registered.exists()
    final_report.preflight("EXP-V-001", "r1-v1/vault", "final")
    assert splits.load_part("r1-v1", "vault", splits.Purpose.EVAL, "EXP-V-001", "final") == []
    rows = [line for line in ledger.LEDGER.read_text().splitlines() if "r1-v1/vault" in line]
    assert len(rows) == 1
    with pytest.raises(LineageError, match="already opened"):
        final_report.preflight("EXP-V-001", "r1-v1/vault", "final")
    with pytest.raises(LineageError, match="already opened"):
        splits.load_part("r1-v1", "vault", splits.Purpose.EVAL, "EXP-V-001", "final")
    assert len([line for line in ledger.LEDGER.read_text().splitlines() if "r1-v1/vault" in line]) == 1


def test_experiment_id_v_is_accepted_by_the_ledger():
    assert ledger.EXP_ID.match("EXP-V-001")
    assert not ledger.EXP_ID.match("EXP-X-001")


def test_config_hashes_are_the_released_ones():
    reference = rr_v1_reference("kb-v3")
    assert reference.config_hash == final_report.CONFIG_HASHES["rerank-v1.0.0"]
    candidate = RerankConfig.from_dict(
        {**reference.to_dict(), "weights": {**reference.weights, "onset": 0.25}}
    )
    assert candidate.config_hash == final_report.CONFIG_HASHES["rerank-v1.1.0"]


def test_systems_are_the_ones_release_check_scored():
    assert final_report.SYSTEMS["rerank-v1.0.0"].as_dict() == {
        "neg": 0.5,
        "sex": 0.0,
        "age": 0.0,
        "onset": 0.0,
    }
    assert final_report.SYSTEMS["rerank-v1.1.0"].as_dict() == {
        "neg": 0.5,
        "sex": 0.0,
        "age": 0.0,
        "onset": 0.25,
    }


def test_report_layout_identities_and_onset_subset():
    cases = make_cases()
    report, records = final_report.evaluate(FakeBase(), K, cases, GROUPS)
    assert report["descriptive_only"] and "not a gate" in report["note"]
    assert set(report["views"]) == {"given", "present"}
    assert set(records["given"]) == set(final_report.SYSTEMS)
    block = report["views"]["given"]
    assert set(block["contrasts"]) == set(final_report.CONTRASTS)
    assert set(block["contrasts"]["v1.1_vs_E0"]) == set(final_report.METRICS)
    assert block["systems"]["E0"]["n"] == len(cases)
    assert {"top1", "top10", "top100", "mrr_ci95"} <= set(block["systems"]["E0"])
    assert report["sanity"] == {
        "present_view_v1.1_vs_E0_mismatches": 0,
        "present_view_v1.0_vs_E0_mismatches": 0,
    }
    present = report["views"]["present"]["contrasts"]["v1.1_vs_E0"]["mrr"]
    assert present["delta"] == 0 and present["harmed"] == 0
    sub = report["onset_subset"]
    assert sub["with_usable_onset"]["n"] + sub["without_usable_onset"]["n"] == len(cases)
    assert sub["without_usable_onset"]["contrasts"]["v1.1_minus_v1.0"]["mrr"]["delta"] == 0
    assert report["publications"] == len({GROUPS[c.case_id] for c in cases})
