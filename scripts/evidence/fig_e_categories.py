"""Figure (e): ANALYSIS-002/003 term categories (share of present terms), real R1-train vs simulator candidates.

Two reference frames, because the analyses changed the reference (ANALYSIS-003 section 2):
 - frame 1 (ANALYSIS-002): all R1-train, categories against kb-v4; candidates 1 and 2.
 - frame 2 (ANALYSIS-003): R1-train patients whose paper HPOA does not cite, against kb-v3 (data/calib/calib-v2.targets.json);
   candidates 3, 4, 5, 6a, 6b, 6.
"""

from common import DARK, INK, LIGHT, MID, PALE, load, plt, save, save_data

CATS = ["explained", "more_specific", "related_ic_ge_2", "weak_ic_lt_2"]
LABELS = ["explained", "more specific than annotated", "related (IC >= 2)", "weak or unrelated (IC < 2)"]
COLOURS = [PALE, LIGHT, MID, DARK]
HATCH = [None, "..", "//", "xx"]
A2 = "results/analyses/ANALYSIS-002/term_categories.jsonl"
CALIB2 = "data/calib/calib-v2.targets.json"
CAND = {
    "2": "results/realism/v0.4-cand2.term-categories.json",
    "3": "results/realism/v0.4-cand3.term-categories.json",
    "4": "results/realism/v0.5-cand4.term-categories.json",
    "5": "results/realism/v0.5.1-cand5.term-categories.json",
    "6a": "results/realism/v0.5.2-cand6a.term-categories.json",
    "6b": "results/realism/v0.5.3-cand6b.term-categories.json",
    "6": "results/realism/v0.5.4-cand6.term-categories.json",
}


def frame1() -> dict:
    import json

    from common import ROOT

    rows = [json.loads(line) for line in open(ROOT / A2, encoding="utf-8")]
    out = {}
    for r in rows:
        b = r["unexplained_lca_bins_share_of_all_terms"]
        key = "R1-train (all, kb-v4)" if r["set"] == "R1-train" else "1 (1% sample)"
        out[key] = {
            "explained": r["explained"],
            "more_specific": r["descendant_of_annotated"],
            "related_ic_ge_2": b["2<=ic<4"] + b["ic>=4"],
            "weak_ic_lt_2": b["ic<2"],
        }
    out["2 (5% sample)"] = load(CAND["2"])["shares"]
    return out


def frame2() -> dict:
    c = load(CALIB2)["categories"]
    out = {"R1-train (uncited, kb-v3)": {k: c[k] for k in CATS}}
    for k in ("3", "4", "5", "6a", "6b", "6"):
        out[k] = load(CAND[k])["shares"]
    return out


def draw(ax, data: dict, title: str) -> None:
    names = list(data)
    for i, n in enumerate(names):
        left = 0.0
        for c, col, h in zip(CATS, COLOURS, HATCH):
            v = data[n][c]
            ax.barh(i, v, left=left, color=col, edgecolor=INK, hatch=h, height=0.7, lw=0.6)
            if v > 0.05:
                ax.text(
                    left + v / 2,
                    i,
                    f"{v:.3f}",
                    ha="center",
                    va="center",
                    fontsize=7,
                    color=INK,
                    bbox={"fc": "white", "ec": "none", "pad": 0.6, "alpha": 0.8},
                )
            left += v
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("share of present terms")
    ax.set_title(title, loc="left", fontsize=9.5)


def main() -> None:
    f1, f2 = frame1(), frame2()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9.5, 6.4), gridspec_kw={"height_ratios": [3, 7]})
    draw(ax1, f1, "Frame 1 (ANALYSIS-002): all R1-train patients, categories against kb-v4")
    draw(ax2, f2, "Frame 2 (ANALYSIS-003): R1-train patients whose paper HPOA does not cite, against kb-v3")
    handles = [plt.Rectangle((0, 0), 1, 1, fc=c, ec=INK, hatch=h) for c, h in zip(COLOURS, HATCH)]
    fig.legend(handles, LABELS, loc="lower center", bbox_to_anchor=(0.5, 0.07), ncol=4, frameon=False, fontsize=7.5)
    fig.suptitle(
        "Where present terms sit relative to the gene's annotations: real vs simulated",
        x=0.01,
        ha="left",
        fontsize=10.5,
    )
    save(fig, "fig_e_term_categories", [A2, CALIB2] + list(CAND.values()))
    save_data("fig_e_term_categories.json", {"frame1": f1, "frame2": f2})


if __name__ == "__main__":
    main()
