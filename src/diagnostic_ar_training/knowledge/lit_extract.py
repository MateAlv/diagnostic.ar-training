"""lit-extract-v1: shards, source text, row checks and the blind cross-check (ADR-0013).

Extraction itself is done by shard agents following `docs/lit/EXTRACTION_GUIDE.md`.
This module holds everything that must be identical for all of them:
- the deterministic shard assignment over the frozen `lit-sources-v1` lists, with
  the construction units each source may feed;
- the plain-text rendering of a source (GeneReviews NXML or Europe PMC JATS) that
  agents read and that evidence quotes are checked against;
- the row schema and its checks;
- the seeded cross-check sample, the blind prompt and the agreement rule.

Everything here is a pure function of its inputs; network and file access live in
the CLI (`dxt lit ...`).
"""

import io
import json
import math
import random
import re
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

CHAPTERS_PER_SHARD = 10
PAPERS_PER_SHARD = 12
PRIORITY_ORDER = ("P1", "P2", "P3", "P4")
GENEREVIEWS_LICENCE = "genereviews-noncommercial"
TEXT_RENDERER = "lit-text-1"
MAX_QUOTE_WORDS = 25
SMALL_N = 5
QUOTE_GAP = " ... "
AGE_FEATURES = ("AGE_ONSET", "AGE_PRESENTATION")
FLAGS = ("small_n", "pooled", "named_period")
SEXES = ("", "male", "female")
SOURCE_KINDS = {"chapters": "genereviews", "papers": "cohort_paper"}
ACCESS_PATHS = ("genereviews-snapshot", "europepmc-fulltext", "europepmc-abstract")
MAX_AGE_YEARS = 120.0
PREVALENCE_TOLERANCE = 0.005

SHARD_COLUMNS = (
    "shard", "kind", "position", "source_id", "alt_id", "source_kind", "licence", "priority", "title",
    "construction_genes", "units",
)  # fmt: skip
ROW_COLUMNS = (
    "source_id", "gene", "disease_id", "construction_unit", "disease_name", "feature_label", "hpo_id",
    "prevalence", "prevalence_low", "prevalence_high", "n_affected", "n_assessed", "sex_restriction",
    "population", "age_onset_low_years", "age_onset_high_years", "age_presentation_low_years",
    "age_presentation_high_years", "age_note", "flags", "source_kind", "citation", "section",
    "evidence_quote", "access_path", "licence",
)  # fmt: skip
ONSET_COLUMNS = ("age_onset_low_years", "age_onset_high_years")
PRESENTATION_COLUMNS = ("age_presentation_low_years", "age_presentation_high_years")
PREVALENCE_COLUMNS = ("prevalence", "prevalence_low", "prevalence_high")
COUNT_COLUMNS = ("n_affected", "n_assessed")


# --- Shards ---------------------------------------------------------------------


@dataclass(frozen=True)
class Entity:
    """A simulable disease entity of a construction gene (genes-v2), as a unit's disease."""

    gene: str
    disease_id: str
    ids: frozenset[str]
    main: bool


def construction_entities(
    built: dict, eval_genes: set[str], eval_diseases: set[str]
) -> dict[str, list[Entity]]:
    """v3.0 gene -> its simulable entities that touch no evaluation unit, main entity first.

    A gene is left out when it or any of its symbols is an evaluation gene, or when
    its main entity shares an id with an evaluation disease. Any other entity that
    shares an id with an evaluation disease is dropped.
    """
    out: dict[str, list[Entity]] = {}
    for v3, current in sorted(built["vocabulary"].items()):
        record = built["genes"].get(current) if current else None
        if record is None:
            continue
        symbols = {v3.upper(), current.upper()} | {p.upper() for p in record.get("previous_symbols", [])}
        if symbols & eval_genes:
            continue
        entities = [e for e in record.get("entities", []) if e["simulable"]]
        if not entities:
            continue
        entities.sort(key=lambda e: (-e["sim_weight"], e["entity"]))
        ids = [frozenset({e["entity"], *e["ids"], *e["profile_ids"]}) for e in entities]
        if ids[0] & eval_diseases:
            continue
        out[v3] = [
            Entity(v3, e["entity"], i, n == 0)
            for n, (e, i) in enumerate(zip(entities, ids, strict=True))
            if not i & eval_diseases
        ]
    return out


def chapter_units(genes: list[str], omim_ids: set[str], entities: dict[str, list[Entity]]) -> list[Entity]:
    """Units a chapter may feed: per gene, the entities among the chapter's OMIM ids, else the main one."""
    out = []
    for g in genes:
        mine = entities.get(g, [])
        named = [e for e in mine if e.ids & omim_ids]
        out.extend(named or mine[:1])
    return out


def paper_units(genes: list[str], entities: dict[str, list[Entity]]) -> list[Entity]:
    """Units a paper may feed: every simulable entity of its genes that touches no evaluation unit."""
    return [e for g in genes for e in entities.get(g, [])]


def units_field(units: list[Entity]) -> str:
    return ";".join(f"{u.gene}|{u.disease_id}" for u in units)


def parse_units(value: str) -> set[tuple[str, str]]:
    return {tuple(x.split("|", 1)) for x in value.split(";") if x}


def assign_shards(chapters: list[dict], papers: list[dict], entities: dict[str, list[Entity]]) -> list[dict]:
    """One row per (shard, source).

    Chapters: usable ones in priority order (P1..P4, then the frozen priority rank),
    CHAPTERS_PER_SHARD per shard, ids C001.... Papers: selected ones in the frozen
    list order, PAPERS_PER_SHARD per shard, ids P001....
    """
    usable = sorted(
        (c for c in chapters if c["status"] == "usable"),
        key=lambda c: (PRIORITY_ORDER.index(c["priority_class"]), int(c["priority_rank"])),
    )
    selected = [p for p in papers if p["status"] == "selected"]
    rows = []
    for i, c in enumerate(usable):
        genes = [g for g in c["construction_genes"].split(";") if g]
        units = chapter_units(genes, set(c["omim_ids"].split(";")), entities)
        rows.append(
            {
                "shard": f"C{i // CHAPTERS_PER_SHARD + 1:03d}",
                "kind": "chapters",
                "position": i % CHAPTERS_PER_SHARD + 1,
                "source_id": c["nbk"],
                "alt_id": c["shortname"],
                "source_kind": SOURCE_KINDS["chapters"],
                "licence": GENEREVIEWS_LICENCE,
                "priority": c["priority_class"],
                "title": c["title"],
                "construction_genes": ";".join(genes),
                "units": units_field(units),
            }
        )
    for i, p in enumerate(selected):
        genes = [g for g in p["genes"].split(";") if g]
        rows.append(
            {
                "shard": f"P{i // PAPERS_PER_SHARD + 1:03d}",
                "kind": "papers",
                "position": i % PAPERS_PER_SHARD + 1,
                "source_id": f"PMID:{p['pmid']}",
                "alt_id": p["pmcid"],
                "source_kind": SOURCE_KINDS["papers"],
                "licence": p["licence"],
                "priority": "weak" if p["weak_genes"] else "",
                "title": p["title"],
                "construction_genes": ";".join(genes),
                "units": units_field(paper_units(genes, entities)),
            }
        )
    return rows


def shards_summary(rows: list[dict]) -> dict:
    by_shard = Counter(r["shard"] for r in rows)
    kinds = {k: sorted({r["shard"] for r in rows if r["kind"] == k}) for k in SOURCE_KINDS}
    return {
        "shards": {k: len(v) for k, v in kinds.items()},
        "first_last": {k: [v[0], v[-1]] if v else [] for k, v in kinds.items()},
        "sources": {k: sum(r["kind"] == k for r in rows) for k in SOURCE_KINDS},
        "sources_without_units": sorted(r["source_id"] for r in rows if not r["units"]),
        "units": {
            k: len({u for r in rows if r["kind"] == k for u in parse_units(r["units"])}) for k in SOURCE_KINDS
        },
        "genes": {
            k: len({g for r in rows if r["kind"] == k for g in r["construction_genes"].split(";") if g})
            for k in SOURCE_KINDS
        },
        "sources_per_shard": dict(sorted(Counter(by_shard.values()).items())),
    }


# --- Source text ----------------------------------------------------------------

_BLOCKS = {
    "sec", "p", "list", "list-item", "table-wrap", "fig", "boxed-text", "disp-quote", "def-list",
    "def-item", "statement", "caption", "table-wrap-foot", "fn", "fn-group", "glossary", "abstract",
    "notes", "title", "label", "ref-list", "table", "alternatives", "graphic", "media",
    "supplementary-material", "disp-formula", "array", "speech", "verse-group", "trans-abstract",
}  # fmt: skip
_SKIP = {
    "ref-list", "ref", "contrib-group", "aff", "pub-history", "kwd-group", "book-part-id", "object-id",
    "permissions", "graphic", "media", "alternatives", "author-notes", "funding-group", "counts",
    "history", "article-categories", "custom-meta-group", "related-article", "related-object",
}  # fmt: skip
_SKIP_SECTIONS = re.compile(r"^(references|literature cited|chapter notes|revision history)\b", re.I)


def normalise(text: str) -> str:
    """NFC, non-breaking and other Unicode spaces to plain spaces, whitespace runs collapsed."""
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def _raw(e, flatten: bool) -> str:
    parts = [e.text or ""]
    for c in e:
        if c.tag in _SKIP:
            pass
        elif c.tag == "break":
            parts.append(" ")
        elif c.tag == "sup":
            parts.append("^" + _raw(c, True).strip())
        elif c.tag in _BLOCKS:
            if flatten:
                parts.append(" " + _raw(c, True) + " ")
        else:
            parts.append(_raw(c, True))
        parts.append(c.tail or "")
    return "".join(parts)


def _inline(e, flatten: bool = False) -> str:
    """The element's text; nested blocks are skipped (rendered separately) unless `flatten`."""
    return normalise(_raw(e, flatten))


def _label(e) -> str:
    lab = e.find("label")
    return normalise(_inline(lab, True)).rstrip(".:").strip() if lab is not None else ""


class _Renderer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.tables = 0

    def heading(self, level: int, text: str) -> None:
        self.lines += ["", "#" * min(level, 6) + " " + text, ""]

    def para(self, text: str, prefix: str = "") -> None:
        if text:
            self.lines.append(prefix + text)

    def table(self, tw) -> None:
        self.tables += 1
        label = _label(tw) or f"Table (unlabelled {self.tables})"
        cap = tw.find("caption")
        caption = _inline(cap, True) if cap is not None else ""
        self.lines += ["", f"[{label}] {caption}".rstrip()]
        for tr in tw.iter("tr"):
            cells = [_inline(c, True) for c in tr if c.tag in ("td", "th")]
            if any(cells):
                self.lines.append(" | ".join(cells))
        for foot in tw.findall("table-wrap-foot"):
            for fn in foot.findall(".//fn") or [foot]:
                text = " ".join(x for x in (_label(fn), *(_inline(p, True) for p in fn.iter("p"))) if x)
                if text:
                    self.lines.append(f"[{label} note] {text}")
        self.lines += [f"[/{label}]", ""]

    def block(self, e, level: int) -> None:
        tag = e.tag
        if tag in _SKIP:
            return
        if tag == "sec":
            title = e.find("title")
            text = _inline(title, True) if title is not None else ""
            lab = _label(e)
            heading = f"{lab} {text}".strip() if lab and not text.startswith(lab) else text
            if _SKIP_SECTIONS.match(heading):
                return
            if heading:
                self.heading(level, heading)
            for c in e:
                if c.tag not in ("title", "label"):
                    self.block(c, level + 1)
        elif tag == "table-wrap":
            self.table(e)
        elif tag == "fig":
            cap = e.find("caption")
            text = _inline(cap, True) if cap is not None else ""
            self.lines += ["", f"[{_label(e) or 'Figure'}] {text}".rstrip(), ""]
        elif tag == "p":
            self.para(_inline(e))
            for c in e:
                if c.tag in _BLOCKS:
                    self.block(c, level)
        elif tag == "list":
            for item in e.findall("list-item"):
                first = True
                for c in item:
                    if c.tag == "p" and first:
                        self.para(_inline(c), "- ")
                        for cc in c:
                            if cc.tag in _BLOCKS:
                                self.block(cc, level)
                        first = False
                    elif c.tag != "label":
                        self.block(c, level)
                if first and item.text and item.text.strip():
                    self.para(_inline(item), "- ")
        elif tag in ("abstract", "trans-abstract"):
            title = e.find("title")
            self.heading(level, _inline(title, True) if title is not None else "Abstract")
            for c in e:
                if c.tag != "title":
                    self.block(c, level + 1)
        elif tag in ("title", "label", "caption"):
            return
        else:
            own = normalise(e.text or "")
            if own and not len(e):
                self.para(own)
            for c in e:
                self.block(c, level)


def render_jats(xml: bytes) -> str:
    """GeneReviews NXML (BITS book part) or a JATS article -> the plain text agents read.

    Layout: `# title`, Markdown headings for sections (`## Abstract` first),
    one paragraph per line, list items as `- ...`, and each table as
    `[Table N] caption`, one `cell | cell | ...` line per row, `[Table N note] ...`
    footnotes and a closing `[/Table N]`. Superscripts are written `^x`.
    References, author lists and back matter are left out.
    """
    root = ET.parse(io.BytesIO(xml)).getroot()
    r = _Renderer()
    meta = root.find(".//book-part-meta")
    if meta is None:
        meta = root.find(".//article-meta")
    title = meta.find(".//title-group/*") if meta is not None else None
    if title is not None:
        r.lines.append("# " + _inline(title, True))
    if meta is not None:
        for ab in meta.findall("abstract"):
            if ab.get("abstract-type") in ("graphical", "teaser"):
                continue
            r.block(ab, 2)
    body = root.find(".//body")
    if body is not None:
        for c in body:
            r.block(c, 2)
    floats = root.find(".//floats-group")
    if floats is not None:
        r.heading(2, "Tables and figures")
        for c in floats:
            r.block(c, 3)
    text = "\n".join(r.lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def render_abstract(title: str, abstract: str) -> str:
    return f"# {normalise(title)}\n\n## Abstract\n\n{normalise(abstract)}\n"


_HEADING = re.compile(r"^(#{1,6}) (.+)$")
_TABLE_OPEN = re.compile(r"^\[(Table [^\]]+?)(?<! note)\]( |$)")


def _key(section: str) -> str:
    s = normalise(section).lower().rstrip(".:").strip()
    return re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", s)


def sections(text: str) -> dict[str, list[tuple[int, int]]]:
    """Section key -> line spans [start, end) of every heading or table block with that name."""
    lines = text.splitlines()
    out: dict[str, list[tuple[int, int]]] = {}
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            end = next(
                (
                    j
                    for j in range(i + 1, len(lines))
                    if (h := _HEADING.match(lines[j])) and len(h.group(1)) <= level
                ),
                len(lines),
            )
            out.setdefault(_key(m.group(2)), []).append((i, end))
            continue
        t = _TABLE_OPEN.match(line)
        if t:
            close = f"[/{t.group(1)}]"
            end = next((j + 1 for j in range(i + 1, len(lines)) if lines[j] == close), len(lines))
            out.setdefault(_key(t.group(1)), []).append((i, end))
    return out


def passage(text: str, section: str) -> str | None:
    """The text of the named section or table (all blocks with that name), or None."""
    spans = sections(text).get(_key(section))
    if not spans:
        return None
    lines = text.splitlines()
    return "\n".join("\n".join(lines[a:b]) for a, b in spans)


def quote_found(quote: str, text: str) -> bool:
    """Every ` ... `-separated segment of the quote occurs verbatim in the text, in order."""
    hay = normalise(text)
    pos = 0
    for seg in quote.split(QUOTE_GAP.strip()):
        seg = normalise(seg)
        if not seg:
            continue
        i = hay.find(seg, pos)
        if i < 0:
            return False
        pos = i + len(seg)
    return True


def quote_words(quote: str) -> int:
    return len([w for w in normalise(quote.replace(QUOTE_GAP.strip(), " ")).split(" ") if w])


# --- Row checks -----------------------------------------------------------------


def _num(value: str) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def _int(value: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    if not re.fullmatch(r"\d+", value):
        raise ValueError(value)
    return int(value)


@dataclass
class ShardSource:
    source_id: str
    kind: str
    source_kind: str
    licence: str
    units: set[tuple[str, str]]
    title: str = ""


@dataclass
class SourceText:
    text: str
    access_path: str
    sha256: str = ""


@dataclass
class Boundary:
    """What a row may never touch, and the ontology it is checked against."""

    ontology: object
    eval_genes: set[str]
    eval_diseases: set[str]
    heldout_pmids: set[str]
    chapter_heldout: dict[str, list[str]] = field(default_factory=dict)


def check_rows(
    rows: list[dict], sources: dict[str, ShardSource], texts: dict[str, SourceText], b: Boundary
) -> list[str]:
    """Every problem of a shard's rows, as `row N (...): message`; empty when the shard passes."""
    from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY

    problems: list[str] = []
    seen: Counter = Counter()
    for i, row in enumerate(rows, start=2):
        where = f"row {i} ({row.get('source_id')} {row.get('gene')} / {row.get('feature_label')})"

        def bad(msg: str, where: str = where) -> None:
            problems.append(f"{where}: {msg}")

        missing = [c for c in ROW_COLUMNS if c not in row or row[c] is None]
        if missing:
            bad(f"missing columns {missing}")
            continue
        src = sources.get(row["source_id"])
        if src is None:
            bad("source_id is not a source of this shard")
            continue
        gene, disease = row["gene"].strip(), row["disease_id"].strip()
        if row["construction_unit"] != f"{gene}|{disease}":
            bad(f"construction_unit must be '{gene}|{disease}'")
        if gene.upper() in b.eval_genes:
            bad(f"{gene} is an evaluation gene (litpanel-split-v3)")
        if disease in b.eval_diseases:
            bad(f"{disease} is an evaluation disease (litpanel-split-v3)")
        if (gene, disease) not in src.units:
            bad(f"{gene}|{disease} is not a unit this source may feed (shards.tsv)")
        if row["source_kind"] != src.source_kind:
            bad(f"source_kind must be {src.source_kind}")
        if row["licence"] != src.licence:
            bad(f"licence must be '{src.licence}'")
        pmid = row["source_id"].removeprefix("PMID:")
        if row["source_id"].startswith("PMID:") and pmid in b.heldout_pmids:
            bad("source PMID is an R1 held-out PMID")
        if b.chapter_heldout.get(row["source_id"]):
            bad(f"chapter cites R1 held-out PMIDs {b.chapter_heldout[row['source_id']]}")
        if row["source_id"] not in row["citation"]:
            bad("citation must contain the source_id")
        flags = [f for f in row["flags"].split(";") if f]
        if set(flags) - set(FLAGS):
            bad(f"unknown flags {sorted(set(flags) - set(FLAGS))}; allowed {FLAGS}")
        if row["sex_restriction"] not in SEXES:
            bad(f"sex_restriction must be one of {SEXES}")
        if not row["population"].strip():
            bad("population is required")
        if not row["section"].strip():
            bad("section is required")

        try:
            n_aff, n_ass = (_int(row[c]) for c in COUNT_COLUMNS)
        except ValueError as e:
            bad(f"counts must be whole numbers ({e})")
            n_aff = n_ass = None
        try:
            p, lo, hi = (_num(row[c]) for c in PREVALENCE_COLUMNS)
            ages = {c: _num(row[c]) for c in ONSET_COLUMNS + PRESENTATION_COLUMNS}
        except ValueError as e:
            bad(f"not a number ({e})")
            continue
        if n_aff is not None and n_ass is None:
            bad("n_affected needs n_assessed")
        if n_ass is not None:
            if n_ass < 1:
                bad("n_assessed must be >= 1")
            elif n_aff is not None and n_aff > n_ass:
                bad(f"n_affected {n_aff} > n_assessed {n_ass}")
            if ("small_n" in flags) != (n_ass < SMALL_N):
                bad(f"flag small_n exactly when n_assessed < {SMALL_N}")
        elif "small_n" in flags:
            bad("small_n needs n_assessed")

        for lo_c, hi_c in (ONSET_COLUMNS, PRESENTATION_COLUMNS):
            a, z = ages[lo_c], ages[hi_c]
            for c, v in ((lo_c, a), (hi_c, z)):
                if v is not None and not 0 <= v <= MAX_AGE_YEARS:
                    bad(f"{c} must be in [0, {MAX_AGE_YEARS:g}] years")
            if a is not None and z is not None and a > z:
                bad(f"{lo_c} > {hi_c}")

        feature = row["feature_label"].strip()
        if feature in AGE_FEATURES:
            mine = ONSET_COLUMNS if feature == "AGE_ONSET" else PRESENTATION_COLUMNS
            other = PRESENTATION_COLUMNS if feature == "AGE_ONSET" else ONSET_COLUMNS
            if row["hpo_id"].strip():
                bad("an age row has no hpo_id")
            if any(v is not None for v in (p, lo, hi)):
                bad("an age row has no prevalence")
            if n_aff is not None:
                bad("an age row has no n_affected")
            if all(ages[c] is None for c in mine):
                bad(f"{feature} needs {mine[0]} and/or {mine[1]}")
            if any(ages[c] is not None for c in other):
                bad(f"{feature} must leave {other} empty")
            key = (
                row["source_id"],
                gene,
                disease,
                feature,
                row["population"].strip(),
                row["sex_restriction"],
            )
        else:
            hpo = row["hpo_id"].strip()
            term = b.ontology.resolve(hpo) if hpo else None
            if term is None or term != hpo:
                bad(f"{hpo or '(empty)'} is not a current HPO id (resolves to {term})")
            elif not b.ontology.is_a(hpo, PHENOTYPIC_ABNORMALITY):
                bad(f"{hpo} is not under Phenotypic abnormality")
            if p is None:
                bad("prevalence is required for a feature row")
            elif not 0 <= p <= 1:
                bad("prevalence must be in [0, 1]")
            else:
                if (lo is not None and lo > p) or (hi is not None and p > hi):
                    bad(f"prevalence {p} outside its range [{lo}, {hi}]")
                if n_aff is not None and n_ass:
                    if abs(p - n_aff / n_ass) > PREVALENCE_TOLERANCE:
                        bad(f"prevalence {p} is not {n_aff}/{n_ass} = {n_aff / n_ass:.4f}")
            for c, v in (("prevalence_low", lo), ("prevalence_high", hi)):
                if v is not None and not 0 <= v <= 1:
                    bad(f"{c} must be in [0, 1]")
            key = (row["source_id"], gene, disease, hpo, row["population"].strip(), row["sex_restriction"])
        seen[key] += 1
        if seen[key] == 2:
            bad("duplicate (source, unit, feature, population, sex)")

        quote = row["evidence_quote"]
        if not quote.strip():
            bad("evidence_quote is required")
        elif quote_words(quote) > MAX_QUOTE_WORDS:
            bad(f"evidence_quote has {quote_words(quote)} words (max {MAX_QUOTE_WORDS})")
        text = texts.get(row["source_id"])
        if text is None:
            bad("no local source text")
            continue
        if row["access_path"] != text.access_path:
            bad(f"access_path must be {text.access_path} (the cached text)")
        if quote.strip():
            block = passage(text.text, row["section"])
            if block is None:
                bad(f"section '{row['section']}' is not a heading or table of the source text")
            elif not quote_found(quote, block):
                where_else = quote_found(quote, text.text)
                bad(
                    "evidence_quote is not verbatim in that section"
                    + (" (it is elsewhere in the source: fix `section`)" if where_else else "")
                )
    return problems


def row_stats(rows: list[dict]) -> dict:
    ages = [r for r in rows if r["feature_label"] in AGE_FEATURES]
    return {
        "rows": len(rows),
        "feature_rows": len(rows) - len(ages),
        "age_rows": len(ages),
        "rows_per_source": dict(sorted(Counter(r["source_id"] for r in rows).items())),
        "units": len({r["construction_unit"] for r in rows}),
        "rows_with_counts": sum(bool(r["n_assessed"].strip()) for r in rows),
        "rows_with_range": sum(
            bool(r["prevalence_low"].strip() or r["prevalence_high"].strip()) for r in rows
        ),
        "flags": dict(sorted(Counter(f for r in rows for f in r["flags"].split(";") if f).items())),
        "sex_restricted": sum(bool(r["sex_restriction"]) for r in rows),
    }


# --- Cross-check ----------------------------------------------------------------

CROSSCHECK_SEED = 20261001
FEATURE_PROMPT = """You are checking one fact in a medical source.
The source passage is given in the <stdin> block; answer from it only. Do not use outside knowledge.

Gene: {gene}
Disease: {disease_name} ({disease_id})
Population: {population}{sex}
Clinical feature: {feature_label} ({hpo_id} {hpo_label})
Citation: {citation}; {section}

Question: according to this passage, what proportion of the affected individuals in that population
have this feature? Use only a number the passage states (a percentage, a count such as 14/29, a range,
or a bound). Do not estimate, and do not compute a complement. For a range, report its bounds and their
midpoint; for a bound such as ">99%" or "<5%", report the bound as the prevalence and 1 or 0 as the
open end. Report n_affected/n_assessed only if the passage states them. If the passage gives no number,
set found to false. Leave the age fields null."""
AGE_PROMPT = """You are checking one fact in a medical source.
The source passage is given in the <stdin> block; answer from it only. Do not use outside knowledge.

Gene: {gene}
Disease: {disease_name} ({disease_id})
Population: {population}{sex}
Fact: {what}
Citation: {citation}; {section}

Question: according to this passage, what is the {what_lower} in that population, in years?
Use only ages the passage states. For a range report its bounds; for a single stated age (a mean or
median) report it as both bounds; for "before age X" report null and X. Convert months to years
(divide by 12). If the passage states no age, set found to false. Leave the prevalence fields null."""
AGE_WHAT = {"AGE_ONSET": "Age at onset", "AGE_PRESENTATION": "Age at diagnosis or presentation"}
ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "found",
        "prevalence",
        "prevalence_low",
        "prevalence_high",
        "n_affected",
        "n_assessed",
        "age_low_years",
        "age_high_years",
        "quote",
    ],  # fmt: skip
    "properties": {
        "found": {"type": "boolean"},
        **{
            k: {"type": ["number", "null"]}
            for k in ("prevalence", "prevalence_low", "prevalence_high", "age_low_years", "age_high_years")
        },
        "n_affected": {"type": ["integer", "null"]},
        "n_assessed": {"type": ["integer", "null"]},
        "quote": {"type": "string", "description": "the sentence or table row used, at most 25 words"},
    },
}
CROSSCHECK_COLUMNS = (
    "item", "shard", "row", "source_id", "gene", "disease_id", "feature_label", "hpo_id", "population",
    "sex_restriction", "section", "ours_low", "ours_point", "ours_high", "other_found", "other_low",
    "other_point", "other_high", "other_n", "other_quote", "agree", "resolution",
)  # fmt: skip


def sample(rows_by_shard: dict[str, list[dict]], fraction: float, seed: int, all_under: int) -> list[tuple]:
    """(shard, row index) of a seeded `fraction` of each shard's rows, at least one per shard.

    Sampling per shard keeps each shard's draw fixed as other shards land. A shard
    with fewer than `all_under` rows is taken whole.
    """
    out = []
    for shard in sorted(rows_by_shard):
        n = len(rows_by_shard[shard])
        if not n:
            continue
        k = n if n < all_under else max(1, math.ceil(n * fraction))
        out += [(shard, i) for i in sorted(random.Random(f"{seed}:{shard}").sample(range(n), k))]
    return out


def crosscheck_prompt(row: dict, hpo_label: str = "") -> str:
    """The blind prompt: unit, feature, population and citation, never our numbers or quote."""
    fields = {k: row.get(k, "") for k in ("gene", "disease_name", "disease_id", "population", "citation")}
    fields["section"] = row.get("section", "")
    fields["sex"] = f" ({row['sex_restriction']}s only)" if row.get("sex_restriction") else ""
    if row["feature_label"] in AGE_FEATURES:
        what = AGE_WHAT[row["feature_label"]]
        return AGE_PROMPT.format(**fields, what=what, what_lower=what.lower())
    return FEATURE_PROMPT.format(
        **fields, feature_label=row["feature_label"], hpo_id=row["hpo_id"], hpo_label=hpo_label
    )


def parse_answer(data: dict) -> dict:
    """Codex's schema-shaped answer -> found, point, low, high (strings; "" when absent), n, quote."""
    found = bool(data.get("found"))

    def s(x) -> str:
        return "" if x is None else repr(float(x))

    if data.get("age_low_years") is not None or data.get("age_high_years") is not None:
        lo, hi = data.get("age_low_years"), data.get("age_high_years")
        point = (lo + hi) / 2 if lo is not None and hi is not None else (lo if hi is None else hi)
        return {
            "found": found,
            "low": s(lo),
            "point": s(point),
            "high": s(hi),
            "n": "",
            "quote": data.get("quote") or "",
        }
    p, lo, hi = data.get("prevalence"), data.get("prevalence_low"), data.get("prevalence_high")
    n_aff, n_ass = data.get("n_affected"), data.get("n_assessed")
    if p is None and n_aff is not None and n_ass:
        p = n_aff / n_ass
    n = f"{n_aff}/{n_ass}" if n_aff is not None and n_ass else ""
    return {
        "found": found,
        "low": s(lo),
        "point": s(p),
        "high": s(hi),
        "n": n,
        "quote": data.get("quote") or "",
    }


def ours(row: dict) -> tuple[str, str, str]:
    """Our (low, point, high) for a row: prevalence, or the age range with its midpoint."""
    if row["feature_label"] in AGE_FEATURES:
        cols = ONSET_COLUMNS if row["feature_label"] == "AGE_ONSET" else PRESENTATION_COLUMNS
        lo, hi = _num(row[cols[0]]), _num(row[cols[1]])
        point = (lo + hi) / 2 if lo is not None and hi is not None else (lo if hi is None else hi)
        return row[cols[0]], "" if point is None else repr(point), row[cols[1]]
    return row["prevalence_low"], row["prevalence"], row["prevalence_high"]


def agrees(row: dict, other: dict, tolerance: float = 0.10) -> bool:
    """The panel's rule: ranges overlap, or points within `tolerance` (prevalence).

    For ages the point tolerance is max(1 year, 10% of the larger point), and an open
    bound ("before age 5") counts as a range from 0 or up to MAX_AGE_YEARS.
    """
    from diagnostic_ar_training.knowledge import literature_panel as lp

    if not other.get("found"):
        return False
    lo, point, hi = ours(row)
    if row["feature_label"] not in AGE_FEATURES:
        return lp.agrees(
            {"prevalence": point, "prevalence_low": lo, "prevalence_high": hi},
            {"prevalence": other["point"], "prevalence_low": other["low"], "prevalence_high": other["high"]},
            tolerance,
        )
    a = (_num(lo), _num(hi))
    b = (_num(other["low"]), _num(other["high"]))
    if a == (None, None) or b == (None, None):
        return False
    a = (a[0] if a[0] is not None else 0.0, a[1] if a[1] is not None else MAX_AGE_YEARS)
    b = (b[0] if b[0] is not None else 0.0, b[1] if b[1] is not None else MAX_AGE_YEARS)
    if a[0] <= b[1] and b[0] <= a[1]:
        return True
    pa, pb = _num(point), _num(other["point"])
    return pa is not None and pb is not None and abs(pa - pb) <= max(1.0, 0.1 * max(pa, pb)) + 1e-9


def schema_json() -> str:
    return json.dumps(ANSWER_SCHEMA, indent=1)


# --- Shard notes ----------------------------------------------------------------

NOTES_COLUMNS = ("source_id", "outcome", "rows", "note")
OUTCOMES = ("extracted", "no_numbers", "not_cohort", "not_about_units", "no_text")


def check_notes(notes: list[dict], source_ids: list[str], rows: list[dict]) -> list[str]:
    """Every source of the shard has exactly one note whose row count matches the rows file."""
    problems = []
    counts = Counter(r["source_id"] for r in rows)
    seen = Counter(n.get("source_id") for n in notes)
    for s in source_ids:
        if seen[s] != 1:
            problems.append(f"notes: {s} must appear exactly once (found {seen[s]})")
    for n in notes:
        s = n.get("source_id")
        if s not in source_ids:
            problems.append(f"notes: {s} is not a source of this shard")
            continue
        if n.get("outcome") not in OUTCOMES:
            problems.append(f"notes: {s} outcome must be one of {OUTCOMES}")
        if str(counts[s]) != (n.get("rows") or "").strip():
            problems.append(f"notes: {s} says {n.get('rows')} rows, the rows file has {counts[s]}")
        if (n.get("outcome") == "extracted") != (counts[s] > 0):
            problems.append(f"notes: {s} outcome 'extracted' exactly when it has rows")
        if n.get("outcome") != "extracted" and not (n.get("note") or "").strip():
            problems.append(f"notes: {s} needs a note saying why nothing was extracted")
    return problems


# --- HPO lookup -----------------------------------------------------------------


def hpo_index(graph: dict) -> dict[str, tuple[str, tuple[str, ...], str]]:
    """hp.json graph -> term -> (label, synonyms, definition)."""
    out = {}
    for node in graph["nodes"]:
        term = node["id"].rsplit("/", 1)[-1].replace("_", ":", 1)
        if not term.startswith("HP:") or not node.get("lbl"):
            continue
        meta = node.get("meta", {})
        syns = tuple(s["val"] for s in meta.get("synonyms", []))
        out[term] = (node["lbl"], syns, meta.get("definition", {}).get("val", ""))
    return out


def hpo_search(index: dict, ontology, query: str, limit: int = 25) -> list[tuple[str, str, str]]:
    """Current phenotypic-abnormality terms whose label or a synonym holds every query word.

    Returns (term, label, matched synonym or ""), exact matches first, then label
    matches, then shorter names.
    """
    from diagnostic_ar_training.ontology import PHENOTYPIC_ABNORMALITY

    words = [w for w in re.split(r"\W+", query.lower()) if w]
    hits = []
    for term, (label, syns, _) in index.items():
        if ontology.resolve(term) != term or not ontology.is_a(term, PHENOTYPIC_ABNORMALITY):
            continue
        for name, is_label in ((label, True), *((s, False) for s in syns)):
            low = name.lower()
            if all(re.search(rf"\b{re.escape(w)}", low) for w in words):
                exact = low == query.lower().strip()
                hits.append(((not exact, not is_label, len(low)), term, label, "" if is_label else name))
                break
    hits.sort()
    return [(t, lab, syn) for _, t, lab, syn in hits[:limit]]
