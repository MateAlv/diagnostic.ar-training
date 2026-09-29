"""Training, re-ranking and evaluation for diagnostic.ar (see docs/INDEX.md)."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SPLITS_DIR = DATA_DIR / "splits"
MANIFESTS_DIR = DATA_DIR / "manifests"
INTERIM_DIR = DATA_DIR / "interim"
RESULTS_DIR = REPO_ROOT / "results"
DOCS_DIR = REPO_ROOT / "docs"
