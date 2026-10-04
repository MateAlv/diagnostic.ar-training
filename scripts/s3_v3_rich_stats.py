"""Counts of the S3 v3 rich cases before they are deleted: onset source and sex.

For S3 v3 (strict rule) it stops with exit status 1 unless every case drew its onset age from the
literature (ADR-0015). With a third argument, the ids of the literature-onset cases are written there, one per
line (S3 v3b, whose primary analysis is restricted to them), and the all-literature requirement is dropped.

Usage: python scripts/s3_v3_rich_stats.py <cases.jsonl> <rich-stats.json> [literature-case-ids.txt]
"""

import json
import sys
from collections import Counter
from pathlib import Path


def main(cases: Path, out: Path, ids_out: Path | None = None) -> int:
    counts: Counter[str] = Counter()
    genes, n, literature_ids = set(), 0, []
    with cases.open(encoding="utf-8") as handle:
        for line in handle:
            r = json.loads(line)
            n += 1
            genes.add(r["target"]["gene"])
            source = r["metadata"]["onset_age_source"] or "none"
            counts[source] += 1
            if source == "literature":
                literature_ids.append(r["case_id"])
            counts[f"sex_{r['patient']['sex']}"] += 1
    stats = {"cases": n, "genes": len(genes), "counts": dict(sorted(counts.items()))}
    out.write_text(json.dumps(stats) + "\n")
    print(json.dumps(stats))
    if ids_out is not None:
        ids_out.write_text("".join(f"{i}\n" for i in sorted(literature_ids)))
        return 0
    return 0 if counts["literature"] == n else 1


if __name__ == "__main__":
    sys.exit(main(*(Path(a) for a in sys.argv[1:4])))
