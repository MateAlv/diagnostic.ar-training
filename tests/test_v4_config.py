"""v4 run configurations: YAML loading, hashing into run ids, overrides, and the committed ladder configs."""

import pytest
import yaml

from diagnostic_ar_training import REPO_ROOT
from diagnostic_ar_training.v4 import config, grid
from diagnostic_ar_training.v4.config import ArchConfig, RunConfig

LADDER = sorted((REPO_ROOT / "configs" / "p3").glob("R*.yaml"))


def test_hash_ignores_the_label_and_covers_every_other_field():
    a = RunConfig(label="a")
    assert a.config_hash == RunConfig(label="b").config_hash
    assert a.run_id == f"a-{a.config_hash[:10]}"
    changed = [
        config.override(a, {"seed": 1}),
        config.override(a, {"sim.preset": "freq"}),
        config.override(a, {"sim.real_ratio": 0.1}),
        config.override(a, {"encoding.edges": "both"}),
        config.override(a, {"arch.pooling": "attention_mean"}),
        config.override(a, {"train.num_workers": 4}),
    ]
    assert len({c.config_hash for c in changed} | {a.config_hash}) == len(changed) + 1


def test_hash_is_stable_through_yaml(tmp_path):
    cfg = config.override(RunConfig(label="x"), {"encoding.observed_flag": True, "train.lr": 1e-4})
    path = tmp_path / "c.yaml"
    path.write_text(config.dump(cfg))
    assert config.load(path) == cfg and config.load(path).run_id == cfg.run_id


def test_simulator_parameters_enter_the_hash_by_content(tmp_path):
    params = tmp_path / "params.json"
    params.write_text('{"a": 1}')
    cfg = config.override(RunConfig(), {"sim.params": str(params)})
    first = cfg.run_id
    assert first != RunConfig().run_id
    params.write_text('{"a": 2}')
    assert cfg.run_id != first
    with pytest.raises(FileNotFoundError):
        _ = config.override(RunConfig(), {"sim.params": str(tmp_path / "missing.json")}).run_id


def test_unknown_keys_and_values_are_errors():
    with pytest.raises(ValueError, match="unknown keys"):
        config.from_dict({"train": {"learning_rate": 1}})
    with pytest.raises(ValueError, match="unknown keys"):
        config.from_dict({"model": {}})
    with pytest.raises(ValueError, match="unknown override"):
        config.override(RunConfig(), {"arch.width": 3})
    with pytest.raises(ValueError):
        config.from_dict({"encoding": {"edges": "down"}})
    with pytest.raises(ValueError):
        config.from_dict({"sim": {"real_ratio": 1.0}})


def test_a_warm_start_needs_e0s_shape():
    ArchConfig(init="e0")
    with pytest.raises(ValueError, match="E0's shape"):
        ArchConfig(init="e0", hidden=768)
    with pytest.raises(ValueError, match="E0's shape"):
        ArchConfig(init="e0", layers=4)


@pytest.mark.parametrize(
    "path", [p for p in LADDER if not p.name.endswith("-grid.yaml")], ids=lambda p: p.name
)
def test_ladder_configs_load(path):
    cfg = config.load(path)
    assert cfg.label == path.stem


def test_ladder_rungs_change_one_thing_at_a_time():
    r = {p.stem: config.load(p) for p in LADDER if not p.name.endswith("-grid.yaml")}
    assert r["R0"].arch.init == "e0" and r["R0"].train.max_samples == 0
    assert r["R1"].sim.preset == "e0" and r["R1"].arch.init == "scratch"
    assert [r[k].sim.preset for k in ("R2", "R3", "R4")] == ["freq", "real", "real_noise"]
    assert r["R5"].sim.real_ratio > 0 and r["R4"].sim.real_ratio == 0
    assert r["R6"].encoding == config.EncodingConfig(True, True, "both", True, False)
    assert r["R7"].encoding.covariates and r["R7"].sim == r["R6"].sim
    assert r["R6-on-R2"].sim == r["R2"].sim and r["R6-on-R2"].encoding == r["R6"].encoding
    assert len({c.train for k, c in r.items() if k != "R0"}) == 1


@pytest.mark.parametrize("path", [p for p in LADDER if p.name.endswith("-grid.yaml")], ids=lambda p: p.name)
def test_grid_specs_expand(path):
    spec = grid.load_spec(path)
    points = grid.expand(spec)
    assert points and all(p.cfg.label == spec["grid_id"] for p in points)
    assert yaml.safe_load(path.read_text())["total_minutes"] > 0
