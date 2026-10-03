"""Run one question strategy over S3 cases and score E0-initial, E0+answers and the final system."""

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

from diagnostic_ar_training.eval import harness, questioning, s3_run
from diagnostic_ar_training.rerank.features import COMPONENTS
from diagnostic_ar_training.rerank.learned import table

_RR_V1 = re.compile(r"^rr-v1(?:\[(.*)\])?$")


def parse_reranker(spec: str) -> tuple[str, np.ndarray]:
    """`rr-v1` (= rr-v1[neg=0.5]), `rr-v1[neg=1,sex=0.5]`, or a JSON file {"beta": {component: weight}}."""
    if m := _RR_V1.match(spec):
        weights = {"neg": 0.5} if m.group(1) is None else {}
        for part in filter(None, (m.group(1) or "").split(",")):
            key, value = part.split("=")
            if key not in ("neg", "sex", "age", "onset"):
                raise ValueError(f"unknown rr-v1 weight {key!r}")
            weights[key.strip()] = float(value)
        name = "rr-v1[" + ",".join(f"{k}={v:g}" for k, v in sorted(weights.items())) + "]"
        return name, s3_run.rr_v1_beta(**weights)
    path = Path(spec)
    if not path.is_file():
        raise ValueError(f"reranker {spec!r} is neither rr-v1[...] nor a config file")
    beta = json.loads(path.read_text())["beta"]
    return path.stem, np.array([beta.get(c, 0.0) for c in COMPONENTS])


def make_strategy(name: str, lam: float):
    from diagnostic_ar_training.eval.agent_selector import Q1

    strategies = {
        "Q0": lambda: questioning.Q0(n_questions=questioning.BUDGET),
        "Q1": Q1,
        "Q2": questioning.Q2,
        "Q2b": lambda: questioning.Q2b(lam=lam),
    }
    if name not in strategies:
        raise ValueError(f"unknown strategy {name!r}; known: {sorted(strategies)}")
    return strategies[name]()


def select_cases(pairs, n: int, excluded: set[str]) -> list:
    """Drop the exclusion list, then take the first `n` by sha256(case_id): deterministic and gene-blind."""
    kept = [p for p in pairs if p[0].case_id not in excluded]
    kept.sort(key=lambda p: hashlib.sha256(p[0].case_id.encode()).hexdigest())
    return kept[:n] if n > 0 else kept


def run(pairs, strategy, ctx, noise: float, seed: int, top_k: int) -> list[dict]:
    """One row per case: the interview, the three scored distributions' ranks, and the wall time."""
    rows = []
    for case, truth in pairs:
        start = time.perf_counter()
        initial = ctx.e0_probs(case)
        iv = questioning.interview(case, truth, strategy, ctx, noise, seed)
        t = table(ctx.e0, ctx.knowledge, iv.after, top_k)
        base, final = t.combine(np.zeros(len(COMPONENTS))), t.combine(ctx.beta)
        rows.append(
            {
                "case_id": case.case_id,
                "gene": case.gene,
                "questions": iv.questions,
                "answers": iv.answers,
                "yes": sum(a == questioning.YES for a in iv.answers.values()),
                "no": sum(a == questioning.NO for a in iv.answers.values()),
                "unknown": sum(a == questioning.UNKNOWN for a in iv.answers.values()),
                "rank_initial": s3_run.rank(initial, ctx.e0.genes, case.gene),
                "rank_answers": s3_run.rank(base, ctx.e0.genes, case.gene),
                "rank_final": s3_run.rank(final, ctx.e0.genes, case.gene),
                "seconds": time.perf_counter() - start,
            }
        )
    return rows


def records(rows: list[dict], key: str) -> list[dict]:
    return [
        {
            "case_id": r["case_id"],
            "group": r["gene"],
            "gene": r["gene"],
            "rank": r[key],
            "has_excluded": r["no"] > 0,
            "has_sex": False,
            "has_age": False,
            "gene_in_vocab": True,
            "scorable": True,
            "latency_ms": r["seconds"] * 1000,
        }
        for r in rows
    ]


def report(rows: list[dict]) -> dict:
    initial, answers, final = (records(rows, k) for k in ("rank_initial", "rank_answers", "rank_final"))
    secs = np.array([r["seconds"] for r in rows])
    return {
        "cases": len(rows),
        "questions_per_case": float(np.mean([len(r["questions"]) for r in rows])),
        "yes_per_case": float(np.mean([r["yes"] for r in rows])),
        "no_per_case": float(np.mean([r["no"] for r in rows])),
        "unknown_per_case": float(np.mean([r["unknown"] for r in rows])),
        "seconds_per_case": {
            "mean": float(secs.mean()),
            "p50": float(np.percentile(secs, 50)),
            "p95": float(np.percentile(secs, 95)),
        },  # fmt: skip
        "E0-initial": harness.summarize(initial)["all"],
        "E0+answers": harness.summarize(answers)["all"],
        "final": harness.summarize(final)["all"],
        "questioner_effect (E0+answers vs E0-initial)": harness.compare(initial, answers),
        "reranker_effect (final vs E0+answers)": harness.compare(answers, final),
        "primary (final vs E0-initial)": harness.compare(initial, final),
    }
