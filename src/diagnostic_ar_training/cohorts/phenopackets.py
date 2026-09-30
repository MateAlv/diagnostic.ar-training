"""phenopacket-store parser. Code outside splits.py must go through the frozen split."""

import json
import re
import zipfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from diagnostic_ar_training.cohorts.schema import Case, Sex

COHORT = "phenopacket_store"
_DURATION = re.compile(
    r"^P(?:(?P<y>\d+(?:\.\d+)?)Y)?(?:(?P<m>\d+(?:\.\d+)?)M)?(?:(?P<w>\d+(?:\.\d+)?)W)?"
    r"(?:(?P<d>\d+(?:\.\d+)?)D)?(?:T.*)?$"
)
_SEX = {"MALE": Sex.MALE, "FEMALE": Sex.FEMALE}


def iso_duration_years(value: str) -> float | None:
    match = _DURATION.match(value or "")
    if not match or not any(match.groupdict().values()):
        return None
    parts = {k: float(v) if v else 0.0 for k, v in match.groupdict().items()}
    return parts["y"] + parts["m"] / 12 + parts["w"] * 7 / 365.25 + parts["d"] / 365.25


def _time_element(element: dict | None) -> tuple[float | None, str | None]:
    """(years, HPO onset class) from a phenopacket TimeElement."""
    if not element:
        return None, None
    if "age" in element:
        return iso_duration_years(element["age"].get("iso8601duration", "")), None
    if "ageRange" in element:
        return iso_duration_years(element["ageRange"].get("start", {}).get("iso8601duration", "")), None
    if "gestationalAge" in element:
        return 0.0, None
    if "ontologyClass" in element:
        return None, element["ontologyClass"].get("id")
    return None, None


def _causative_genes(packet: dict) -> set[str]:
    genes = set()
    for interpretation in packet.get("interpretations", []):
        for gi in interpretation.get("diagnosis", {}).get("genomicInterpretations", []):
            if gi.get("interpretationStatus") not in (None, "CAUSATIVE", "CONTRIBUTORY"):
                continue
            variant = gi.get("variantInterpretation", {}).get("variationDescriptor", {})
            symbol = variant.get("geneContext", {}).get("symbol") or gi.get("gene", {}).get("symbol")
            if symbol:
                genes.add(symbol)
    return genes


def parse_packet(packet: dict, drops: Counter) -> Case | None:
    genes = _causative_genes(packet)
    if len(genes) != 1:
        drops["not_single_gene"] += 1
        return None

    present, excluded, onsets = set(), set(), {}
    for feature in packet.get("phenotypicFeatures", []):
        term = feature.get("type", {}).get("id", "")
        if term.startswith("HP:"):
            (excluded if feature.get("excluded") else present).add(term)
            if not feature.get("excluded") and feature.get("onset"):
                years, onset_class = _time_element(feature["onset"])
                if years is not None or onset_class:
                    onsets.setdefault(term, (years, onset_class))
    conflicted = present & excluded
    if conflicted:
        drops["terms_both_present_and_excluded"] += len(conflicted)
        present -= conflicted
        excluded -= conflicted
    if not present:
        drops["no_present_terms"] += 1
        return None

    subject = packet.get("subject", {})
    age_years, _ = _time_element(subject.get("timeAtLastEncounter"))
    diseases = packet.get("diseases", [])
    onset_years, onset_term = _time_element(diseases[0].get("onset") if diseases else None)
    disease_ids = {d.get("term", {}).get("id") for d in diseases} | {
        i.get("diagnosis", {}).get("disease", {}).get("id") for i in packet.get("interpretations", [])
    }
    pmids = {
        ref["id"]
        for ref in packet.get("metaData", {}).get("externalReferences", [])
        if ref.get("id", "").startswith("PMID:")
    }
    return Case(
        case_id=packet["id"],
        cohort=COHORT,
        gene=genes.pop(),
        present=tuple(sorted(present)),
        excluded=tuple(sorted(excluded)),
        sex=_SEX.get(subject.get("sex", ""), Sex.UNKNOWN),
        age_years=age_years,
        onset_years=onset_years,
        onset_term=onset_term,
        disease_ids=tuple(sorted(d for d in disease_ids if d)),
        pmids=tuple(sorted(pmids)),
        feature_onsets=tuple((t, *onsets[t]) for t in sorted(onsets) if t in present),
    )


def iter_cases(zip_path: Path, drops: Counter | None = None) -> Iterator[Case]:
    drops = drops if drops is not None else Counter()
    seen: set[str] = set()
    with zipfile.ZipFile(zip_path) as archive:
        for name in sorted(archive.namelist()):
            if not name.endswith(".json"):
                continue
            case = parse_packet(json.loads(archive.read(name)), drops)
            if case is None:
                continue
            if case.case_id in seen:
                drops["duplicate_id"] += 1
                continue
            seen.add(case.case_id)
            yield case
