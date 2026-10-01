"""lit-papers-v2: a deterministic re-screen of the lit-sources-v1 papers (ADR-0013 amendment 1).

The P001 pilot found that only 3 of 12 selected papers were cohorts of at least
20 genetically confirmed patients per (gene, disease) unit. The dead ends had
recognisable signatures in the title and abstract: diagnostic-yield and panel
studies, screening studies with few positives, association designs, penetrance
in carriers, variant databases and mixed multi-disease series. This module
holds the rule built from them. It is a pure function of a Europe PMC record
(title, abstract, publication types) and the paper's genes.

The rule, in order (the first failing check sets the reason):
1. publication type: case report, review, trial;
2. title signatures (TITLE_SIGNATURES): review; case, family or sibling
   report; a single patient; database or biobank; screening or method title
   (sequencing, panel, NGS, molecular or genetic testing, screening other than
   newborn screening, mutation analysis, "for mutations in", variant
   prevalence or frequency, diagnostic yield, unsolved or suspected cases,
   prenatal diagnosis, "is a frequent cause"); carriers or penetrance;
   variant-level work (novel or new variants, reclassification, in silico,
   functional studies, copy number); treatment; biomarker; model organism;
   then a plural disease group ("disorders", "cardiomyopathies") with no gene
   symbol of the paper; then a title count below MIN_PER_UNIT;
3. abstract signatures (ABSTRACT_SIGNATURES, on title and abstract):
   diagnostic yield or negative-tested or unexplained cohorts; sequencing
   applied to a series of N; association or risk designs (susceptibility,
   predisposition, odds or hazard ratio, case-control, risk factors,
   polymorphism, comparison with healthy individuals); penetrance in carriers
   (unaffected carriers, cascade or family screening, lifetime risk, general
   population); variant databases or biobanks; then positives reported as a
   share of those screened, all below MIN_PER_UNIT;
4. positive evidence of a per-unit cohort of at least MIN_PER_UNIT: a stated
   count bound to a gene symbol of the paper or to a single disease (a defined
   abbreviation whose long form is not a plural group, or a disease noun), or a
   bare count in an abstract whose title names a single disease or gene and no
   group.
"""

import re

from diagnostic_ar_training.knowledge import lit_sources as ls

RECORD_FIELDS = ("pmid", "pmcid", "title", "abstractText", "pubTypeList", "pubYear", "source")
MIN_PER_UNIT = 20

PUB_TYPES = {
    "case reports": "case_report",
    "review": "review",
    "systematic review": "review",
    "meta-analysis": "review",
    "clinical trial": "trial",
    "randomized controlled trial": "trial",
    "controlled clinical trial": "trial",
    "clinical trial, phase i": "trial",
    "clinical trial, phase ii": "trial",
    "clinical trial, phase iii": "trial",
    "clinical trial, phase iv": "trial",
}

GROUP_PLURAL = (
    r"disorders|diseases|syndromes|conditions|defects|errors|anomalies|cardiomyopathies|myopathies"
    r"|neuropathies|dystrophies|ataxias|dysplasias|ichthyoses|leukodystrophies|ciliopathies|channelopathies"
    r"|encephalopathies|epilepsies|FAODs|IEMs"
)
_GROUP = re.compile(rf"\b(?:{GROUP_PLURAL})\b", re.IGNORECASE)

TITLE_SIGNATURES = (
    ("title:review", r"\breview\b|meta-analys"),
    ("title:case_report", r"case report|\ba case of\b|\bcase series of (?:two|three)\b"),
    (
        "title:family_report",
        r"\b(?:a|an|one|two|three|four) (?:[\w'-]+ ){0,3}(?:family|families|pedigrees?|kindreds?|siblings)\b"
        r"|\b(?:siblings?|sibs|twins?|brothers|sisters|pedigrees)\b",
    ),
    (
        "title:single_patient",
        r"\b(?:a|an|one) (?:[\w'-]+ ){0,3}(?:patient|boy|girl|child|infant|neonate|man|woman|proband|case)\b",
    ),
    ("title:database", r"\bdatabases?\b|\bbiobank\b"),
    (
        "title:screening_method",
        r"sequencing|\bpanels?\b|\bNGS\b|molecular (?:testing|diagnosis|screening)"
        r"|genetic (?:testing|screening)|(?<!newborn )(?<!neonatal )screening|mutation(?:al)? analysis"
        r"|\bfor (?:[\w-]+ ){0,2}(?:mutations|variants)\b|population-based"
        r"|prevalence of (?:[\w-]+ ){0,4}(?:mutations|variants|deletions|duplications)|frequency of"
        r"|diagnostic yield|diagnostic rate|detection rate|unsolved|suspicion|suspected|prenatal diagnosis"
        r"|(?:is|are) (?:a )?(?:frequent|major|common|rare|significant) (?:[\w-]+ )?causes?",
    ),
    ("title:carriers", r"\bcarriers?\b|penetrance"),
    (
        "title:variant_level",
        r"\b(?:novel|new) (?:[\w-]+ ){0,3}(?:mutations?|variants?|variations?|deletions?)\b"
        r"|reclassification|variant curation|mutation update|in silico|pathogenicity"
        r"|functional (?:analysis|characteri[sz]ation|studies)|copy[- ]number|pseudogenes?",
    ),
    (
        "title:treatment",
        r"\b\w+mab\b|\btreatment\b|\btherap(?:y|ies|eutic)\b|transplant\w*|\bsurgery\b|\bsurgical\b|\bdrugs?\b"
        r"|enzyme replacement|\bdosing\b|\bsafety\b|\befficacy\b",
    ),
    ("title:biomarker", r"\b(?:bio)?markers?\b|\bserum\b|\bplasma\b"),
    (
        "title:model_organism",
        r"\b(?:mice|mouse|murine|zebrafish|drosophila|xenopus|rats?|knock-?out|iPSCs?|organoids?)\b",
    ),
)

ABSTRACT_SIGNATURES = (
    (
        "diagnostic_yield",
        r"diagnostic yield|diagnostic rate|detection rate|solve rate|molecular testing|diagnostic utility"
        r"|\b(?:un)?solved\b|negative for|tested negative"
        r"|previously (?:tested|unsolved|undiagnosed|unexplained)"
        r"|genetically (?:unexplained|unresolved|undetermined|undiagnosed)|unknown (?:a?etiology|cause)",
    ),
    (
        "sequenced_cohort",
        r"(?:exome|genome|panel|targeted|next[- ]generation) sequencing (?:was |were )?"
        r"(?:performed |applied |carried out )?"
        r"(?:in|of|on|for) (?:a (?:[\w-]+ ){0,2}(?:cohort|series|group|total) of )?\d",
    ),
    (
        "association",
        r"susceptib|predispos|odds ratio|case[- ]control|risk factors?|genetic risk|increased risk"
        r"|risk alleles?"
        r"|polymorphism|\bGWAS\b|genome-wide association|association (?:study|analysis)|hazard ratio"
        r"|compared (?:with|to) (?:\d+ )?healthy",
    ),
    (
        "penetrance",
        r"penetrance|(?:unaffected|asymptomatic|presymptomatic|healthy|non-?penetrant) (?:[\w-]+ )?carriers"
        r"|carrier (?:frequency|screening|status)|cascade (?:screening|testing)"
        r"|predictive (?:genetic )?testing"
        r"|family screening|lifetime risk|cumulative (?:risk|incidence)|general population",
    ),
    ("database", r"(?:variant|mutation|locus-specific) database|\bbiobank\b|\bLOVD\b"),
)

POSITIVE_SHARE = re.compile(
    r"\b([\w,]+) (?:[\w-]+ ){0,3}\(\s?\d+(?:\.\d+)?\s?%\)\s?(?:[\w-]+ ){0,2}"
    r"(?:carried|harbou?red|had|tested positive|were positive|were found to (?:carry|harbou?r|have))"
    r"|(?:identified|detected|found) in (?:[\w-]+ ){0,2}([\w,]+) (?:[\w-]+ ){0,3}\(\s?\d+(?:\.\d+)?\s?%\)"
    r"|\b([\w,]+) (?:of|out of) (?:the )?[\d,]+ (?:[\w-]+ ){0,3}"
    r"(?:carried|harbou?red|tested positive|were positive)",
    re.IGNORECASE,
)
_ABBREVIATION = re.compile(r"([A-Za-z][\w'-]*)\s\(([A-Z][A-Za-z0-9-]{1,11})\)")
DISEASE_HEAD = re.compile(
    r"(?:disease|syndrome|deficiency|dystrophy|ataxia|paraplegia|plegia|pathy|lepsy|osis|emia|aemia|uria|itis"
    r"|ism|oma|plasia|trophy|ectasia|elasticum|pigmentosa|amaurosis|imperfecta|bullosa|congenita|anemia"
    r"|calcification|rickets|galactosemia|cystinosis|albinism|aniridia|deafness|dementia|parkinsonism|dystonia"
    r"|hypoplasia|atrophy|proteinopathy|neurodegeneration|hemophilia|thalassemia|porphyria|acidemia|aciduria)$",
    re.IGNORECASE,
)
NOT_DISEASE = {
    "diagnosis", "prognosis", "mechanism", "mechanisms", "metabolism", "organism", "mosaicism",
    "polymorphism", "dimorphism", "empathy", "academia", "genome", "homeostasis", "anastomosis",
}  # fmt: skip
BIND = {"with", "carrying", "harboring", "harbouring", "bearing", "having", "of"}
BIND_PAIRS = {("affected", "by"), ("diagnosed", "with"), ("due", "to"), ("caused", "by")}
NOT_UNIT = {
    "suspected",
    "possible",
    "probable",
    "undiagnosed",
    "unexplained",
    "unknown",
    "clinical",
    "clinically",
}
COHORT_NOUNS = {"cohort", "registry", "series", "group", "dataset", "set"}
COUNT_GAP = 3
PHRASE_WINDOW = 6


def record_text(record: dict) -> tuple[str, str]:
    return ls.plain(record.get("title")), ls.plain(record.get("abstractText"))


def unit_terms(title: str, abstract: str, genes: list[str]) -> tuple[set[str], set[str]]:
    """(unit terms, group terms): the paper's gene symbols and the abbreviations it defines.

    An abbreviation whose long form ends in a plural group word ("fatty acid
    oxidation disorders (FAODs)") is a group term, never a unit term.
    """
    units, groups = set(genes), set()
    for m in _ABBREVIATION.finditer(f"{title}. {abstract}"):
        last, abbr = m.group(1), m.group(2)
        if sum(c.isupper() for c in abbr) < 2:
            continue
        (groups if _GROUP.fullmatch(last) or abbr.endswith("s") and abbr[:-1].isupper() else units).add(abbr)
    return units - groups, groups


def _disease_noun(token: str) -> bool:
    word = token.lower().split("-")[-1]
    return word not in NOT_DISEASE and DISEASE_HEAD.search(word) is not None


def _is_unit(token: str, units: set[str]) -> bool:
    return any(token == u or token.startswith(u + "-") for u in units)


def _count(token: str) -> int | None:
    return ls._number(token)


def _sentences(title: str, abstract: str) -> list[list[str]]:
    return [ls._TOKEN.findall(s) for s in [title, *ls._sentences(abstract)]]


def _phrase_names_unit(tokens: list[str], units: set[str], groups: set[str]) -> bool:
    """The phrase after a binding word names one unit: a unit term, or a disease noun not in a group."""
    for t in tokens[:PHRASE_WINDOW]:
        low = t.lower()
        if low in NOT_UNIT or t in groups or _GROUP.fullmatch(t):
            return False
        if _is_unit(t, units) or _disease_noun(t):
            return True
        if low in ("and", "or", "in", "from", "at", "who", "which", "were", "was", "had"):
            return False
    return False


def per_unit_counts(title: str, abstract: str, genes: list[str]) -> list[tuple[int, str]]:
    """Stated counts bound to one unit, as (count, how). Only counts of at least MIN_PER_UNIT are kept.

    Patterns, per sentence (the title is one):
    - `N [<= 3 words] NOUN with|carrying|of|affected by ... <unit term or disease noun>`;
    - `N [<= 3 words, one a unit term] NOUN` ("45 MCADD patients", "84 ENPP1-deficient individuals");
    - `<unit term> [<= 4 words] cohort|registry|series|n N` ("ENPP1 data set (n = 84)");
    - a bare `N [<= 3 words] NOUN` when the title names one unit and no group.
    """
    units, groups = unit_terms(title, abstract, genes)
    title_tokens = ls._TOKEN.findall(title)
    title_single = not _GROUP.search(title) and (
        any(_is_unit(t, units) for t in title_tokens) or any(_disease_noun(t) for t in title_tokens)
    )
    out = []
    for tokens in _sentences(title, abstract):
        lows = [t.lower() for t in tokens]
        for i, t in enumerate(tokens):
            n = _count(t)
            if n is None or n < MIN_PER_UNIT or n > ls.MAX_COUNT:
                continue
            if 1900 <= n <= 2100 and i and lows[i - 1] in ls._YEAR_PREVIOUS | {"january", "july", "june"}:
                continue
            noun = next(
                (
                    j
                    for j in range(i + 1, min(len(tokens), i + 2 + COUNT_GAP))
                    if ls._NOUN.fullmatch(tokens[j])
                ),
                None,
            )
            if noun is not None:
                between = tokens[i + 1 : noun]
                if "%" in between or ls.CONTROL_WORDS & {w.lower() for w in between}:
                    continue
                if any(w in groups or _GROUP.fullmatch(w) for w in between):
                    continue
                if any(_is_unit(w, units) for w in between):
                    out.append((n, "count_unit_noun"))
                    continue
                k = noun + 1
                if k < len(tokens) and (lows[k] in BIND or tuple(lows[k : k + 2]) in BIND_PAIRS):
                    k += 2 if tuple(lows[k : k + 2]) in BIND_PAIRS else 1
                    if _phrase_names_unit(tokens[k:], units, groups):
                        out.append((n, "count_noun_with_unit"))
                    continue
                if title_single:
                    out.append((n, "bare_count_single_unit_title"))
                continue
            back = lows[max(0, i - 6) : i]
            if back and back[-1] in ("n", "of") and any(w in COHORT_NOUNS or w == "n" for w in back):
                if any(_is_unit(w, units) for w in tokens[max(0, i - 6) : i]):
                    out.append((n, "unit_cohort_of_n"))
    return out


def few_positives(abstract: str) -> list[int]:
    """Positive counts reported as a share of those screened ("9 patients (5.7%) carried"); all of them."""
    out = []
    for m in POSITIVE_SHARE.finditer(abstract):
        token = next(g for g in m.groups() if g)
        n = _count(token.strip(","))
        if n is not None:
            out.append(n)
    return out


def rescreen(record: dict, genes: list[str]) -> tuple[str, str, int | None]:
    """Europe PMC record + the paper's genes -> (status, reason, largest per-unit count).

    Status is `pass` or `fail`; the reason of a pass is how the per-unit count was bound.
    """
    title, abstract = record_text(record)
    text = f"{title} {abstract}"
    counts = per_unit_counts(title, abstract, genes)
    best = max((n for n, _ in counts), default=None)
    for p in (record.get("pubTypeList") or {}).get("pubType") or []:
        if p.lower() in PUB_TYPES:
            return "fail", f"pub_type:{PUB_TYPES[p.lower()]}", best
    for reason, rx in TITLE_SIGNATURES:
        if re.search(rx, title, re.IGNORECASE):
            return "fail", reason, best
    if _GROUP.search(title) and not any(ls.word_in(g, title) for g in genes):
        return "fail", "title:disease_group", best
    title_n = ls.stated_n(title)
    if title_n is not None and title_n < MIN_PER_UNIT:
        return "fail", f"title:n_lt_{MIN_PER_UNIT}", best
    for reason, rx in ABSTRACT_SIGNATURES:
        if re.search(rx, text, re.IGNORECASE):
            return "fail", f"abstract:{reason}", best
    positives = few_positives(abstract)
    if positives and max(positives) < MIN_PER_UNIT:
        return "fail", "abstract:few_positives", best
    if best is None:
        return "fail", f"no_per_unit_n_ge_{MIN_PER_UNIT}", best
    how = next(h for n, h in counts if n == best)
    return "pass", how, best


def epmc_record_query(pmids: list[str]) -> str:
    return "(" + " OR ".join(f"EXT_ID:{p}" for p in pmids) + ") AND SRC:MED"


RESCREEN_COLUMNS = (
    "pmid", "pmcid", "status", "reason", "per_unit_n", "in_subset", "calibration_shard",
    "calibration_outcome", "licence", "n_stated", "genes", "weak_genes", "title",
)  # fmt: skip
QUALIFIED_OUTCOMES = ("extracted",)


def rescreen_rows(
    papers: list[dict], records: dict[str, dict], calibration: dict[str, tuple[str, str]]
) -> list[dict]:
    """One row per selected paper of the base list, in list order.

    `calibration` maps the PMIDs of already-extracted shards to (shard, notes outcome);
    they are re-screened to check the rule but never enter the subset.
    """
    rows = []
    for p in papers:
        status, reason, n = rescreen(records[p["pmid"]], [g for g in p["genes"].split(";") if g])
        shard, outcome = calibration.get(p["pmid"], ("", ""))
        rows.append(
            {
                "pmid": p["pmid"],
                "pmcid": p["pmcid"],
                "status": status,
                "reason": reason,
                "per_unit_n": "" if n is None else n,
                "in_subset": status == "pass" and not shard,
                "calibration_shard": shard,
                "calibration_outcome": outcome,
                "licence": p["licence"],
                "n_stated": p["n_stated"],
                "genes": p["genes"],
                "weak_genes": p["weak_genes"],
                "title": p["title"],
            }
        )
    return rows


def confusion(rows: list[dict]) -> dict:
    """The rule against the calibration papers' known outcomes (qualified = rows were extracted)."""
    cal = [r for r in rows if r["calibration_shard"]]
    cells = {"qualified_pass": 0, "qualified_fail": 0, "dead_end_pass": 0, "dead_end_fail": 0}
    for r in cal:
        truth = "qualified" if r["calibration_outcome"] in QUALIFIED_OUTCOMES else "dead_end"
        cells[f"{truth}_{r['status']}"] += 1
    per_paper = {
        f"PMID:{r['pmid']}": f"{r['calibration_outcome']} -> {r['status']} ({r['reason']})" for r in cal
    }
    return {"papers": len(cal), **cells, "per_paper": per_paper}
