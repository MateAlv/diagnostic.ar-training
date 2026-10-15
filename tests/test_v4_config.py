"""v4 run configurations: YAML loading, hashing into run ids, overrides, and the committed ladder configs."""

import pytest
import yaml

from diagnostic_ar_training import REPO_ROOT
from diagnostic_ar_training.v4 import config, grid
from diagnostic_ar_training.v4.config import ArchConfig, RunConfig

LADDER = sorted((REPO_ROOT / "configs" / "p3").glob("R*.yaml"))
BATCH2 = REPO_ROOT / "configs" / "p3" / "b2"


def test_hash_ignores_the_label_and_covers_every_other_field():
    a = RunConfig(label="a")
    assert a.config_hash == RunConfig(label="b").config_hash
    assert a.run_id == f"a-{a.config_hash[:10]}"
    changed = [
        config.override(a, {"seed": 1}),
        config.override(a, {"sim.preset": "freq"}),
        config.override(a, {"sim.real_ratio": 0.1}),
        config.override(a, {"sim.real_draw": "gene"}),
        config.override(a, {"sim.real_folds": [0, 1, 3]}),
        config.override(a, {"arch.init": "run:R1c-39306a6b7c"}),
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


def test_existing_run_ids_keep_their_hash():
    assert config.load(BATCH2 / "R1c.yaml").run_id == "R1c-39306a6b7c"
    assert config.load(REPO_ROOT / "configs" / "p3" / "R5.yaml").run_id == "R5-521ab9969c"
    assert "real_draw" not in RunConfig().hashed_body()["sim"]
    assert config.override(RunConfig(), {"sim.real_draw": "gene"}).hashed_body()["sim"]["real_draw"] == "gene"


def test_real_folds_is_hash_neutral_at_its_default():
    r5 = config.load(BATCH2 / "R5-r30.yaml")
    assert r5.sim.real_folds == (0, 1, 2) and r5.run_id == "R5-r30-fa772ffa7e"
    assert "real_folds" not in RunConfig().hashed_body()["sim"]
    assert config.override(r5, {"sim.real_folds": [2, 1, 0]}).run_id == r5.run_id
    other = config.override(r5, {"sim.real_folds": [1, 2, 3]})
    assert other.config_hash != r5.config_hash and other.hashed_body()["sim"]["real_folds"] == (1, 2, 3)


def test_real_folds_are_training_folds_only(tmp_path):
    assert config.from_dict({"sim": {"real_folds": [3, 0, 1]}}).sim.real_folds == (0, 1, 3)
    for bad, match in (
        ([0, 4], "CONFIRM"),
        ([4], "CONFIRM"),
        ([], "non-empty"),
        ([1, 1, 2], "repeats"),
        ([0, 5], "among"),
        ([-1], "among"),
        (3, "list"),
        (["1"], "list"),
    ):
        with pytest.raises(ValueError, match=match):
            config.from_dict({"sim": {"real_folds": bad}})
    cfg = config.override(RunConfig(label="x"), {"sim.real_folds": [1, 2, 3]})
    path = tmp_path / "c.yaml"
    path.write_text(config.dump(cfg))
    assert config.load(path) == cfg and config.load(path).run_id == cfg.run_id


def test_warm_start_from_a_run():
    assert ArchConfig(init="run:R1c-39306a6b7c").init_run == ("R1c-39306a6b7c", "last")
    assert ArchConfig(init="run:R1c-39306a6b7c@best").init_run == ("R1c-39306a6b7c", "best")
    assert ArchConfig(init="run:a.b_c-1@last", hidden=8).init_run == ("a.b_c-1", "last")
    assert ArchConfig().init_run is None and ArchConfig(init="e0").init_run is None
    for bad in ("run:", "run:R1c@first", "run:-x", "R1c-39306a6b7c"):
        with pytest.raises(ValueError, match="init"):
            ArchConfig(init=bad)
    with pytest.raises(ValueError, match="real_draw"):
        config.from_dict({"sim": {"real_draw": "publication"}})


def test_batch2_r5_configs():
    r = {p.stem: config.load(p) for p in sorted(BATCH2.glob("R5*.yaml"))}
    r1c = config.load(BATCH2 / "R1c.yaml")
    assert sorted(r) == ["R5-r10", "R5-r30", "R5-r30s1", "R5-r90", "R5s-r30", "R5x-f0", "R5x-f1", "R5x-f2", "R5x-f4"]
    seed0 = config.override(r["R5-r30s1"], {"seed": 0})
    assert r["R5-r30s1"].seed == 1 and seed0.config_hash == r["R5-r30"].config_hash
    assert all(c.label == k and c.sim.real_draw == "gene" for k, c in r.items())
    assert [r[k].sim.real_ratio for k in ("R5-r10", "R5-r30", "R5-r90", "R5s-r30")] == [0.1, 0.3, 0.9, 0.3]
    assert r["R5-r10"].arch.init_run == r["R5-r30"].arch.init_run == (r1c.run_id, "last")
    assert r["R5-r90"].train == r["R5-r30"].train and r["R5-r90"].arch == r["R5-r30"].arch
    assert r["R5s-r30"].arch.init == "scratch" and r["R5s-r30"].train == r1c.train
    assert r["R5-r30"].train == config.override(r1c, {"train.lr": 1e-4, "train.max_minutes": 60}).train
    assert r["R5-r10"].sim.preset == r1c.sim.preset and r["R5-r10"].encoding == r1c.encoding


def test_batch2_r5_cross_fitted_configs_differ_from_r5_r30_only_in_real_folds():
    r5 = config.load(BATCH2 / "R5-r30.yaml")
    held_out = {}
    for k in (0, 1, 2, 4):
        cfg = config.load(BATCH2 / f"R5x-f{k}.yaml")
        assert cfg.label == f"R5x-f{k}" and k not in cfg.sim.real_folds
        held_out[k] = set(cfg.sim.real_folds)
        assert config.override(cfg, {"label": r5.label, "sim.real_folds": [0, 1, 2]}) == r5
    assert held_out == {k: {0, 1, 2, 3} - {k} for k in (0, 1, 2, 4)}


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
