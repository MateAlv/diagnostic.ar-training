"""Paired Δ MRR between two logged arms of one stage, from its per-case ranks file.

Usage: python scripts/dev_search_paired.py <stage> <arm-a> <arm-b> [exp-id]   (prints b - a)
Reads results/<exp>/dev-search/<stage>.ranks.tsv.gz; changes nothing.
"""

import csv
import gzip
import sys

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.eval import dev_search


def main(stage: str, a: str, b: str, exp: str) -> None:
    with gzip.open(RESULTS_DIR / exp / "dev-search" / f"{stage}.ranks.tsv.gz", "rt") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    ids = [r["case_id"] for r in rows]
    genes = [r["gene"] for r in rows]
    ra = dev_search.records(ids, genes, [float(r[a]) for r in rows])
    rb = dev_search.records(ids, genes, [float(r[b]) for r in rows])
    d = dev_search.compare(ra, rb)
    print(
        f"{b} - {a}: {d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}] "
        f"harmed {d['harmed']:.3f} helped {d['helped']:.3f} n={d['n']}"
    )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "EXP-B-004")
