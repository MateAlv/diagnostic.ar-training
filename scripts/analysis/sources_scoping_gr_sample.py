"""SOURCES-SCOPING-001: draw and screen a 30-chapter GeneReviews sample.

The frame is every GeneReviews chapter that names a construction gene and
touches no `litpanel-split-v3` unit (gene or disease id). For each sampled
chapter it counts, from the NXML of the NCBI litarch bulk archive:
- "Frequency of Select Features"-style tables and their numeric cells;
- Clinical Description sentences that state a number (%, n/N, "n of N");
- sentences that state an age at onset, presentation or diagnosis;
- cited PMIDs, and how many are R1 held-out or literature-panel sources.

The automatic counts are a screen; the verdicts in the write-up come from
reading the flagged snippets, which go to --snippets (outside the repo: they
quote copyrighted text).

Usage: python scripts/analysis/sources_scoping_gr_sample.py --genes GENES_TSV
       --archive-dir DIR --out DIR --snippets FILE
"""

import argparse
import csv
import json
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from diagnostic_ar_training import DATA_DIR

SEED = 20260930
SIZE = 30
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\s?%|\b\d+\s?/\s?\d+\b|\b\d+ of \d+\b")
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
SKIP_TABLES = re.compile(
    r"differential|evaluation|treatment|surveillance|testing|genes and databases|omim|variants|resources",
    re.I,
)
FEATURE_TABLES = re.compile(r"frequency|features|findings|manifestations|phenotyp", re.I)
CLINICAL_SECS = re.compile(r"^(clinical description|suggestive findings|clinical characteristics)$", re.I)


def text(e) -> str:
    return re.sub(r"\s+", " ", "".join(e.itertext())).strip()


def sentences(s: str) -> list[str]:
    return [x.strip() for x in re.split(r"(?<=[.;])\s+(?=[A-Z(])", s) if x.strip()]


def screen(path: Path, heldout: set[str], panel: set[str]) -> tuple[dict, dict]:
    root = ET.parse(path).getroot()
    tables, snip_tables = [], []
    for tw in root.iter("table-wrap"):
        cap = tw.find("caption")
        caption = text(cap) if cap is not None else ""
        if not caption or SKIP_TABLES.search(caption) or not FEATURE_TABLES.search(caption):
            continue
        rows = [[text(c) for c in tr if c.tag in ("td", "th")] for tr in tw.iter("tr")]
        numeric_rows = [r for r in rows if any(NUMBER.search(c) for c in r[1:])]
        tables.append({"caption": caption, "rows": len(rows), "numeric_rows": len(numeric_rows)})
        snip_tables.append({"caption": caption, "rows": [" | ".join(r) for r in rows[:14]]})
    table_ids = {id(x) for tw in root.iter("table-wrap") for x in tw.iter()}
    clinical, seen = [], set()
    for sec in root.iter("sec"):
        t = sec.find("title")
        if t is None or not CLINICAL_SECS.match(text(t)):
            continue
        for e in sec.iter():
            if e.tag == "p" and id(e) not in table_ids and id(e) not in seen:
                seen.add(id(e))
                clinical.extend(sentences(text(e)))
    numeric = [s for s in clinical if NUMBER.search(s)]
    age_num = [s for s in clinical if AGE_NUMBER.search(s)]
    age_words = [s for s in clinical if AGE_WORDS.search(s)]
    pmids = {x.text.strip() for x in root.iter("pub-id") if x.get("pub-id-type") == "pmid" and x.text}
    counts = {
        "nxml_bytes": path.stat().st_size,
        "feature_tables": len(tables),
        "feature_table_rows": sum(t["rows"] for t in tables),
        "feature_table_numeric_rows": sum(t["numeric_rows"] for t in tables),
        "clinical_sentences": len(clinical),
        "clinical_numeric_sentences": len(numeric),
        "age_numeric_sentences": len(age_num),
        "age_qualitative_sentences": len(age_words),
        "cited_pmids": len(pmids),
        "cited_pmids_r1_heldout": len(pmids & heldout),
        "cited_pmids_litpanel_sources": len(pmids & panel),
    }
    snippets = {
        "tables": snip_tables,
        "numeric": numeric[:25],
        "age_numeric": age_num[:12],
        "age_words": age_words[:6],
    }
    return counts, snippets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--genes", type=Path, required=True)
    ap.add_argument("--chapters", type=Path, required=True)
    ap.add_argument("--archive-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--snippets", type=Path, required=True)
    args = ap.parse_args()

    with args.genes.open(encoding="utf-8") as h:
        rows = [r for r in csv.DictReader(h, delimiter="\t") if r["role"] == "construction"]
    frame = sorted({s for r in rows for s in r["gr_usable"].split(";") if s})
    in_archive = [s for s in frame if (args.archive_dir / f"{s}.nxml").is_file()]
    sample = sorted(random.Random(SEED).sample(in_archive, SIZE))
    with args.chapters.open(encoding="utf-8") as h:
        meta = {r["shortname"]: r for r in csv.DictReader(h, delimiter="\t")}

    heldout = {
        x.strip().removeprefix("PMID:")
        for x in (DATA_DIR / "splits/r1-v1.heldout-pmids.txt").open()
        if x.strip()
    }
    panel = set()
    with (DATA_DIR / "realism/extraction/curated.tsv").open(encoding="utf-8") as h:
        for r in csv.DictReader(h, delimiter="\t"):
            panel |= set(re.findall(r"PMID:?\s?(\d+)", r["citation"]))

    out, snippets = [], {}
    for s in sample:
        counts, snip = screen(args.archive_dir / f"{s}.nxml", heldout, panel)
        out.append(
            {
                "shortname": s,
                "nbk": meta[s]["nbk"],
                "title": meta[s]["title"],
                "n_genes": meta[s]["n_genes"],
                **counts,
            }
        )
        snippets[s] = snip
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "gr_sample30.auto.tsv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=list(out[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    frame_info = {
        "seed": SEED,
        "size": SIZE,
        "frame_chapters": len(frame),
        "frame_in_archive": len(in_archive),
        "sample": sample,
    }
    (args.out / "gr_sample30.frame.json").write_text(
        json.dumps(frame_info, indent=1) + "\n", encoding="utf-8"
    )
    args.snippets.write_text(json.dumps(snippets, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(frame_info, indent=1))


if __name__ == "__main__":
    main()
