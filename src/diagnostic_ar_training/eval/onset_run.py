"""EXP-B-005: one Q2b interview driven by the reference re-ranker, scored for several configurations.

The questioner of a Q2b interview uses the re-ranker's posterior, so interviews driven by different
configurations can ask different questions. The session therefore interviews once with the reference
configuration and scores every candidate on those same answers (`dev_search.score_arms`); the
reference's own ranks from the interview are kept to check that the two scoring paths agree.
"""

import gzip
import json
import math
import multiprocessing

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import dev_search, questioning
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import GeneKnowledge
from diagnostic_ar_training.rerank.learned import table

SEALED_EXPERIMENT = {"s3-v3b": "EXP-B-005"}
"""The only experiment allowed to open the sealed part of each split in a session."""

_IV: dict = {}


def check_sealed_request(split_id: str, part: str, exp: str, reason: str, cases: int = 0) -> None:
    """A sealed session is the one pre-registered read of its experiment: all cases, with a reason."""
    from diagnostic_ar_training.cohorts import s3

    if part not in s3.SEALED:
        return
    if SEALED_EXPERIMENT.get(split_id) != exp or not reason.strip() or cases != 0:
        raise ValueError(
            f"{split_id}/{part} is read only by {SEALED_EXPERIMENT.get(split_id)}'s one pre-registered "
            "read: all cases, with a reason"
        )


def _encode(rank: float):
    return "inf" if math.isinf(rank) else rank


def _init(lam, knowledge, rr_knowledge, ontology, beta, top_k) -> None:
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    e0 = GenPheniaV3()
    ctx = questioning.Context(e0, knowledge, ontology, beta, top_k, rr_knowledge)
    _IV.update(
        ctx=ctx,
        strategy=questioning.Q2b(lam=lam),
        lookup=dev_search.gene_index(e0.genes),
        top_k=top_k,
    )


def _interview_one(pair: tuple[Case, frozenset[str]]) -> dict:
    case, truth = pair
    ctx = _IV["ctx"]
    iv = questioning.interview(case, truth, _IV["strategy"], ctx)
    idx = _IV["lookup"].get(case.gene.upper())
    final = table(ctx.e0, ctx.rr_knowledge, iv.after, _IV["top_k"]).combine(ctx.beta)
    return {
        "case_id": case.case_id,
        "gene": case.gene,
        "questions": iv.questions,
        "answers": iv.answers,
        "after": iv.after.model_dump(mode="json"),
        "rank_initial": _encode(dev_search.rank_at(ctx.e0_probs(case), idx)),
        "rank_driver_final": _encode(dev_search.rank_at(final, idx)),
    }


def interview(
    pairs: list[tuple[Case, frozenset[str]]],
    lam: float,
    knowledge: GeneKnowledge,
    rr_knowledge: GeneKnowledge,
    ontology: Ontology,
    beta: np.ndarray,
    top_k: int,
    workers: int,
) -> list[dict]:
    """Q2b interviews in input order; the questioner sees a PublicCase only."""
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(workers, _init, (lam, knowledge, rr_knowledge, ontology, beta, top_k)) as pool:
        return list(pool.imap(_interview_one, pairs, 8))


def write_rows(path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for r in rows:
            handle.write(json.dumps(r, sort_keys=True) + "\n")


def read_rows(path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    for r in rows:
        r["case"] = Case.model_validate(r["after"])
        for key in ("rank_initial", "rank_driver_final"):
            r[key] = math.inf if r[key] == "inf" else r[key]
    return rows
