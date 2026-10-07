"""The safe-v1 knowledge artifact: per gene of E0's vocabulary, what HPO, Orphanet and HGNC make impossible.

Rules, regexes and onset tables follow `scripts/analysis/p2_probes.py` (P2-PROBES-v1), with two changes:
- Infantile onset (HPO HP:0003593, Orphanet "Infancy") has lower bound 0, a conservative choice (PHASE2.md).
- HGNC locations are looked up by approved symbol first; a previous or alias symbol is used only when no
  approved symbol has that name, so another gene's alias cannot lend its chromosome to a symbol.

Records per gene:
- `sex`: limited to one sex, with the reasons (`y_chromosome`, `names`, `y_linked_inheritance`);
- `onset`: the strict earliest onset in years, with per-disease evidence;
- `obligate`: the obligate phenotypes of each annotated disease.
"""

import csv
import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "safe-kb/1"

# Lower bound, in years, of each onset class.
HPO_ONSET_LOWER: dict[str, float] = {
    "HP:0030674": -1,  # antenatal
    "HP:0011460": -1,  # embryonal
    "HP:0011461": -1,  # fetal
    "HP:0034199": -1,  # late first trimester
    "HP:0034198": -1,  # second trimester
    "HP:0034197": -1,  # third trimester
    "HP:0003577": 0,  # congenital
    "HP:0003623": 0,  # neonatal
    "HP:0410280": 0,  # pediatric
    "HP:0003593": 0,  # infantile
    "HP:0011463": 1,  # childhood
    "HP:0003621": 5,  # juvenile
    "HP:0011462": 16,  # young adult
    "HP:0025708": 16,  # early young adult
    "HP:0025709": 19,  # intermediate young adult
    "HP:0025710": 25,  # late young adult
    "HP:0003581": 16,  # adult
    "HP:0003596": 40,  # middle age
    "HP:0003584": 60,  # late
}
ORPHANET_ONSET_LOWER: dict[str, float] = {
    "Antenatal": -1,
    "Neonatal": 0,
    "Infancy": 0,
    "Childhood": 1,
    "Adolescent": 10,
    "Adult": 16,
    "Elderly": 60,
    "All ages": 0,
}

Y_LINKED = "HP:0001450"
MALE_NAMES = re.compile(
    r"sperm|zoospermia|acrosom|flagell|sertoli|anorchia|cryptorchidism|hypospadias|"
    r"male infertility|persistent mullerian duct|testicular regression|micropenis",
    re.I,
)
FEMALE_NAMES = re.compile(
    r"ovarian (failure|insufficiency|dysgenesis|hyperstimulation)|premature ovarian|oocyte|"
    r"female infertility|hydatidiform mole|preimplantation embryonic lethality|embryonic arrest|"
    r"zygot|empty follicle|mullerian aplasia|mayer-rokitansky|polycystic ovary|"
    r"recurrent pregnancy loss|pre-?eclampsia",
    re.I,
)
SEX_REVERSAL = re.compile(
    r"sex reversal|gonadal dysgenesis|disorder of sex development|swyer|androgen insensitivity|"
    r"46,? ?x[xy]",
    re.I,
)
OBLIGATE_FREQUENCIES = ("HP:0040280", "100%")
OBLIGATE_MIN_N = 5
_FRACTION = re.compile(r"(\d+)/(\d+)")


def is_obligate(frequency: str) -> bool:
    """HP:0040280 (obligate), "100%", or n/n with n >= 5."""
    m = _FRACTION.fullmatch(frequency)
    return frequency in OBLIGATE_FREQUENCIES or (
        bool(m) and m.group(1) == m.group(2) and int(m.group(2)) >= OBLIGATE_MIN_N
    )


def _pmid(ref: str) -> str:
    return ref.strip().removeprefix("PMID:")


@dataclass
class Annotations:
    """What phenotype.hpoa says, after masking. Names come from every row, masked or not."""

    names: dict[str, str] = field(default_factory=dict)
    inheritance: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    onset_terms: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    phenotypes: dict[str, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    stats: Counter = field(default_factory=Counter)


def read_genes_to_disease(path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    with Path(path).open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if r["association_type"] != "POLYGENIC":
                out[r["gene_symbol"]].add(r["disease_id"])
    return dict(out)


def read_annotations(path: Path, masked_pmids: Iterable[str]) -> Annotations:
    masked = {_pmid(p) for p in masked_pmids}
    out = Annotations()
    with Path(path).open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader((x for x in f if not x.startswith("#")), delimiter="\t")
        for r in rows:
            d = r["database_id"]
            out.names.setdefault(d, r["disease_name"])
            out.stats["rows"] += 1
            if {_pmid(x) for x in r["reference"].split(";")} & masked:
                out.stats["rows_masked_heldout_pmid"] += 1
                continue
            if r["aspect"] == "I":
                out.inheritance[d].add(r["hpo_id"])
            elif r["aspect"] == "C":
                out.onset_terms[d].add(r["hpo_id"])
            elif r["aspect"] == "P" and r["qualifier"] != "NOT":
                out.phenotypes[d].append((r["hpo_id"], r["frequency"]))
    return out


def read_orphanet_onsets(path: Path) -> dict[str, set[str]]:
    """ORPHA:<code> -> Orphanet AverageAgeOfOnset class names with a lower bound."""
    out: dict[str, set[str]] = defaultdict(set)
    for _, el in ET.iterparse(path):
        if el.tag == "Disorder":
            code = el.findtext("OrphaCode")
            for a in el.iter("AverageAgeOfOnset"):
                if a.findtext("Name") in ORPHANET_ONSET_LOWER:
                    out[f"ORPHA:{code}"].add(a.findtext("Name"))
            el.clear()
    return dict(out)


def read_hgnc_locations(path: Path) -> dict[str, str]:
    approved, other = {}, {}
    with Path(path).open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            approved[r["symbol"].strip('"')] = r["location"]
            for sym in (r["prev_symbol"] + "|" + r["alias_symbol"]).split("|"):
                if sym.strip('"'):
                    other.setdefault(sym.strip('"'), r["location"])
    return {**other, **approved}


def disease_onset(d: str, ann: Annotations, orphanet: dict[str, set[str]]) -> float | None:
    vals = [HPO_ONSET_LOWER[t] for t in ann.onset_terms.get(d, ()) if t in HPO_ONSET_LOWER]
    vals += [ORPHANET_ONSET_LOWER[c] for c in orphanet.get(d, ())]
    return min(vals) if vals else None


def sex_limitation(diseases: set[str], ann: Annotations, location: str) -> tuple[str | None, list[str], bool]:
    """(limit, reasons, ambiguous). A gene matching both sexes is limited to neither (`ambiguous`)."""
    names = [ann.names.get(d, "") for d in diseases]
    reversal = any(SEX_REVERSAL.search(n) for n in names)
    named = [ann.names[d] for d in diseases if d in ann.names]

    def all_named(pattern: re.Pattern) -> bool:
        return bool(named) and all(pattern.search(n) for n in named) and not reversal

    male = []
    if location.startswith("Y") and "X" not in location and not reversal:
        male.append("y_chromosome")
    if all_named(MALE_NAMES):
        male.append("names")
    inherited = [d for d in diseases if d in ann.inheritance]
    if inherited and all(ann.inheritance[d] == {Y_LINKED} for d in inherited) and not reversal:
        male.append("y_linked_inheritance")
    female = ["names"] if all_named(FEMALE_NAMES) else []
    if male and female:
        return None, [], True
    if male:
        return "male", male, False
    if female:
        return "female", female, False
    return None, [], False


def build(
    genes: Iterable[str],
    genes_to_disease: dict[str, set[str]],
    ann: Annotations,
    orphanet: dict[str, set[str]],
    hgnc_locations: dict[str, str],
    ancestors_or_self: Callable[[str], Iterable[str]],
) -> tuple[dict, dict]:
    """(kb, stats), uncurated. Plain JSON-serialisable and deterministic."""
    out_genes: dict[str, dict] = {}
    names: dict[str, str] = {}
    obligate_terms: set[str] = set()
    stats: Counter = Counter()
    for g in sorted(set(genes)):
        ds = genes_to_disease.get(g, set())
        record: dict = {"diseases": sorted(ds)}
        limit, reasons, ambiguous = sex_limitation(ds, ann, hgnc_locations.get(g, ""))
        stats["genes_sex_ambiguous_dropped"] += ambiguous
        if limit:
            record["sex"] = {"limit": limit, "reasons": reasons}
        onsets = {d: disease_onset(d, ann, orphanet) for d in ds}
        known = [o for o in onsets.values() if o is not None]
        if known:
            stats["genes_with_lenient_onset"] += 1
            if all(onsets[d] is not None for d in ds if d.startswith("OMIM:")):
                record["onset"] = {
                    "earliest_years": min(known),
                    "diseases": {
                        d: {
                            "lower_years": onsets[d],
                            "hpo_terms": sorted(
                                t for t in ann.onset_terms.get(d, ()) if t in HPO_ONSET_LOWER
                            ),
                            "orphanet": sorted(orphanet.get(d, ())),
                        }
                        for d in sorted(ds)
                    },
                }
        annotated = sorted(d for d in ds if d in ann.phenotypes)
        if annotated:
            record["obligate"] = {
                d: sorted({t for t, fr in ann.phenotypes[d] if is_obligate(fr)}) for d in annotated
            }
            obligate_terms |= {t for terms in record["obligate"].values() for t in terms}
        names.update({d: ann.names[d] for d in ds if d in ann.names})
        out_genes[g] = record
    kb = {
        "schema": SCHEMA,
        "onset_lower_years": {"hpo": HPO_ONSET_LOWER, "orphanet": ORPHANET_ONSET_LOWER},
        "genes": out_genes,
        "disease_names": dict(sorted(names.items())),
        "ancestors_or_self": {t: sorted(set(ancestors_or_self(t)) | {t}) for t in sorted(obligate_terms)},
        "overrides": [],
    }
    stats.update(summary_stats(kb))
    stats.update({f"hpoa_{k}": v for k, v in ann.stats.items()})
    return kb, dict(sorted(stats.items()))


def negatable(record: dict) -> bool:
    """Every annotated disease has at least one obligate phenotype, so excluded terms can contradict it."""
    ob = record.get("obligate", {})
    return bool(ob) and all(ob.values())


def summary_stats(kb: dict) -> dict:
    g = kb["genes"]
    bounds = [r["onset"]["earliest_years"] for r in g.values() if "onset" in r]
    return {
        "genes": len(g),
        "genes_with_diseases": sum(bool(r["diseases"]) for r in g.values()),
        "male_limited": sum(r.get("sex", {}).get("limit") == "male" for r in g.values()),
        "female_limited": sum(r.get("sex", {}).get("limit") == "female" for r in g.values()),
        "genes_with_strict_onset": len(bounds),
        **{f"strict_onset_at_least_{t}y": sum(b >= t for b in bounds) for t in (1, 5, 10, 16, 40)},
        "genes_with_annotated_diseases": sum("obligate" in r for r in g.values()),
        "genes_negatable": sum(negatable(r) for r in g.values()),
        "obligate_terms": len(kb["ancestors_or_self"]),
        "overrides_applied": len(kb["overrides"]),
    }
