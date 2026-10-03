"""Split EXP-B-004's shared dev-search log into per-stage rows files and amend the stage manifests.

The first stage manifests (l1a to l3) listed the shared `dev-search.tsv` as an output; it grows with every
stage, so their hashes stopped matching. Each stage's rows are now their own file (`<stage>.log-rows.tsv`,
written by `dxt s3 dev-score` from here on). This one-off script creates the files for the five stages
already run, checks that the shared log is exactly their concatenation, and replaces the log in each of
those manifests with the stage's rows file, noting the amendment.

Usage: python scripts/dev_search_stage_rows.py
"""

import csv
import json
import sys

from diagnostic_ar_training import MANIFESTS_DIR, RESULTS_DIR
from diagnostic_ar_training.eval import dev_search
from diagnostic_ar_training.lineage.hashing import sha256_file

STAGES = ("l1a", "l1b", "l1c", "l2", "l3")
NOTE = (
    "Amended 2026-10-03: the shared results/EXP-B-004/dev-search.tsv, which grows with each stage, is replaced "
    "by this stage's rows file; the shared log is the header plus the stage rows files in order."
)


def main() -> int:
    base = RESULTS_DIR / "EXP-B-004"
    directory = base / "dev-search"
    log = base / "dev-search.tsv"
    lines = [x for x in log.read_text().splitlines() if not x.startswith("#")]
    rows = list(csv.DictReader(lines, delimiter="\t"))
    used = 0
    files = []
    for stage in STAGES:
        ids = {d["arm_id"] for d in json.loads((directory / f"arms-{stage}.json").read_text())}
        if stage == "l1a":
            ids.add("ref-rr-v1")
        mine = [r for r in rows if r["arm_id"] in ids]
        if rows[used : used + len(mine)] != mine:
            print(f"{stage}: its rows are not the next rows of the log", file=sys.stderr)
            return 1
        used += len(mine)
        path = directory / f"{stage}.log-rows.tsv"
        dev_search.write_stage_rows(path, mine)
        files.append(path)
        manifest_path = MANIFESTS_DIR / f"results-EXP-B-004-dev-{stage}.json"
        manifest = json.loads(manifest_path.read_text())
        outputs = [o for o in manifest["outputs"] if not o["path"].endswith("dev-search.tsv")]
        outputs.append(
            {
                "path": str(path.relative_to(path.parents[3])),
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
        manifest["outputs"] = outputs
        manifest["notes"] = (manifest.get("notes") or "") + NOTE
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"{stage}: {len(mine)} rows")
    ok = used == len(rows) and dev_search.log_equals_stage_rows(log, files)
    print("shared log equals the concatenation of the stage files:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
