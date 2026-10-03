"""`dxt lit`: extraction shards over lit-sources-v1, shard validation and the blind cross-check (ADR-0013)."""

import csv
import gzip
import hashlib
import json
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import typer

from diagnostic_ar_training import DATA_DIR, INTERIM_DIR, REPO_ROOT
from diagnostic_ar_training.lineage.registry import LineageError

extract_app = typer.Typer(no_args_is_help=True, help="Literature extraction shards (ADR-0013).")
crosscheck_app = typer.Typer(no_args_is_help=True, help="Blind Codex re-extraction of a seeded sample.")
extract_app.add_typer(crosscheck_app, name="crosscheck")
audit_app = typer.Typer(no_args_is_help=True, help="Codex audit of a seeded sample of sources.")
extract_app.add_typer(audit_app, name="audit")

SOURCES_ID = "lit-sources-v1"
PAPERS_V2_ID = "lit-papers-v2"
EXTRACT_DIR = DATA_DIR / "lit-extract"
SHARDS_PATH = EXTRACT_DIR / "shards.tsv"
ROWS_DIR = EXTRACT_DIR / "rows"
NOTES_DIR = EXTRACT_DIR / "notes"
REPORTS_DIR = EXTRACT_DIR / "reports"
CROSSCHECK_DIR = EXTRACT_DIR / "crosscheck"
AUDIT_DIR = EXTRACT_DIR / "audit"
TEXT_DIR = INTERIM_DIR / "lit-text"
WORK_DIR = INTERIM_DIR / "lit-extract"
EPMC_REST = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CODEX = (
    "codex exec --skip-git-repo-check --ephemeral -s read-only --output-schema {schema} -o {answer} {prompt}"
)
AUDIT_CODEX = CODEX.replace("-s read-only", "-s read-only -c 'model_reasoning_effort=\"medium\"'")
ITEM_COLUMNS = (
    "item", "shard", "row", "source_id", "gene", "disease_id", "disease_name", "feature_label", "hpo_id",
    "population", "sex_restriction", "citation", "section", "passage_chars",
)  # fmt: skip


def _read_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as h:
        return list(csv.DictReader(h, delimiter="\t", quoting=csv.QUOTE_NONE))


def _write_tsv(rows: list[dict], columns: tuple[str, ...], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(columns), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows({c: r.get(c, "") for c in columns} for r in rows)


def _eval_boundary() -> tuple[set[str], set[str]]:
    from diagnostic_ar_training.cli_lit import SPLIT_ID, _verified

    genes, diseases = set(), set()
    for row in _read_tsv(_verified(SPLIT_ID, ".tsv")):
        genes |= {row["gene"].upper(), row["symbol"].upper()}
        diseases |= set(row["disease_ids"].split(";")) | {row["disease_id"]}
    return genes, diseases


def _heldout() -> set[str]:
    from diagnostic_ar_training import splits

    splits.write_heldout_pmids("r1-v1")
    return {x.removeprefix("PMID:") for x in splits.heldout_pmids_path("r1-v1").read_text().split()}


def _shards_path(shard_set: str) -> Path:
    return SHARDS_PATH if shard_set == "v1" else EXTRACT_DIR / f"shards-{shard_set}.tsv"


def _shard_rows(shard: str) -> list[dict]:
    from diagnostic_ar_training.knowledge import lit_extract as le

    try:
        path = _shards_path(le.shard_set(shard))
    except ValueError as e:
        raise LineageError(str(e)) from e
    if not path.is_file():
        raise LineageError(f"{path.relative_to(REPO_ROOT)} is missing; run `dxt lit shards`")
    rows = [r for r in _read_tsv(path) if r["shard"] == shard]
    if not rows:
        raise LineageError(f"no shard {shard} in {path.name}")
    return rows


@extract_app.command("shards")
def shards(
    shard_set: str = typer.Option("v1", "--set", help="v1 (C/P shards over lit-sources-v1) or papers-v2 (Q)"),
    force: bool = typer.Option(False, help="Overwrite a shards file that differs"),
) -> None:
    """Assign frozen sources to shards, with the units each may feed.

    `--set v1`: lit-sources-v1 chapters (C) and papers (P), `shards.tsv`.
    `--set papers-v2`: the lit-papers-v2 subset (Q), `shards-papers-v2.tsv`.
    """
    from diagnostic_ar_training.cli_lit import GENES_ID, SPLIT_ID, _verified
    from diagnostic_ar_training.knowledge import lit_extract as le
    from diagnostic_ar_training.lineage.hashing import sha256_file

    if shard_set not in le.SHARD_SETS:
        raise typer.BadParameter(f"--set must be one of {sorted(le.SHARD_SETS)}")
    papers_path = _verified(SOURCES_ID, "papers.tsv")
    genes_path = _verified(GENES_ID, "genes.json.gz")
    eval_genes, eval_diseases = _eval_boundary()
    entities = le.construction_entities(json.load(gzip.open(genes_path)), eval_genes, eval_diseases)
    inputs = {
        f"{SOURCES_ID}:papers.tsv": sha256_file(papers_path),
        f"{GENES_ID}:genes.json.gz": sha256_file(genes_path),
        f"{SPLIT_ID}.tsv": sha256_file(_verified(SPLIT_ID, ".tsv")),
    }
    rules = {
        "paper_units": "every simulable genes-v2 entity of the paper's genes",
        "excluded": "evaluation genes and every entity sharing an id with a litpanel-split-v3 disease; "
        "genes whose main entity does",
    }
    if shard_set == "v1":
        chapters_path = _verified(SOURCES_ID, "chapters.tsv")
        rows = le.assign_shards(_read_tsv(chapters_path), _read_tsv(papers_path), entities)
        inputs[f"{SOURCES_ID}:chapters.tsv"] = sha256_file(chapters_path)
        rules |= {
            "chapters": f"usable chapters in priority order (P1..P4, then priority_rank), "
            f"{le.CHAPTERS_PER_SHARD} per shard, ids C001...",
            "papers": f"selected papers in papers.tsv order, {le.PAPERS_PER_SHARD} per shard, ids P001...",
            "chapter_units": "per construction gene of the chapter, its simulable genes-v2 entities "
            "whose ids meet the chapter's OMIM ids, else its main entity",
        }
    else:
        rescreen_path = _verified(PAPERS_V2_ID, "papers.tsv")
        order = le.papers_v2_order(_read_tsv(papers_path), _read_tsv(rescreen_path))
        rows = le.assign_paper_shards(order, entities, "Q")
        inputs[f"{PAPERS_V2_ID}:papers.tsv"] = sha256_file(rescreen_path)
        rules["papers"] = (
            f"{SOURCES_ID} selected papers in papers.tsv order, filtered to the {PAPERS_V2_ID} subset, "
            f"{le.PAPERS_PER_SHARD} per shard, ids Q001..."
        )
    path = _shards_path(shard_set)
    tmp = path.with_suffix(".tsv.new")
    _write_tsv(rows, le.SHARD_COLUMNS, tmp)
    if path.exists() and path.read_bytes() != tmp.read_bytes() and not force:
        tmp.unlink()
        raise LineageError(f"{path.name} would change; shards are fixed once extraction starts (--force)")
    tmp.replace(path)
    summary = le.shards_summary(rows)
    summary["inputs"] = inputs
    summary["shards_tsv_sha256"] = sha256_file(path)
    summary["rules"] = rules
    path.with_suffix(".json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    typer.echo(json.dumps({k: v for k, v in summary.items() if k != "sources_without_units"}, indent=1))


# --- Source text ----------------------------------------------------------------


def _text_paths(source_id: str) -> tuple[Path, Path]:
    folder = TEXT_DIR / ("genereviews" if source_id.startswith("NBK") else "epmc")
    stem = source_id.replace(":", "")
    return folder / f"{stem}.txt", folder / f"{stem}.meta.json"


def _get(url: str, data: bytes | None = None) -> bytes | None:
    """GET (or POST) with retries; None on 404."""
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            wait = min(240, 15 * 2**attempt)
            typer.echo(f"HTTP {e.code} for {url}; retry in {wait}s", err=True)
        except (urllib.error.URLError, TimeoutError) as e:
            wait = min(240, 15 * 2**attempt)
            typer.echo(f"{e} for {url}; retry in {wait}s", err=True)
        time.sleep(wait)
    raise LineageError(f"{url} unreachable after 6 attempts")


def _save_text(source_id: str, text: str, meta: dict) -> None:
    txt, meta_path = _text_paths(source_id)
    txt.parent.mkdir(parents=True, exist_ok=True)
    txt.write_text(text, encoding="utf-8")
    meta |= {"source_id": source_id, "sha256": hashlib.sha256(text.encode()).hexdigest()}
    meta_path.write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")


def _fetch_paper(source_id: str, pmcid: str) -> None:
    from diagnostic_ar_training.knowledge import lit_extract as le
    from diagnostic_ar_training.knowledge import lit_sources as ls

    fetched = datetime.now(UTC).isoformat(timespec="seconds")
    txt, _ = _text_paths(source_id)
    raw = txt.with_suffix(".xml.gz")
    xml = gzip.decompress(raw.read_bytes()) if raw.is_file() else None
    if xml is None and pmcid:
        url = f"{EPMC_REST}/{pmcid}/fullTextXML"
        xml = _get(url)
        if xml and b"<body" in xml:
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(gzip.compress(xml))
        else:
            xml = None
    if xml is not None:
        meta = {"access_path": "europepmc-fulltext", "url": f"{EPMC_REST}/{pmcid}/fullTextXML"}
        _save_text(
            source_id, le.render_jats(xml), meta | {"fetched_utc": fetched, "renderer": le.TEXT_RENDERER}
        )
        return
    pmid = source_id.removeprefix("PMID:")
    query = urllib.parse.urlencode(
        {"query": f"EXT_ID:{pmid} AND SRC:MED", "resultType": "core", "format": "json"}
    )
    data = json.loads(_get(f"{EPMC_REST}/search?{query}") or b"{}")
    hits = [r for r in data.get("resultList", {}).get("result", []) if str(r.get("pmid")) == pmid]
    if not hits or not hits[0].get("abstractText"):
        raise LineageError(f"{source_id}: no full text and no abstract in Europe PMC")
    rec = hits[0]
    text = le.render_abstract(ls.plain(rec.get("title")), ls.plain(rec.get("abstractText")))
    meta = {"access_path": "europepmc-abstract", "url": f"{EPMC_REST}/search?{query}"}
    _save_text(source_id, text, meta | {"fetched_utc": fetched, "renderer": le.TEXT_RENDERER})


def _ensure_texts(rows: list[dict]) -> dict:
    """Cache the plain text of every source of the shard; source_id -> SourceText."""
    from diagnostic_ar_training.knowledge import lit_extract as le

    def stale(source_id: str) -> bool:
        txt, meta = _text_paths(source_id)
        if not (txt.is_file() and meta.is_file()):
            return True
        m = json.loads(meta.read_text())
        return (
            m.get("renderer") != le.TEXT_RENDERER
            or m.get("sha256") != hashlib.sha256(txt.read_bytes()).hexdigest()
        )

    chapters = [r for r in rows if r["kind"] == "chapters" and stale(r["source_id"])]
    if chapters:
        from diagnostic_ar_training.knowledge import lit_sources as ls
        from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source

        snapshot = open_source("genereviews", Purpose.KB)
        version = load_sources()["genereviews"].version
        _, nxml = ls.read_snapshot(snapshot)
        for r in chapters:
            if r["alt_id"] not in nxml:
                raise LineageError(f"{r['source_id']} ({r['alt_id']}) is not in the GeneReviews snapshot")
            meta = {
                "access_path": "genereviews-snapshot",
                "url": f"source:genereviews@{version}/gene_NBK1116/{r['alt_id']}.nxml",
                "renderer": le.TEXT_RENDERER,
            }
            _save_text(r["source_id"], le.render_jats(nxml[r["alt_id"]]), meta)
    for r in rows:
        if r["kind"] == "papers" and stale(r["source_id"]):
            _fetch_paper(r["source_id"], r["alt_id"])
    out = {}
    for r in rows:
        txt, meta = _text_paths(r["source_id"])
        m = json.loads(meta.read_text())
        out[r["source_id"]] = le.SourceText(txt.read_text(encoding="utf-8"), m["access_path"], m["sha256"])
    return out


def _disease_names() -> dict[str, str]:
    from diagnostic_ar_training.lineage.registry import Purpose, open_source

    names: dict[str, str] = {}
    with open_source("hpo_annotations", Purpose.KB).open(encoding="utf-8") as h:
        lines = (x for x in h if not x.startswith("#"))
        for row in csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE):
            names.setdefault(row["database_id"], row["disease_name"])
    return names


@extract_app.command("fetch-text")
def fetch_text(shard: str) -> None:
    """Cache every source text of a shard and write its worksheet (texts, allowed units, row header)."""
    from diagnostic_ar_training.knowledge import lit_extract as le

    rows = _shard_rows(shard)
    texts = _ensure_texts(rows)
    names = _disease_names()
    out = [f"# Shard {shard} worksheet", "", f"Rows file: data/lit-extract/rows/{shard}.tsv", ""]
    out += ["Header (tab-separated, in this order):", "", "\t".join(le.ROW_COLUMNS), ""]
    for r in rows:
        txt, _ = _text_paths(r["source_id"])
        t = texts[r["source_id"]]
        out += [
            f"## {r['position']}. {r['source_id']} ({r['alt_id']}): {r['title']}",
            "",
            f"- text: {txt.relative_to(REPO_ROOT)} ({len(t.text):,} chars, access_path {t.access_path})",
            f"- source_kind: {r['source_kind']}; licence: {r['licence']}",
            f"- units it may feed (gene | disease_id | name): {len(le.parse_units(r['units']))}",
        ]
        out += [f"  - {g} | {d} | {names.get(d, '?')}" for g, d in sorted(le.parse_units(r["units"]))]
        out.append("")
    path = WORK_DIR / shard / "worksheet.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    for r in rows:
        t = texts[r["source_id"]]
        typer.echo(f"{r['source_id']:14} {t.access_path:22} {len(t.text):>8,} chars  {r['title'][:60]}")
    typer.echo(f"worksheet: {path.relative_to(REPO_ROOT)}")


@extract_app.command("hpo")
def hpo(
    query: list[str] = typer.Argument(None, help="Words that must all occur in a label or synonym"),
    term: str = typer.Option("", help="Show one term: label, definition, synonyms, parents, children"),
    limit: int = typer.Option(25),
) -> None:
    """Look up HPO terms in the pinned release (current terms under Phenotypic abnormality only)."""
    from diagnostic_ar_training.knowledge import lit_extract as le
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology

    path = open_source("hpo_ontology", Purpose.KB)
    ontology = Ontology.from_json(path)
    index = le.hpo_index(json.loads(path.read_text())["graphs"][0])
    if term:
        current = ontology.resolve(term)
        if current is None:
            raise LineageError(f"{term} does not resolve in the pinned HPO")
        label, syns, definition = index[current]
        typer.echo(f"{current} {label}" + (f"  (resolved from {term})" if current != term else ""))
        typer.echo(f"  definition: {definition}")
        typer.echo(f"  synonyms: {'; '.join(syns)}")
        for kind, terms in (("parent", ontology.parents(current)), ("child", ontology.children(current))):
            for t in terms:
                typer.echo(f"  {kind}: {t} {ontology.labels.get(t, '')}")
        return
    for t, label, syn in le.hpo_search(index, ontology, " ".join(query or []), limit):
        typer.echo(f"{t}  {label}" + (f"  [synonym: {syn}]" if syn else ""))


# --- Validation -----------------------------------------------------------------


@lru_cache(maxsize=1)
def _genereviews_snapshot():
    from diagnostic_ar_training.knowledge import lit_sources as ls
    from diagnostic_ar_training.lineage.registry import Purpose, open_source

    return ls.read_snapshot(open_source("genereviews", Purpose.KB))


@lru_cache(maxsize=1)
def _validation_context():
    """What every shard is checked against: ontology, evaluation boundary, held-out PMIDs, chapter list."""
    from diagnostic_ar_training.cli_lit import _verified
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology

    eval_genes, eval_diseases = _eval_boundary()
    chapters = {r["nbk"]: r for r in _read_tsv(_verified(SOURCES_ID, "chapters.tsv"))}
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    return ontology, eval_genes, eval_diseases, _heldout(), chapters


def _validate(shard: str) -> tuple[list[str], dict, list[dict]]:
    """(problems, report, rows) of a shard; writes nothing."""
    from diagnostic_ar_training.knowledge import lit_extract as le
    from diagnostic_ar_training.knowledge import lit_sources as ls
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file

    shard_rows = _shard_rows(shard)
    rows_path = ROWS_DIR / f"{shard}.tsv"
    if not rows_path.is_file():
        raise LineageError(f"{rows_path.relative_to(REPO_ROOT)} is missing")
    with rows_path.open(encoding="utf-8", newline="") as h:
        header = h.readline().rstrip("\n").split("\t")
    problems = []
    if tuple(header) != le.ROW_COLUMNS:
        problems.append(f"header must be exactly: {chr(9).join(le.ROW_COLUMNS)}")
    rows = _read_tsv(rows_path)
    texts = _ensure_texts(shard_rows)
    sources = {
        r["source_id"]: le.ShardSource(
            r["source_id"], r["kind"], r["source_kind"], r["licence"], le.parse_units(r["units"]), r["title"]
        )
        for r in shard_rows
    }
    ontology, eval_genes, eval_diseases, heldout, chapters = _validation_context()
    chapter_heldout = {}
    nbk = [r for r in shard_rows if r["kind"] == "chapters"]
    if nbk:
        _, nxml = _genereviews_snapshot()
        for r in nbk:
            cited = ls.screen_chapter(nxml[r["alt_id"]]).pmids & heldout
            if cited or chapters[r["source_id"]]["status"] != "usable":
                chapter_heldout[r["source_id"]] = sorted(cited) or ["status not usable"]
    boundary = le.Boundary(ontology, eval_genes, eval_diseases, heldout, chapter_heldout)
    problems += le.check_rows(rows, sources, texts, boundary)
    notes_path = NOTES_DIR / f"{shard}.tsv"
    if not notes_path.is_file():
        problems.append(f"{notes_path.relative_to(REPO_ROOT)} is missing")
    else:
        notes = _read_tsv(notes_path)
        if notes and tuple(notes[0]) != le.NOTES_COLUMNS:
            problems.append(f"notes header must be exactly: {chr(9).join(le.NOTES_COLUMNS)}")
        problems += le.check_notes(notes, [r["source_id"] for r in shard_rows], rows)
    report = {
        "shard": shard,
        "status": "fail" if problems else "pass",
        "validated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "code": code_state().as_dict(),
        "rows_sha256": sha256_file(rows_path),
        "notes_sha256": sha256_file(notes_path) if notes_path.is_file() else "",
        "stats": le.row_stats(rows) if rows and tuple(header) == le.ROW_COLUMNS else {},
        "sources": {
            r["source_id"]: {
                "rows": sum(x.get("source_id") == r["source_id"] for x in rows),
                "access_path": texts[r["source_id"]].access_path,
                "text_sha256": texts[r["source_id"]].sha256,
                "text_renderer": le.TEXT_RENDERER,
            }
            for r in shard_rows
        },
        "problems": problems,
    }
    return problems, report, rows


@extract_app.command("validate-shard")
def validate_shard(shard: str) -> None:
    """Check a shard's rows (HPO, counts, verbatim quotes, units, held-out PMIDs) and write its report."""
    problems, report, rows = _validate(shard)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"{shard}.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    for p in problems:
        typer.echo(f"FAIL {p}", err=True)
    typer.echo(f"{shard}: {len(rows)} rows, {len(problems)} problems -> {out.relative_to(REPO_ROOT)}")
    if problems:
        raise typer.Exit(1)


# --- Cross-check ----------------------------------------------------------------


def _cc_dir(name: str) -> Path:
    return WORK_DIR / "crosscheck" / name


@crosscheck_app.command("prepare")
def crosscheck_prepare(
    name: str = typer.Option(..., help="Run name, e.g. pilot-C001 or lit-extract-v1"),
    shard: list[str] = typer.Option(..., "--shard", help="Validated shards to sample (repeatable)"),
    fraction: float = typer.Option(0.1),
    seed: int = typer.Option(20261001),
    all_under: int = typer.Option(0, help="Take every row of a shard with fewer rows than this"),
) -> None:
    """Write the blind inputs (prompt + source passage) for a seeded sample of the shards' rows."""
    from diagnostic_ar_training.knowledge import lit_extract as le
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology

    rows_by_shard = {}
    for s in shard:
        report = REPORTS_DIR / f"{s}.json"
        if not report.is_file() or json.loads(report.read_text())["status"] != "pass":
            raise LineageError(f"{s} has no passing validation report; run `dxt lit validate-shard {s}`")
        rows_by_shard[s] = _read_tsv(ROWS_DIR / f"{s}.tsv")
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    picks = le.sample(rows_by_shard, fraction, seed, all_under)
    base = _cc_dir(name)
    (base / "items").mkdir(parents=True, exist_ok=True)
    (base / "schema.json").write_text(le.schema_json() + "\n")
    items = []
    texts = {}
    for s in shard:
        texts |= _ensure_texts(_shard_rows(s))
    for n, (s, i) in enumerate(picks, start=1):
        row = rows_by_shard[s][i]
        item = f"{n:04d}"
        text = texts[row["source_id"]].text
        block = le.passage(text, row["section"]) or text
        folder = base / "items" / item
        folder.mkdir(exist_ok=True)
        (folder / "prompt.txt").write_text(le.crosscheck_prompt(row, ontology.labels.get(row["hpo_id"], "")))
        (folder / "passage.txt").write_text(block + "\n", encoding="utf-8")
        items.append({**{c: row.get(c, "") for c in le.ROW_COLUMNS}, "item": item, "shard": s, "row": i + 2,
                      "passage_chars": len(block)})  # fmt: skip
    _write_tsv(items, ITEM_COLUMNS, CROSSCHECK_DIR / f"{name}.items.tsv")
    typer.echo(
        f"{len(items)} items from {sum(map(len, rows_by_shard.values()))} rows -> "
        f"{base.relative_to(REPO_ROOT)}"
    )


@crosscheck_app.command("run")
def crosscheck_run(
    name: str = typer.Option(...),
    limit: int = typer.Option(0, help="At most this many pending items (0 = all); Codex has usage limits"),
    workers: int = typer.Option(2),
    command: str = typer.Option(CODEX, help="Re-extractor; {schema}, {answer}, {prompt} are filled in"),
) -> None:
    """Ask Codex each pending item blind (passage on stdin); resumable, one answer.json per item."""
    base = _cc_dir(name)
    items = sorted(p for p in (base / "items").iterdir() if p.is_dir())
    pending = [p for p in items if not (p / "answer.json").is_file()]
    if limit:
        pending = pending[:limit]
    typer.echo(f"{len(items)} items, {len(pending)} to ask")

    def ask(folder: Path) -> tuple[str, int, float]:
        start = time.time()
        fill = {
            "{schema}": str(base / "schema.json"),
            "{answer}": str(folder / "answer.json"),
            "{prompt}": (folder / "prompt.txt").read_text(),
        }
        args = [fill.get(a, a) for a in shlex.split(command)]
        proc = subprocess.run(
            args,
            input=(folder / "passage.txt").read_text(encoding="utf-8"),
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
            cwd=folder,
        )
        (folder / "codex.log").write_text(
            f"exit {proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}"
        )
        if proc.returncode != 0:
            (folder / "answer.json").unlink(missing_ok=True)
        return folder.name, proc.returncode, time.time() - start

    failures = 0
    with ThreadPoolExecutor(workers) as pool:
        for item, code, secs in pool.map(ask, pending):
            failures += code != 0
            typer.echo(f"item {item}: exit {code} ({secs:.0f}s)")
    if failures:
        typer.echo(f"{failures} items failed (see codex.log); re-run to retry", err=True)
        raise typer.Exit(1)


@crosscheck_app.command("score")
def crosscheck_score(name: str = typer.Option(...)) -> None:
    """Parse Codex's answers, compare with our rows (panel rule) and write the cross-check TSV."""
    from diagnostic_ar_training.knowledge import lit_extract as le

    base = _cc_dir(name)
    items = _read_tsv(CROSSCHECK_DIR / f"{name}.items.tsv")
    out_path = CROSSCHECK_DIR / f"{name}.tsv"
    resolutions = {r["item"]: r["resolution"] for r in _read_tsv(out_path)} if out_path.is_file() else {}
    rows_cache: dict[str, list[dict]] = {}
    out, missing = [], []
    for it in items:
        rows = rows_cache.setdefault(it["shard"], _read_tsv(ROWS_DIR / f"{it['shard']}.tsv"))
        row = rows[int(it["row"]) - 2]
        if (row["source_id"], row["gene"], row["feature_label"], row["hpo_id"]) != (
            it["source_id"], it["gene"], it["feature_label"], it["hpo_id"]
        ):  # fmt: skip
            raise LineageError(f"item {it['item']}: {it['shard']} row {it['row']} changed since prepare")
        answer = base / "items" / it["item"] / "answer.json"
        if not answer.is_file():
            missing.append(it["item"])
            continue
        try:
            other = le.parse_answer(json.loads(answer.read_text()))
        except (json.JSONDecodeError, TypeError, ValueError):
            other = {"found": False, "low": "", "point": "", "high": "", "n": "", "quote": "unparseable"}
        lo, point, hi = le.ours(row)
        out.append(
            {
                **{
                    c: it[c]
                    for c in (
                        "item",
                        "shard",
                        "row",
                        "source_id",
                        "gene",
                        "disease_id",
                        "feature_label",
                        "hpo_id",
                        "population",
                        "sex_restriction",
                        "section",
                    )
                },  # fmt: skip
                "ours_low": lo,
                "ours_point": point,
                "ours_high": hi,
                "other_found": str(other["found"]).lower(),
                "other_low": other["low"],
                "other_point": other["point"],
                "other_high": other["high"],
                "other_n": other["n"],
                "other_quote": other["quote"].replace("\t", " ").replace("\n", " "),
                "agree": str(le.agrees(row, other)).lower(),
                "resolution": resolutions.get(it["item"], ""),
            }
        )
    _write_tsv(out, le.CROSSCHECK_COLUMNS, out_path)
    agree = sum(r["agree"] == "true" for r in out)
    summary = {
        "items": len(items),
        "answered": len(out),
        "missing": missing,
        "agree": agree,
        "agreement": round(agree / len(out), 4) if out else None,
        "disagreements_unresolved": [r["item"] for r in out if r["agree"] != "true" and not r["resolution"]],
    }
    (CROSSCHECK_DIR / f"{name}.summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    typer.echo(json.dumps(summary, indent=1))


# --- Audit ----------------------------------------------------------------------


def _audit_dir(name: str) -> Path:
    return WORK_DIR / "audit" / name


def _audit_sources() -> dict[str, list[dict]]:
    """Shard -> its shard-file rows (one per source, in position order) for every validated shard."""
    out: dict[str, list[dict]] = {}
    for path in (SHARDS_PATH, _shards_path("papers-v2")):
        for row in _read_tsv(path):
            out.setdefault(row["shard"], []).append(row)
    passing = {}
    for shard, rows in out.items():
        report = REPORTS_DIR / f"{shard}.json"
        if report.is_file() and json.loads(report.read_text())["status"] == "pass":
            passing[shard] = sorted(rows, key=lambda r: int(r["position"]))
    return passing


def _source_rows(shard: str, source_id: str) -> list[tuple[int, dict]]:
    """(line of the shard rows file, row) for every row of the source."""
    rows = _read_tsv(ROWS_DIR / f"{shard}.tsv")
    return [(i + 2, r) for i, r in enumerate(rows) if r["source_id"] == source_id]


@audit_app.command("prepare")
def audit_prepare(
    name: str = typer.Option(..., help="Run name, e.g. lit-extract-v1"),
    fraction: float = typer.Option(0.05),
    seed: int = typer.Option(20261002),
) -> None:
    """Write the audit inputs for a seeded sample of sources; the list is frozen."""
    from diagnostic_ar_training.knowledge import lit_audit as la
    from diagnostic_ar_training.knowledge import lit_extract as le
    from diagnostic_ar_training.lineage.registry import Purpose, open_source
    from diagnostic_ar_training.ontology import Ontology

    shard_sources = _audit_sources()
    notes = {
        shard: {n["source_id"]: n for n in _read_tsv(NOTES_DIR / f"{shard}.tsv")} for shard in shard_sources
    }
    frozen = AUDIT_DIR / f"{name}.items.tsv"
    if frozen.is_file():
        picks = [(r["item"], r["shard"], r["source_id"]) for r in _read_tsv(frozen)]
    else:
        usable = {
            shard: [
                r["source_id"]
                for r in rows
                if notes[shard].get(r["source_id"], {}).get("outcome") != "no_text"
            ]
            for shard, rows in shard_sources.items()
        }
        drawn = la.sample(usable, fraction, seed)
        picks = [(f"{n:04d}", shard, source) for n, (shard, source) in enumerate(drawn, start=1)]
    ontology = Ontology.from_json(open_source("hpo_ontology", Purpose.KB))
    names = _disease_names()
    base = _audit_dir(name)
    (base / "items").mkdir(parents=True, exist_ok=True)
    (base / "schema.json").write_text(la.schema_json() + "\n")
    items = []
    for item, shard, source in picks:
        shard_row = next(r for r in shard_sources[shard] if r["source_id"] == source)
        text = _ensure_texts([shard_row])[source].text
        rows = _source_rows(shard, source)
        note = notes[shard].get(source, {})
        cut = la.cut_source(text, [r["section"] for _, r in rows])
        units = la.units_text(
            sorted(le.parse_units(shard_row["units"])), names, note.get("outcome", ""), note.get("note", "")
        )
        folder = base / "items" / item
        folder.mkdir(exist_ok=True)
        (folder / "prompt.txt").write_text(la.PROMPT + "\n", encoding="utf-8")
        (folder / "source.txt").write_text(cut, encoding="utf-8")
        (folder / "units.txt").write_text(units, encoding="utf-8")
        (folder / "rows.tsv").write_text(la.rows_table(rows, ontology.labels), encoding="utf-8")
        items.append(
            {
                "item": item,
                "shard": shard,
                "source_id": source,
                "source_kind": shard_row["source_kind"],
                "outcome": note.get("outcome", ""),
                "rows": len(rows),
                "source_chars": len(cut),
            }
        )
    _write_tsv(items, la.ITEM_COLUMNS, frozen)
    per_shard = Counter(i["shard"] for i in items)
    typer.echo(
        f"{len(items)} sources of {sum(len(v) for v in shard_sources.values())} in {len(per_shard)} shards "
        f"-> {base.relative_to(REPO_ROOT)}; frozen list {frozen.relative_to(REPO_ROOT)}"
    )


@audit_app.command("run")
def audit_run(
    name: str = typer.Option(...),
    limit: int = typer.Option(0, help="At most this many pending items (0 = all); Codex has usage limits"),
    workers: int = typer.Option(2),
    command: str = typer.Option(
        AUDIT_CODEX, help="Auditor; {schema}, {answer}, {prompt} are filled in; the item's files go on stdin"
    ),
) -> None:
    """Ask Codex each pending item (source, units and rows on stdin); resumable, one answer.json per item."""
    from diagnostic_ar_training.knowledge import lit_audit as la

    base = _audit_dir(name)
    items = sorted(p for p in (base / "items").iterdir() if p.is_dir())
    pending = [p for p in items if not (p / "answer.json").is_file()]
    if limit:
        pending = pending[:limit]
    typer.echo(f"{len(items)} items, {len(pending)} to ask")

    def ask(folder: Path) -> tuple[str, int, float]:
        start = time.time()
        fill = {
            "{schema}": str(base / "schema.json"),
            "{answer}": str(folder / "answer.json"),
            "{prompt}": (folder / "prompt.txt").read_text(encoding="utf-8"),
        }
        args = [fill.get(a, a) for a in shlex.split(command)]
        parts = [(folder / f).read_text(encoding="utf-8") for f in ("source.txt", "units.txt", "rows.tsv")]
        proc = subprocess.run(
            args,
            input=la.stdin_text(*parts),
            capture_output=True,
            text=True,
            timeout=1500,
            check=False,
            cwd=folder,
        )
        (folder / "codex.log").write_text(
            f"exit {proc.returncode}\n--- stdout\n{proc.stdout}\n--- stderr\n{proc.stderr}"
        )
        if proc.returncode != 0:
            (folder / "answer.json").unlink(missing_ok=True)
        return folder.name, proc.returncode, time.time() - start

    failures = 0
    with ThreadPoolExecutor(workers) as pool:
        for item, code, secs in pool.map(ask, pending):
            failures += code != 0
            typer.echo(f"item {item}: exit {code} ({secs:.0f}s)")
    if failures:
        typer.echo(f"{failures} items failed (see codex.log); re-run to retry", err=True)
        raise typer.Exit(1)


@audit_app.command("score")
def audit_score(
    name: str = typer.Option(...),
    from_item: str = typer.Option(
        "",
        help="Items before this one keep their issues from the existing issues file; use it after "
        "audit fixes changed their shard rows (their row numbers refer to the rows at prepare time)",
    ),
) -> None:
    """Parse the answers; summarise issues per shard and list every flagged issue for human review."""
    from diagnostic_ar_training.knowledge import lit_audit as la

    base = _audit_dir(name)
    items = _read_tsv(AUDIT_DIR / f"{name}.items.tsv")
    issues_path = AUDIT_DIR / f"{name}.issues.tsv"
    resolutions = (
        {
            (r["item"], r["kind"], r["row"], r["feature"], r["detail"]): r["resolution"]
            for r in _read_tsv(issues_path)
        }
        if issues_path.is_file()
        else {}
    )
    frozen = _read_tsv(issues_path) if from_item and issues_path.is_file() else []
    results, flagged, missing, unparseable, row_counts = [], [], [], [], {}
    for it in items:
        keep = bool(from_item) and it["item"] < from_item
        rows = {} if keep else dict(_source_rows(it["shard"], it["source_id"]))
        if not keep and len(rows) != int(it["rows"]):
            raise LineageError(
                f"item {it['item']}: {it['shard']} {it['source_id']} rows changed since prepare"
            )
        row_counts[it["item"]] = int(it["rows"]) if keep else len(rows)
        answer = base / "items" / it["item"] / "answer.json"
        if not answer.is_file():
            missing.append(it["item"])
            continue
        try:
            parsed = la.parse_answer(json.loads(answer.read_text()))
        except (json.JSONDecodeError, ValueError):
            unparseable.append(it["item"])
            continue
        found = [r for r in frozen if r["item"] == it["item"]] if keep else la.issues(it, parsed, rows)
        for issue in [] if keep else found:
            for c in ("detail", "quote"):
                issue[c] = issue[c].replace("\t", " ").replace("\n", " ")
            key = (
                it["item"],
                issue["kind"],
                str(issue.get("row", "")),
                issue.get("feature", ""),
                issue["detail"],
            )
            issue["resolution"] = resolutions.get(key, "")
        results.append({"item": it["item"], "answer": parsed, "issues": found})
        flagged += found
    _write_tsv(flagged, la.ISSUE_COLUMNS, issues_path)
    summary = {
        "items": len(items),
        "answered": len(results),
        "missing": missing,
        "unparseable": unparseable,
        **la.summarise(results, items, row_counts),
        "issues_unresolved": sum(not i["resolution"] for i in flagged),
    }
    (AUDIT_DIR / f"{name}.summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    typer.echo(json.dumps(summary["total"], indent=1))
    typer.echo(f"{len(flagged)} issues -> {issues_path.relative_to(REPO_ROOT)}")


# --- Build ----------------------------------------------------------------------

BUILD_DIR = DATA_DIR / "lit-build"
GR_TITLES = "GRtitle_shortname_NBKid.txt"
BUILD_KINDS = ("hpoa-lit", "hpoa-enriched", "presentation-ages", "onset-ages")


def _chapter_index() -> dict[str, tuple[str, str]]:
    import tarfile

    from diagnostic_ar_training.knowledge import lit_build as lb
    from diagnostic_ar_training.knowledge import lit_sources as ls
    from diagnostic_ar_training.lineage.registry import Purpose, open_source

    with tarfile.open(open_source("genereviews", Purpose.KB), "r:gz") as tar:
        for member in tar:
            if member.name == f"{ls.INDEX_DIR}/{GR_TITLES}":
                return lb.chapter_index(tar.extractfile(member).read().decode("latin-1"))
    raise LineageError(f"{GR_TITLES} is not in the GeneReviews snapshot")


def _build_shards() -> tuple[list[dict], dict, dict]:
    """(rows of every accepted shard, accepted shard -> hashes, refused shard -> reason and rows).

    A shard is accepted when its committed report passes and it re-validates with no problem now.
    """
    from diagnostic_ar_training.lineage.hashing import sha256_file

    listed = []
    for path in (SHARDS_PATH, _shards_path("papers-v2")):
        listed += sorted({r["shard"] for r in _read_tsv(path)})
    rows, accepted, refused = [], {}, {}
    for shard in listed:
        rows_path = ROWS_DIR / f"{shard}.tsv"
        if not rows_path.is_file():
            continue
        report_path = REPORTS_DIR / f"{shard}.json"
        status = json.loads(report_path.read_text())["status"] if report_path.is_file() else "missing"
        if status != "pass":
            refused[shard] = {"reason": f"report status {status}", "rows": len(_read_tsv(rows_path))}
            continue
        problems, _, shard_rows = _validate(shard)
        if problems:
            refused[shard] = {
                "reason": "re-validation failed",
                "problems": len(problems),
                "rows": len(shard_rows),
            }
            continue
        accepted[shard] = {
            "rows": len(shard_rows),
            "rows_sha256": sha256_file(rows_path),
            "notes_sha256": sha256_file(NOTES_DIR / f"{shard}.tsv"),
        }
        rows += shard_rows
    return rows, accepted, refused


def _build_paths(dry_run: bool, out_dir: Path | None, ids: dict[str, str]) -> dict[str, Path]:
    if dry_run:
        names = {"hpoa-lit": "hpoa-lit.hpoa", "hpoa-enriched": "phenotype.hpoa"}
        return {k: out_dir / names.get(k, f"{k}.tsv") for k in BUILD_KINDS}
    base = INTERIM_DIR / "lit-build"
    return {
        "hpoa-lit": base / ids["hpoa-lit"] / "phenotype.hpoa",
        "hpoa-enriched": base / ids["hpoa-enriched"] / "phenotype.hpoa",
        "presentation-ages": base / ids["presentation-ages"] / "presentation-ages.tsv",
        "onset-ages": base / ids["onset-ages"] / "onset-ages.tsv",
    }


def _build_manifests(
    ids, paths, report_path, accepted, recount_id, recount_sha, lit_sha, state, publish
) -> None:
    from diagnostic_ar_training.knowledge import lit_build as lb
    from diagnostic_ar_training.lineage.manifest import build_manifest, write_manifest
    from diagnostic_ar_training.lineage.manifest import publish as publish_release
    from diagnostic_ar_training.lineage.registry import load_sources

    sources = load_sources()
    shard_inputs = [
        {"id": f"lit-extract:{s}:{kind}", "sha256": h[f"{kind}_sha256"]}
        for s, h in accepted.items()
        for kind in ("rows", "notes")
    ]
    recount_input = {"id": f"artifact:{recount_id}", "sha256": recount_sha}
    params = {"adr": "0013 amendment 2", "recount": recount_id, "evidence": lb.EVIDENCE,
              "biocuration": lb.BIOCURATION, "shards": sorted(accepted)}  # fmt: skip
    plan = {
        "hpoa-lit": (
            [
                *shard_inputs,
                recount_input,
                sources["genereviews"].as_input(),
                sources["hpo_ontology"].as_input(),
            ],
            [paths["hpoa-lit"], report_path],
        ),
        "hpoa-enriched": (
            [recount_input, {"id": f"artifact:{ids['hpoa-lit']}", "sha256": lit_sha}],
            [paths["hpoa-enriched"]],
        ),
        "presentation-ages": (shard_inputs, [paths["presentation-ages"]]),
        "onset-ages": (shard_inputs, [paths["onset-ages"]]),
    }
    for kind, (inputs, outputs) in plan.items():
        manifest = build_manifest(ids[kind], kind, inputs, params, outputs, state=state)
        if publish:
            manifest = publish_release(manifest, ids[kind])
        write_manifest(manifest)


@extract_app.command("build")
def build(
    version: int = typer.Option(
        0, help="N of hpoa-lit-vN, hpoa-enriched-vN, presentation-ages-vN, onset-ages-vN"
    ),
    recount_id: str = typer.Option(
        "hpoa-recount-v1", "--recount", help="hpoa-recount artifact the layer joins"
    ),
    dry_run: bool = typer.Option(False, help="Files and report only: no artifact ids, no manifests"),
    out_dir: Path = typer.Option(None, help="With --dry-run: directory for the four files"),
    report_path: Path = typer.Option(
        None, "--report", help="Report JSON (default data/lit-build/<id>.report.json)"
    ),
    publish: bool = typer.Option(False, help="Upload the four artifacts as releases (ADR-0005)"),
) -> None:
    """hpoa-lit, hpoa-enriched, presentation- and onset-ages from validated shards (ADR-0013 am. 2, 4)."""
    from diagnostic_ar_training.cli_lit import _verified
    from diagnostic_ar_training.knowledge import lit_build as lb
    from diagnostic_ar_training.knowledge import recount
    from diagnostic_ar_training.lineage.gitinfo import code_state
    from diagnostic_ar_training.lineage.hashing import sha256_file

    if dry_run == bool(version):
        raise typer.BadParameter("give either --version N (a real build) or --dry-run")
    if dry_run and (out_dir is None or report_path is None or publish):
        raise typer.BadParameter("--dry-run needs --out-dir and --report, and never publishes")
    ids = {k: f"{k}-v{version}" for k in BUILD_KINDS}
    state = code_state()
    if not dry_run:
        from diagnostic_ar_training.lineage.manifest import ensure_new

        for i in ids.values():
            ensure_new(i)
        if state.dirty:
            raise typer.BadParameter("commit your code first: artifacts must be reproducible from a SHA")
    label = {k: f"{k} (dry run)" for k in ids} if dry_run else ids

    rows, accepted, refused = _build_shards()
    recount_path = _verified(recount_id, "phenotype.hpoa")
    recount_sha = sha256_file(recount_path)
    comments, hpoa_rows = recount.read_hpoa(recount_path)
    result = lb.build(rows, hpoa_rows, _validation_context()[0], _chapter_index())

    paths = _build_paths(dry_run, out_dir, ids)
    for p in paths.values():
        p.parent.mkdir(parents=True, exist_ok=True)
    header = "\t".join(recount.COLUMNS) + "\n"
    lit_lines = lb.hpoa_lines(result["lit_rows"])
    lit_comments = [
        f"#description: {label['hpoa-lit']}: lit-extract rows as HPOA phenotype rows (ADR-0013 am. 2)\n",
        *(c for c in comments if c.startswith("#hpo-version:")),
        f"#derived: {len(accepted)} validated shards, {len(rows)} rows; biocuration {lb.BIOCURATION}\n",
    ]
    paths["hpoa-lit"].write_text("".join(lit_comments) + header + "".join(lit_lines), encoding="utf-8")
    lit_sha = sha256_file(paths["hpoa-lit"])
    body = recount_path.read_text(encoding="utf-8").split(header, 1)
    if len(body) != 2 or not body[1].endswith("\n"):
        raise LineageError(f"{recount_id}: unexpected phenotype.hpoa layout")
    enriched_note = (
        f"#derived: {label['hpoa-enriched']} = {recount_id} (phenotype.hpoa sha256 {recount_sha}) + "
        f"{label['hpoa-lit']} (sha256 {lit_sha}), concatenated\n"
    )
    paths["hpoa-enriched"].write_text(
        "".join(comments) + enriched_note + header + body[1] + "".join(lit_lines), encoding="utf-8"
    )
    paths["presentation-ages"].write_text(
        "".join(lb.presentation_lines(result["presentation_ages"])), encoding="utf-8"
    )
    paths["onset-ages"].write_text("".join(lb.onset_lines(result["onset_ages"])), encoding="utf-8")

    report = {
        "adr": "0013 amendments 2, 4",
        "dry_run": dry_run,
        "artifact_ids": {} if dry_run else ids,
        "code": state.as_dict(),
        "inputs": {
            "recount": {"id": recount_id, "phenotype_hpoa_sha256": recount_sha, "rows": len(hpoa_rows)},
            "shards_accepted": accepted,
            "shards_refused": refused,
        },
        **result["report"],
        "rows_dropped_failed_validation": sum(v["rows"] for v in refused.values()),
        "hpoa_enriched": {
            "rows": len(hpoa_rows) + len(result["lit_rows"]),
            "recount_rows": len(hpoa_rows),
            "lit_rows": len(result["lit_rows"]),
        },
        "outputs": {
            k: {"file": p.name, "sha256": sha256_file(p), "bytes": p.stat().st_size} for k, p in paths.items()
        },
        "residual_dependency": (
            "GeneReviews chapters synthesise literature HPOA may also cite; patient-level overlap "
            "is not detectable (rule 5)"
        ),
    }
    report_path = report_path or BUILD_DIR / f"{ids['hpoa-lit']}.report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    if not dry_run:
        _build_manifests(ids, paths, report_path, accepted, recount_id, recount_sha, lit_sha, state, publish)
    summary = {
        "shards": {"accepted": len(accepted), "refused": len(refused)},
        "rows_in": result["report"]["rows_in"],
        "hpoa_lit_rows": len(result["lit_rows"]),
        "presentation_age_diseases": len(result["presentation_ages"]),
        "onset_age_diseases": len(result["onset_ages"]),
    }
    typer.echo(json.dumps(summary, indent=1))
    typer.echo(f"report: {report_path}")
