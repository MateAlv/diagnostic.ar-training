"""Which HPO terms make the patient's onset age informative about the gene (knowledge-based).

For a term t, candidate genes are those whose diseases annotate t (or a descendant), weighted by
P(t | g) under a uniform gene prior. Each gene carries the onset distribution the `onset` feature uses
(`GeneKnowledge.onset_distribution`). The score is the mutual information, in bits, between the gene
and the onset bin among candidates that explain t.
"""

from collections import defaultdict

import numpy as np

from diagnostic_ar_training.rerank.features import GeneKnowledge

PHENOTYPIC_ABNORMALITY = "HP:0000118"


def mutual_information_bits(weights: np.ndarray, onset: np.ndarray) -> float:
    """I(gene; bin) for p(g) proportional to `weights` and p(bin | g) = onset[g] (rows sum to 1)."""
    pg = weights / weights.sum()
    joint = pg[:, None] * onset
    pb = joint.sum(axis=0)
    expected = pg[:, None] * pb[None, :]
    nz = joint > 0
    return float((joint[nz] * np.log2(joint[nz] / expected[nz])).sum())


def score_terms(knowledge: GeneKnowledge, min_genes: int = 3) -> dict[str, dict]:
    """term -> {"score_bits", "n_genes"} for terms under Phenotypic abnormality with enough genes."""
    onset: dict[str, np.ndarray] = {}
    per_term: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for gene in knowledge.kb["genes"]:
        dist = knowledge.onset_distribution(gene)
        if dist is None:
            continue
        onset[gene] = np.asarray(dist) / sum(dist)
        probs: dict[str, float] = defaultdict(float)
        for disease, w in knowledge.diseases(gene).items():
            for term, p in knowledge._propagated(disease, None).items():
                probs[term] += w * p
        for term, p in probs.items():
            if p > 0:
                per_term[term].append((gene, p))
    ontology = knowledge.ontology
    out = {}
    for term, rows in per_term.items():
        if term == PHENOTYPIC_ABNORMALITY or len(rows) < min_genes:
            continue
        if PHENOTYPIC_ABNORMALITY not in ontology.ancestors(term):
            continue
        weights = np.asarray([p for _, p in rows])
        matrix = np.vstack([onset[g] for g, _ in rows])
        out[term] = {"score_bits": mutual_information_bits(weights, matrix), "n_genes": len(rows)}
    return out
