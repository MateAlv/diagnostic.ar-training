"""Figure (g): Front A retraining, R1-dev Delta MRR vs E0 for every run of EXP-A-001, A-002f and A-003f (results/*/report.json).

Headline view per experiment: A-001 present-only; A-002f "+excluded" (negation); A-003f "all" (sex + age + onset).
"""

from common import DARK, INK, MID, load, plt, save, save_data

EXPS = [
    (
        "EXP-A-001",
        "results/EXP-A-001/report.json",
        None,
        "A-001: simulator positives only (present view)",
        DARK,
        "o",
    ),
    (
        "EXP-A-002f",
        "results/EXP-A-002f/report.json",
        "excluded",
        "A-002f: negation into frozen v3.0 (+excluded view)",
        MID,
        "s",
    ),
    (
        "EXP-A-003f",
        "results/EXP-A-003f/report.json",
        "all",
        "A-003f: sex, age, onset into frozen v3.0 (all view)",
        INK,
        "^",
    ),
]


def r1(run: dict, view):
    d = run["r1_dev"]
    return d if view is None else d[view]


def main() -> None:
    fig, axes = plt.subplots(3, 1, figsize=(9, 9.2), sharex=True)
    out = {}
    for ax, (eid, rel, view, title, colour, marker) in zip(axes, EXPS):
        runs = load(rel)["runs"]
        rows = []
        for run in runs:
            if "pipeline-check" in run["run_id"]:
                continue
            d = r1(run, view)
            rows.append((run["run_id"], d["delta"], d["ci95"], d["harmed"]))
        out[eid] = [{"run": a, "delta": b, "ci95": c, "harmed": h} for a, b, c, h in rows]
        for i, (rid, delta, ci, harmed) in enumerate(rows):
            ax.errorbar(
                delta,
                i,
                xerr=[[delta - ci[0]], [ci[1] - delta]],
                fmt=marker,
                color=colour,
                mec=INK,
                capsize=3,
                ms=6,
                lw=1.4,
            )
        ax.axvline(0, color=INK, lw=1)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(
            [f"{r[0].split('-', 1)[1]}  (harmed {r[3] * 100:.0f}%)" for r in rows], fontsize=7.5
        )
        ax.invert_yaxis()
        ax.set_title(title, loc="left", fontsize=9.5)
    axes[-1].set_xlabel("R1-dev Delta MRR vs E0 (E0 = 0), paired publication-clustered 95% CI; n = 1,883")
    axes[0].set_xlim(-0.34, 0.03)
    fig.suptitle("Front A retraining: every run's change in R1-dev MRR", x=0.01, ha="left", fontsize=11)
    save(fig, "fig_g_frontA_r1dev", [e[1] for e in EXPS])
    save_data("fig_g_frontA_r1dev.json", out)


if __name__ == "__main__":
    main()
