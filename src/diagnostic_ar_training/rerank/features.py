"""B2 features: how compatible a gene is with a patient's negated symptoms, sex, age and onset.

Every feature is a log-likelihood ratio against "no information" and is
exactly 0 when its input is absent or the gene has no knowledge about it, so a
re-ranker built on them is the identity for cases without the new inputs.
Parameters are fixed in FeatureParams and pre-registered in EXP-B-001.
"""

import bisect
import math
from dataclasses import dataclass
from functools import lru_cache

from diagnostic_ar_training.cohorts.schema import Case, Sex
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.kb import HPO_ONSET_YEARS

# P(patient is male | disease) by mode of inheritance; first matching term wins.
MALE_SHARE = (
    ("HP:0001475", 0.99),  # male-limited expression
    ("HP:0034344", 0.01),  # female-limited expression
    ("HP:0001450", 0.99),  # Y-linked
    ("HP:0001419", 0.9),  # X-linked recessive
    ("HP:0001423", 0.33),  # X-linked dominant: affected females outnumber males about 2:1
    ("HP:0001417", 0.7),  # X-linked, unspecified
)
# Onset bins (years): prenatal, neonatal, infantile, early childhood, childhood, young adult, adult, late.
ONSET_BIN_EDGES = (0.0, 28 / 365.25, 1.0, 5.0, 15.0, 40.0, 60.0)


# How the negated symptoms are turned into the neg_llr component (EXP-B-004, L1).
NEG_FORMS = ("llr", "gated", "capped", "propagated")


@dataclass(frozen=True)
class FeatureParams:
    neg_strength: float = 0.5
    unknown_frequency: float = 0.3
    epsilon: float = 0.01
    onset_smoothing: float = 0.1
    neg_form: str = "llr"
    neg_tau: float | None = None
    neg_cap: float | None = None

    def __post_init__(self) -> None:
        if self.neg_form not in NEG_FORMS:
            raise ValueError(f"neg_form must be one of {NEG_FORMS}, got {self.neg_form!r}")
        if not 0.0 <= self.neg_strength < 1.0:
            raise ValueError("neg_strength must be in [0, 1)")
        if self.neg_form == "gated" and (self.neg_tau is None or not 0.0 <= self.neg_tau <= 1.0):
            raise ValueError("neg_form 'gated' needs neg_tau in [0, 1]")
        if self.neg_form == "capped" and (self.neg_cap is None or self.neg_cap <= 0):
            raise ValueError("neg_form 'capped' needs neg_cap > 0")
        if self.neg_form != "gated" and self.neg_tau is not None:
            raise ValueError("neg_tau only applies to neg_form 'gated'")
        if self.neg_form != "capped" and self.neg_cap is not None:
            raise ValueError("neg_cap only applies to neg_form 'capped'")


def onset_bin(years: float) -> int:
    return bisect.bisect_right(ONSET_BIN_EDGES, years) if years >= 0 else 0


N_BINS = len(ONSET_BIN_EDGES) + 1


def _interval_bins(lo: float, hi: float) -> list[float]:
    """Share of an age interval falling in each onset bin (a point interval puts all in one bin)."""
    out = [0.0] * N_BINS
    if hi <= lo:
        out[onset_bin(lo)] = 1.0
        return out
    edges = (-math.inf, *ONSET_BIN_EDGES, math.inf)
    for b in range(N_BINS):
        overlap = max(0.0, min(hi, edges[b + 1]) - max(lo, edges[b]))
        out[b] = overlap / (hi - lo)
    return out


class GeneKnowledge:
    def __init__(self, kb: dict, ontology: Ontology, params: FeatureParams = FeatureParams()) -> None:
        if kb.get("schema") != 2:
            raise ValueError("features need a schema-2 KB (kb-v3 or later)")
        self.kb = kb
        self.ontology = ontology
        self.params = params
        self.vocabulary = kb.get("vocabulary", {})
        with_onset = [self._disease_onset(d) for d in kb["diseases"] if kb["diseases"][d]["onset_years"]]
        self.onset_background = [sum(col) / len(with_onset) for col in zip(*with_onset, strict=True)]

    def diseases(self, gene: str) -> dict[str, float]:
        return self.kb["genes"].get(self.vocabulary.get(gene, gene), {})

    @lru_cache(maxsize=16384)  # noqa: B019 -- one instance per run
    def _propagated(self, disease_id: str, sex: str | None) -> dict[str, float]:
        """P(t | disease) for every term the disease annotates, directly or through a descendant.

        With `sex`, annotations restricted to the other sex are left out.
        """
        absent: dict[str, float] = {}
        for term, pheno in self.kb["diseases"][disease_id]["phenotypes"].items():
            if sex is not None and pheno["sex"] not in (None, sex):
                continue
            f = pheno["freq"] if pheno["freq"] is not None else self.params.unknown_frequency
            for t in (term, *self.ontology.ancestors(term)):
                absent[t] = absent.get(t, 1.0) * (1.0 - f)
        return {t: 1.0 - a for t, a in absent.items()}

    def term_probability(self, gene: str, term: str, sex: str | None = None) -> float:
        return sum(w * self._propagated(d, sex).get(term, 0.0) for d, w in self.diseases(gene).items())

    def male_share(self, gene: str) -> float | None:
        ds = self.diseases(gene)
        if not ds:
            return None
        total = 0.0
        for d, w in ds.items():
            inheritance = set(self.kb["diseases"][d]["inheritance"])
            share = next((s for term, s in MALE_SHARE if term in inheritance), 0.5)
            total += w * share
        return total

    @lru_cache(maxsize=16384)  # noqa: B019
    def _disease_onset(self, disease_id: str) -> tuple[float, ...]:
        intervals = self.kb["diseases"][disease_id]["onset_years"]
        bins = [_interval_bins(lo, hi) for lo, hi in intervals]
        return tuple(sum(col) / len(bins) for col in zip(*bins, strict=True))

    def onset_distribution(self, gene: str) -> list[float] | None:
        """Mixture over the gene's diseases; diseases without onset data contribute the background."""
        ds = self.diseases(gene)
        known = [d for d in ds if self.kb["diseases"][d]["onset_years"]]
        if not known:
            return None
        a = self.params.onset_smoothing
        out = [0.0] * N_BINS
        for d, w in ds.items():
            dist = self._disease_onset(d) if self.kb["diseases"][d]["onset_years"] else self.onset_background
            for b in range(N_BINS):
                out[b] += w * ((1 - a) * dist[b] + a / N_BINS)
        return out

    def onset_before_any(self, gene: str, age: float) -> float | None:
        """Like onset_before, but a disease fits if ANY listed onset class fits (EXP-B-001 Add. 3)."""
        ds = self.diseases(gene)
        if not any(self.kb["diseases"][d]["onset_years"] for d in ds):
            return None
        total = 0.0
        for d, w in ds.items():
            intervals = self.kb["diseases"][d]["onset_years"]
            if not intervals:
                total += w
                continue
            total += w * max(
                1.0 if age >= hi else (0.0 if age < lo else (age - lo) / (hi - lo)) for lo, hi in intervals
            )
        return total

    def onset_before(self, gene: str, age: float) -> float | None:
        """P(onset <= age | gene); diseases without onset data are taken as compatible."""
        ds = self.diseases(gene)
        if not any(self.kb["diseases"][d]["onset_years"] for d in ds):
            return None
        total = 0.0
        for d, w in ds.items():
            intervals = self.kb["diseases"][d]["onset_years"]
            if not intervals:
                total += w
                continue
            share = 0.0
            for lo, hi in intervals:
                share += 1.0 if age >= hi else (0.0 if age < lo else (age - lo) / (hi - lo))
            total += w * share / len(intervals)
        return total


def case_onset_years(case: Case) -> float | None:
    if case.onset_years is not None:
        return case.onset_years
    if case.onset_term in HPO_ONSET_YEARS:
        lo, hi = HPO_ONSET_YEARS[case.onset_term]
        return (lo + hi) / 2
    return None


def _most_general(ontology: Ontology, terms: tuple[str, ...]) -> set[str]:
    """Excluded terms with no excluded ancestor: a "no" to a parent already covers its children."""
    listed = set(terms)
    return {t for t in listed if not ontology.ancestors(t) & listed}


def negation(knowledge: GeneKnowledge, case: Case, gene: str) -> tuple[float, float]:
    """(penalty, annotated share) for the case's excluded terms under knowledge.params.neg_form.

    The penalty is a sum of log(1 - k * P(t | gene)) <= 0. P(t | gene) already includes every
    descendant of t (see GeneKnowledge._propagated), so in every form a "no" to a parent counts
    against genes annotating only a child. "llr" is rr-v1 and is the reference for the others:
    - gated: only terms with P(t | gene) >= neg_tau count;
    - capped: the total is floored at -neg_cap;
    - propagated: only the most general excluded terms count, so a parent and its excluded
      child are not both charged for the same annotation.
    """
    p = knowledge.params
    probs = [knowledge.term_probability(gene, term) for term in case.excluded]
    keep = [True] * len(probs)
    if p.neg_form == "gated":
        keep = [prob >= p.neg_tau for prob in probs]
    elif p.neg_form == "propagated":
        general = _most_general(knowledge.ontology, case.excluded)
        seen: set[str] = set()
        keep = []
        for term in case.excluded:
            keep.append(term in general and term not in seen)
            seen.add(term)
    total = 0.0
    for prob, k in zip(probs, keep, strict=True):
        if k:
            total += math.log(1.0 - p.neg_strength * prob)
    if p.neg_form == "capped":
        total = max(total, -p.neg_cap)
    annotated = sum(prob > 0 for prob in probs)
    return total, annotated / len(probs) if probs else 0.0


COMPONENTS = ("neg_llr", "neg_annotated_share", "sex_prior", "sex_restricted", "age_mean", "age_any", "onset")


def components(knowledge: GeneKnowledge, case: Case, gene: str) -> dict[str, float]:
    """The pieces rr-v1 sums and rr-v2 weighs separately; each is 0 without its input."""
    p = knowledge.params
    out = dict.fromkeys(COMPONENTS, 0.0)
    if not knowledge.diseases(gene):
        return out

    if case.excluded:
        out["neg_llr"], out["neg_annotated_share"] = negation(knowledge, case, gene)

    if case.sex != Sex.UNKNOWN:
        sex = case.sex.value
        share = knowledge.male_share(gene)
        prior = share if case.sex == Sex.MALE else 1.0 - share
        out["sex_prior"] = math.log(max(p.epsilon, prior) / 0.5)
        # A present finding the gene explains only through annotations restricted to the other sex.
        for term in case.present:
            any_sex = knowledge.term_probability(gene, term)
            if any_sex > 0:
                same_sex = knowledge.term_probability(gene, term, sex)
                out["sex_restricted"] += math.log(max(p.epsilon, same_sex / any_sex))

    if case.age_years is not None:
        before = knowledge.onset_before(gene, case.age_years)
        if before is not None:
            out["age_mean"] = math.log(max(p.epsilon, before))
            out["age_any"] = math.log(max(p.epsilon, knowledge.onset_before_any(gene, case.age_years)))

    onset = case_onset_years(case)
    if onset is not None:
        dist = knowledge.onset_distribution(gene)
        if dist is not None:
            b = onset_bin(onset)
            background = (1 - p.onset_smoothing) * knowledge.onset_background[b] + p.onset_smoothing / N_BINS
            out["onset"] = math.log(dist[b] / background)
    return out


def features(knowledge: GeneKnowledge, case: Case, gene: str) -> dict[str, float]:
    """rr-v1's four features (EXP-B-001), as sums of the components."""
    c = components(knowledge, case, gene)
    return {
        "neg": c["neg_llr"],
        "sex": c["sex_prior"] + c["sex_restricted"],
        "age": c["age_mean"],
        "onset": c["onset"],
    }
