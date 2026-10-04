"""Literature-onset counts of `s3-data-v3b` per split part (ADR-0015 addendum). Counts only.

The sealed test part is not loaded: only the frozen split's case ids, the literature-case id list and the
export's `onset_years` and `gene` fields are aggregated, and nothing per case is printed.

Usage: PYTHONPATH=src .venv/bin/python scripts/s3_v3b_literature_report.py
"""

import gzip
import json

from diagnostic_ar_training import INTERIM_DIR, SPLITS_DIR

DATA = INTERIM_DIR / "datasets" / "s3-data-v3b"
lit = set((DATA / "literature-onset-cases.txt").read_text().split())
split = json.loads((SPLITS_DIR / "s3-v3b.json").read_text())
part_of = {i: p for p, ids in split["case_ids"].items() for i in ids}
export = next(DATA.glob("*.jsonl.gz"))
stats = {
    p: {"cases": 0, "literature": 0, "literature_onset_reported": 0, "genes": set()}
    for p in split["case_ids"]
}
with gzip.open(export, "rt", encoding="utf-8") as handle:
    for line in handle:
        r = json.loads(line)
        s = stats[part_of[f"s3-v3b:{r['case_id']}"]]
        s["cases"] += 1
        if r["case_id"] in lit:
            s["literature"] += 1
            s["literature_onset_reported"] += r["onset_years"] is not None
            s["genes"].add(r["gene"])
total = {k: sum(s[k] for s in stats.values()) for k in ("cases", "literature", "literature_onset_reported")}
report = {
    "overall": {
        **total,
        "literature_share": round(total["literature"] / total["cases"], 4),
        "onset_reported_share_among_literature": round(
            total["literature_onset_reported"] / total["literature"], 4
        ),
    },
    "parts": {
        p: {
            "cases": s["cases"],
            "literature": s["literature"],
            "literature_share": round(s["literature"] / s["cases"], 4),
            "genes_with_a_literature_case": len(s["genes"]),
            "literature_onset_reported": s["literature_onset_reported"],
        }
        for p, s in stats.items()
    },
}
print(json.dumps(report, indent=1))
(DATA / "literature-report.json").write_text(json.dumps(report, indent=1) + "\n")
