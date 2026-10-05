"""Figure (j): EXP-B-004 descriptive sealed table on S3-v2-test as a forest plot (Delta vs E0+answers, harmed, Delta vs F)."""

from common import DARK, INK, LIGHT, MID, load, plt, save, save_data

SRC = "results/EXP-B-004/sealed-analysis.json"
SYSTEMS = [
    ("F", "F (8ecd5b320f33)", INK, "D"),
    ("rr-v1 formula on kb-v6", "rr-v1 formula, kb-v6 (2b6a00674f4c)", LIGHT, "o"),
    ("F on kb-v7", "F on kb-v7 (af6da5cdbf19)", LIGHT, "o"),
    ("F + onset 0.5", "F + onset 0.5 (458768f1bca4)", DARK, "s"),
    ("F + sex 0.5", "F + sex 0.5 (96e69f9e62fa)", MID, "^"),
    ("F + age_mean 0.5", "F + age_mean 0.5 (5b30ab00d1a0)", MID, "v"),
    ("frontier <=7.5% (propagated k0.8 w0.75)", "frontier 7.5% (c34cb31bd53f)", LIGHT, "P"),
    ("frontier <=10% (capped C2 w2)", "frontier 10% (84296576dc8e)", LIGHT, "X"),
]


def main() -> None:
    d = load(SRC)
    n = len(SYSTEMS)
    fig, axes = plt.subplots(
        1, 3, figsize=(14, 4.4), sharey=True, gridspec_kw={"width_ratios": [1.2, 0.8, 1]}
    )
    out = {"n": d["n"], "systems": {}}
    for i, (key, label, colour, marker) in enumerate(SYSTEMS):
        y = n - 1 - i
        s = d[key]
        e0, vf = s["vs_E0+answers"], s["vs_F"]
        axes[0].errorbar(
            e0["delta"],
            y,
            xerr=[[e0["delta"] - e0["ci95"][0]], [e0["ci95"][1] - e0["delta"]]],
            fmt=marker,
            color=colour,
            capsize=3,
            ms=6,
            lw=1.3,
        )
        axes[0].annotate(
            f"{e0['delta']:+.4f}", (e0["ci95"][1], y), textcoords="offset points", xytext=(4, -3), fontsize=7
        )
        axes[1].plot(e0["harmed"] * 100, y, marker, color=colour, ms=6.5)
        axes[1].annotate(
            f"{e0['harmed'] * 100:.2f}%",
            (e0["harmed"] * 100, y),
            textcoords="offset points",
            xytext=(6, -3),
            fontsize=7,
        )
        if key != "F":
            axes[2].errorbar(
                vf["delta"],
                y,
                xerr=[[vf["delta"] - vf["ci95"][0]], [vf["ci95"][1] - vf["delta"]]],
                fmt=marker,
                color=colour,
                capsize=3,
                ms=6,
                lw=1.3,
            )
            axes[2].annotate(
                f"{vf['delta']:+.4f}",
                (vf["ci95"][1], y),
                textcoords="offset points",
                xytext=(4, -3),
                fontsize=7,
            )
        out["systems"][key] = {
            "config": s["config"],
            "delta_vs_e0_answers": e0["delta"],
            "ci95": e0["ci95"],
            "harmed": e0["harmed"],
            "helped": e0["helped"],
            "delta_vs_F": None if key == "F" else vf["delta"],
            "delta_vs_F_ci95": None if key == "F" else vf["ci95"],
            "mrr_final": s["mrr_final"],
        }
    axes[0].set_yticks(range(n))
    axes[0].set_yticklabels([x[1] for x in SYSTEMS][::-1])
    axes[0].set_ylim(-0.6, n - 0.4)
    axes[0].axvline(0, color="#333333", lw=0.9)
    axes[0].set_xlabel("Delta MRR vs E0+answers, 95% CI over genes")
    axes[0].set_title("Delta vs E0+answers", loc="left", fontsize=10)
    axes[1].axvline(5, color=INK, ls="--", lw=0.9)
    axes[1].text(5.05, n - 0.55, "5%", fontsize=7.5)
    axes[1].set_xlim(0, 11.5)
    axes[1].set_xlabel("harmed share vs E0+answers (%)")
    axes[1].set_title("Harmed", loc="left", fontsize=10)
    axes[2].axvline(0, color="#333333", lw=0.9)
    axes[2].set_xlabel("paired Delta MRR vs F, 95% CI over genes")
    axes[2].set_title("Delta vs F", loc="left", fontsize=10)
    fig.suptitle(
        f"EXP-B-004 sealed S3-v2-test (n = {d['n']:,}, interview Q0, budget 9): descriptive, nothing gated or selected",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    save(fig, "fig_j_expb004_forest", [SRC])
    save_data("fig_j_expb004_forest.json", out)


if __name__ == "__main__":
    main()
