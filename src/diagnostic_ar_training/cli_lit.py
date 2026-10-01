"""`dxt lit-sources`: the frozen literature extraction lists of ADR-0013 (lit-sources-v1)."""

import csv
import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR, REPO_ROOT
from diagnostic_ar_training.lineage.registry import LineageError

lit_app = typer.Typer(no_args_is_help=True, help="Literature extraction lists (ADR-0013).")
EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/searchPOST"
PMID_BATCH = 150
PAGE_SIZE = 1000
GENES_ID = "genes-v2"
RECOUNT_ID = "hpoa-recount-v1"
SPLIT_ID = "litpanel-split-v3"
PANEL_ROWS = DATA_DIR / "realism" / "extraction" / "curated.tsv"
CHAPTER_COLUMNS = (
    "priority_rank", "priority_class", "shortname", "nbk", "title", "status", "n_index_genes",
    "construction_genes", "n_construction_genes", "weak_construction_genes", "n_weak_construction_genes",
    "best_weak_tier", "simulable_construction_genes", "genes_blocked_eval_disease", "eval_units_touched",
    "omim_ids", "has_numeric_frequency_table", "feature_tables", "feature_table_numeric_rows",
    "clinical_numeric_sentences", "age_numeric_sentences", "cited_pmids", "cited_heldout_pmids",
)  # fmt: skip
PAPER_COLUMNS = (
    "pmid", "pmcid", "status", "reason", "licence", "n_stated", "genes", "genes_from", "weak_genes",
    "cited_by_genereviews", "citing_chapters", "in_hpoa", "in_hpoa_diseases", "found_by", "pub_year",
    "journal", "pub_types", "title",
)  # fmt: skip


def _cache_path(artifact_id: str) -> Path:
    return INTERIM_DIR / "lit-sources" / artifact_id / "epmc-cache.jsonl.gz"


def _out_dir(artifact_id: str) -> Path:
    return DATA_DIR / "lit-sources" / artifact_id


def _verified(artifact_id: str, suffix: str) -> Path:
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import fetch_outputs, load_manifest, output_path

    manifest = load_manifest(artifact_id)
    out = next(o for o in manifest.outputs if o.path.endswith(suffix))
    path = output_path(out)
    if not path.is_file():
        fetch_outputs(manifest)
    if sha256_file(path) != out.sha256:
        raise LineageError(f"{path} does not match the {artifact_id} manifest")
    return path


def _boundary():
    """Everything both stages need: chapters, screens, genes, evaluation boundary, masks."""
    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import lit_sources as ls
    from diagnostic_ar_training.lineage.registry import Purpose, open_source

    chapters, nxml = ls.read_snapshot(open_source("genereviews", Purpose.KB))
    screens = {s: ls.screen_chapter(x) for s, x in nxml.items()}
    eval_genes, eval_diseases = set(), set()
    with _verified(SPLIT_ID, ".tsv").open(encoding="utf-8") as h:
        for row in csv.DictReader(h, delimiter="\t"):
            eval_genes |= {row["gene"].upper(), row["symbol"].upper()}
            eval_diseases |= set(row["disease_ids"].split(";"))
    built = json.load(gzip.open(_verified(GENES_ID, "genes.json.gz")))
    profiles = ls.profile_strength(_verified(RECOUNT_ID, "phenotype.hpoa"))
    genes = ls.gene_infos(built, profiles, eval_genes, eval_diseases)
    splits.write_heldout_pmids("r1-v1")
    heldout = {x.removeprefix("PMID:") for x in splits.heldout_pmids_path("r1-v1").read_text().split()}
    rows = ls.chapter_rows(chapters, screens, genes, eval_genes, eval_diseases, heldout)
    usable = [r for r in rows if r["status"] == "usable"]
    cited: dict[str, set[str]] = {}
    for r in usable:
        for p in screens[r["shortname"]].pmids:
            cited.setdefault(p, set()).add(r["shortname"])
    covered = {g for r in usable for g in r["construction_genes"].split(";")}
    second_pass = sorted(
        (g for g in genes if g.construction and g.simulable and g.weak and g.gene not in covered),
        key=lambda g: g.gene,
    )
    return {
        "chapters": chapters,
        "screens": screens,
        "genes": genes,
        "rows": rows,
        "cited": cited,
        "second_pass": second_pass,
        "eval_genes": eval_genes,
        "eval_diseases": eval_diseases,
        "heldout": heldout,
    }


def _post(query: str, cursor: str = "*") -> dict:
    data = urllib.parse.urlencode(
        {"query": query, "resultType": "core", "pageSize": PAGE_SIZE, "format": "json", "cursorMark": cursor}
    ).encode()
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(EPMC_SEARCH, data=data), timeout=120) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = min(300, 15 * 2**attempt)
            typer.echo(f"Europe PMC error ({e}); retry in {wait}s", err=True)
            time.sleep(wait)
    raise LineageError("Europe PMC unreachable after 8 attempts")


def _search(query: str) -> tuple[int, list[dict]]:
    results, cursor, hits = [], "*", 0
    while True:
        page = _post(query, cursor)
        hits = int(page.get("hitCount", 0))
        batch = page.get("resultList", {}).get("result", [])
        results.extend(batch)
        nxt = page.get("nextCursorMark")
        if not batch or not nxt or nxt == cursor or len(results) >= hits:
            return hits, results
        cursor = nxt


def _jobs(b: dict) -> list[tuple[str, str]]:
    """(cache key, Europe PMC query) for both passes, in a fixed order."""
    from diagnostic_ar_training.knowledge import lit_sources as ls

    pmids = sorted(b["cited"], key=int)
    jobs = [
        (f"pmids:{i // PMID_BATCH}", ls.epmc_pmid_query(pmids[i : i + PMID_BATCH]))
        for i in range(0, len(pmids), PMID_BATCH)
    ]
    return jobs + [(f"gene:{g.gene}", ls.epmc_gene_query(g.gene)) for g in b["second_pass"]]


@lit_app.command("fetch")
def fetch(artifact_id: str = typer.Option(..., "--id")) -> None:
    """Query Europe PMC for both paper passes and cache the raw responses (resumable)."""

    b = _boundary()
    cache = _cache_path(artifact_id)
    cache.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if cache.exists():
        with gzip.open(cache, "rt", encoding="utf-8") as h:
            done = {json.loads(line)["key"] for line in h}
    jobs = _jobs(b)
    typer.echo(
        f"{len(b['cited'])} cited PMIDs, {len(b['second_pass'])} second-pass genes, {len(jobs)} queries"
    )
    with gzip.open(cache, "at", encoding="utf-8") as h:
        for n, (key, query) in enumerate(jobs, 1):
            if key in done:
                continue
            hits, results = _search(query)
            fetched = datetime.now(UTC).isoformat(timespec="seconds")
            h.write(json.dumps({"key": key, "query": query, "fetched_utc": fetched, "hitCount": hits,
                                "results": results}) + "\n")  # fmt: skip
            h.flush()
            if n % 50 == 0:
                typer.echo(f"{n}/{len(jobs)}")
    typer.echo(f"cache: {cache}")


def _write_tsv(rows: list[dict], columns: tuple[str, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(columns), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows({c: r[c] for c in columns} for r in rows)


@lit_app.command("freeze")
def freeze(
    artifact_id: str = typer.Option(..., "--id"),
    publish: bool = typer.Option(False, help="Upload as a release of this repo (ADR-0005)"),
) -> None:
    """Screen the cached records deterministically and freeze the lists with a manifest."""
    from collections import Counter

    from diagnostic_ar_training import splits
    from diagnostic_ar_training.knowledge import lit_sources as ls
    from diagnostic_ar_training.lineage import registry
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file
    from diagnostic_ar_training.lineage.manifest import build_manifest, ensure_new, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import Purpose, open_source

    ensure_new(artifact_id)
    state = code_state()
    if state.dirty:
        raise LineageError("commit first: lit-sources lists must be reproducible from a SHA")
    b = _boundary()
    cache = _cache_path(artifact_id)
    entries = {}
    with gzip.open(cache, "rt", encoding="utf-8") as h:
        for line in h:
            e = json.loads(line)
            entries[e["key"]] = e
    expected = dict(_jobs(b))
    if {k: e["query"] for k, e in entries.items()} != expected:
        raise LineageError("the Europe PMC cache does not match the current lists and queries; re-run fetch")

    panel = set()
    with PANEL_ROWS.open(encoding="utf-8") as h:
        for r in csv.DictReader(h, delimiter="\t"):
            panel |= set(re.findall(r"PMID:?\s?(\d+)", r["citation"]))
    hpoa_pmids = ls.hpoa_pmids_by_disease(open_source("hpo_annotations", Purpose.KB))
    by_gene = {g.gene: g for g in b["genes"]}
    construction_by_symbol = {}
    for g in b["genes"]:
        if g.construction:
            for s in sorted(g.symbols):
                construction_by_symbol.setdefault(s, g)
    chapter_genes = {
        r["shortname"]: r["construction_genes"].split(";") for r in b["rows"] if r["status"] == "usable"
    }

    papers: dict[str, dict] = {}
    for key in sorted(k for k in entries if k.startswith("pmids:")):
        for rec in entries[key]["results"]:
            pmid = str(rec.get("pmid") or "")
            if pmid not in b["cited"] or pmid in papers:
                continue
            status, reason, n = ls.screen_paper(rec, b["heldout"], panel, b["eval_genes"])
            citing = sorted(b["cited"][pmid])
            pool = sorted({g for c in citing for g in chapter_genes[c]})
            text = f"{ls.plain(rec.get('title'))} {ls.plain(rec.get('abstractText'))}"
            named = [g for g in pool if any(ls.word_in(s, text) for s in by_gene[g].symbols)]
            genes = [by_gene[g] for g in (named or pool)]
            papers[pmid] = ls.paper_row(
                rec, status, reason, n, genes, "title_abstract" if named else "citing_chapters",
                citing, hpoa_pmids, "genereviews_reference",
            )  # fmt: skip

    gene_rows = []
    for g in b["second_pass"]:
        e = entries[f"gene:{g.gene}"]
        title_hits = 0
        for rec in e["results"]:
            if not any(ls.word_in(s, ls.plain(rec.get("title"))) for s in g.symbols):
                continue
            title_hits += 1
            pmid = str(rec.get("pmid") or "")
            if not pmid:
                continue
            if pmid in papers:
                row = papers[pmid]
                if g.gene not in row["genes"].split(";"):
                    row["genes"] = ";".join(sorted(set(row["genes"].split(";")) | {g.gene}))
                    if g.weak:
                        row["weak_genes"] = ";".join(
                            sorted(set(filter(None, row["weak_genes"].split(";"))) | {g.gene})
                        )
                    row["found_by"] = ";".join(sorted(set(row["found_by"].split(";")) | {"epmc_gene_query"}))
                continue
            status, reason, n = ls.screen_paper(rec, b["heldout"], panel, b["eval_genes"])
            papers[pmid] = ls.paper_row(
                rec, status, reason, n, [g], "query_gene", [], hpoa_pmids, "epmc_gene_query"
            )
        selected = sum(
            1 for p in papers.values() if p["status"] == "selected" and g.gene in p["genes"].split(";")
        )
        gene_rows.append(
            {
                "gene": g.gene,
                "weakness": g.weakness,
                "hit_count": e["hitCount"],
                "records": len(e["results"]),
                "symbol_in_title": title_hits,
                "selected_papers": selected,
                "query": e["query"],
            }
        )

    rows = b["rows"]
    paper_rows = sorted(
        papers.values(),
        key=lambda p: (p["status"] != "selected", not p["cited_by_genereviews"], p["genes"], int(p["pmid"])),
    )
    out = _out_dir(artifact_id)
    chapters_path, papers_path = out / "chapters.tsv", out / "papers.tsv"
    queries_path, summary_path = out / "gene-queries.tsv", out / "summary.json"
    _write_tsv(rows, CHAPTER_COLUMNS, chapters_path)
    _write_tsv(paper_rows, PAPER_COLUMNS, papers_path)
    _write_tsv(gene_rows, ("gene", "weakness", "hit_count", "records", "symbol_in_title", "selected_papers",
                           "query"), queries_path)  # fmt: skip

    usable = [r for r in rows if r["status"] == "usable"]
    selected = [p for p in paper_rows if p["status"] == "selected"]
    gr_genes = {g for r in usable for g in r["construction_genes"].split(";")}
    paper_genes = {g for p in selected for g in p["genes"].split(";")}
    weak = {g.gene for g in b["genes"] if g.construction and g.simulable and g.weak}
    summary = {
        "chapters": {
            "in_gene_map": len(rows),
            "by_status": dict(Counter(r["status"] for r in rows)),
            "usable_by_priority_class": dict(Counter(r["priority_class"] for r in usable)),
            "usable_with_numeric_table": sum(r["has_numeric_frequency_table"] for r in usable),
            "usable_with_numeric_age_sentence": sum(r["age_numeric_sentences"] > 0 for r in usable),
            "construction_genes_covered": len(gr_genes),
            "weak_construction_genes_covered": len(gr_genes & weak),
        },
        "papers": {
            "cited_pmids_of_usable_chapters": len(b["cited"]),
            "open_access_records_screened": sum(p["cited_by_genereviews"] for p in paper_rows),
            "second_pass_genes": len(b["second_pass"]),
            "second_pass_records_screened": sum(not p["cited_by_genereviews"] for p in paper_rows),
            "by_status_reason": dict(
                Counter(f"{p['status']}:{p['reason'].split(':')[0]}" for p in paper_rows)
            ),
            "selected": len(selected),
            "selected_cited_by_genereviews": sum(p["cited_by_genereviews"] for p in selected),
            "selected_by_licence": dict(Counter(p["licence"] for p in selected)),
            "in_hpoa_marked": sum(p["in_hpoa"] for p in paper_rows),
            "genes_with_selected_paper": len(paper_genes),
            "weak_genes_with_selected_paper": len(paper_genes & weak),
            "second_pass_genes_with_selected_paper": sum(r["selected_papers"] > 0 for r in gene_rows),
        },
        "genes": {
            "construction_weak_simulable": len(weak),
            "with_chapter_or_paper": len(gr_genes | paper_genes),
            "weak_with_chapter_or_paper": len((gr_genes | paper_genes) & weak),
        },
        "llm_classification": "none: every paper decision is the deterministic screen",
    }
    summary_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")

    sources = registry.load_sources()
    mask = splits.heldout_pmids_path("r1-v1")
    inputs = [
        sources["genereviews"].as_input(),
        sources["hpo_annotations"].as_input(),
        *(
            {"id": f"artifact:{a}", "sha256": sha256_file(_verified(a, s))}
            for a, s in ((GENES_ID, "genes.json.gz"), (RECOUNT_ID, "phenotype.hpoa"), (SPLIT_ID, ".tsv"))
        ),
        {"id": "heldout-pmids:r1-v1", "sha256": sha256_file(mask)},
        {"id": "literature-panel-v2:curated.tsv", "sha256": sha256_file(PANEL_ROWS)},
    ]
    params = {
        "chapter_rule": "drop if the gene map or OMIM ids touch an evaluation unit (litpanel-split-v3 "
        "genes and all disease ids), if not in the archive, if any cited PMID is R1 held-out, or if it "
        "covers no construction gene (a vocabulary gene that is not an evaluation gene and whose main "
        "disease is not an evaluation disease)",
        "numeric_table": "SOURCES-SCOPING-001 screen: a feature table with >= 1 numeric row",
        "priority": "P1 weak gene + numeric table, P2 weak gene, P3 numeric table, P4 rest; then more weak "
        "genes, more numeric table rows, NBK id",
        "weak_tiers": list(ls.WEAK_TIERS),
        "reuse_licences": list(ls.REUSE_LICENCES),
        "min_patients": ls.MIN_PATIENTS,
        "excluded_pub_types": ls.EXCLUDED_PUB_TYPES,
        "screen_order": ls.screen_paper.__doc__.split("The rule, in order: ")[1].split("\n\n")[0],
        "count_window": ls.COUNT_WINDOW,
        "pmid_query": ls.epmc_pmid_query(["<PMID>"]),
        "gene_query": ls.epmc_gene_query("<SYMBOL>"),
        "second_pass_genes": "simulable weak (W1-W4) construction genes with no usable chapter; records kept "
        "only if a gene symbol is in the title (case-sensitive)",
        "in_hpoa": "a selected paper cited by phenotype.hpoa for a main disease of its genes is excluded",
        "europe_pmc": EPMC_SEARCH,
    }
    outputs = [chapters_path, papers_path, queries_path, summary_path, cache]
    notes = (
        f"{len(usable)} usable chapters, {len(selected)} selected papers. Frozen before any extraction "
        "(ADR-0013). The Europe PMC cache holds raw open-access metadata and abstracts; private release only."
    )
    manifest = build_manifest(artifact_id, "lit-sources", inputs, params, outputs, notes=notes, state=state)
    if publish:
        manifest = publish_release(manifest, artifact_id)
    write_manifest(manifest)
    typer.echo(json.dumps(summary, indent=1))
    typer.echo(str(Path(manifest.path).relative_to(REPO_ROOT)))
