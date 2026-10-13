"""v4 grids: expansion, every configuration and seed logged, resume, budget, failures."""

import pytest

from diagnostic_ar_training.v4 import grid, runs

SPEC = {
    "grid_id": "G",
    "config": {"train": {"max_minutes": 10}},
    "total_minutes": 100,
    "seeds": [0, 1],
    "axes": {"arch.hidden": [64, 128], "train.lr": [1e-4]},
    "points": [{"arch.dropout": 0.1}],
}


@pytest.fixture(autouse=True)
def results(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "P3_RESULTS", tmp_path / "P3")
    return tmp_path / "P3"


def fake_run(calls, fail=()):
    def run(cfg):
        calls.append(cfg.run_id)
        if cfg.arch.hidden in fail:
            raise RuntimeError("boom")
        row = {"status": runs.COMPLETE, "select": {"primary": {"delta": 0.01}}, "training": {"minutes": 1}}
        runs.write_json(runs.row_path(cfg.run_id), row)
        return row

    return run


def test_expand_is_the_product_plus_points_times_seeds():
    points = grid.expand(SPEC)
    assert len(points) == (2 + 1) * 2
    assert [(p.overrides.get("arch.hidden"), p.seed) for p in points[:4]] == [
        (64, 0),
        (64, 1),
        (128, 0),
        (128, 1),
    ]
    assert all(p.cfg.label == "G" for p in points)
    with pytest.raises(ValueError, match="same configuration"):
        grid.expand({**SPEC, "points": [{"arch.hidden": 64, "train.lr": 1e-4}]})


def test_every_configuration_and_seed_is_logged_and_the_grid_resumes():
    calls: list[str] = []
    table = grid.run_grid(SPEC, fake_run(calls), log=lambda s: None)
    assert len(calls) == 6 and all(r["status"] == "complete" for r in table)
    log = grid.read_log()
    assert [e["event"] for e in log].count("started") == 6
    assert [e["event"] for e in log].count("completed") == 6
    assert all("config" in e for e in log if e["event"] == "started")
    assert log[0]["event"] == "grid_started" and log[-1]["event"] == "grid_finished"

    calls.clear()
    grid.run_grid(SPEC, fake_run(calls), log=lambda s: None)
    assert calls == []
    assert [e["event"] for e in grid.read_log()].count("skipped_complete") == 6
    assert (runs.P3_RESULTS / "grids" / "G.json").is_file()


def test_budget_failures_and_interruptions_are_logged():
    now = [0.0]

    def run(cfg):
        now[0] += 60 * 30
        return fake_run([], fail=(128,))(cfg)

    table = grid.run_grid(SPEC, run, total_minutes=95, clock=lambda: now[0], log=lambda s: None)
    status = [r["status"] for r in table]
    assert status[:3] == ["complete", "complete", "failed"]
    assert "skipped_budget" in status
    events = [e["event"] for e in grid.read_log()]
    assert events.count("failed") == 1 and events.count("skipped_budget") == status.count("skipped_budget")

    def interrupted(cfg):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        grid.run_grid(SPEC, interrupted, log=lambda s: None)
    assert [e["event"] for e in grid.read_log()][-2:] == ["interrupted", "grid_interrupted"]
