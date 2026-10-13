"""v4 summaries: strata, Δ vs E0 with the cluster bootstrap, helped/harmed counts, ranks files."""

import math

import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.v4 import report
from diagnostic_ar_training.v4.patients import CITED, UNCITED, Patient


def patient(i: int, status: str) -> Patient:
    return Patient(Case(case_id=f"c{i}", cohort="t", gene="G", present=("HP:1",)), f"g{i // 2}", status, 3)


def records(ranks, statuses, in_vocab=None):
    in_vocab = in_vocab or [True] * len(ranks)
    return [
        report.record(patient(i, s), v, True, r)
        for i, (r, s, v) in enumerate(zip(ranks, statuses, in_vocab, strict=True))
    ]


STATUSES = [UNCITED, UNCITED, UNCITED, UNCITED, CITED, CITED]


def test_strata_and_metrics():
    recs = records([1, 2, 10, math.inf, 1, 20], STATUSES, [True, True, True, False, True, True])
    s = report.summarize(recs)["strata"]
    assert s["all"]["n"] == 6 and s["uncited"]["n"] == 4 and s["cited"]["n"] == 2
    assert s["uncited"]["mrr"] == pytest.approx((1 + 0.5 + 0.1 + 0) / 4)
    assert s["uncited"]["top1"] == 0.25 and s["uncited"]["top10"] == 0.75
    assert s["oov"]["n"] == 1 and s["uncited_in_vocab"]["n"] == 3
    assert s["uncited"]["n_groups"] == 2


def test_delta_vs_e0_helped_harmed_and_primary():
    e0 = records([2, 2, 10, math.inf, 1, 1], STATUSES)
    new = records([1, 4, 10, math.inf, 1, 3], STATUSES)
    out = report.summarize(new, e0)
    u = out["strata"]["uncited"]
    assert u["delta"]["mrr"] == pytest.approx((0.5 - 0.25) / 4)
    assert (u["helped"], u["harmed"], u["unchanged"]) == (1, 1, 2)
    lo, hi = u["delta_mrr_ci95"]
    assert lo <= u["delta"]["mrr"] <= hi
    assert out["primary"]["stratum"] == "uncited" and out["primary"]["delta"] == u["delta"]["mrr"]
    assert out["strata"]["cited"]["harmed"] == 1


def test_e0_must_cover_the_same_cases():
    with pytest.raises(KeyError):
        report.summarize(records([1, 2], STATUSES[:2]), records([1], STATUSES[:1]))


def test_ranks_round_trip(tmp_path):
    recs = records([1, math.inf], STATUSES[:2])
    back = report.read_ranks(report.write_ranks(tmp_path / "r" / "x.ranks.jsonl", recs))
    assert [r["rank"] for r in back] == [1, math.inf]
    assert back[0]["strata"] == recs[0]["strata"] and back[0]["group"] == "g0"
