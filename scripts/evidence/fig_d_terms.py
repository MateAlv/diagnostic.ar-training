"""Figure (d): present terms per case, R1-train vs candidate 6 vs UP vs V03-full, from the g2c blocks of results/realism reports."""

from common import DARK, INK, LIGHT, MID, load, plt, save, save_data

FILES = {
    "UP": "results/realism/up-graphens.json",
    "V03-full": "results/realism/v0.3-full-baseline.json",
    "Candidate 6": "results/realism/v0.5.4-cand6.json",
}
PCTS = ["10", "25", "50", "75", "90"]


def main() -> None:
    g = {k: load(v)["g2c_terms_per_case"]["present"] for k, v in FILES.items()}
    series = {"R1-train": g["Candidate 6"]["r1_train"]}
    for k in FILES:
        series[k] = g[k]["sim"]
    w1 = {k: g[k]["w1_vs_r1_train"] for k in FILES}
    style = {
        "R1-train": (INK, "o", "-"),
        "UP": (LIGHT, "s", "--"),
        "V03-full": (MID, "^", ":"),
        "Candidate 6": (DARK, "D", "-."),
    }
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.8), gridspec_kw={"width_ratios": [1.4, 1]})
    out = {}
    for k, s in series.items():
        c, mk, ls = style[k]
        y = [s["percentiles"][p] for p in PCTS]
        ax1.plot(
            [int(p) for p in PCTS],
            y,
            color=c,
            marker=mk,
            ls=ls,
            mec=INK,
            ms=6,
            lw=1.6,
            label=f"{k} (mean {s['mean']:.2f}, n={s['n']:,})",
        )
        out[k] = {
            "mean": s["mean"],
            "n": s["n"],
            "percentiles": s["percentiles"],
            "w1_vs_r1_train": w1.get(k),
        }
    ax1.set_xticks([int(p) for p in PCTS])
    ax1.set_xlabel("percentile of cases")
    ax1.set_ylabel("present terms per case")
    ax1.legend(frameon=False, fontsize=8)
    ax1.set_title("Percentiles of terms per case", loc="left", fontsize=10)
    names = list(FILES)
    colours = {"UP": LIGHT, "V03-full": MID, "Candidate 6": DARK}
    bars = ax2.bar(
        names, [w1[n] for n in names], color=[colours[n] for n in names], edgecolor=INK, hatch=None
    )
    bars[0].set_hatch("//")
    bars[1].set_hatch("..")
    for b in bars:
        ax2.annotate(
            f"{b.get_height():.3f}",
            (b.get_x() + b.get_width() / 2, b.get_height()),
            textcoords="offset points",
            xytext=(0, 2),
            ha="center",
            fontsize=8,
        )
    ax2.set_ylabel("Wasserstein-1 vs R1-train (G2c, lower is better)")
    ax2.set_title("G2c", loc="left", fontsize=10)
    fig.suptitle("Present terms per case (the G2c view)", x=0.01, ha="left", fontsize=11)
    save(fig, "fig_d_terms_per_case", list(FILES.values()))
    save_data("fig_d_terms_per_case.json", out)


if __name__ == "__main__":
    main()
