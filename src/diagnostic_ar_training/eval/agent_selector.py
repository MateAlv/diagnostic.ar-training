"""Q1: the production question agent's selector, imported read-only and fed our E0 posterior and knowledge.

The agent is MarBL00126/diagnosticar-question-agent, branch feat/rerank-negaciones, read from
its worktree at AGENT_ROOT at runtime; nothing is copied. Its round is reproduced as
`RoundService.run` does: `model_query` -> model.rank -> BayesianReranker -> `shortlist`. The HTTP
model client is replaced by `E0Client`, which serves E0 on present + "yes", with the harness
re-ranker applied to the "no" answers, as the model service does for `excluded_hpo_ids`.
"""

import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from diagnostic_ar_training.eval.questioning import NO, UNKNOWN, YES, Context
from diagnostic_ar_training.lineage.registry import LineageError

AGENT_ROOT = Path("/home/mate/diagnostic.ar/qa-rerank-wt")
AGENT_BRANCH = "feat/rerank-negaciones"
RANKING_TOP_K = 50


def _git(*args: str) -> str:
    # A git hook exports GIT_DIR, which would point `git -C` at our repo instead of the agent's.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(AGENT_ROOT), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def agent_version() -> dict:
    """Commit, branch and cleanliness of the agent worktree, recorded in every Q1 result."""
    if not (AGENT_ROOT / "src" / "diagnosticar_preguntas").is_dir():
        raise LineageError(f"cannot read the question agent at {AGENT_ROOT}")
    return {
        "path": str(AGENT_ROOT),
        "sha": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(_git("status", "--porcelain", "--untracked-files=no")),
    }


def import_agent() -> None:
    """Make `diagnosticar_preguntas` importable: its src first, its venv only for missing deps."""
    version = agent_version()
    if version["branch"] != AGENT_BRANCH:
        raise LineageError(f"{AGENT_ROOT} is on {version['branch']}, expected {AGENT_BRANCH}")
    src = str(AGENT_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    try:
        import httpx  # noqa: F401
    except ModuleNotFoundError:
        for site in sorted((AGENT_ROOT / ".venv" / "lib").glob("python*/site-packages")):
            sys.path.append(str(site))


def build_agent_kb(knowledge, ontology, genes):
    """The agent's KnowledgeBase over exactly our half-A knowledge: same diseases, frequencies, genes."""
    from diagnosticar_preguntas.kb.build import _requires_testing
    from diagnosticar_preguntas.kb.ontology import depths
    from diagnosticar_preguntas.kb.requires_testing import OBSERVABLE_ROOTS, REQUIRES_TESTING_ROOTS
    from diagnosticar_preguntas.kb.store import Annotation, KnowledgeBase, Term

    parents = {t: frozenset(ontology.parents(t)) for t in ontology._parents}
    ancestors = {t: ontology.ancestors(t) for t in parents}
    depth = depths(parents)
    testing = _requires_testing(ancestors, REQUIRES_TESTING_ROOTS, OBSERVABLE_ROOTS)
    terms = {
        t: Term(t, ontology.labels.get(t, t), None, t in ontology.obsolete, None, depth.get(t), t in testing)
        for t in parents
    }
    annotations = {}
    for disease_id, d in knowledge.kb["diseases"].items():
        rows = [Annotation(t, False, p["freq"], None) for t, p in d["phenotypes"].items()]
        rows += [Annotation(t, True, None, None) for t in d.get("excluded", ())]
        annotations[disease_id] = tuple(rows)
    gene_diseases = {g: tuple(sorted(knowledge.diseases(g))) for g in genes if knowledge.diseases(g)}
    return KnowledgeBase(
        meta={"hpo_version": "harness", "kb_schema_version": "harness"},
        terms=terms,
        alt_ids=dict(ontology._alt_ids),
        parents=parents,
        ancestors=ancestors,
        disease_names={d: None for d in annotations},
        annotations=annotations,
        gene_diseases=gene_diseases,
    )


class E0Client:
    """Implements the agent's `ModelClient` over E0 and the harness re-ranker instead of HTTP."""

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def rank(self, hpo_ids, top_k, excluded_hpo_ids=()):
        import_agent()
        from diagnosticar_preguntas.domain import ModelRanking

        from diagnostic_ar_training.cohorts.schema import Case

        case = Case(
            case_id="q1",
            cohort="s3-question",
            gene="",
            present=tuple(hpo_ids),
            excluded=tuple(excluded_hpo_ids),
        )
        probs = self._ctx.posterior(case, rerank=bool(excluded_hpo_ids))
        genes = self._ctx.e0.genes
        if probs is None:
            return ModelRanking(scores={}, query_hpo_ids=tuple(hpo_ids))
        top = probs.argsort()[::-1][:top_k]
        return ModelRanking(scores={genes[i]: float(probs[i]) for i in top}, query_hpo_ids=tuple(hpo_ids))


@dataclass
class Q1:
    """The agent's selector: top-50 posterior, P(term | disease), MMR diversity; 3 rounds x 3."""

    mode: str = "clinician"
    name: str = "Q1"
    schedule: tuple[int, ...] = (3, 3, 3)
    _state: dict = None

    def _setup(self, ctx: Context) -> dict:
        if self._state is None or self._state["ctx"] is not ctx:
            import_agent()
            from diagnosticar_preguntas.config import Settings
            from diagnosticar_preguntas.ranking.likelihood import LikelihoodModel
            from diagnosticar_preguntas.ranking.reranker import BayesianReranker
            from diagnosticar_preguntas.selection import InformationGainSelector, SelectionConfig
            from diagnosticar_preguntas.selection.askability import AskabilityRules

            kb = build_agent_kb(ctx.knowledge, ctx.ontology, ctx.e0.genes)
            likelihood = LikelihoodModel(kb)
            self._state = {
                "ctx": ctx,
                "kb": kb,
                "client": E0Client(ctx),
                "reranker": BayesianReranker(kb, likelihood),
                "selector": InformationGainSelector(
                    kb, likelihood, SelectionConfig(askability=AskabilityRules(require_spanish_label=False))
                ),
                "shortlist_size": Settings.model_fields["shortlist_size"].default,
            }
        return self._state

    def next_batch(self, ctx: Context, public, answers: Mapping[str, str], n: int) -> list[str]:
        import_agent()
        from diagnosticar_preguntas.domain import Evidence
        from diagnosticar_preguntas.ranking.strategy import RerankStrategy, model_query

        s = self._setup(ctx)
        evidence = Evidence(
            present=frozenset(public.present) | {t for t, a in answers.items() if a == YES},
            absent=frozenset(t for t, a in answers.items() if a == NO),
            unknown=frozenset(t for t, a in answers.items() if a == UNKNOWN),
        )
        query = model_query(
            RerankStrategy.MODEL_SEES_PRESENT,
            reported_present=public.present,
            evidence=evidence,
            answered_no=evidence.absent,
        )
        ranking = s["client"].rank(query.hpo_ids, RANKING_TOP_K, query.excluded_hpo_ids)
        if not ranking.scores:
            return []
        posterior = s["reranker"].rerank(ranking, evidence)
        shortlist = s["selector"].shortlist(posterior, evidence, k=s["shortlist_size"])
        if self.mode == "patient":
            answerable = [c for c in shortlist if not c.requires_testing]
            shortlist = (
                answerable + [c for c in shortlist if c.requires_testing][: max(0, n - len(answerable))]
            )
        return [c.hpo_id for c in shortlist[:n]]


__all__ = ["Q1", "E0Client", "agent_version"]
