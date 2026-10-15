"""The hard age rule on top of v4 (P4-AGE): a gene whose earliest possible onset, per E0's knowledge, is later
than the patient's latest possible onset (plus a margin) is moved below every other gene. Unknown age and
onset change nothing.

- **Knowledge** (`age-kb/1`, `build`): per gene of E0's vocabulary, the earliest onset its knowledge is
  certain about, from E0's knowledge only (HPOA 2025-03-03, the 2025-03-03 ontology, E0's gene list and
  gene -> disease links, as `v4.addon.build_kb`; no Orphanet):
  - a disease's lower bound is the lowest `ONSET_LOWER` of its onset classes (HPOA aspect C) and of the onsets
    of its phenotype rows (HPOA's onset column; NOT and zero-frequency rows skipped), which can only lower it;
  - a disease without an onset class, or with an onset term outside `ONSET_LOWER`, has no bound;
  - a gene has a bound (`earliest_years`) only if it has diseases and **every** one has a bound: the minimum
    over its diseases.
- **Patient** (`latest_onset`): the latest age at which the patient's disease can have started, the minimum
  of the onset in years, the upper end of the onset class (`ONSET_UPPER`; open-ended classes give none),
  each per-symptom onset (years and class) and the current age. None when nothing is recorded.
- **Rule** (`AgeRule`): pure numpy, usable in production on any score vector (logits or add-on scores).
  A gene is blocked when its bound is at least `min_earliest_years` and later than the patient's latest
  onset plus `margin_years`. Blocked genes keep their order among themselves (`sexrule.block`).
- **Chosen variant** (`age-v1`, P4-AGE): only late-onset genes (`MIN_EARLIEST_YEARS`), a margin of
  `MARGIN_YEARS`, the patient's ages in years only (`ONSET_CLASSES`).
"""

import csv
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import numpy as np

from diagnostic_ar_training import INTERIM_DIR
from diagnostic_ar_training.lineage.registry import Purpose, open_source
from diagnostic_ar_training.safe import knowledge as safe_knowledge
from diagnostic_ar_training.v4.knowledge import is_negation
from diagnostic_ar_training.v4.sexrule import block

SCHEMA = "age-kb/1"
KB_KIND = "age-kb"
KB_DIR = INTERIM_DIR / "p4-age"
KB_FILE = "age-kb.json.gz"
KB_SOURCES = {
    "annotations": "hpo_annotations_2025_03_03",
    "ontology": "hpo_ontology_2025_03_03",
    "genes": "e0_genes_to_phenotype",
}
MIN_EARLIEST_YEARS = 60.0
MARGIN_YEARS = 30.0
ONSET_CLASSES = False
ONSET_ROOT = "HP:0003674"
ONSET_LOWER = safe_knowledge.HPO_ONSET_LOWER
ONSET_UPPER: dict[str, float] = {
    "HP:0030674": 0,  # antenatal
    "HP:0011460": 0,  # embryonal
    "HP:0011461": 0,  # fetal
    "HP:0034199": 0,  # late first trimester
    "HP:0034198": 0,  # second trimester
    "HP:0034197": 0,  # third trimester
    "HP:0003577": 0,  # congenital
    "HP:0003623": 28 / 365,  # neonatal
    "HP:0003593": 1,  # infantile
    "HP:0011463": 5,  # childhood
    "HP:0003621": 16,  # juvenile
    "HP:0410280": 16,  # pediatric
    "HP:0011462": 40,  # young adult
    "HP:0025708": 19,  # early young adult
    "HP:0025709": 25,  # intermediate young adult
    "HP:0025710": 40,  # late young adult
    "HP:0003596": 60,  # middle age
}


def read_onsets(path: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """(disease -> aspect C terms, disease -> onsets of its phenotype rows, disease -> name) of
    phenotype.hpoa, unmasked; phenotype rows that are NOT or zero-frequency are skipped."""
    classes: dict[str, set[str]] = {}
    rows: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for r in csv.DictReader((x for x in handle if not x.startswith("#")), delimiter="\t"):
            d = r["database_id"]
            names.setdefault(d, r["disease_name"])
            if r["aspect"] == "C":
                classes.setdefault(d, set()).add(r["hpo_id"])
            elif r["aspect"] == "P" and r["onset"] and not is_negation(r["qualifier"], r["frequency"]):
                rows.setdefault(d, set()).add(r["onset"])
    return classes, rows, names


def disease_bound(
    classes: Iterable[str], row_onsets: Iterable[str], is_onset: Callable[[str], bool]
) -> tuple[float | None, float | None, str | None]:
    """(lower bound with the rows' onsets, lower bound of the classes alone, why there is none)."""
    onset = sorted(t for t in classes if is_onset(t))
    if not onset:
        return None, None, "no_onset_class"
    if any(t not in ONSET_LOWER for t in (*onset, *row_onsets)):
        return None, None, "unknown_onset_term"
    by_class = min(ONSET_LOWER[t] for t in onset)
    return min([by_class, *(ONSET_LOWER[t] for t in row_onsets)]), by_class, None


def build(
    genes: Iterable[str],
    genes_to_disease: Mapping[str, set[str]],
    classes: Mapping[str, set[str]],
    row_onsets: Mapping[str, set[str]],
    names: Mapping[str, str],
    is_onset: Callable[[str], bool],
) -> tuple[dict, dict]:
    """(kb, stats). Every gene with diseases gets each disease's bounds and onset terms, and `earliest_years`
    when every disease has a bound (else `why`: the first disease's reason)."""
    out, used = {}, {}
    stats: Counter = Counter()
    for g in sorted(set(genes)):
        ds = sorted(genes_to_disease.get(g, set()))
        if not ds:
            stats["genes_without_diseases"] += 1
            continue
        diseases = {}
        for d in ds:
            rows = sorted(row_onsets.get(d, ()))
            lower, by_class, why = disease_bound(classes.get(d, ()), rows, is_onset)
            diseases[d] = {
                "lower_years": lower,
                "class_lower_years": by_class,
                "classes": sorted(t for t in classes.get(d, ()) if is_onset(t)),
                "row_onsets": rows,
            } | ({"why": why} if why else {})
        missing = [r["why"] for r in diseases.values() if "why" in r]
        earliest = None if missing else min(r["lower_years"] for r in diseases.values())
        record: dict = {"earliest_years": earliest}
        if missing:
            record["why"] = "unknown_onset_term" if "unknown_onset_term" in missing else "no_onset_class"
            stats[f"genes_{record['why']}"] += 1
        else:
            stats["genes_with_bound"] += 1
            stats[f"genes_bound_{record['earliest_years']:g}y"] += 1
            stats["genes_bound_lowered_by_rows"] += record["earliest_years"] < min(
                r["class_lower_years"] for r in diseases.values()
            )
        out[g] = record | {"diseases": diseases}
        used.update({d: names[d] for d in ds if d in names})
    kb = {
        "schema": SCHEMA,
        "rules": {"onset_root": ONSET_ROOT, "onset_lower_years": ONSET_LOWER},
        "genes": out,
        "disease_names": dict(sorted(used.items())),
    }
    stats["genes"] = len(set(genes))
    return kb, dict(sorted(stats.items()))


def kb_from_sources(genes: Iterable[str]) -> tuple[dict, dict, list[str]]:
    """(kb, stats, the source names read), opening only `KB_SOURCES` through the registry."""
    from diagnostic_ar_training.ontology import Ontology
    from diagnostic_ar_training.v4 import addon

    paths = {k: open_source(name, Purpose.KB) for k, name in KB_SOURCES.items()}
    onset = Ontology.from_json(paths["ontology"]).descendants(ONSET_ROOT) | {ONSET_ROOT}
    classes, rows, names = read_onsets(paths["annotations"])
    kb, stats = build(genes, addon.genes_to_disease(paths["genes"]), classes, rows, names, onset.__contains__)
    return kb, stats, list(KB_SOURCES.values())


def bounds(kb: Mapping, rows: bool = True) -> dict[str, float]:
    """gene -> earliest onset in years of an `age-kb/1` document, for the genes that have one; `rows=False`
    reads the onset classes alone."""
    if rows:
        return {g: r["earliest_years"] for g, r in kb["genes"].items() if r["earliest_years"] is not None}
    return {
        g: min(d["class_lower_years"] for d in r["diseases"].values())
        for g, r in kb["genes"].items()
        if r["earliest_years"] is not None
    }


def load_kb(kb_id: str) -> tuple[dict, str]:
    """(kb, sha256) of a verified `age-kb` artifact."""
    from diagnostic_ar_training.rerank import kb as kb_io
    from diagnostic_ar_training.v4.addon import _verified_output

    path, sha = _verified_output(kb_id, KB_KIND, KB_FILE)
    return kb_io.read(path), sha


def write_kb(kb: dict, kb_id: str) -> Path:
    from diagnostic_ar_training.rerank import kb as kb_io

    path = KB_DIR / kb_id / KB_FILE
    kb_io.write(kb, path)
    return path


def latest_onset(
    onset_years: float | None = None,
    onset_term: str | None = None,
    age_years: float | None = None,
    feature_onsets: Iterable[tuple[str, float | None, str | None]] = (),
    classes: bool = True,
) -> float | None:
    """The latest age, in years, at which the patient's disease can have started; None when unknown.
    `classes=False` reads ages in years only (no onset class)."""
    vals = [onset_years, age_years, *(y for _, y, _ in feature_onsets)]
    if classes:
        vals += [ONSET_UPPER.get(t) for t in (onset_term, *(c for _, _, c in feature_onsets)) if t]
    vals = [max(float(v), 0.0) for v in vals if v is not None and np.isfinite(v)]
    return min(vals) if vals else None


def case_latest_onset(case, classes: bool = True) -> float | None:
    """`latest_onset` of a `cohorts.schema.Case`."""
    return latest_onset(case.onset_years, case.onset_term, case.age_years, case.feature_onsets, classes)


class AgeRule:
    """Each gene's certain earliest onset over a vocabulary: `blocked(latest)` and `apply(scores, latest)`."""

    def __init__(
        self,
        gene_bounds: Mapping[str, float],
        genes: Sequence[str],
        margin_years: float = MARGIN_YEARS,
        min_earliest_years: float = MIN_EARLIEST_YEARS,
    ) -> None:
        self.genes = tuple(genes)
        self.margin_years, self.min_earliest_years = float(margin_years), float(min_earliest_years)
        earliest = np.array([gene_bounds.get(g, np.nan) for g in self.genes], dtype=np.float64)
        self.earliest = np.where(earliest >= self.min_earliest_years, earliest, np.nan)

    def blocked(self, latest: float | None) -> np.ndarray:
        """Genes that cannot have started by `latest` (+ the margin); none when `latest` is unknown."""
        if latest is None or not np.isfinite(latest):
            return np.zeros(len(self.genes), dtype=bool)
        return np.nan_to_num(self.earliest, nan=-np.inf) > max(float(latest), 0.0) + self.margin_years

    def apply(self, scores: np.ndarray, latest: float | None) -> np.ndarray:
        mask = self.blocked(latest)
        return block(scores, mask) if mask.any() else np.asarray(scores, dtype=np.float64).reshape(-1)
