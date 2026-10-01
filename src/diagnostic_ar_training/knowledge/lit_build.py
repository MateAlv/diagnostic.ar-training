"""hpoa-lit, hpoa-enriched and presentation-ages from lit-extract rows (ADR-0013 amendment 2).

Feature rows become HPOA phenotype rows (aspect P) on their unit's disease:
- rule 1: counts -> `n/m`; prevalence only -> `X%`; prevalence 0 without counts -> NOT;
- rule 2: a `pooled_group` row -> a percentage (NOT for 0) on every listed disease, except a
  disease that has a non-`pooled_group` row from the same source for the same term;
- rule 3: a `pooled` row stays on its own disease;
- rule 4: `small_n`, `binned`, `lower_bound` rows are kept with their point estimate;
- rule 5: a placement whose source HPOA already cites for the same disease and term is dropped;
- rule 6: per (disease, term), count rows from distinct sources are summed into one row (one row
  per source: the largest denominator); of the percentage rows, the largest stated population is
  kept; NOT rows merge into one.

AGE_PRESENTATION rows become one age range per disease (rule 7). Everything here is a pure
function of its inputs; file access lives in `dxt lit build`.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from diagnostic_ar_training.knowledge.lit_extract import AGE_FEATURES, PRESENTATION_COLUMNS
from diagnostic_ar_training.knowledge.recount import COLUMNS as HPOA_COLUMNS

EVIDENCE = "PCS"
BIOCURATION = "diagnostic.ar-training:lit-extract"
PRESENTATION_AGE_COLUMNS = ("disease_id", "age_low_years", "age_high_years", "source")
SIM_DISEASE_ID = re.compile(r"^(OMIM|ORPHA|DECIPHER):\d+$")
WIDEN_FRACTION = 0.10
WIDEN_MIN_YEARS = 1.0
SEX_COLUMN = {"male": "MALE", "female": "FEMALE"}
SPECIFICITY = {"unit": 0, "pooled": 1, "pooled_group": 2}

USED = "used"
DROP_GROUP_SKIP = "pooled_group_unit_specific_row"
DROP_HPOA = "hpoa_double_count"
DROP_SAME_SOURCE_COUNT = "same_source_smaller_count"
DROP_PERCENT = "percentage_smaller_population"
AGE_OPEN_UPPER = "open_upper_bound"
AGE_BAD_ID = "disease_id_not_simulator_format"
AGE_NOT_CHOSEN = "not_chosen"
AGE_GROUP_SKIP = DROP_GROUP_SKIP

_NBK_URL = re.compile(r"/books/(NBK\d+)")
_GR_PART = re.compile(r"[?&]book=gene&part=([A-Za-z0-9_-]+)")


def _flags(row: dict) -> list[str]:
    return [f for f in row["flags"].split(";") if f]


def _specificity(row: dict) -> str:
    flags = _flags(row)
    return "pooled_group" if "pooled_group" in flags else "pooled" if "pooled" in flags else "unit"


def _int(value: str) -> int | None:
    value = (value or "").strip()
    return int(value) if value else None


def _float(value: str) -> float | None:
    value = (value or "").strip()
    return float(value) if value else None


def _diseases(row: dict) -> list[str]:
    """The diseases a row is placed on: every listed one for `pooled_group`, else its own."""
    if _specificity(row) != "pooled_group":
        return [row["disease_id"].strip()]
    return list(dict.fromkeys(u.split("|", 1)[1] for u in row["construction_unit"].split(";") if "|" in u))


def _units(row: dict) -> list[tuple[str, str]]:
    return [tuple(u.split("|", 1)) for u in row["construction_unit"].split(";") if "|" in u]


# --- Citations ------------------------------------------------------------------


def reference_keys(reference: str) -> set[str]:
    """Keys a HPOA `reference` field cites: `PMID:n`, `NBKn` (bare or a Bookshelf URL), `GR:<shortname>`."""
    keys = set()
    for ref in (r.strip() for r in reference.split(";")):
        if not ref:
            continue
        if ref.startswith("PMID:") or re.fullmatch(r"NBK\d+", ref):
            keys.add(ref)
        if m := _NBK_URL.search(ref):
            keys.add(m.group(1))
        if m := _GR_PART.search(ref):
            keys.add(f"GR:{m.group(1)}")
    return keys


def source_keys(source_id: str, chapters: dict[str, tuple[str, str]]) -> set[str]:
    """Keys that cite a literature source: a paper's PMID; a chapter's NBK id, its PMID and shortname.

    `chapters` maps an NBK id to (shortname, chapter PMID) from the GeneReviews index.
    """
    if source_id.startswith("PMID:"):
        return {source_id}
    keys = {source_id}
    shortname, pmid = chapters.get(source_id, ("", ""))
    if shortname:
        keys.add(f"GR:{shortname}")
    if pmid:
        keys.add(f"PMID:{pmid}")
    return keys


def hpoa_index(rows: list[dict], ontology) -> dict:
    """From hpoa-recount rows (aspect P), per (disease, resolved term):
    citations (reference keys), notations of positive rows, and whether a NOT row exists;
    plus disease names and the set of diseases."""
    cites: dict[tuple[str, str], set[str]] = defaultdict(set)
    positive: dict[tuple[str, str], set[str]] = defaultdict(set)
    names: dict[str, str] = {}
    for row in rows:
        names.setdefault(row["database_id"], row["disease_name"])
        if row["aspect"] != "P" or not (term := ontology.resolve(row["hpo_id"])):
            continue
        key = (row["database_id"], term)
        cites[key] |= reference_keys(row["reference"])
        if row["qualifier"] != "NOT" and row["frequency"] != "HP:0040285":
            positive[key].add(notation(row["frequency"]))
    return {"cites": dict(cites), "positive": dict(positive), "names": names}


def notation(frequency: str) -> str:
    """counts, percent, category or none, as the simulator reads a HPOA frequency."""
    f = (frequency or "").strip()
    if not f:
        return "none"
    if re.fullmatch(r"\d+\s*/\s*\d+", f) and int(f.split("/")[1]) > 0:
        return "counts"
    if re.fullmatch(r"\d+(?:\.\d+)?\s*%", f):
        return "percent"
    return "category"


# --- Feature rows ---------------------------------------------------------------


@dataclass
class Placement:
    """One literature figure placed on one disease."""

    row_id: int
    source_id: str
    disease_id: str
    term: str
    kind: str
    """count, percent or not"""
    n: int | None
    m: int | None
    prevalence: float
    population: int
    sex: str
    specificity: str
    disease_name: str
    outcome: str = USED


def place(rows: list[dict]) -> list[Placement]:
    """Rules 1-4: every feature row placed on its disease(s), with its notation."""
    specific = {
        (r["source_id"], r["disease_id"].strip(), r["hpo_id"].strip())
        for r in rows
        if r["feature_label"] not in AGE_FEATURES and _specificity(r) != "pooled_group"
    }
    out = []
    for i, r in enumerate(rows):
        if r["feature_label"] in AGE_FEATURES:
            continue
        spec = _specificity(r)
        p = float(r["prevalence"])
        n, m = _int(r["n_affected"]), _int(r["n_assessed"])
        if spec == "pooled_group":
            kind = "not" if p == 0 else "percent"
        elif n is not None and m is not None:
            kind = "count"
        else:
            kind = "not" if p == 0 else "percent"
        term = r["hpo_id"].strip()
        for disease in _diseases(r):
            pl = Placement(
                row_id=i,
                source_id=r["source_id"],
                disease_id=disease,
                term=term,
                kind=kind,
                n=n if kind == "count" else None,
                m=m if kind == "count" else None,
                prevalence=p,
                population=m or 0,
                sex=r["sex_restriction"],
                specificity=spec,
                disease_name=r["disease_name"] if disease == r["disease_id"].strip() else "",
            )
            if spec == "pooled_group" and (r["source_id"], disease, term) in specific:
                pl.outcome = DROP_GROUP_SKIP
            out.append(pl)
    return out


def drop_hpoa_cited(placements: list[Placement], cites: dict, chapters: dict) -> None:
    """Rule 5, in place."""
    for pl in placements:
        if pl.outcome == USED and source_keys(pl.source_id, chapters) & cites.get(
            (pl.disease_id, pl.term), set()
        ):
            pl.outcome = DROP_HPOA


def _percent(p: float) -> str:
    return f"{round(p * 100, 2):g}%"


def _agreed_sex(group: list[Placement]) -> str:
    sexes = {pl.sex for pl in group}
    return SEX_COLUMN.get(sexes.pop(), "") if len(sexes) == 1 else ""


def _percent_rank(pl: Placement) -> tuple:
    """Largest stated population first; on a tie both sexes before one, then the more specific
    placement, then source and file order."""
    return (-pl.population, bool(pl.sex), SPECIFICITY[pl.specificity], pl.source_id, pl.row_id)


def _decided_by(top: Placement, runner: Placement) -> str:
    if top.population != runner.population:
        return "stated_population"
    if bool(top.sex) != bool(runner.sex):
        return "both_sexes_over_one"
    if top.specificity != runner.specificity:
        return "specificity"
    return "source_then_file_order"


def pool(placements: list[Placement], names: dict[str, str]) -> tuple[list[dict], dict]:
    """Rule 6: the surviving placements -> HPOA rows (sorted by disease, term, kind); marks drops in place."""
    groups: dict[tuple[str, str], list[Placement]] = defaultdict(list)
    for pl in placements:
        if pl.outcome == USED:
            groups[(pl.disease_id, pl.term)].append(pl)
    stats: Counter = Counter()
    out = []
    for (disease, term), group in sorted(groups.items()):
        name = names.get(disease) or next((pl.disease_name for pl in group if pl.disease_name), "")
        base = {c: "" for c in HPOA_COLUMNS} | {
            "database_id": disease,
            "disease_name": _clean(name),
            "hpo_id": term,
            "evidence": EVIDENCE,
            "aspect": "P",
            "biocuration": BIOCURATION,
        }
        counts = [pl for pl in group if pl.kind == "count"]
        if counts:
            best: dict[str, Placement] = {}
            for pl in sorted(counts, key=lambda x: (-x.m, x.row_id)):
                if pl.source_id in best:
                    pl.outcome = DROP_SAME_SOURCE_COUNT
                else:
                    best[pl.source_id] = pl
            kept = list(best.values())
            n, m = sum(pl.n for pl in kept), sum(pl.m for pl in kept)
            refs = ";".join(sorted(best))
            out.append(base | {"reference": refs, "frequency": f"{n}/{m}", "sex": _agreed_sex(kept)})
            stats["count_rows"] += 1
            stats["count_rows_pooling_several_sources"] += len(kept) > 1
            stats["count_rows_mixed_sex"] += len({pl.sex for pl in kept}) > 1
        percents = sorted((pl for pl in group if pl.kind == "percent"), key=_percent_rank)
        if percents:
            top = percents[0]
            for pl in percents[1:]:
                pl.outcome = DROP_PERCENT
            if len(percents) > 1:
                stats[f"percent_choice_by_{_decided_by(top, percents[1])}"] += 1
            sex = SEX_COLUMN.get(top.sex, "")
            out.append(base | {"reference": top.source_id, "frequency": _percent(top.prevalence), "sex": sex})
            stats["percent_rows"] += 1
            stats["percent_rows_beside_lit_counts"] += bool(counts)
        nots = [pl for pl in group if pl.kind == "not"]
        if nots:
            refs = ";".join(sorted({pl.source_id for pl in nots}))
            out.append(base | {"qualifier": "NOT", "reference": refs, "sex": _agreed_sex(nots)})
            stats["not_rows"] += 1
            stats["not_rows_beside_lit_positive"] += bool(counts or percents)
    return out, dict(sorted(stats.items()))


def _clean(value: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", value).strip()


def effect_on_existing(out_rows: list[dict], positive: dict) -> dict:
    """Per positive (disease, term) written: new to HPOA, or what it does to the existing estimate
    under the simulator's precedence (counts > percentages > categories)."""
    lit: dict[tuple[str, str], set[str]] = defaultdict(set)
    nots = []
    for r in out_rows:
        key = (r["database_id"], r["hpo_id"])
        if r["qualifier"] == "NOT":
            nots.append(key)
        else:
            lit[key].add("counts" if "/" in r["frequency"] else "percent")
    effects: Counter = Counter()
    for key, kinds in lit.items():
        have = positive.get(key)
        mine = "counts" if "counts" in kinds else "percent"
        if not have:
            effects["new_term"] += 1
            continue
        theirs = next(k for k in ("counts", "percent", "category", "none") if k in have)
        if mine == "counts":
            effects[
                "counts_pooled_with_hpoa_counts"
                if theirs == "counts"
                else "lit_counts_override_hpoa_" + theirs
            ] += 1
        elif theirs == "counts":
            effects["lit_percent_shadowed_by_hpoa_counts"] += 1
        elif theirs == "percent":
            effects["percent_averaged_with_hpoa_percent"] += 1
        else:
            effects["lit_percent_overrides_hpoa_" + theirs] += 1
    terms = {"new": effects["new_term"], "existing": len(lit) - effects["new_term"]}
    return {
        "positive_pairs": len(lit),
        "terms": terms,
        "effects": dict(sorted(effects.items())),
        "not_pairs": len(nots),
        "not_pairs_conflicting_with_hpoa_positive": sum(k in positive for k in nots),
    }


# --- Presentation ages ----------------------------------------------------------


def widen(low: float, high: float) -> tuple[float, float, bool]:
    """A single value widened by ±max(10%, 1 year), floored at 0; a range is kept."""
    if low != high:
        return low, high, False
    pad = max(WIDEN_FRACTION * low, WIDEN_MIN_YEARS)
    return max(0.0, low - pad), low + pad, True


def presentation_ages(rows: list[dict]) -> tuple[list[dict], dict]:
    """Rule 7: one range per disease from AGE_PRESENTATION rows: GeneReviews first, then the largest
    stated population (non-sex-restricted, then source and row order on ties).

    A missing low end (before X, or a range starting prenatally) is 0. A missing high end leaves
    no range and the row is not used. A `pooled_group` row applies to every listed disease that
    has no other AGE_PRESENTATION row from the same source (as rule 2).
    """
    ages = [(i, r) for i, r in enumerate(rows) if r["feature_label"] == "AGE_PRESENTATION"]
    specific = {
        (r["source_id"], r["disease_id"].strip()) for _, r in ages if _specificity(r) != "pooled_group"
    }
    outcomes: Counter = Counter()
    candidates: dict[str, list[tuple]] = defaultdict(list)
    for i, r in ages:
        low, high = (_float(r[c]) for c in PRESENTATION_COLUMNS)
        for disease in _diseases(r):
            if _specificity(r) == "pooled_group" and (r["source_id"], disease) in specific:
                outcomes[AGE_GROUP_SKIP] += 1
            elif high is None:
                outcomes[AGE_OPEN_UPPER] += 1
            elif not SIM_DISEASE_ID.match(disease):
                outcomes[AGE_BAD_ID] += 1
            else:
                rank = (
                    r["source_kind"] != "genereviews",
                    -(_int(r["n_assessed"]) or 0),
                    bool(r["sex_restriction"]),
                    r["source_id"],
                    i,
                )
                candidates[disease].append((rank, low or 0.0, high, r))
    out = []
    widened = 0
    kinds: Counter = Counter()
    specificity: Counter = Counter()
    for disease in sorted(candidates):
        ranked = sorted(candidates[disease], key=lambda x: x[0])
        _, low, high, r = ranked[0]
        outcomes[USED] += 1
        outcomes[AGE_NOT_CHOSEN] += len(ranked) - 1
        low, high, w = widen(low, high)
        widened += w
        kinds[r["source_kind"]] += 1
        specificity[_specificity(r)] += 1
        out.append(
            {
                "disease_id": disease,
                "age_low_years": f"{round(low, 4):g}",
                "age_high_years": f"{round(high, 4):g}",
                "source": r["source_id"],
            }
        )
    stats = {
        "rows_in": len(ages),
        "placements_by_outcome": dict(sorted(outcomes.items())),
        "diseases": len(out),
        "by_source_kind": dict(sorted(kinds.items())),
        "by_row_specificity": dict(sorted(specificity.items())),
        "single_values_widened": widened,
    }
    return out, stats


def onset_coverage(rows: list[dict], presentation: list[dict]) -> dict:
    """AGE_ONSET rows: how many, and which diseases they reach (not used; ADR-0013 amendment 2 rule 7)."""
    onset = [r for r in rows if r["feature_label"] == "AGE_ONSET"]
    diseases = {d for r in onset for d in _diseases(r)}
    with_ages = {r["disease_id"] for r in presentation}
    return {
        "rows": len(onset),
        "diseases": len(diseases),
        "diseases_also_with_presentation_age": len(diseases & with_ages),
        "diseases_only_onset": len(diseases - with_ages),
        "units": len({u for r in onset for u in _units(r)}),
        "by_source_kind": dict(sorted(Counter(r["source_kind"] for r in onset).items())),
    }


# --- Writers --------------------------------------------------------------------


def hpoa_lines(rows: list[dict]) -> list[str]:
    return ["\t".join(r[c] for c in HPOA_COLUMNS) + "\n" for r in rows]


def presentation_lines(rows: list[dict]) -> list[str]:
    head = "\t".join(PRESENTATION_AGE_COLUMNS) + "\n"
    return [head] + ["\t".join(r[c] for c in PRESENTATION_AGE_COLUMNS) + "\n" for r in rows]


# --- Whole build ----------------------------------------------------------------


def build(rows: list[dict], hpoa_rows: list[dict], ontology, chapters: dict[str, tuple[str, str]]) -> dict:
    """Validated shard rows + hpoa-recount rows -> hpoa-lit rows, presentation ages, report body."""
    index = hpoa_index(hpoa_rows, ontology)
    placements = place(rows)
    drop_hpoa_cited(placements, index["cites"], chapters)
    lit_rows, pool_stats = pool(placements, index["names"])
    ages, age_stats = presentation_ages(rows)

    by_row: dict[int, set[str]] = defaultdict(set)
    for pl in placements:
        by_row[pl.row_id].add(pl.outcome)
    row_outcomes: Counter = Counter()
    for outcomes in by_row.values():
        if USED in outcomes:
            row_outcomes[USED] += 1
        else:
            row_outcomes["+".join(sorted(outcomes))] += 1
    feature_rows = [r for r in rows if r["feature_label"] not in AGE_FEATURES]

    written = {r["database_id"] for r in lit_rows}
    units_in = {u for r in feature_rows for u in _units(r)}
    units_enriched = {u for u in units_in if u[1] in written}
    return {
        "lit_rows": lit_rows,
        "presentation_ages": ages,
        "report": {
            "rows_in": {
                "total": len(rows),
                "feature": len(feature_rows),
                "age_presentation": sum(r["feature_label"] == "AGE_PRESENTATION" for r in rows),
                "age_onset": sum(r["feature_label"] == "AGE_ONSET" for r in rows),
            },
            "feature_rows_by_outcome": dict(sorted(row_outcomes.items())),
            "placements": {
                "total": len(placements),
                "by_kind": dict(sorted(Counter(pl.kind for pl in placements).items())),
                "by_outcome": dict(sorted(Counter(pl.outcome for pl in placements).items())),
                "pooled_group_rows": sum(_specificity(r) == "pooled_group" for r in feature_rows),
                "pooled_group_placements": sum(pl.specificity == "pooled_group" for pl in placements),
            },
            "hpoa_lit": {
                "rows_out": len(lit_rows),
                "by_notation": pool_stats,
                "diseases": len(written),
                "diseases_not_in_hpoa_recount": len(written - set(index["names"])),
                "units_in": len(units_in),
                "units_enriched": len(units_enriched),
                "sources_used": len({pl.source_id for pl in placements if pl.outcome == USED}),
                **effect_on_existing(lit_rows, index["positive"]),
            },
            "presentation_ages": age_stats,
            "age_onset_coverage": onset_coverage(rows, ages),
        },
    }


def chapter_index(text: str) -> dict[str, tuple[str, str]]:
    """GeneReviews `GRtitle_shortname_NBKid.txt` -> NBK id -> (shortname, chapter PMID)."""
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) >= 4 and cells[2].startswith("NBK"):
            out[cells[2]] = (cells[0], cells[3].strip())
    return out
