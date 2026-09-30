"""Frozen-base run helpers: which views each design is scored on, and the rank files they write."""

import json

import pytest

pytest.importorskip("torch")

from diagnostic_ar_training.gnn import frozen  # noqa: E402
from diagnostic_ar_training.gnn import train as training  # noqa: E402


def cfg(design: str) -> training.TrainConfig:
    return training.TrainConfig(lr_base=0.0, lr_new=1e-3, frozen_base=True, **frozen.DESIGNS[design])


@pytest.mark.parametrize(
    ("design", "views", "primary"),
    [
        ("neg", ("present", "excluded"), "excluded"),
        ("neg2", ("present", "excluded"), "excluded"),
        ("cov", ("present", "sex", "age", "all"), "all"),
        ("neg2+cov", ("present", "excluded", "sex", "age", "all"), "all"),
    ],
)
def test_each_design_is_followed_on_the_views_its_inputs_can_change(design, views, primary):
    assert frozen.epoch_views(cfg(design)) == views
    assert frozen.primary_r1_view(cfg(design)) == primary


def test_rank_files_are_named_by_cohort_and_view(tmp_path):
    rec = [{"case_id": "a", "rank": 1.0, "group": "g"}]
    paths = frozen.write_ranks(tmp_path, {"r1_dev_present": rec, "s3_dev_all": rec, "s2": rec})
    assert sorted(p.name for p in paths) == ["r1-v1-dev.present.ranks.jsonl", "s2.ranks.jsonl",
                                              "s3-v1-dev.all.ranks.jsonl"]  # fmt: skip
    assert json.loads(paths[0].read_text()) == {"case_id": "a", "group": "g", "rank": 1.0}


def test_same_ranks_counts_changed_cases():
    a = [{"case_id": "x", "rank": 1.0}, {"case_id": "y", "rank": 3.0}]
    b = [{"case_id": "y", "rank": 2.0}, {"case_id": "x", "rank": 1.0}]
    assert frozen.same_ranks(a, b) == 1
