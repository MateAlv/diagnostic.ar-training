"""Counts of the S3 v3 rich cases before they are deleted: onset source and sex.

Stops with exit status 1 unless every case drew its onset age from the literature (ADR-0015).

Usage: python scripts/s3_v3_rich_stats.py <cases.jsonl> <rich-stats.json>
"""

import json
import sys
from collections import Counter
from pathlib import Path


def main(cases: Path, out: Path) -> int:
    counts: Counter[str] = Counter()
    genes, n = set(), 0
    with cases.open(encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            n += 1
            genes.add(r["target"]["gene"])
            counts[r["metadata"]["onset_age_source"] or "none"] += 1
            counts[f"sex_{r['patient']['sex']}"] += 1
    stats = {"cases": n, "genes": len(genes), "counts": dict(sorted(counts.items()))}
    out.write_text(json.dumps(stats) + "\n")
    print(json.dumps(stats))
    return 0 if counts["literature"] == n else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
