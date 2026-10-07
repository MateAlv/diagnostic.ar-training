"""The curation queue: every sex-limited gene and every gene with a strict earliest onset of 1 year or more.

Each row carries the knowledge behind the rule and which files of the pinned GeneReviews and MedlinePlus
Genetics snapshots mention the gene symbol (a case-sensitive token match), so a curator knows where to
look. Curation itself writes data/curation/safe-v1-overrides.csv.
"""

import csv
import re
import tarfile
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

ONSET_MIN_YEARS = 1.0
COLUMNS = (
    "gene",
    "rule",
    "current",
    "sex_reasons",
    "diseases",
    "disease_onset_lower_years",
    "hpo_onset_evidence",
    "orphanet_onset_evidence",
    "genereviews_files",
    "medlineplus_files",
)
_TOKEN = re.compile(rb"[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]|[A-Za-z0-9]")


def mentions(tarball: Path, symbols: Iterable[str], member_filter=lambda name: True) -> dict[str, list[str]]:
    """symbol -> sorted file names (basename) in the tarball whose text contains the symbol as a token."""
    wanted = {s.encode() for s in symbols}
    out: dict[str, set[str]] = defaultdict(set)
    with tarfile.open(tarball, "r:gz") as tar:
        for member in tar:
            if not member.isfile() or not member_filter(member.name):
                continue
            tokens = set(_TOKEN.findall(tar.extractfile(member).read()))
            tokens |= {part for t in tokens if b"-" in t for part in t.split(b"-")}
            for token in tokens & wanted:
                out[token.decode()].add(Path(member.name).name)
    return {k: sorted(v) for k, v in out.items()}


def genereviews_chapter(name: str) -> bool:
    base = Path(name).name
    return base.endswith(".nxml") and not base.startswith(("GR", "TOC"))


def medlineplus_page(name: str) -> bool:
    return name.endswith(".html")


def rows(kb: dict, genereviews: dict[str, list[str]], medlineplus: dict[str, list[str]]) -> list[dict]:
    names = kb["disease_names"]
    out = []
    for gene, record in sorted(kb["genes"].items()):
        rules = []
        if "sex" in record:
            rules.append(("sex", record["sex"]["limit"]))
        if "onset" in record and record["onset"]["earliest_years"] >= ONSET_MIN_YEARS:
            rules.append(("onset", f"{record['onset']['earliest_years']:g}"))
        for rule, current in rules:
            evidence = record.get("onset", {}).get("diseases", {})
            out.append(
                {
                    "gene": gene,
                    "rule": rule,
                    "current": current,
                    "sex_reasons": "|".join(record.get("sex", {}).get("reasons", [])),
                    "diseases": "; ".join(f"{d} | {names.get(d, '')}" for d in record["diseases"]),
                    "disease_onset_lower_years": "; ".join(
                        f"{d}: {'none' if e['lower_years'] is None else format(e['lower_years'], 'g')}"
                        for d, e in evidence.items()
                    ),
                    "hpo_onset_evidence": "; ".join(
                        f"{d}: {','.join(e['hpo_terms'])}" for d, e in evidence.items() if e["hpo_terms"]
                    ),
                    "orphanet_onset_evidence": "; ".join(
                        f"{d}: {','.join(e['orphanet'])}" for d, e in evidence.items() if e["orphanet"]
                    ),
                    "genereviews_files": "|".join(genereviews.get(gene, [])),
                    "medlineplus_files": "|".join(medlineplus.get(gene, [])),
                }
            )
    return out


def write(path: Path, queue: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(queue)
