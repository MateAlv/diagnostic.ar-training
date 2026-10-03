"""Figure (f): literature quality. Cross-check agreement by checker, audit verdict breakdown, error-rate and recall CIs.

Committed inputs: data/lit-extract/crosscheck/lit-extract-v1.{tsv,summary.json,adjudication.tsv},
data/lit-extract/audit/lit-extract-v1.{items,adjudication}.tsv.
The per-checker item counts (Codex high/low effort, Haiku) are not stored in committed data; they come from
docs/analyses/LIT-CROSSCHECK-v1.md and are checked against the committed totals (744 items, 715 agree, disagreements per checker).
"""

import csv
from collections import Counter
from math import sqrt

from common import DARK, INK, LIGHT, MID, PALE, ROOT, load, plt, save, save_data

XC = "data/lit-extract/crosscheck/lit-extract-v1"
AU = "data/lit-extract/audit/lit-extract-v1"
XC_ITEMS_DOC = {"Codex, high effort": 216, "Codex, low effort": 138, "Claude Haiku": 390}
REMOVED_ROWS = 16  # rows removed by the audit fixes (docs/analyses/LIT-AUDIT-v1.md, "What was fixed")


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return p, c - h, c + h


def tsv(rel: str) -> list[dict]:
    with open(ROOT / rel, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def main() -> None:
    xc_summary = load(XC + ".summary.json")
    xc_rows = tsv(XC + ".tsv")
    adj_xc = tsv(XC + ".adjudication.tsv")
    n_items, agree = len(xc_rows), sum(r["agree"] == "true" for r in xc_rows)
    assert (n_items, agree) == (xc_summary["items"], xc_summary["agree"]) == (744, 715)
    dis = Counter(r["checker"] for r in adj_xc)
    verdicts = Counter(r["verdict"] for r in adj_xc)
    codex_items = XC_ITEMS_DOC["Codex, high effort"] + XC_ITEMS_DOC["Codex, low effort"]
    assert dis["codex"] == 12 + 0 + 0 + (0)  # codex disagreements (all ours_correct)
    assert sum(XC_ITEMS_DOC.values()) == n_items

    au_items = tsv(AU + ".items.tsv")
    au_adj = tsv(AU + ".adjudication.tsv")
    rows_audited = sum(int(r["rows"]) for r in au_items)
    kinds = ("wrong_unit", "bad_row", "missed")
    table = {k: Counter(r["valid"] for r in au_adj if r["kind"] == k) for k in kinds}
    bad_rows = {
        (r["item"], r["row"])
        for r in au_adj
        if r["kind"] in ("wrong_unit", "bad_row") and r["valid"] == "yes"
    }
    missed_yes = table["missed"]["yes"]
    extracted_after = rows_audited - REMOVED_ROWS

    # checker rows: Codex disagreements are all in the first 354 by definition; split by effort is not reconstructable from files.
    xc_groups = {
        "Codex, high effort": (211, 216),
        "Codex, low effort": (131, 138),
        "Codex, all": (342, codex_items),
        "Claude Haiku": (373, 390),
        "All checkers": (715, 744),
    }
    assert xc_groups["Codex, all"][0] == codex_items - dis["codex"]
    assert xc_groups["Claude Haiku"][0] == 390 - dis["haiku"]
    rates = {
        "Cross-check, error (1/744)": (1, 744),
        "Cross-check, upper bound (3/744)": (3, 744),
        "Audit, items 1-83 (15/814)": (15, 814),
        "Audit, all 98 sources": (len(bad_rows), rows_audited),
        "Audit, if all 27 category flags valid": (len(bad_rows) + 27, rows_audited),
    }
    recall = {
        "Audit recall, all 98 (after removals)": (extracted_after, extracted_after + missed_yes),
        "Audit recall, items 1-83": (799, 799 + 52),
    }

    fig, axes = plt.subplots(2, 2, figsize=(12, 7.4))
    ax = axes[0, 0]
    names = list(xc_groups)
    for i, n in enumerate(names):
        k, m = xc_groups[n]
        p, lo, hi = wilson(k, m)
        ax.errorbar(
            p * 100,
            len(names) - 1 - i,
            xerr=[[(p - lo) * 100], [(hi - p) * 100]],
            fmt="o",
            color=DARK if "Haiku" in n else MID,
            mec=INK,
            capsize=4,
            ms=7,
        )
        ax.annotate(
            f"{k}/{m} = {p * 100:.1f}%",
            (p * 100, len(names) - 1 - i),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7.5,
        )
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names[::-1])
    ax.set_xlim(88, 100)
    ax.set_xlabel("agreement with our row (%), Wilson 95% CI")
    ax.set_title("Cross-check agreement by checker (744 rows)", loc="left", fontsize=9.5)

    ax = axes[0, 1]
    cols = {"yes": (DARK, None, "valid (real error / would extract)"), "no": (PALE, "//", "not valid")}
    for i, k in enumerate(kinds):
        left = 0
        for v in ("yes", "no"):
            c, h, lab = cols[v]
            n = table[k][v]
            ax.barh(
                len(kinds) - 1 - i,
                n,
                left=left,
                color=c,
                hatch=h,
                edgecolor=INK,
                label=lab if i == 0 else None,
            )
            if n >= 8:
                ax.text(
                    left + n / 2,
                    len(kinds) - 1 - i,
                    str(n),
                    ha="center",
                    va="center",
                    fontsize=8,
                    bbox={"fc": "white", "ec": "none", "pad": 0.5, "alpha": 0.8},
                )
            left += n
    ax.set_yticks(range(len(kinds)))
    ax.set_yticklabels(["wrong_unit", "bad_row", "missed (recall only)"][::-1])
    ax.set_xlabel("audit issues (265 total, adjudicated; wrong_unit: 1 valid, 5 not valid)")
    ax.set_title("Audit verdicts by issue kind (98 sources)", loc="left", fontsize=9.5)
    ax.legend(frameon=False, fontsize=8, loc="upper right")

    ax = axes[1, 0]
    names = list(rates)
    for i, n in enumerate(names):
        k, m = rates[n]
        p, lo, hi = wilson(k, m)
        ax.errorbar(
            p * 100,
            len(names) - 1 - i,
            xerr=[[(p - lo) * 100], [(hi - p) * 100]],
            fmt="s" if "Audit" in n else "o",
            color=INK if "Audit" in n else LIGHT,
            mec=INK,
            capsize=4,
            ms=7,
        )
        ax.annotate(
            f"{p * 100:.2f}% [{lo * 100:.2f}, {hi * 100:.2f}]",
            (p * 100, len(names) - 1 - i),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7.5,
        )
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names[::-1], fontsize=8)
    ax.set_xlabel("row error rate (%), Wilson 95% CI")
    ax.set_title("Row error rate", loc="left", fontsize=9.5)

    ax = axes[1, 1]
    names = list(recall)
    for i, n in enumerate(names):
        k, m = recall[n]
        p, lo, hi = wilson(k, m)
        ax.errorbar(
            p * 100,
            len(names) - 1 - i,
            xerr=[[(p - lo) * 100], [(hi - p) * 100]],
            fmt="D",
            color=MID,
            mec=INK,
            capsize=4,
            ms=7,
        )
        ax.annotate(
            f"{p * 100:.1f}% [{lo * 100:.1f}, {hi * 100:.1f}]",
            (p * 100, len(names) - 1 - i),
            textcoords="offset points",
            xytext=(0, 8),
            ha="center",
            fontsize=7.5,
        )
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names[::-1], fontsize=8)
    ax.set_ylim(-0.6, len(names) - 0.3)
    ax.set_xlim(90, 97)
    ax.set_xlabel("rough recall (%), Wilson 95% CI (floor on the miss rate)")
    ax.set_title("Recall estimate", loc="left", fontsize=9.5)

    fig.suptitle(
        "Literature extraction quality: blind cross-check and full-source audit",
        x=0.01,
        ha="left",
        fontsize=11,
    )
    save(
        fig,
        "fig_f_literature_quality",
        [
            XC + ".tsv",
            XC + ".adjudication.tsv",
            XC + ".summary.json",
            AU + ".items.tsv",
            AU + ".adjudication.tsv",
            "per-checker item counts: docs/analyses/LIT-CROSSCHECK-v1.md",
        ],
    )
    save_data(
        "fig_f_literature_quality.json",
        {
            "crosscheck": {
                k: {"agree": a, "n": m, "wilson95": wilson(a, m)} for k, (a, m) in xc_groups.items()
            },
            "crosscheck_disagreements_by_checker": dict(dis),
            "crosscheck_verdicts": dict(verdicts),
            "audit_verdicts": {k: dict(v) for k, v in table.items()},
            "audit_rows_audited": rows_audited,
            "audit_distinct_wrong_rows": len(bad_rows),
            "audit_removed_rows": REMOVED_ROWS,
            "rates": {k: {"k": a, "n": m, "wilson95": wilson(a, m)} for k, (a, m) in rates.items()},
            "recall": {k: {"k": a, "n": m, "wilson95": wilson(a, m)} for k, (a, m) in recall.items()},
        },
    )


if __name__ == "__main__":
    main()
