"""The hard sex rule on top of v4 (P4-SEX): genes a patient of the recorded sex cannot have are moved below
every other gene. Unknown sex changes nothing.

- **Knowledge** (`sex-kb/2`, `build`): which genes only one sex can have, from E0's knowledge (HPOA
  2025-03-03, the 2025-03-03 ontology, E0's gene list and gene -> disease links, as `v4.addon.build_kb`) plus
  one declared extra source, HGNC's chromosome locations. The bar is certainty: a gene is limited to a sex
  only when every one of its diseases is, or it lies on the Y chromosome outside the pseudoautosomal regions.
  A disease is limited to a sex by any of:
  - `y_linked_inheritance`: Y-linked is its only inheritance term (male);
  - `names`: its name is a sex-limited condition (`MALE_NAMES`, `FEMALE_NAMES`, safe-v1's lists extended).
    The name must start with it, and every part joined by "with", "with or without", "and" or "/" must be
    sex-limited too: "Heterotaxy ... with male infertility" or "... with or without ovarian failure"
    (safe-v1 matched them anywhere) do not limit;
  - `phenotypes`: each annotated phenotype is a genital or reproductive term (HP:0000078) and at least one
    is in one sex's subtrees (`MALE_TERMS`, `FEMALE_TERMS`).

  It is not limited when it also has evidence for the other sex, or a phenotype in the other sex's subtrees
  (`contradicted`). A gene is never limited when any of its diseases is a difference of sex development
  (name `DSD_NAMES` or a phenotype under `DSD_TERMS`), where the recorded sex can differ from the karyotype,
  nor when it has limits of both sexes (`ambiguous`). X-linked recessive inheritance is not evidence:
  manifesting carriers exist.
- **Rule** (`SexRule`, `block`): pure numpy, usable in production on any score vector (logits or add-on
  scores). Blocked genes keep their order among themselves.
"""

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training import INTERIM_DIR
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.safe import knowledge as safe_knowledge

SCHEMA = "sex-kb/2"
KB_KIND = "sex-kb"
KB_DIR = INTERIM_DIR / "p4-sex"
KB_FILE = "sex-kb.json.gz"
KB_SOURCES = {
    "annotations": "hpo_annotations_2025_03_03",
    "ontology": "hpo_ontology_2025_03_03",
    "genes": "e0_genes_to_phenotype",
    "hgnc": "hgnc",
}
SEXES = ("male", "female")
REASONS = ("y_chromosome", "y_linked_inheritance", "names", "phenotypes")

GENITAL = "HP:0000078"  # Abnormality of the genital system
MALE_TERMS = (
    "HP:0010461",  # Abnormality of the male genitalia
    "HP:0012874",  # Abnormal male reproductive system physiology
    "HP:0012863",  # Abnormal male germ cell morphology
)
FEMALE_TERMS = (
    "HP:0010460",  # Abnormality of the female genitalia
    "HP:0030012",  # Abnormal female reproductive system physiology
    "HP:0033338",  # Abnormal female meiosis
    "HP:0020155",  # Abnormal oocyte morphology
)
DSD_TERMS = (
    "HP:0000062",  # Ambiguous genitalia
    "HP:0000037",  # Male pseudohermaphroditism
    "HP:0010458",  # Female pseudohermaphroditism
    "HP:0000133",  # Gonadal dysgenesis
    "HP:0012244",  # Abnormal sex determination
    "HP:0031170",  # Female fetal virilization
)
MALE_NAMES = re.compile(
    r"sperm|zoospermia|acrosom|flagell|sertoli|anorchia|cryptorchidism|hypospadias|\bmale infertility|"
    r"persistent m[uü]llerian duct|testicular regression|micropenis|vas deferens|prostate cancer|"
    r"chromosome y microdeletion",
    re.I,
)
FEMALE_NAMES = re.compile(
    safe_knowledge.FEMALE_NAMES.pattern + r"|m[uü]llerian aplasia|\bmrkh\b|eclampsia|"
    r"embryo(nic)? (maturation )?arrest",
    re.I,
)
DSD_NAMES = re.compile(
    safe_knowledge.SEX_REVERSAL.pattern
    + r"|sex development|hermaphroditism|ambiguous genitalia|ovotesticular|pseudovaginal",
    re.I,
)
_CONNECTOR = re.compile(r"\bwith(?: or without)?\b|\band\b|/", re.I)
_QUALIFIER = re.compile(r"[\s,.\-]*(?:types?\s+)?[ivx\d]*[\s,.\-]*", re.I)
_LEAD = (
    r"\W*(?:(?:primary|isolated|familial|congenital|hereditary|idiopathic|non-?syndromic|(?:non-?)?obstructive|"
    r"severe|recurrent|[xy]-linked)\s+)*\w*?"
)
NAMES = {"male": MALE_NAMES, "female": FEMALE_NAMES}


def limited_name(name: str, pattern: re.Pattern) -> bool:
    """The name starts with the condition and every joined part is that condition or a bare qualifier."""
    first, *rest = _CONNECTOR.split(name)
    if not re.match(_LEAD + f"(?:{pattern.pattern})", first, re.I):
        return False
    return all(pattern.search(p) or _QUALIFIER.fullmatch(p) for p in rest)


def y_chromosome(location: str) -> bool:
    """On Y and not in a pseudoautosomal region (HGNC writes those as "Xp22.33 and Yp11.32")."""
    return location.startswith("Y") and "X" not in location


def term_classifier(ancestors: Callable[[str], Iterable[str]]) -> Callable[[str], str]:
    """term -> "dsd" | "male" | "female" | "both" | "genital" | "other" by its ancestors (self included)."""
    male, female, dsd = set(MALE_TERMS), set(FEMALE_TERMS), set(DSD_TERMS)
    cache: dict[str, str] = {}

    def classify(term: str) -> str:
        if term not in cache:
            up = set(ancestors(term)) | {term}
            sexes = [s for s, roots in (("male", male), ("female", female)) if up & roots]
            if up & dsd:
                cache[term] = "dsd"
            elif sexes:
                cache[term] = sexes[0] if len(sexes) == 1 else "both"
            else:
                cache[term] = "genital" if GENITAL in up else "other"
        return cache[term]

    return classify


def disease_evidence(
    disease: str, ann: safe_knowledge.Annotations, classify: Callable[[str], str]
) -> dict[str, list[str] | bool]:
    """{"male": reasons, "female": reasons} and flags: "male_terms" / "female_terms" (a phenotype in that
    sex's subtrees), "dsd", "compound_name" (a sex-limited phrase inside a name that does not limit)."""
    name = ann.names.get(disease, "")
    classes = Counter(classify(t) for t, _ in ann.phenotypes.get(disease, ()))
    out: dict = {"male": [], "female": []}
    if ann.inheritance.get(disease) == {safe_knowledge.Y_LINKED}:
        out["male"].append("y_linked_inheritance")
    for sex in SEXES:
        if name and limited_name(name, NAMES[sex]):
            out[sex].append("names")
        if classes[sex] and set(classes) <= {sex, "genital"}:
            out[sex].append("phenotypes")
    out["male_terms"] = bool(classes["male"] or classes["both"])
    out["female_terms"] = bool(classes["female"] or classes["both"])
    out["dsd"] = bool(DSD_NAMES.search(name) or classes["dsd"])
    out["compound_name"] = any(NAMES[s].search(name) and "names" not in out[s] for s in SEXES)
    return out


def disease_limit(evidence: Mapping) -> str | None:
    """The disease's sex, or None: no evidence, evidence for both, or a phenotype of the other sex."""
    male = evidence["male"] and not evidence["female"] and not evidence["female_terms"]
    female = evidence["female"] and not evidence["male"] and not evidence["male_terms"]
    return "male" if male else "female" if female else None


def gene_limit(evidence: Mapping[str, Mapping], location: str) -> tuple[str | None, list[str], str | None]:
    """(limit, reasons, why not limited) from each disease's `disease_evidence`; why is "dsd", "ambiguous",
    "contradicted", "partial" (some diseases only), "compound_name" (a sex-limited phrase only inside a longer
    name) or None."""
    limits = {d: disease_limit(e) for d, e in evidence.items()}
    if any(e["dsd"] for e in evidence.values()):
        return None, [], "dsd" if any(e["male"] or e["female"] for e in evidence.values()) else None
    on_y = y_chromosome(location)
    ok = {
        "male": on_y or (bool(limits) and all(v == "male" for v in limits.values())),
        "female": not on_y and bool(limits) and all(v == "female" for v in limits.values()),
    }
    seen = {
        "male": on_y or any(e["male"] for e in evidence.values()),
        "female": any(e["female"] for e in evidence.values()),
    }
    for sex, other in (("male", "female"), ("female", "male")):
        if ok[sex] and not seen[other]:
            reasons = {r for d, e in evidence.items() for r in e[sex] if limits[d] == sex}
            reasons |= {"y_chromosome"} if on_y else set()
            return sex, [r for r in REASONS if r in reasons], None
    if ok["male"] or ok["female"] or (seen["male"] and seen["female"]):
        return None, [], "ambiguous"
    if any(e[s] and limits[d] is None for d, e in evidence.items() for s in SEXES):
        return None, [], "contradicted"
    if any(limits.values()):
        return None, [], "partial"
    return None, [], "compound_name" if any(e["compound_name"] for e in evidence.values()) else None


def _compact(evidence: Mapping) -> list[str]:
    out = [f"{s}:{r}" for s in SEXES for r in evidence[s]]
    return out + [k for k in ("male_terms", "female_terms", "dsd", "compound_name") if evidence[k]]


def build(
    genes: Iterable[str],
    genes_to_disease: Mapping[str, set[str]],
    ann: safe_knowledge.Annotations,
    hgnc_locations: Mapping[str, str],
    ancestors: Callable[[str], Iterable[str]],
) -> tuple[dict, dict]:
    """(kb, stats). `genes` holds the limited genes, `excluded` those with some evidence that are not; each
    with its diseases' evidence (`male:names`, `female:phenotypes`, `male_terms`, `dsd`, ...)."""
    classify = term_classifier(ancestors)
    out, excluded, names = {}, {}, {}
    stats: Counter = Counter()
    for g in sorted(set(genes)):
        ds = sorted(genes_to_disease.get(g, set()))
        evidence = {d: disease_evidence(d, ann, classify) for d in ds}
        location = hgnc_locations.get(g, "")
        limit, reasons, why = gene_limit(evidence, location)
        record = {"location": location, "diseases": {d: _compact(e) for d, e in evidence.items()}}
        if limit:
            out[g] = {"limit": limit, "reasons": reasons, **record}
            stats[f"{limit}_limited"] += 1
            stats.update(f"{limit}_reason_{r}" for r in reasons)
            stats[f"{limit}_reasons_{'+'.join(reasons)}"] += 1
        elif why:
            excluded[g] = {"why": why, **record}
            stats[f"excluded_{why}"] += 1
        else:
            continue
        names.update({d: ann.names[d] for d in ds if d in ann.names})
    kb = {
        "schema": SCHEMA,
        "rules": {
            "male_terms": list(MALE_TERMS),
            "female_terms": list(FEMALE_TERMS),
            "dsd_terms": list(DSD_TERMS),
            "male_names": MALE_NAMES.pattern,
            "female_names": FEMALE_NAMES.pattern,
            "dsd_names": DSD_NAMES.pattern,
        },
        "genes": out,
        "excluded": excluded,
        "disease_names": dict(sorted(names.items())),
    }
    stats["genes"] = len(set(genes))
    return kb, dict(sorted(stats.items()))


def kb_from_sources(genes: Iterable[str]) -> tuple[dict, dict, list[str]]:
    """(kb, stats, the source names read), opening only `KB_SOURCES` through the registry."""
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.v4 import addon

    paths = {k: open_source(name, Purpose.KB) for k, name in KB_SOURCES.items()}
    ontology = Ontology.from_json(paths["ontology"])
    kb, stats = build(
        genes,
        addon.genes_to_disease(paths["genes"]),
        addon.annotations(paths["annotations"]),
        safe_knowledge.read_hgnc_locations(paths["hgnc"]),
        ontology.ancestors,
    )
    return kb, stats, list(KB_SOURCES.values())


def limits(kb: Mapping) -> dict[str, str]:
    """gene -> "male" | "female" of a `sex-kb/2` document or of an add-on knowledge (`ft-kb/2`, safe-v1)."""
    if kb.get("schema") == SCHEMA:
        return {g: r["limit"] for g, r in kb["genes"].items()}
    return {g: r["sex"]["limit"] for g, r in kb["safe"]["genes"].items() if "sex" in r}


def load_kb(kb_id: str) -> tuple[dict, str]:
    """(kb, sha256) of a verified `sex-kb` artifact."""
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.v4.addon import _verified_output

    path, sha = _verified_output(kb_id, KB_KIND, KB_FILE)
    return kb_io.read(path), sha


def sex_of(value) -> str | None:
    text = str(getattr(value, "value", value)).lower() if value is not None else ""
    return text if text in SEXES else None


def block(scores: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """float64 scores with the masked genes moved below every other gene, their own order kept."""
    out = np.asarray(scores, dtype=np.float64).reshape(-1).copy()
    mask = np.asarray(mask, dtype=bool)
    if mask.any() and not mask.all():
        out[mask] -= out.max() - out.min() + 1.0
    return out


class SexRule:
    """A sex limit per gene over a vocabulary: `blocked(sex)` and `apply(scores, sex)`."""

    def __init__(self, gene_limits: Mapping[str, str], genes: Sequence[str]) -> None:
        self.genes = tuple(genes)
        self.only = {s: np.array([gene_limits.get(g) == s for g in self.genes]) for s in SEXES}

    def blocked(self, sex) -> np.ndarray:
        """Genes impossible for this sex (those limited to the other one); none when the sex is unknown."""
        sex = sex_of(sex)
        if sex is None:
            return np.zeros(len(self.genes), dtype=bool)
        return self.only["female" if sex == "male" else "male"]

    def apply(self, scores: np.ndarray, sex) -> np.ndarray:
        mask = self.blocked(sex)
        return block(scores, mask) if mask.any() else np.asarray(scores, dtype=np.float64).reshape(-1)


def write_kb(kb: dict, kb_id: str) -> Path:
    from diagnostic_ar_training.rerank import kb as kb_io

    path = KB_DIR / kb_id / KB_FILE
    kb_io.write(kb, path)
    return path
