"""The ft-v1 knowledge artifact (`ft-kb/2`): what the residual's compatibility features read, per gene of E0.

It is built from the same sources and rules as safe-v1 (`safe/knowledge.py`), but with every `r1-v1` PMID
masked (`splits.mask_pmids("r1-v1", "all")`), so a training patient never sees annotations curated from their
own paper.

- `safe`: a `safe-kb/1` document (sex limitation, strict earliest onset, obligate phenotypes), with the
  curation overrides that still apply under this mask. An override whose rule the gene no longer has is
  skipped and listed.
- `genes`, per gene:
  - `lenient_onset_years`: the lowest onset lower bound among the gene's diseases that have onset data;
  - `xlr_only`: every HPO inheritance term of the gene's diseases is the explicit X-linked recessive term
    (HP:0001419). Generic X-linked inheritance (HP:0001417) does not qualify: it also covers disorders that
    affect females (e.g. PCDH19). `ft-kb/1` counted it, and had an `xld_only` flag, which is gone;
  - `profile`: the phenotype terms annotated to the gene's diseases (aspect P, not NOT), sorted.
"""

from collections import Counter
from collections.abc import Callable, Iterable

from diagnostic_ar_training.safe import knowledge as safe_knowledge
from diagnostic_ar_training.safe import overrides as curation

SCHEMA = "ft-kb/2"
XLR = frozenset({"HP:0001419"})
X_LINKED = frozenset({"HP:0001417", "HP:0001419"})


def xlr_only(inheritance: set[str]) -> bool:
    """X-linked recessive only: every inheritance term is the explicit HP:0001419."""
    return bool(inheritance) and inheritance <= XLR


def apply_overrides(kb: dict, rows: list[curation.Override]) -> tuple[dict, list[dict]]:
    """Apply each override that still has a rule to act on; return the curated kb and the skipped rows."""
    applicable, skipped = [], []
    for o in rows:
        record = kb["genes"].get(o.gene)
        if record is None or o.rule not in record:
            skipped.append({"gene": o.gene, "rule": o.rule, "action": o.action, "why": "rule absent"})
        elif o.action == "lower_onset" and o.value_years >= record["onset"]["earliest_years"]:
            skipped.append({"gene": o.gene, "rule": o.rule, "action": o.action, "why": "bound already lower"})
        else:
            applicable.append(o)
    return curation.apply(kb, applicable), skipped


def build(
    genes: Iterable[str],
    genes_to_disease: dict[str, set[str]],
    ann: safe_knowledge.Annotations,
    orphanet: dict[str, set[str]],
    hgnc_locations: dict[str, str],
    ancestors_or_self: Callable[[str], Iterable[str]],
    overrides: list[curation.Override] = (),
) -> tuple[dict, dict]:
    """(kb, stats). Plain JSON-serialisable and deterministic."""
    genes = sorted(set(genes))
    safe, safe_stats = safe_knowledge.build(
        genes, genes_to_disease, ann, orphanet, hgnc_locations, ancestors_or_self
    )
    safe, skipped = apply_overrides(safe, list(overrides))
    out: dict[str, dict] = {}
    stats: Counter = Counter()
    for g in genes:
        ds = genes_to_disease.get(g, set())
        inheritance = set().union(*(ann.inheritance.get(d, set()) for d in ds)) if ds else set()
        onsets = [o for d in ds if (o := safe_knowledge.disease_onset(d, ann, orphanet)) is not None]
        profile = sorted({t for d in ds for t, _ in ann.phenotypes.get(d, ())})
        record: dict = {"profile": profile}
        if onsets:
            record["lenient_onset_years"] = min(onsets)
        if xlr_only(inheritance):
            record["xlr_only"] = True
        out[g] = record
        stats["genes_with_lenient_onset"] += bool(onsets)
        stats["xlr_only"] += "xlr_only" in record
        stats["xl_generic_not_xlr_only"] += (
            bool(inheritance) and inheritance <= X_LINKED and not xlr_only(inheritance)
        )
        stats["genes_with_profile"] += bool(profile)
        stats["profile_pairs"] += len(profile)
    kb = {"schema": SCHEMA, "safe": safe, "genes": out, "overrides_skipped": skipped}
    stats = {
        **dict(sorted(stats.items())),
        "overrides_given": len(overrides),
        "overrides_applied": len(safe["overrides"]),
        "overrides_skipped": len(skipped),
        "profile_terms": len({t for r in out.values() for t in r["profile"]}),
        "safe": {**safe_knowledge.summary_stats(safe)},
        "safe_uncurated": {k: v for k, v in safe_stats.items() if not k.startswith("hpoa_")},
        **{k: v for k, v in safe_stats.items() if k.startswith("hpoa_")},
    }
    return kb, stats
