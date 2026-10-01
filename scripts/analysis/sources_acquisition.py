"""SOURCES-ACQUISITION-001: what each Tier-1 curated source offers per vocabulary gene.

One row per v3.0 vocabulary gene, with the role (construction or evaluation), the
profile weakness tier and the main disease taken from SOURCES-SCOPING-001's
`genes.tsv` (same `litpanel-split-v3` boundary, same `genes-v2` main entity). For
each source (MedlinePlus Genetics, Gene2Phenotype, PanelApp, ClinGen validity and,
optionally, the frozen GeneReviews list) it records:
- whether the gene is covered (v3 symbol, current symbol, previous symbols, HGNC id);
- whether it offers phenotype terms that the main disease's `hpoa-recount-v1`
  profile lacks (`new`: not in the profile; `new_unrelated`: not in the profile and
  neither an ancestor nor a descendant of a profile term). Only terms under
  Phenotypic abnormality (HP:0000118) count;
- whether it offers a frequency or prevalence, an age (onset or diagnosis), or a
  gene-disease confidence.

MedlinePlus has no HPO ids. Its "terms" are exact, case-insensitive matches of HPO
labels and exact synonyms in the condition's description text: a deterministic,
rough indicator, not an extraction. Its age flags reuse the SOURCES-SCOPING-001
GeneReviews regexes on the same text, and its prevalence flag means the Frequency
section states a number (disease prevalence, not feature frequency).

--gr-chapters adds GeneReviews: a TSV with a `nbk` column and a
`construction_genes` column (semicolon-separated symbols), plus optional
`has_frequency_table` and `age_numeric` columns.

--lit-papers adds the frozen Tier-2 papers (lit-sources-v1 papers.tsv; only
`selected` rows count). Given lit-sources-v1 chapters.tsv, --gr-chapters keeps
only `usable` chapters.

Usage: python scripts/analysis/sources_acquisition.py --out DIR [--gr-chapters TSV] [--lit-papers TSV]
"""

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from diagnostic_ar_training import DATA_DIR, REPO_ROOT
from diagnostic_ar_training.knowledge import gene2phenotype, medlineplus, panelapp
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source
from diagnostic_ar_training.ontology import Ontology

PHENOTYPIC_ABNORMALITY = "HP:0000118"
SCOPING = REPO_ROOT / "results/analyses/SOURCES-SCOPING-001/genes.tsv"
TIERS = (
    "W1_mostly_no_frequency",
    "W2_orphanet_bins_only",
    "W3_no_counts_other",
    "W4_counts_from_small_series_only",
    "ok_counts",
    "W0_no_profile",
)
WEAK = set(TIERS[:4])
MIN_LABEL_CHARS = 6
MAX_NGRAM = 8
EXACT_SYNONYM = "hasExactSynonym"
EVIDENCE_RANK = {"green": 3, "amber": 2, "red": 1}
CLINGEN_RANK = {
    "Definitive": 6,
    "Strong": 5,
    "Moderate": 4,
    "Limited": 3,
    "Disputed": 2,
    "Refuted": 1,
    "No Known Disease Relationship": 0,
}
# The same patterns as scripts/analysis/sources_scoping_gr_sample.py.
AGE_NUMBER = re.compile(
    r"(?:age[sd]?|onset|diagnos\w*|present\w*|manifest\w*)[^.;]{0,80}?\b\d+(?:\.\d+)?(?:\s?(?:-|–|to|and)\s?\d+(?:\.\d+)?)?\s?(?:years?|yrs?|months?|weeks?|days?)\b"
    r"|\b(?:mean|median|average)\s+age\b",
    re.IGNORECASE,
)
AGE_WORDS = re.compile(
    r"\b(?:onset|present\w*|manifest\w*)\b[^.;]{0,60}\b"
    r"(?:prenatal\w*|antenatal\w*|congenital|at birth|neonatal\w*|infancy|childhood|adolescence"
    r"|adulthood|early adult\w*|late adult\w*|middle age)\b",
    re.IGNORECASE,
)
PREVALENCE_NUMBER = re.compile(
    r"\b\d[\d,]*\s+(?:in|per|out of)\s+(?:\d[\d,]*|a million|one million)\b|\b\d+(?:\.\d+)?\s?%"
    r"|\b\d[\d,]*\s+(?:affected\s+)?(?:people|individuals|cases|families|patients)\b",
    re.IGNORECASE,
)
WORD = re.compile(r"[a-z0-9]+(?:[-'][a-z0-9]+)*")


def main_entity(gene: dict | None) -> dict | None:
    entities = [e for e in (gene or {}).get("entities", []) if e["simulable"]]
    return min(entities, key=lambda e: (-e["sim_weight"], e["entity"])) if entities else None


def profiles(path: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as h:
        lines = (x for x in h if not x.startswith("#"))
        for row in csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["aspect"] == "P" and row["qualifier"] != "NOT":
                out[row["database_id"]].add(row["hpo_id"])
    return out


def hpo_dictionary(hp_json: Path, phenotypic: frozenset[str]) -> dict[tuple[str, ...], str]:
    """Lower-cased word tuples of labels and exact synonyms -> HPO id (ambiguous phrases dropped)."""
    seen: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for node in json.loads(hp_json.read_text())["graphs"][0]["nodes"]:
        term = node["id"].rsplit("/", 1)[-1].replace("_", ":", 1)
        if term not in phenotypic:
            continue
        names = [node.get("lbl") or ""]
        names += [s["val"] for s in node.get("meta", {}).get("synonyms", []) if s["pred"] == EXACT_SYNONYM]
        for name in names:
            words = tuple(WORD.findall(name.lower()))
            if words and len(" ".join(words)) >= MIN_LABEL_CHARS and len(words) <= MAX_NGRAM:
                seen[words].add(term)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def dictionary_terms(text: str, dictionary: dict[tuple[str, ...], str]) -> set[str]:
    words = WORD.findall(text.lower())
    found = set()
    for i in range(len(words)):
        for n in range(1, MAX_NGRAM + 1):
            hit = dictionary.get(tuple(words[i : i + n]))
            if hit:
                found.add(hit)
    return found


def novelty(terms: set[str], profile: set[str], ontology: Ontology) -> tuple[set[str], set[str]]:
    new = terms - profile
    related = set(profile)
    for t in profile:
        related |= ontology.ancestors(t) | ontology.descendants(t)
    return new, new - related


def clingen_validity(path: Path) -> dict[str, list[str]]:
    """HGNC id -> classifications."""
    out: dict[str, list[str]] = defaultdict(list)
    with path.open(encoding="utf-8") as h:
        rows = list(csv.reader(h))
    header = next(i for i, r in enumerate(rows) if r and r[0] == "GENE SYMBOL")
    for r in rows[header + 1 :]:
        if len(r) > 6 and r[1].startswith("HGNC:"):
            out[r[1]].append(r[6])
    return out


def gene_index(items, keys) -> dict[str, list]:
    index: dict[str, list] = defaultdict(list)
    for item in items:
        for k in keys(item):
            if k:
                index[k.upper()].append(item)
    return index


def lookup(index: dict[str, list], keys: set[str]) -> list:
    seen, out = set(), []
    for k in keys:
        for item in index.get(k, []):
            if id(item) not in seen:
                seen.add(id(item))
                out.append(item)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--gr-chapters", type=Path)
    ap.add_argument("--lit-papers", type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    hp_json = open_source("hpo_ontology", Purpose.KB)
    ontology = Ontology.from_json(hp_json)
    phenotypic = ontology.descendants(PHENOTYPIC_ABNORMALITY)
    dictionary = hpo_dictionary(hp_json, phenotypic)
    genes_path = fetch_outputs(load_manifest("genes-v2"))[0]
    built = json.load(gzip.open(genes_path))
    hpoa_path = next(p for p in fetch_outputs(load_manifest("hpoa-recount-v1")) if p.name == "phenotype.hpoa")
    profile_terms = profiles(hpoa_path)
    heldout = {x.strip() for x in (DATA_DIR / "splits/r1-v1.heldout-pmids.txt").open() if x.strip()}
    with SCOPING.open(encoding="utf-8") as h:
        scoping = {r["gene"]: r for r in csv.DictReader(h, delimiter="\t")}

    mlp = medlineplus.load(open_source("medlineplus_genetics", Purpose.KB))
    g2p = gene2phenotype.parse(open_source("gene2phenotype", Purpose.KB))
    pa = panelapp.parse(open_source("panelapp", Purpose.KB))
    cg = clingen_validity(open_source("clingen_validity", Purpose.KB))
    mlp_idx = gene_index(mlp, lambda c: c.genes)
    g2p_idx = gene_index(g2p, lambda r: (r.gene, r.hgnc_id))
    pa_idx = gene_index(pa, lambda p: (p.gene, p.hgnc_id))
    gr_idx: dict[str, list[dict]] = defaultdict(list)
    if args.gr_chapters:
        with args.gr_chapters.open(encoding="utf-8") as h:
            for row in csv.DictReader(h, delimiter="\t"):
                if row.get("status", "usable") != "usable":
                    continue
                row.setdefault("has_frequency_table", row.get("has_numeric_frequency_table", ""))
                if "age_numeric_sentences" in row:
                    row.setdefault("age_numeric", str(int(row["age_numeric_sentences"]) > 0))
                for g in row["construction_genes"].split(";"):
                    if g:
                        gr_idx[g.upper()].append(row)
    paper_idx: dict[str, list[dict]] = defaultdict(list)
    if args.lit_papers:
        with args.lit_papers.open(encoding="utf-8") as h:
            for row in csv.DictReader(h, delimiter="\t"):
                if row["status"] == "selected":
                    for g in row["genes"].split(";"):
                        paper_idx[g.upper()].append(row)

    rows = []
    for v3, current in sorted(built["vocabulary"].items()):
        sc = scoping[v3]
        record = built["genes"].get(current) if current else None
        keys = {v3.upper(), (current or "").upper()} | {
            p.strip('"').upper() for p in (record or {}).get("previous_symbols", [])
        }
        keys.discard("")
        hgnc = (record or {}).get("hgnc_id", "")
        main = main_entity(record)
        main_ids = set(sc["main_ids"].split(";")) - {""}
        profile = set().union(*(profile_terms.get(i, set()) for i in (main["profile_ids"] if main else [])))
        row = {
            "gene": v3,
            "symbol": current or "",
            "role": sc["role"],
            "weakness": sc["weakness"],
            "main_entity": sc["main_entity"],
            "main_shares_eval_disease": sc["main_shares_eval_disease"],
            "profile_terms": len(profile),
        }

        conds = lookup(mlp_idx, keys)
        main_conds = [c for c in conds if set(c.omim_ids) & main_ids] or conds
        text = " ".join(c.sections.get("description", "") for c in main_conds)
        freq = " ".join(c.sections.get("frequency", "") for c in main_conds)
        mlp_terms = dictionary_terms(text, dictionary)
        mlp_new, mlp_unrel = novelty(mlp_terms, profile, ontology)
        row |= {
            "mlp_conditions": len(conds),
            "mlp_main_disease": any(set(c.omim_ids) & main_ids for c in conds),
            "mlp_frequency_section": any(c.sections.get("frequency") for c in main_conds),
            "mlp_prevalence_numeric": bool(PREVALENCE_NUMBER.search(freq)),
            "mlp_inheritance": any(c.inheritance_hpo for c in main_conds),
            "mlp_age_numeric": bool(AGE_NUMBER.search(text)),
            "mlp_age_qualitative": bool(AGE_WORDS.search(text)),
            "mlp_dict_terms": len(mlp_terms),
            "mlp_dict_new": len(mlp_new),
            "mlp_dict_new_unrelated": len(mlp_unrel),
        }

        recs = lookup(g2p_idx, keys | {hgnc.upper()} if hgnc else keys)
        main_recs = [r for r in recs if set(r.disease_ids) & main_ids] or recs
        g2p_terms = {t for r in main_recs for t in r.hpo_ids if t in phenotypic}
        g2p_new, g2p_unrel = novelty(g2p_terms, profile, ontology)
        panels = sorted({p for r in recs for p in r.panels})
        row |= {
            "g2p_records": len(recs),
            "g2p_panels": ";".join(panels),
            "g2p_dd_only": panels == ["DD"],
            "g2p_best_confidence": max(recs, key=lambda r: r.confidence_rank).confidence if recs else "",
            "g2p_main_disease": any(set(r.disease_ids) & main_ids for r in recs),
            "g2p_terms": len(g2p_terms),
            "g2p_new": len(g2p_new),
            "g2p_new_unrelated": len(g2p_unrel),
            "g2p_cites_heldout": any(set(r.pmids) & heldout for r in recs),
        }

        entries = lookup(pa_idx, keys | {hgnc.upper()} if hgnc else keys)
        main_entries = [e for e in entries if set(e.omim_ids) & main_ids] or entries
        pa_terms = {t for e in main_entries for t in e.hpo_ids if ontology.resolve(t) in phenotypic}
        pa_new, pa_unrel = novelty(pa_terms, profile, ontology)
        best = max((EVIDENCE_RANK[e.evidence] for e in entries), default=0)
        row |= {
            "pa_entries": len(entries),
            "pa_panels": len({e.panel_id for e in entries}),
            "pa_green_panels": len({e.panel_id for e in entries if e.evidence == "green"}),
            "pa_best_evidence": {3: "green", 2: "amber", 1: "red", 0: ""}[best],
            "pa_main_disease": any(set(e.omim_ids) & main_ids for e in entries),
            "pa_terms": len(pa_terms),
            "pa_new": len(pa_new),
            "pa_new_unrelated": len(pa_unrel),
        }

        classes = cg.get(hgnc, [])
        row |= {
            "cg_curations": len(classes),
            "cg_best": max(classes, key=lambda c: CLINGEN_RANK.get(c, -1)) if classes else "",
        }
        if args.gr_chapters:
            chapters = lookup(gr_idx, keys)
            row |= {
                "gr_chapters": ";".join(sorted({c["nbk"] for c in chapters})),
                "gr_frequency_table": any(
                    c.get("has_frequency_table") in ("True", "true", "1") for c in chapters
                ),
                "gr_age_numeric": any(c.get("age_numeric") in ("True", "true", "1") for c in chapters),
            }
        if args.lit_papers:
            papers = lookup(paper_idx, keys)
            row |= {
                "t2_papers": len({p["pmid"] for p in papers}),
                "t2_papers_cited_by_gr": len(
                    {p["pmid"] for p in papers if p["cited_by_genereviews"] == "True"}
                ),
            }
        rows.append(row)

    with (args.out / "genes.tsv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    measures = {
        "medlineplus": {
            "covered": lambda r: r["mlp_conditions"] > 0,
            "main_disease_matched": lambda r: r["mlp_main_disease"],
            "new_terms_dictionary": lambda r: r["mlp_dict_new"] > 0,
            "new_unrelated_terms_dictionary": lambda r: r["mlp_dict_new_unrelated"] > 0,
            "prevalence_section": lambda r: r["mlp_frequency_section"],
            "prevalence_numeric": lambda r: r["mlp_prevalence_numeric"],
            "age_numeric": lambda r: r["mlp_age_numeric"],
            "age_qualitative": lambda r: r["mlp_age_qualitative"],
            "inheritance": lambda r: r["mlp_inheritance"],
        },
        "gene2phenotype": {
            "covered": lambda r: r["g2p_records"] > 0,
            "main_disease_matched": lambda r: r["g2p_main_disease"],
            "dd_panel_only": lambda r: r["g2p_dd_only"],
            "any_hpo_terms": lambda r: r["g2p_terms"] > 0,
            "new_terms": lambda r: r["g2p_new"] > 0,
            "new_unrelated_terms": lambda r: r["g2p_new_unrelated"] > 0,
            "confidence_definitive_or_strong": lambda r: r["g2p_best_confidence"] in ("definitive", "strong"),
            "cites_heldout_pmid": lambda r: r["g2p_cites_heldout"],
        },
        "panelapp": {
            "covered": lambda r: r["pa_entries"] > 0,
            "green_on_some_panel": lambda r: r["pa_green_panels"] > 0,
            "main_disease_matched": lambda r: r["pa_main_disease"],
            "any_hpo_terms": lambda r: r["pa_terms"] > 0,
            "new_terms": lambda r: r["pa_new"] > 0,
        },
        "clingen_validity": {
            "covered": lambda r: r["cg_curations"] > 0,
            "definitive_or_strong": lambda r: r["cg_best"] in ("Definitive", "Strong"),
        },
        "any_tier1_kb": {
            "covered": lambda r: bool(r["mlp_conditions"] or r["g2p_records"] or r["pa_entries"]),
            "new_terms_g2p_or_panelapp": lambda r: r["g2p_new"] > 0 or r["pa_new"] > 0,
        },
    }
    if args.gr_chapters:
        measures["genereviews_frozen"] = {
            "covered": lambda r: bool(r["gr_chapters"]),
            "frequency_table": lambda r: r["gr_frequency_table"],
            "age_numeric": lambda r: r["gr_age_numeric"],
        }
    if args.lit_papers:
        measures["tier2_papers_frozen"] = {
            "covered": lambda r: r["t2_papers"] > 0,
            "covered_by_gr_cited_paper": lambda r: r["t2_papers_cited_by_gr"] > 0,
        }
    if args.gr_chapters and args.lit_papers:
        measures["lit_sources_any"] = {
            "chapter_or_paper": lambda r: bool(r["gr_chapters"]) or r["t2_papers"] > 0,
        }

    def table(rs):
        return {s: {m: sum(bool(f(r)) for r in rs) for m, f in ms.items()} for s, ms in measures.items()}

    summary = {
        "inputs": {
            **{f"source:{n}": s.sha256 for n, s in load_sources().items() if n in INPUT_SOURCES},
            "genes-v2": sha256_file(genes_path),
            "hpoa-recount-v1/phenotype.hpoa": sha256_file(hpoa_path),
            "SOURCES-SCOPING-001/genes.tsv": sha256_file(SCOPING),
            **({"gr_chapters": sha256_file(args.gr_chapters)} if args.gr_chapters else {}),
            **({"lit_papers": sha256_file(args.lit_papers)} if args.lit_papers else {}),
        },
        "params": {
            "min_label_chars": MIN_LABEL_CHARS,
            "max_ngram": MAX_NGRAM,
            "dictionary_phrases": len(dictionary),
        },
        "source_sizes": {
            "medlineplus_conditions": len(mlp),
            "medlineplus_with_frequency_section": sum(bool(c.sections.get("frequency")) for c in mlp),
            "g2p_records": len(g2p),
            "g2p_records_by_panel": dict(Counter(p for r in g2p for p in r.panels)),
            "g2p_records_with_hpo": sum(bool(r.hpo_ids) for r in g2p),
            "g2p_records_by_confidence": dict(Counter(r.confidence for r in g2p)),
            "panelapp_gene_entries": len(pa),
            "panelapp_panels": len({p.panel_id for p in pa}),
            "panelapp_entries_by_evidence": dict(Counter(p.evidence for p in pa)),
            "panelapp_entries_with_hpo": sum(bool(p.hpo_ids) for p in pa),
            "panelapp_entries_with_omim": sum(bool(p.omim_ids) for p in pa),
        },
    }
    for role in ("construction", "evaluation"):
        rs = [r for r in rows if r["role"] == role]
        summary[role] = {
            "genes": len(rs),
            "all": table(rs),
            "weak_W1_W4": table([r for r in rs if r["weakness"] in WEAK]),
            "by_tier": {
                t: {
                    "genes": sum(r["weakness"] == t for r in rs),
                    **table([r for r in rs if r["weakness"] == t]),
                }
                for t in TIERS
            },
        }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("source_sizes", "construction")}, indent=1)[:6000])


INPUT_SOURCES = {"hpo_ontology", "medlineplus_genetics", "gene2phenotype", "panelapp", "clingen_validity"}


if __name__ == "__main__":
    main()
