"""Audit of extracted literature rows for missed facts and wrong units (ADR-0013 amendment 4, 3.2).

A seeded sample of sources (not rows) is shown to an auditor together with the guide's skip rules,
the units the source may feed and our rows for it. The auditor answers with wrong-unit rows, facts
the guide would have extracted that we missed, and rows that break the guide. Everything here is a
pure function of its inputs; file access and the Codex call live in `dxt lit audit`.
"""

import json
import math
import random
import re
from collections import Counter, defaultdict

from diagnostic_ar_training.knowledge.lit_extract import _TABLE_OPEN, AGE_FEATURES, _key, sections

SOURCE_CHAR_CAP = 12_000
CITED_SHARE = 2 / 3
MIN_SOURCES = {"C036": 2}
TRUNCATED = "[... excerpt cut at the character cap ...]"
GAP = "[...]"
KINDS = ("wrong_unit", "missed", "bad_row")
COUNT_KEYS = (
    "sources", "answered", "rows_audited", "sources_with_issue", "wrong_unit_rows", "missed_facts",
    "bad_rows", "invalid_row_numbers", "ok_false_without_entries",
)  # fmt: skip

ITEM_COLUMNS = ("item", "shard", "source_id", "source_kind", "outcome", "rows", "source_chars")
ROWS_COLUMNS = (
    "row", "feature", "hpo_id", "hpo_label", "prevalence", "prevalence_low", "prevalence_high",
    "n_affected", "n_assessed", "sex", "population", "unit", "flags", "age_onset", "age_presentation",
    "age_note", "section", "quote",
)  # fmt: skip
ISSUE_COLUMNS = (
    "item", "shard", "source_id", "kind", "row", "gene", "disease_id", "feature", "hpo_id", "detail",
    "quote", "valid", "resolution",
)  # fmt: skip

ANSWER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ok", "wrong_unit", "missed", "bad_row"],
    "properties": {
        "ok": {"type": "boolean"},
        "wrong_unit": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["row", "reason"],
                "properties": {"row": {"type": "integer"}, "reason": {"type": "string"}},
            },
        },
        "missed": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["feature", "stated_number", "quote"],
                "properties": {
                    "feature": {"type": "string"},
                    "stated_number": {"type": "string"},
                    "quote": {"type": "string", "description": "verbatim, at most 25 words"},
                },
            },
        },
        "bad_row": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["row", "reason"],
                "properties": {"row": {"type": "integer"}, "reason": {"type": "string"}},
            },
        },
    },
}

PROMPT = """You are auditing literature-extraction rows against their source. Answer only from the text below.
Do not use outside knowledge.

Standard input has three blocks: SOURCE (an excerpt of the source text), UNITS (the (gene, disease)
units this source may feed, with the disease name, then the outcome and note of our extraction of the
source) and ROWS (the rows we extracted; `row` is the number to cite). The excerpt is cut to the sections our
rows cite plus the tables: report a missed fact only if it is printed in the excerpt.

What the extraction guide asks for. A row states how often a clinical feature occurs among
AFFECTED individuals (prevalence, optionally n_affected / n_assessed), or an age at onset or at
presentation, for one unit. Every number must be printed in the source.

Task 1, wrong_unit. A row is a wrong unit when the figure describes a different gene or a different
disease than the unit the row names (compare the unit's disease name with what the figure describes:
subtype, OMIM number, gene). Rows that carry the `pooled` flag (a disease-level figure placed on one
unit of that disease) or `pooled_group` (one figure for several listed units) are correct when their
unit is one of the diseases the figure covers.

Task 2, missed. List facts the guide WOULD extract that no row has. Apply the guide's skip rules,
and list nothing the guide would skip:
- Never a number that is inferred, computed, added up, a complement ("absent in 4/246" does not give
  "present in 242/246"), read off a figure, or tallied from a per-patient table.
- Never vague quantifiers: most, majority, almost all, nearly, common, frequent, rare, a few, some,
  occasionally, typically, usually; never "up to x%" or "as many as x%".
- Never one number for several features, or a bundle category listing heterogeneous contents.
- Never a conditional share (percent of those who already have another feature) or sub-items listed
  under a parent percentage.
- Never penetrance, lifetime or cumulative risk by an age, a risk among unselected carriers, the share
  of a disease caused by a gene, detection or diagnostic yield, carrier frequency, birth prevalence,
  mortality or treatment response.
- Never evaluation units: a figure about a gene or disease that is not in UNITS is not a miss.
- Never a hedged absence ("rarely if ever"). An explicit, unhedged absence ("not observed in any of
  the 40", "never") is a fact (prevalence 0); "has not been reported" is not.
- Papers: only the paper's own results, never an Introduction or Background figure and never a sentence
  citing other studies (reference marker, "et al", "previously reported", "in the literature"). A paper
  feeds a unit only through a group of at least 20 genetically confirmed patients of that unit; a
  subgroup under 20 is never extracted, even inside a qualifying paper. A paper where no unit reaches
  20 yields nothing, so a miss in it is not a miss. A figure about a smaller slice of a group of 20 or
  more is fine.
- Ages: AGE_ONSET is age at first manifestation of the disease, AGE_PRESENTATION age at diagnosis or
  presentation of a symptomatic patient; never age at newborn, carrier, predictive or genetic or
  molecular diagnosis or confirmation, never "variable", "any age", "wide range", vague words or hedged
  statements. Convert months, weeks and days to years.
- A source whose several columns give several cohorts has one row per feature, from the column with the
  largest denominator; different populations (sexes, subtypes, adults and children) are separate rows.
- A feature that already has a row for the same unit and population is not missed.
For each missed fact give the feature, the stated number exactly as printed (for example "30%" or
"12/40" or "2 to 10 years"), and a verbatim quote of at most 25 words from the excerpt that contains it.

Task 3, bad_row. A row is bad when its numbers do not match the quote or the source, when it breaks
one of the skip rules above (inferred, conditional, bundle, vague, wrong population or sex, an age of
the wrong kind), or when its HPO label does not mean what the source feature means. Give the reason
in a short phrase. A row that is only imprecise but defensible is not bad.

Be conservative: report only what you are sure of from the excerpt, and at most 15 entries per list.
Cite rows by the `row` number. Set ok to true only if all three lists are empty."""


def sample(
    sources_by_shard: dict[str, list[str]], fraction: float, seed: int, minimum: dict[str, int] | None = None
) -> list[tuple[str, str]]:
    """(shard, source_id) of a seeded `fraction` of each shard's sources, at least one per shard.

    Sampling per shard keeps each shard's draw fixed as other shards land. `minimum` raises the
    floor of named shards. The result is ordered by shard, then by position in the shard.
    """
    minimum = MIN_SOURCES if minimum is None else minimum
    out = []
    for shard in sorted(sources_by_shard):
        sources = sources_by_shard[shard]
        if not sources:
            continue
        k = min(len(sources), max(minimum.get(shard, 1), math.ceil(len(sources) * fraction)))
        picked = set(random.Random(f"{seed}:{shard}").sample(sorted(sources), k))
        out += [(shard, s) for s in sources if s in picked]
    return out


def cut_source(text: str, cited: list[str], cap: int = SOURCE_CHAR_CAP) -> str:
    """The sections the rows cite, then the feature tables, up to about `cap` characters.

    Cited sections get at most two thirds of the cap when tables exist, so a long section
    cannot crowd out the tables. A source cited by no row starts at the beginning of the text.
    """
    lines = text.splitlines()
    found = sections(text)
    cited_spans = [span for name in dict.fromkeys(cited) for span in found.get(_key(name), [])]
    tables = sorted({span for spans in found.values() for span in spans if _TABLE_OPEN.match(lines[span[0]])})
    covered: set[int] = set()
    used = 0
    cut = False

    def take(spans: list[tuple[int, int]], limit: int) -> None:
        nonlocal used, cut
        for a, b in spans:
            for i in range(a, b):
                if i in covered:
                    continue
                if used + len(lines[i]) + 1 > limit:
                    cut = True
                    return
                covered.add(i)
                used += len(lines[i]) + 1

    take(cited_spans, int(cap * CITED_SHARE) if tables else cap)
    take(tables, cap)
    if not covered:
        take([(0, len(lines))], cap)
    out, previous = [], None
    for i in sorted(covered):
        if previous is not None and i != previous + 1:
            out.append(GAP)
        out.append(lines[i])
        previous = i
    if cut:
        out.append(TRUNCATED)
    return "\n".join(out) + "\n"


def units_text(units: list[tuple[str, str]], names: dict[str, str], outcome: str, note: str) -> str:
    """The allowed units (gene | disease_id | disease name), then how our extraction ended."""
    lines = [f"{g} | {d} | {names.get(d, '?')}" for g, d in sorted(units)]
    return "\n".join(lines + ["", f"Extraction outcome: {outcome}", f"Extraction note: {note}"]) + "\n"


def rows_table(rows: list[tuple[int, dict]], labels: dict[str, str]) -> str:
    """Our rows for one source as a TSV; `row` is the line of the shard file."""

    def clean(value: str) -> str:
        return re.sub(r"[\t\r\n]+", " ", value).strip()

    lines = ["\t".join(ROWS_COLUMNS)]
    for line, r in rows:
        age = r["feature_label"] in AGE_FEATURES
        lines.append(
            "\t".join(
                clean(str(v))
                for v in (
                    line,
                    r["feature_label"],
                    r["hpo_id"],
                    labels.get(r["hpo_id"], ""),
                    r["prevalence"],
                    r["prevalence_low"],
                    r["prevalence_high"],
                    r["n_affected"],
                    r["n_assessed"],
                    r["sex_restriction"],
                    r["population"],
                    r["construction_unit"],
                    r["flags"],
                    _range(r, "onset") if age else "",
                    _range(r, "presentation") if age else "",
                    r["age_note"],
                    r["section"],
                    r["evidence_quote"],
                )
            )
        )
    return "\n".join(lines) + "\n"


def _range(row: dict, kind: str) -> str:
    low, high = row[f"age_{kind}_low_years"], row[f"age_{kind}_high_years"]
    return f"{low}-{high}" if low or high else ""


def stdin_text(source: str, units: str, rows: str) -> str:
    """The blocks the auditor reads, in the order the prompt names them."""
    return (
        f"=== SOURCE ===\n{source}\n=== UNITS (gene | disease_id | disease name) ===\n{units}\n"
        f"=== ROWS ===\n{rows}"
    )


def schema_json() -> str:
    return json.dumps(ANSWER_SCHEMA, indent=1)


def parse_answer(data: dict) -> dict:
    """A schema-shaped answer -> ok, wrong_unit, missed, bad_row, with every entry checked for shape.

    Raises ValueError on anything that is not the schema's shape.
    """
    if not isinstance(data, dict):
        raise ValueError("answer is not an object")
    try:
        out = {
            "ok": bool(data["ok"]),
            "wrong_unit": [{"row": int(x["row"]), "reason": str(x["reason"])} for x in data["wrong_unit"]],
            "missed": [
                {
                    "feature": str(x["feature"]),
                    "stated_number": str(x["stated_number"]),
                    "quote": str(x["quote"]),
                }
                for x in data["missed"]
            ],
            "bad_row": [{"row": int(x["row"]), "reason": str(x["reason"])} for x in data["bad_row"]],
        }
    except (KeyError, TypeError) as e:
        raise ValueError(f"answer lacks the schema's fields: {e!r}") from e
    return out


def has_issue(answer: dict) -> bool:
    return not answer["ok"] or any(answer[k] for k in KINDS)


def issues(item: dict, answer: dict, rows: dict[int, dict]) -> list[dict]:
    """One line per flagged issue; `valid` is false for a row number that is not one of the item's rows."""
    base = {k: item[k] for k in ("item", "shard", "source_id")}
    out = []
    for kind in ("wrong_unit", "bad_row"):
        for x in answer[kind]:
            r = rows.get(x["row"])
            out.append(
                base
                | {
                    "kind": kind,
                    "row": x["row"],
                    "gene": r["gene"] if r else "",
                    "disease_id": r["disease_id"] if r else "",
                    "feature": r["feature_label"] if r else "",
                    "hpo_id": r["hpo_id"] if r else "",
                    "detail": x["reason"],
                    "quote": r["evidence_quote"] if r else "",
                    "valid": str(r is not None).lower(),
                }
            )
    for x in answer["missed"]:
        out.append(
            base
            | {
                "kind": "missed",
                "feature": x["feature"],
                "detail": x["stated_number"],
                "quote": x["quote"],
                "valid": "true",
            }
        )
    return out


def summarise(results: list[dict], items: list[dict], row_counts: dict[str, int]) -> dict:
    """Per shard and in total: sources audited and answered, sources with any issue, and issue counts.

    `results` are the parsed answers (each with its item id and `issues` lines); `items` is the frozen
    sample; `row_counts` maps item id to its number of rows.
    """
    by_item = {r["item"]: r for r in results}
    shards: dict[str, Counter] = defaultdict(Counter)
    for it in items:
        c = shards[it["shard"]]
        c["sources"] += 1
        c["rows_audited"] += row_counts.get(it["item"], 0)
        r = by_item.get(it["item"])
        if r is None:
            continue
        a = r["answer"]
        c["answered"] += 1
        c["sources_with_issue"] += has_issue(a)
        c["wrong_unit_rows"] += sum(x["valid"] == "true" for x in r["issues"] if x["kind"] == "wrong_unit")
        c["missed_facts"] += len(a["missed"])
        c["bad_rows"] += sum(x["valid"] == "true" for x in r["issues"] if x["kind"] == "bad_row")
        c["invalid_row_numbers"] += sum(x["valid"] != "true" for x in r["issues"])
        c["ok_false_without_entries"] += (not a["ok"]) and not any(a[k] for k in KINDS)

    def row(c: Counter) -> dict:
        d = {k: c[k] for k in COUNT_KEYS}
        d["share_sources_with_issue"] = (
            round(c["sources_with_issue"] / c["answered"], 4) if c["answered"] else None
        )
        return d

    total: Counter = Counter()
    for c in shards.values():
        total.update(c)
    return {"total": row(total), "by_shard": {s: row(c) for s, c in sorted(shards.items())}}
