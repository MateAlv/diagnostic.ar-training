"""Shared helpers for the evidence-pack figure scripts (docs/evidence/).

Each fig_*.py reads committed result files only and writes PNG and SVG into docs/evidence/figures/.
Requires matplotlib and numpy (not in the project's pinned environment).
Run all: python scripts/evidence/make_all.py
"""

import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIG_DIR = ROOT / "docs" / "evidence" / "figures"
DATA_DIR = ROOT / "docs" / "evidence" / "data"

# Lightness-separated so the series stay distinguishable in greyscale; markers and hatches repeat the identity.
INK = "#111111"
DARK = "#1b4f8a"
MID = "#d2791f"
LIGHT = "#8c8c8c"
PALE = "#d9d9d9"

plt.rcParams.update(
    {
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#e3e3e3",
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "figure.dpi": 110,
        "svg.fonttype": "none",
    }
)


def load(rel: str):
    with open(ROOT / rel, encoding="utf-8") as fh:
        return json.load(fh)


def save(fig, name: str, sources: list[str]) -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.text(
        0.01,
        0.005,
        textwrap.fill("Source: " + "; ".join(sources), 165),
        fontsize=6.5,
        color="#555555",
        ha="left",
        va="bottom",
    )
    fig.tight_layout(rect=(0, 0.11, 1, 1))
    for ext in ("png", "svg"):
        fig.savefig(FIG_DIR / f"{name}.{ext}", dpi=170)
    plt.close(fig)
    print("wrote", FIG_DIR / f"{name}.png")


def save_data(name: str, obj) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / name, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, sort_keys=True)
        fh.write("\n")
