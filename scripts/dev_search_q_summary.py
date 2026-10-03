"""Table and selection of the EXP-Q-001 dev search (L4) from its log.

Usage: python scripts/dev_search_q_summary.py [noise]
Selection rule: max primary Δ among strategies with re-ranker-effect harmed <= 5% and primary CI lower bound > 0;
a tie within 0.001 goes to the simpler strategy, Q0 < Q1 < Q2 < Q2b. Prints markdown, changes nothing.
"""

import csv
import sys

from diagnostic_ar_training import RESULTS_DIR

SIMPLE = {"Q0": 0, "Q1": 1, "Q2": 2, "Q2b": 3}


def read(path) -> list[dict]:
    lines = [line for line in path.read_text().splitlines() if not line.startswith("#")]
    return list(csv.DictReader(lines, delimiter="\t"))


def f(r, k) -> float:
    return float(r[k])


def paired_vs_q0(strategy: str, reranker: str, noise: float, label: str = "dev") -> dict:
    import json

    from diagnostic_ar_training.eval import harness, question_run

    def final(name):
        path = (
            RESULTS_DIR
            / "EXP-Q-001"
            / label
            / f"s3-v2-dev__{name}__{reranker}__noise{noise:g}.interviews.jsonl"
        )
        return [json.loads(line) for line in path.read_text().splitlines()]

    a, b = final("Q0"), final(strategy)
    return harness.compare(question_run.records(a, "rank_final"), question_run.records(b, "rank_final"))


def main(noise: float) -> None:
    rows = [r for r in read(RESULTS_DIR / "EXP-Q-001" / "dev-search.tsv") if f(r, "noise") == noise]
    print(f"noise {noise:g}: {len(rows)} runs\n")
    print(
        "| strategy | hash | MRR initial | MRR +answers | MRR final | primary Δ vs E0-initial [95% CI] | harmed | helped "
        "| questioner effect | re-ranker effect [CI] | rr harmed | top-10 initial → final | yes/no per case |"
    )
    print("|" + "---|" * 13)
    for r in rows:
        print(
            f"| {r['strategy']} | {r['config_hash']} | {f(r, 'mrr_initial'):.4f} | {f(r, 'mrr_answers'):.4f} | "
            f"{f(r, 'mrr_final'):.4f} | {f(r, 'delta_primary'):+.4f} [{f(r, 'ci_lo'):+.4f}, {f(r, 'ci_hi'):+.4f}] | "
            f"{f(r, 'harmed_primary'):.3f} | {f(r, 'helped_primary'):.3f} | {f(r, 'questioner_delta'):+.4f} "
            f"[{f(r, 'questioner_ci_lo'):+.4f}, {f(r, 'questioner_ci_hi'):+.4f}] | {f(r, 'reranker_delta'):+.4f} "
            f"[{f(r, 'reranker_ci_lo'):+.4f}, {f(r, 'reranker_ci_hi'):+.4f}] | {f(r, 'reranker_harmed'):.3f} | "
            f"{f(r, 'top10_initial'):.3f} → {f(r, 'top10_final'):.3f} | {f(r, 'yes_per_case'):.2f} / {f(r, 'no_per_case'):.2f} |"
        )
    ok = [r for r in rows if f(r, "reranker_harmed") <= 0.05 and f(r, "ci_lo") > 0]
    print(
        "\nSelection (re-ranker-effect harmed <= 5%, primary CI lower bound > 0, ties within 0.001 -> simpler):"
    )
    if not ok:
        print("- no strategy satisfies the rule")
        return
    best = max(f(r, "delta_primary") for r in ok)
    near = [r for r in ok if f(r, "delta_primary") >= best - 0.001]
    pick = min(near, key=lambda r: (SIMPLE[r["strategy"].split("-")[0]], -f(r, "delta_primary")))
    print(
        f"- feasible: {[r['strategy'] for r in ok]}; best Δ {best:+.4f}; within 0.001: {[r['strategy'] for r in near]}"
    )
    print(f"- winner: {pick['strategy']} ({pick['config_hash']}), primary Δ {f(pick, 'delta_primary'):+.4f}")
    print("\nPaired difference in final MRR vs Q0 (same cases, 95% CI over genes):")
    for r in rows:
        if r["strategy"] != "Q0":
            d = paired_vs_q0(r["strategy"], r["reranker"], noise, "dev" if noise == 0 else "noise")
            print(f"- {r['strategy']}: {d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]")
    excluded = [(r["strategy"], f(r, "reranker_harmed")) for r in rows if r not in ok]
    print(f"- not feasible: {excluded}")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 0.0)
