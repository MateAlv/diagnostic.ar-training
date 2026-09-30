"""`cardinal-*`: hallmark features per disease (ADR-0011 §4).

Kinds:
- `diagnostic_criterion`, `pathognomonic`: Orphadata product 4 `DiagnosticCriteria` flags,
  written for the ORPHA disorder and for every OMIM id exactly (and validatedly) aligned to it;
- `cardinal_proxy`: a (disease, term) whose pooled count rows in `hpoa-recount-*` reach
  `m >= min_patients` with `n/m >= min_frequency`.

`source` is semicolon-separated: the origin first, then the references behind the row
(the product-4 disorder and its cited PMIDs, or the HPOA rows' references), so consumers can
leave out rows that cite publications they must not see.
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.kb import parse_frequency

DIAGNOSTIC_CRITERIA = {"Diagnostic criterion": "diagnostic_criterion", "Pathognomonic sign": "pathognomonic"}
PROXY = "cardinal_proxy"
KINDS = ("diagnostic_criterion", "pathognomonic", PROXY)
HEADER = ("disease_id", "hpo_id", "kind", "source")


def parse_product4(path: Path) -> list[tuple[str, str, str, list[str]]]:
    """(ORPHA id, HPO id, kind, the disorder's cited PMIDs) for every flagged association."""
    out = []
    for status in ET.parse(path).getroot().iter("HPODisorderSetStatus"):
        disorder = status.find("Disorder")
        orpha = f"ORPHA:{disorder.findtext('OrphaCode')}"
        cited = (status.findtext("Source") or "").split("_")
        pmids = sorted({f"PMID:{s.removesuffix('[PMID]')}" for s in cited if s.endswith("[PMID]")})
        for assoc in disorder.iter("HPODisorderAssociation"):
            name = assoc.findtext("DiagnosticCriteria/Name")
            if name in DIAGNOSTIC_CRITERIA:
                out.append((orpha, assoc.findtext("HPO/HPOId"), DIAGNOSTIC_CRITERIA[name], pmids))
    return out


def references(source: str) -> set[str]:
    """PMIDs and R1 recount markers a row rests on."""
    return {t for t in source.split(";")[1:] if t.startswith(("PMID:", "R1-TRAIN:"))}


def build(
    product4: list[tuple[str, str, str, list[str]]],
    hpoa_rows: list[dict],
    ontology: Ontology,
    exact_pairs: list[tuple[str, str]],
    heldout_pmids: set[str],
    product4_name: str,
    recount_name: str,
    min_patients: int = 10,
    min_frequency: float = 0.8,
) -> tuple[list[tuple[str, str, str, str]], dict]:
    stats: dict[str, int] = defaultdict(int)
    omim_of: dict[str, set[str]] = defaultdict(set)
    for orpha, omim in exact_pairs:
        omim_of[orpha].add(omim)
    rows = set()
    for orpha, raw, kind, pmids in product4:
        stats[f"product4_{kind}"] += 1
        term = ontology.resolve(raw or "")
        if term is None:
            stats["product4_unresolvable_term"] += 1
            continue
        if set(pmids) & heldout_pmids:
            stats["product4_dropped_cites_heldout_pmid"] += 1
            continue
        source = ";".join([product4_name, orpha, *pmids])
        rows.add((orpha, term, kind, source))
        for omim in sorted(omim_of.get(orpha, ())):
            rows.add((omim, term, kind, source))
            stats["product4_rows_via_exact_alignment"] += 1

    pooled: dict[tuple[str, str], list] = defaultdict(lambda: [0, 0, set()])
    for row in hpoa_rows:
        if row["aspect"] != "P" or row["qualifier"] == "NOT":
            continue
        parsed = parse_frequency(row["frequency"])
        if parsed is None or parsed[0] != "count":
            continue
        term = ontology.resolve(row["hpo_id"])
        if term is None:
            continue
        acc = pooled[(row["database_id"], term)]
        acc[0] += parsed[1][0]
        acc[1] += parsed[1][1]
        acc[2].update(r for r in row["reference"].split(";") if r)
    for (disease, term), (n, m, refs) in pooled.items():
        if m >= min_patients and n / m >= min_frequency:
            rows.add((disease, term, PROXY, ";".join([recount_name, *sorted(refs)])))
    out = sorted(rows)
    for kind in KINDS:
        stats[f"rows_{kind}"] = sum(r[2] == kind for r in out)
        stats[f"diseases_{kind}"] = len({r[0] for r in out if r[2] == kind})
    stats["rows"] = len(out)
    stats["diseases"] = len({r[0] for r in out})
    return out, dict(sorted(stats.items()))


def write(path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\t".join(HEADER) + "\n" + "".join("\t".join(r) + "\n" for r in rows))


def read(path: Path) -> list[dict]:
    lines = Path(path).read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"), strict=True)) for line in lines[1:] if line]
