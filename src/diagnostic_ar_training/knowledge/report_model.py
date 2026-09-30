"""`report-model-*`: which of a patient's true features a clinician writes down (ADR-0011 §3).

A logistic model over (R1-train patient, term of the patient's disease profile) pairs; the
label is whether the patient's report contains the term or a descendant of it. Profiles
come from a KB that masks every R1 publication, so a patient's own paper never shaped the
frequency it is scored with (ANALYSIS-001 §3.2).
"""

import math
from collections import Counter, defaultdict

import numpy as np
from scipy.optimize import minimize

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology

FEATURES = (
    "frequency",
    "frequency_unknown",
    "information_content",
    "ancestor_count",
    "log_reportability",
    "cardinal",
)
FREQUENCY_ONLY = ("frequency", "frequency_unknown")
DEFINITIONS = {
    "frequency": "HPOA frequency of the term in the disease profile (ADR-0007 estimate); 0 when unknown",
    "frequency_unknown": "1 if the profile gives the term no frequency, else 0",
    "information_content": "-ln((a + 1) / (D + 1)); a = diseases in the masked KB annotating the term "
    "or a descendant, D = diseases in the KB (terms.annotated_diseases, annotation_diseases)",
    "ancestor_count": "number of strict is_a ancestors of the term in HPO (terms.ancestors)",
    "log_reportability": "ln((c + 1) / (N + 1)); c = R1-train patients reporting the term or a "
    "descendant, N = R1-train patients (terms.reportability, reportability_patients). While fitting, "
    "c and N leave out the scored patient's publication group",
    "cardinal": "1 if (disease, term) is a cardinal-v1 row, else 0",
}
L2 = 1e-4


def closure(terms, ontology: Ontology) -> set[str]:
    out = set()
    for t in terms:
        if term := ontology.resolve(t):
            out |= {term, *ontology.ancestors(term)}
    return out


def annotation_counts(kb: dict, ontology: Ontology) -> tuple[Counter, int]:
    """(term -> diseases annotating it or a descendant, number of diseases)."""
    counts: Counter = Counter()
    for disease in kb["diseases"].values():
        counts.update(closure(disease["phenotypes"], ontology))
    return counts, len(kb["diseases"])


def reportability_counts(cases: list[Case], ontology: Ontology) -> Counter:
    counts: Counter = Counter()
    for case in cases:
        counts.update(closure(case.present, ontology))
    return counts


def entity_ids(disease_ids, exact_pairs: list[tuple[str, str]]) -> list[str]:
    """The patient's disease ids plus their exact aligned ids, OMIM first."""
    aligned = defaultdict(set)
    for orpha, omim in exact_pairs:
        aligned[omim].add(orpha)
        aligned[orpha].add(omim)
    ids = set(disease_ids)
    for d in list(ids):
        ids |= aligned.get(d, set())
    return sorted(ids, key=lambda i: (not i.startswith("OMIM:"), i))


def profile(kb: dict, ids: list[str], ontology: Ontology) -> dict[str, float | None]:
    """Phenotypic-abnormality terms of the merged profile; a term takes the first known frequency."""
    out: dict[str, float | None] = {}
    for d in ids:
        for term, pheno in kb["diseases"].get(d, {}).get("phenotypes", {}).items():
            if not ontology.is_a(term, PHENOTYPIC_ABNORMALITY):
                continue
            if out.get(term) is None:
                out[term] = pheno["freq"]
    return out


class Featurizer:
    def __init__(
        self,
        ontology: Ontology,
        annotations: Counter,
        n_diseases: int,
        reportability: Counter,
        n_patients: int,
        cardinal: set[tuple[str, str]],
    ) -> None:
        self.ontology = ontology
        self.annotations = annotations
        self.n_diseases = n_diseases
        self.reportability = reportability
        self.n_patients = n_patients
        self.cardinal = cardinal

    def row(
        self,
        term: str,
        freq: float | None,
        disease_ids,
        reportability_minus: int = 0,
        patients_minus: int = 0,
    ) -> list[float]:
        c = self.reportability.get(term, 0) - reportability_minus
        n = self.n_patients - patients_minus
        return [
            0.0 if freq is None else freq,
            float(freq is None),
            -math.log((self.annotations.get(term, 0) + 1) / (self.n_diseases + 1)),
            float(len(self.ontology.ancestors(term))),
            math.log((c + 1) / (n + 1)),
            float(any((d, term) in self.cardinal for d in disease_ids)),
        ]


def training_rows(
    cases: list[Case],
    groups: dict[str, str],
    kb: dict,
    featurizer: Featurizer,
    exact_pairs: list[tuple[str, str]],
) -> tuple[np.ndarray, np.ndarray, list[str], dict]:
    """(X, y, gene per row, stats); reportability leaves out each patient's publication group."""
    ontology = featurizer.ontology
    by_group: dict[str, Counter] = defaultdict(Counter)
    group_size: Counter = Counter()
    closures = {}
    for case in cases:
        closures[case.case_id] = closure(case.present, ontology)
        by_group[groups[case.case_id]].update(closures[case.case_id])
        group_size[groups[case.case_id]] += 1
    X, y, genes = [], [], []
    patients = 0
    for case in cases:
        ids = entity_ids(case.disease_ids, exact_pairs)
        terms = profile(kb, ids, ontology)
        if not terms:
            continue
        patients += 1
        g = groups[case.case_id]
        for term, freq in sorted(terms.items()):
            X.append(featurizer.row(term, freq, ids, by_group[g].get(term, 0), group_size[g]))
            y.append(float(term in closures[case.case_id]))
            genes.append(case.gene)
    stats = {"patients": len(cases), "patients_with_profile": patients, "rows": len(y)}
    return np.asarray(X), np.asarray(y), genes, stats


def fit(X: np.ndarray, y: np.ndarray, columns: tuple[int, ...]) -> dict:
    """L2-light logistic regression on standardised columns; coefficients returned on the raw scale."""
    Z = X[:, columns]
    mean, sd = Z.mean(axis=0), Z.std(axis=0)
    sd[sd == 0] = 1.0
    S = (Z - mean) / sd
    A = np.hstack([np.ones((len(S), 1)), S])

    def loss(w):
        z = A @ w
        nll = np.logaddexp(0.0, z) - y * z
        p = 1 / (1 + np.exp(-z))
        grad = A.T @ (p - y) / len(y) + L2 * np.r_[0.0, w[1:]]
        return nll.mean() + 0.5 * L2 * (w[1:] @ w[1:]), grad

    result = minimize(loss, np.zeros(A.shape[1]), jac=True, method="L-BFGS-B")
    w = result.x
    coef = w[1:] / sd
    intercept = w[0] - float(coef @ mean)
    return {
        "intercept": float(intercept),
        "coef": [float(c) for c in coef],
        "converged": bool(result.success),
    }


def logit(model: dict, X: np.ndarray, columns: tuple[int, ...]) -> np.ndarray:
    return model["intercept"] + X[:, columns] @ np.asarray(model["coef"])


def log_loss(y: np.ndarray, z: np.ndarray) -> float:
    return float(np.mean(np.logaddexp(0.0, z) - y * z))


def auc(y: np.ndarray, score: np.ndarray) -> float:
    """Mann-Whitney AUC with tied scores sharing their average rank."""
    from scipy.stats import rankdata

    y = np.asarray(y)
    ranks = rankdata(score)
    pos = y == 1
    n_pos, n_neg = int(pos.sum()), int((~pos).sum())
    return float((ranks[pos].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def spearman(a, b) -> float:
    from scipy.stats import spearmanr

    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return float("nan")
    return float(spearmanr(a, b).statistic)


def gene_level_rho(
    cases: list[Case],
    knowledge_genes,
    kb: dict,
    featurizer: Featurizer,
    models: dict[str, tuple[dict, tuple[int, ...]]],
    min_patients: int = 5,
) -> dict:
    """Mean within-gene Spearman(score, real reporting rate) over genes with >= min_patients patients.

    Per gene the terms are its diseases' profile terms (masked KB); a term's frequency is the
    weight-averaged known frequency over the diseases annotating it, and its reportability is the
    full R1-train count. `knowledge_genes` maps a patient's gene to {disease id: weight}.
    """
    ontology = featurizer.ontology
    by_gene: dict[str, list[set[str]]] = defaultdict(list)
    for case in cases:
        by_gene[case.gene].append(closure(case.present, ontology))
    per_model: dict[str, list[float]] = {name: [] for name in models}
    genes_used = 0
    for gene, closures in sorted(by_gene.items()):
        diseases = knowledge_genes(gene)
        if len(closures) < min_patients or not diseases:
            continue
        num: dict[str, float] = defaultdict(float)
        den: dict[str, float] = defaultdict(float)
        terms: set[str] = set()
        for d, w in diseases.items():
            for term, freq in profile(kb, [d], ontology).items():
                terms.add(term)
                if freq is not None:
                    num[term] += w * freq
                    den[term] += w
        if len(terms) < 3:
            continue
        ordered = sorted(terms)
        X = np.asarray(
            [featurizer.row(t, num[t] / den[t] if den[t] else None, list(diseases)) for t in ordered]
        )
        rate = [sum(t in c for c in closures) / len(closures) for t in ordered]
        genes_used += 1
        for name, (model, columns) in models.items():
            per_model[name].append(spearman(logit(model, X, columns), rate))
    return {
        "genes": genes_used,
        "min_patients": min_patients,
        "mean_rho": {name: float(np.nanmean(v)) if v else None for name, v in per_model.items()},
    }


def term_budget(cases: list[Case]) -> dict:
    sizes = [len(c.present) for c in cases]
    hist = Counter(sizes)
    return {
        "definition": "number of present (reported) terms per R1-train case",
        "cases": len(sizes),
        "mean": float(np.mean(sizes)),
        "percentiles": {str(p): float(np.percentile(sizes, p)) for p in (10, 25, 50, 75, 90, 99)},
        "histogram": {str(k): hist[k] for k in sorted(hist)},
    }
