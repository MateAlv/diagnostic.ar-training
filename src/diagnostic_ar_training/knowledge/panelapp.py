"""Genomics England PanelApp: gene-panel-disease links with an evidence level.

The `panelapp` source is a gzipped JSON snapshot of the public API
(scripts/sources/snapshot_panelapp.py): `panels` and `genes`, where each gene entry
is one gene on one panel. Phenotypes are free-text strings that often end in an
OMIM number and sometimes carry HPO ids; both are picked out by pattern only.

Terms of use (December 2019) exclude commercial and diagnostic use without a
separate agreement with Genomics England; see data/sources.yaml.
"""

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path

EVIDENCE_LEVEL = {"3": "green", "2": "amber", "1": "red", "0": "red"}
_HPO = re.compile(r"\bHP:\s?(\d{7})\b")
_OMIM = re.compile(r"(?:\bOMIM:?\s?|\bMIM:?\s?|(?<![\d:.]))(\d{6})(?![\d.])")


@dataclass(frozen=True)
class PanelGene:
    panel_id: int
    panel_name: str
    panel_version: str
    disease_group: str
    relevant_disorders: tuple[str, ...]
    gene: str
    hgnc_id: str
    evidence: str
    """green, amber or red (PanelApp confidence level 3, 2, 1/0)."""
    mode_of_inheritance: str
    phenotypes: tuple[str, ...]
    hpo_ids: tuple[str, ...]
    omim_ids: tuple[str, ...]
    pmids: tuple[str, ...]


def hpo_ids(texts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({f"HP:{m}" for t in texts for m in _HPO.findall(t)}))


def omim_ids(texts: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({f"OMIM:{m}" for t in texts for m in _OMIM.findall(_HPO.sub(" ", t))}))


def parse(path: Path) -> list[PanelGene]:
    with gzip.open(path, "rt", encoding="utf-8") as h:
        doc = json.load(h)
    out = []
    for g in doc["genes"]:
        if g.get("entity_type") != "gene":
            continue
        panel, data = g["panel"], g.get("gene_data") or {}
        phenotypes = tuple(p.strip() for p in g.get("phenotypes") or [] if p and p.strip())
        out.append(
            PanelGene(
                panel_id=panel["id"],
                panel_name=panel["name"],
                panel_version=panel.get("version", ""),
                disease_group=panel.get("disease_group") or "",
                relevant_disorders=tuple(panel.get("relevant_disorders") or ()),
                gene=data.get("hgnc_symbol") or data.get("gene_symbol") or g["entity_name"],
                hgnc_id=data.get("hgnc_id") or "",
                evidence=EVIDENCE_LEVEL.get(str(g.get("confidence_level")), "red"),
                mode_of_inheritance=g.get("mode_of_inheritance") or "",
                phenotypes=phenotypes,
                hpo_ids=hpo_ids(phenotypes),
                omim_ids=omim_ids(phenotypes),
                pmids=tuple(
                    sorted({f"PMID:{p.strip()}" for p in g.get("publications") or [] if p.strip().isdigit()})
                ),
            )
        )
    return out
