"""`hpoa-recount-*`: phenotype.hpoa with held-out publications recounted from R1-train (ADR-0011 §1).

A phenotype row citing no held-out PMID is copied unchanged. The phenotype rows of a
(disease, term) that cite a held-out PMID are replaced by one row whose frequency is
`n/m` over the R1-train patients of that disease:
- `n`: patients with the term, or a descendant of it, present;
- `m`: those plus the patients who exclude it (the term itself or an ancestor excluded).

With `m < min_patients` the rows are dropped. Rows of other aspects that cite a held-out
PMID are dropped, as before (EVAL_PROTOCOL §4.1 as amended).
"""

import csv
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from diagnostic_ar_training.cohorts.schema import Case
from diagnostic_ar_training.ontology import Ontology
from diagnostic_ar_training.rerank.kb import onset_interval

COLUMNS = (
    "database_id", "disease_name", "qualifier", "hpo_id", "reference", "evidence",
    "onset", "frequency", "sex", "modifier", "aspect", "biocuration",
)  # fmt: skip
RECOUNT_EVIDENCE = "PCS"
MIN_ONSET_PATIENTS = 3
# Upper bounds (years, exclusive) of the onset class a median onset age is written as.
ONSET_CLASSES = (
    (0.0, "HP:0030674"),  # antenatal
    (1e-9, "HP:0003577"),  # congenital (onset at birth)
    (28 / 365.25, "HP:0003623"),  # neonatal
    (1.0, "HP:0003593"),  # infantile
    (5.0, "HP:0011463"),  # childhood
    (16.0, "HP:0003621"),  # juvenile
    (40.0, "HP:0011462"),  # young adult
    (60.0, "HP:0003596"),  # middle age
    (float("inf"), "HP:0003584"),  # late
)


def onset_class(years: float) -> str:
    return next(term for upper, term in ONSET_CLASSES if years < upper)


def read_hpoa(path: Path) -> tuple[list[str], list[dict]]:
    """(leading comment lines, rows as dicts in file order)."""
    comments, rows = [], []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        lines = []
        for line in handle:
            (comments if line.startswith("#") and not lines else lines).append(line)
    reader = csv.DictReader(lines, delimiter="\t", quoting=csv.QUOTE_NONE)
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(f"{path}: unexpected header {reader.fieldnames}")
    rows = [dict(r) for r in reader]
    return comments, rows


def write_hpoa(path: Path, comments: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.writelines(comments)
        handle.write("\t".join(COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(row[c] for c in COLUMNS) + "\n")


@dataclass(frozen=True)
class _Patient:
    present: frozenset[str]
    """Present terms and all their ancestors."""
    excluded: frozenset[str]
    onsets: tuple[tuple[str, float], ...]
    """(present term, onset years) for features with a recorded onset."""


def _patient(case: Case, ontology: Ontology) -> _Patient:
    present, excluded, onsets = set(), set(), []
    for t in case.present:
        if term := ontology.resolve(t):
            present |= {term, *ontology.ancestors(term)}
    for t in case.excluded:
        if term := ontology.resolve(t):
            excluded.add(term)
    for t, years, klass in case.feature_onsets:
        term = ontology.resolve(t)
        if years is None and klass and (iv := onset_interval(ontology, klass)):
            years = (iv[0] + iv[1]) / 2
        if term and years is not None:
            onsets.append((term, years))
    return _Patient(frozenset(present), frozenset(excluded), tuple(onsets))


def patients_by_disease(
    cases: list[Case], ontology: Ontology, exact_pairs: list[tuple[str, str]]
) -> dict[str, list[_Patient]]:
    """Disease id -> its R1-train patients; ORPHA ids take the patients of their exactly aligned OMIM ids."""
    out: dict[str, list[_Patient]] = defaultdict(list)
    for case in cases:
        patient = _patient(case, ontology)
        for disease_id in set(case.disease_ids):
            out[disease_id].append(patient)
    for orpha, omim in sorted(set(exact_pairs)):
        out[orpha].extend(out.get(omim, ()))
    return dict(out)


def count(term: str, patients: list[_Patient], ontology: Ontology) -> tuple[int, int]:
    """(n, m): patients with the term present, and those plus the ones who exclude it."""
    lineage = {term, *ontology.ancestors(term)}
    n = sum(term in p.present for p in patients)
    m = sum(term in p.present or bool(p.excluded & lineage) for p in patients)
    return n, m


def onset_years(term: str, patients: list[_Patient], ontology: Ontology) -> list[float]:
    """Onset of the term in each patient who reports it (or a descendant) with a feature-level onset."""
    out = []
    for p in patients:
        if term not in p.present:
            continue
        ages = [y for t, y in p.onsets if t == term or term in ontology.ancestors(t)]
        if ages:
            out.append(min(ages))
    return out


def _agreed(rows: list[dict], column: str) -> str:
    values = {r[column] for r in rows}
    return values.pop() if len(values) == 1 else ""


def recount(
    rows: list[dict],
    heldout_pmids: set[str],
    patients: dict[str, list[_Patient]],
    ontology: Ontology,
    split_id: str = "r1-v1",
    min_patients: int = 3,
    biocuration: str = "hpoa-recount",
) -> tuple[list[dict], dict]:
    """Returns (rows of the recounted file, stats with totals and per-disease counts)."""
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if row["aspect"] == "P" and set(row["reference"].split(";")) & heldout_pmids:
            groups[(row["database_id"], row["hpo_id"])].append(i)
    first_of = {idx[0]: key for key, idx in groups.items()}
    per_disease: dict[str, Counter] = defaultdict(Counter)
    totals: Counter = Counter()
    out = []
    for i, row in enumerate(rows):
        disease = row["database_id"]
        cites_heldout = bool(set(row["reference"].split(";")) & heldout_pmids)
        if not cites_heldout:
            out.append(row)
            per_disease[disease]["kept"] += 1
            continue
        if row["aspect"] != "P":
            per_disease[disease]["dropped"] += 1
            totals["rows_dropped_other_aspect"] += 1
            continue
        if i not in first_of:
            continue
        members = [rows[j] for j in groups[first_of[i]]]
        term = ontology.resolve(row["hpo_id"])
        if term is None:
            per_disease[disease]["dropped"] += len(members)
            totals["rows_dropped_unresolvable_term"] += len(members)
            continue
        n, m = count(term, patients.get(disease, []), ontology)
        if m < min_patients:
            per_disease[disease]["dropped"] += len(members)
            totals["rows_dropped_too_few_patients"] += len(members)
            continue
        ages = onset_years(term, patients[disease], ontology)
        out.append(
            {
                **row,
                "qualifier": "",
                "reference": f"R1-TRAIN:{split_id}",
                "evidence": RECOUNT_EVIDENCE,
                "onset": onset_class(statistics.median(ages)) if len(ages) >= MIN_ONSET_PATIENTS else "",
                "frequency": f"{n}/{m}",
                "sex": _agreed(members, "sex"),
                "modifier": _agreed(members, "modifier"),
                "biocuration": biocuration,
            }
        )
        per_disease[disease]["recounted"] += len(members)
        per_disease[disease]["recount_rows"] += 1
        totals["rows_recounted"] += len(members)
        totals["recount_rows_written"] += 1
        totals["recount_rows_with_onset"] += len(ages) >= MIN_ONSET_PATIENTS
    totals["rows_in"] = len(rows)
    totals["rows_out"] = len(out)
    totals["rows_kept_unchanged"] = sum(c["kept"] for c in per_disease.values())
    totals["rows_dropped"] = sum(c["dropped"] for c in per_disease.values())
    totals["phenotype_rows_citing_heldout"] = sum(len(v) for v in groups.values())
    totals["diseases_touched"] = sum(bool(c["recounted"] or c["dropped"]) for c in per_disease.values())
    touched = {
        d: {k: c[k] for k in ("kept", "recounted", "recount_rows", "dropped")}
        for d, c in sorted(per_disease.items())
        if c["recounted"] or c["dropped"]
    }
    return out, {"totals": dict(sorted(totals.items())), "per_disease": touched}


def feature_onsets(
    rows: list[dict], patients: dict[str, list[_Patient]], ontology: Ontology
) -> list[tuple[str, str, int, float, float, float]]:
    """(disease, term, patients with an onset, q25, median, q75 years) for every phenotype row's pair
    with at least MIN_ONSET_PATIENTS R1-train patients whose feature-level onset is recorded."""
    out = []
    pairs = sorted(
        {(r["database_id"], r["hpo_id"]) for r in rows if r["aspect"] == "P" and r["qualifier"] != "NOT"}
    )
    for disease, raw in pairs:
        if disease not in patients or not (term := ontology.resolve(raw)):
            continue
        ages = onset_years(term, patients[disease], ontology)
        if len(ages) >= MIN_ONSET_PATIENTS:
            q = statistics.quantiles(ages, n=4, method="inclusive")
            out.append((disease, raw, len(ages), q[0], statistics.median(ages), q[2]))
    return out


def write_onsets(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "disease_id\thpo_id\tpatients\tonset_years_q25\tonset_years_median\tonset_years_q75\n"
    body = "".join(f"{d}\t{t}\t{k}\t{a:.4f}\t{b:.4f}\t{c:.4f}\n" for d, t, k, a, b, c in rows)
    path.write_text(header + body)
