"""Evaluation literature panel (ADR-0012 G4): the frozen disease split and the panel rows.

The split picks, once and deterministically, which (gene, main disease) units
the literature panel evaluates. Every other unit is "construction": only those
may ever feed literature-derived enrichment of simulator profiles. The panel
rows are then extracted by hand or with an LLM for the evaluation units only,
and `validate_rows` checks and annotates them before they become an artifact.
"""

import csv
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY, Ontology

ANALYSIS_001_GENES = (
    "NF1", "LMNA", "FBN1", "PTPN11", "KMT2D", "TBX5", "UMOD", "FBXL4", "SPTAN1", "ITPR1",
)  # fmt: skip
INHERITANCE_TERMS = {"AD": "HP:0000006", "AR": "HP:0000007", "XL": "HP:0001417"}
TRAIN_BINS = ("0", "1-9", ">=10")
SPLIT_COLUMNS = (
    "rank", "role", "gene", "symbol", "disease_id", "disease_ids", "disease_name", "organ_system",
    "organ_system_label", "inheritance", "r1_train_patients", "train_bin", "r1_dev_patients",
    "orphanet_prevalence", "sim_weight",
)  # fmt: skip


@dataclass(frozen=True)
class Unit:
    """A vocabulary gene and its main disease entity (highest simulation weight)."""

    gene: str
    symbol: str
    disease_id: str
    disease_ids: tuple[str, ...]
    disease_name: str
    organ_system: str
    organ_system_label: str
    inheritance: str
    r1_train_patients: int
    r1_dev_patients: int
    orphanet_prevalence: float | None
    sim_weight: float

    @property
    def train_bin(self) -> str:
        n = self.r1_train_patients
        return "0" if n == 0 else ("1-9" if n < 10 else ">=10")

    def strata(self) -> tuple[tuple[str, str], ...]:
        return (("organ", self.organ_system), ("inheritance", self.inheritance), ("train", self.train_bin))


def inheritance_class(terms: list[str], ontology: Ontology) -> str:
    """AD, AR or XL when the terms name exactly one of them; otherwise "other"."""
    classes = {name for t in terms for name, root in INHERITANCE_TERMS.items() if ontology.is_a(t, root)}
    return classes.pop() if len(classes) == 1 else "other"


def organ_system(terms: set[str], ontology: Ontology) -> str:
    """The child of Phenotypic abnormality under which most of the disease's terms fall."""
    top = set(ontology.children(PHENOTYPIC_ABNORMALITY))
    counts: Counter = Counter()
    for t in terms:
        for system in (ontology.ancestors(t) | {t}) & top:
            counts[system] += 1
    if not counts:
        return "none"
    return min(counts, key=lambda s: (-counts[s], s))


def hpoa_phenotypes(path: Path, ontology: Ontology, masked_pmids: set[str]) -> tuple[dict, dict]:
    """Disease id -> positive phenotype terms (masked rows dropped), and disease id -> name."""
    terms: dict[str, set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if not line.startswith("#"))
        for row in csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE):
            names.setdefault(row["database_id"], row["disease_name"])
            if row["aspect"] != "P" or row["qualifier"] == "NOT":
                continue
            if set(row["reference"].split(";")) & masked_pmids:
                continue
            if term := ontology.resolve(row["hpo_id"]):
                terms[row["database_id"]].add(term)
    return terms, names


def patients_per_gene(cases) -> Counter:
    return Counter(c.gene.upper() for c in cases)


def units(
    genes_built: dict,
    ontology: Ontology,
    phenotypes: dict[str, set[str]],
    names: dict[str, str],
    train: Counter,
    dev: Counter,
) -> list[Unit]:
    """One unit per vocabulary gene that has a simulable disease entity."""
    out = []
    for v3, current in sorted(genes_built["vocabulary"].items()):
        gene = genes_built["genes"].get(current) if current else None
        entities = [e for e in (gene or {}).get("entities", []) if e["simulable"]]
        if not entities:
            continue
        main = min(entities, key=lambda e: (-e["sim_weight"], e["entity"]))
        terms = set().union(*(phenotypes.get(i, set()) for i in main["profile_ids"]))
        system = organ_system(terms, ontology)
        keys = {v3.upper(), current.upper()}
        out.append(
            Unit(
                gene=v3,
                symbol=current,
                disease_id=main["entity"],
                disease_ids=tuple(main["ids"]),
                disease_name=next((names[i] for i in main["ids"] if i in names), ""),
                organ_system=system,
                organ_system_label=ontology.labels.get(system, system),
                inheritance=inheritance_class(main["inheritance"], ontology),
                r1_train_patients=sum(train[k] for k in keys),
                r1_dev_patients=sum(dev[k] for k in keys),
                orphanet_prevalence=main["prevalence"],
                sim_weight=main["sim_weight"],
            )
        )
    return out


def _sqrt_targets(pool: list[Unit]) -> dict[tuple[str, str], float]:
    """Square-root allocation per margin: a compromise between proportional and equal shares."""
    targets = {}
    for dim in ("organ", "inheritance", "train"):
        counts = Counter(v for u in pool for d, v in u.strata() if d == dim)
        total = sum(math.sqrt(n) for n in counts.values())
        targets.update({(dim, v): math.sqrt(n) / total for v, n in counts.items()})
    return targets


def select(
    pool: list[Unit],
    anchors: tuple[str, ...] = ANALYSIS_001_GENES,
    size: int = 60,
    reserves: int = 20,
    seed: int = 20260930,
    dev_share: float = 0.5,
    dev_min: int = 10,
) -> list[tuple[Unit, str]]:
    """Anchors, then `size - len(anchors)` sampled units, then an ordered reserve list.

    Each pick is the candidate with the largest total deficit against the
    square-root targets on the three margins (organ system, inheritance,
    R1-train patient bin); ties go to a seeded shuffle. Picks alternate between
    units with >= `dev_min` R1-dev patients and the rest until the dev quota
    (`dev_share` of the sampled picks) is met or that pool runs out.
    """
    by_gene = {u.gene: u for u in pool}
    missing = [g for g in anchors if g not in by_gene]
    if missing:
        raise ValueError(f"anchor genes without a simulable unit: {missing}")
    chosen: list[tuple[Unit, str]] = [(by_gene[g], "anchor") for g in anchors]
    remaining = sorted((u for u in pool if u.gene not in set(anchors)), key=lambda u: u.gene)
    random.Random(seed).shuffle(remaining)
    priority = {u.gene: i for i, u in enumerate(remaining)}
    targets = _sqrt_targets(pool)
    counts: Counter = Counter(s for u, _ in chosen for s in u.strata())

    def pick(candidates: list[Unit]) -> Unit:
        k = len(chosen) + 1
        return max(
            candidates,
            key=lambda u: (sum(targets[s] * k - counts[s] for s in u.strata()), -priority[u.gene]),
        )

    n_sampled = size - len(anchors)
    dev_quota = round(n_sampled * dev_share)
    dev_taken = 0
    for i in range(n_sampled + reserves):
        sampled = i < n_sampled
        dev_pool = [u for u in remaining if u.r1_dev_patients >= dev_min]
        other_pool = [u for u in remaining if u.r1_dev_patients < dev_min]
        if sampled and dev_taken < dev_quota and dev_pool and (i % 2 == 0 or not other_pool):
            candidates = dev_pool
        elif sampled and other_pool:
            candidates = other_pool
        else:
            candidates = remaining
        unit = pick(candidates)
        dev_taken += sampled and unit.r1_dev_patients >= dev_min
        remaining.remove(unit)
        chosen.append((unit, "sampled" if sampled else "reserve"))
        counts.update(unit.strata())
    return chosen


def split_rows(chosen: list[tuple[Unit, str]]) -> list[dict]:
    rows = []
    for rank, (u, role) in enumerate(chosen, start=1):
        d = asdict(u)
        d["disease_ids"] = ";".join(u.disease_ids)
        d["orphanet_prevalence"] = "" if u.orphanet_prevalence is None else u.orphanet_prevalence
        rows.append({"rank": rank, "role": role, "train_bin": u.train_bin, **d})
    return rows


def write_tsv(rows: list[dict], columns: tuple[str, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({c: r.get(c, "") for c in columns} for r in rows)


def read_tsv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def split_summary(rows: list[dict], pool: list[Unit]) -> dict:
    def margins(items) -> dict:
        return {
            dim: dict(sorted(Counter(r[col] for r in items).items()))
            for dim, col in (
                ("organ", "organ_system_label"),
                ("inheritance", "inheritance"),
                ("train", "train_bin"),
            )
        }

    panel = [r for r in rows if r["role"] != "reserve"]
    return {
        "pool_units": len(pool),
        "panel_units": len(panel),
        "reserve_units": len(rows) - len(panel),
        "panel_with_dev_ge_10": sum(int(r["r1_dev_patients"]) >= 10 for r in panel),
        "panel_margins": margins(panel),
        "pool_margins": margins([split_rows([(u, "pool")])[0] for u in pool]),
    }


# --- Panel rows -----------------------------------------------------------------

SOURCE_KINDS = ("genereviews", "cohort_paper", "orphanet")
PANEL_COLUMNS = (
    "gene", "disease_id", "disease_name", "feature_label", "hpo_id", "hpo_label", "prevalence",
    "prevalence_low", "prevalence_high", "n_affected", "n_assessed", "sex_restriction", "age_note",
    "source_kind", "citation", "section", "evidence_quote", "access_path", "source_pmids",
    "source_in_hpoa", "source_r1_part", "independent",
)  # fmt: skip
CURATED_COLUMNS = PANEL_COLUMNS[:18]
MAX_QUOTE_WORDS = 25
_PMID = re.compile(r"PMID:?\s*(\d+)")


def _float(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def validate_rows(
    curated: list[dict],
    split_rows_: list[dict],
    ontology: Ontology,
    hpoa_pmids: set[str],
    r1_pmids: dict[str, str],
) -> tuple[list[dict], list[str]]:
    """Check curated rows and add the independence columns; returns (rows, problems).

    `hpoa_pmids`: every PMID cited by a phenotype.hpoa row. `r1_pmids`: PMID ->
    "train" or "heldout" for R1 publications.
    """
    units_by_gene = {r["gene"]: r for r in split_rows_}
    problems, out = [], []
    for i, row in enumerate(curated, start=2):
        where = f"row {i} ({row.get('gene')} / {row.get('feature_label')})"
        unit = units_by_gene.get(row["gene"])
        if unit is None:
            problems.append(f"{where}: gene is not an evaluation unit of the split")
            continue
        if row["disease_id"] not in unit["disease_ids"].split(";"):
            problems.append(f"{where}: disease {row['disease_id']} is not the unit's disease")
        term = ontology.resolve(row["hpo_id"])
        if term is None or term != row["hpo_id"]:
            problems.append(f"{where}: {row['hpo_id']} is not a current HPO id (resolves to {term})")
        p, lo, hi = (_float(row[c]) for c in ("prevalence", "prevalence_low", "prevalence_high"))
        if p is None or not 0 <= p <= 1:
            problems.append(f"{where}: prevalence must be in [0, 1]")
        elif (lo is not None and not lo <= p) or (hi is not None and not p <= hi):
            problems.append(f"{where}: prevalence {p} outside its range [{lo}, {hi}]")
        if lo is not None and hi is not None and not 0 <= lo <= hi <= 1:
            problems.append(f"{where}: bad range [{lo}, {hi}]")
        if row["source_kind"] not in SOURCE_KINDS:
            problems.append(f"{where}: source_kind must be one of {SOURCE_KINDS}")
        if not row["citation"].strip() or not row["evidence_quote"].strip():
            problems.append(f"{where}: citation and evidence quote are required")
        if len(row["evidence_quote"].split()) > MAX_QUOTE_WORDS:
            problems.append(f"{where}: evidence quote longer than {MAX_QUOTE_WORDS} words")
        pmids = sorted(set(_PMID.findall(row["citation"])))
        in_hpoa = any(p_ in hpoa_pmids for p_ in pmids)
        parts = sorted({r1_pmids[p_] for p_ in pmids if p_ in r1_pmids})
        r1_part = ";".join(parts) if parts else "none"
        out.append(
            {
                **{c: row.get(c, "") for c in CURATED_COLUMNS},
                "hpo_label": ontology.labels.get(row["hpo_id"], ""),
                "source_pmids": ";".join(pmids),
                "source_in_hpoa": str(in_hpoa).lower(),
                "source_r1_part": r1_part,
                "independent": str(
                    row["source_kind"] != "orphanet" and not in_hpoa and "train" not in parts
                ).lower(),
            }
        )
    keys = Counter((r["gene"], r["hpo_id"]) for r in out)
    problems += [f"duplicate feature {k}" for k, n in keys.items() if n > 1]
    return out, problems


def hpoa_cited_pmids(path: Path) -> set[str]:
    out = set()
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if not line.startswith("#"))
        for row in csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE):
            out.update(m for ref in row["reference"].split(";") if (m := ref.removeprefix("PMID:")) != ref)
    return out


def crosscheck_sample(rows: list[dict], fraction: float = 0.1, seed: int = 20260930) -> list[int]:
    """Indices of a seeded random `fraction` of the rows (at least one)."""
    k = max(1, math.ceil(len(rows) * fraction))
    return sorted(random.Random(seed).sample(range(len(rows)), k))


def agrees(a: dict, b: dict, tolerance: float = 0.10) -> bool:
    """Two extractions agree if their ranges overlap or their point estimates differ by <= tolerance."""

    def interval(x: dict) -> tuple[float, float] | None:
        p = _float(x.get("prevalence", ""))
        lo = _float(x.get("prevalence_low", ""))
        hi = _float(x.get("prevalence_high", ""))
        if p is None and lo is None and hi is None:
            return None
        lo = lo if lo is not None else p
        hi = hi if hi is not None else p
        return (lo if lo is not None else hi, hi if hi is not None else lo)

    ia, ib = interval(a), interval(b)
    if ia is None or ib is None:
        return False
    if ia[0] <= ib[1] and ib[0] <= ia[1]:
        return True
    pa, pb = _float(a.get("prevalence", "")), _float(b.get("prevalence", ""))
    return pa is not None and pb is not None and abs(pa - pb) <= tolerance + 1e-9
