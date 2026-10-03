"""Subset tables of one dev-search stage: Δ MRR per arm on chosen subsets, vs E0+answers and paired.

Usage: python scripts/dev_search_subsets.py <stage> <subset,subset,...> [paired-arm-id] [exp-id]
Reads results/<exp>/dev-search/<stage>.report.json; prints markdown, changes nothing.
"""

import json
import sys

from diagnostic_ar_training import RESULTS_DIR


def cell(d: dict) -> str:
    if not d["n"]:
        return "n/a"
    return f"{d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]"


def main(stage: str, subsets: list[str], paired: str, exp: str) -> None:
    report = json.loads((RESULTS_DIR / exp / "dev-search" / f"{stage}.report.json").read_text())
    print(
        f"{stage}: {report['cases']} cases; subset sizes "
        + ", ".join(f"{s}={report['subset_sizes'][s]}" for s in subsets)
    )
    head = "| arm | " + " | ".join(f"{s} vs E0+answers" for s in subsets)
    if paired:
        head += " | " + " | ".join(f"{s} vs {paired}" for s in subsets)
    print("\n" + head + " |\n|" + "---|" * (1 + len(subsets) * (2 if paired else 1)))
    for arm_id, a in report["arms"].items():
        cells = [cell(a["vs_e0_answers"][s]) for s in subsets]
        if paired:
            cells += [cell(a["paired"][paired][s]) if paired in a["paired"] else "n/a" for s in subsets]
        print(f"| {arm_id} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main(
        sys.argv[1],
        sys.argv[2].split(","),
        sys.argv[3] if len(sys.argv) > 3 else "",
        sys.argv[4] if len(sys.argv) > 4 else "EXP-B-004",
    )
