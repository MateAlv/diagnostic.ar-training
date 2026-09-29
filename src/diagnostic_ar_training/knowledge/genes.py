"""Gene profiles: which diseases each gene causes, how strongly, and with what inheritance.

The rules are in docs/decisions/0008-gene-profiles.md; the constants below are
that ADR's tables.
"""

import csv
import gzip
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from diagnostic_ar_training.ontology import MODE_OF_INHERITANCE, Ontology

CLINGEN_VALIDITY = {
    "Definitive": 1.0,
    "Strong": 1.0,
    "Moderate": 0.6,
    "Limited": 0.3,
    "Disputed": 0.05,
    "Refuted": 0.0,
    "No Known Disease Relationship": 0.0,
}
ORPHANET_VALIDITY = {
    "Disease-causing germline mutation(s) in": 1.0,
    "Disease-causing germline mutation(s) (loss of function) in": 1.0,
    "Disease-causing germline mutation(s) (gain of function) in": 1.0,
    "Role in the phenotype of": 0.5,
    "Major susceptibility factor in": 0.3,
    "Modifying germline mutation in": 0.2,
    "Candidate gene tested in": 0.1,
    "Disease-causing somatic mutation(s) in": 0.0,
    "Part of a fusion gene in": 0.0,
    "Biomarker tested in": 0.0,
}
NOT_YET_ASSESSED_FACTOR = 0.5
CLINGEN_MOI = {
    "AD": "HP:0000006",
    "AR": "HP:0000007",
    "XL": "HP:0001417",
    "MT": "HP:0001427",
    "SD": "HP:0032113",
}
PREVALENCE_CLASS = {
    "<1 / 1 000 000": 5e-7,
    "1-9 / 1 000 000": 5e-6,
    "1-9 / 100 000": 5e-5,
    "1-5 / 10 000": 3e-4,
    "6-9 / 10 000": 7.5e-4,
    ">1 / 1000": 2e-3,
}
EXCLUDED_HPO_ASSOCIATIONS = frozenset({"POLYGENIC"})
_ORPHA_EXACT = "E (Exact mapping"
_MONDO_EQUIVALENT = 'source="MONDO:equivalentTo"'


def _tsv(path: Path, first_field: str, opener=open):
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if not line.startswith("#") or line.startswith("#AlleleID"))
        reader = csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
        if not reader.fieldnames or reader.fieldnames[0] != first_field:
            raise ValueError(f"{path}: unexpected header {reader.fieldnames}")
        yield from reader


def chromosome(location: str) -> str:
    loc = location.strip().lower()
    if loc.startswith("mitochondria"):
        return "MT"
    if loc.startswith("x and y") or loc.startswith("xp22.33 and yp11") or " and y" in loc:
        return "XY"
    if m := re.match(r"^(\d{1,2}|x|y)(?=[pq]|$| )", loc):
        return m[1].upper()
    return "unknown"


def parse_hgnc(path: Path) -> tuple[dict[str, dict], dict[str, str]]:
    """Approved genes by symbol, and a resolver from previous/alias symbols to approved ones."""
    genes, previous, aliases = {}, defaultdict(set), defaultdict(set)
    for row in _tsv(path, "hgnc_id"):
        if row["status"] != "Approved":
            continue
        symbol = row["symbol"]
        split = lambda value: [v for v in value.split("|") if v]  # noqa: E731
        genes[symbol] = {
            "hgnc_id": row["hgnc_id"],
            "name": row["name"],
            "locus_type": row["locus_type"],
            "location": row["location"],
            "chromosome": chromosome(row["location"]),
            "aliases": split(row["alias_symbol"]),
            "previous_symbols": split(row["prev_symbol"]),
            "omim_gene_ids": split(row["omim_id"]),
        }
        for s in split(row["prev_symbol"]):
            previous[s.upper()].add(symbol)
        for s in split(row["alias_symbol"]):
            aliases[s.upper()].add(symbol)
    resolver = {s.upper(): s for s in genes}
    for table in (previous, aliases):
        for old, targets in table.items():
            if old not in resolver and len(targets) == 1:
                resolver[old] = next(iter(targets))
    return genes, resolver


def parse_orphanet_genes(path: Path) -> list[tuple[str, str, str, str]]:
    """(ORPHA id, gene symbol, association type, association status)."""
    out = []
    for disorder in ET.parse(path).getroot().find("DisorderList"):
        orpha = f"ORPHA:{disorder.findtext('OrphaCode')}"
        for assoc in disorder.iter("DisorderGeneAssociation"):
            out.append(
                (
                    orpha,
                    assoc.findtext("Gene/Symbol"),
                    assoc.findtext("DisorderGeneAssociationType/Name"),
                    assoc.findtext("DisorderGeneAssociationStatus/Name"),
                )
            )
    return out


def parse_orphanet_prevalence(path: Path) -> dict[str, float]:
    """ORPHA id -> prevalence estimate: worldwide point prevalence, else birth, else any classed record."""
    ranked: dict[str, tuple[int, float]] = {}
    preference = {("Point prevalence", "Worldwide"): 0, ("Prevalence at birth", "Worldwide"): 1}
    for disorder in ET.parse(path).getroot().find("DisorderList"):
        orpha = f"ORPHA:{disorder.findtext('OrphaCode')}"
        for prev in disorder.iter("Prevalence"):
            value = PREVALENCE_CLASS.get(prev.findtext("PrevalenceClass/Name") or "")
            if value is None:
                continue
            key = (prev.findtext("PrevalenceType/Name"), prev.findtext("PrevalenceGeographic/Name"))
            rank = preference.get(key, 2)
            if orpha not in ranked or (rank, -value) < (ranked[orpha][0], -ranked[orpha][1]):
                ranked[orpha] = (rank, value)
    return {k: v for k, (_, v) in ranked.items()}


def parse_orphanet_alignments(path: Path) -> list[tuple[str, str]]:
    """Exact, validated (ORPHA id, OMIM id) pairs."""
    pairs = []
    for disorder in ET.parse(path).getroot().find("DisorderList"):
        orpha = f"ORPHA:{disorder.findtext('OrphaCode')}"
        for ref in disorder.iter("ExternalReference"):
            if (
                ref.findtext("Source") == "OMIM"
                and (ref.findtext("DisorderMappingRelation/Name") or "").startswith(_ORPHA_EXACT)
                and ref.findtext("DisorderMappingValidationStatus/Name") == "Validated"
            ):
                pairs.append((orpha, f"OMIM:{ref.findtext('Reference')}"))
    return pairs


def parse_mondo(path: Path) -> dict[str, set[str]]:
    """MONDO id -> the OMIM/ORPHA ids it is declared equivalent to."""
    out: dict[str, set[str]] = {}
    current, obsolete = None, False
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("[Term]") or line.startswith("[Typedef]"):
                current, obsolete = None, False
            elif line.startswith("id: MONDO:"):
                current = line[4:].strip()
            elif line.startswith("is_obsolete: true"):
                obsolete = True
                out.pop(current, None)
            elif current and not obsolete and line.startswith("xref: ") and _MONDO_EQUIVALENT in line:
                ref = line[6:].split(" ", 1)[0]
                if ref.startswith("OMIM:"):
                    out.setdefault(current, set()).add(ref)
                elif ref.startswith("Orphanet:"):
                    out.setdefault(current, set()).add("ORPHA:" + ref.split(":", 1)[1])
    return out


def parse_clingen(path: Path) -> list[tuple[str, str, str, str]]:
    """(gene symbol, MONDO id, mode of inheritance, classification)."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = next(i for i, r in enumerate(rows) if r and r[0] == "GENE SYMBOL")
    return [(r[0], r[3], r[4], r[6]) for r in rows[header + 1 :] if r and r[0] and not r[0].startswith("+")]


def parse_clinvar(path: Path) -> Counter:
    """Distinct P/LP germline GRCh38 alleles per (single gene symbol, OMIM/ORPHA condition id)."""
    alleles: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in _tsv(path, "#AlleleID", opener=gzip.open):
        if row["Assembly"] != "GRCh38" or row["ClinSigSimple"] != "1":
            continue
        if "germline" not in row["OriginSimple"]:
            continue
        gene = row["GeneSymbol"]
        if not gene or ";" in gene or gene == "-":
            continue
        for phenotype in row["PhenotypeIDS"].split("|"):
            for ref in phenotype.split(","):
                if ref.startswith("OMIM:"):
                    alleles[(gene, ref)].add(row["#AlleleID"])
                elif ref.startswith("Orphanet:"):
                    alleles[(gene, "ORPHA:" + ref.split(":", 1)[1].removeprefix("ORPHA"))].add(
                        row["#AlleleID"]
                    )
    return Counter({k: len(v) for k, v in alleles.items()})


def hpoa_facts(
    path: Path, ontology: Ontology, masked_pmids: set[str]
) -> tuple[set[str], dict[str, set[str]]]:
    """Disease ids with >= 1 unmasked positive phenotype row, and their inheritance terms."""
    profiles, inheritance = set(), defaultdict(set)
    for row in _tsv(path, "database_id"):
        if set(row["reference"].split(";")) & masked_pmids:
            continue
        if row["aspect"] == "P" and row["qualifier"] != "NOT":
            profiles.add(row["database_id"])
        elif row["aspect"] == "I" and (term := ontology.resolve(row["hpo_id"])):
            if ontology.is_a(term, MODE_OF_INHERITANCE):
                inheritance[row["database_id"]].add(term)
    return profiles, inheritance


class _Entities:
    """Union-find over disease ids that are exactly equivalent."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)

    def groups(self) -> dict[str, list[str]]:
        out = defaultdict(list)
        for x in self.parent:
            out[self.find(x)].append(x)
        return {k: sorted(v) for k, v in out.items()}


def _primary(ids: list[str]) -> str:
    omim = [i for i in ids if i.startswith("OMIM:")]
    return (omim or ids)[0]


def build(
    ontology: Ontology,
    hgnc: Path,
    hpoa: Path,
    genes_to_disease: Path,
    genes_to_phenotype: Path,
    orphanet_genes: Path,
    orphanet_alignments: Path,
    orphanet_prevalence: Path,
    clingen: Path,
    mondo: Path,
    clinvar: Path,
    masked_pmids: set[str],
    vocabulary: list[str],
) -> tuple[dict, dict]:
    stats: Counter = Counter()
    approved, resolve = parse_hgnc(hgnc)

    def symbol_of(raw: str) -> str | None:
        return resolve.get(raw.upper())

    profiles, hpoa_inheritance = hpoa_facts(hpoa, ontology, masked_pmids)
    entities = _Entities()
    for orpha, omim in parse_orphanet_alignments(orphanet_alignments):
        entities.union(orpha, omim)
    mondo_map = parse_mondo(mondo)
    for ids in mondo_map.values():
        ids = sorted(ids)
        for other in ids[1:]:
            entities.union(ids[0], other)

    evidence: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    def link(raw_symbol: str, disease_id: str, kind: str, value) -> None:
        symbol = symbol_of(raw_symbol)
        if symbol is None:
            stats[f"links_unresolved_symbol_{kind}"] += 1
            return
        evidence[symbol][disease_id][kind].append(value)
        entities.find(disease_id)

    for row in _tsv(genes_to_disease, "ncbi_gene_id"):
        if row["gene_symbol"] in ("", "-") or row["association_type"] in EXCLUDED_HPO_ASSOCIATIONS:
            continue
        link(row["gene_symbol"], row["disease_id"], "hpo", row["association_type"])
    seen_pairs = set()
    for row in _tsv(genes_to_phenotype, "ncbi_gene_id"):
        pair = (row["gene_symbol"], row["disease_id"])
        if row["gene_symbol"] not in ("", "-") and pair not in seen_pairs:
            seen_pairs.add(pair)
            link(row["gene_symbol"], row["disease_id"], "hpo", "GENES_TO_PHENOTYPE")
    for orpha, symbol, assoc_type, status in parse_orphanet_genes(orphanet_genes):
        link(symbol, orpha, "orphanet", [assoc_type, status])
    for symbol, mondo_id, moi, classification in parse_clingen(clingen):
        targets = sorted(mondo_map.get(mondo_id, ()))
        if not targets:
            stats["clingen_curations_without_omim_or_orpha"] += 1
            continue
        link(symbol, targets[0], "clingen", [classification, moi])
    clinvar_counts = parse_clinvar(clinvar)
    prevalence = parse_orphanet_prevalence(orphanet_prevalence)
    groups = entities.groups()
    group_of = {i: root for root, ids in groups.items() for i in ids}

    # The v3.0 vocabulary keeps its own spelling; record how it maps to current symbols.
    vocab_map = {g: symbol_of(g) for g in vocabulary if g != "-"}
    v3_symbol = {current: g for g, current in vocab_map.items() if current}

    out_genes = {}
    for symbol in sorted(evidence):
        by_entity: dict[str, dict] = defaultdict(lambda: defaultdict(list))
        for disease_id, kinds in evidence[symbol].items():
            for kind, values in kinds.items():
                by_entity[group_of[disease_id]][kind].extend(values)
        entities_out = []
        for root in sorted(by_entity):
            ids = groups[root]
            ev = by_entity[root]
            if ev.get("clingen"):
                v = max(CLINGEN_VALIDITY.get(c, 0.0) for c, _ in ev["clingen"])
                basis = "clingen"
            elif ev.get("orphanet"):
                v = max(
                    ORPHANET_VALIDITY.get(t, 0.0)
                    * (NOT_YET_ASSESSED_FACTOR if s == "Not yet assessed" else 1)
                    for t, s in ev["orphanet"]
                )
                basis = "orphanet"
            else:
                v, basis = 1.0, "hpo"
            clinvar = sum(clinvar_counts.get((symbol, i), 0) for i in ids)
            moi = sorted({CLINGEN_MOI[m] for _, m in ev.get("clingen", []) if m in CLINGEN_MOI})
            inheritance = moi or sorted({t for i in ids for t in hpoa_inheritance.get(i, ())})
            prev = [prevalence[i] for i in ids if i in prevalence]
            entities_out.append(
                {
                    "entity": _primary(ids),
                    "ids": ids,
                    "profile_ids": [i for i in ids if i in profiles],
                    "validity": v,
                    "validity_basis": basis,
                    "clingen": sorted(map(list, {tuple(x) for x in ev.get("clingen", [])})),
                    "orphanet": sorted(map(list, {tuple(x) for x in ev.get("orphanet", [])})),
                    "hpo_associations": sorted(set(ev.get("hpo", []))),
                    "clinvar_plp_alleles": clinvar,
                    "prevalence": max(prev) if prev else None,
                    "inheritance": inheritance,
                    "inheritance_basis": "clingen" if moi else ("hpoa" if inheritance else None),
                    "weight_raw": round(v * math.sqrt(1 + clinvar), 6),
                }
            )
        for e in entities_out:
            e["simulable"] = bool(e["profile_ids"]) and e["weight_raw"] > 0
        simulable = [e for e in entities_out if e["simulable"]]
        total = sum(e["weight_raw"] for e in simulable)
        for e in entities_out:
            e["sim_weight"] = round(e["weight_raw"] / total, 6) if e["simulable"] else 0.0
        info = approved.get(symbol, {})
        out_genes[symbol] = {
            **info,
            "symbol": symbol,
            "v3_symbol": v3_symbol.get(symbol),
            "entities": entities_out,
            "simulable_entities": len(simulable),
        }
        stats["genes"] += 1
        stats["genes_with_simulable_entity"] += bool(simulable)
        stats["genes_with_multiple_simulable_entities"] += len(simulable) > 1
        stats["entities"] += len(entities_out)
        stats["entities_simulable"] += len(simulable)
        for e in entities_out:
            stats[f"entities_basis_{e['validity_basis']}"] += 1
            stats["entities_zero_validity"] += e["validity"] == 0
            stats["entities_with_clinvar"] += e["clinvar_plp_alleles"] > 0

    for g, current in vocab_map.items():
        stats["vocab_genes"] += 1
        stats["vocab_genes_renamed"] += current is not None and current != g
        stats["vocab_genes_unresolved"] += current is None
        stats["vocab_genes_with_simulable_entity"] += bool(
            current and out_genes.get(current, {}).get("simulable_entities")
        )
    return {"genes": out_genes, "vocabulary": vocab_map}, dict(sorted(stats.items()))


def calibration(
    genes: dict, vocabulary: dict, cases, groups: dict, gammas=(0.0, 0.25, 0.5, 0.75, 1.0, 1.5)
) -> dict:
    """How well weights predict which of its gene's diseases a patient has (R1-train only).

    Scores v * (1 + c) ** gamma for each gamma; gamma = 0.5 is ADR-0008's weight.
    """
    rows = []
    for case in cases:
        gene = genes.get(vocabulary.get(case.gene) or case.gene)
        if not gene:
            continue
        ents = [e for e in gene["entities"] if e["simulable"]]
        truth = [i for i, e in enumerate(ents) if set(e["ids"]) & set(case.disease_ids)]
        if len(ents) >= 2 and truth:
            rows.append((groups[case.case_id], ents, truth))

    def score(gamma: float) -> dict:
        logp, top1, prob = [], [], []
        for _, ents, truth in rows:
            w = [e["validity"] * (1 + e["clinvar_plp_alleles"]) ** gamma for e in ents]
            total = sum(w)
            p = sum(w[i] for i in truth) / total if total else 0.0
            best = max(w)
            top1.append(any(w[i] == best for i in truth) and w.count(best) == 1)
            logp.append(math.log(max(p, 1e-6)))
            prob.append(p)
        n = len(rows)
        return {"mean_log_p": sum(logp) / n, "top1": sum(top1) / n, "mean_p": sum(prob) / n}

    uniform = sum(len(truth) / len(ents) for _, ents, truth in rows) / len(rows)
    return {
        "cases": len(rows),
        "publications": len({g for g, _, _ in rows}),
        "mean_entities_per_gene": sum(len(e) for _, e, _ in rows) / len(rows),
        "uniform_mean_p": uniform,
        "by_gamma": {str(g): score(g) for g in gammas},
    }
