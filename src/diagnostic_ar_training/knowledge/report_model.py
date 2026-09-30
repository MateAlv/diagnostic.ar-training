"""`report-model-*`: which of a patient's true features a clinician writes down (ADR-0011 §3).

A logistic model over (R1-train patient, term of the patient's disease profile) pairs; the
label is whether the patient's report contains the term or a descendant of it. Profiles
come from a KB that masks every R1 publication, so a patient's own paper never shaped the
frequency it is scored with (ANALYSIS-001 §3.2).
"""

import math
from collections import Counter, defaultdict
from collections.abc import Callable

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


def gene_frequencies(kb: dict, diseases: dict[str, float], ontology: Ontology) -> dict[str, float | None]:
    """{term: P(term | gene)}: the disease-weight mixture of known frequencies; None if none is known."""
    mix: dict[str, float] = defaultdict(float)
    known, terms = set(), set()
    for d, w in diseases.items():
        for term, freq in profile(kb, [d], ontology).items():
            terms.add(term)
            if freq is not None:
                mix[term] += w * freq
                known.add(term)
    return {t: (mix[t] if t in known else None) for t in terms}


Scorer = Callable[[str, float | None, bool], float]


def gene_level_rho(
    cases: list[Case],
    knowledge_genes,
    kb: dict,
    ontology: Ontology,
    cardinal: set[tuple[str, str]],
    scorers: dict[str, Scorer],
    min_patients: int = 5,
) -> dict:
    """Mean within-gene Spearman(score, real reporting rate) over genes with >= min_patients patients.

    Per gene the terms are its diseases' profile terms (masked KB), with P(term | gene) as the
    frequency (`gene_frequencies`); a term is cardinal if it is for any of the gene's diseases.
    `knowledge_genes` maps a patient's gene to {disease id: weight}; a scorer maps
    (term, frequency, cardinal) to a logit.
    """
    by_gene: dict[str, list[set[str]]] = defaultdict(list)
    for case in cases:
        by_gene[case.gene].append(closure(case.present, ontology))
    per_model: dict[str, list[float]] = {name: [] for name in scorers}
    genes_used = 0
    for gene, closures in sorted(by_gene.items()):
        diseases = knowledge_genes(gene)
        if len(closures) < min_patients or not diseases:
            continue
        freqs = gene_frequencies(kb, diseases, ontology)
        if len(freqs) < 3:
            continue
        ordered = sorted(freqs)
        rate = [sum(t in c for c in closures) / len(closures) for t in ordered]
        flags = [any((d, t) in cardinal for d in diseases) for t in ordered]
        genes_used += 1
        for name, score in scorers.items():
            values = [score(t, freqs[t], flag) for t, flag in zip(ordered, flags, strict=True)]
            per_model[name].append(spearman(values, rate))
    return {
        "genes": genes_used,
        "min_patients": min_patients,
        "frequency": "P(term | gene): disease-weight mixture of the masked KB's known frequencies",
        "mean_rho": {name: float(np.nanmean(v)) if v else None for name, v in per_model.items()},
    }


def internal_scorer(featurizer: "Featurizer", model: dict, columns: tuple[int, ...]) -> Scorer:
    def score(term: str, freq: float | None, cardinal: bool) -> float:
        row = featurizer.row(term, freq, [])
        row[FEATURES.index("cardinal")] = float(cardinal)
        return float(logit(model, np.asarray([row]), columns)[0])

    return score


def to_simulator_format(
    artifact_id: str,
    model: dict,
    annotations: Counter,
    n_diseases: int,
    reportability: Counter,
    n_patients: int,
    budget: dict,
    provenance: dict,
    notes: str,
) -> dict:
    """The fitted model in rare-disease-simulator's `report-model` format, version 1.

    The simulator's `frequency` feature has one value for unknown frequencies; this model's
    `frequency_unknown` indicator is folded into it as `unknown_value = c_unknown / c_frequency`,
    which gives the same logit.
    """
    coef = dict(zip(FEATURES, model["coef"], strict=True))
    unknown_value = coef["frequency_unknown"] / coef["frequency"] if coef["frequency"] else math.nan
    if not 0.0 <= unknown_value <= 1.0:
        raise ValueError(f"frequency_unknown cannot be folded into [0, 1]: {unknown_value}")
    missing_ic = -math.log(1 / (n_diseases + 1))
    return {
        "format": "report-model",
        "format_version": 1,
        "artifact_id": artifact_id,
        "link": "logistic",
        "intercept": model["intercept"],
        "features": [
            {"name": "frequency", "kind": "frequency", "coefficient": coef["frequency"],
             "unknown_value": unknown_value, "description": DEFINITIONS["frequency"]
             + "; unknown_value folds in the frequency_unknown indicator"},
            {"name": "information_content", "kind": "information_content",
             "coefficient": coef["information_content"], "source": "table", "missing_value": missing_ic,
             "description": DEFINITIONS["information_content"]},
            {"name": "ancestor_count", "kind": "ancestor_count", "coefficient": coef["ancestor_count"],
             "include_self": False, "description": DEFINITIONS["ancestor_count"]},
            {"name": "log_reportability", "kind": "log_reportability",
             "coefficient": coef["log_reportability"], "pseudocount": 1.0, "normalize": True,
             "description": DEFINITIONS["log_reportability"]},
            {"name": "cardinal", "kind": "cardinal_flag", "coefficient": coef["cardinal"],
             "description": DEFINITIONS["cardinal"]},
        ],
        "tables": {
            "information_content": {
                t: -math.log((a + 1) / (n_diseases + 1)) for t, a in sorted(annotations.items()) if a
            }
        },
        "reportability": {
            "closure": "ancestors",
            "patients": n_patients,
            "counts": {t: c for t, c in sorted(reportability.items()) if c},
        },
        "term_budget": {"histogram": budget["histogram"], "description": budget["definition"]},
        "provenance": provenance,
        "notes": notes,
    }  # fmt: skip


def simulator_scorer(body: dict, ontology: Ontology) -> Scorer:
    """A term's logit under a `report-model` file, as rare-disease-simulator computes it."""
    ic_table = body["tables"].get("information_content", {})
    counts = body["reportability"]["counts"]
    patients = body["reportability"]["patients"]

    def value(f: dict, term: str, freq: float | None, cardinal: bool) -> float:
        kind = f["kind"]
        if kind == "frequency":
            return freq if freq is not None else f["unknown_value"]
        if kind == "information_content":
            return ic_table.get(term, f["missing_value"])
        if kind == "ancestor_count":
            return len(ontology.ancestors(term)) + (1 if f["include_self"] else 0)
        if kind == "log_reportability":
            v = math.log(counts.get(term, 0) + f["pseudocount"])
            return v - math.log(patients + f["pseudocount"]) if f["normalize"] else v
        if kind == "cardinal_flag":
            return float(cardinal)
        raise ValueError(f"unknown feature kind {kind!r}")

    def score(term: str, freq: float | None, cardinal: bool) -> float:
        total = body["intercept"]
        for f in body["features"]:
            total += (
                f["coefficient"]
                * (value(f, term, freq, cardinal) - f.get("center", 0.0))
                / f.get("scale", 1.0)
            )
        return total

    return score


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
