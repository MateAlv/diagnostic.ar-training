"""Track 4 new-row training (vocab/): the head, the fit, the standards test and the selection rule.

The numpy parts run without torch or data; the torch tests skip without torch.
"""

import math

import numpy as np
import pytest

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.ft.bundle import softmax64
from diagnostic_ar_training.ft.system import E0Logits
from diagnostic_ar_training.vocab import standards

GENES = ("G0", "G1", "G2", "G3", "G4", "G5")
HIDDEN = 4


def case(cid, gene, group="p1", present=("HP:1",)):
    return Case(case_id=cid, cohort="c", gene=gene, present=present)


class FakeBase:
    genes = GENES

    class inputs:  # noqa: N801
        emb_index = {"HP:1": 0}

        @staticmethod
        def known_present(case):
            known = [t for t in case.present if t.startswith("HP:")]
            return known, {"n_present": len(case.present)}

    def logits(self, known):
        return np.arange(len(GENES), dtype=np.float32)[::-1].copy(), tuple(known)

    def lineage_inputs(self):
        return []


# Gene choice


def test_choose_genes_takes_eligible_vocabulary_genes_and_samples_above_the_cap():
    cases = [case("a", "g1"), case("b", "G2"), case("c", "OUT"), case("d", "G3"), case("e", "G1")]
    chosen, counts = standards.choose_genes(cases, GENES, lambda g: g != "G3")
    assert chosen == ["G1", "G2"]
    assert counts["in_vocabulary"] == 3 and counts["excluded_no_profile"] == ["G3"] and counts["chosen"] == 2
    many = [case(str(i), g) for i, g in enumerate(GENES)]
    a, _ = standards.choose_genes(many, GENES, lambda g: True, max_genes=3, seed=1)
    b, _ = standards.choose_genes(many, GENES, lambda g: True, max_genes=3, seed=1)
    assert a == b and len(a) == 3 and a == [g for g in GENES if g in a]


# The relearned system


def test_relearned_replaces_only_its_genes_logits():
    e0 = E0Logits(FakeBase())
    pooled = {"a": np.array([1.0, 0.0, 2.0, 0.0])}
    weight = np.array([[100.0, 0, 0, 0], [0, 0, 1.0, 0]])
    system = standards.Relearned(e0, [4, 1], weight, np.array([0.5, -1.0]), pooled)
    c = case("a", "G4")
    base, _ = e0(c)
    got, _ = system.logits(c)
    keep = [i for i in range(len(GENES)) if i not in (4, 1)]
    assert np.array_equal(got[keep], np.asarray(base, dtype=np.float64)[keep])
    assert got[4] == 100.5 and got[1] == 1.0
    assert np.array_equal(system.score(c).probs, softmax64(got)) and system.score(c).probs.argmax() == 4
    assert system.score(case("b", "G4", present=("x",))).probs is None


# Statistics and rules


def rec(cid, gene, rank, group):
    return {"case_id": cid, "gene": gene, "rank": rank, "group": group}


def test_ratio_bootstrap_and_report():
    e0 = [rec("a", "G1", 1, "p1"), rec("b", "G1", 2, "p2"), rec("c", "G2", 4, "p3"), rec("d", "G3", 1, "p4")]
    new = [rec("a", "G1", 2, "p1"), rec("b", "G1", 2, "p2"), rec("c", "G2", 4, "p3"), rec("d", "G3", 1, "p4")]
    same = standards.ratio_bootstrap([1, 2, 4], [1, 2, 4], ["p1", "p2", "p3"])
    assert same["ratio"] == 1.0 and same["ci95"] == [1.0, 1.0]
    rep = standards.report(e0, new, ["G1"])
    assert rep["relearned"]["e0"]["n"] == 2 and math.isclose(rep["relearned"]["ratio"]["ratio"], 1.0 / 1.5)
    assert rep["relearned"]["vs_e0"]["harmed_n"] == 1 and rep["others"]["vs_e0"]["delta"] == 0.0
    assert rep["criterion"] == {**rep["criterion"], "a_met": False, "b_met": True, "pass": False}
    ok = standards.report(e0, e0, ["G1"])
    assert ok["criterion"]["pass"] and ok["relearned"]["ratio"]["ratio"] == 1.0
    assert standards.per_gene(e0, new, ["G1"]) == [{"gene": "G1", "n": 2, "e0_mrr": 0.75, "new_mrr": 0.5}]


def test_criterion_thresholds_are_the_registered_ones():
    def rep(ratio, delta):
        return {"relearned": {"ratio": {"ratio": ratio}}, "others": {"vs_e0": {"delta": delta}}}

    assert standards.criterion(rep(0.90, -0.001))["pass"]
    assert not standards.criterion(rep(0.8999, 0.0))["pass"]
    assert not standards.criterion(rep(1.2, -0.0011))["pass"]


def test_select_rule():
    assert len(standards.CONFIGS) <= 6

    def rows(name, ratio, delta):
        return [{"config": name, "seed": s, "ratio": ratio, "others_delta": delta} for s in standards.SEEDS]

    picked = standards.select(
        rows("c3-n512-r128", 0.95, -0.0005)
        + rows("c2-n512-r32", 0.945, -0.0002)
        + rows("c5-n2048-r128", 0.99, -0.002)
        + rows("c1-n128-r8", 0.80, 0.0)
    )
    assert picked["feasible"] == ["c1-n128-r8", "c2-n512-r32", "c3-n512-r128"]
    assert picked["within_tie"] == ["c2-n512-r32", "c3-n512-r128"] and picked["selected"] == "c2-n512-r32"
    none = standards.select(rows("c3-n512-r128", 0.95, -0.003) + rows("c1-n128-r8", 0.9, -0.002))
    assert none["selected"] == "c1-n128-r8" and none["feasible"] == []
    partial = standards.select([{"config": "c1-n128-r8", "seed": 0, "ratio": 1.0, "others_delta": 0.0}])
    assert partial["selected"] is None


# The torch head and the fit


def frozen(torch, n_genes=len(GENES), hidden=HIDDEN, seed=0):
    gen = torch.Generator().manual_seed(seed)
    return torch.randn(n_genes, hidden, generator=gen) * 5, torch.randn(n_genes, generator=gen)


def test_new_rows_start_from_a_seeded_random_draw_not_the_old_rows():
    torch = pytest.importorskip("torch")
    from diagnostic_ar_training.vocab.rows import RowHead

    w, b = frozen(torch)
    a, again, other = (RowHead(w, b, replace=[1, 3], seed=s) for s in (0, 0, 1))
    assert torch.equal(a.new_weight, again.new_weight) and not torch.equal(a.new_weight, other.new_weight)
    assert a.new_weight.abs().max() <= 1 / math.sqrt(HIDDEN) and a.new_bias.abs().max() <= 1 / math.sqrt(
        HIDDEN
    )
    assert not torch.allclose(a.new_weight, w[[1, 3]]) and a.slots() == [1, 3]
    with pytest.raises(ValueError):
        RowHead(w, b, replace=[1, 1])
    with pytest.raises(ValueError):
        RowHead(w, b)


def test_softmax_over_the_extended_vocabulary():
    torch = pytest.importorskip("torch")
    from diagnostic_ar_training.vocab.rows import RowHead

    w, b = frozen(torch)
    head = RowHead(w, b, replace=[2], add=2, seed=0)
    pooled = torch.randn(5, HIDDEN, generator=torch.Generator().manual_seed(3))
    logits = head(pooled)
    assert logits.shape == (5, len(GENES) + 2) and head.n_out == len(GENES) + 2
    assert head.slots() == [2, len(GENES), len(GENES) + 1]
    probs = torch.softmax(logits.double(), dim=1)
    assert torch.allclose(probs.sum(dim=1), torch.ones(5, dtype=torch.float64))
    full_w, full_b = head.matrix()
    assert torch.allclose(logits, pooled @ full_w.T + full_b, atol=1e-5)
    untouched = [0, 1, 3, 4, 5]
    assert torch.equal(logits[:, untouched], (pooled @ w.T + b)[:, untouched])
    target = torch.tensor([len(GENES), len(GENES) + 1, 2, 0, 1])
    torch.nn.functional.cross_entropy(logits, target).backward()
    assert head.new_weight.grad is not None and head.new_weight.grad.abs().sum() > 0
    assert [n for n, p in head.named_parameters()] == ["new_weight", "new_bias"]


def test_fit_learns_new_rows_and_leaves_old_rows_bit_for_bit():
    torch = pytest.importorskip("torch")
    from diagnostic_ar_training.vocab import rows

    gen = torch.Generator().manual_seed(0)
    centers = torch.randn(len(GENES) + 1, HIDDEN, generator=gen) * 3
    w, b = centers[: len(GENES)].clone(), torch.zeros(len(GENES))
    w_before, b_before = w.clone(), b.clone()

    head = rows.RowHead(w, b, replace=[1], add=1, seed=0)

    def around(targets, n):
        t = torch.tensor([x for x in targets for _ in range(n)])
        return rows.Pool(centers[t] + 0.3 * torch.randn(len(t), HIDDEN, generator=gen), t)

    new, val_new = around(head.slots(), 64), around(head.slots(), 16)
    others = [0, 2, 3, 4, 5]
    replay, val_replay = around(others, 32), around(others, 8)
    cfg = rows.RowConfig(lr=0.05, batch_new=32, batch_replay=64, max_epochs=60, patience=10)
    w_new = rows.prior_weight(2, len(others))
    result = rows.fit(cfg, head, new, replay, val_new, val_replay, w_new, log=lambda *_: None)
    assert torch.equal(head.weight, w_before) and torch.equal(head.bias, b_before)
    assert torch.equal(w, w_before) and torch.equal(b, b_before)
    best = result.history[result.best_epoch]["val"]["loss"]
    assert result.best_epoch > 0 and best < result.history[0]["val"]["loss"]
    with torch.no_grad():
        pred = head(val_new.pooled).argmax(dim=1)
    assert (pred == val_new.target).float().mean() > 0.9
    weight, bias = rows.mean_rows([head, head])
    assert np.allclose(weight, head.new_weight.detach().double().numpy())


def test_pseudo_pools_target_slots_and_drop_relearned_genes_from_replay():
    pytest.importorskip("torch")
    from diagnostic_ar_training.vocab import rows

    kb = {"genes": {g: {"profile": ["HP:1", "HP:2", "HP:3"]} for g in GENES}}
    known = {"HP:1", "HP:2", "HP:3"}
    new, replay, stats = rows.pseudo_pools(kb, GENES, known, set(), ["G2", "G4"], [2, 4], 5, 3)
    assert {t for t, _ in new} == {2, 4} and len(new) == 10
    assert {t for t, _ in replay} == {0, 1, 3, 5} and stats["replay_genes"] == 4 and stats["new_genes"] == 2
    vn, vr, _ = rows.pseudo_pools(kb, GENES, known, set(), ["G2", "G4"], [2, 4], 5, 3, val=True)
    assert len(vn) == 10 and {t for t, _ in vr} == {0, 1, 3, 5}
    added, _, _ = rows.pseudo_pools(kb, GENES, known, set(), ["G2"], [len(GENES)], 2, 1)
    assert {t for t, _ in added} == {len(GENES)}
    with pytest.raises(ValueError):
        rows.pseudo_pools(kb, GENES, known, set(), ["G2"], [2, 3], 1, 1)
