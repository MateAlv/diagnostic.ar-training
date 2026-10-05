"""Figure (h): EXP-B-004 L1 frontier. Dev: 48 L1 arms on S3-v2-dev. Sealed: the descriptive S3-v2-test points."""

import csv

from common import DARK, INK, LIGHT, MID, ROOT, load, plt, save, save_data

DEV = "results/EXP-B-004/dev-search.tsv"
SEALED = "results/EXP-B-004/sealed-analysis.json"
LIMITS = (0.05, 0.075, 0.10)
FORMS = {
    "llr": (LIGHT, "o", "llr (rr-v1 form)"),
    "gated": (MID, "s", "gated"),
    "capped": (DARK, "^", "capped"),
    "propagated": (INK, "D", "propagated"),
}
SEALED_POINTS = [
    ("F", "F (propagated k0.5 w0.5)"),
    ("rr-v1 formula on kb-v6", "rr-v1 formula, kb-v6"),
    ("frontier <=7.5% (propagated k0.8 w0.75)", "frontier 7.5% point"),
    ("frontier <=10% (capped C2 w2)", "frontier 10% point"),
]


def dev_rows():
    with open(ROOT / DEV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader((ln for ln in fh if not ln.startswith("#")), delimiter="\t"))
    return [r for r in rows if r["lever"] == "L1"]


def marks(ax):
    for x in LIMITS:
        ax.axvline(x * 100, color=INK, ls="--", lw=0.8)
        ax.text(
            x * 100 + 0.1, 1.0, f"{x * 100:g}%", transform=ax.get_xaxis_transform(), fontsize=7.5, va="top"
        )


def main() -> None:
    rows = dev_rows()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.4), sharey=True)
    dev_by_hash = {}
    out = {"dev_L1_arms": [], "sealed": {}}
    for r in rows:
        colour, marker, _ = FORMS[r["form"]]
        h, d, lo, hi = float(r["harmed"]) * 100, float(r["delta_mrr"]), float(r["ci_lo"]), float(r["ci_hi"])
        ax1.errorbar(h, d, yerr=[[d - lo], [hi - d]], fmt=marker, color=colour, ms=5, lw=0.7, capsize=1.5)
        dev_by_hash[r["config_hash"]] = (h, d, lo, hi)
        out["dev_L1_arms"].append(
            {
                "arm": r["arm_id"],
                "config": r["config_hash"],
                "delta": d,
                "ci95": [lo, hi],
                "harmed": float(r["harmed"]),
                "r1dev_pass": r["r1dev_pass"],
            }
        )
    for colour, marker, label in FORMS.values():
        ax1.plot([], [], marker, color=colour, label=label, ms=5, lw=0)
    ax1.legend(frameon=False, fontsize=7.5, loc="lower right", title="negation form", title_fontsize=8)
    marks(ax1)
    ax1.set_title("Dev (S3-v2-dev, 9,750 cases): 48 L1 arms", loc="left", fontsize=10)
    ax1.set_xlabel("harmed share vs E0+answers (%)")
    ax1.set_ylabel("Delta MRR vs E0+answers, 95% CI (genes)")

    sealed = load(SEALED)
    for key, label in SEALED_POINTS:
        s = sealed[key]
        v = s["vs_E0+answers"]
        h, d, lo, hi = v["harmed"] * 100, v["delta"], v["ci95"][0], v["ci95"][1]
        dh = dev_by_hash[s["config"]]
        ax2.plot([dh[0], h], [dh[1], d], color="#bbbbbb", lw=0.8, zorder=1)
        ax2.plot(dh[0], dh[1], "o", mfc="white", mec=LIGHT, ms=6, zorder=2)
        ax2.errorbar(h, d, yerr=[[d - lo], [hi - d]], fmt="o", color=DARK, ms=6, lw=1.3, capsize=3, zorder=3)
        ax2.annotate(label, (h, d), textcoords="offset points", xytext=(6, -11), fontsize=7.5)
        out["sealed"][key] = {
            "config": s["config"],
            "delta": d,
            "ci95": [lo, hi],
            "harmed": v["harmed"],
            "dev_delta": dh[1],
            "dev_ci95": [dh[2], dh[3]],
            "dev_harmed": dh[0] / 100,
        }
    ax2.plot([], [], "o", mfc="white", mec=LIGHT, label="same config on dev", lw=0)
    ax2.plot([], [], "o", color=DARK, label="S3-v2-test (sealed, descriptive)", lw=0)
    ax2.legend(frameon=False, fontsize=7.5, loc="lower right")
    marks(ax2)
    ax2.set_title("Sealed S3-v2-test (9,565 cases), 4 configurations", loc="left", fontsize=10)
    ax2.set_xlabel("harmed share vs E0+answers (%)")
    fig.suptitle(
        "EXP-B-004 L1: gain against harm, with the 5%, 7.5% and 10% limits (sealed panel is descriptive, no gate)",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    save(fig, "fig_h_l1_frontier", [DEV, SEALED])
    save_data("fig_h_l1_frontier.json", out)


if __name__ == "__main__":
    main()
