"""Run one question strategy over S3 cases and score E0-initial, E0+answers and the final system."""

import hashlib
import json
import re
import time
from pathlib import Path

import numpy as np

from diagnostic_ar_training.eval import harness, questioning, s3_run
from diagnostic_ar_training.rerank.config import RerankConfig
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


def load_reranker(spec: str) -> tuple[str, np.ndarray, RerankConfig | None]:
    """`parse_reranker`, plus a `RerankConfig` JSON file ({"kb_id": ..., "neg_form": ..., "weights": ...}).

    The config's name is `cfg-<hash>`; its KB and feature parameters come back as the config.
    """
    path = Path(spec)
    if path.is_file():
        data = json.loads(path.read_text())
        if "kb_id" in data:
            config = RerankConfig.from_dict(data)
            return f"cfg-{config.config_hash}", config.beta(), config
    name, beta = parse_reranker(spec)
    return name, beta, None


def strategy_label(name: str, lam: float) -> str:
    return f"Q2b-lam{lam:g}" if name == "Q2b" else name


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
        t = table(ctx.e0, ctx.rr_knowledge, iv.after, top_k)
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


_RUN: dict = {}


def _init_run(name, lam, knowledge, rr_knowledge, ontology, beta, noise, seed, top_k) -> None:
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    ctx = questioning.Context(GenPheniaV3(), knowledge, ontology, beta, top_k, rr_knowledge)
    _RUN.update(ctx=ctx, strategy=make_strategy(name, lam), noise=noise, seed=seed, top_k=top_k)


def _run_one(pair) -> dict:
    return run([pair], _RUN["strategy"], _RUN["ctx"], _RUN["noise"], _RUN["seed"], _RUN["top_k"])[0]


def run_parallel(
    pairs,
    name,
    lam,
    knowledge,
    rr_knowledge,
    ontology,
    beta,
    noise: float,
    seed: int,
    top_k: int,
    workers: int,
) -> list[dict]:
    """`run` over worker processes, in input order; each worker loads its own E0 and strategy."""
    import multiprocessing

    args = (name, lam, knowledge, rr_knowledge, ontology, beta, noise, seed, top_k)
    with multiprocessing.get_context("fork").Pool(workers, _init_run, args) as pool:
        return list(pool.imap(_run_one, pairs, 8))


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


Q_LOG_COLUMNS = (
    "strategy", "lam", "config_hash", "reranker", "reranker_hash", "kb", "noise", "cases",
    "delta_primary", "ci_lo", "ci_hi", "harmed_primary", "helped_primary",
    "questioner_delta", "questioner_ci_lo", "questioner_ci_hi",
    "reranker_delta", "reranker_ci_lo", "reranker_ci_hi", "reranker_harmed", "reranker_helped",
    "mrr_initial", "mrr_answers", "mrr_final", "top10_initial", "top10_final",
    "yes_per_case", "no_per_case",
    "r1dev_delta", "r1dev_ci_lo", "r1dev_ci_hi", "r1dev_pass", "code_sha",
)  # fmt: skip


def run_hash(strategy: str, lam: float, reranker_hash: str, kb_id: str, noise: float, seed: int) -> str:
    """Identity of one L4 configuration: strategy, its parameter, the re-ranker, the KB, budget, noise."""
    from diagnostic_ar_training.lineage.hashing import sha256_json

    body = {
        "strategy": strategy,
        "lam": lam if strategy == "Q2b" else None,
        "reranker": reranker_hash,
        "kb": kb_id,
        "budget": questioning.BUDGET,
        "noise": noise,
        "seed": seed,
    }
    return sha256_json(body)[:12]


def q_log_row(report: dict, label: str, lam: float, reranker_hash: str, r1: dict, code_sha: str) -> dict:
    primary = report["primary (final vs E0-initial)"]
    q_eff = report["questioner_effect (E0+answers vs E0-initial)"]
    r_eff = report["reranker_effect (final vs E0+answers)"]
    return {
        "strategy": label,
        "lam": lam if report["strategy"] == "Q2b" else "",
        "config_hash": run_hash(
            report["strategy"], lam, reranker_hash, report["kb"], report["noise"], report["seed"]
        ),
        "reranker": report["reranker"],
        "reranker_hash": reranker_hash,
        "kb": report["kb"],
        "noise": report["noise"],
        "cases": report["cases"],
        "delta_primary": round(primary["delta"], 6),
        "ci_lo": round(primary["ci95"][0], 6),
        "ci_hi": round(primary["ci95"][1], 6),
        "harmed_primary": round(primary["harmed"], 5),
        "helped_primary": round(primary["helped"], 5),
        "questioner_delta": round(q_eff["delta"], 6),
        "questioner_ci_lo": round(q_eff["ci95"][0], 6),
        "questioner_ci_hi": round(q_eff["ci95"][1], 6),
        "reranker_delta": round(r_eff["delta"], 6),
        "reranker_ci_lo": round(r_eff["ci95"][0], 6),
        "reranker_ci_hi": round(r_eff["ci95"][1], 6),
        "reranker_harmed": round(r_eff["harmed"], 5),
        "reranker_helped": round(r_eff["helped"], 5),
        "mrr_initial": round(report["E0-initial"]["mrr"], 6),
        "mrr_answers": round(report["E0+answers"]["mrr"], 6),
        "mrr_final": round(report["final"]["mrr"], 6),
        "top10_initial": round(report["E0-initial"]["top10"], 5),
        "top10_final": round(report["final"]["top10"], 5),
        "yes_per_case": round(report["yes_per_case"], 4),
        "no_per_case": round(report["no_per_case"], 4),
        "r1dev_delta": r1["r1dev_delta"],
        "r1dev_ci_lo": r1["r1dev_ci_lo"],
        "r1dev_ci_hi": r1["r1dev_ci_hi"],
        "r1dev_pass": r1["r1dev_pass"],
        "code_sha": code_sha,
    }


def r1_from_b004(log: Path, reranker_hash: str) -> dict:
    """The re-ranker's R1-dev no-harm values, as logged for the same config hash in EXP-B-004's search."""
    import csv

    lines = [line for line in log.read_text().splitlines() if not line.startswith("#")]
    for r in csv.DictReader(lines, delimiter="\t"):
        if r["config_hash"] == reranker_hash:
            return {k: r[k] for k in ("r1dev_delta", "r1dev_ci_lo", "r1dev_ci_hi", "r1dev_pass")}
    return dict.fromkeys(("r1dev_delta", "r1dev_ci_lo", "r1dev_ci_hi", "r1dev_pass"), "")


def append_q_log(path: Path, row: dict) -> None:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text().splitlines() if path.exists() else []
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, Q_LOG_COLUMNS, delimiter="\t", lineterminator="\n")
        if not any(line.startswith("strategy\t") for line in existing):
            writer.writeheader()
        writer.writerow(row)
