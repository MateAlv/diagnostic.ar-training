"""Node information content from E0's knowledge cut, HPO `phenotype.hpoa` 2025-03-03 (ADR-0019 §3).

IC(t) = ln((N + 1) / (n_t + 1)) / ln(N + 1), in [0, 1]: n_t is the number of diseases annotated with t or a
descendant of t in E0's DAG, N the number of annotated diseases. Literature negations are dropped first:
qualifier `NOT`, and frequencies 0/n and 0% (ADR-0019 §4). A term no disease reaches gets 1.

Computed from knowledge only (no patient), cached under `data/interim/v4/` keyed by the source's sha256.
"""

import csv
import re
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from diagnostic_ar_training import INTERIM_DIR
from diagnostic_ar_training.lineage.registry import Purpose, load_sources, open_source

SOURCE = "hpo_annotations_2025_03_03"
CACHE_DIR = INTERIM_DIR / "v4"
_ZERO_FRACTION = re.compile(r"^0/\d+$")
_ZERO_PERCENT = re.compile(r"^0(\.0+)?%$")


def is_negation(qualifier: str, frequency: str) -> bool:
    f = frequency.strip()
    return qualifier.strip().upper() == "NOT" or bool(_ZERO_FRACTION.match(f) or _ZERO_PERCENT.match(f))


def disease_terms(rows: Iterable[dict]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in rows:
        if is_negation(r.get("qualifier", ""), r.get("frequency", "")):
            continue
        out.setdefault(r["database_id"], set()).add(r["hpo_id"])
    return out


def read_hpoa(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        lines = (line for line in handle if not line.startswith("#"))
        return list(csv.DictReader(lines, delimiter="\t"))


def information_content(annotations: dict[str, set[str]], dag) -> np.ndarray:
    """[len(dag.node_ids)] float32, aligned with the DAG's node order."""
    n_nodes = len(dag.node_ids)
    counts = np.zeros(n_nodes, dtype=np.int64)
    for terms in annotations.values():
        reached: set[str] = set()
        for t in terms:
            if t in dag.index:
                reached.add(t)
                reached |= dag.ancestors(t)
        for t in reached:
            counts[dag.index[t]] += 1
    n = len(annotations)
    return (np.log((n + 1) / (counts + 1)) / np.log(n + 1)).astype(np.float32)


def ic_table(dag) -> np.ndarray:
    sha = load_sources()[SOURCE].sha256
    cache = CACHE_DIR / f"ic-{sha[:12]}-{len(dag.node_ids)}.npy"
    if cache.is_file():
        return np.load(cache)
    table = information_content(disease_terms(read_hpoa(open_source(SOURCE, Purpose.TRAIN))), dag)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp.npy")
    np.save(tmp, table)
    tmp.replace(cache)
    return table
