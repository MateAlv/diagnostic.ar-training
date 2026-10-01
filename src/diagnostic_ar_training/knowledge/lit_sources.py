"""lit-sources-v1: the frozen extraction lists of ADR-0013 (amendment 1).

Two lists, frozen and committed before any extraction:
- GeneReviews chapters usable for construction genes. A chapter is dropped if
  it touches an evaluation unit (an evaluation gene in its gene map, or an
  evaluation disease id among its OMIM ids) or cites any R1 held-out PMID.
- Tier-2 major studies: open-access papers with a reuse-compatible licence that
  pass a deterministic screen on publication type, title and abstract (at least
  20 patients stated, genetic confirmation, not an association study). They come
  first from the references of usable chapters, then from a recorded Europe PMC
  query for weak construction genes that have no usable chapter.

Everything here is a pure function of its inputs; network access lives in the
CLI (`dxt knowledge lit-sources fetch`), which caches raw responses.
"""

import csv
import html
import io
import re
import tarfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

INDEX_DIR = "GeneReviews"
NXML_DIR = "gene_NBK1116"
WEAK_TIERS = ("W1", "W2", "W3", "W4")
MIN_PATIENTS = 20
REUSE_LICENCES = ("cc by", "cc0", "cc by-nc", "cc by-nc-sa", "cc by-nc-nd")
EXCLUDED_PUB_TYPES = {
    "case reports": "case_report",
    "preprint": "preprint",
    "review": "review",
    "systematic review": "review",
    "meta-analysis": "review",
    "editorial": "not_primary",
    "comment": "not_primary",
    "published erratum": "not_primary",
    "retraction of publication": "not_primary",
    "retracted publication": "not_primary",
    "practice guideline": "not_primary",
    "guideline": "not_primary",
    "news": "not_primary",
}

# The SOURCES-SCOPING-001 screen (scripts/analysis/sources_scoping_gr_sample.py).
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+\s?/\s?\d+\b|\b\d+ of \d+\b")
AGE_NUMBER = re.compile(
    r"(?:age[sd]?|onset|diagnos\w*|present\w*|manifest\w*)[^.;]{0,80}?\b\d+(?:\.\d+)?(?:\s?(?:-|–|to|and)\s?\d+(?:\.\d+)?)?\s?(?:years?|yrs?|months?|weeks?|days?)\b"
    r"|\b(?:mean|median|average)\s+age\b",
    re.IGNORECASE,
)
SKIP_TABLES = re.compile(
    r"differential|evaluation|treatment|surveillance|testing|genes and databases|omim|variants|resources",
    re.I,
)
FEATURE_TABLES = re.compile(r"frequency|features|findings|manifestations|phenotyp", re.I)
CLINICAL_SECS = re.compile(r"^(clinical description|suggestive findings|clinical characteristics)$", re.I)

UNITS = {w: i for i, w in enumerate("one two three four five six seven eight nine".split(), 1)}
TEENS = {
    w: i for i, w in enumerate("ten eleven twelve thirteen fourteen fifteen sixteen seventeen".split(), 10)
}
TEENS |= {"eighteen": 18, "nineteen": 19}
TENS = {w: 10 * i for i, w in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2)}
NUMBER_WORDS = UNITS | TEENS | TENS
PATIENT_NOUNS = (
    r"patients|individuals|subjects|probands|cases|children|adults|families|participants|carriers"
    r"|persons|people|males|females|boys|girls|infants|neonates|newborns|pedigrees|kindreds"
    r"|women|men|fetuses|siblings"
)
_NOUN = re.compile(rf"\b(?:{PATIENT_NOUNS})\b", re.IGNORECASE)
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-.,][A-Za-z0-9]+)*|%")
MAX_COUNT = 100_000
_YEAR_PREVIOUS = {"in", "since", "from", "to", "until", "between", "during", "of", "and"}
COUNT_WINDOW = 5
_N_EQUALS = re.compile(r"\b[nN]\s?=\s?(\d{2,6})\b")
CONTROL_WORDS = {"healthy", "control", "controls", "unaffected", "normal", "population", "general"}
GENETIC = re.compile(
    r"variant|mutation|mutated|pathogenic|genotyp|sequenc|exome|genome|molecular(?:ly)?\s+(?:confirmed|diagnos)"
    r"|genetic(?:ally)?\s+(?:confirmed|diagnos|tested|testing|analys)|biallelic|bi-allelic|heterozygous|homozygous"
    r"|hemizygous|compound heterozyg|deletion|duplication|expansion|de novo",
    re.IGNORECASE,
)
LITERATURE_REVIEW = re.compile(
    r"review of (?:the )?literature|literature review|systematic review|meta-analys", re.IGNORECASE
)
ASSOCIATION = re.compile(
    r"genome-wide association|\bGWAS\b|polygenic|susceptibility locus|risk allele|case-control association"
    r"|single nucleotide polymorphism|\bSNPs?\b",
    re.IGNORECASE,
)


@dataclass
class Chapter:
    shortname: str
    nbk: str = ""
    title: str = ""
    genes: set[str] = field(default_factory=set)
    omim: set[str] = field(default_factory=set)


@dataclass
class ChapterScreen:
    pmids: set[str]
    feature_tables: int
    feature_table_numeric_rows: int
    clinical_numeric_sentences: int
    age_numeric_sentences: int


def _tsv_rows(text: str):
    return csv.reader((x for x in text.splitlines() if not x.startswith("#")), delimiter="\t")


def _hpoa_rows(handle):
    lines = (x for x in handle if not x.startswith("#"))
    return csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)


def parse_index(files: dict[str, str]) -> dict[str, Chapter]:
    """GeneReviews FTP index files (name -> text) -> chapter shortname -> Chapter."""
    chapters: dict[str, Chapter] = {}
    for line in files["GRshortname_NBKid_genesymbol_dzname.txt"].splitlines():
        parts = line.split("|")
        if len(parts) != 4 or parts[0].startswith("#"):
            continue
        short, nbk, gene, name = parts
        ch = chapters.setdefault(short, Chapter(short))
        ch.nbk = ch.nbk or nbk
        ch.title = ch.title or name
        if gene and gene != "Not applicable":
            ch.genes.add(gene.upper())
    for row in _tsv_rows(files["NBKid_shortname_OMIM.txt"]):
        if len(row) == 3 and row[1] in chapters:
            chapters[row[1]].omim.add(f"OMIM:{row[2]}")
    for row in _tsv_rows(files["GRtitle_shortname_NBKid.txt"]):
        if len(row) >= 2 and row[0] in chapters:
            chapters[row[0]].title = row[1]
    return chapters


def read_snapshot(path: Path) -> tuple[dict[str, Chapter], dict[str, bytes]]:
    """The `genereviews` source tarball -> (chapters from the index files, shortname -> NXML bytes)."""
    index, nxml = {}, {}
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            folder, _, name = member.name.partition("/")
            data = tar.extractfile(member).read()
            if folder == INDEX_DIR:
                index[name] = data.decode("latin-1")
            elif folder == NXML_DIR and name.endswith(".nxml"):
                nxml[name.removesuffix(".nxml")] = data
    return parse_index(index), nxml


def _text(e) -> str:
    return re.sub(r"\s+", " ", "".join(e.itertext())).strip()


def _sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z(])", s) if x.strip()]


def screen_chapter(xml: bytes) -> ChapterScreen:
    """Cited PMIDs and the SOURCES-SCOPING-001 numeric screen of one chapter."""
    root = ET.parse(io.BytesIO(xml)).getroot()
    tables = numeric_rows = 0
    for tw in root.iter("table-wrap"):
        cap = tw.find("caption")
        caption = _text(cap) if cap is not None else ""
        if not caption or SKIP_TABLES.search(caption) or not FEATURE_TABLES.search(caption):
            continue
        rows = [[_text(c) for c in tr if c.tag in ("td", "th")] for tr in tw.iter("tr")]
        tables += 1
        numeric_rows += sum(any(NUMBER.search(c) for c in r[1:]) for r in rows)
    in_tables = {id(x) for tw in root.iter("table-wrap") for x in tw.iter()}
    clinical, seen = [], set()
    for sec in root.iter("sec"):
        t = sec.find("title")
        if t is None or not CLINICAL_SECS.match(_text(t)):
            continue
        for e in sec.iter():
            if e.tag == "p" and id(e) not in in_tables and id(e) not in seen:
                seen.add(id(e))
                clinical.extend(_sentences(_text(e)))
    pmids = {x.text.strip() for x in root.iter("pub-id") if x.get("pub-id-type") == "pmid" and x.text}
    return ChapterScreen(
        pmids=pmids,
        feature_tables=tables,
        feature_table_numeric_rows=numeric_rows,
        clinical_numeric_sentences=sum(bool(NUMBER.search(s)) for s in clinical),
        age_numeric_sentences=sum(bool(AGE_NUMBER.search(s)) for s in clinical),
    )


@dataclass(frozen=True)
class GeneInfo:
    """One v3.0 vocabulary gene, as the construction/evaluation boundary sees it."""

    gene: str
    symbol: str
    symbols: frozenset[str]
    role: str
    simulable: bool
    main_ids: frozenset[str]
    shares_eval_disease: bool
    weakness: str

    @property
    def construction(self) -> bool:
        """Usable for construction: not an evaluation gene, main disease not an evaluation disease."""
        return self.role == "construction" and not self.shares_eval_disease

    @property
    def weak(self) -> bool:
        return self.weakness.startswith(WEAK_TIERS)


def _main_entity(record: dict | None) -> dict | None:
    entities = [e for e in (record or {}).get("entities", []) if e["simulable"]]
    return min(entities, key=lambda e: (-e["sim_weight"], e["entity"])) if entities else None


def profile_strength(path: Path) -> dict[str, dict[str, list]]:
    """hpoa-recount phenotype.hpoa -> disease id -> term -> [has frequency, has n/m, max m]."""
    from diagnostic_ar_training.rerank.kb import parse_frequency

    terms: dict[str, dict[str, list]] = defaultdict(dict)
    with path.open(encoding="utf-8") as h:
        for row in _hpoa_rows(h):
            if row["qualifier"] == "NOT" or row["aspect"] != "P":
                continue
            freq = parse_frequency(row["frequency"])
            slot = terms[row["database_id"]].setdefault(row["hpo_id"], [False, False, 0])
            slot[0] |= freq is not None
            if freq is not None and freq[0] == "count":
                slot[1] = True
                slot[2] = max(slot[2], freq[1][1])
    return terms


def weakness(per_term: dict[str, list], orpha_only: bool) -> str:
    """SOURCES-SCOPING-001 §3 tiers of a main disease's profile."""
    if not per_term:
        return "W0_no_profile"
    has_count = any(c for _, c, _ in per_term.values())
    max_m = max(m for _, _, m in per_term.values())
    if has_count:
        return "ok_counts" if max_m >= 5 else "W4_counts_from_small_series_only"
    if orpha_only:
        return "W2_orphanet_bins_only"
    nofreq = sum(not f for f, _, _ in per_term.values()) / len(per_term)
    return "W1_mostly_no_frequency" if nofreq >= 0.5 else "W3_no_counts_other"


def gene_infos(
    built: dict, profiles: dict[str, dict[str, list]], eval_genes: set[str], eval_diseases: set[str]
) -> list[GeneInfo]:
    """genes-v2 + recounted profiles + the evaluation boundary -> one GeneInfo per vocabulary gene."""
    out = []
    for v3, current in sorted(built["vocabulary"].items()):
        record = built["genes"].get(current) if current else None
        keys = {v3.upper(), (current or "").upper()} - {""}
        role = "evaluation" if keys & eval_genes else "construction"
        symbols = keys | {p.upper() for p in (record or {}).get("previous_symbols", [])}
        main = _main_entity(record)
        main_ids = frozenset(set(main["ids"]) | set(main["profile_ids"])) if main else frozenset()
        per_term: dict[str, list] = {}
        kinds = set()
        for i in main["profile_ids"] if main else []:
            if profiles.get(i):
                kinds.add(i.split(":")[0])
            for t, (f, c, m) in profiles.get(i, {}).items():
                slot = per_term.setdefault(t, [False, False, 0])
                slot[0] |= f
                slot[1] |= c
                slot[2] = max(slot[2], m)
        out.append(
            GeneInfo(
                gene=v3,
                symbol=current or "",
                symbols=frozenset(symbols),
                role=role,
                simulable=main is not None,
                main_ids=main_ids,
                shares_eval_disease=role == "construction" and bool(main_ids & eval_diseases),
                weakness=weakness(per_term, kinds == {"ORPHA"}) if main else "W0_no_profile",
            )
        )
    return out


def chapter_rows(
    chapters: dict[str, Chapter],
    screens: dict[str, ChapterScreen],
    genes: list[GeneInfo],
    eval_genes: set[str],
    eval_diseases: set[str],
    heldout: set[str],
) -> list[dict]:
    """One row per chapter of the gene map, with its status; usable rows come first, in priority order."""
    by_symbol: dict[str, list[GeneInfo]] = defaultdict(list)
    for g in genes:
        for s in g.symbols:
            by_symbol[s].append(g)
    rows = []
    for short, ch in chapters.items():
        matched = {g.gene: g for s in ch.genes for g in by_symbol.get(s, [])}
        construction = sorted(g for g, info in matched.items() if info.construction)
        blocked = sorted(
            g for g, info in matched.items() if info.role == "construction" and info.shares_eval_disease
        )
        weak = [g for g in construction if matched[g].weak]
        screen = screens.get(short)
        eval_hit = sorted((ch.genes & eval_genes) | (ch.omim & eval_diseases))
        cited_heldout = sorted(screen.pmids & heldout) if screen else []
        if eval_hit:
            status = "dropped_eval_unit"
        elif screen is None:
            status = "dropped_not_in_archive"
        elif cited_heldout:
            status = "dropped_heldout_pmid"
        elif not construction:
            status = "dropped_no_construction_gene"
        else:
            status = "usable"
        has_table = bool(screen and screen.feature_table_numeric_rows > 0)
        rows.append(
            {
                "shortname": short,
                "nbk": ch.nbk,
                "title": ch.title,
                "status": status,
                "n_index_genes": len(ch.genes),
                "construction_genes": ";".join(construction),
                "n_construction_genes": len(construction),
                "weak_construction_genes": ";".join(weak),
                "n_weak_construction_genes": len(weak),
                "best_weak_tier": min((matched[g].weakness[:2] for g in weak), default=""),
                "simulable_construction_genes": sum(matched[g].simulable for g in construction),
                "genes_blocked_eval_disease": ";".join(blocked),
                "eval_units_touched": ";".join(eval_hit),
                "omim_ids": ";".join(sorted(ch.omim)),
                "has_numeric_frequency_table": has_table,
                "feature_tables": screen.feature_tables if screen else 0,
                "feature_table_numeric_rows": screen.feature_table_numeric_rows if screen else 0,
                "clinical_numeric_sentences": screen.clinical_numeric_sentences if screen else 0,
                "age_numeric_sentences": screen.age_numeric_sentences if screen else 0,
                "cited_pmids": len(screen.pmids) if screen else 0,
                "cited_heldout_pmids": ";".join(cited_heldout),
            }
        )
    for r in rows:
        weak, table = r["n_weak_construction_genes"] > 0, r["has_numeric_frequency_table"]
        r["priority_class"] = (
            (("P1" if table else "P2") if weak else ("P3" if table else "P4"))
            if r["status"] == "usable"
            else ""
        )
    rows.sort(
        key=lambda r: (
            r["status"] != "usable",
            r["priority_class"],
            -r["n_weak_construction_genes"],
            -r["feature_table_numeric_rows"],
            r["status"],
            int(r["nbk"].removeprefix("NBK") or 0),
            r["shortname"],
        )
    )
    rank = 0
    for r in rows:
        if r["status"] == "usable":
            rank += 1
            r["priority_rank"] = rank
        else:
            r["priority_rank"] = ""
    return rows


def normalise_licence(raw: str | None) -> str:
    return re.sub(r"\s+", " ", (raw or "").strip().lower().replace("_", " ")).replace("cc-by", "cc by")


def _number(token: str) -> int | None:
    t = token.lower()
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", t):
        return int(t.replace(",", ""))
    parts = t.split("-")
    if len(parts) == 1 and t in NUMBER_WORDS:
        return NUMBER_WORDS[t]
    if len(parts) == 2 and parts[0] in TENS and parts[1] in UNITS:
        return TENS[parts[0]] + UNITS[parts[1]]
    return None


def plain(raw: str | None) -> str:
    """Europe PMC title or abstract -> plain text (HTML entities decoded, tags removed)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(raw or "")))).strip()


def stated_n(text: str) -> int | None:
    """The largest patient count stated in a title or abstract; None if none is stated.

    For each patient noun, the nearest number among the COUNT_WINDOW tokens before
    it is the count ("12 of 40 patients" gives 40). It is ignored when a control
    word or "%" lies between the two, or when it looks like a year ("in 2019").
    "n = 33" also counts.
    """
    best = None
    for m in _NOUN.finditer(text):
        before = _TOKEN.findall(text[max(0, m.start() - 100) : m.start()])[-COUNT_WINDOW:]
        for i in range(len(before) - 1, -1, -1):
            token = before[i]
            if re.fullmatch(r"\d+\.\d+", token):
                break
            value = _number(token)
            if value is None:
                continue
            if value > MAX_COUNT:
                break
            prev = before[i - 1].lower() if i else ""
            if token.lower() in UNITS and prev in TENS:
                value += TENS[prev]
            between = [w.lower() for w in before[i + 1 :]]
            if "%" in between or CONTROL_WORDS & set(between):
                break
            if 1900 <= value <= 2100 and prev in _YEAR_PREVIOUS:
                break
            if between[:1] == ["hundred"]:
                value *= 100
            best = max(best or 0, value)
            break
    for m in _N_EQUALS.finditer(text):
        best = max(best or 0, int(m.group(1)))
    return best


def word_in(symbol: str, text: str) -> bool:
    """Case-sensitive whole-symbol match (hyphenated forms like `SYM-related` count)."""
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(symbol)}(?![A-Za-z0-9])", text) is not None


def screen_paper(
    record: dict,
    heldout: set[str],
    panel_pmids: set[str],
    eval_symbols: set[str],
) -> tuple[str, str, int | None]:
    """Europe PMC core record -> (status, reason, n). Status is `selected` or `excluded`.

    The rule, in order: held-out PMID; literature-panel source; licence outside
    REUSE_LICENCES; preprint; excluded publication type (case report, review,
    meta-analysis, editorial ...); "case report" in the title; an evaluation gene
    symbol in the title or abstract; literature-review wording; association-study
    wording; no genetic-confirmation wording; no patient count stated; fewer than
    MIN_PATIENTS stated.
    """
    pmid = str(record.get("pmid") or "")
    title = plain(record.get("title"))
    text = f"{title} {plain(record.get('abstractText'))}"
    n = stated_n(text)
    licence = normalise_licence(record.get("license"))
    pub_types = [p.lower() for p in (record.get("pubTypeList") or {}).get("pubType", [])]
    if pmid in heldout:
        return "excluded", "heldout_pmid", n
    if pmid in panel_pmids:
        return "excluded", "litpanel_source", n
    if licence not in REUSE_LICENCES:
        return "excluded", f"licence:{licence or 'none'}", n
    if record.get("source") == "PPR":
        return "excluded", "preprint", n
    for p in pub_types:
        if p in EXCLUDED_PUB_TYPES:
            return "excluded", f"pub_type:{EXCLUDED_PUB_TYPES[p]}", n
    if re.search(r"case report", title, re.I):
        return "excluded", "title:case_report", n
    hits = sorted(s for s in eval_symbols if word_in(s, text))
    if hits:
        return "excluded", "mentions_eval_gene:" + ",".join(hits), n
    if LITERATURE_REVIEW.search(text):
        return "excluded", "literature_review", n
    if ASSOCIATION.search(text):
        return "excluded", "association_study", n
    if not GENETIC.search(text):
        return "excluded", "no_genetic_confirmation", n
    if n is None:
        return "excluded", "n_not_stated", n
    if n < MIN_PATIENTS:
        return "excluded", f"n_lt_{MIN_PATIENTS}", n
    return "selected", f"n>={MIN_PATIENTS}", n


def epmc_gene_query(symbol: str) -> str:
    """The recorded Europe PMC query for cohort or natural-history studies of one gene."""
    design = (
        'cohort OR "natural history" OR registry OR "case series" OR "clinical spectrum" OR '
        '"phenotypic spectrum" OR "genotype-phenotype" OR "clinical features" OR "clinical characteristics"'
    )
    return f'TITLE:"{symbol}" AND (TITLE:({design}) OR ABSTRACT:({design})) AND OPEN_ACCESS:y AND SRC:MED'


def epmc_pmid_query(pmids: list[str]) -> str:
    return "(" + " OR ".join(f"EXT_ID:{p}" for p in pmids) + ") AND SRC:MED AND OPEN_ACCESS:y"


def hpoa_pmids_by_disease(path: Path) -> dict[str, set[str]]:
    """phenotype.hpoa -> disease id -> PMIDs its rows cite."""
    out: dict[str, set[str]] = defaultdict(set)
    with path.open(encoding="utf-8") as h:
        for row in _hpoa_rows(h):
            for ref in row["reference"].split(";"):
                if ref.startswith("PMID:"):
                    out[row["database_id"]].add(ref.removeprefix("PMID:").strip())
    return out


def paper_row(
    record: dict,
    status: str,
    reason: str,
    n: int | None,
    genes: list[GeneInfo],
    gene_source: str,
    cited_by: list[str],
    hpoa_pmids: dict[str, set[str]],
    found_by: str,
) -> dict:
    """One row of papers.tsv. A selected paper already cited by HPOA for a gene's main disease is excluded."""
    pmid = str(record.get("pmid") or "")
    in_hpoa = sorted({i for g in genes for i in g.main_ids if pmid in hpoa_pmids.get(i, set())})
    if status == "selected" and in_hpoa:
        status, reason = "excluded", "in_hpoa"
    return {
        "pmid": pmid,
        "pmcid": record.get("pmcid") or "",
        "status": status,
        "reason": reason,
        "licence": normalise_licence(record.get("license")),
        "n_stated": "" if n is None else n,
        "genes": ";".join(sorted(g.gene for g in genes)),
        "genes_from": gene_source,
        "weak_genes": ";".join(sorted(g.gene for g in genes if g.weak)),
        "cited_by_genereviews": bool(cited_by),
        "citing_chapters": ";".join(sorted(cited_by)),
        "in_hpoa": bool(in_hpoa),
        "in_hpoa_diseases": ";".join(in_hpoa),
        "found_by": found_by,
        "pub_year": record.get("pubYear") or "",
        "journal": (record.get("journalInfo") or {}).get("journal", {}).get("title", ""),
        "pub_types": ";".join((record.get("pubTypeList") or {}).get("pubType", [])),
        "title": plain(record.get("title")),
    }
