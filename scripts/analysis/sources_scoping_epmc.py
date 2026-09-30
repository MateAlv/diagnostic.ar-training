"""SOURCES-SCOPING-001: Europe PMC open-access cohort papers per gene (counts and metadata only).

Draws a seeded stratified sample of simulable construction genes (GeneReviews
chapter usable: yes/no x weak profile: yes/no, 50 each) and also queries every
evaluation gene, reported separately. Three queries per gene, all OPEN_ACCESS:y:
- broad: the gene symbol anywhere AND a cohort keyword anywhere;
- ta: the symbol in title or abstract AND a cohort keyword in title or abstract;
- title: the symbol in the title AND a cohort keyword in title or abstract (the estimate).
For "title" it keeps up to 100 hits' metadata (PMID, PMCID, licence, publication
types, year, title) to count licences and PMIDs that are R1 held-out, cited
in phenotype.hpoa, or literature-panel sources. No full text is fetched.

Usage: python scripts/analysis/sources_scoping_epmc.py --genes GENES_TSV --out DIR
"""

import argparse
import csv
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from diagnostic_ar_training import DATA_DIR
from diagnostic_ar_training.lineage.registry import Purpose, open_source

SEED = 20260930
PER_STRATUM = 50
KEYWORDS = '(cohort OR "case series" OR "clinical spectrum" OR "phenotypic spectrum")'
API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def queries(symbol: str) -> dict[str, str]:
    s = f'"{symbol}"'
    return {
        "broad": f"{s} AND {KEYWORDS} AND OPEN_ACCESS:y",
        "ta": f"(TITLE:{s} OR ABSTRACT:{s}) AND (TITLE:{KEYWORDS} OR ABSTRACT:{KEYWORDS}) AND OPEN_ACCESS:y",
        "title": f"TITLE:{s} AND (TITLE:{KEYWORDS} OR ABSTRACT:{KEYWORDS}) AND OPEN_ACCESS:y",
    }


def search(query: str, core: bool) -> dict:
    params = {
        "query": query,
        "format": "json",
        "resultType": "core" if core else "lite",
        "pageSize": 100 if core else 1,
    }
    url = f"{API}?{urllib.parse.urlencode(params)}"
    for attempt in range(8):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(min(60, 5 * 2**attempt))
    raise RuntimeError(f"Europe PMC unreachable for {query}")


def stratum(row: dict) -> str:
    gr = "gr" if row["gr_usable"] else "nogr"
    weak = "ok" if row["weakness"] == "ok_counts" else "weak"
    return f"{gr}_{weak}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--genes", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    with args.genes.open(encoding="utf-8") as h:
        rows = list(csv.DictReader(h, delimiter="\t"))
    construction = [r for r in rows if r["role"] == "construction" and r["simulable"] == "True"]
    strata: dict[str, list[dict]] = {}
    for r in construction:
        strata.setdefault(stratum(r), []).append(r)
    rng = random.Random(SEED)
    picked = []
    for name in sorted(strata):
        pool = sorted(strata[name], key=lambda r: r["gene"])
        picked += [(r, name) for r in rng.sample(pool, min(PER_STRATUM, len(pool)))]
    picked += [(r, "evaluation") for r in rows if r["role"] == "evaluation"]

    heldout = {
        x.strip().removeprefix("PMID:")
        for x in (DATA_DIR / "splits/r1-v1.heldout-pmids.txt").open()
        if x.strip()
    }
    in_hpoa = set()
    with open_source("hpo_annotations", Purpose.KB).open(encoding="utf-8") as h:
        for line in h:
            if not line.startswith("#"):
                in_hpoa.update(re.findall(r"PMID:(\d+)", line))
    panel = set()
    with (DATA_DIR / "realism/extraction/curated.tsv").open(encoding="utf-8") as h:
        for r in csv.DictReader(h, delimiter="\t"):
            panel |= set(re.findall(r"PMID:?\s?(\d+)", r["citation"]))

    args.out.mkdir(parents=True, exist_ok=True)
    per_gene, hits = [], []
    for row, name in picked:
        symbol = row["symbol"] or row["gene"]
        qs = queries(symbol)
        counts = {k: search(q, core=False)["hitCount"] for k, q in qs.items() if k != "title"}
        result = search(qs["title"], core=True)
        counts["title"] = result["hitCount"]
        got = result.get("resultList", {}).get("result", [])
        licences = Counter((x.get("license") or "none").lower() for x in got)
        pmids = {x["pmid"] for x in got if x.get("pmid")}
        per_gene.append(
            {
                "gene": row["gene"],
                "symbol": symbol,
                "stratum": name,
                "weakness": row["weakness"],
                "gr_usable": bool(row["gr_usable"]),
                "hits_broad": counts["broad"],
                "hits_ta": counts["ta"],
                "hits_title": counts["title"],
                "retrieved": len(got),
                "retrieved_r1_heldout": len(pmids & heldout),
                "retrieved_in_hpoa": len(pmids & in_hpoa),
                "retrieved_litpanel_source": len(pmids & panel),
                "licences": json.dumps(dict(licences), sort_keys=True),
            }
        )
        for x in got:
            pmid = x.get("pmid", "")
            types = (x.get("pubTypeList") or {}).get("pubType", [])
            hits.append(
                {
                    "gene": row["gene"],
                    "stratum": name,
                    "pmid": pmid,
                    "pmcid": x.get("pmcid", ""),
                    "licence": (x.get("license") or "none").lower(),
                    "year": x.get("pubYear", ""),
                    "case_report": any("case" in t.lower() and "report" in t.lower() for t in types),
                    "review": any("review" in t.lower() for t in types),
                    "r1_heldout": pmid in heldout,
                    "in_hpoa": pmid in in_hpoa,
                    "litpanel_source": pmid in panel,
                    "title": re.sub(r"\s+", " ", x.get("title", "")).strip(),
                }
            )
        time.sleep(0.2)

    for name, data in (("epmc_genes.tsv", per_gene), ("epmc_hits.tsv", hits)):
        with (args.out / name).open("w", encoding="utf-8", newline="") as h:
            w = csv.DictWriter(h, fieldnames=list(data[0]), delimiter="\t", lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    frame = {
        "seed": SEED,
        "per_stratum": PER_STRATUM,
        "strata_sizes": {k: len(v) for k, v in sorted(strata.items())},
        "queries": queries("{SYMBOL}"),
        "retrieved_per_gene_cap": 100,
        "run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (args.out / "epmc_frame.json").write_text(json.dumps(frame, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(frame, indent=1))


if __name__ == "__main__":
    main()
