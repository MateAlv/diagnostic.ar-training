"""E0 must be production: same top-10 and scores as captured from the production server."""

import json
from pathlib import Path

import numpy as np
import pytest

from diagnostic_ar_training.lineage import registry

pytest.importorskip("onnxruntime")
if not registry.verify(registry.load_sources()["genphenia_v3"]):
    pytest.skip("genphenia_v3 bundle not fetched (dxt sources fetch genphenia_v3)", allow_module_level=True)

from diagnostic_ar_training.cohorts.schema import Case  # noqa: E402
from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3  # noqa: E402

REFERENCE = json.loads(
    (Path(__file__).parent / "fixtures" / "production_reference_rankings.json").read_text()
)


@pytest.fixture(scope="module")
def model():
    return GenPheniaV3()


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_matches_production_rankings(model, name):
    expected = REFERENCE[name]
    probs, _, _ = model.probabilities(expected["hpo_ids"])
    top = np.argsort(probs)[::-1][:10]
    assert [model.genes[i].upper() for i in top] == [g for g, _ in expected["top_genes"]]
    for i, (_, score) in zip(top, expected["top_genes"], strict=True):
        assert probs[i] == pytest.approx(score, abs=2e-6)


def test_term_order_does_not_change_the_answer(model):
    ids = REFERENCE["neurofibromatosis_like"]["hpo_ids"]
    a, _, _ = model.probabilities(ids)
    b, _, _ = model.probabilities(list(reversed(ids)))
    assert np.allclose(a, b, atol=1e-7)


def test_unknown_terms_are_left_out_and_a_case_with_none_is_unscorable(model):
    ids = tuple(REFERENCE["neurofibromatosis_like"]["hpo_ids"])
    with_unknown = model.score(Case(case_id="a", cohort="t", gene="NF1", present=ids + ("HP:9999999",)))
    plain = model.score(Case(case_id="b", cohort="t", gene="NF1", present=ids))
    assert with_unknown.info["n_unknown"] == 1
    assert np.array_equal(with_unknown.probs, plain.probs)
    assert model.score(Case(case_id="c", cohort="t", gene="NF1", present=("HP:9999999",))).probs is None
