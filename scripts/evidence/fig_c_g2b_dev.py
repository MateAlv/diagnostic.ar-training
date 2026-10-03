"""Figure (c): G2b on R1-dev with bootstrap CIs over genes, recomputed from the per-gene rho saved in results/realism/*.json.

Uses the 38 genes scored by all four datasets; 10,000 resamples of genes, percentile intervals.
"""

import numpy as np
from common import DARK, INK, LIGHT, MID, load, plt, save, save_data

FILES = {
    "UP": "results/realism/up-graphens.json",
    "V03-full": "results/realism/v0.3-full-baseline.json",
    "Candidate 2": "results/realism/v0.4-cand2.json",
    "Candidate 6": "results/realism/v0.5.4-cand6.json",
}
SEED = 20261003
RESAMPLES = 10_000
BITACORA = {  # docs/BITACORA.md, 2026-10-03 "G2b on dev with intervals"
    "UP": (0.235, 0.147, 0.317),
    "Candidate 2": (0.193, 0.098, 0.281),
    "Candidate 6": (0.159, 0.067, 0.242),
    "V03-full": (0.095, 0.011, 0.174),
}
BITACORA_DIFF = {
    "UP": (-0.075, -0.157, 0.000),
    "Candidate 2": (-0.034, -0.089, 0.003),
    "V03-full": (0.065, 0.024, 0.110),
}


def main() -> None:
    per_gene = {}
    for name, rel in FILES.items():
        d = load(rel)["g2b_dev_rho"]["per_gene"]
        per_gene[name] = {g: v["rho"] for g, v in d.items() if v.get("rho") is not None}
    common = sorted(set.intersection(*[set(v) for v in per_gene.values()]))
    m = {k: np.array([v[g] for g in common]) for k, v in per_gene.items()}
    idx = np.random.default_rng(SEED).integers(0, len(common), (RESAMPLES, len(common)))
    boots = {k: v[idx].mean(1) for k, v in m.items()}
    res = {}
    for k, v in m.items():
        lo, hi = np.percentile(boots[k], [2.5, 97.5])
        res[k] = {"mean": float(v.mean()), "ci95": [float(lo), float(hi)]}
    diffs = {}
    for k in ("UP", "Candidate 2", "V03-full"):
        b = boots["Candidate 6"] - boots[k]
        lo, hi = np.percentile(b, [2.5, 97.5])
        diffs[k] = {"diff": float(m["Candidate 6"].mean() - m[k].mean()), "ci95": [float(lo), float(hi)]}
    save_data(
        "fig_c_g2b_dev_intervals.json",
        {
            "genes": len(common),
            "resamples": RESAMPLES,
            "seed": SEED,
            "datasets": res,
            "candidate6_minus": diffs,
            "bitacora_datasets": BITACORA,
            "bitacora_candidate6_minus": BITACORA_DIFF,
            "all_genes_mean_rho": {k: load(rel)["g2b_dev_rho"]["mean_rho"] for k, rel in FILES.items()},
        },
    )

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.8), gridspec_kw={"width_ratios": [1.3, 1]})
    order = ["UP", "Candidate 2", "Candidate 6", "V03-full"]
    style = {
        "UP": (LIGHT, "s"),
        "Candidate 2": (MID, "o"),
        "Candidate 6": (DARK, "D"),
        "V03-full": (INK, "^"),
    }
    for i, k in enumerate(order):
        y = len(order) - 1 - i
        r = res[k]
        c, mk = style[k]
        ax1.errorbar(
            r["mean"],
            y,
            xerr=[[r["mean"] - r["ci95"][0]], [r["ci95"][1] - r["mean"]]],
            fmt=mk,
            color=c,
            mec=INK,
            capsize=4,
            ms=7,
            lw=1.6,
        )
        ax1.annotate(
            f"{r['mean']:.3f} [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}]",
            (r["mean"], y),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=7.5,
        )
    ax1.set_yticks(range(len(order)))
    ax1.set_yticklabels(order[::-1])
    ax1.set_ylim(-0.6, len(order) - 0.3)
    ax1.set_xlabel("mean per-gene Spearman rho on R1-dev (38 genes), bootstrap 95% CI")
    ax1.set_title("G2b per dataset", loc="left", fontsize=10)
    ks = ["UP", "Candidate 2", "V03-full"]
    for i, k in enumerate(ks):
        y = len(ks) - 1 - i
        r = diffs[k]
        ax2.errorbar(
            r["diff"],
            y,
            xerr=[[r["diff"] - r["ci95"][0]], [r["ci95"][1] - r["diff"]]],
            fmt="o",
            color=DARK,
            mec=INK,
            capsize=4,
            ms=7,
            lw=1.6,
        )
        ax2.annotate(
            f"{r['diff']:+.3f} [{r['ci95'][0]:+.3f}, {r['ci95'][1]:+.3f}]",
            (r["diff"], y),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=7.5,
        )
    ax2.axvline(0, color="#333333", lw=0.9)
    ax2.set_yticks(range(len(ks)))
    ax2.set_yticklabels([f"vs {k}" for k in ks][::-1])
    ax2.set_ylim(-0.6, len(ks) - 0.3)
    ax2.set_xlabel("candidate 6 minus other (paired over genes), 95% CI")
    ax2.set_title("Paired differences", loc="left", fontsize=10)
    fig.suptitle("G2b on R1-dev (the last of 3 budgeted reads)", x=0.01, ha="left", fontsize=11)
    save(fig, "fig_c_g2b_dev_intervals", list(FILES.values()))


if __name__ == "__main__":
    main()
