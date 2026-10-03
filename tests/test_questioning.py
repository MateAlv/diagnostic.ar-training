import inspect

import numpy as np
import pytest
from test_rerank import ONTO, K

from diagnostic_ar_training.eval import interactive, question_run, questioning
from diagnostic_ar_training.eval.interactive import PublicCase
from diagnostic_ar_training.rerank.features import COMPONENTS
from diagnostic_ar_training.systems import Scored

GENES = ("XLR", "ADULT", "NOONSET")


class FakeE0:
    name = "fake"
    genes = GENES

    def score(self, case):
        p = np.array([0.5, 0.3, 0.2])
        if "HP:0002373" in case.present:
            p = np.array([0.8, 0.1, 0.1])
        return Scored(p)


def ctx(beta=None):
    return questioning.Context(FakeE0(), K, ONTO, np.zeros(len(COMPONENTS)) if beta is None else beta, 10)


def legacy_choose_questions(public, e0_probs, genes, knowledge, ontology, n_candidates=10, n_questions=7):
    """Verbatim copy of choose_questions as of ce1582e, kept as the identity reference for Q0."""
    order = [i for i in np.argsort(e0_probs)[::-1] if knowledge.diseases(genes[i])][:n_candidates]
    if len(order) < 2:
        return []
    prior = e0_probs[order] / e0_probs[order].sum()
    reported = set(public.present)
    related = set(reported)
    for t in reported:
        related |= ontology.ancestors(t) | ontology.descendants(t)
    terms = set()
    for i in order:
        for disease in knowledge.diseases(genes[i]):
            terms.update(knowledge.kb["diseases"][disease]["phenotypes"])
    terms -= related
    h0 = interactive._entropy(prior)
    scored = []
    for t in sorted(terms):
        p = np.clip([knowledge.term_probability(genes[i], t) for i in order], 0.02, 1 - 0.02)
        p_yes = float(prior @ p)
        post_yes, post_no = prior * p / p_yes, prior * (1 - p) / (1 - p_yes)
        gain = h0 - p_yes * interactive._entropy(post_yes) - (1 - p_yes) * interactive._entropy(post_no)
        if gain > 1e-9:
            scored.append((gain, t))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [t for _, t in scored[:n_questions]]


@pytest.mark.parametrize("present", [("HP:0001263",), ("HP:0001250",), ("HP:0001263", "HP:0000028"), ()])
@pytest.mark.parametrize("probs", [(0.5, 0.3, 0.2), (0.2, 0.2, 0.6), (1.0, 0.0, 0.0)])
def test_q0_questions_are_identical_to_the_legacy_questioner_at_q7(present, probs):
    probs = np.array(probs)
    public = PublicCase("c", present)
    legacy = legacy_choose_questions(public, probs, GENES, K, ONTO, 10, 7)
    assert interactive.choose_questions(public, probs, GENES, K, ONTO, 10, 7) == legacy

    class E0(FakeE0):
        def score(self, case):
            return Scored(probs)

    c = questioning.Context(E0(), K, ONTO, np.zeros(len(COMPONENTS)))
    q0 = questioning.Q0(n_questions=7)
    assert q0.schedule == (7,)
    assert q0.next_batch(c, public, {}, 7) == legacy


def test_q0_runs_9_in_one_batch_and_strategies_never_receive_the_truth():
    assert questioning.Q0().schedule == (9,)
    assert questioning.Q2().schedule == questioning.Q2b().schedule == (3, 3, 3)
    assert sum(questioning.Q2().schedule) == questioning.BUDGET
    for fn in (questioning.Q0.next_batch, questioning.Q2.next_batch):
        assert "true_present" not in inspect.signature(fn).parameters


def test_harness_owns_the_answer_rule_and_adaptive_rounds_see_earlier_answers():
    from test_rerank import case

    seen = []

    class Spy:
        name = "spy"
        schedule = (1, 1)

        def next_batch(self, c, public, answers, n):
            seen.append(dict(answers))
            return ["HP:0001250"] if not answers else ["HP:0000028"]

    iv = questioning.interview(case(), frozenset({"HP:0002373"}), Spy(), ctx())
    assert seen == [{}, {"HP:0001250": "yes"}]
    assert iv.after.present == ("HP:0001250", "HP:0001263") and iv.after.excluded == ("HP:0000028",)


def test_budget_is_enforced_and_repeats_are_dropped():
    from test_rerank import case

    class Greedy:
        name = "greedy"
        schedule = (5, 5)

        def next_batch(self, c, public, answers, n):
            return ["HP:0001250", "HP:0001250", "HP:0000028", "HP:0001263"]

    iv = questioning.interview(case(), frozenset(), Greedy(), ctx(), budget=2)
    assert len(iv.questions) == 2 and len(set(iv.questions)) == 2


def test_noise_is_seeded_and_flips_or_unknowns():
    rng = questioning._rng(1, "c")
    answers = {questioning.noisy(True, 1.0, rng) for _ in range(200)}
    assert answers == {questioning.NO, questioning.UNKNOWN}
    assert questioning.noisy(True, 0.0, rng) == questioning.YES
    a = [questioning.noisy(False, 0.3, questioning._rng(7, "c")) for _ in range(3)]
    assert a == [questioning.noisy(False, 0.3, questioning._rng(7, "c")) for _ in range(3)]


def test_q2_applies_the_reranker_to_no_answers_and_never_asks_related_terms():
    beta = question_run.parse_reranker("rr-v1[neg=2]")[1]
    public = PublicCase("c", ("HP:0001263",))
    q2 = questioning.Q2(n_candidates=3)
    first = q2.next_batch(ctx(beta), public, {}, 3)
    assert first and "HP:0001263" not in first
    answers = {"HP:0000028": "no"}
    probs = q2.posterior(ctx(beta), public, answers)
    plain = ctx(beta).posterior(questioning.case_of(public, answers), rerank=False)
    assert not np.allclose(probs, plain)
    later = q2.next_batch(ctx(beta), public, answers, 3)
    assert "HP:0000028" not in later


def test_q2b_penalises_terms_sharing_a_sub_organ_ancestor():
    c = ctx()
    scored = [(1.0, "HP:0001250"), (0.9, "HP:0002373"), (0.6, "HP:0000028")]
    pick = questioning.Q2b(lam=0.5).pick(c, scored, {}, 2)
    assert pick == ["HP:0001250", "HP:0000028"]
    assert questioning.Q2().pick(c, scored, {}, 2) == ["HP:0001250", "HP:0002373"]


def test_reranker_specs():
    name, beta = question_run.parse_reranker("rr-v1")
    assert name == "rr-v1[neg=0.5]" and beta[COMPONENTS.index("neg_llr")] == 0.5
    assert question_run.parse_reranker("rr-v1[neg=1,sex=0.5]")[0] == "rr-v1[neg=1,sex=0.5]"
    with pytest.raises(ValueError):
        question_run.parse_reranker("nope")


def test_q1_serves_the_agent_selector_our_posterior_and_knowledge():
    from diagnostic_ar_training.eval import agent_selector

    if not (agent_selector.AGENT_ROOT / "src").is_dir():
        pytest.skip("question agent worktree not readable")
    q1 = agent_selector.Q1()
    public = PublicCase("c", ("HP:0001263",))
    c = ctx()
    batch = q1.next_batch(c, public, {}, 3)
    assert batch and "HP:0001263" not in batch
    later = q1.next_batch(c, public, {batch[0]: "no"}, 3)
    assert batch[0] not in later
    assert agent_selector.agent_version()["sha"]


def test_the_sealed_part_is_refused_before_anything_is_read(tmp_path):
    from typer.testing import CliRunner

    from diagnostic_ar_training.cli import app

    result = CliRunner().invoke(
        app, ["s3", "interview", "--exp", "EXP-Q-001", "--part", "test", "--strategy", "Q0"]
    )
    assert result.exit_code != 0
