"""Figure (b): simulator gate G2 metrics for UP, V03-full and candidates 1-6 (ADR-0012), one panel per metric."""

from common import DARK, INK, LIGHT, MID, load, plt, save, save_data

G6 = "results/realism/gate-v0.5.4-cand6-gonogo.json"
G3 = "results/realism/gate-v0.4-cand3-gonogo.json"
G1 = "results/realism/gate-v0.4-cand1.json"
DEV6 = "results/realism/v0.5.4-cand6.json"
METRICS = [
    ("a", "G2a: literature-panel MAE, truth layer\n(lower is better)"),
    ("b", "G2b: R1-dev mean per-gene rho\n(higher is better; dev read)"),
    ("c", "G2c: W1 distance, terms per case\nvs R1-train (lower)"),
    ("d", "G2d: classifier AUC vs R1-train\n(lower; must be <= 0.75)"),
    ("e", "G2e: |E0 MRR - 0.405|\n(lower; must be <= 0.10)"),
]


def collect() -> dict:
    g6 = load(G6)
    g3 = load(G3)
    g1 = load(G1)
    vals = {"UP": g6["baselines"]["up-graphens"], "V03-full": g6["baselines"]["v0.3-full-baseline"]}
    vals["1"] = dict(g1["candidates"]["v0.4-cand1"]["values"])
    vals["2"] = g3["secondary"]["v0.4-cand2"]
    sec = g6["secondary"]
    vals["3"] = sec["v0.4-cand3-full-nodev"]
    vals["4"] = sec["v0.5-cand4-full-nodev"]
    vals["5"] = sec["v0.5.1-cand5-full-nodev"]
    vals["6a"] = sec["v0.5.2-cand6a-full-nodev"]
    vals["6b"] = sec["v0.5.3-cand6b-full-nodev"]
    vals["6"] = dict(g6["candidates"]["v0.5.4-cand6-full-nodev"]["values"])
    vals["6"]["b"] = load(DEV6)["g2b_dev_rho"]["mean_rho"]
    vals = {k: dict(v) for k, v in vals.items()}
    vals["1"]["a"] = None
    vals["1"]["e"] = None
    return vals


def main() -> None:
    vals = collect()
    names = list(vals)
    fig, axes = plt.subplots(1, 5, figsize=(15, 4.4))
    for ax, (key, title) in zip(axes, METRICS):
        for i, n in enumerate(names):
            v = vals[n].get(key)
            if v is None:
                ax.text(
                    0.02,
                    i,
                    "n/a",
                    va="center",
                    fontsize=7,
                    color="#555555",
                    transform=ax.get_yaxis_transform(),
                )
                continue
            colour = LIGHT if n in ("UP", "V03-full") else (DARK if n == "6" else MID)
            hatch = "//" if n in ("UP", "V03-full") else None
            ax.barh(i, v, color=colour, edgecolor=INK, hatch=hatch, height=0.65)
            ax.annotate(
                f"{v:.3f}", (v, i), textcoords="offset points", xytext=(3, 0), va="center", fontsize=7
            )
        up, v03 = vals["UP"][key], vals["V03-full"][key]
        ax.axvline(up, color=INK, ls="--", lw=1)
        ax.axvline(v03, color=INK, ls=":", lw=1.3)
        if key == "d":
            ax.axvline(0.75, color=INK, ls="-", lw=1.2)
        if key == "e":
            ax.axvline(0.10, color=INK, ls="-", lw=1.2)
        ax.set_title(title, fontsize=8.5, loc="left")
        ax.set_yticks(range(len(names)))
        ax.set_yticklabels(names if ax is axes[0] else [])
        ax.invert_yaxis()
        ax.set_xlim(0, max(v for v in (vals[n].get(key) for n in names) if v is not None) * 1.2)
    axes[0].set_ylabel("dataset")
    handles = [
        plt.Line2D([], [], color=INK, ls="--", label="UP value"),
        plt.Line2D([], [], color=INK, ls=":", lw=1.3, label="V03-full value"),
        plt.Line2D([], [], color=INK, ls="-", label="absolute cap (G2d 0.75, G2e 0.10)"),
    ]
    fig.legend(handles=handles, loc="upper right", frameon=False, ncol=3, fontsize=8)
    fig.suptitle(
        "ADR-0012 gate, G2 metrics. A candidate must beat both UP and V03-full lines (G2b: exceed them)",
        x=0.01,
        ha="left",
        fontsize=10.5,
    )
    fig.text(
        0.01,
        0.06,
        "Candidate 1 was scored under the original rules (G2a emission layer, G2e target 0.512), so its G2a and G2e are not plotted. "
        "G2b exists only for UP, V03-full, 1, 2, 6 (R1-dev reads); candidate 6 G2b is the dev value. Candidates 3-6b are train-side only.",
        fontsize=6.8,
        color="#333333",
    )
    save(fig, "fig_b_simulator_gate", [G6, G3, G1, DEV6])
    save_data("fig_b_simulator_gate.json", vals)


if __name__ == "__main__":
    main()
