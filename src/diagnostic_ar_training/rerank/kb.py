"""Front B knowledge base: what HPO and Orphanet say about each disease and gene.

Built only from sources with role `knowledge`, with every HPOA row that cites a
held-out R1 publication removed (EVAL_PROTOCOL §4.1). Frequencies follow
ADR-0007 (schema 2): pooled counts with a Jeffreys prior, then percentages,
then category midpoints; an empty frequency is "unknown", never "always", and
only NOT marks an absence. Gene -> disease weights come from the gene profiles
(ADR-0008).
"""

import csv
import gzip
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean

from diagnostic_ar_training.lineage.hashing import canonical_json
from diagnostic_ar_training.ontology import MODE_OF_INHERITANCE, ONSET, Ontology

FREQUENCY_CATEGORIES = {
    "HP:0040280": 1.0,
    "HP:0040281": (0.80 + 0.99) / 2,
    "HP:0040282": (0.30 + 0.79) / 2,
    "HP:0040283": (0.05 + 0.29) / 2,
    "HP:0040284": (0.01 + 0.04) / 2,
    "HP:0040285": 0.0,
}
EXCLUDED_FREQUENCY = "HP:0040285"
_FRACTION = re.compile(r"^(\d+)\s*/\s*(\d+)$")
_PERCENT = re.compile(r"^(\d+(?:\.\d+)?)\s*%$")

_DAY = 1 / 365.25
# Age intervals in years (negative = prenatal) from the HPO onset term definitions.
HPO_ONSET_YEARS: dict[str, tuple[float, float]] = {
    "HP:0030674": (-0.75, 0.0),  # antenatal
    "HP:0011460": (-0.75, -0.6),  # embryonal
    "HP:0011461": (-0.6, 0.0),  # fetal
    "HP:0003577": (0.0, 0.0),  # congenital
    "HP:0003623": (0.0, 28 * _DAY),  # neonatal
    "HP:0003593": (28 * _DAY, 1.0),  # infantile
    "HP:0011463": (1.0, 5.0),  # childhood
    "HP:0003621": (5.0, 15.0),  # juvenile
    "HP:0410280": (0.0, 16.0),  # pediatric
    "HP:0003581": (16.0, 100.0),  # adult
    "HP:0011462": (16.0, 40.0),  # young adult
    "HP:0025708": (16.0, 19.0),  # early young adult
    "HP:0025709": (19.0, 25.0),  # intermediate young adult
    "HP:0025710": (25.0, 40.0),  # late young adult
    "HP:0003596": (40.0, 60.0),  # middle age
    "HP:0003584": (60.0, 100.0),  # late
}
# Orphanet AverageAgeOfOnset classes; "All ages" says nothing and is not used.
ORPHANET_ONSET_YEARS: dict[str, tuple[float, float]] = {
    "Antenatal": (-0.75, 0.0),
    "Neonatal": (0.0, 28 * _DAY),
    "Infancy": (28 * _DAY, 2.0),
    "Childhood": (2.0, 11.0),
    "Adolescent": (11.0, 18.0),
    "Adult": (18.0, 65.0),
    "Elderly": (65.0, 100.0),
}
EXCLUDED_ASSOCIATIONS = frozenset({"POLYGENIC"})


def parse_frequency(raw: str) -> tuple[str, object] | None:
    """("count", (n, m)) | ("percent", p) | ("category", midpoint) | None."""
    text = raw.strip()
    if not text or text == "-":
        return None
    if text in FREQUENCY_CATEGORIES:
        return "category", FREQUENCY_CATEGORIES[text]
    if m := _FRACTION.match(text):
        num, den = int(m[1]), int(m[2])
        return ("count", (num, den)) if 0 < den and num <= den else None
    if m := _PERCENT.match(text):
        value = float(m[1]) / 100
        return ("percent", value) if value <= 1 else None
    return None


def estimate_frequency(
    counts: tuple[int, int], percents: list[float], categories: list[float]
) -> float | None:
    """ADR-0007: pooled counts (Jeffreys mean), else mean percentage, else mean category midpoint."""
    n, m = counts
    if m:
        return (n + 0.5) / (m + 1)
    if percents:
        return fmean(percents)
    if categories:
        return fmean(categories)
    return None


def _rows(path: Path, first_field: str):
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if not line.startswith("#"))
        reader = csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
        if not reader.fieldnames or reader.fieldnames[0] != first_field:
            raise ValueError(f"{path}: unexpected header {reader.fieldnames}")
        yield from reader


@dataclass
class _Phenotype:
    n: int = 0
    m: int = 0
    percents: list[float] = field(default_factory=list)
    categories: list[float] = field(default_factory=list)
    onsets: set[str] = field(default_factory=set)
    sexes: set[str] = field(default_factory=set)
    unrestricted: bool = False


@dataclass
class _Disease:
    name: str = ""
    phenotypes: dict[str, _Phenotype] = field(default_factory=dict)
    excluded: set[str] = field(default_factory=set)
    onset_terms: set[str] = field(default_factory=set)
    inheritance: set[str] = field(default_factory=set)


def onset_interval(ontology: Ontology, term: str) -> tuple[float, float] | None:
    """Interval of an onset term, or of its nearest mapped ancestor."""
    if term in HPO_ONSET_YEARS:
        return HPO_ONSET_YEARS[term]
    mapped = [HPO_ONSET_YEARS[a] for a in ontology.ancestors(term) if a in HPO_ONSET_YEARS]
    return min(mapped, key=lambda iv: iv[1] - iv[0]) if mapped else None


def parse_orphanet_onsets(path: Path) -> dict[str, list[str]]:
    """ORPHA:<code> -> Orphanet onset class names (informative ones only)."""
    out = {}
    for disorder in ET.parse(path).getroot().find("DisorderList"):
        names = sorted(
            {
                a.findtext("Name")
                for a in disorder.iter("AverageAgeOfOnset")
                if a.findtext("Name") in ORPHANET_ONSET_YEARS
            }
        )
        if names:
            out[f"ORPHA:{disorder.findtext('OrphaCode')}"] = names
    return out


def parse_exact_alignments(path: Path) -> dict[str, set[str]]:
    """OMIM id -> ORPHA ids it is exactly (and validatedly) equivalent to."""
    out: dict[str, set[str]] = defaultdict(set)
    for disorder in ET.parse(path).getroot().find("DisorderList"):
        for ref in disorder.iter("ExternalReference"):
            if (
                ref.findtext("Source") == "OMIM"
                and (ref.findtext("DisorderMappingRelation/Name") or "").startswith("E (Exact mapping")
                and ref.findtext("DisorderMappingValidationStatus/Name") == "Validated"
            ):
                out[f"OMIM:{ref.findtext('Reference')}"].add(f"ORPHA:{disorder.findtext('OrphaCode')}")
    return out


def gene_weights_from_profiles(profiles: dict) -> tuple[dict[str, dict[str, float]], dict[str, str]]:
    """symbol -> {HPOA disease id: weight}, splitting each entity's weight over its profiles."""
    out = {}
    for symbol, gene in profiles["genes"].items():
        weights = {}
        for entity in gene["entities"]:
            if entity["sim_weight"] > 0:
                for pid in entity["profile_ids"]:
                    weights[pid] = weights.get(pid, 0.0) + entity["sim_weight"] / len(entity["profile_ids"])
        if weights:
            out[symbol] = {k: round(v, 6) for k, v in sorted(weights.items())}
    return out, {k: v for k, v in profiles["vocabulary"].items() if v}


def build(
    ontology: Ontology,
    hpoa: Path,
    genes_to_disease: Path,
    genes_to_phenotype: Path,
    orphanet_ages: Path,
    masked_pmids: set[str],
    orphanet_alignments: Path | None = None,
    gene_profiles: dict | None = None,
    drop_annotations: set[tuple[str, str]] | None = None,
) -> tuple[dict, dict]:
    """Returns (kb, stats). The kb is plain JSON-serialisable data, deterministic.

    With `gene_profiles` (schema 2) genes map to weighted diseases; without, to
    their association types as in kb-v1.
    """
    stats: Counter = Counter(
        {
            k: 0
            for k in (
                "rows_masked_heldout_pmid",
                "rows_unresolvable_term",
                "rows_term_resolved_to_current_id",
                "rows_unparsed_frequency",
                "negations_dropped_conflicting_with_positive",
            )
        }
    )
    diseases: dict[str, _Disease] = defaultdict(_Disease)

    for row in _rows(hpoa, "database_id"):
        stats["hpoa_rows"] += 1
        refs = set(row["reference"].split(";"))
        if refs & masked_pmids:
            stats["rows_masked_heldout_pmid"] += 1
            continue
        term = ontology.resolve(row["hpo_id"])
        if term is None:
            stats["rows_unresolvable_term"] += 1
            continue
        if term != row["hpo_id"]:
            stats["rows_term_resolved_to_current_id"] += 1
        if drop_annotations and (row["database_id"], row["hpo_id"]) in drop_annotations:
            if row["aspect"] == "P" and row["qualifier"] != "NOT":
                stats["rows_dropped_heldout_annotation"] += 1
                continue
        disease = diseases[row["database_id"]]
        disease.name = disease.name or row["disease_name"]
        aspect = row["aspect"]
        if aspect == "P":
            if row["qualifier"] == "NOT" or row["frequency"].strip() == EXCLUDED_FREQUENCY:
                disease.excluded.add(term)
                stats["rows_negated"] += 1
                continue
            pheno = disease.phenotypes.setdefault(term, _Phenotype())
            parsed = parse_frequency(row["frequency"])
            if parsed is None:
                stats["rows_unparsed_frequency"] += bool(row["frequency"].strip())
            elif parsed[0] == "count":
                pheno.n += parsed[1][0]
                pheno.m += parsed[1][1]
            elif parsed[0] == "percent":
                pheno.percents.append(parsed[1])
            else:
                pheno.categories.append(parsed[1])
            if row["onset"].strip() and (onset := ontology.resolve(row["onset"].strip())):
                pheno.onsets.add(onset)
            sex = row["sex"].strip().lower()
            if sex in ("male", "female"):
                pheno.sexes.add(sex)
            else:
                pheno.unrestricted = True
        elif aspect == "C" and ontology.is_a(term, ONSET):
            disease.onset_terms.add(term)
        elif aspect == "I" and ontology.is_a(term, MODE_OF_INHERITANCE):
            disease.inheritance.add(term)

    orphanet = parse_orphanet_onsets(orphanet_ages)
    alignments = parse_exact_alignments(orphanet_alignments) if orphanet_alignments else {}
    kb_diseases = {}
    for disease_id in sorted(diseases):
        d = diseases[disease_id]
        conflicting = d.excluded & set(d.phenotypes)
        if conflicting:
            stats["negations_dropped_conflicting_with_positive"] += len(conflicting)
        phenotypes = {}
        for term in sorted(d.phenotypes):
            p = d.phenotypes[term]
            freq = estimate_frequency((p.n, p.m), p.percents, p.categories)
            phenotypes[term] = {
                "freq": None if freq is None else round(freq, 6),
                "onset": sorted(p.onsets),
                # Restricted only if every row naming the phenotype names one sex.
                "sex": next(iter(p.sexes)) if len(p.sexes) == 1 and not p.unrestricted else None,
            }
        intervals = sorted({iv for t in d.onset_terms if (iv := onset_interval(ontology, t))})
        onset_source = "hpoa" if intervals else None
        if not intervals and disease_id in orphanet:
            intervals = sorted({ORPHANET_ONSET_YEARS[n] for n in orphanet[disease_id]})
            onset_source = "orphanet"
        if not intervals:
            names = {n for orpha in alignments.get(disease_id, ()) for n in orphanet.get(orpha, ())}
            if names:
                intervals = sorted({ORPHANET_ONSET_YEARS[n] for n in names})
                onset_source = "orphanet_exact_alignment"
        kb_diseases[disease_id] = {
            "name": d.name,
            "phenotypes": phenotypes,
            "excluded": sorted(d.excluded - set(d.phenotypes)),
            "onset_terms": sorted(d.onset_terms),
            "onset_years": [list(iv) for iv in intervals],
            "onset_source": onset_source,
            "inheritance": sorted(d.inheritance),
        }

    genes: dict[str, dict[str, str]] = defaultdict(dict)
    for row in _rows(genes_to_disease, "ncbi_gene_id"):
        symbol, assoc = row["gene_symbol"], row["association_type"]
        if symbol in ("", "-"):
            continue
        if assoc in EXCLUDED_ASSOCIATIONS:
            stats["gene_disease_links_excluded_polygenic"] += 1
            continue
        genes[symbol][row["disease_id"]] = assoc
    for row in _rows(genes_to_phenotype, "ncbi_gene_id"):
        symbol, disease_id = row["gene_symbol"], row["disease_id"]
        if symbol not in ("", "-") and disease_id not in genes[symbol]:
            if disease_id in kb_diseases:
                genes[symbol][disease_id] = "GENES_TO_PHENOTYPE_ONLY"
                stats["gene_disease_links_from_genes_to_phenotype_only"] += 1
    kb_genes = {}
    for symbol in sorted(genes):
        linked = {d: a for d, a in sorted(genes[symbol].items()) if d in kb_diseases}
        stats["gene_disease_links_without_annotations"] += len(genes[symbol]) - len(linked)
        if linked:
            kb_genes[symbol] = linked

    kb = {"schema": 1, "diseases": kb_diseases, "genes": kb_genes}
    if gene_profiles is not None:
        weights, vocabulary = gene_weights_from_profiles(gene_profiles)
        kb_genes = {
            symbol: {d: w for d, w in ws.items() if d in kb_diseases} for symbol, ws in weights.items()
        }
        kb_genes = {k: v for k, v in kb_genes.items() if v}
        kb = {"schema": 2, "diseases": kb_diseases, "genes": kb_genes, "vocabulary": vocabulary}
    stats.update(
        diseases=len(kb_diseases),
        genes=len(kb_genes),
        phenotype_annotations=sum(len(d["phenotypes"]) for d in kb_diseases.values()),
        negated_annotations=sum(len(d["excluded"]) for d in kb_diseases.values()),
        sex_restricted_annotations=sum(
            1 for d in kb_diseases.values() for p in d["phenotypes"].values() if p["sex"]
        ),
        diseases_with_onset_hpoa=sum(d["onset_source"] == "hpoa" for d in kb_diseases.values()),
        diseases_with_onset_orphanet=sum(d["onset_source"] == "orphanet" for d in kb_diseases.values()),
        diseases_with_onset_orphanet_via_alignment=sum(
            d["onset_source"] == "orphanet_exact_alignment" for d in kb_diseases.values()
        ),
        phenotypes_with_frequency_one=sum(
            1 for d in kb_diseases.values() for p in d["phenotypes"].values() if p["freq"] == 1.0
        ),
        diseases_with_inheritance=sum(bool(d["inheritance"]) for d in kb_diseases.values()),
    )
    return kb, dict(sorted(stats.items()))


def write(kb: dict, path: Path) -> None:
    """Byte-deterministic: canonical JSON, gzip without timestamp or filename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
        gz.write(canonical_json(kb).encode("utf-8"))


def read(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)
