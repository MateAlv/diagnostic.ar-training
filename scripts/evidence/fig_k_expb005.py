"""Figure (k): EXP-B-005 on S3 v3b: dev choice of the onset weight, sealed P1, and the sealed secondary subsets."""

from common import DARK, INK, LIGHT, MID, load, plt, save, save_data

DEV = "results/EXP-B-005/dev-analysis.json"
SEALED = "results/EXP-B-005/sealed-analysis.json"
SUBSETS = [
    ("lit", "P1: literature onset (gated)"),
    ("all", "all cases"),
    ("known", "known onset, any source"),
    ("lit_known", "lit., onset known"),
    ("lit_unknown", "lit., onset unknown"),
    ("lit_src_hpoa", "lit., kb source hpoa"),
    ("lit_src_orphanet", "lit., kb source orphanet"),
    ("lit_src_orphanet_exact_alignment", "lit., kb source orphanet_exact_alignment"),
    ("lit_src_none", "lit., kb source none"),
]


def main() -> None:
    dev, sealed = load(DEV), load(SEALED)
    fig = plt.figure(figsize=(16, 4.8))
    gs = fig.add_gridspec(1, 3, width_ratios=[0.9, 0.7, 1.6])
    ax1, ax2, ax3 = (fig.add_subplot(g) for g in gs)
    out = {"dev": {}, "sealed": {}}

    for arm, a in dev["arms"].items():
        v, e = a["vs_F"]["lit"], a["vs_e0"]["lit"]
        h = e["harmed"] * 100
        sel = a["config_hash"] == dev["arms"][dev["selected"]]["config_hash"]
        colour = DARK if a["feasible"] else LIGHT
        ax1.errorbar(
            h,
            v["delta"],
            yerr=[[v["delta"] - v["ci95"][0]], [v["ci95"][1] - v["delta"]]],
            fmt="D" if sel else "o",
            color=colour,
            ms=7,
            capsize=3,
            lw=1.3,
        )
        ax1.annotate(
            f"w = {a['w']:g}", (h, v["delta"]), textcoords="offset points", xytext=(7, -3), fontsize=8
        )
        out["dev"][arm] = {
            "config": a["config_hash"],
            "w": a["w"],
            "delta_vs_F": v["delta"],
            "ci95": v["ci95"],
            "harmed_vs_e0": e["harmed"],
            "feasible": a["feasible"],
            "selected": sel,
            "r1dev_delta": a["r1dev"]["delta"],
            "r1dev_ci95": a["r1dev"]["ci95"],
            "n": v["n"],
        }
    ax1.axvline(5, color=INK, ls="--", lw=0.9)
    ax1.text(5.1, 0.02, "5% cap", transform=ax1.get_xaxis_transform(), fontsize=7.5, va="bottom")
    ax1.axhline(0, color="#333333", lw=0.9)
    ax1.set_xlabel("harmed share of F + onset vs E0+answers (%)")
    ax1.set_ylabel("Delta MRR vs F, 95% CI (genes)")
    ax1.set_title(
        f"Dev: weight choice (n = {dev['mask_sizes']['lit']:,} literature-onset)", loc="left", fontsize=10
    )
    ax1.plot([], [], "D", color=DARK, label="feasible, selected (w 0.25)", lw=0)
    ax1.plot([], [], "o", color=LIGHT, label="over the 5% cap", lw=0)
    ax1.legend(frameon=False, fontsize=7.5, loc="upper left")

    arm = sealed["arms"]["F+onset0.25"]
    p1 = sealed["P1"]["F+onset0.25"]
    ax2.errorbar(
        0,
        p1["delta"],
        yerr=[[p1["delta"] - p1["ci95"][0]], [p1["ci95"][1] - p1["delta"]]],
        fmt="D",
        color=DARK,
        ms=8,
        capsize=4,
        lw=1.6,
    )
    ax2.axhline(0, color="#333333", lw=0.9)
    ax2.set_xlim(-0.6, 1.5)
    ax2.set_xticks([])
    ax2.set_ylabel("Delta MRR vs F, 95% CI (genes)")
    ax2.set_title("Sealed P1 (pre-registered, gated)", loc="left", fontsize=10)
    ax2.text(
        0.42,
        0.45,
        f"{p1['delta']:+.4f}\n[{p1['ci95'][0]:+.4f}, {p1['ci95'][1]:+.4f}]\n\nn = {p1['n']:,} literature-onset cases\nharmed vs E0+answers {p1['harmed'] * 100:.2f}% (cap 5%)\n"
        f"P1 pass: {p1['pass']}",
        transform=ax2.transAxes,
        fontsize=7.5,
    )
    out["sealed"]["P1"] = p1

    n = len(SUBSETS)
    for i, (key, label) in enumerate(SUBSETS):
        y = n - 1 - i
        v, e = arm["vs_F"][key], arm["vs_e0"][key]
        colour, marker = (DARK, "D") if key == "lit" else (MID if "src" in key else LIGHT, "o")
        ax3.errorbar(
            v["delta"],
            y,
            xerr=[[v["delta"] - v["ci95"][0]], [v["ci95"][1] - v["delta"]]],
            fmt=marker,
            color=colour,
            capsize=3,
            ms=6,
            lw=1.3,
        )
        ax3.annotate(
            f"{v['delta']:+.4f}  (n {v['n']:,}, harmed {e['harmed'] * 100:.2f}%)",
            (v["ci95"][1], y),
            textcoords="offset points",
            xytext=(5, -3),
            fontsize=7,
        )
        out["sealed"][key] = {
            "n": v["n"],
            "delta_vs_F": v["delta"],
            "ci95": v["ci95"],
            "harmed_vs_e0": e["harmed"],
        }
    ax3.set_yticks(range(n))
    ax3.set_yticklabels([s[1] for s in SUBSETS][::-1], fontsize=8)
    ax3.axvline(0, color="#333333", lw=0.9)
    ax3.set_xlim(-0.004, 0.0215)
    ax3.set_xticks([-0.004, 0, 0.004, 0.008, 0.012])
    ax3.set_xlabel("Delta MRR vs F, 95% CI (secondaries descriptive)")
    ax3.set_title("Sealed S3-v3b-test: P1, secondaries", loc="left", fontsize=10)
    fig.suptitle(
        "EXP-B-005: F + onset 0.25 against F, Q2b interview (S3 v3b: dev 30% / test 70%)",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    save(fig, "fig_k_expb005_onset", [DEV, SEALED])
    save_data("fig_k_expb005_onset.json", out)


if __name__ == "__main__":
    main()
