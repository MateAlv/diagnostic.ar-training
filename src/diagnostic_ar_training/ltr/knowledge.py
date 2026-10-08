"""Build the ltr-v1 knowledge (`ltr-kb/1`, ltr/bundle.py `Knowledge`) from a rerank KB and a safe-v1 bundle.

Both inputs must mask every r1-v1 publication (scope `all`), so that a train patient's features never come
from annotations curated from their own paper, and train and dev features come from the same knowledge
(PHASE2.md Track 2).
"""

import math
from collections import Counter
from collections.abc import Iterable

from diagnostic_ar_training.ltr.bundle import EPSILON, KB_FORMAT, UNKNOWN_FREQUENCY, XL, XLD, XLR, Knowledge
from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology


def _lenient_onset(diseases: dict, ids: Iterable[str]) -> float | None:
    """Lowest onset lower bound among the gene's diseases with onset data (any disease suffices)."""
    lows = [lo for d in ids for lo, _ in diseases[d]["onset_years"]]
    return max(min(lows), 0.0) if lows else None


def _inheritance(diseases: dict, ids: Iterable[str]) -> set[str]:
    return {t for d in ids for t in diseases[d]["inheritance"]}


def build(
    rerank_kb: dict, safe_bundle: dict, ontology: Ontology, vocabulary: Iterable[str]
) -> tuple[dict, dict]:
    """(knowledge, stats); plain JSON-serialisable and deterministic."""
    if rerank_kb.get("schema") != 2:
        raise ValueError("needs a schema-2 rerank KB (kb-v3 or later)")
    kb_diseases = rerank_kb["diseases"]
    aliases = rerank_kb.get("vocabulary", {})
    genes, used = {}, set()
    for symbol in sorted(set(vocabulary)):
        weights = rerank_kb["genes"].get(aliases.get(symbol) or symbol, {})
        record: dict = {"diseases": dict(sorted(weights.items()))}
        if weights:
            used.update(weights)
            lenient = _lenient_onset(kb_diseases, weights)
            if lenient is not None:
                record["lenient_onset_years"] = lenient
            inheritance = _inheritance(kb_diseases, weights)
            if inheritance and inheritance <= {XLR, XL}:
                record["xlr_only"] = True
            if inheritance == {XLD}:
                record["xld_only"] = True
        genes[symbol] = record
    diseases = {
        d: [[t, p["freq"]] for t, p in sorted(kb_diseases[d]["phenotypes"].items())] for d in sorted(used)
    }

    phenotype_terms = sorted(ontology.descendants(PHENOTYPIC_ABNORMALITY) | {PHENOTYPIC_ABNORMALITY})
    parents = {t: list(ontology.parents(t)) for t in phenotype_terms}
    resolve = {}
    for old in sorted(set(ontology._alt_ids) | set(ontology.obsolete)):
        current = ontology.resolve(old)
        if current and current != old and current in parents:
            resolve[old] = current
    kb = {
        "format": KB_FORMAT,
        "epsilon": EPSILON,
        "unknown_frequency": UNKNOWN_FREQUENCY,
        "genes": genes,
        "diseases": diseases,
        "parents": parents,
        "resolve": resolve,
        "ic": {},
        "background": {},
        "safe": safe_bundle,
    }

    # Information content over the diseases the vocabulary reaches, then the background P(term | gene).
    engine = Knowledge(kb)
    counts: Counter = Counter()
    for d in diseases:
        counts.update(engine.disease_profile(d)[0].keys())
    n = len(diseases)
    kb["ic"] = {t: round(-math.log(c / n), 6) for t, c in sorted(counts.items())}
    total: Counter = Counter()
    for symbol in genes:
        for t, p in engine.gene_profile(symbol)[0].items():
            total[t] += p
    kb["background"] = {t: round(v / len(genes), 9) for t, v in sorted(total.items())}

    stats = {
        "genes": len(genes),
        "genes_with_knowledge": sum(bool(r["diseases"]) for r in genes.values()),
        "diseases": n,
        "annotations": sum(len(v) for v in diseases.values()),
        "phenotype_terms": len(parents),
        "resolvable_old_ids": len(resolve),
        "terms_with_ic": len(kb["ic"]),
        "genes_lenient_onset": sum("lenient_onset_years" in r for r in genes.values()),
        "genes_xlr_only": sum(bool(r.get("xlr_only")) for r in genes.values()),
        "genes_xld_only": sum(bool(r.get("xld_only")) for r in genes.values()),
        "safe_kb_id": safe_bundle["kb_id"],
        "safe_sex_limited": sum("sex" in r for r in safe_bundle["genes"].values()),
        "safe_strict_onset": sum("earliest_onset_years" in r for r in safe_bundle["genes"].values()),
        "safe_negatable": len(safe_bundle["obligate"]),
    }
    return kb, stats
