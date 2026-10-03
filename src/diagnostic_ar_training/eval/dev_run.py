"""Orchestration of the EXP-B-004 dev search: the Q0 interview, arm scoring, subsets and the R1-dev check."""

import gzip
import json
import math
import multiprocessing
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.eval import dev_search, questioning
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.config import RerankConfig, rr_v1_reference
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge

_IV: dict = {}


def _init_interview(knowledge: GeneKnowledge, ontology: Ontology, n_questions: int, top_k: int) -> None:
    from diagnostic_ar_training.systems.genphenia_v3 import GenPheniaV3

    e0 = GenPheniaV3()
    _IV.update(
        ctx=questioning.Context(e0, knowledge, ontology, np.zeros(len(COMPONENTS)), top_k),
        strategy=questioning.Q0(n_questions=n_questions),
        lookup=dev_search.gene_index(e0.genes),
    )


def _interview_one(pair: tuple[Case, frozenset[str]]) -> dict:
    case, truth = pair
    ctx = _IV["ctx"]
    iv = questioning.interview(case, truth, _IV["strategy"], ctx)
    return {
        "case_id": case.case_id,
        "gene": case.gene,
        "questions": iv.questions,
        "answers": iv.answers,
        "after": iv.after.model_dump(mode="json"),
        "rank_initial": dev_search.rank_at(ctx.e0_probs(case), _IV["lookup"].get(case.gene.upper())),
    }


def interview_dev(
    pairs: list[tuple[Case, frozenset[str]]],
    knowledge: GeneKnowledge,
    ontology: Ontology,
    n_questions: int,
    top_k: int,
    workers: int,
) -> list[dict]:
    """Q0 interviews, in input order. The questioner sees a PublicCase only; E0 and the half-A KB drive it."""
    ctx = multiprocessing.get_context("fork")
    with ctx.Pool(workers, _init_interview, (knowledge, ontology, n_questions, top_k)) as pool:
        return list(pool.imap(_interview_one, pairs, 16))


def read_interviews(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    for r in rows:
        r["case"] = Case.model_validate(r["after"])
        r["rank_initial"] = math.inf if r["rank_initial"] == "inf" else r["rank_initial"]
    return rows


def encode_interview(row: dict) -> dict:
    return {**row, "rank_initial": "inf" if math.isinf(row["rank_initial"]) else row["rank_initial"]}


def subset_masks(
    rows: list[dict],
    entities: dict[str, str],
    lit_entities: set[str],
    half_b: set[tuple[str, str]],
    onset_source: dict[str, str | None],
) -> dict[str, list[bool]]:
    """Case subsets for the analyses; `entities` is analysis-only metadata, never given to a system."""
    out: dict[str, list[bool]] = {"all": [True] * len(rows)}
    cases = [r["case"] for r in rows]
    entity = [entities[c.case_id] for c in cases]
    out["with_excluded"] = [bool(c.excluded) for c in cases]
    out["sex_known"] = [dev_search.known_sex(c) for c in cases]
    out["age_known"] = [c.age_years is not None for c in cases]
    lit = [e in lit_entities for e in entity]
    out["lit_onset"] = lit
    out["lit_onset_age_known"] = [a and c.age_years is not None for a, c in zip(lit, cases, strict=True)]
    for source in ("hpoa", "orphanet", "orphanet_exact_alignment", None):
        label = "none" if source is None else source
        out[f"lit_onset_src_{label}"] = [
            a and onset_source.get(e) == source for a, e in zip(lit, entity, strict=True)
        ]
        out[f"lit_onset_src_{label}_age_known"] = [
            m and c.age_years is not None for m, c in zip(out[f"lit_onset_src_{label}"], cases, strict=True)
        ]
    in_b = [[(e, t) in half_b for t in c.excluded] for e, c in zip(entity, cases, strict=True)]
    out["halfB_only_excluded"] = [bool(f) and all(f) for f in in_b]
    out["halfB_any_excluded"] = [any(f) for f in in_b]
    out["excluded_none_halfB"] = [bool(f) and not any(f) for f in in_b]
    return out


def analyse(
    rows: list[dict],
    base_ranks: Sequence[float],
    arm_ranks: np.ndarray,
    arms: list[dev_search.Arm],
    masks: dict[str, list[bool]],
    vs: dict[str, int] | None = None,
) -> dict:
    """Per arm and subset: Δ MRR vs E0+answers (CI over genes), and vs the arms named in `vs` (paired)."""
    ids = [r["case_id"] for r in rows]
    groups = [r["gene"] for r in rows]
    base = dev_search.records(ids, groups, base_ranks)
    out: dict = {}
    for j, arm in enumerate(arms):
        new = dev_search.records(ids, groups, arm_ranks[:, j])
        entry = {name: dev_search.compare(base, new, mask) for name, mask in masks.items()}
        paired = {}
        for label, k in (vs or {}).items():
            ref = dev_search.records(ids, groups, arm_ranks[:, k])
            paired[label] = {name: dev_search.compare(ref, new, mask) for name, mask in masks.items()}
        out[arm.arm_id] = {
            "config": arm.config.to_dict(),
            "config_hash": arm.config.config_hash,
            "vs_e0_answers": entry,
            "paired": paired,
        }
    return out


def r1_dev(
    arms: list[dev_search.Arm],
    knowledges: dict[str, GeneKnowledge],
    ontology: Ontology,
    top_k: int,
    workers: int,
) -> tuple[list[dict], list[float], np.ndarray]:
    """R1-dev cases as given ("all" view), their E0 ranks and every arm's ranks; groups are publications."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.cohorts import access

    cases = access.load("r1-v1/dev")
    groups = splits.publication_groups("r1-v1")
    base, ranks = dev_search.score_arms(
        [(c, c.gene) for c in cases], arms, knowledges, ontology, top_k, workers
    )
    meta = [{"case_id": c.case_id, "gene": groups[c.case_id]} for c in cases]
    return meta, base, ranks


def r1_summary(
    meta: list[dict], base: Sequence[float], ranks: np.ndarray, arms: list[dev_search.Arm]
) -> dict:
    ids = [m["case_id"] for m in meta]
    groups = [m["gene"] for m in meta]
    b = dev_search.records(ids, groups, base)
    return {
        a.arm_id: dev_search.compare(b, dev_search.records(ids, groups, ranks[:, j]))
        for j, a in enumerate(arms)
    }


def reference_arms(kb_id: str = "kb-v5") -> list[dev_search.Arm]:
    """rr-v1[neg=0.5] on kb-v5: the released system, scored as the bar. Not a search arm."""
    return [
        dev_search.Arm(
            "ref-rr-v1", "ref", rr_v1_reference(kb_id), "released system, kb-v5 (declared: half B of v1)"
        )
    ]


def zero_config(kb_id: str) -> RerankConfig:
    return RerankConfig(kb_id=kb_id)
