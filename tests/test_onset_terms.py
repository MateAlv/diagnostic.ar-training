import numpy as np
import pytest

from diagnostic_ar_training.rerank.onset_terms import mutual_information_bits


def test_same_onset_everywhere_carries_no_information():
    onset = np.tile([0.0, 1.0, 0.0], (4, 1))
    assert mutual_information_bits(np.array([1.0, 2.0, 1.0, 5.0]), onset) == pytest.approx(0.0)


def test_distinct_onsets_give_log2_of_genes():
    onset = np.eye(4)
    assert mutual_information_bits(np.ones(4), onset) == pytest.approx(2.0)


def test_weights_matter():
    onset = np.eye(2)
    skewed = mutual_information_bits(np.array([9.0, 1.0]), onset)
    assert 0 < skewed < 1.0
