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
