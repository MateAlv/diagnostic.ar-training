"""rr-v2: a conditional-logit re-ranker whose feature weights are fitted on R1-train.

score(g) = log p_gnn(g) + beta . components(case, g) over the GNN's top-K genes; the
GNN term has a fixed coefficient of 1, so a case without new inputs gets exactly the
GNN's distribution. beta maximises the L2-penalised likelihood of the true gene among
the top-K candidates, over training cases whose true gene is among them.
"""

import json
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.rerank.features import COMPONENTS, GeneKnowledge, components
from diagnostic_ar_training.systems import Scored, System


@dataclass
class Table:
    probs: np.ndarray | None
    top: np.ndarray
    x: np.ndarray  # [K, len(COMPONENTS)]
    true_pos: int | None  # position of the true gene within `top`
    info: dict

    def combine(self, beta: np.ndarray) -> np.ndarray | None:
        if self.probs is None:
            return None
        delta = self.x @ beta if self.top.size else None
        if delta is None or not np.any(delta):
            return self.probs
        scores = np.log(np.clip(self.probs, 1e-300, None))
        scores[self.top] += delta
        scores -= scores.max()
        exp = np.exp(scores)
        return exp / exp.sum()


def table(base: System, knowledge: GeneKnowledge, case: Case, top_k: int) -> Table:
    scored = base.score(case)
    empty = np.zeros((0, len(COMPONENTS)))
    if scored.probs is None:
        return Table(None, np.zeros(0, dtype=int), empty, None, scored.info)
    top = np.argsort(scored.probs)[::-1][:top_k]
    x = np.array(
        [[components(knowledge, case, base.genes[i])[c] for c in COMPONENTS] for i in top], dtype=float
    )
    upper = [base.genes[i].upper() for i in top]
    true_pos = upper.index(case.gene.upper()) if case.gene.upper() in upper else None
    return Table(scored.probs, top, x, true_pos, scored.info)


def fit(tables: list[Table], l2: float) -> tuple[np.ndarray, dict]:
    usable = [t for t in tables if t.true_pos is not None and np.any(t.x)]
    logp = [np.log(np.clip(t.probs[t.top], 1e-300, None)) for t in usable]
    n_features = len(COMPONENTS)

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        loss, grad = l2 * beta @ beta, 2 * l2 * beta
        for t, lp in zip(usable, logp, strict=True):
            s = lp + t.x @ beta
            s -= s.max()
            p = np.exp(s)
            p /= p.sum()
            loss -= np.log(p[t.true_pos])
            grad -= t.x[t.true_pos] - p @ t.x
        return loss / len(usable), grad / len(usable)

    result = minimize(objective, np.zeros(n_features), jac=True, method="L-BFGS-B")
    return result.x, {
        "cases_used": len(usable),
        "converged": bool(result.success),
        "loss": float(result.fun),
        "loss_at_zero": float(objective(np.zeros(n_features))[0]),
    }


class LearnedReRanker:
    def __init__(
        self, base: System, knowledge: GeneKnowledge, beta: np.ndarray, top_k: int = 200, name="rr-v2"
    ):
        self.base, self.knowledge, self.beta, self.top_k, self.name = base, knowledge, beta, top_k, name
        self.genes = base.genes

    def lineage_inputs(self) -> list[dict]:
        return self.base.lineage_inputs()

    def score(self, case: Case) -> Scored:
        t = table(self.base, self.knowledge, case, self.top_k)
        return Scored(t.combine(self.beta), t.info)


def save_beta(beta: np.ndarray, path) -> None:
    path.write_text(
        json.dumps(dict(zip(COMPONENTS, map(float, beta), strict=True)), indent=1, sort_keys=True) + "\n"
    )


def load_beta(path) -> np.ndarray:
    values = json.loads(path.read_text())
    return np.array([values[c] for c in COMPONENTS])
