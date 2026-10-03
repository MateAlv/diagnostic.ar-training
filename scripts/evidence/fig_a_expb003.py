"""Figure (a): EXP-B-003 sealed results for rr-v1[neg=0.5], from results/EXP-B-003/*report.json."""

from common import DARK, INK, MID, load, plt, save, save_data

S3 = "results/EXP-B-003/s3-v1-test__report.json"
R1 = "results/EXP-B-003/r1-v1-test__rr-v1[neg=0.5]__report.json"


def main() -> None:
    s3 = load(S3)["systems"]["rr-v1[neg=0.5]"]["vs_E0+answers"]
    r1 = load(R1)["views"]
    rows = [
        ("S3-test (sealed)\nvs E0+answers, n=9,990\nCI resamples genes", s3, DARK, "o"),
        (
            "R1-test (sealed), all view\nvs E0, n=2,548\nCI resamples publications",
            r1["all"]["vs_e0"],
            MID,
            "s",
        ),
        ("R1-test (sealed), present view\nvs E0, n=2,548", r1["present"]["vs_e0"], INK, "D"),
    ]
    out = {}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [1.25, 1]})
    for i, (label, d, colour, marker) in enumerate(rows):
        y = len(rows) - 1 - i
        ax1.errorbar(
            d["delta"],
            y,
            xerr=[[d["delta"] - d["ci95"][0]], [d["ci95"][1] - d["delta"]]],
            fmt=marker,
            color=colour,
            capsize=4,
            ms=7,
            lw=1.6,
        )
        ax1.annotate(
            f"{d['delta']:+.4f}  [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]",
            (d["delta"], y),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=7.5,
        )
        out[label.split("\n")[0]] = {
            "delta": d["delta"],
            "ci95": d["ci95"],
            "harmed": d["harmed"],
            "helped": d["helped"],
            "n": d["n"],
        }
    ax1.axvline(0, color="#333333", lw=0.9)
    ax1.set_yticks(range(len(rows)))
    ax1.set_yticklabels([r[0] for r in rows][::-1])
    ax1.set_ylim(-0.6, len(rows) - 0.3)
    ax1.set_xlabel("Delta MRR (rr-v1[neg=0.5] minus reference), 95% CI")
    ax1.set_title("Delta MRR with 95% CI", loc="left", fontsize=10)

    names = ["S3-test", "R1-test (all)"]
    ds = [s3, r1["all"]["vs_e0"]]
    xs = range(len(names))
    w = 0.36
    b1 = ax2.bar(
        [x - w / 2 for x in xs],
        [d["harmed"] * 100 for d in ds],
        w,
        color=MID,
        hatch="//",
        edgecolor=INK,
        label="harmed",
    )
    b2 = ax2.bar(
        [x + w / 2 for x in xs], [d["helped"] * 100 for d in ds], w, color=DARK, edgecolor=INK, label="helped"
    )
    for bars in (b1, b2):
        for b in bars:
            ax2.annotate(
                f"{b.get_height():.1f}%",
                (b.get_x() + b.get_width() / 2, b.get_height()),
                textcoords="offset points",
                xytext=(0, 2),
                ha="center",
                fontsize=8,
            )
    ax2.axhline(5, color=INK, ls="--", lw=0.9)
    ax2.text(-0.45, 5.5, "5% harm cap (S3 gate)", ha="left", fontsize=7.5)
    ax2.set_xticks(list(xs))
    ax2.set_xticklabels(names)
    ax2.set_ylabel("share of cases (%)")
    ax2.set_title("Harmed and helped rate", loc="left", fontsize=10)
    ax2.legend(frameon=False)
    fig.suptitle("EXP-B-003: rr-v1[neg=0.5] on sealed S3-test and R1-test", x=0.01, ha="left", fontsize=11)
    save(fig, "fig_a_expb003_sealed", [S3, R1])
    save_data("fig_a_expb003_sealed.json", out)


if __name__ == "__main__":
    main()
