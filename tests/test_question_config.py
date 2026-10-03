import json

import numpy as np
from test_questioning import GENES, K, ONTO, FakeE0

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import question_run, questioning
from diagnostic_ar_training.rerank.config import RerankConfig
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge


def test_a_rerank_config_file_is_a_reranker_spec_with_its_hash_in_the_name(tmp_path):
    config = RerankConfig("kb-v6", "propagated", 0.5, weights={"neg_llr": 0.5})
    path = tmp_path / "final.json"
    path.write_text(config.to_json())
    name, beta, loaded = question_run.load_reranker(str(path))
    assert name == f"cfg-{config.config_hash}" and loaded == config
    assert np.array_equal(beta, config.beta())
    beta_only = tmp_path / "beta.json"
    beta_only.write_text(json.dumps({"beta": {"neg_llr": 1.0}}))
    name, beta, loaded = question_run.load_reranker(str(beta_only))
    assert loaded is None and beta[COMPONENTS.index("neg_llr")] == 1.0
    assert question_run.load_reranker("rr-v1")[2] is None


def test_the_posterior_uses_the_rerankers_knowledge_and_parameters_not_the_questioners():
    config = RerankConfig("kb-x", "gated", 0.5, neg_tau=0.99, weights={"neg_llr": 1.0})
    case = Case(case_id="c", cohort="t", gene="", present=("HP:0001263",), excluded=("HP:0002373",))

    def posterior(rr_knowledge):
        ctx = questioning.Context(FakeE0(), K, ONTO, config.beta(), 10, rr_knowledge)
        return ctx.posterior(case, rerank=True)

    plain = posterior(None)
    gated = posterior(config.knowledge(K.kb, ONTO))
    assert not np.allclose(plain, gated)
    assert np.allclose(gated, FakeE0().score(case).probs)
    assert len(GENES) == len(plain)


def test_a_run_has_a_stable_hash_over_everything_that_defines_it_and_q2b_lambda_is_part_of_the_label():
    h = question_run.run_hash("Q2b", 0.3, "abc", "kb-v6", 0.0, 0)
    assert h == question_run.run_hash("Q2b", 0.3, "abc", "kb-v6", 0.0, 0)
    assert h != question_run.run_hash("Q2b", 0.6, "abc", "kb-v6", 0.0, 0)
    assert h != question_run.run_hash("Q2b", 0.3, "abc", "kb-v6", 0.05, 0)
    assert question_run.run_hash("Q0", 0.3, "abc", "kb-v6", 0.0, 0) == question_run.run_hash(
        "Q0", 0.9, "abc", "kb-v6", 0.0, 0
    )
    assert (
        question_run.strategy_label("Q2b", 0.3) == "Q2b-lam0.3"
        and question_run.strategy_label("Q0", 0.3) == "Q0"
    )


def test_the_log_row_reads_every_effect_and_the_r1_values_of_the_same_reranker(tmp_path):
    def cmp(delta, harmed=0.0):
        return {"delta": delta, "ci95": [delta - 0.01, delta + 0.01], "harmed": harmed, "helped": 0.2}

    summary = {"mrr": 0.4, "top10": 0.6}
    report = {
        "strategy": "Q2b", "kb": "kb-v6", "noise": 0.0, "seed": 0, "reranker": "cfg-x", "cases": 10,
        "primary (final vs E0-initial)": cmp(0.1, 0.01),
        "questioner_effect (E0+answers vs E0-initial)": cmp(0.09),
        "reranker_effect (final vs E0+answers)": cmp(0.01, 0.04),
        "E0-initial": summary, "E0+answers": summary, "final": summary,
        "yes_per_case": 1.1, "no_per_case": 7.8,
    }  # fmt: skip
    b004 = tmp_path / "dev-search.tsv"
    b004.write_text(
        "# header\nlever\tconfig_hash\tr1dev_delta\tr1dev_ci_lo\tr1dev_ci_hi\tr1dev_pass\nL1\tabc\t-0.002\t-0.01\t0.004\t1\n"
    )
    r1 = question_run.r1_from_b004(b004, "abc")
    assert r1["r1dev_pass"] == "1"
    assert question_run.r1_from_b004(b004, "zzz")["r1dev_delta"] == ""
    row = question_run.q_log_row(report, "Q2b-lam0.3", 0.3, "abc", r1, "sha")
    assert row["strategy"] == "Q2b-lam0.3" and row["lam"] == 0.3 and row["reranker_hash"] == "abc"
    assert row["delta_primary"] == 0.1 and row["reranker_harmed"] == 0.04 and row["r1dev_delta"] == "-0.002"
    log = tmp_path / "q.tsv"
    question_run.append_q_log(log, row)
    question_run.append_q_log(log, row)
    lines = log.read_text().splitlines()
    assert (
        len(lines) == 3 and lines[0].startswith("strategy\t") and set(row) == set(question_run.Q_LOG_COLUMNS)
    )
