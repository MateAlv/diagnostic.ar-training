"""What real patients look like, measured on R1-train only, as targets for the simulator.

Two reference choices, both meant to make "explained by the gene" mean what it would
for a new patient:
- all R1-train patients against a KB that masks every R1 publication (calib-v1);
- R1-train patients whose publications the pinned HPOA does not cite, against a KB
  that keeps R1-train's annotations as the simulator's profiles do (ADR-0011
  amendment 4, calib-v2).
"""

import math
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.features import GeneKnowledge

POPULATIONS = ("all", "uncited")
VOCABULARY_RULES = ("unexplained", "related_or_weak")
CATEGORIES = ("explained", "more_specific", "related_ic_ge_2", "weak_ic_lt_2")
RELATED_MIN_IC = 2.0


def cited_pmids(hpoa_path: Path) -> set[str]:
    """Bare PMIDs cited anywhere in a `phenotype.hpoa` (the ANALYSIS-002 rule)."""
    cited: set[str] = set()
    with Path(hpoa_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("#"):
                cited.update(re.findall(r"PMID:(\d+)", line))
    return cited


def is_cited(case: Case, cited: set[str]) -> bool:
    return bool({p.replace("PMID:", "") for p in case.pmids} & cited)


def select_population(cases: Iterable[Case], population: str, cited: set[str] | None = None) -> list[Case]:
    if population not in POPULATIONS:
        raise ValueError(f"unknown population {population!r}")
    if population == "all":
        return list(cases)
    if cited is None:
        raise ValueError("the uncited population needs the cited PMIDs")
    return [c for c in cases if not is_cited(c, cited)]


class TermCategories:
    """ANALYSIS-002 categories of a present term against a gene's KB annotations.

    explained: the gene's diseases give it probability > 0; more_specific: a descendant of an
    annotated term; otherwise related (IC >= 2) or weak (IC < 2), by the information content of the
    most informative ancestor it shares with an annotated term.
    """

    def __init__(self, kb: dict, knowledge: GeneKnowledge, ontology: Ontology) -> None:
        self.knowledge, self.ontology, self.diseases = knowledge, ontology, kb["diseases"]
        counts: Counter = Counter()
        for d in self.diseases.values():
            closure = set()
            for t in d["phenotypes"]:
                closure.add(t)
                closure |= ontology.ancestors(t)
            counts.update(closure)
        self.counts, self.n = counts, len(self.diseases)
        self._annotated: dict[str, set[str]] = {}

    def ic(self, term: str) -> float:
        return -math.log(max(self.counts.get(term, 0), 1) / self.n)

    def annotated(self, gene: str) -> set[str]:
        if gene not in self._annotated:
            self._annotated[gene] = {
                t for d in self.knowledge.diseases(gene) for t in self.diseases[d]["phenotypes"]
            }
        return self._annotated[gene]

    def classify(self, gene: str, term: str) -> str:
        t = self.ontology.resolve(term) or term
        if self.knowledge.term_probability(gene, t) > 0:
            return "explained"
        annotated = self.annotated(gene)
        ancestors = self.ontology.ancestors(t)
        if ancestors & annotated:
            return "more_specific"
        best = 0.0
        own = ancestors | {t}
        for a in annotated:
            common = own & (self.ontology.ancestors(a) | {a})
            if common:
                best = max(best, max(self.ic(c) for c in common))
        return "related_ic_ge_2" if best >= RELATED_MIN_IC else "weak_ic_lt_2"


def _distribution(values: list[int]) -> dict:
    arr = np.asarray(values)
    return {
        "mean": float(arr.mean()),
        "share_zero": float((arr == 0).mean()),
        "percentiles": {str(p): float(np.percentile(arr, p)) for p in (10, 25, 50, 75, 90)},
    }


def measure(
    cases: list[Case],
    knowledge: GeneKnowledge,
    min_noise_count: int = 2,
    categories: TermCategories | None = None,
    vocabulary: str = "unexplained",
) -> tuple[dict, list[tuple]]:
    """Returns (targets, noise vocabulary rows (hpo_id, patients, weight)).

    `vocabulary` picks the terms the noise vocabulary is drawn from: every unexplained present term
    (calib-v1), or only the related and weak ones, leaving more specific terms to the simulator's
    specialisation (`related_or_weak`, needs `categories`). With `categories`, the targets add the
    category shares and `noise_share`, the share of present terms that are related or weak.
    """
    if vocabulary not in VOCABULARY_RULES:
        raise ValueError(f"unknown vocabulary rule {vocabulary!r}")
    if vocabulary == "related_or_weak" and categories is None:
        raise ValueError("the related_or_weak vocabulary needs term categories")
    in_kb = [c for c in cases if knowledge.diseases(c.gene)]
    own = other = 0
    unexplained_per_case = []
    noise: Counter = Counter()
    tally: Counter = Counter()
    for case in in_kb:
        for term in case.excluded:
            if knowledge.term_probability(case.gene, term) > 0:
                own += 1
            else:
                other += 1
        unexplained = {t for t in case.present if knowledge.term_probability(case.gene, t) == 0}
        unexplained_per_case.append(len(unexplained))
        if categories is None:
            noise.update(unexplained)
            continue
        kinds = {t: categories.classify(case.gene, t) for t in case.present}
        tally.update(kinds.values())
        if vocabulary == "related_or_weak":
            noise.update(t for t, k in kinds.items() if k in ("related_ic_ge_2", "weak_ic_lt_2"))
        else:
            noise.update(unexplained)
    n = len(cases)
    targets = {
        "cases": n,
        "cases_with_gene_in_kb": len(in_kb),
        "present_per_case": _distribution([len(c.present) for c in cases]),
        "excluded_per_case": _distribution([len(c.excluded) for c in cases]),
        "excluded_annotated_to_own_gene_share": own / (own + other) if own + other else None,
        "unexplained_present_per_case": _distribution(unexplained_per_case),
        "unexplained_present_share": sum(unexplained_per_case) / max(1, sum(len(c.present) for c in in_kb)),
        "missing": {
            "sex": sum(c.sex == Sex.UNKNOWN for c in cases) / n,
            "age": sum(c.age_years is None for c in cases) / n,
            "onset": sum(c.onset_years is None and c.onset_term is None for c in cases) / n,
            "excluded": sum(not c.excluded for c in cases) / n,
        },
    }
    if categories is not None:
        terms = sum(tally.values())
        shares = {k: tally[k] / terms if terms else 0.0 for k in CATEGORIES}
        targets["categories"] = {"terms": terms, **shares}
        targets["noise_share"] = shares["related_ic_ge_2"] + shares["weak_ic_lt_2"]
        targets["related_share_of_noise"] = (
            shares["related_ic_ge_2"] / targets["noise_share"] if targets["noise_share"] else None
        )
    # Terms seen once are more likely one paper's idiosyncrasy than a recurring pattern.
    kept = {t: k for t, k in noise.items() if k >= min_noise_count}
    total = sum(kept.values())
    rows = sorted(((t, k, k / total) for t, k in kept.items()), key=lambda r: (-r[1], r[0]))
    targets["noise_vocabulary"] = {
        "terms": len(rows),
        "min_patients": min_noise_count,
        "dropped_singletons": len(noise) - len(kept),
        "rule": vocabulary,
    }
    return targets, rows
