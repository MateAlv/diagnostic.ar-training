"""Figure (i): EXP-Q-001 L4 on sealed S3-v2-test: primary Delta vs E0-initial by strategy, paired differences, noise run."""

from common import DARK, INK, LIGHT, MID, load, plt, save, save_data

SRC = "results/EXP-Q-001/sealed-analysis.json"


def forest(ax, items, title, xlabel):
    n = len(items)
    for i, (label, d, colour, marker) in enumerate(items):
        y = n - 1 - i
        ax.errorbar(
            d["delta"],
            y,
            xerr=[[d["delta"] - d["ci95"][0]], [d["ci95"][1] - d["delta"]]],
            fmt=marker,
            color=colour,
            capsize=3.5,
            ms=6.5,
            lw=1.4,
        )
        ax.annotate(
            f"{d['delta']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]",
            (d["delta"], y),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7,
        )
    ax.set_yticks(range(n))
    ax.set_yticklabels([x[0] for x in items][::-1])
    ax.set_ylim(-0.6, n - 0.3)
    ax.set_title(title, loc="left", fontsize=10)
    ax.set_xlabel(xlabel)


def main() -> None:
    d = load(SRC)
    prim = [
        ("Q0 (S3 v1 questioner)", d["Q0"]["primary"], LIGHT, "o"),
        ("Q1 (production agent selector)", d["Q1"]["primary"], MID, "s"),
        ("Q2b lambda 0.6", d["Q2b"]["primary"], DARK, "D"),
        ("Q0, 5% answer noise", d["Q0-noise"]["primary"], LIGHT, "o"),
        ("Q2b lambda 0.6, 5% noise", d["Q2b-noise"]["primary"], DARK, "D"),
    ]
    paired = [
        ("P1 (gated): Q2b - Q0", d["P1"]["paired_Q2b_minus_Q0"], DARK, "D"),
        ("S1: Q2b - Q1", d["S1"]["paired_Q2b_minus_Q1"], MID, "s"),
        ("S2 (5% noise): Q2b - Q0", d["S2"]["paired_Q2b_minus_Q0_noise0.05"], LIGHT, "o"),
    ]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14, 4.2), gridspec_kw={"width_ratios": [1.2, 1, 0.8]})
    forest(
        ax1,
        prim,
        "Primary: Delta MRR vs E0-initial",
        "Delta MRR (interview + F re-ranker), 95% CI over genes",
    )
    ax1.axvline(0, color="#333333", lw=0.9)
    forest(ax2, paired, "Paired differences in final MRR", "Delta MRR, 95% CI over genes")
    ax2.axvline(0, color="#333333", lw=0.9)

    names = ["Q0", "Q1", "Q2b"]
    vals = [d[k]["reranker_effect"]["harmed"] * 100 for k in names]
    bars = ax3.bar(names, vals, color=[LIGHT, MID, DARK], edgecolor=INK)
    bars[1].set_hatch("//")
    for b, v in zip(bars, vals):
        ax3.annotate(
            f"{v:.2f}%",
            (b.get_x() + b.get_width() / 2, 0.3),
            ha="center",
            fontsize=8,
            bbox={"fc": "white", "ec": "none", "pad": 1.5},
        )
    ax3.axhline(5, color=INK, ls="--", lw=0.9)
    ax3.text(2.45, 5.1, "5% cap", fontsize=7.5, ha="right")
    ax3.set_ylim(0, 7)
    ax3.set_ylabel("re-ranker effect, harmed share (%)")
    ax3.set_title("Re-ranker harm by strategy", loc="left", fontsize=10)
    fig.suptitle(
        f"EXP-Q-001 on sealed S3-v2-test (n = {d['n']:,}, re-ranker F, budget 9). "
        "P1 is pre-registered and gated; S1 and S2 are reported only",
        x=0.01,
        ha="left",
        fontsize=10.5,
    )
    save(fig, "fig_i_l4_strategies", [SRC])
    out = {
        "n": d["n"],
        "primary": {
            x[0]: {"delta": x[1]["delta"], "ci95": x[1]["ci95"], "harmed": x[1]["harmed"]} for x in prim
        },
        "paired": {x[0]: {"delta": x[1]["delta"], "ci95": x[1]["ci95"]} for x in paired},
        "reranker_harmed": dict(zip(names, [v / 100 for v in vals])),
        "P1_pass": d["P1"]["pass"],
    }
    save_data("fig_i_l4_strategies.json", out)


if __name__ == "__main__":
    main()
