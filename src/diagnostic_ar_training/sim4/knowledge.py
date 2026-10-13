"""sim4 knowledge: E0's own cut (ADR-0019 §3) with every literature negation removed (§4).

Inputs are only HPO 2025-03-03 (`hp.json`, `phenotype.hpoa`) and E0's `genes_to_phenotype.txt`
(GraPhens@7aef83d). Rows with qualifier NOT, frequency 0/n, 0% or HP:0040285 (Excluded) are dropped before
anything is pooled, and so are E0's rows whose (disease, term) HPOA only states as NOT. Patient findings are
restricted to the phenotypic-abnormality subtree, strictly below HP:0000118.

E0's output index is the sorted set of its gene symbols, `"-"` at 0; it is kept as is, and `"-"` is never
simulated.
"""

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from diagnostic_ar_training.lineage.hashing import sha256_json
from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
from diagnostic_ar_training.ontology import ONSET, PHENOTYPIC_ABNORMALITY, Ontology
from diagnostic_ar_training.sim4.frequency import is_zero_frequency, pooled_frequency

ONTOLOGY_SOURCE = "hpo_ontology_2025_03_03"
ANNOTATIONS_SOURCE = "hpo_annotations_2025_03_03"
GENES_SOURCE = "e0_genes_to_phenotype"
SOURCES = (ONTOLOGY_SOURCE, ANNOTATIONS_SOURCE, GENES_SOURCE)

DASH = "-"
GROUP_MIN_GENES = 5
NO_DISEASE = "NODISEASE"


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@dataclass(frozen=True)
class Entity:
    """A disease of a gene with its findings; `kind` is disease, group (ORPHA linking >= 5 genes) or
    nodisease (E0's rows without a disease id, pooled per gene)."""

    id: str
    kind: str
    terms: tuple[str, ...]
    frequencies: tuple[float | None, ...]
    duplicate: bool = False
    """An OMIM and an ORPHA entity of the same gene with the same name: each counts half."""


@dataclass
class Knowledge:
    ontology: Ontology
    genes: tuple[str, ...]
    entities: dict[str, tuple[Entity, ...]]
    e0_rows: dict[str, tuple[str, ...]]
    """E0's recipe: the gene's filtered rows, duplicates kept, in file order."""
    disease_counts: Counter
    """Term -> HPOA 2025-03-03 diseases annotated with it or a descendant (after the filters)."""
    n_diseases: int
    inheritance: dict[str, frozenset[str]]
    onsets: dict[str, tuple[str, ...]]
    stats: dict = field(default_factory=dict)
    _profiles: dict[str, frozenset[str]] = field(default_factory=dict, repr=False)
    _up: dict = field(default_factory=dict, repr=False)

    @cached_property
    def gene_index(self) -> dict[str, int]:
        return {g: i for i, g in enumerate(self.genes)}

    @cached_property
    def simulable_genes(self) -> tuple[str, ...]:
        return tuple(g for g in self.genes if g != DASH and self.entities.get(g))

    def profile(self, gene: str) -> frozenset[str]:
        if gene not in self._profiles:
            self._profiles[gene] = frozenset(t for e in self.entities.get(gene, ()) for t in e.terms)
        return self._profiles[gene]

    def entity_weights(self, gene: str, group_weight: float) -> list[float]:
        """Equal weights per disease; groups and the no-disease pool are down-weighted when the gene has a
        specific disease; same-name OMIM/ORPHA duplicates count half each."""
        ents = self.entities.get(gene, ())
        specific = any(e.kind == "disease" for e in ents)
        out = []
        for e in ents:
            w = group_weight if specific and e.kind != "disease" else 1.0
            out.append(w * (0.5 if e.duplicate else 1.0))
        return out

    def is_finding(self, term: str) -> bool:
        return term != PHENOTYPIC_ABNORMALITY and PHENOTYPIC_ABNORMALITY in self.ontology.ancestors(term)

    def up_levels(self, term: str) -> tuple[tuple[str, ...], ...]:
        """Ancestors that are findings, by shortest is_a distance (level 1 = parents)."""
        if term not in self._up:
            self._up[term] = self._levels(term, self.ontology.parents, 99)
        return self._up[term]

    def _levels(self, term: str, step, depth: int) -> tuple[tuple[str, ...], ...]:
        seen, frontier, out = {term}, [term], []
        while frontier and len(out) < depth:
            nxt = sorted({n for t in frontier for n in step(t) if n not in seen and self.is_finding(n)})
            seen.update(nxt)
            if nxt:
                out.append(tuple(nxt))
            frontier = nxt
        return tuple(out)

    def content_hash(self) -> str:
        return sha256_json(
            {
                "genes": list(self.genes),
                "entities": {
                    g: [[e.id, e.kind, e.duplicate, list(e.terms), list(e.frequencies)] for e in ents]
                    for g, ents in sorted(self.entities.items())
                },
                "e0_rows": {g: list(r) for g, r in sorted(self.e0_rows.items())},
            }
        )


def _read_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        lines = (line for line in handle if not line.startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def build(ontology: Ontology, hpoa: list[dict], g2p: list[dict]) -> Knowledge:
    stats: dict = {"hpoa": Counter(), "genes_to_phenotype": Counter(), "entities": Counter()}
    sh, sg, se = stats["hpoa"], stats["genes_to_phenotype"], stats["entities"]
    kb = Knowledge(ontology, (), {}, {}, Counter(), 0, {}, {})

    def finding(term: str, counter: Counter) -> str | None:
        resolved = ontology.resolve(term)
        if resolved is None:
            counter["dropped_unknown_term"] += 1
            return None
        if resolved != term:
            counter["remapped_term"] += 1
        if not kb.is_finding(resolved):
            counter["dropped_not_phenotypic_abnormality"] += 1
            return None
        return resolved

    names: dict[str, str] = {}
    positive: dict[tuple[str, str], list[str]] = defaultdict(list)
    stated: set[tuple[str, str]] = set()
    negated: set[tuple[str, str]] = set()
    inheritance: dict[str, set[str]] = defaultdict(set)
    onsets: dict[str, set[str]] = defaultdict(set)
    sh["rows"] = len(hpoa)
    for r in hpoa:
        disease, term = r["database_id"], r["hpo_id"]
        names.setdefault(disease, r["disease_name"])
        if r["qualifier"] == "NOT":
            sh[f"dropped_not_aspect_{r['aspect']}"] += 1
            if r["aspect"] == "P":
                negated.add((disease, term))
            continue
        if r["aspect"] == "I":
            inheritance[disease].add(term)
            continue
        if r["aspect"] == "C" and ontology.is_a(term, ONSET):
            onsets[disease].add(term)
            continue
        if r["aspect"] != "P":
            continue
        sh["rows_p_positive"] += 1
        stated.add((disease, term))
        if is_zero_frequency(r["frequency"]):
            sh["dropped_zero_frequency"] += 1
            continue
        positive[(disease, term)].append(r["frequency"])
    zero_only = {p for p in stated if p not in positive}
    sh["pairs_zero_frequency_only"] = len(zero_only)
    sh["pairs_not_only"] = len(negated - stated)
    sh["pairs_pooled_multi_row"] = sum(len(v) > 1 for v in positive.values())
    pooled = {p: pooled_frequency(v) for p, v in positive.items()}

    by_disease: dict[str, set[str]] = defaultdict(set)
    pair_drops: Counter = Counter()
    for disease, term in pooled:
        if t := finding(term, pair_drops):
            by_disease[disease].add(t)
    sh.update({f"pairs_{k}": v for k, v in pair_drops.items()})
    sh["pairs_kept"] = sum(len(v) for v in by_disease.values())
    counts: Counter = Counter()
    for terms in by_disease.values():
        closed = set(terms)
        for t in terms:
            closed |= ontology.ancestors(t)
        counts.update(closed)
    kb.disease_counts, kb.n_diseases = counts, len(by_disease)
    kb.inheritance = {d: frozenset(v) for d, v in inheritance.items()}
    kb.onsets = {d: tuple(sorted(v)) for d, v in onsets.items()}

    genes = sorted({r["gene_symbol"] for r in g2p})
    kb.genes = tuple(genes)
    sg["rows"], sg["genes"] = len(g2p), len(genes)
    disease_genes: dict[str, set[str]] = defaultdict(set)
    rows: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for r in g2p:
        gene, disease, term = r["gene_symbol"], r["disease_id"], r["hpo_id"]
        if gene == DASH:
            sg["dropped_dash_gene"] += 1
            continue
        f = r["frequency"]
        if is_zero_frequency(f):
            sg["dropped_zero_frequency"] += 1
            continue
        if disease and (disease, term) in negated and (disease, term) not in stated:
            sg["dropped_not_only_in_hpoa"] += 1
            continue
        if disease and (disease, term) in zero_only:
            sg["dropped_zero_frequency_only_in_hpoa"] += 1
            continue
        if (t := finding(term, sg)) is None:
            continue
        if disease:
            disease_genes[disease].add(gene)
        rows[gene].append((disease, t, f))
    sg["rows_kept"] = sum(len(v) for v in rows.values())

    for gene in genes:
        gene_rows = rows.get(gene, [])
        kb.e0_rows[gene] = tuple(t for _, t, _ in gene_rows)
        per_disease: dict[str, dict[str, list]] = defaultdict(dict)
        for disease, term, f in gene_rows:
            per_disease[disease].setdefault(term, []).append(f)
        ents = []
        for disease in sorted(per_disease):
            terms = sorted(per_disease[disease])
            if disease:
                freqs = tuple(
                    pooled[(disease, t)]
                    if (disease, t) in pooled
                    else pooled_frequency(per_disease[disease][t])
                    for t in terms
                )
                kind = (
                    "group"
                    if disease.startswith("ORPHA:") and len(disease_genes[disease]) >= GROUP_MIN_GENES
                    else "disease"
                )
                ents.append(Entity(disease, kind, tuple(terms), freqs))
            else:
                n_rows = sum(len(v) for v in per_disease[disease].values())
                sg["deduped_no_disease_rows"] += n_rows - len(terms)
                freqs = tuple(pooled_frequency(per_disease[disease][t]) for t in terms)
                ents.append(Entity(f"{NO_DISEASE}:{gene}", "nodisease", tuple(terms), freqs))
        omim = {_norm_name(names.get(e.id, "")) for e in ents if e.id.startswith("OMIM:")} - {""}
        dup = {e.id for e in ents if e.id.startswith("ORPHA:") and _norm_name(names.get(e.id, "")) in omim}
        if dup:
            dup_names = {_norm_name(names[d]) for d in dup}
            dup |= {
                e.id
                for e in ents
                if e.id.startswith("OMIM:") and _norm_name(names.get(e.id, "")) in dup_names
            }
            ents = [Entity(e.id, e.kind, e.terms, e.frequencies, e.id in dup) for e in ents]
            se["orpha_name_duplicates_of_omim"] += sum(1 for d in dup if d.startswith("ORPHA:"))
        if ents:
            kb.entities[gene] = tuple(ents)
            for e in ents:
                se[e.kind] += 1
        elif gene != DASH:
            se["genes_without_findings"] += 1
    se["genes_simulable"] = len(kb.simulable_genes)
    se["genes_no_disease_only"] = sum(
        1 for ents in kb.entities.values() if all(e.kind == "nodisease" for e in ents)
    )
    se["frequency_known_share"] = round(
        sum(f is not None for ents in kb.entities.values() for e in ents for f in e.frequencies)
        / max(1, sum(len(e.frequencies) for ents in kb.entities.values() for e in ents)),
        4,
    )
    kb.stats = {k: dict(sorted(v.items())) for k, v in stats.items()}
    return kb


def lineage_inputs() -> list[dict]:
    sources = load_sources()
    return [sources[name].as_input() for name in SOURCES]


def load_knowledge() -> Knowledge:
    """Build sim4's knowledge from the pinned sources (deterministic; ~20 s)."""
    ontology = Ontology.from_json(open_source(ONTOLOGY_SOURCE, Purpose.SIMULATE))
    hpoa = _read_tsv(open_source(ANNOTATIONS_SOURCE, Purpose.SIMULATE))
    g2p = _read_tsv(open_source(GENES_SOURCE, Purpose.SIMULATE))
    return build(ontology, hpoa, g2p)
