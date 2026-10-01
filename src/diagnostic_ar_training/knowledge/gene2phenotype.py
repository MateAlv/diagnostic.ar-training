"""Gene2Phenotype (EBI G2P): curated gene-disease records with HPO terms.

The `gene2phenotype` source is G2P's all-panels CSV download (one row per
record, with the panels it belongs to). Each record keeps its panels, because
DDG2P (panel DD) was curated partly from the DDD study, a sealed eval cohort
(ADR-0013 amendment 1, DDD caveat).

Only curator-reviewed publications (`publications`) are kept. The column
`additional mined publications` comes from G2P's machine-learning literature
pipeline and is not reviewed by curators, so it is ignored.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

CONFIDENCE_RANK = {"definitive": 5, "strong": 4, "moderate": 3, "limited": 2, "disputed": 1, "refuted": 0}
PANELS = ("DD", "Eye", "Skin", "Skeletal", "Cardiac", "Cancer", "Ear")
ALLELIC_REQUIREMENT_HPO = {
    "biallelic_autosomal": "HP:0000007",
    "monoallelic_autosomal": "HP:0000006",
    "monoallelic_X_hemizygous": "HP:0001419",
    "monoallelic_X_heterozygous": "HP:0001423",
    "monoallelic_X": "HP:0001417",
    "monoallelic_Y_hemizygous": "HP:0001450",
    "mitochondrial": "HP:0001427",
}


@dataclass(frozen=True)
class Record:
    g2p_id: str
    gene: str
    hgnc_id: str
    previous_symbols: tuple[str, ...]
    disease_name: str
    disease_ids: tuple[str, ...]
    """OMIM and MONDO ids, when the record gives them."""
    allelic_requirement: str
    cross_cutting_modifiers: tuple[str, ...]
    confidence: str
    variant_consequences: tuple[str, ...]
    molecular_mechanism: str
    hpo_ids: tuple[str, ...]
    pmids: tuple[str, ...]
    panels: tuple[str, ...]

    @property
    def confidence_rank(self) -> int:
        return CONFIDENCE_RANK.get(self.confidence, -1)


def _split(value: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in value.split(";") if x.strip())


def parse(path: Path) -> list[Record]:
    out = []
    with Path(path).open(encoding="utf-8", newline="") as h:
        for row in csv.DictReader(h):
            ids = []
            if row["disease mim"].strip():
                ids.append(f"OMIM:{row['disease mim'].strip()}")
            if row["disease MONDO"].strip():
                ids.append(row["disease MONDO"].strip())
            hgnc = row["hgnc id"].strip()
            out.append(
                Record(
                    g2p_id=row["g2p id"],
                    gene=row["gene symbol"].strip(),
                    hgnc_id=f"HGNC:{hgnc}" if hgnc and not hgnc.startswith("HGNC:") else hgnc,
                    previous_symbols=_split(row["previous gene symbols"]),
                    disease_name=row["disease name"].strip(),
                    disease_ids=tuple(ids),
                    allelic_requirement=row["allelic requirement"].strip(),
                    cross_cutting_modifiers=_split(row["cross cutting modifier"]),
                    confidence=row["confidence"].strip().lower(),
                    variant_consequences=_split(row["variant consequence"]),
                    molecular_mechanism=row["molecular mechanism"].strip(),
                    hpo_ids=tuple(t for t in _split(row["phenotypes"]) if t.startswith("HP:")),
                    pmids=tuple(f"PMID:{p}" for p in _split(row["publications"]) if p.isdigit()),
                    panels=_split(row["panel"]),
                )
            )
    return out
