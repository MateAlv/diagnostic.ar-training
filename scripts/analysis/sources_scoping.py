"""SOURCES-SCOPING-001: per-gene profile strength, GeneReviews coverage and onset sources.

One row per v3.0 vocabulary gene, split into construction and evaluation genes
(`litpanel-split-v3`). Reads only knowledge sources, derived artifacts and the
GeneReviews FTP index files given with --gr-index (no chapter text).

Usage: python scripts/analysis/sources_scoping.py --gr-index DIR --out DIR
"""

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from diagnostic_ar_training import REPO_ROOT
from diagnostic_ar_training.lineage.hashing import sha256_file
from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.ontology import ONSET, Ontology
from diagnostic_ar_training.rerank.kb import parse_exact_alignments, parse_frequency, parse_orphanet_onsets

WEAK_NOFREQ_SHARE = 0.5
OVERVIEW_GENES = 10
MIN_SERIES = 5


def gene_reviews(index: Path):
    """Chapter shortname -> {nbk, title, genes, omim}."""
    chapters: dict[str, dict] = defaultdict(lambda: {"nbk": "", "title": "", "genes": set(), "omim": set()})
    with (index / "GRshortname_NBKid_genesymbol_dzname.txt").open(encoding="latin-1") as h:
        for line in h:
            short, nbk, gene, name = line.rstrip("\n").split("|")
            ch = chapters[short]
            ch["nbk"] = ch["nbk"] or nbk
            ch["title"] = ch["title"] or name
            if gene and gene != "Not applicable":
                ch["genes"].add(gene.upper())
    with (index / "NBKid_shortname_OMIM.txt").open(encoding="latin-1") as h:
        for row in csv.reader((x for x in h if not x.startswith("#")), delimiter="\t"):
            if len(row) == 3 and row[1] in chapters:
                chapters[row[1]]["omim"].add(f"OMIM:{row[2]}")
    with (index / "GRtitle_shortname_NBKid.txt").open(encoding="latin-1") as h:
        for row in csv.reader((x for x in h if not x.startswith("#")), delimiter="\t"):
            if row and row[0] in chapters:
                chapters[row[0]]["title"] = row[1]
    return dict(chapters)


def main_entity(gene: dict | None) -> dict | None:
    entities = [e for e in (gene or {}).get("entities", []) if e["simulable"]]
    return min(entities, key=lambda e: (-e["sim_weight"], e["entity"])) if entities else None


def hpoa_profiles(path: Path, ontology: Ontology):
    """Disease id -> {term -> [has_freq, has_count, max n/m denominator]}; disease id -> onset terms."""
    terms: dict[str, dict[str, list]] = defaultdict(dict)
    onsets: dict[str, set[str]] = defaultdict(set)
    onset_terms = ontology.descendants(ONSET) | {ONSET}
    with path.open(encoding="utf-8") as h:
        lines = (x for x in h if not x.startswith("#"))
        for row in csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["qualifier"] == "NOT":
                continue
            if row["aspect"] == "C" and row["hpo_id"] in onset_terms:
                onsets[row["database_id"]].add(row["hpo_id"])
            if row["aspect"] != "P":
                continue
            if row["onset"]:
                onsets[row["database_id"]].add(row["onset"])
            freq = parse_frequency(row["frequency"])
            slot = terms[row["database_id"]].setdefault(row["hpo_id"], [False, False, 0])
            slot[0] |= freq is not None
            if freq is not None and freq[0] == "count":
                slot[1] = True
                slot[2] = max(slot[2], freq[1][1])
    return terms, onsets


def weakness(n_terms: int, nofreq: float, has_count: bool, max_m: int, kind: str) -> str:
    if n_terms == 0:
        return "W0_no_profile"
    if has_count and max_m >= MIN_SERIES:
        return "ok_counts"
    if has_count:
        return "W4_counts_from_small_series_only"
    if kind == "orpha_only":
        return "W2_orphanet_bins_only"
    if nofreq >= WEAK_NOFREQ_SHARE:
        return "W1_mostly_no_frequency"
    return "W3_no_counts_other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gr-index", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    genes_path = fetch_outputs(load_manifest("genes-v2"))[0]
    built = json.load(gzip.open(genes_path))
    hpoa_path = next(p for p in fetch_outputs(load_manifest("hpoa-recount-v1")) if p.name == "phenotype.hpoa")
    split_out = next(o for o in load_manifest("litpanel-split-v3").outputs if o.path.endswith(".tsv"))
    split_path = REPO_ROOT / split_out.path
    if sha256_file(split_path) != split_out.sha256:
        raise SystemExit(f"{split_path}: sha256 differs from its manifest")
    profiles, hpoa_onsets = hpoa_profiles(hpoa_path, ontology)
    orpha_onsets = parse_orphanet_onsets(open_source("orphanet_ages_2026_06", Purpose.KB))
    exact = parse_exact_alignments(open_source("orphanet_alignments", Purpose.KB))
    chapters = gene_reviews(args.gr_index)

    eval_genes, eval_diseases = set(), set()
    with split_path.open(encoding="utf-8") as h:
        for row in csv.DictReader(h, delimiter="\t"):
            eval_genes |= {row["gene"].upper(), row["symbol"].upper()}
            eval_diseases |= set(row["disease_ids"].split(";"))

    chapter_eval = {
        s: bool(ch["genes"] & eval_genes or ch["omim"] & eval_diseases) for s, ch in chapters.items()
    }
    by_symbol: dict[str, set[str]] = defaultdict(set)
    for s, ch in chapters.items():
        for g in ch["genes"]:
            by_symbol[g].add(s)

    rows = []
    for v3, current in sorted(built["vocabulary"].items()):
        record = built["genes"].get(current) if current else None
        keys = {v3.upper(), (current or "").upper()} - {""}
        role = "evaluation" if keys & eval_genes else "construction"
        symbols = keys | {p.upper() for p in (record or {}).get("previous_symbols", [])}
        gr = sorted(set().union(*(by_symbol.get(s, set()) for s in symbols)))
        main = main_entity(record)
        ids = main["profile_ids"] if main else []
        all_ids = set(main["ids"]) | set(ids) if main else set()
        per_term: dict[str, list] = {}
        kinds = set()
        for i in ids:
            if profiles.get(i):
                kinds.add(i.split(":")[0])
            for t, (f, c, m) in profiles.get(i, {}).items():
                slot = per_term.setdefault(t, [False, False, 0])
                slot[0] |= f
                slot[1] |= c
                slot[2] = max(slot[2], m)
        n_terms = len(per_term)
        nofreq = sum(not f for f, _, _ in per_term.values()) / n_terms if n_terms else 0.0
        n_count = sum(c for _, c, _ in per_term.values())
        max_m = max((m for _, _, m in per_term.values()), default=0)
        has_count = n_count > 0
        kind = (
            "none" if not kinds else ("orpha_only" if kinds == {"ORPHA"} else "+".join(sorted(kinds)).lower())
        )
        orpha_ids = {i for i in all_ids if i.startswith("ORPHA:")}
        for i in all_ids:
            orpha_ids |= exact.get(i, set())
        orpha_onset = sorted({c for o in orpha_ids for c in orpha_onsets.get(o, [])})
        hpoa_onset = sorted({t for i in ids for t in hpoa_onsets.get(i, set())})
        disease_gr = sorted(s for s in gr if chapters[s]["omim"] & all_ids)
        rows.append(
            {
                "gene": v3,
                "symbol": current or "",
                "role": role,
                "simulable": bool(main),
                "main_entity": main["entity"] if main else "",
                "main_ids": ";".join(sorted(all_ids)),
                "main_shares_eval_disease": bool(all_ids & eval_diseases) and role == "construction",
                "r1_train_patients_gene": sum(
                    e["r1_train_patients"] for e in (record or {}).get("entities", [])
                ),
                "profile_source": kind,
                "n_terms": n_terms,
                "nofreq_share": round(nofreq, 4),
                "has_count_rows": has_count,
                "count_share": round(n_count / n_terms, 4) if n_terms else 0.0,
                "max_count_denominator": max_m,
                "weakness": weakness(n_terms, nofreq, has_count, max_m, kind) if main else "W0_no_profile",
                "hpoa_onset": bool(hpoa_onset),
                "orphanet_onset": ";".join(orpha_onset),
                "gr_chapters": ";".join(gr),
                "gr_chapter_for_main_disease": ";".join(disease_gr),
                "gr_dedicated": any(len(chapters[s]["genes"]) <= OVERVIEW_GENES for s in gr),
                "gr_usable": ";".join(s for s in gr if not chapter_eval[s]),
                "gr_eval_only": bool(gr) and all(chapter_eval[s] for s in gr),
            }
        )

    with (args.out / "genes.tsv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    with (args.out / "gr_chapters.tsv").open("w", encoding="utf-8", newline="") as h:
        w = csv.writer(h, delimiter="\t", lineterminator="\n")
        w.writerow(["shortname", "nbk", "title", "n_genes", "n_omim", "touches_eval_unit", "genes"])
        for s, ch in sorted(chapters.items()):
            w.writerow(
                [
                    s,
                    ch["nbk"],
                    ch["title"],
                    len(ch["genes"]),
                    len(ch["omim"]),
                    chapter_eval[s],
                    ";".join(sorted(ch["genes"])),
                ]
            )

    inputs = {
        "genes-v2": sha256_file(genes_path),
        "hpoa-recount-v1/phenotype.hpoa": sha256_file(hpoa_path),
        "litpanel-split-v3.tsv": sha256_file(split_path),
        **{f"gr_index/{p.name}": sha256_file(p) for p in sorted(args.gr_index.glob("*.txt"))},
    }
    summary = {
        "inputs": inputs,
        "params": {
            "weak_nofreq_share": WEAK_NOFREQ_SHARE,
            "overview_genes": OVERVIEW_GENES,
            "min_series": MIN_SERIES,
        },
    }
    summary["chapters"] = {
        "in_gene_map": len(chapters),
        "with_nbk": sum(bool(c["nbk"]) for c in chapters.values()),
        "touching_eval_units": sum(chapter_eval.values()),
        "with_gt_10_genes": sum(len(c["genes"]) > OVERVIEW_GENES for c in chapters.values()),
    }
    for role in ("construction", "evaluation"):
        rs = [r for r in rows if r["role"] == role]
        sim = [r for r in rs if r["simulable"]]
        summary[role] = {
            "genes": len(rs),
            "simulable": len(sim),
            "main_shares_eval_disease": sum(r["main_shares_eval_disease"] for r in rs),
            "gr_any_chapter": sum(bool(r["gr_chapters"]) for r in rs),
            "gr_dedicated_chapter": sum(r["gr_dedicated"] for r in rs),
            "gr_chapter_lists_main_disease": sum(bool(r["gr_chapter_for_main_disease"]) for r in rs),
            "gr_usable_chapter": sum(bool(r["gr_usable"]) for r in rs),
            "gr_only_eval_touched_chapters": sum(r["gr_eval_only"] for r in rs),
            "weakness": dict(Counter(r["weakness"] for r in rs)),
            "profile_source": dict(Counter(r["profile_source"] for r in sim)),
            "has_count_rows": sum(r["has_count_rows"] for r in sim),
            "nofreq_share_ge_0.5": sum(
                r["nofreq_share"] >= WEAK_NOFREQ_SHARE and r["n_terms"] > 0 for r in sim
            ),
            "onset": {
                "hpoa": sum(r["hpoa_onset"] for r in sim),
                "orphanet": sum(bool(r["orphanet_onset"]) for r in sim),
                "either": sum(r["hpoa_onset"] or bool(r["orphanet_onset"]) for r in sim),
                "neither": sum(not (r["hpoa_onset"] or r["orphanet_onset"]) for r in sim),
            },
            "r1_train_bin": dict(
                Counter(
                    "0"
                    if r["r1_train_patients_gene"] == 0
                    else ("1-9" if r["r1_train_patients_gene"] < 10 else ">=10")
                    for r in rs
                )
            ),
        }
    (args.out / "genes.summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
