"""Tables from the EXP-B-004 dev-search log: the frontier, the selection rule's winner and a lever's rows.

Usage: python scripts/dev_search_summary.py L1|L2|L3 [exp-id]
Reads results/<exp>/dev-search.tsv and the arms files; prints markdown, changes nothing.
"""

import json
import sys

from diagnostic_ar_training import RESULTS_DIR
from diagnostic_ar_training.eval import dev_search

COLUMNS = (
    "arm_id",
    "config_hash",
    "delta_mrr",
    "ci",
    "harmed",
    "helped",
    "r1dev_delta",
    "r1dev_ci",
    "r1_pass",
)


def arms_of(directory) -> dict:
    out = {}
    for path in sorted(directory.glob("arms-*.json")):
        for d in json.loads(path.read_text()):
            arm = dev_search.Arm.from_dict(d)
            out.setdefault(arm.arm_id, arm)
    return out


def table(rows: list[dict]) -> str:
    lines = [
        "| arm | hash | Δ MRR | 95% CI | harmed | helped | R1-dev Δ | R1-dev CI | R1 pass |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['arm_id']} | {r['config_hash']} | {r['delta_mrr']:+.4f} | "
            f"[{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] | {r['harmed']:.3f} | {r['helped']:.3f} | "
            f"{r['r1dev_delta']:+.4f} | [{r['r1dev_ci_lo']:+.4f}, {r['r1dev_ci_hi']:+.4f}] | {r['r1_pass']} |"
        )
    return "\n".join(lines)


def main(lever: str, exp: str) -> None:
    base = RESULTS_DIR / exp
    rows = dev_search.read_log(base / "dev-search.tsv")
    arms = arms_of(base / "dev-search")
    mine = [r for r in rows if r["lever"] == lever]
    print(f"{lever}: {len(mine)} configurations logged (budget {dict(L1=48, L2=6, L3=12)[lever]})\n")
    print(table(mine))
    print("\nFrontier (best Δ at each harm limit, over this lever's arms):")
    for limit, r in dev_search.frontier(mine).items():
        print(
            f"- harmed <= {limit:.3f}: "
            + (
                f"{r['arm_id']} Δ {r['delta']:+.4f} [{r['ci_lo']:+.4f}, {r['ci_hi']:+.4f}] harmed {r['harmed']:.3f}, "
                f"CI lower bound > 0: {r['ci_lo'] > 0}, R1-dev pass: {bool(r['r1_pass'])}"
                if r
                else "no arm"
            )
        )
    winner = dev_search.select(mine, arms)
    print(
        "\nSelection rule (harmed <= 5%, CI lower bound > 0, R1-dev no-harm, ties within 0.001 -> simpler):"
    )
    print(
        f"- winner: {winner['arm_id'] + ' ' + arms[winner['arm_id']].config.config_hash if winner else 'none'}"
    )
    if winner:
        near = [
            r["arm_id"]
            for r in mine
            if dev_search.feasible(r) and r["delta"] >= winner["delta"] - dev_search.TIE and r is not winner
        ]
        print(
            f"- feasible arms within 0.001 of the best Δ, passed over for the simpler winner: {near or 'none'}"
        )


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "EXP-B-004")
