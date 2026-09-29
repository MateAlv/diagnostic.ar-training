import math

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import contamination, metrics


def test_ties_count_against_the_true_gene():
    genes = ["A", "B", "C"]
    assert metrics.rank_of("B", genes, np.array([0.5, 0.5, 0.1])) == 2
    assert metrics.rank_of("A", genes, np.array([0.9, 0.5, 0.1])) == 1
    assert metrics.rank_of("Z", genes, np.array([0.9, 0.5, 0.1])) == math.inf


def test_summary_counts_unrankable_as_misses():
    s = metrics.summarize([1, 2, math.inf, 10], ks=(1, 10))
    assert s["n"] == 4 and s["unrankable"] == 1
    assert s["top1"] == 0.25 and s["top10"] == 0.75
    assert s["mrr"] == pytest.approx((1 + 0.5 + 0 + 0.1) / 4)


def test_paired_bootstrap_of_identical_systems_is_zero():
    ranks = [1, 3, 7, 2, 40]
    out = metrics.paired_bootstrap(ranks, ranks)
    assert out["delta"] == 0 and out["ci95"] == [0.0, 0.0]


def test_paired_bootstrap_detects_a_consistent_gain():
    base = np.arange(1, 201)
    out = metrics.paired_bootstrap(base, np.maximum(base - 1, 1), metric="mrr")
    assert out["delta"] > 0 and out["ci95"][0] > 0


def test_harmed_and_helped():
    assert metrics.harmed_helped([1, 2, 3, 4], [2, 2, 1, 4]) == {"harmed": 0.25, "helped": 0.25}


def test_contamination_checks():
    a = Case(case_id="a", cohort="t", gene="G", present=("HP:1", "HP:2"), pmids=("PMID:1",))
    b = Case(case_id="b", cohort="t", gene="G", present=("HP:2", "HP:1"), excluded=("HP:3",))
    assert contamination.signature_overlap([a], [b]) == []
    assert contamination.present_set_overlap([a], [b]) == ["b"]
    assert contamination.pmid_overlap({"PMID:1"}, [a, b]) == ["a"]


def test_cluster_bootstrap_is_wider_when_clusters_are_correlated():
    rng = np.random.default_rng(1)
    # 20 publications of 50 patients; the effect differs by publication.
    groups = np.repeat(np.arange(20), 50).astype(str)
    effect = np.repeat(rng.integers(0, 2, 20), 50)
    base = np.full(1000, 2.0)
    new = np.where(effect == 1, 1.0, 3.0)
    case = metrics.paired_bootstrap(base, new)
    clustered = metrics.paired_bootstrap(base, new, groups=groups)
    assert clustered["delta"] == case["delta"]
    assert clustered["resample_unit"] == "group" and clustered["n_units"] == 20
    width = lambda o: o["ci95"][1] - o["ci95"][0]  # noqa: E731
    assert width(clustered) > 3 * width(case)


def test_bootstrap_ci_brackets_the_point_estimate():
    ranks = [1, 2, 3, 4, 10, 20, 1, 1]
    lo, hi = metrics.bootstrap_ci(ranks)
    assert lo <= metrics.summarize(ranks)["mrr"] <= hi
